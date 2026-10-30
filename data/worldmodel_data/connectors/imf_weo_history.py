"""IMF WEO historical forecasts: what each World Economic Outlook since 1990 forecast.

    https://www.imf.org/-/media/Files/Publications/WEO/WEO-Database/WEOhistorical.ashx

One Excel file from the IMF, updated after each WEO, holding every spring (April)
and fall (October) release's figures for real GDP growth, inflation and the
current account. Used for the forecast track record: how far each release's
forecasts were from what happened.

The layout read here: a sheet per variable (or variable codes in the column
names), one row per country and year, and one column per release named like
S2010 / F2010 (spring / fall 2010), optionally followed by the variable code
(S2010ngdp_rpch). The country is the ISO alpha-3 column. Anything else in the
file is ignored, and a layout this cannot read stops the fetch with a clear
error rather than storing nothing useful.

Each release is stored with breakdown `release=YYYY-MM` (04 or 10), all in one
vintage, so ordinary views (which show breakdown '') never mix them with the
current figures. Years before the release year are its estimates (E); the rest
are forecasts (P).

A copy of the file can be given instead: worldmodel-data fetch imf_weo_history --from FILE.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError

log = logging.getLogger(__name__)

URL = "https://www.imf.org/-/media/Files/Publications/WEO/WEO-Database/WEOhistorical.ashx"
FILE = "WEOhistorical.xlsx"
RELEASE_COLUMN = re.compile(r"^\s*(S|F|spring|fall|apr|april|oct|october)[\s_-]?((?:19|20)\d\d)\s*([a-z_]*)\s*$", re.I)
ISO_HEADER = re.compile(r"iso.*(3|alpha)|^iso$|^iso_?code$|^country_?code$", re.I)


class IMFWEOHistory(Connector):
    source_id = "imf_weo_history"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")  # the file has no release of its own: the fetch date

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(URL, raw_dir / FILE)
        return URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm", ".ashx"))
        if not files:
            raise ConnectorError(f"imf_weo_history: no Excel file in {raw_dir}")
        rows = read_workbook(files[0], self.series_map())
        if not rows:
            raise ConnectorError(f"imf_weo_history: found no release columns (like S2010, F2010) in {files[0].name}; "
                                 "the IMF may have changed the file's layout")
        con.execute("CREATE TABLE weo_hist (source_code VARCHAR, indicator_id VARCHAR, period_start DATE, "
                    "breakdown VARCHAR, value DOUBLE, status VARCHAR)")
        con.executemany("INSERT INTO weo_hist VALUES (?, ?, ?, ?, ?, ?)", rows)
        return (f"SELECT 'imf_weo_history' AS source_id, '{vintage}' AS vintage, 'imf' AS scheme, source_code, "
                f"indicator_id, period_start, 'A' AS freq, breakdown, 'central' AS variant, value, status "
                f"FROM weo_hist")


def read_workbook(path: Path, series: dict[str, tuple[str, float]]) -> list[tuple]:
    """(country, indicator, period_start, breakdown, value, status) for every release column found."""
    from openpyxl import load_workbook  # only needed here

    codes = {c.lower(): v for c, v in series.items()}
    fh = path.open("rb")  # a file object, so a copy saved as .ashx opens too
    wb = load_workbook(fh, read_only=True, data_only=True)
    out: list[tuple] = []
    try:
        for ws in wb.worksheets:
            sheet_code = next((c for c in codes if c in ws.title.lower()), None)
            it = ws.iter_rows(values_only=True)
            header, iso_col, year_col, releases = None, None, None, {}
            for _ in range(15):  # the header is near the top
                row = next(it, None)
                if row is None:
                    break
                cells = [str(c).strip() if c is not None else "" for c in row]
                found = {}
                for i, cell in enumerate(cells):
                    m = RELEASE_COLUMN.match(cell)
                    if not m:
                        continue
                    season, year, suffix = m.group(1).lower(), m.group(2), m.group(3).lower()
                    code = next((c for c in codes if suffix and c in suffix), None) if suffix else sheet_code
                    if code:
                        found[i] = (f"{year}-{'04' if season[0] in 'sa' else '10'}", code)
                if found:
                    header, releases = cells, found
                    iso_col = next((i for i, c in enumerate(cells) if ISO_HEADER.search(c)), None)
                    year_col = next((i for i, c in enumerate(cells) if c.lower() == "year"), None)
                    break
            if header is None or iso_col is None or year_col is None:
                if header is not None:
                    log.warning("imf_weo_history: sheet %s has release columns but no ISO code or year column", ws.title)
                continue
            for row in it:
                if row is None or len(row) <= max(iso_col, year_col):
                    continue
                iso, year = row[iso_col], row[year_col]
                try:
                    year = int(year)
                except (TypeError, ValueError):
                    continue
                if not iso or not isinstance(iso, str):
                    continue
                for i, (rel, code) in releases.items():
                    if i >= len(row):
                        continue
                    value = _number(row[i])
                    if value is None:
                        continue
                    indicator, scale = codes[code]
                    out.append((iso.strip().upper(), indicator, f"{year}-01-01", f"release={rel}", value * scale,
                                "P" if year >= int(rel[:4]) else "E"))
    finally:
        wb.close()
        fh.close()
    return out


def _number(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if s in ("", "n/a", "--", "NA", ".", "..."):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None
