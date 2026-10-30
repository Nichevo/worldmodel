"""Python validation gates, run after the dbt tests on a new build.

  coverage     enough countries have data for the core indicators
  spot checks  known published values match (spot_checks.csv)
  shrinkage    no source or indicator lost a large share of its rows
  unmapped     source codes the crosswalk does not know (warning)
  manual       a random sample with links to the source sites, to check by eye
"""

from __future__ import annotations

import csv
import fnmatch
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import duckdb

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
            manual_sample(con)]


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
            lines += ["", f"## Failing rows: {c.check_id}", ""] + [f"- {e}" if e else "" for e in c.examples]
    if manual:
        lines += ["", "## Check these by eye against the source sites", ""]
        lines += [f"- {line}" for line in manual.detail.splitlines()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
