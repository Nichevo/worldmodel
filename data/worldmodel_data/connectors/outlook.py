"""Monthly and quarterly figures for the Outlook page: recession odds and nowcasts
(Settings > Outlook, "Recession odds and nowcasts").

oecd_cli
    OECD Data Explorer SDMX API (sdmx.oecd.org), CSV, keyless:
    DF_CLI   composite leading indicators, amplitude adjusted (100 = the long-run trend),
             by month, for OECD members and the larger other economies. The indicator
             gathers the monthly figures that turn before output does (business and
             consumer surveys, orders, building permits, share prices, interest rate gaps).
    DF_QNA   real GDP, growth on the previous quarter, seasonally adjusted, by quarter.
fred_cycle
    FRED (fredgraph.csv, keyless): the US 10-year less 3-month Treasury yield gap
    (T10Y3M, daily, kept as monthly averages) and the Atlanta Fed's GDPNow estimate of
    this quarter's US growth (GDPNOW, annualised).
"""

from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.housing import code, col, read_csv
from worldmodel_data.connectors.markets import DatedRows
from worldmodel_data.connectors.tabular import entity_for, indicator, num

log = logging.getLogger(__name__)

OECD = "https://sdmx.oecd.org/public/rest/data/"
CLI_URLS = (OECD + "OECD.SDD.STES,DSD_STES@DF_CLI,4.1/.M.LI...AA...H?startPeriod=1980-01&format=csvfile",
            OECD + "OECD.SDD.STES,DSD_STES@DF_CLI,/.M.LI...AA...H?startPeriod=1980-01&format=csvfile")
QNA_URLS = (OECD + "OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA,/Q.Y..S1..B1GQ......?startPeriod=1980-Q1&format=csvfile",
            OECD + "OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA,/Q...S1..B1GQ......?startPeriod=1980-Q1&format=csvfile")
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"


def period_start(p: str) -> date | None:
    """The first day of an SDMX period: 2024-05, 2024-Q2, 2024-05-17."""
    s = str(p or "").strip()
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", s):
        return date(int(m.group(1)), 3 * int(m.group(2)) - 2, 1)
    if m := re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", s):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    return None


def _area(v: str) -> tuple[str, str] | None:
    a = code(v)
    if a in ("EA20", "EA19", "EA", "EU27_2020"):
        return "iso3", "eu"
    return ("iso3", a) if entity_for("iso3", a) else None


def cli_rows(data: list[dict], out: DatedRows) -> int:
    if not data:
        return 0
    h = data[0].keys()
    area, period, obs = col(h, "REF_AREA"), col(h, "TIME_PERIOD"), col(h, "OBS_VALUE")
    measure, adj = col(h, "MEASURE"), col(h, "ADJUSTMENT")
    if not (area and period and obs):
        raise ConnectorError("oecd_cli: the CLI file lacks REF_AREA, TIME_PERIOD or OBS_VALUE")
    n = 0
    for r in data:
        if (measure and code(r[measure]) not in ("LI", "")) or (adj and code(r[adj]) not in ("AA", "")):
            continue
        a, d = _area(r[area]), period_start(r[period])
        if a and d:
            out.add(a[0], a[1], "oecd_cli", d, num(r[obs]), freq="M")
            n += 1
    return n


def gdp_rows(data: list[dict], out: DatedRows) -> int:
    """Quarterly real growth: the published growth rates where the file has them, else
    worked out from the volume levels."""
    if not data:
        return 0
    h = data[0].keys()
    area, period, obs = col(h, "REF_AREA"), col(h, "TIME_PERIOD"), col(h, "OBS_VALUE")
    trans, price, adj, unit, tx = (col(h, "TRANSFORMATION"), col(h, "PRICE_BASE"), col(h, "ADJUSTMENT"),
                                   col(h, "UNIT_MEASURE"), col(h, "TRANSACTION"))
    if not (area and period and obs):
        raise ConnectorError("oecd_cli: the GDP file lacks REF_AREA, TIME_PERIOD or OBS_VALUE")
    growth: dict[tuple, dict[date, float]] = defaultdict(dict)
    level: dict[tuple, dict[date, float]] = defaultdict(dict)
    for r in data:
        if tx and code(r[tx]) not in ("B1GQ", ""):
            continue
        if adj and code(r[adj]) not in ("Y", ""):
            continue
        if price and code(r[price]) not in ("LR", "L", ""):
            continue
        a, d, v = _area(r[area]), period_start(r[period]), num(r[obs])
        if not a or not d or v is None:
            continue
        t = code(r[trans]) if trans else ""
        if t == "G1":
            growth[a][d] = v
        elif t in ("N", "") and (not unit or code(r[unit]) not in ("PC", "PT_B1GQ")):
            level[a][d] = v
    n = 0
    for a in set(growth) | set(level):
        g = dict(growth.get(a, {}))
        lv = sorted(level.get(a, {}).items())
        for (d0, v0), (d1, v1) in zip(lv, lv[1:]):
            if d1 not in g and v0 and (d1.year * 12 + d1.month) - (d0.year * 12 + d0.month) == 3:
                g[d1] = 100 * (v1 / v0 - 1)
        for d, v in g.items():
            out.add(a[0], a[1], "gdp_growth_q", d, round(v, 3), freq="Q")
            n += 1
    return n


