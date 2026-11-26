"""Build the warehouse: load catalogues and vintages, run dbt, gate, swap in.

A build never touches the live warehouse. It writes a new file under
warehouse/builds/, runs the dbt models and tests and the Python gates
against it, and only if all of them pass points warehouse/CURRENT at the
new file. The app follows CURRENT, so it never sees a half-built warehouse,
and a failed build leaves the previous one in place.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import duckdb

from worldmodel_contract import SCHEMA_VERSION, catalogue
from worldmodel_contract.schema import TABLES
from worldmodel_data import (__version__, cities, crowd_tables, episodes, gates, history, hospitals, layer_tables, nature_tables, network_tables,
                             osint_tables, port_pressure, stepcache)
from worldmodel_data.config import Paths
from worldmodel_data.vintage_store import (CITY_COLUMNS, CITY_VALUE_COLUMNS, EVENT_COLUMNS, HISTORY_COLUMNS, LAYER_COLUMNS, PLACE_COLUMNS, TEXT_COLUMNS,
                                          VintageStore, now_utc)

log = logging.getLogger(__name__)

DBT_DIR = Path(str(resources.files("worldmodel_data") / "dbt"))
KEEP_BUILDS = 3


class BuildFailed(RuntimeError):
    def __init__(self, message: str, report: Path | None = None, failures: list[dict] | None = None):
        super().__init__(message)
        self.report = report
        self.failures = failures or []  # the failed checks, for the refresh log and the app's Problems list


@dataclass
class BuildResult:
    build_id: str
    path: Path
    report: Path
    checks: list[gates.Check] = field(default_factory=list)


def inputs_hash(paths: Paths, manifests=None) -> str:
    """What a build reads: every stored vintage (and how it was staged), the code and its lists,
    and the year (the map layer counts are dated by it). The same hash means the same warehouse."""
    manifests = VintageStore(paths).manifests() if manifests is None else manifests
    stored = sorted((m.source_id, m.vintage, m.sha256, m.stage_version, m.row_count) for m in manifests)
    return stepcache.key("build", SCHEMA_VERSION, now_utc().year, stored)


def unchanged_since(paths: Paths) -> str | None:
    """The live build's id when it was made from exactly what a build would read now, else None."""
    current = paths.current_build()
    if current is None:
        return None
    try:
        con = duckdb.connect(str(current), read_only=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        finally:
            con.close()
    except (duckdb.Error, OSError):
        return None
    return meta.get("build_id") if meta.get("inputs") and meta.get("inputs") == inputs_hash(paths) else None


def build(paths: Paths, allow_shrink: bool = False, reuse: bool = True) -> BuildResult:
    problems = catalogue.validate()
    if problems:
        raise BuildFailed("catalogue problems:\n  " + "\n  ".join(problems))

    store = VintageStore(paths)
    manifests = store.manifests()
    if not manifests:
        raise BuildFailed(f"no vintages under {paths.vintages}; run `worldmodel-data fetch <source>` first")

    started = now_utc()
    build_id = started.strftime("%Y%m%dT%H%M%SZ")
    inputs = inputs_hash(paths, manifests)
    cache = stepcache.StepCache(paths.builds / "step_cache", on=reuse)
    paths.builds.mkdir(parents=True, exist_ok=True)
    paths.reports.mkdir(parents=True, exist_ok=True)
    tmp = paths.builds / f"{build_id}.duckdb.tmp"
    final = paths.builds / f"{build_id}.duckdb"
    report_path = paths.reports / f"{build_id}.md"
    compact = paths.builds / f"{build_id}.duckdb.compact"
    tmp.unlink(missing_ok=True)

    try:
        con = duckdb.connect(str(tmp))
        try:
            left_out = _load_sources(con, paths, manifests, cache)
        finally:
            con.close()

        dbt_ok, checks = _run_dbt(tmp)

        con = duckdb.connect(str(tmp))
        try:
            if dbt_ok:  # the Python gates read tables dbt skips once a test fails
                found = episodes.compute(con)
                checks.append(gates.Check("episodes:computed", "episodes", "info",
                                          f"{found} recessions, booms, inflation spikes and debt surges worked out "
                                          "from the data (rules in episode_rules.yaml)"))
                n_cities, matched, missed, examples = cities.compute(con)
                if n_cities or matched or missed:
                    checks.append(gates.Check("cities:matched", "cities", "info",
                                              f"{n_cities:,} cities; {matched:,} city figures matched to one"
                                              + (f"; {missed:,} places matched no city" if missed else ""), examples))
                n_places, placed = cities.compute_places(con)
                if n_places:
                    checks.append(gates.Check("places:matched", "places", "info",
                                              f"{n_places:,} metro systems, universities and companies; "
                                              f"{placed:,} matched to a city"))
                n_long, n_pol, n_hev = history.compute(con)
                if n_long or n_pol or n_hev:
                    checks.append(gates.Check("history:loaded", "history", "info",
                                              f"Long history: {n_long:,} long-run figures, {n_pol:,} border shapes, "
                                              f"{n_hev:,} events far back"))
                nat = nature_tables.compute(con)
                if any(nat.values()):
                    checks.append(gates.Check("nature:loaded", "nature", "info",
                                              f"Pollution and nature: {nat['zone_grids']} climate zone maps, "
                                              f"{nat['protected_areas']:,} protected areas, {nat['species_status']:,} "
                                              f"species by name, {nat['pest_presence']:,} pest records"))
                net = network_tables.compute(con)
                if any(net.values()):
                    checks.append(gates.Check("networks:loaded", "networks", "info",
                                              f"Transport and networks: {net['geo_features']:,} rivers, basins, waterways, "
                                              f"cables and pipelines, {net['port_traffic']:,} port months, "
                                              f"{net['port_daily']:,} port days, {net['port_links']:,} port links, {net['port_goods']:,} goods-by-port rows, "
                                              f"{net['chokepoint_traffic']:,} chokepoint days, {net['airport_traffic']:,} airport years"))
                try:
                    pp = port_pressure.compute(con, cache)
                except Exception as exc:  # noqa: BLE001 -- a slip here must not stop the build
                    log.warning("port pressure left out of this build: %s", exc)
                    for t in ("traffic_weekly", "traffic_impacts"):
                        con.execute(f"DROP TABLE IF EXISTS {t}")
                    con.execute(port_pressure.WEEKLY_DDL)
                    con.execute(port_pressure.IMPACTS_DDL)
                    pp = {}
                if any(pp.values()):
                    checks.append(gates.Check("port_pressure:computed", "networks", "info",
                                              f"Port pressure: {pp['traffic_weekly']:,} port and chokepoint weeks, "
                                              f"{pp['traffic_impacts']:,} event impacts"))
                crw = crowd_tables.compute(con)
                if any(crw.values()):
                    checks.append(gates.Check("crowd:loaded", "crowd", "info",
                                              f"Crowd forecasts: {crw['crowd_questions']:,} questions, {crw['crowd_points']:,} "
                                              f"saved chances, {crw['crowd_comments']:,} comments, {crw['crowd_mine']:,} of your "
                                              f"forecasts; {crw['conflict_forecasts']:,} ViEWS country months"))
                pdt = crowd_tables.compute_pundits(con)
                if any(pdt.values()):
                    checks.append(gates.Check("pundits:loaded", "crowd", "info",
                                              f"Pundits: {pdt['pundits']:,} forecasters, {pdt['pundit_calls']:,} calls "
                                              "from saved Prediction Archive pages"))
                osn = osint_tables.compute(con)
                if any(osn.values()):
                    checks.append(gates.Check("osint:loaded", "osint", "info",
                                              f"OSINT detail: {osn['conflict_events']:,} located events, {osn['war_losses']:,} loss "
                                              f"totals, {osn['war_areas']:,} front-line days, {osn['sanction_listings']:,} sanctions "
                                              f"listings, {osn['military_strength']:,} military figures, {osn['arms_deals']:,} arms deals"))
                lay = layer_tables.compute(con)
                if lay:
                    checks.append(gates.Check("layer_items:loaded", "map layers", "info",
                                              f"Map layer details: {sum(lay.values()):,} items in {len(lay)} layers "
                                              f"({', '.join(f'{k} {v:,}' for k, v in sorted(lay.items()))})"))
                checks += gates.run(con, previous=paths.current_build(), allow_shrink=allow_shrink, shrink_ok=left_out)
            if cache.reused:
                checks.append(gates.Check("build:reused", "build", "info",
                                          "Unchanged since the last build, so reused instead of worked out again: "
                                          + ", ".join(cache.reused)))
            _finish(con, build_id, started, checks, inputs)
            failed = [c for c in checks if c.status == "fail"]
            if not failed and dbt_ok:
                _compact(con, compact)
        finally:
            con.close()
        if failed or not dbt_ok:
            kept = paths.builds / f"{build_id}.failed.duckdb"
            try:
                os.replace(tmp, kept)
            except OSError:  # Windows can hold the file a moment after closing: report on it where it is
                kept = tmp
            gates.write_report(report_path, build_id, checks, kept)
            failures = [{"check_id": c.check_id, "kind": c.kind, "detail": c.detail, "examples": c.examples[:12]}
                        for c in checks if c.status == "fail"]
            raise BuildFailed(f"{len(failures)} validation gate(s) failed; the live warehouse is unchanged. "
                              f"Report: {report_path}. Failed build kept for inspection: {kept}", report_path, failures)
        gates.write_report(report_path, build_id, checks, final)
    except BuildFailed:
        raise
    except Exception:
        for f in (tmp, compact):
            try:
                f.unlink(missing_ok=True)
            except OSError:  # locked on Windows: keep the error that stopped the build, not this one
                pass
        raise

    os.replace(compact, final)
    try:
        tmp.unlink()
    except OSError:  # Windows keeps it locked until the process exits
        pass
    _point_current(paths, final.name)
    _prune(paths)
    log.info("build %s is live: %s", build_id, final)
    return BuildResult(build_id, final, report_path, checks)


def _load_sources(con: duckdb.DuckDBPyConnection, paths: Paths, manifests, cache: stepcache.StepCache = stepcache.OFF) -> set[str]:
    """Copy the contract catalogues and every staged vintage into schema src. Returns the
    sources deliberately left out of this build (their lost rows are a warning, not a failure)."""
    con.execute("CREATE SCHEMA src")
    cat = catalogue.CATALOGUE_DIR
    for name in ("entities", "entity_codes", "memberships", "successions", "subdivisions"):
        cols = TABLES[name].columns
        casts = ", ".join(f"CAST(nullif({c}, '') AS {t}) AS {c}" for c, t in cols.items())
        con.execute(f"CREATE TABLE src.{name} AS SELECT {casts} FROM "
                    f"read_csv('{(cat / f'{name}.csv').as_posix()}', header = true, all_varchar = true)")
    # The curated notable episodes (dates and descriptions typed from the sources linked on each row).
    cols = {"event_key": "VARCHAR", "entity_id": "VARCHAR", "subkind": "VARCHAR", "title": "VARCHAR",
            "start_date": "DATE", "end_date": "DATE", "precision": "VARCHAR", "size": "DOUBLE", "size_unit": "VARCHAR",
            "url": "VARCHAR", "detail": "VARCHAR"}
    casts = ", ".join(f"CAST(nullif({c}, '') AS {t}) AS {c}" for c, t in cols.items())
    con.execute(f"CREATE TABLE src.notable_episodes AS SELECT {casts} FROM "
                f"read_csv('{(cat / 'notable_episodes.csv').as_posix()}', header = true, all_varchar = true)")

    latest = {}
    for m in manifests:
        latest[m.source_id] = m  # manifests are sorted by retrieval time
    # Memberships a source lists itself (World Bank income groups), for groups the contract
    # has but does not list members of.
    known = {r[0] for r in con.execute("SELECT entity_id FROM src.entities").fetchall()}
    listed = {r[0] for r in con.execute("SELECT DISTINCT group_id FROM src.memberships").fetchall()}
    for m in latest.values():
        path = paths.vintages / m.source_id / m.vintage.replace("/", "_") / "memberships.json"
        if not path.exists():
            continue
        rows = [r for r in json.loads(path.read_text(encoding="utf-8"))
                if r["group_id"] in known and r["member_id"] in known and r["group_id"] not in listed]
        cols = list(TABLES["memberships"].columns)
        con.executemany(f"INSERT INTO src.memberships ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [[r.get(c) or None for c in cols] for r in rows])
        listed |= {r["group_id"] for r in rows}
    inds = all_indicators(paths, latest.values())
    con.execute(_create("indicators"))
    con.executemany(f"INSERT INTO src.indicators VALUES ({', '.join('?' * len(TABLES['indicators'].columns))})", [
        (i.id, i.name, i.description, "|".join(i.synonyms), i.domain, i.unit, i.decimals, i.frequency,
         "|".join(i.breakdowns), i.aggregation.method, i.aggregation.weight, i.aggregation.numerator,
         i.aggregation.denominator, i.aggregation.multiplier, i.bounds[0], i.bounds[1], i.default_on) for i in inds])
    con.execute(_create("indicator_sources"))
    con.executemany("INSERT INTO src.indicator_sources VALUES (?, ?, ?, ?, ?, ?)", [
        (i.id, s.source_id, s.series, s.scale, rank, s.notes) for i in inds for rank, s in enumerate(i.sources, 1)])
    con.execute(_create("sources"))
    con.executemany(f"INSERT INTO src.sources VALUES ({', '.join('?' * len(TABLES['sources'].columns))})", [
        (s.id, s.name, s.short_name, s.publisher, s.url, s.licence, s.licence_url, s.commercial_use, s.cadence,
         s.attribution, s.status, s.default_rank) for s in catalogue.sources().values()])

    con.execute(_create("vintages"))
    con.executemany("INSERT INTO src.vintages VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (m.source_id, m.vintage, m.release, m.retrieved_at, m.sha256, m.row_count, m.origin,
         latest[m.source_id].vintage == m.vintage) for m in manifests])

    files = [(paths.vintages / m.source_id / m.vintage.replace("/", "_") / "observations.parquet").as_posix()
             for m in manifests]
    file_list = ", ".join(f"'{f}'" for f in files)
    con.execute(f"CREATE TABLE src.raw_observations AS SELECT * FROM read_parquet([{file_list}], union_by_name = true)")

    # Text (Factbook fields, Wikidata facts), dated events and map layers: the latest vintage of each source only.
    for table, file, columns in (("raw_texts", "texts.parquet", TEXT_COLUMNS), ("raw_events", "events.parquet", EVENT_COLUMNS),
                                 ("raw_layers", "layers.parquet", LAYER_COLUMNS), ("raw_cities", "cities.parquet", CITY_COLUMNS),
                                 ("raw_city_values", "city_values.parquet", CITY_VALUE_COLUMNS),
                                 ("raw_places", "places.parquet", PLACE_COLUMNS),
                                 *((f"raw_{t}", f"{t}.parquet", cols) for t, cols in HISTORY_COLUMNS.items())):
        found = [(paths.vintages / m.source_id / m.vintage.replace("/", "_") / file).as_posix() for m in latest.values()]
        found = [f for f in found if Path(f).exists()]
        con.execute(f"CREATE TABLE src.{table} ({', '.join(f'{c} {t}' for c, t in columns.items())})")
        if found:
            con.execute(f"INSERT INTO src.{table} BY NAME SELECT * FROM read_parquet([{', '.join(repr(f) for f in found)}], "
                        "union_by_name = true)")
    # One Hospitals layer from every hospital list, each hospital once.
    try:
        hospitals.prepare(con, cache)
    except Exception as exc:  # noqa: BLE001 - a failed merge leaves the lists' own layers; the build goes on
        log.warning("hospitals: could not merge the hospital lists (%s); each list's layer is kept as it is", exc)
    # Every dot layer's items with a country, and the map_layers indicators (before dbt, so blocs get them too).
    # A slip here must not stop the build: the layers' details pages are left empty instead.
    try:
        layer_tables.prepare(con, paths.raw, cache=cache)
    except Exception as exc:  # noqa: BLE001
        log.warning("map layer details left out of this build: %s", exc)
        con.execute("DROP TABLE IF EXISTS src.raw_layer_items")
        src_id = layer_tables.spec.SOURCE_ID
        # By the ids the layers give (indicators may be written before their indicator_sources rows).
        ids = [i["id"] for i in layer_tables.spec.indicators()]
        con.execute("DELETE FROM src.indicators WHERE indicator_id IN "
                    "(SELECT indicator_id FROM src.indicator_sources WHERE source_id = ?) OR list_contains(?, indicator_id)",
                    [src_id, ids])
        for t in ("raw_observations", "indicator_sources", "vintages"):
            con.execute(f"DELETE FROM src.{t} WHERE source_id = ?", [src_id])
        # Its figures are gone from this build on purpose: that must not fail the shrinkage check.
        return {src_id}
    return set()


