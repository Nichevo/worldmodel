"""Python validation gates, run after the dbt tests on a new build.

  coverage     enough countries have data for the core indicators
  spot checks  known published values match (spot_checks.csv)
  shrinkage    no source or indicator lost a large share of its rows
  unmapped     source codes the crosswalk does not know (warning)
  implausible  high/low variant or interval values left out as meaningless (info)
  manual       a random sample with links to the source sites, to check by eye
  what-if      the population what-if model, run with the UN's own inputs, against
               the UN projection (never fails: it says how far the model is from it)
"""

from __future__ import annotations

import csv
import fnmatch
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import duckdb

from worldmodel_contract import cohort

SPOT_CHECKS = Path(str(resources.files("worldmodel_data") / "spot_checks.csv"))

# indicator -> minimum number of countries with an estimate in the latest estimate year
COVERAGE = {"pop_total": 200, "tfr": 200, "life_expectancy": 200, "pop_by_age_sex": 200, "gdp_growth": 180}
MAX_SHRINK = 0.10

SOURCE_LINKS = {
    "un_wpp": "https://population.un.org/dataportal/data/indicators/49/locations/{m49}/start/{year}/end/{year}",
    "imf_weo": "https://www.imf.org/external/datamapper/{series}@WEO/{iso3}",
}


@dataclass
class Check:
    check_id: str
    kind: str
    status: str  # pass, warn, fail, info, skip
    detail: str = ""
    examples: list[str] = field(default_factory=list)  # sample failing rows


def run(con: duckdb.DuckDBPyConnection, previous: Path | None, allow_shrink: bool = False) -> list[Check]:
    return [*coverage(con), *spot_checks(con), *shrinkage(con, previous, allow_shrink), *unmapped(con),
            *implausible_variants(con), *whatif_model(con), manual_sample(con)]


def coverage(con) -> list[Check]:
    out = []
    loaded = {r[0] for r in con.execute("SELECT DISTINCT indicator_id FROM series").fetchall()}
    for indicator, minimum in COVERAGE.items():
        if indicator not in loaded:
            out.append(Check(f"coverage:{indicator}", "coverage", "skip", "indicator not loaded"))
            continue
        year, n = con.execute("""
            WITH latest_year AS (
                SELECT max(period_start) AS p FROM series WHERE indicator_id = ? AND status = 'E')
            SELECT strftime(l.p, '%Y'), count(DISTINCT s.entity_id)
            FROM series s JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country', latest_year l
            WHERE s.indicator_id = ? AND s.period_start = l.p AND s.status = 'E'
            GROUP BY l.p""", [indicator, indicator]).fetchone() or ("?", 0)
        status = "pass" if n >= minimum else "fail"
        out.append(Check(f"coverage:{indicator}", "coverage", status,
                         f"{n} countries in {year} (need {minimum})"))
    return out


def spot_checks(con) -> list[Check]:
    out = []
    vintages = dict(con.execute("SELECT source_id, vintage FROM vintages WHERE is_latest").fetchall())
    with SPOT_CHECKS.open(encoding="utf-8") as f:
        for row in csv.DictReader(r for r in f if not r.startswith("#")):
            cid = f"spot:{row['source_id']}:{row['entity_id']}:{row['indicator_id']}:{row['year']}"
            vintage = vintages.get(row["source_id"])
            if vintage is None or not fnmatch.fnmatch(vintage, row["vintage"]):
                out.append(Check(cid, "spot_check", "skip", f"applies to vintage {row['vintage']}, loaded {vintage}"))
                continue
            got = con.execute("""
                SELECT value FROM series WHERE source_id = ? AND entity_id = ? AND indicator_id = ?
                AND period_start = make_date(?, 1, 1) AND breakdown = '' AND variant = 'central'""",
                              [row["source_id"], row["entity_id"], row["indicator_id"], int(row["year"])]).fetchone()
            expected, tol = float(row["expected"]), float(row["tolerance"])
            if got is None:
                out.append(Check(cid, "spot_check", "fail", f"no value; expected {expected:g} ({row['reference']})"))
                continue
            ok = abs(got[0] - expected) <= tol
            out.append(Check(cid, "spot_check", "pass" if ok else "fail",
                             f"got {got[0]:,.4g}, expected {expected:,.4g} ± {tol:g} ({row['reference']})"))
    return out