class OECDCLI(Connector):
    source_id = "oecd_cli"
    switch = "outlook_fetch"
    fetch_every_days = 7

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def _first(self, urls: tuple[str, ...], dest: Path) -> str:
        errors = []
        for u in urls:
            try:
                self.get(u, dest)
                return u
            except ConnectorError as exc:
                errors.append(str(exc))
        raise ConnectorError(f"oecd_cli: {dest.name} could not be downloaded: {'; '.join(errors[:2])}")

    def download(self, raw_dir: Path, release: str) -> str:
        got = [self._first(CLI_URLS, raw_dir / "cli.csv")]
        try:
            got.append(self._first(QNA_URLS, raw_dir / "gdp_q.csv"))
        except ConnectorError as exc:
            log.warning("%s; leading indicators only", exc)
        return " ".join(got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        out = DatedRows()
        n = 0
        for name, fn in (("cli.csv", cli_rows), ("gdp_q.csv", gdp_rows)):
            p = raw_dir / name
            if p.exists():
                n += fn(read_csv(p), out)
        if not n:
            raise ConnectorError(f"oecd_cli: no values read from {raw_dir}")
        self.listed_indicators = [
            indicator("oecd_cli", "Composite leading indicator (OECD)",
                      "The OECD's leading indicator: monthly figures that usually turn before output does, gathered into "
                      "one index. 100 is the long-run trend; above 100 and rising points to growth above trend, below 100 "
                      "and falling to a slowdown, typically six to nine months ahead.", "index, trend = 100", "economy",
                      "oecd_cli", "DF_CLI:M.LI.AA", decimals=2, frequency="M", default_on=False, bounds=(50, 150)),
            indicator("gdp_growth_q", "GDP growth on the previous quarter",
                      "Real GDP growth on the quarter before, seasonally adjusted, not annualised. OECD quarterly national "
                      "accounts.", "%", "economy", "oecd_cli", "DF_QNA:Q.Y.B1GQ.LR.G1", decimals=2, frequency="Q",
                      default_on=False, bounds=(-50, 50)),
        ]
        return out.stage(con, self.source_id, vintage)


def fred_points(path: Path) -> list[tuple[date, float]]:
    """(date, value) from a fredgraph.csv file; '.' and blanks skipped."""
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 2:
                continue
            try:
                d = date.fromisoformat(r[0].strip()[:10])
            except ValueError:
                continue  # the header
            v = num(r[1])
            if v is not None:
                out.append((d, v))
    return out


class FREDCycle(Connector):
    source_id = "fred_cycle"
    switch = "outlook_fetch"
    fetch_every_days = 3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for sid in ("T10Y3M", "GDPNOW"):
            self.get(FRED.format(id=sid), raw_dir / f"{sid}.csv")
        return FRED.format(id="T10Y3M,GDPNOW")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        out = DatedRows()
        p = raw_dir / "T10Y3M.csv"
        if p.exists():
            months: dict[date, list[float]] = defaultdict(list)
            for d, v in fred_points(p):
                months[d.replace(day=1)].append(v)
            for m, vals in months.items():
                out.add("iso3", "USA", "us_term_spread", m, round(sum(vals) / len(vals), 3), freq="M")
        p = raw_dir / "GDPNOW.csv"
        if p.exists():
            for d, v in fred_points(p):
                out.add("iso3", "USA", "us_gdpnow", d, v, freq="Q")
        if not len(out):
            raise ConnectorError(f"fred_cycle: no values read from {raw_dir}")
        self.listed_indicators = [
            indicator("us_term_spread", "US yield curve (10-year less 3-month)",
                      "The 10-year Treasury yield less the 3-month bill rate, monthly average. Below zero (an 'inverted' "
                      "curve) has come before every US recession since the 1960s, usually by about a year. FRED T10Y3M.",
                      "percentage points", "finance", "fred_cycle", "T10Y3M", decimals=2, frequency="M", default_on=False,
                      bounds=(-10, 10)),
            indicator("us_gdpnow", "US GDPNow (Atlanta Fed)",
                      "The Atlanta Fed's running estimate of this quarter's US real GDP growth, at an annual rate, "
                      "updated several times a month until the official figure comes out. FRED GDPNOW.",
                      "% a year", "economy", "fred_cycle", "GDPNOW", decimals=1, frequency="Q", default_on=False,
                      bounds=(-50, 50)),
        ]
        return out.stage(con, self.source_id, vintage)