def all_indicators(paths: Paths, latest) -> list:
    """The contract's indicators, then those the latest vintage of each source
    lists itself (indicators.json beside its observations), leaving out any whose
    source series the contract already covers. A listed indicator whose id is
    already known (the Factbook's population, say) adds its source to that one,
    after the sources it has. Sources are taken in their default rank order."""
    inds = {i.id: i for i in catalogue.indicators().values()}
    mapped = {(s.source_id, s.series) for i in inds.values() for s in i.sources}
    rank = {k: v.default_rank for k, v in catalogue.sources().items()}
    for m in sorted(latest, key=lambda m: (rank.get(m.source_id, 99), m.source_id)):
        for i in catalogue.source_indicators(paths.vintages / m.source_id / m.vintage.replace("/", "_") / "indicators.json"):
            new = [s for s in i.sources if (s.source_id, s.series) not in mapped]
            if not new:
                continue
            mapped |= {(s.source_id, s.series) for s in new}
            if i.id in inds:
                have = inds[i.id]
                inds[i.id] = have.model_copy(update={"sources": [*have.sources, *new]})
            else:
                inds[i.id] = i
    return with_source_in_shared_names(list(inds.values()))


def with_source_in_shared_names(inds: list) -> list:
    """Two sources can give the same name to different series (OWID's coal production
    in TWh, the Factbook's in tonnes). Where a name is shared, each one gets its main
    source after it, "Coal production (CIA Factbook)", and its unit too if that is
    not enough to tell them apart."""
    short = {k: v.short_name for k, v in catalogue.sources().items()}

    def tag(i, unit=False):
        src = short.get(i.sources[0].source_id, i.sources[0].source_id) if i.sources else ""
        return ", ".join(x for x in (src, i.unit if unit else "") if x)

    def shared(key) -> set[str]:
        n: dict[str, int] = {}
        for i in inds:
            n[key(i)] = n.get(key(i), 0) + 1
        return {k for k, c in n.items() if c > 1}

    names = shared(lambda i: i.name.lower())
    tags = shared(lambda i: f"{i.name.lower()}|{tag(i)}")
    return [i.model_copy(update={"name": f"{i.name} ({tag(i, f'{i.name.lower()}|{tag(i)}' in tags)})"})
            if i.name.lower() in names else i for i in inds]