def shrinkage(con, previous: Path | None, allow_shrink: bool) -> list[Check]:
    if previous is None:
        return [Check("shrinkage", "shrinkage", "skip", "no previous build to compare with")]
    now = dict(((s, i), n) for s, i, n in con.execute(
        "SELECT source_id, indicator_id, count(*) FROM series GROUP BY ALL").fetchall())
    try:
        prev_con = duckdb.connect(str(previous), read_only=True)
        before = dict(((s, i), n) for s, i, n in prev_con.execute(
            "SELECT source_id, indicator_id, count(*) FROM series GROUP BY ALL").fetchall())
        prev_con.close()
    except duckdb.Error as exc:
        return [Check("shrinkage", "shrinkage", "warn", f"could not read previous build: {exc}")]
    out = []
    for key, n_before in sorted(before.items()):
        n_now = now.get(key, 0)
        if n_now < n_before * (1 - MAX_SHRINK):
            status = "warn" if allow_shrink else "fail"
            out.append(Check(f"shrinkage:{key[0]}:{key[1]}", "shrinkage", status,
                             f"{n_before:,} rows before, {n_now:,} now"))
    return out or [Check("shrinkage", "shrinkage", "pass", f"no series lost more than {MAX_SHRINK:.0%} of its rows")]


def unmapped(con) -> list[Check]:
    rows = con.execute("SELECT source_id, scheme, source_code, rows FROM unmapped_codes ORDER BY 1, 3").fetchall()
    if not rows:
        return [Check("unmapped", "crosswalk", "pass", "every source code maps to an entity")]
    listed = ", ".join(f"{s}:{c}" for s, _, c, _ in rows[:30])
    more = f" and {len(rows) - 30} more" if len(rows) > 30 else ""
    return [Check("unmapped", "crosswalk", "warn", f"{len(rows)} codes not in the crosswalk: {listed}{more}")]


def implausible_variants(con) -> list[Check]:
    """Values of high/low variants or prediction intervals left out as meaningless."""
    rows = con.execute("""SELECT source_id, indicator_id, entity_id, variant, rows, first_year, last_year
        FROM implausible_variant_values ORDER BY rows DESC, 1, 2, 3""").fetchall()
    if not rows:
        return [Check("implausible_variants", "variants", "pass", "every variant value is within reach of the bounds")]
    total = sum(r[4] for r in rows)
    return [Check("implausible_variants", "variants", "info",
                  f"{total} variant value(s) left out as implausible (outside the room given around the "
                  f"indicator's bounds, or infinite)",
                  [f"{s} {i} {e} {v}: {n} row(s), {a}-{b}" for s, i, e, v, n, a, b in rows[:10]])]


WHATIF_TOLERANCE = 1.0  # percent of total population, at every year compared
BACKTEST_YEARS = 30


