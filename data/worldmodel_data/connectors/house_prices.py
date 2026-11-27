"""House prices in dollars, over time, for New Zealand's regions and Australia's states.

nz_property_sales
    The Ministry for Cities, Environment, Regions and Transport (formerly the Ministry of
    Housing and Urban Development, HUD) "Property and sales statistics" download: one Excel
    file (about 22 MB, renamed each month, linked from the dashboard's About page) built from
    the councils' District Valuation Rolls, monthly from 1980. Read for New Zealand as a whole
    and its 16 regions:
      Sales               residential sales, lower quartile, median and upper quartile sale price,
                          each Monthly, 3-Month rolling and 12-Month rolling
      House Price Index   the MCERT HPI (sale price to appraisal), Monthly and 3-Month rolling
    Kept: yearly figures (the median for the calendar year, from the 12-month rolling figure
    at December; the HPI averaged over the year; sales in the year) and monthly ones (3-month
    rolling median and HPI, which smooth out small regions; monthly sales counts). The last two
    months are left out by the Ministry because late sales are still coming in, and the whole
    history is recalculated each month.

abs_dwellings
    Australian Bureau of Statistics Data API (data.api.abs.gov.au, SDMX, keyless), quarterly:
      RES_DWELL_ST  mean price of residential dwellings, value of the dwelling stock and number
                    of dwellings, for Australia and each state and territory, from 2011
      RES_DWELL     median price of established house transfers and of attached dwellings
                    (units, townhouses), for each capital city and the rest of each state, from 2002
    Kept: quarterly values and yearly averages. The capital-city and rest-of-state medians are
    put on the state (separate figures), and Australia gets the capital-city medians only where
    the ABS gives them (it does not).

Region figures are kept apart from country menus (default_on false), as are the US state
figures; the national value sits in the same figure, so each region can be set against it.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.disease import nz_region
from worldmodel_data.connectors.markets import DatedRows
from worldmodel_data.connectors.tabular import Rows, indicator, key, num

log = logging.getLogger(__name__)


def _ind(id: str, name: str, desc: str, unit: str, source: str, series: str, **kw) -> dict:
    kw.setdefault("default_on", False)  # region figures stay off the world map's menus
    return indicator(id, name, desc, unit, "housing", source, series, **kw)


def month_of(v) -> date | None:
    """The first of the month from an Excel date, an Excel day number (29221 = 1 Jan 1980) or "2026-08"."""
    if isinstance(v, datetime):
        return date(v.year, v.month, 1)
    if isinstance(v, date):
        return date(v.year, v.month, 1)
    if isinstance(v, (int, float)) and 1 < v < 100000:
        d = date(1899, 12, 30) + timedelta(days=int(v))
        return date(d.year, d.month, 1)
    m = re.match(r"\s*(\d{4})-(\d{1,2})", str(v or ""))
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1)
    n = num(v)
    return month_of(n) if isinstance(n, float) and n > 1000 else None


# ------------------------------------------------------------------------------------ New Zealand
NZ_PAGE = "https://www.hud.govt.nz/stats-and-insights/property-and-sales-statistics/about-the-dashboard"
NZ_SITE = "https://www.hud.govt.nz"
NZ_SOURCE = "nz_property_sales"


def nz_place(area_type, area) -> str | None:
    t = key(area_type)
    if t == "national":
        return "NZL"
    if t == "region":
        return nz_region(str(area or ""))
    return None  # territorial authorities and Auckland local boards: no entities for them yet


def _sheet_rows(path: Path, want: str):
    """Rows of the sheet whose name contains `want` (case ignored), streamed."""
    from openpyxl import load_workbook

    with open(path, "rb") as fh:
        wb = load_workbook(fh, read_only=True, data_only=True)
        try:
            name = next((n for n in wb.sheetnames if key(n) == key(want)), None) \
                or next((n for n in wb.sheetnames if key(n).startswith(key(want)) and "composition" not in key(n)), None)
            if name is None:
                return
            ws = wb[name]
            if hasattr(ws, "reset_dimensions"):
                ws.reset_dimensions()
            yield from ws.iter_rows(values_only=True)
        finally:
            wb.close()


def nz_rows(path: Path, rows: Rows, dated: DatedRows) -> int:
    """Read the Sales and House Price Index sheets for New Zealand and its regions."""
    n = 0
    hpi_year: dict[tuple[str, int], list[float]] = defaultdict(list)
    for sheet in ("Sales", "House Price Index"):
        head: dict[str, int] | None = None
        for r in _sheet_rows(path, sheet):
            if head is None:
                cells = [key(c) for c in r]
                if "stattype" in cells and "period" in cells:
                    head = {c: i for i, c in enumerate(cells) if c}
                continue
            def cell(name: str):
                i = head.get(name)
                return r[i] if i is not None and i < len(r) else None
            ent = nz_place(cell("areatype"), cell("area"))
            d = month_of(cell("period"))
            if not ent or not d:
                continue
            stat = key(cell("stattype"))
            if sheet == "Sales":
                median, sales = num(cell("mediansaleprice")), num(cell("residentialsales"))
                if stat == "monthly":
                    dated.add("iso3", ent, "nzhouse_sales_m", d, sales, freq="M")
                elif stat == "3monthrolling":
                    dated.add("iso3", ent, "nzhouse_median_price_m", d, median, freq="M")
                    dated.add("iso3", ent, "nzhouse_lq_price_m", d, num(cell("lowerquartilesaleprice")), freq="M")
                    dated.add("iso3", ent, "nzhouse_uq_price_m", d, num(cell("upperquartilesaleprice")), freq="M")
                elif stat == "12monthrolling" and d.month == 12:  # the calendar year
                    rows.add("iso3", ent, "nzhouse_median_price", d.year, median)
                    rows.add("iso3", ent, "nzhouse_lq_price", d.year, num(cell("lowerquartilesaleprice")))
                    rows.add("iso3", ent, "nzhouse_uq_price", d.year, num(cell("upperquartilesaleprice")))
                    rows.add("iso3", ent, "nzhouse_sales", d.year, sales)
                else:
                    continue
                n += 1
            else:
                hpi = num(cell("housepriceindexallquartiles"))
                if hpi is None or hpi <= 0:  # 0 where a month had too few sales to index
                    continue
                if stat == "monthly":
                    hpi_year[(ent, d.year)].append(hpi)
                elif stat == "3monthrolling":
                    dated.add("iso3", ent, "nzhouse_hpi_m", d, hpi, freq="M")
                else:
                    continue
                n += 1
    for (ent, y), vals in hpi_year.items():
        if len(vals) >= 6:  # most of the year
            rows.add("iso3", ent, "nzhouse_hpi", y, sum(vals) / len(vals))
    return n


NZ_NOTE = ("Ministry for Cities, Environment, Regions and Transport (formerly HUD), Property and sales statistics, "
           "from the councils' District Valuation Rolls: market sales of single freehold residential properties, by "
           "agreement date. The latest two months are left out and the whole series is recalculated each month.")
NZ_INDICATORS = [
    ("nzhouse_median_price", "Median house sale price (NZ regions)",
     "The middle price paid for residential properties sold in the calendar year (12-month rolling median at December).",
     "NZ$", 0, "Sales: 12-Month rolling, median_sale_price (December)", "A"),
    ("nzhouse_lq_price", "Lower quartile house sale price (NZ regions)",
     "The price a quarter of residential sales in the calendar year were below: the cheaper end of the market.",
     "NZ$", 0, "Sales: 12-Month rolling, lower_quartile_sale_price (December)", "A"),
    ("nzhouse_uq_price", "Upper quartile house sale price (NZ regions)",
     "The price a quarter of residential sales in the calendar year were above: the dearer end of the market.",
     "NZ$", 0, "Sales: 12-Month rolling, upper_quartile_sale_price (December)", "A"),
    ("nzhouse_sales", "Residential sales (NZ regions)", "Residential properties sold in the calendar year.",
     "sales", 0, "Sales: 12-Month rolling, residential_sales (December)", "A"),
    ("nzhouse_hpi", "House price index, MCERT (NZ regions)",
     "The MCERT House Price Index, which compares each sale price with the property's rating valuation so that a "
     "month with more dear (or cheap) homes sold does not look like a price change. Yearly average of the months.",
     "index", 0, "House Price Index: Monthly, house_price_index_all_quartiles (yearly average)", "A"),
    ("nzhouse_median_price_m", "Median house sale price, monthly (NZ regions)",
     "The middle price paid for residential properties sold in the three months to each month.",
     "NZ$", 0, "Sales: 3-Month rolling, median_sale_price", "M"),
    ("nzhouse_lq_price_m", "Lower quartile house sale price, monthly (NZ regions)",
     "The price a quarter of residential sales in the three months to each month were below.",
     "NZ$", 0, "Sales: 3-Month rolling, lower_quartile_sale_price", "M"),
    ("nzhouse_uq_price_m", "Upper quartile house sale price, monthly (NZ regions)",
     "The price a quarter of residential sales in the three months to each month were above.",
     "NZ$", 0, "Sales: 3-Month rolling, upper_quartile_sale_price", "M"),
    ("nzhouse_sales_m", "Residential sales, monthly (NZ regions)", "Residential properties sold each month.",
     "sales", 0, "Sales: Monthly, residential_sales", "M"),
    ("nzhouse_hpi_m", "House price index, MCERT, monthly (NZ regions)",
     "The MCERT House Price Index over the three months to each month (sale price to appraisal).",
     "index", 0, "House Price Index: 3-Month rolling, house_price_index_all_quartiles", "M"),
]


class NZPropertySales(Connector):
    source_id = NZ_SOURCE
    pack = "nz"
    fetch_every_days = 25
    keep_vintages = 3  # each download is a full 22 MB history

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"download[-_ ]([A-Za-z]+)[-_ ](\d{4})", f.name)
            if m:
                try:
                    return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)}", "%b %Y").strftime("%Y-%m")
                except ValueError:
                    pass
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        page = self.client.get(NZ_PAGE)
        page.raise_for_status()
        links = re.findall(r'href="([^"]*Property-and-Sales[^"]*\.xlsx[^"]*)"', page.text, re.I)
        if not links:
            raise ConnectorError("nz_property_sales: no link to the data download (Property-and-Sales-data-download-<month>.xlsx) "
                                 "on the dashboard's About page")
        url = links[0].replace("&amp;", "&")
        url = url if url.startswith("http") else NZ_SITE + url
        name = re.sub(r"[^\w.-]", "_", url.rsplit("/", 1)[-1].split("?", 1)[0]) or "Property-and-Sales-data-download.xlsx"
        self.get(url, raw_dir / name)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.xlsx"))
        if not files:
            raise ConnectorError(f"nz_property_sales: no .xlsx in {raw_dir}")
        rows, dated = Rows(), DatedRows()
        n = nz_rows(files[-1], rows, dated)
        if not n:
            raise ConnectorError(f"nz_property_sales: no national or regional figures read from {files[-1].name}; "
                                 "the sheets (Sales, House Price Index) or their headings may have changed")
        found = {r[2] for r in rows.rows} | {r[2] for r in dated.rows}
        self.listed_indicators = [
            _ind(i, name, f"{desc} {NZ_NOTE}", unit, self.source_id, series, decimals=dec, frequency=freq,
                 bounds=(0, 1e9), notes="New Zealand and its 16 regions, from 1980.")
            for i, name, desc, unit, dec, series, freq in NZ_INDICATORS if i in found]
        return rows.stage(con, self.source_id, vintage) + " UNION ALL " + dated.stage(con, self.source_id, vintage)


# -------------------------------------------------------------------------------------- Australia
ABS_API = "https://data.api.abs.gov.au/rest/data/ABS,{flow}/all"
ABS_FLOWS = ("RES_DWELL_ST", "RES_DWELL")
ABS_ACCEPT = {"Accept": "application/vnd.sdmx.data+csv;labels=both"}
AU_SOURCE = "abs_dwellings"
AU_STATES = {"1": "AU-NSW", "2": "AU-VIC", "3": "AU-QLD", "4": "AU-SA", "5": "AU-WA", "6": "AU-TAS", "7": "AU-NT",
             "8": "AU-ACT", "AUS": "AUS"}
# RES_DWELL_ST measure -> (indicator, scale to the unit kept)
ST_MEASURES = {"5": ("aureg_mean_dwelling_price", 1000.0),      # A$ thousands -> A$
               "1": ("aureg_dwelling_stock_value", 0.001),      # A$ millions -> A$ billions
               "4": ("aureg_dwellings", 1000.0)}                # thousands -> dwellings
# RES_DWELL measure -> indicator stem (capital city or rest of state added)
RD_MEASURES = {"3": "aureg_house_median", "4": "aureg_unit_median"}


def _code(v) -> str:
    return str(v or "").split(":", 1)[0].strip()


def _quarter(v) -> date | None:
    m = re.match(r"\s*(\d{4})-?Q([1-4])", str(v or ""))
    return date(int(m.group(1)), 3 * int(m.group(2)) - 2, 1) if m else None


def abs_rows(text: str, rows: Rows, dated: DatedRows) -> int:
    """One ABS CSV (SDMX-CSV with labels, or the Data Explorer's 'CSV with labels' download)."""
    data = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not data:
        return 0
    cols = {key(_code(h) if ":" in h else h): h for h in data[0]}
    measure, region, period, obs = (cols.get("measure"), cols.get("region"), cols.get("timeperiod"), cols.get("obsvalue"))
    flow = cols.get("dataflow")
    if not (measure and region and period and obs):
        return 0
    n = 0
    for r in data:
        q, v = _quarter(r[period]), num(r[obs])
        if q is None or v is None:
            continue
        m, reg = _code(r[measure]), _code(r[region]).upper()
        f = str(r.get(flow, "") if flow else "").upper()
        is_st = "RES_DWELL_ST" in f or (not f and reg in AU_STATES)
        if is_st:
            if m not in ST_MEASURES or reg not in AU_STATES:
                continue
            ind, scale = ST_MEASURES[m]
            ent = AU_STATES[reg]
        else:
            stem = RD_MEASURES.get(m)
            st = AU_STATES.get(reg[:1]) if reg[:1].isdigit() else None
            if not stem or not st or len(reg) < 2:
                continue
            ind, scale, ent = f"{stem}_{'capital' if reg[1] == 'G' or reg.startswith('8') else 'rest'}", 1000.0, st
        dated.add("iso3", ent, f"{ind}_q", q, v * scale, freq="Q")
        rows.add_period("iso3", ent, ind, q.year, v * scale)
        n += 1
    return n


AU_NOTE = "Australian Bureau of Statistics."
AU_INDICATORS = [
    ("aureg_mean_dwelling_price", "Mean dwelling price (Australian states)",
     "The average price of residential dwellings (houses and units) in the state, from the value of the whole "
     "dwelling stock divided by the number of dwellings. ABS Total Value of Dwellings (RES_DWELL_ST).", "A$", 0, "RES_DWELL_ST:5"),
    ("aureg_dwelling_stock_value", "Value of the dwelling stock (Australian states)",
     "What all the residential dwellings in the state were worth. ABS Total Value of Dwellings (RES_DWELL_ST).",
     "A$ billion", 1, "RES_DWELL_ST:1"),
    ("aureg_dwellings", "Residential dwellings (Australian states)",
     "Number of residential dwellings in the state. ABS Total Value of Dwellings (RES_DWELL_ST).", "dwellings", 0, "RES_DWELL_ST:4"),
    ("aureg_house_median_capital", "Median house price, capital city (Australian states)",
     "The middle price of established house transfers in the state's capital city (Greater Sydney, Greater "
     "Melbourne, and so on; all of the ACT). ABS Residential Dwellings (RES_DWELL).", "A$", 0, "RES_DWELL:3 (Greater capital)"),
    ("aureg_house_median_rest", "Median house price, rest of state (Australian states)",
     "The middle price of established house transfers in the state outside its capital city. ABS Residential "
     "Dwellings (RES_DWELL).", "A$", 0, "RES_DWELL:3 (Rest of state)"),
    ("aureg_unit_median_capital", "Median unit price, capital city (Australian states)",
     "The middle price of attached dwelling transfers (flats, units, townhouses) in the state's capital city. ABS "
     "Residential Dwellings (RES_DWELL).", "A$", 0, "RES_DWELL:4 (Greater capital)"),
    ("aureg_unit_median_rest", "Median unit price, rest of state (Australian states)",
     "The middle price of attached dwelling transfers (flats, units, townhouses) in the state outside its capital "
     "city. ABS Residential Dwellings (RES_DWELL).", "A$", 0, "RES_DWELL:4 (Rest of state)"),
]


class ABSDwellings(Connector):
    source_id = AU_SOURCE
    fetch_every_days = 30
    stage_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for flow in ABS_FLOWS:
            url = ABS_API.format(flow=flow)
            try:
                self.get(url, raw_dir / f"{flow}.csv", headers=ABS_ACCEPT)
                got.append(url)
            except Exception as exc:  # noqa: BLE001 - the other table may still come
                log.warning("abs_dwellings: %s not downloaded (%s)", flow, exc)
        if not got:
            raise ConnectorError("abs_dwellings: neither ABS table (RES_DWELL_ST, RES_DWELL) could be downloaded")
        return " ".join(got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, dated = Rows(), DatedRows()
        n = 0
        files = sorted(raw_dir.glob("*.csv"))
        names = {f.name for f in files}
        for flow in ABS_FLOWS:  # a table missing from this vintage comes from the last one that has it
            if f"{flow}.csv" not in names and not any(flow in f.name.upper() for f in files):
                if (p := self.earlier_copy(raw_dir, f"{flow}.csv")):
                    files.append(p)
        for f in files:
            n += abs_rows(f.read_bytes().decode("utf-8-sig", errors="replace"), rows, dated)
        if not n:
            raise ConnectorError(f"abs_dwellings: no figures read from {raw_dir}")
        rows.finish_periods(need=4)  # whole years only
        found = {r[2] for r in rows.rows} | {r[2][:-2] for r in dated.rows}
        self.listed_indicators = []
        for i, name, desc, unit, dec, series in AU_INDICATORS:
            if i not in found:
                continue
            self.listed_indicators.append(_ind(i, name, f"{desc} Yearly average of the quarters. {AU_NOTE}", unit,
                                               self.source_id, series, decimals=dec, bounds=(0, 1e12)))
            self.listed_indicators.append(_ind(f"{i}_q", name.replace(" (Australian", ", quarterly (Australian"),
                                               f"{desc} {AU_NOTE}", unit, self.source_id, f"{series} quarterly",
                                               decimals=dec, bounds=(0, 1e12), frequency="Q"))
        return rows.stage(con, self.source_id, vintage) + " UNION ALL " + dated.stage(con, self.source_id, vintage)