def _create(name: str) -> str:
    cols = ", ".join(f"{c} {t}" for c, t in TABLES[name].columns.items())
    return f"CREATE TABLE src.{name} ({cols})"


def _run_dbt(db_path: Path) -> tuple[bool, list[gates.Check]]:
    from dbt.cli.main import dbtRunner

    # On Windows dbt can still hold its log file open when the run returns, so a
    # failed clean-up of the scratch folder must not fail the build.
    with tempfile.TemporaryDirectory(prefix="worldmodel-dbt-", ignore_cleanup_errors=True) as work:
        os.environ["WM_DUCKDB_PATH"] = str(db_path)
        args = ["build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR),
                "--target-path", str(Path(work) / "target"), "--log-path", str(Path(work) / "logs"),
                "--quiet", "--no-use-colors", "--no-send-anonymous-usage-stats"]
        res = dbtRunner().invoke(args)
        checks = []
        failing_sql = {}
        for r in (res.result or []):
            node = r.node
            if node.resource_type != "test":
                if str(r.status) == "error":
                    checks.append(gates.Check(f"dbt:{node.name}", "dbt_model", "fail", r.message or "model failed"))
                continue
            status = {"pass": "pass", "warn": "warn", "skipped": "skip"}.get(str(r.status), "fail")
            detail = r.message or ""
            if r.failures:
                detail = f"{r.failures} failing row(s)"
            check = gates.Check(f"dbt:{node.name}", "dbt_test", status, detail)
            if status == "fail" and getattr(node, "compiled_code", None):
                failing_sql[id(check)] = node.compiled_code
            checks.append(check)
        if res.exception:
            checks.append(gates.Check("dbt:run", "dbt_model", "fail", str(res.exception)))
    if failing_sql:
        _sample_failures(db_path, [c for c in checks if id(c) in failing_sql], failing_sql)
    return bool(res.success), checks