def whatif_model(con) -> list[Check]:
    """The what-if's default run per country against the UN: forward over the UN
    projection, and a back-test from 30 years before the last estimate to it."""
    loaded = {r[0] for r in con.execute("SELECT DISTINCT indicator_id FROM series").fetchall()}
    if "pop_by_age_sex" not in loaded:
        return [Check("whatif:model", "model", "skip", "no population pyramids loaded")]
    countries = [r[0] for r in con.execute("SELECT entity_id FROM entities WHERE type = 'country' ORDER BY 1").fetchall()]
    sql = cohort.inputs_sql()
    runs: dict[str, list] = {"projection": [], "backtest": []}
    failed, short = [], 0
    for e in countries:
        rows = con.execute(sql, [e]).fetchall()
        inp = cohort.prepare(rows)
        if inp is None:
            continue
        tests = []
        if inp.last_year > inp.base_year:
            # Only a fair test where the UN's own projected inputs run to the end.
            held = cohort.fill_paths(inp.raw, inp.base_year, inp.last_year).held
            if any(k in held for k in ("tfr", "e0_male", "e0_female", "net_migration")):
                short += 1
            else:
                tests.append(("projection", inp, inp.last_year))
        start = max((r[1] for r in rows if r[0] == "pop_by_age_sex" and r[1] <= inp.base_year - BACKTEST_YEARS),
                    default=None)
        old = cohort.prepare(rows, start) if start else None
        if old:
            tests.append(("backtest", old, inp.base_year))
        for kind, i, end in tests:
            un = {y: p for y, p in i.un.items() if y <= end}
            if kind == "backtest":
                un[inp.base_year] = inp.base
            try:
                run = cohort.whatif(i.base_year, i.base, i.raw, end, cohort.Levers(), un, i.un_totals)
            except (ValueError, ZeroDivisionError, OverflowError) as exc:
                failed.append(f"{e}: {exc}")
                continue
            if run["raw_error"]["worst_total_pct"] is not None:
                runs[kind].append((run["raw_error"]["worst_total_pct"], e, i.base_year, end))
    out = []
    for kind, label in (("projection", "the UN projection"), ("backtest", "what happened")):
        errors = sorted(runs[kind], reverse=True)
        cid = f"whatif:{kind}"
        if not errors:
            why = (f"the UN's projected inputs (life expectancy, migration) stop before the projection ends for {short} "
                   f"countries" if kind == "projection" and short else "no country had the data to compare with")
            out.append(Check(cid, "model", "skip", why))
            continue
        within = sum(w <= WHATIF_TOLERANCE for w, *_ in errors)
        share = within / len(errors)
        years = f"{min(b for *_, b, _ in errors)}-{max(e for *_, e in errors)}"
        furthest = ", ".join(f"{e} {w:.1f}%" for w, e, *_ in errors[:8])
        detail = (f"Population what-if against {label}, {years}: {within} of {len(errors)} countries ({share:.0%}) within "
                  f"{WHATIF_TOLERANCE:g}% of the UN total in every year; median largest gap "
                  f"{errors[len(errors) // 2][0]:.2f}%. Furthest: {furthest}."
                  + (f" Could not run: {'; '.join(failed[:5])}." if failed else "")
                  + (" The app shows the UN figures plus what the levers change, so this gap is not in what you see."
                     if kind == "projection" else ""))
        out.append(Check(cid, "model", "pass" if share >= 0.9 and not failed else "warn", detail))
    return out


def manual_sample(con, n: int = 12) -> Check:
    """A reproducible sample of values to compare by eye with the source sites."""
    rows = con.execute(f"""
        SELECT s.source_id, s.entity_id, e.m49, s.indicator_id, i.name, strftime(s.period_start, '%Y'), s.value,
            i.unit, src.series
        FROM series s
        JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
        JOIN indicators i ON i.indicator_id = s.indicator_id
        JOIN indicator_sources src ON src.indicator_id = s.indicator_id AND src.source_id = s.source_id
        WHERE s.breakdown = '' AND s.status = 'E' AND NOT s.is_aggregate
            AND s.indicator_id IN ('pop_total', 'tfr', 'life_expectancy', 'median_age', 'gdp_growth', 'gdp_usd')
        ORDER BY hash(s.entity_id || s.indicator_id || s.period_start::VARCHAR) LIMIT {n}""").fetchall()
    lines = []
    for source_id, iso3, m49, ind, name, year, value, unit, series in rows:
        link = SOURCE_LINKS.get(source_id, "").format(m49=int(m49) if m49 else "", year=year, iso3=iso3,
                                                      series=series)
        lines.append(f"{iso3} {name} {year}: {value:,.6g} {unit} ({source_id}) {link}")
    return Check("manual_sample", "manual", "info", "\n".join(lines))


def write_report(path: Path, build_id: str, checks: list[Check], build_file: Path) -> None:
    failed = [c for c in checks if c.status == "fail"]
    lines = [f"# Build {build_id}", "",
             f"Result: {'FAILED, not swapped in' if failed else 'passed, live'}", f"File: {build_file.name}", "",
             "| Check | Kind | Status | Detail |", "| --- | --- | --- | --- |"]
    manual = None
    for c in checks:
        if c.kind == "manual":
            manual = c
            continue
        lines.append(f"| {c.check_id} | {c.kind} | {c.status} | {' '.join(c.detail.replace('|', '/').split())} |")
    for c in checks:
        if c.examples:
            title = "Failing rows" if c.status == "fail" else "Details"
            lines += ["", f"## {title}: {c.check_id}", ""] + [f"- {e}" if e else "" for e in c.examples]
    if manual:
        lines += ["", "## Check these by eye against the source sites", ""]
        lines += [f"- {line}" for line in manual.detail.splitlines()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
