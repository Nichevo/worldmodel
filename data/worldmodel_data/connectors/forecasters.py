"""Official forecasts from other forecasters, beside the IMF's.

oecd_eo
    OECD Economic Outlook (twice a year, early June and early December), from the
    OECD Data Explorer SDMX API (sdmx.oecd.org), CSV, yearly: real GDP growth
    (GDPV_ANNPCT) and consumer price inflation (CPI_YTYPCT) for OECD members and
    the larger other economies. Key dimensions: REF_AREA.MEASURE.FREQ.

wb_gep
    World Bank Global Economic Prospects (January and June), through the World
    Bank API as source 27: real GDP growth (NYGDPMKTPKDZ) for about 160 countries,
    estimates plus forecasts two or three years ahead.

Both feed the catalogue's gdp_growth (and, for the OECD, inflation) as further
sources, so their figures sit beside the IMF's under the same indicator. Each
fetch is named after the edition current on the fetch date (OECD: YYYY-06 or
YYYY-12; World Bank: YYYY-01 or YYYY-06), and years from the edition's year on
are forecasts (status P). Each stored edition is one vintage, so a track record
builds up from the second edition stored onwards (see forecast_pairs_sql).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.housing import code, col, read_csv, year_of
from worldmodel_data.connectors.tabular import Rows, num

log = logging.getLogger(__name__)

OECD_EO = ("https://sdmx.oecd.org/public/rest/data/OECD.ECO.MAD,DSD_EO@DF_EO,/.{measures}.A"
           "?startPeriod=1990&format=csvfile")
WB_GEP = ("https://api.worldbank.org/v2/country/all/indicator/NYGDPMKTPKDZ"
          "?source=27&format=json&per_page=20000&date=1990:2035")


def edition(fetched_at: datetime, months: tuple[int, int]) -> str:
    """The edition current on a date, for a forecaster publishing in two given months."""
    first, second = months
    y, m = fetched_at.year, fetched_at.month
    if m >= second:
        return f"{y}-{second:02d}"
    if m >= first:
        return f"{y}-{first:02d}"
    return f"{y - 1}-{second:02d}"


def first_forecast_year(release: str, name: str) -> int:
    try:
        return int(release[:4])
    except ValueError:
        raise ConnectorError(f"{name}: release {release!r} should start with a year, like 2026-06")


class OECDEO(Connector):
    source_id = "oecd_eo"
    fetch_every_days = 14

    def default_release(self, fetched_at: datetime) -> str:
        return edition(fetched_at, (6, 12))

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            if f.name == "release.txt":
                return f.read_text().strip()
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = OECD_EO.format(measures="+".join(self.series_map()))
        self.get(url, raw_dir / "economic_outlook.csv")
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        start = first_forecast_year(release, self.source_id)
        wanted = self.series_map()
        p = raw_dir / "economic_outlook.csv"
        data = read_csv(p) if p.exists() else []
        if not data:
            raise ConnectorError(f"oecd_eo: no rows in {p}")
        h = data[0].keys()
        area, measure, freq, period, obs = (col(h, "REF_AREA"), col(h, "MEASURE"), col(h, "FREQ"),
                                            col(h, "TIME_PERIOD"), col(h, "OBS_VALUE"))
        if not all((area, measure, period, obs)):
            raise ConnectorError("oecd_eo: the file lacks REF_AREA, MEASURE, TIME_PERIOD or OBS_VALUE")
        rows = Rows()
        for r in data:
            if freq and code(r[freq]) not in ("A", ""):
                continue
            m = wanted.get(code(r[measure]))
            y = year_of(r[period])
            if not m or not y or re.search(r"Q|M", str(r[period])[4:]):
                continue
            ind, scale = m
            v = num(r[obs])
            rows.add("iso3", code(r[area]), ind, y, None if v is None else v * scale,
                     status="P" if y >= start else "E")
        if not len(rows):
            raise ConnectorError(f"oecd_eo: no values for {', '.join(wanted)} in {p.name}")
        return rows.stage(con, self.source_id, vintage)


class WorldBankGEP(Connector):
    source_id = "wb_gep"
    fetch_every_days = 14

    def default_release(self, fetched_at: datetime) -> str:
        return edition(fetched_at, (1, 6))

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            if f.name == "release.txt":
                return f.read_text().strip()
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(WB_GEP, raw_dir / "gep_gdp_growth.json")
        return WB_GEP

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        start = first_forecast_year(release, self.source_id)
        wanted = self.series_map()
        rows = Rows()
        for p in sorted(raw_dir.glob("*.json")):
            payload = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(payload, list) and payload and isinstance(payload[0], dict) and payload[0].get("message"):
                raise ConnectorError(f"wb_gep: the World Bank API answered with an error: {payload[0]['message']}")
            records = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            for r in records or []:
                series = (r.get("indicator") or {}).get("id", "")
                m = wanted.get(series) or wanted.get(series.replace(".", ""))
                y = year_of(r.get("date"))
                iso = r.get("countryiso3code") or (r.get("country") or {}).get("id", "")
                if not m or not y or not iso:
                    continue
                ind, scale = m
                v = num(r.get("value"))
                rows.add("iso3", iso, ind, y, None if v is None else v * scale, status="P" if y >= start else "E")
        if not len(rows):
            raise ConnectorError(f"wb_gep: no GDP growth values read from {raw_dir}")
        return rows.stage(con, self.source_id, vintage)