MAX_GROUPS = 12  # measures listed per failed check; the rest are counted


def _sample_failures(db_path: Path, checks: list[gates.Check], sql: dict[int, str], n: int = 25) -> None:
    """Attach the first failing rows of each failed dbt test, so the report shows what broke."""
    con = duckdb.connect(str(db_path))  # same settings as dbt's own connection, which may still be open
    try:
        for c in checks:
            try:
                cur = con.execute(f"SELECT * FROM ({sql[id(c)]}) LIMIT {n}")
                cols = [d[0] for d in cur.description]
                c.examples = [", ".join(f"{k}={_fmt(v)}" for k, v in zip(cols, row)) for row in cur.fetchall()]
                if {"entity_id", "indicator_id", "period_start"} <= set(cols):  # every failure, one line per measure
                    src = "source_id" if "source_id" in cols else "''"
                    groups = con.execute(f"""SELECT {src}, indicator_id, count(DISTINCT entity_id), count(*),
                        min(year(period_start)), max(year(period_start)),
                        list(DISTINCT entity_id ORDER BY entity_id)[1:3]
                        FROM ({sql[id(c)]}) GROUP BY ALL ORDER BY 4 DESC, 1, 2""").fetchall()
                    lines = []
                    for source, ind, places, k, lo, hi, first in groups[:MAX_GROUPS]:
                        more = f" and {places - len(first)} more" if places > len(first) else ""
                        span = str(lo) if lo == hi else f"{lo}-{hi}"
                        lines.append(f"{(source + ' ') if source else ''}{ind}: {k:,} row(s) in {places:,} place(s) "
                                     f"({', '.join(first)}{more}), {span}")
                    if len(groups) > MAX_GROUPS:
                        lines.append(f"... and {len(groups) - MAX_GROUPS} more measure(s)")
                    c.examples = lines + ["", "First rows:"] + c.examples[:3]
            except duckdb.Error as exc:
                c.examples = [f"(could not list the failing rows: {exc})"]
    finally:
        con.close()


