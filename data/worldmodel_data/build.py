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
from worldmodel_data import __version__, gates
from worldmodel_data.config import Paths
from worldmodel_data.vintage_store import VintageStore, now_utc

log = logging.getLogger(__name__)

DBT_DIR = Path(str(resources.files("worldmodel_data") / "dbt"))
KEEP_BUILDS = 3


class BuildFailed(RuntimeError):
    def __init__(self, message: str, report: Path | None = None):
        super().__init__(message)
        self.report = report


@dataclass
class BuildResult:
    build_id: str
    path: Path
    report: Path
    checks: list[gates.Check] = field(default_factory=list)


def build(paths: Paths, allow_shrink: bool = False) -> BuildResult:
    problems = catalogue.validate()
    if problems:
        raise BuildFailed("catalogue problems:\n  " + "\n  ".join(problems))

    store = VintageStore(paths)
    manifests = store.manifests()
    if not manifests:
        raise BuildFailed(f"no vintages under {paths.vintages}; run `worldmodel-data fetch <source>` first")

    started = now_utc()
    build_id = started.strftime("%Y%m%dT%H%M%SZ")
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
            _load_sources(con, paths, manifests)
        finally:
            con.close()

        dbt_ok, checks = _run_dbt(tmp)

        con = duckdb.connect(str(tmp))
        try:
            if dbt_ok:  # the Python gates read tables dbt skips once a test fails
                checks += gates.run(con, previous=paths.current_build(), allow_shrink=allow_shrink)
            _finish(con, build_id, started, checks)
            failed = [c for c in checks if c.status == "fail"]
            if not failed and dbt_ok:
                _compact(con, compact)
        finally:
            con.close()
        if failed or not dbt_ok:
            kept = paths.builds / f"{build_id}.failed.duckdb"
            os.replace(tmp, kept)
            gates.write_report(report_path, build_id, checks, kept)
            raise BuildFailed(f"{len(failed)} validation gate(s) failed; the live warehouse is unchanged. "
                              f"Report: {report_path}. Failed build kept for inspection: {kept}", report_path)
        gates.write_report(report_path, build_id, checks, final)
    except BuildFailed:
        raise
    except Exception:
        tmp.unlink(missing_ok=True)
        compact.unlink(missing_ok=True)
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


def _load_sources(con: duckdb.DuckDBPyConnection, paths: Paths, manifests) -> None:
    """Copy the contract catalogues and every staged vintage into schema src."""
    con.execute("CREATE SCHEMA src")
    cat = catalogue.CATALOGUE_DIR
    for name in ("entities", "entity_codes", "memberships", "successions"):
        cols = TABLES[name].columns
        casts = ", ".join(f"CAST(nullif({c}, '') AS {t}) AS {c}" for c, t in cols.items())
        con.execute(f"CREATE TABLE src.{name} AS SELECT {casts} FROM "
                    f"read_csv('{(cat / f'{name}.csv').as_posix()}', header = true, all_varchar = true)")

    inds = catalogue.indicators().values()
    con.execute(_create("indicators"))
    con.executemany(f"INSERT INTO src.indicators VALUES ({', '.join('?' * len(TABLES['indicators'].columns))})", [
        (i.id, i.name, i.description, "|".join(i.synonyms), i.domain, i.unit, i.decimals, i.frequency,
         "|".join(i.breakdowns), i.aggregation.method, i.aggregation.weight, i.aggregation.numerator,
         i.aggregation.denominator, i.aggregation.multiplier, i.bounds[0], i.bounds[1]) for i in inds])
    con.execute(_create("indicator_sources"))
    con.executemany("INSERT INTO src.indicator_sources VALUES (?, ?, ?, ?, ?, ?)", [
        (i.id, s.source_id, s.series, s.scale, rank, s.notes) for i in inds for rank, s in enumerate(i.sources, 1)])
    con.execute(_create("sources"))
    con.executemany(f"INSERT INTO src.sources VALUES ({', '.join('?' * len(TABLES['sources'].columns))})", [
        (s.id, s.name, s.short_name, s.publisher, s.url, s.licence, s.licence_url, s.commercial_use, s.cadence,
         s.attribution, s.status, s.default_rank) for s in catalogue.sources().values()])

    latest = {}
    for m in manifests:
        latest[m.source_id] = m.vintage  # manifests are sorted by retrieval time
    con.execute(_create("vintages"))
    con.executemany("INSERT INTO src.vintages VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (m.source_id, m.vintage, m.release, m.retrieved_at, m.sha256, m.row_count, m.origin,
         latest[m.source_id] == m.vintage) for m in manifests])

    files = [(paths.vintages / m.source_id / m.vintage.replace("/", "_") / "observations.parquet").as_posix()
             for m in manifests]
    file_list = ", ".join(f"'{f}'" for f in files)
    con.execute(f"CREATE TABLE src.raw_observations AS SELECT * FROM read_parquet([{file_list}], union_by_name = true)")


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


def _sample_failures(db_path: Path, checks: list[gates.Check], sql: dict[int, str], n: int = 25) -> None:
    """Attach the first failing rows of each failed dbt test, so the report shows what broke."""
    con = duckdb.connect(str(db_path))  # same settings as dbt's own connection, which may still be open
    try:
        for c in checks:
            try:
                cur = con.execute(f"SELECT * FROM ({sql[id(c)]}) LIMIT {n}")
                cols = [d[0] for d in cur.description]
                c.examples = [", ".join(f"{k}={_fmt(v)}" for k, v in zip(cols, row)) for row in cur.fetchall()]
            except duckdb.Error as exc:
                c.examples = [f"(could not list the failing rows: {exc})"]
    finally:
        con.close()


def _fmt(v) -> str:
    return f"{v:,.6g}" if isinstance(v, float) else str(v)


def _finish(con: duckdb.DuckDBPyConnection, build_id: str, started, checks: list[gates.Check]) -> None:
    if not any(c.status == "fail" for c in checks):  # a failed build keeps them for debugging
        con.execute("DROP SCHEMA IF EXISTS src CASCADE")
        con.execute("DROP SCHEMA IF EXISTS int CASCADE")
    con.execute("CREATE OR REPLACE TABLE build_checks (check_id VARCHAR, kind VARCHAR, status VARCHAR, detail VARCHAR)")
    con.executemany("INSERT INTO build_checks VALUES (?, ?, ?, ?)",
                    [(c.check_id, c.kind, c.status, c.detail) for c in checks])
    meta = {
        "schema_version": SCHEMA_VERSION,
        "build_id": build_id,
        "built_at": started.isoformat(),
        "builder": f"worldmodel-data {__version__}",
        "vintages": json.dumps([list(r) for r in con.execute(
            "SELECT source_id, vintage FROM vintages WHERE is_latest ORDER BY 1").fetchall()]),
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
