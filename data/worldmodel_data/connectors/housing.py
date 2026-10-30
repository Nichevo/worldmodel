"""House prices, incomes and household debt.

bis
    Bank for International Settlements statistics API (stats.bis.org), CSV:
    WS_SPP   residential property prices, nominal and real, index 2010 = 100, by quarter
    WS_TC    credit to households from all lenders, % of GDP, by quarter (key Q..H.A.M.770.A)
    If the API cannot be reached, the property prices come from the copy kept on
    GitHub (datasets/house-prices-global). Quarters are averaged to years.

oecd
    OECD Data Explorer SDMX API (sdmx.oecd.org), CSV, yearly:
    DF_HOUSE_PRICES  nominal and real house prices, rents, price-to-rent and
                     price-to-income ratios, and both ratios against their long-run average
    DF_HHDASH_CTRY   household debt, % of gross disposable income

dallas_fed_ihpd
    Federal Reserve Bank of Dallas International House Price Database: one Excel
    file (hpYYMM.xlsx, found on the database's page) with nominal and real house
    prices and nominal and real personal disposable income per person, by quarter,
    index 2005 = 100, for about 25 countries. The price-to-income ratio is worked
    out from them (nominal prices over nominal income, 2005 = 100).

imf_gdd
    IMF Global Debt Database through the DataMapper API: household debt (loans and
    debt securities) and non-financial corporate debt, % of GDP.

Each source's series are its own indicators. Where two sources share a name
("House prices (nominal)"), the menus add the source's name to tell them apart.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, indicator, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def code(v: str | None) -> str:
    """The code part of an SDMX cell: 'N: Nominal' -> 'N'."""
    return (v or "").split(":", 1)[0].strip()


def col(row_keys, *names: str) -> str | None:
    """The header among row_keys matching one of names loosely (an SDMX column may carry a label)."""
    wanted = [key(n) for n in names]
    for h in row_keys:
        k = key(code(h) if ":" in h else h)
        if k in wanted:
            return h
    return None


def year_of(period: str) -> int | None:
    m = re.match(r"\s*(\d{4})", str(period or ""))
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------------------------- BIS
BIS_API = "https://stats.bis.org/api/v2/data/dataflow/BIS/"
BIS_SPP = BIS_API + "WS_SPP/1.0?format=csv"
BIS_TC = [BIS_API + f"WS_TC/{v}/Q..H.A.M.770.A?format=csv" for v in ("2.0", "1.0")]
BIS_MIRROR = "https://raw.githubusercontent.com/datasets/house-prices-global/main/data/"


class BIS(Connector):
    source_id = "bis"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        try:
            self.get(BIS_SPP, raw_dir / "spp.csv")
            got.append(BIS_SPP)
        except Exception as exc:  # noqa: BLE001 - any failure: use the copy on GitHub
            log.warning("bis: property prices API failed (%s); using the copy on GitHub", exc)
            for name in ("nominal_index.csv", "real_index.csv"):
                self.get(BIS_MIRROR + name, raw_dir / f"spp_{name}")
            got.append(BIS_MIRROR)
        for url in BIS_TC:
            try:
                self.get(url, raw_dir / "tc_households.csv")
                got.append(url)
                break
            except ConnectorError as exc:
                log.info("bis: %s (%s)", url, exc)
        else:
            log.warning("bis: household credit could not be downloaded; house prices only")
        return " ".join(got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        spp = raw_dir / "spp.csv"
        if spp.exists():
            data = read_csv(spp)
            if data:
                h = data[0].keys()
                area, val, unit, period, obs = (col(h, "REF_AREA"), col(h, "VALUE"), col(h, "UNIT_MEASURE"),
                                                col(h, "TIME_PERIOD"), col(h, "OBS_VALUE"))
                if not all((area, val, period, obs)):
                    raise ConnectorError(f"bis: {spp.name} lacks REF_AREA, VALUE, TIME_PERIOD or OBS_VALUE")
                for r in data:
                    if unit and code(r[unit]) not in ("628", ""):  # 628 = index, 2010 = 100 (771 is the yearly change)
                        continue
                    ind = {"N": "bis_house_price_nominal", "R": "bis_house_price_real"}.get(code(r[val]))
                    if ind and (y := year_of(r[period])):
                        rows.add_period("iso2", code(r[area]), ind, y, num(r[obs]))
        for name, ind in (("spp_nominal_index.csv", "bis_house_price_nominal"), ("spp_real_index.csv", "bis_house_price_real")):
            p = raw_dir / name
            if p.exists():
                for r in read_csv(p):
                    if y := year_of(r.get("date")):
                        rows.add_period("iso2", r.get("country_code", ""), ind, y, num(r.get("price")))
        tc = raw_dir / "tc_households.csv"
        if tc.exists():
            data = read_csv(tc)
            if data:
                h = data[0].keys()
                area, period, obs = col(h, "BORROWERS_CTY"), col(h, "TIME_PERIOD"), col(h, "OBS_VALUE")
                for r in data if area and period and obs else []:
                    if y := year_of(r[period]):
                        rows.add_period("iso2", code(r[area]), "bis_household_credit_gdp", y, num(r[obs]))
        rows.finish_periods(need=2)
        if not len(rows):
            raise ConnectorError(f"bis: no values read from {raw_dir}")
        self.listed_indicators = BIS_INDICATORS
        return rows.stage(con, self.source_id, vintage)


BIS_INDICATORS = [
    indicator("bis_house_price_nominal", "House prices (nominal)",
              "Residential property prices in local currency, as published by the central bank or statistics office "
              "and collected by the BIS. Yearly average of the quarterly index, 2010 = 100.",
              "index, 2010 = 100", "housing", "bis", "WS_SPP:N.628", decimals=1),
    indicator("bis_house_price_real", "House prices (real)",
              "Residential property prices after consumer price inflation, collected by the BIS. "
              "Yearly average of the quarterly index, 2010 = 100.",
              "index, 2010 = 100", "housing", "bis", "WS_SPP:R.628", decimals=1),
    indicator("bis_household_credit_gdp", "Household debt (% of GDP)",
              "Credit to households and non-profit institutions serving households from all lenders, at market value, "
              "as a share of GDP; adjusted for breaks. Yearly average of the quarters.",
              "% of GDP", "housing", "bis", "WS_TC:Q..H.A.M.770.A", decimals=1),
]


# --------------------------------------------------------------------------------------------- OECD
OECD_API = "https://sdmx.oecd.org/public/rest/data/"
OECD_HOUSE = OECD_API + "OECD.ECO.MPD,DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES,1.0/.A..?format=csvfile"
OECD_HHDEBT = OECD_API + "OECD.SDD.NAD,DSD_HHDASH@DF_HHDASH_CTRY,1.0/A..LES1M_FD4.PT_B6G_S1M?format=csvfile"

# OECD measure -> (indicator, name, unit, description)
OECD_MEASURES = {
    "HPI": ("oecd_house_price_nominal", "House prices (nominal)", "index, 2015 = 100",
            "Nominal house price index, yearly, 2015 = 100."),
    "RHP": ("oecd_house_price_real", "House prices (real)", "index, 2015 = 100",
            "House prices deflated by the private consumption deflator, yearly, 2015 = 100."),
    "RPI": ("oecd_rent_prices", "Rent prices", "index, 2015 = 100", "Rent price index, yearly, 2015 = 100."),
    "HPI_RPI": ("oecd_price_to_rent", "House price to rent ratio", "index, 2015 = 100",
                "Nominal house prices divided by rents: how dear it is to buy compared with renting. 2015 = 100."),
    "HPI_YDH": ("oecd_price_to_income", "House price to income ratio", "index, 2015 = 100",
                "Nominal house prices divided by nominal disposable income per person: how affordable homes are. "
                "2015 = 100."),
    "HPI_RPI_AVG": ("oecd_price_to_rent_vs_avg", "House price to rent ratio vs long-run average", "% of average",
                    "The price-to-rent ratio as a percentage of its own long-run average (100 = average; above it, "
                    "buying is dearer than usual compared with renting)."),
    "HPI_YDH_AVG": ("oecd_price_to_income_vs_avg", "House price to income ratio vs long-run average", "% of average",
                    "The price-to-income ratio as a percentage of its own long-run average (100 = average; above it, "
                    "homes are less affordable than usual)."),
}


class OECD(Connector):
    source_id = "oecd"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(OECD_HOUSE, raw_dir / "house_prices.csv")
        try:
            self.get(OECD_HHDEBT, raw_dir / "household_debt.csv")
        except ConnectorError as exc:
            log.warning("oecd: household debt not downloaded (%s); house prices only", exc)
        return f"{OECD_HOUSE} {OECD_HHDEBT}"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for name in ("house_prices.csv", "household_debt.csv"):
            p = raw_dir / name
            if not p.exists():
                continue
            data = read_csv(p)
            if not data:
                continue
            h = data[0].keys()
            area, freq, measure, period, obs = (col(h, "REF_AREA"), col(h, "FREQ"), col(h, "MEASURE"),
                                                col(h, "TIME_PERIOD"), col(h, "OBS_VALUE"))
            if not all((area, period, obs)):
                raise ConnectorError(f"oecd: {name} lacks REF_AREA, TIME_PERIOD or OBS_VALUE")
            for r in data:
                if freq and code(r[freq]) not in ("A", ""):
                    continue
                if name == "household_debt.csv":
                    ind = "oecd_household_debt_income"
                else:
                    ind = OECD_MEASURES.get(code(r[measure]) if measure else "", (None,))[0]
                y = year_of(r[period])
                if ind and y and not re.search(r"Q|M", str(r[period])[4:]):
                    rows.add("iso3", code(r[area]), ind, y, num(r[obs]))
        if not len(rows):
            raise ConnectorError(f"oecd: no values read from {raw_dir}")
        self.listed_indicators = [
            indicator(i, n, d, u, "housing", "oecd", f"DF_HOUSE_PRICES:{m}", decimals=1)
            for m, (i, n, u, d) in OECD_MEASURES.items()
        ] + [indicator("oecd_household_debt_income", "Household debt (% of disposable income)",
                       "Debt of households and non-profit institutions serving households (loans and other "
                       "liabilities) as a share of their gross disposable income.",
                       "% of disposable income", "housing", "oecd", "DF_HHDASH_CTRY:LES1M_FD4.PT_B6G_S1M", decimals=1)]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------------------- Dallas Fed
DALLAS_PAGE = "https://www.dallasfed.org/research/international/houseprice"
DALLAS_SITE = "https://www.dallasfed.org"
DALLAS_SHEETS = (("HPI", "dfed_house_price_nominal"), ("RHPI", "dfed_house_price_real"),
                 ("PDI", "dfed_income_nominal"), ("RPDI", "dfed_income_real"))
# Column names the database uses that are not country names.
DALLAS_NAMES = {"us": "USA", "uk": "GBR", "skorea": "KOR", "safrica": "ZAF", "newzealand": "NZL", "nz": "NZL"}


class DallasFedIHPD(Connector):
    source_id = "dallas_fed_ihpd"
    fetch_every_days = 28  # quarterly releases

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:  # hp2502.xlsx: the release of February 2025
            if m := re.fullmatch(r"hp(\d{2})(\d{2})\.xlsx", f.name.lower()):
                return f"20{m.group(1)}-{m.group(2)}"
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        page = raw_dir / "page.html"
        self.get(DALLAS_PAGE, page)
        html = page.read_text(encoding="utf-8", errors="replace")
        page.unlink()
        links = re.findall(r"""href=["']([^"']*?hp\d{4}\.xlsx)["']""", html, flags=re.I)
        if not links:
            raise ConnectorError(f"dallas_fed_ihpd: no hpYYMM.xlsx link on {DALLAS_PAGE}; the page may have changed. "
                                 "Download the file by hand and load it with: worldmodel-data fetch dallas_fed_ihpd --from <file>")
        link = max(links, key=lambda u: re.search(r"hp(\d{4})", u, re.I).group(1))
        url = link if link.startswith("http") else DALLAS_SITE + link
        self.get(url, raw_dir / Path(url).name.lower())
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.xlsx"))
        if not files:
            raise ConnectorError(f"dallas_fed_ihpd: no .xlsx file in {raw_dir}")
        path = files[-1]
        names = xlsx_sheet_names(path)
        rows, unmatched = Rows(), set()
        values: dict[tuple[str, str, int], list[float]] = {}
        for pos, (sheet, ind) in enumerate(DALLAS_SHEETS, start=1):
            target = next((n for n in names if key(n) == key(sheet)), names[pos] if pos < len(names) else None)
            if target is None:
                raise ConnectorError(f"dallas_fed_ihpd: sheet {sheet} missing from {path.name}")
            table = xlsx_rows(path, target)
            head = next((i for i, r in enumerate(table[:10]) if sum(isinstance(c, str) for c in r[1:]) >= 5), None)
            if head is None:
                raise ConnectorError(f"dallas_fed_ihpd: no country names on sheet {target}")
            countries = [_dallas_country(c, unmatched) for c in table[head]]
            for r in table[head + 1:]:
                m = re.match(r"\s*(\d{4})\s*:?\s*Q([1-4])", str(r[0] or ""))
                if not m:
                    continue
                y = int(m.group(1))
                for c, v in zip(countries[1:], r[1:]):
                    if c and (x := num(v)) is not None:
                        values.setdefault((c, ind, y), []).append(x)
        if unmatched:
            log.info("dallas_fed_ihpd: columns left out (aggregates or unknown): %s", ", ".join(sorted(unmatched)))
        # Whole years only, and the latest year so far (its quarters to date).
        last = max((k[2] for k in values), default=0)
        yearly = {k: sum(v) / len(v) for k, v in values.items() if len(v) == 4 or k[2] == last}
        for (c, ind, y), v in yearly.items():
            rows.add("iso3", c, ind, y, v)
            if ind == "dfed_house_price_nominal" and (inc := yearly.get((c, "dfed_income_nominal", y))):
                rows.add("iso3", c, "dfed_price_to_income", y, 100 * v / inc)
        if not len(rows):
            raise ConnectorError(f"dallas_fed_ihpd: no values read from {path.name}")
        self.listed_indicators = DALLAS_INDICATORS
        return rows.stage(con, self.source_id, vintage)


def _dallas_country(name, unmatched: set[str]) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    k = key(name)
    if k.startswith("aggregate"):
        return None
    found = DALLAS_NAMES.get(k) or catalogue.country_by_name(name.strip())
    if not found:
        unmatched.add(name.strip())
    return found


DALLAS_NOTE = "Federal Reserve Bank of Dallas International House Price Database; yearly average of the quarters."
DALLAS_INDICATORS = [
    indicator("dfed_house_price_nominal", "House prices (nominal)",
              "Nominal house price index, 2005 = 100. " + DALLAS_NOTE, "index, 2005 = 100", "housing",
              "dallas_fed_ihpd", "HPI"),
    indicator("dfed_house_price_real", "House prices (real)",
              "House prices deflated by the personal consumption deflator, 2005 = 100. " + DALLAS_NOTE,
              "index, 2005 = 100", "housing", "dallas_fed_ihpd", "RHPI"),
    indicator("dfed_income_nominal", "Disposable income per person (nominal)",
              "Personal disposable income per person in local currency, as an index, 2005 = 100. " + DALLAS_NOTE,
              "index, 2005 = 100", "housing", "dallas_fed_ihpd", "PDI"),
    indicator("dfed_income_real", "Disposable income per person (real)",
              "Personal disposable income per person after inflation, as an index, 2005 = 100. " + DALLAS_NOTE,
              "index, 2005 = 100", "housing", "dallas_fed_ihpd", "RPDI"),
    indicator("dfed_price_to_income", "House price to income ratio",
              "Nominal house prices divided by nominal disposable income per person, 2005 = 100: above 100, homes "
              "cost more years of income than in 2005. " + DALLAS_NOTE,
              "index, 2005 = 100", "housing", "dallas_fed_ihpd", "HPI/PDI"),
]


# -------------------------------------------------------------------------------------------- IMF GDD
IMF_DM = "https://www.imf.org/external/datamapper/api/v1/"
IMF_GDD = {
    "HH_LS": ("imf_household_debt_gdp", "Household debt (% of GDP)",
              "Debt of households (loans and debt securities) as a share of GDP, from the IMF Global Debt Database."),
    "NFC_LS": ("imf_corporate_debt_gdp", "Corporate debt (% of GDP)",
               "Debt of non-financial companies (loans and debt securities) as a share of GDP, from the IMF Global "
               "Debt Database."),
}


class IMFGDD(Connector):
    source_id = "imf_gdd"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for series in IMF_GDD:
            self.get(IMF_DM + series, raw_dir / f"{series}.json")
        return " ".join(IMF_DM + s for s in IMF_GDD)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for series, (ind, _, _) in IMF_GDD.items():
            p = raw_dir / f"{series}.json"
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8")).get("values", {}).get(series, {})
            for iso, years in data.items():
                for y, v in (years or {}).items():
                    if re.fullmatch(r"\d{4}", y):
                        rows.add("iso3", iso, ind, int(y), num(v))
        if not len(rows):
            raise ConnectorError(f"imf_gdd: no values read from {raw_dir}")
        self.listed_indicators = [indicator(i, n, d, "% of GDP", "housing" if s == "HH_LS" else "economy", "imf_gdd", s)
                                  for s, (i, n, d) in IMF_GDD.items()]
        return rows.stage(con, self.source_id, vintage)