def _fmt(v) -> str:
    return f"{v:,.6g}" if isinstance(v, float) else str(v)


def _finish(con: duckdb.DuckDBPyConnection, build_id: str, started, checks: list[gates.Check], inputs: str = "") -> None:
    if not any(c.status == "fail" for c in checks):  # a failed build keeps them for debugging
        con.execute("DROP SCHEMA IF EXISTS src CASCADE")
        con.execute("DROP SCHEMA IF EXISTS int CASCADE")
    con.execute("CREATE OR REPLACE TABLE build_checks (check_id VARCHAR, kind VARCHAR, status VARCHAR, detail VARCHAR)")
    con.executemany("INSERT INTO build_checks VALUES (?, ?, ?, ?)",
                    [(c.check_id, c.kind, c.status, c.detail) for c in checks])
    # dbt makes `vintages`; when dbt stopped before making it, read the loaded copy instead, so the
    # failed build still gets its report (with dbt's own error) rather than a missing-table error.
    try:
        latest = con.execute("SELECT source_id, vintage FROM vintages WHERE is_latest ORDER BY 1").fetchall()
    except duckdb.CatalogException:
        try:
            latest = con.execute("SELECT source_id, vintage FROM src.vintages WHERE is_latest ORDER BY 1").fetchall()
        except duckdb.CatalogException:
            latest = []
    meta = {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "built_at": started.isoformat(),
        "builder": f"worldmodel-data {__version__}",
        "vintages": json.dumps([list(r) for r in latest]),
        "inputs": inputs,  # inputs_hash(): a refresh with nothing new leaves this build as it is
    }
    con.execute("CREATE OR REPLACE TABLE meta (key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
    con.execute("CHECKPOINT")


def _compact(con: duckdb.DuckDBPyConnection, dest: Path) -> None:
    """Copy the build into a fresh file: dropping the build-only schemas leaves free blocks behind."""
    dest.unlink(missing_ok=True)
    db = con.execute("SELECT current_database()").fetchone()[0]
    con.execute(f"ATTACH '{dest.as_posix()}' AS compact")
    con.execute(f'COPY FROM DATABASE "{db}" TO compact')
    con.execute("DETACH compact")


def _point_current(paths: Paths, filename: str) -> None:
    tmp = paths.current_pointer.with_suffix(".tmp")
    tmp.write_text(filename + "\n")
    os.replace(tmp, paths.current_pointer)


def _prune(paths: Paths) -> None:
    """Keep the newest few builds; skip any file still open elsewhere (Windows)."""
    builds = sorted(p for p in paths.builds.glob("*.duckdb") if not p.name.endswith(".failed.duckdb"))
    failed = sorted(paths.builds.glob("*.failed.duckdb"))
    for old in builds[:-KEEP_BUILDS] + failed[:-1]:
        try:
            old.unlink()
            (old.with_suffix(".duckdb.wal")).unlink(missing_ok=True)
        except OSError:
            pass


def publish(paths: Paths, dest: Path) -> Path:
    """Copy the live build to dest, for example the app's sample warehouse."""
    current = paths.current_build()
    if current is None:
        raise BuildFailed("no live build to publish; run `worldmodel-data build` first")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(current, dest)
    return dest
