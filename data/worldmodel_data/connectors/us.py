"""US states, DC and counties (Settings > US states and counties). Figures go to the
usreg_* indicators, kept apart from country figures so nothing on the world map changes.

us_census_pep
    Census Bureau population estimates, county totals files (CSV, keyless): people at 1 July,
    births, deaths and moves (domestic and international), for every state and county,
    2000 onward (co-est00int-tot, co-est2020-alldata, co-est2024-alldata and later).
us_acs
    Census API, American Community Survey 5-year estimates (free CENSUS_API_KEY): median
    household income, poverty, degrees, home values and rents, Gini, median age, born abroad,
    language at home; states and counties, 2009 onward.
bea_regional
    BEA regional accounts bulk zips (keyless): GDP (current and real) and personal income per
    person for states (1997-, 1929-) and counties (2001-, 1969-); regional price parities (states, 2008-).
us_unemployment
    FRED (fredgraph.csv, keyless): each state's unemployment rate (BLS local area figures),
    monthly from 1976, kept as yearly averages.
bls_laus_county
    BLS local area unemployment, county yearly averages, 1990 onward. With a free BLS_API_KEY the
    figures come from the BLS public API (about 130 questions the first time, 65 after); without
    one the yearly files (laucntyYY.xlsx) are tried, which BLS's firewall often turns away. A file
    saved by hand into var\\manual\\bls_laus_county is read instead either way.
fhfa_hpi
    FHFA house price index (keyless): states quarterly from 1975 (kept as yearly averages,
    2000 = 100), counties yearly.
mit_elections
    MIT Election Data and Science Lab, presidential votes by state 1976- (Harvard Dataverse, CC0).
mit_county_elections
    The same lab's county presidential returns 2000-, saved by hand (the file asks for a
    guestbook answer before it downloads).
chr_health
    County Health Rankings analytic data (CSV, keyless): life expectancy, premature death,
    uninsured, obesity and smoking, by county and state, for each release year listed.
eia_seds
    EIA State Energy Data System through the EIA API (EIA_API_KEY): energy used and produced
    by each state, 1960 onward, in petajoules.
us_shapes
    Census cartographic boundary files (public domain): state and county outlines, simplified,
    for the "Regions inside a country" maps.
ne_admin1
    Natural Earth admin-1 states and provinces (public domain): outlines of the regions the
    catalogue lists for other countries (New Zealand's 16 so far).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import Rows, indicator, num, xlsx_rows
from worldmodel_data.connectors.transport import stage_geo

log = logging.getLogger(__name__)

SWITCH = "us_fetch"
PEP = "https://www2.census.gov/programs-surveys/popest/datasets/"
PEP_FILES = {  # file -> path under PEP; later years are tried each refresh (co-est2025-alldata ...)
    "co-est00int-tot.csv": "2000-2010/intercensal/county/co-est00int-tot.csv",
    "co-est2020-alldata.csv": "2010-2020/counties/totals/co-est2020-alldata.csv",
}
ACS = "https://api.census.gov/data/{y}/acs/acs5"
BEA_ZIP = "https://apps.bea.gov/regional/zip/{name}.zip"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={ids}"
BLS_CTY = "https://www.bls.gov/lau/laucnty{yy}.xlsx"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_API_SERIES, BLS_API_YEARS = 50, 20  # most series and years one question may ask for (with a key)
FHFA_STATE = "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_state.csv"
FHFA_COUNTY = "https://www.fhfa.gov/hpi/download/annual/hpi_at_county.xlsx"
DATAVERSE = "https://dataverse.harvard.edu/api/"
MIT_STATE_DOI = "doi:10.7910/DVN/42MVDX"
CHR_PAGE = "https://www.countyhealthrankings.org/health-data/methodology-and-sources/data-documentation"
EIA_SEDS = ("https://api.eia.gov/v2/seds/data/?api_key={key}&frequency=annual&data[0]=value"
            "&facets[seriesId][]=TETCB&facets[seriesId][]=TEPRB&facets[seriesId][]=TETPB&offset={offset}&length=5000")
CB = "https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_us_{level}_5m.zip"
NE_ADMIN1 = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson"
NE_ADMIN1_FILE = "ne_10m_admin_1_states_provinces.geojson"

STATES = {  # FIPS -> postal code, for files that give only one of them
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY",
}
POSTAL = {v: k for k, v in STATES.items()}


def fips_of(state: str | int | None, county: str | int | None = None) -> str | None:
    """'06' for a state or '06037' for a county, from codes written with or without leading zeros.
    County 0 (or blank) is the state itself."""
    s = str(state or "").strip().strip('"')
    if not s.isdigit():
        return None
    s = s.zfill(2)
    if s not in STATES:
        return None
    c = str(county or "").strip().strip('"')
    if not c or not c.isdigit() or int(c) == 0:
        return s
    return s + c.zfill(3)


def fips5(code: str | int | None) -> str | None:
    """A FIPS code as found in files ('6037', '06037', ' "06000"'): state (2) or county (5) digits."""
    c = str(code or "").strip().strip('"').strip()
    if not c.isdigit():
        return None
    c = c.zfill(5)
    return fips_of(c[:2], c[2:])


class USConnector(Connector):
    """Shared set-up: the Settings switch, a monthly check, releases named by the day."""
    switch = SWITCH
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def try_get(self, url: str, dest: Path, **kw) -> bool:
        """Download, or log why not and carry on (one missing file should not stop the rest)."""
        try:
            self.get(url, dest, **kw)
            return dest.exists() and dest.stat().st_size > 0
        except (httpx.HTTPError, ConnectorError, OSError) as exc:
            log.info("%s: could not fetch %s (%s)", self.source_id, re.sub(r"(api_key|key)=[^&]+", r"\1=...", url), exc)
            dest.unlink(missing_ok=True)
            return False


def _ind(id: str, name: str, desc: str, unit: str, domain: str, source: str, series: str, **kw) -> dict:
    kw.setdefault("default_on", False)  # region figures stay off the world map's menus
    return indicator(id, name, desc, unit, domain, source, series, **kw)


# ------------------------------------------------------------------------------- population (PEP)
PEP_MEASURES = {  # column stem -> indicator
    "POPESTIMATE": "usreg_population", "BIRTHS": "usreg_births", "DEATHS": "usreg_deaths",
    "DOMESTICMIG": "usreg_domestic_migration", "INTERNATIONALMIG": "usreg_international_migration",
}


def pep_rows(path: Path, rows: Rows) -> int:
    n = 0
    raw = path.read_bytes()
    text = raw.decode("utf-8") if not re.search(rb"[\x80-\xff]", raw) or _utf8(raw) else raw.decode("latin-1")
    for r in csv.DictReader(io.StringIO(text)):
        f = fips_of(r.get("STATE"), r.get("COUNTY"))
        if not f or str(r.get("SUMLEV", "")).lstrip("0") not in ("40", "50"):
            continue
        for k, v in r.items():
            m = re.fullmatch(r"([A-Z]+?)_?(\d{4})", k or "")
            if m and m.group(1) in PEP_MEASURES:
                rows.add("us_fips", f, PEP_MEASURES[m.group(1)], int(m.group(2)), num(v))
                n += 1
    return n


def _utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


class USCensusPEP(USConnector):
    source_id = "us_census_pep"

    def download(self, raw_dir: Path, release: str) -> str:
        for name, path in PEP_FILES.items():
            self.get(PEP + path, raw_dir / name)
        # The current decade's file is named by its last year; try this year back to 2024.
        for y in range(date.today().year, 2023, -1):
            name = f"co-est{y}-alldata.csv"
            if self.try_get(PEP + f"2020-{y}/counties/totals/{name}", raw_dir / name):
                break
        return PEP

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        # Older files first: a later file's estimate for the same year (2010, 2020) replaces the earlier one.
        files = sorted(raw_dir.glob("co-est*.csv"), key=lambda p: (0 if "00int" in p.name else 1, p.name))
        keyed: dict[tuple, tuple] = {}
        for p in files:
            r = Rows()
            pep_rows(p, r)
            for row in r.rows:
                keyed[row[:5]] = row
        rows.rows = list(keyed.values())
        if not rows:
            raise ConnectorError(f"us_census_pep: no figures read from {raw_dir}")
        src = self.source_id
        self.listed_indicators = [
            _ind("usreg_population", "Population (US states and counties)", "People living in each state and county at 1 July, "
                 "Census Bureau population estimates (intercensal for 2000-2010).", "people", "population", src, "POPESTIMATE",
                 decimals=0, bounds=(0, 1e9)),
            _ind("usreg_births", "Births (US states and counties)", "Births in the year to 1 July, Census Bureau estimates.",
                 "births a year", "population", src, "BIRTHS", decimals=0, bounds=(0, 1e8)),
            _ind("usreg_deaths", "Deaths (US states and counties)", "Deaths in the year to 1 July, Census Bureau estimates.",
                 "deaths a year", "population", src, "DEATHS", decimals=0, bounds=(0, 1e8)),
            _ind("usreg_domestic_migration", "Net moves from other states (US states and counties)", "People moving in from "
                 "elsewhere in the US less people moving out, in the year to 1 July (for a county: other counties).",
                 "people a year", "migration", src, "DOMESTICMIG", decimals=0, bounds=(-1e8, 1e8)),
            _ind("usreg_international_migration", "Net moves from abroad (US states and counties)", "People arriving from "
                 "abroad less people leaving, in the year to 1 July, Census Bureau estimates.", "people a year", "migration",
                 src, "INTERNATIONALMIG", decimals=0, bounds=(-1e8, 1e8)),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- ACS 5-year
# indicator -> (variables, how): "v" the first variable as it is; "share" 100 x first / second;
# "share_sum" 100 x sum of all but the last / the last; "rest" 100 x (1 - first / second).
ACS_MEASURES = {
    "usreg_median_household_income": (["B19013_001E"], "v"),
    "usreg_poverty_rate": (["B17001_002E", "B17001_001E"], "share"),
    "usreg_degree_share": (["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E", "B15003_001E"], "share_sum"),
    "usreg_median_home_value": (["B25077_001E"], "v"),
    "usreg_median_rent": (["B25064_001E"], "v"),
    "usreg_gini": (["B19083_001E"], "v"),
    "usreg_median_age": (["B01002_001E"], "v"),
    "usreg_born_abroad_share": (["B05002_013E", "B05002_001E"], "share"),
    "usreg_other_language_share": (["B16001_002E", "B16001_001E"], "rest"),
}


def acs_value(how: str, vals: list[float | None]) -> float | None:
    if any(v is None for v in vals) or any(v < 0 for v in vals if v is not None):  # -666666666: not available
        return None
    if how == "v":
        return vals[0]
    if not vals[-1]:
        return None
    if how == "share":
        return 100 * vals[0] / vals[1]
    if how == "share_sum":
        return 100 * sum(vals[:-1]) / vals[-1]
    if how == "rest":
        return 100 * (1 - vals[0] / vals[1])
    return None


def acs_rows(path: Path, year: int, rows: Rows) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data or len(data) < 2:
        return 0
    head, n = data[0], 0
    at = {h: i for i, h in enumerate(head)}
    for r in data[1:]:
        f = fips_of(r[at["state"]], r[at["county"]] if "county" in at else None)
        if not f:
            continue
        for ind, (vars_, how) in ACS_MEASURES.items():
            if all(v in at for v in vars_):
                v = acs_value(how, [num(r[at[x]]) for x in vars_])
                if v is not None:
                    rows.add("us_fips", f, ind, year, v)
                    n += 1
    return n


class USACS(USConnector):
    source_id = "us_acs"
    needs_env = ("CENSUS_API_KEY",)
    keeps_files = True  # earlier years do not change; only the newest two are asked for again

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("CENSUS_API_KEY")
        last = self.last_vintage_dir(raw_dir)
        newest = date.today().year - 1  # the 5-year figures ending last year come out in December
        got = 0
        for y in range(2009, newest + 1):
            for geo in ("state", "county"):
                name = f"acs5_{y}_{geo}.json"
                if last and (last / name).exists() and y < newest - 1:
                    continue  # carried over by keeps_files
                # One request per group of variables, so a table missing that year loses only its own figures.
                parts = []
                for ind, (vars_, _how) in ACS_MEASURES.items():
                    url = f"{ACS.format(y=y)}?get=NAME,{','.join(vars_)}&for={geo}:*&key={key}"
                    tmp = raw_dir / f"_{name}.{ind}"
                    if self.try_get(url, tmp, cached=False):
                        try:
                            parts.append(json.loads(tmp.read_text(encoding="utf-8")))
                        except json.JSONDecodeError:
                            log.info("us_acs: %s %s %s gave no table", y, geo, ind)
                    tmp.unlink(missing_ok=True)
                    time.sleep(0.2)
                if parts:
                    (raw_dir / name).write_text(json.dumps(_join_acs(parts)), encoding="utf-8")
                    got += 1
        if not got and not last:
            raise ConnectorError("us_acs: the Census API gave nothing (is CENSUS_API_KEY right?)")
        return ACS.format(y="{year}")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.glob("acs5_*.json")):
            m = re.match(r"acs5_(\d{4})_", p.name)
            if m:
                acs_rows(p, int(m.group(1)), rows)
        if not rows:
            raise ConnectorError(f"us_acs: no figures read from {raw_dir}")
        src, s = self.source_id, "ACS 5-year estimates (the five years ending in the year shown)"
        self.listed_indicators = [
            _ind("usreg_median_household_income", "Median household income (US states and counties)",
                 f"Half of households have more, half less, in dollars of the year. Census {s}, B19013.", "US$", "economy", src,
                 "B19013", decimals=0, bounds=(0, 1e6)),
            _ind("usreg_poverty_rate", "People in poverty (US states and counties)", f"Share of people below the official "
                 f"poverty line. Census {s}, B17001.", "%", "economy", src, "B17001", bounds=(0, 100)),
            _ind("usreg_degree_share", "Adults with a degree (US states and counties)", f"Share of people 25 and over with a "
                 f"bachelor's degree or higher. Census {s}, B15003 (from 2012).", "%", "education", src, "B15003", bounds=(0, 100)),
            _ind("usreg_median_home_value", "Median home value (US states and counties)", f"Owners' own estimate of their "
                 f"home's value, middle of the range. Census {s}, B25077.", "US$", "housing", src, "B25077", decimals=0,
                 bounds=(0, 1e7)),
            _ind("usreg_median_rent", "Median rent (US states and counties)", f"Gross rent (rent plus utilities) a month, "
                 f"middle of the range. Census {s}, B25064.", "US$ a month", "housing", src, "B25064", decimals=0, bounds=(0, 1e5)),
            _ind("usreg_gini", "Income inequality, Gini (US states and counties)", f"Gini index of household income, 0 (all "
                 f"equal) to 1 (one household has all). Census {s}, B19083.", "index (0-1)", "economy", src, "B19083",
                 decimals=3, bounds=(0, 1)),
            _ind("usreg_median_age", "Median age (US states and counties)", f"Half the people are older, half younger. "
                 f"Census {s}, B01002.", "years", "population", src, "B01002", bounds=(0, 100)),
            _ind("usreg_born_abroad_share", "Born abroad (US states and counties)", f"Share of people born outside the US. "
                 f"Census {s}, B05002.", "%", "migration", src, "B05002", bounds=(0, 100)),
            _ind("usreg_other_language_share", "Speak another language at home (US states and counties)", f"Share of people 5 "
                 f"and over who speak a language other than English at home. Census {s}, B16001.", "%", "population", src,
                 "B16001", bounds=(0, 100)),
        ]
        return rows.stage(con, self.source_id, vintage)


def _join_acs(parts: list[list[list]]) -> list[list]:
    """Census API tables for the same places side by side, joined on their place codes."""
    geo_cols = ("state", "county")
    head: list[str] = []
    by: dict[tuple, dict] = {}
    for t in parts:
        h = t[0]
        g = [h.index(c) for c in geo_cols if c in h]
        for c in h:
            if c not in head:
                head.append(c)
        for r in t[1:]:
            by.setdefault(tuple(r[i] for i in g), {}).update(dict(zip(h, r)))
    return [head] + [[d.get(c) for c in head] for d in by.values()]


# ------------------------------------------------------------------------------- BEA
BEA_TABLES = {  # zip -> {member prefix: {line: (indicator, scale)}}
    "SAGDP": {"SAGDP1__ALL_AREAS": {"1": ("usreg_real_gdp", 1.0), "3": ("usreg_gdp", 1.0)}},
    "SAINC": {"SAINC1__ALL_AREAS": {"3": ("usreg_income_per_person", 1.0)}},
    "CAGDP1": {"CAGDP1__ALL_AREAS": {"1": ("usreg_real_gdp", 0.001), "3": ("usreg_gdp", 0.001)}},
    "CAINC1": {"CAINC1__ALL_AREAS": {"3": ("usreg_income_per_person", 1.0)}},
    "SARPP": {"SARPP_STATE": {"1": ("usreg_price_level", 1.0)}},
}


def bea_rows(path: Path, lines: dict[str, tuple[str, float]], rows: Rows, states_only: bool = False,
             counties_only: bool = False) -> int:
    """Figures from one BEA regional table. The county tables (CA...) also carry each state's
    total, which the state tables (SA...) already give: read only one level from each."""
    n = 0
    with path.open(encoding="latin-1", newline="") as f:
        rd = csv.reader(f)
        head = next(rd, None)
        if not head:
            return 0
        years = {i: int(h) for i, h in enumerate(head) if h.strip().isdigit()}
        at = {h.strip(): i for i, h in enumerate(head)}
        for r in rd:
            if len(r) < len(head) - 1 or "LineCode" not in at:
                continue
            line = r[at["LineCode"]].strip()
            if line not in lines:
                continue
            fips = fips5(r[at["GeoFIPS"]])
            if not fips or (states_only and len(fips) != 2) or (counties_only and len(fips) == 2):
                continue
            ind, scale = lines[line]
            for i, y in years.items():
                v = num(r[i]) if i < len(r) else None
                if v is not None:
                    rows.add("us_fips", fips, ind, y, v * scale)
                    n += 1
    return n


class BEARegional(USConnector):
    source_id = "bea_regional"
    stage_version = 2  # 2: states from the state tables only (the county tables repeat them)

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for name, members in BEA_TABLES.items():
            zp = raw_dir / f"_{name}.zip"
            if not self.try_get(BEA_ZIP.format(name=name), zp):
                continue
            try:  # keep only the tables read (the zips hold dozens), not the 30 MB of the rest
                with zipfile.ZipFile(zp) as z:
                    for m in z.namelist():
                        if m.endswith(".csv") and any(m.startswith(p) for p in members):
                            (raw_dir / m).write_bytes(z.read(m))
                            got += 1
            except zipfile.BadZipFile:
                log.info("bea_regional: %s.zip was not a zip file", name)
            zp.unlink(missing_ok=True)
        if not got:
            raise ConnectorError("bea_regional: none of the BEA zip files could be read")
        return BEA_ZIP.format(name="{table}")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for members in BEA_TABLES.values():
            for prefix, lines in members.items():
                for p in sorted(raw_dir.glob(prefix + "*.csv")):
                    bea_rows(p, lines, rows, states_only=prefix.startswith("SA"), counties_only=prefix.startswith("CA"))
        if not rows:
            raise ConnectorError(f"bea_regional: no figures read from {raw_dir}")
        src = self.source_id
        self.listed_indicators = [
            _ind("usreg_gdp", "GDP (US states and counties)", "Gross domestic product in current dollars. BEA regional "
                 "accounts SAGDP1 (states, 1997-) and CAGDP1 (counties, 2001-).", "US$ million", "economy", src, "GDP line 3",
                 bounds=(0, 1e8)),
            _ind("usreg_real_gdp", "Real GDP (US states and counties)", "GDP in chained 2017 dollars, so years can be compared. "
                 "BEA SAGDP1 and CAGDP1, line 1.", "US$ million (2017)", "economy", src, "GDP line 1", bounds=(0, 1e8)),
            _ind("usreg_income_per_person", "Personal income per person (US states and counties)", "All income received by "
                 "people living there (pay, business income, rents, dividends, benefits) divided by population. BEA SAINC1 "
                 "(states, 1929-) and CAINC1 (counties, 1969-).", "US$", "economy", src, "INC line 3", decimals=0, bounds=(0, 1e7)),
            _ind("usreg_price_level", "Price level (US states)", "Regional price parity: what the same goods and services "
                 "cost there, US average = 100. BEA SARPP, all items.", "index, US = 100", "economy", src, "SARPP line 1",
                 bounds=(0, 300)),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- unemployment
def fred_columns(path: Path) -> dict[str, list[tuple[date, float]]]:
    """series id -> [(date, value)] from a fredgraph.csv with one or more series."""
    out: dict[str, list[tuple[date, float]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        head = next(rd, None) or []
        for r in rd:
            try:
                d = date.fromisoformat(r[0].strip()[:10])
            except (ValueError, IndexError):
                continue
            for i, sid in enumerate(head[1:], start=1):
                v = num(r[i]) if i < len(r) else None
                if v is not None:
                    out.setdefault(sid.strip(), []).append((d, v))
    return out


class USUnemployment(USConnector):
    source_id = "us_unemployment"
    fetch_every_days = 14

    def download(self, raw_dir: Path, release: str) -> str:
        ids = [f"{p}UR" for p in sorted(POSTAL)]
        got = 0
        for i in range(0, len(ids), 10):
            if self.try_get(FRED.format(ids=",".join(ids[i:i + 10])), raw_dir / f"state_ur_{i // 10 + 1:02d}.csv"):
                got += 1
            time.sleep(1)
        if not got:
            raise ConnectorError("us_unemployment: FRED gave no state figures")
        return FRED.format(ids="CAUR,TXUR,...")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        months: dict[tuple[str, int], int] = {}
        for p in sorted(raw_dir.glob("state_ur_*.csv")):
            for sid, pts in fred_columns(p).items():
                fips = POSTAL.get(sid[:-2]) if sid.endswith("UR") else None
                if not fips:
                    continue
                for d, v in pts:
                    rows.add_period("us_fips", fips, "usreg_unemployment_rate", d.year, v)
                    months[(fips, d.year)] = months.get((fips, d.year), 0) + 1
        rows.finish_periods(need=12)  # whole years only: a part year is not a yearly average
        if not rows:
            raise ConnectorError(f"us_unemployment: no figures read from {raw_dir}")
        self.listed_indicators = [unemployment_indicator(self.source_id, "{ST}UR")]
        return rows.stage(con, self.source_id, vintage)


def unemployment_indicator(source: str, series: str) -> dict:
    return _ind("usreg_unemployment_rate", "Unemployment rate (US states and counties)", "Share of the labour force out of "
                "work and looking, yearly average. BLS local area unemployment statistics (states through FRED, counties "
                "from BLS's yearly county files).", "%", "economy", source, series, bounds=(0, 100))


def laus_county_rows(path: Path, rows: Rows) -> int:
    """BLS laucntyYY.xlsx (or a .csv/.txt saved from it): LAUS code, state FIPS, county FIPS,
    name, year, labour force, employed, unemployed, rate."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        table = xlsx_rows(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        table = [re.split(r"\t|\s{2,}|,|\|", ln.strip()) for ln in text.splitlines()]
    n = 0
    for r in table:
        cells = [c for c in r if c not in (None, "")]
        if len(cells) < 9:
            continue
        st, co = (str(c).strip().split(".")[0] for c in cells[1:3])
        fips = fips_of(st, co) if co.isdigit() and int(co) > 0 else None
        y, rate = num(cells[4]), num(cells[-1])
        if not fips or len(fips) != 5 or y is None or not 1970 < y < 2100 or rate is None:
            continue
        rows.add("us_fips", fips, "usreg_unemployment_rate", int(y), rate)
        n += 1
    return n


def laus_api_rows(path: Path, rows: Rows) -> int:
    """A saved BLS API answer: series LAUCN<fips>0000000003 (unemployment rate), period M13 (the year's average)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for s in ((doc.get("Results") or {}).get("series") or []):
        m = re.fullmatch(r"LAUCN(\d{5})0000000003", s.get("seriesID", ""))
        fips = fips5(m.group(1)) if m else None
        if not fips or len(fips) != 5:
            continue
        for d in s.get("data") or []:
            y, v = num(d.get("year")), num(d.get("value"))
            if d.get("period") == "M13" and y is not None and v is not None:
                rows.add("us_fips", fips, "usreg_unemployment_rate", int(y), v)
                n += 1
    return n


def county_fips() -> list[str]:
    """Every county's FIPS code in the catalogue (counties that have ended too, for their older years)."""
    return sorted({c["code"] for c in catalogue.entity_codes() if c["scheme"] == "us_fips" and len(c["code"] or "") == 5})


class BLSLAUSCounty(USConnector):
    source_id = "bls_laus_county"
    keeps_files = True  # past years do not change; the last two are asked for each time
    stage_version = 2   # also reads saved BLS API answers (laus_api_*.json)

    def download(self, raw_dir: Path, release: str) -> str:
        import os

        key = os.environ.get("BLS_API_KEY", "").strip()
        if key:
            return self._from_api(raw_dir, key)
        last = self.last_vintage_dir(raw_dir)
        newest = date.today().year - 1
        got = 0
        for y in range(1990, newest + 1):
            name = f"laucnty{y % 100:02d}.xlsx"
            if last and (last / name).exists() and y < newest - 1:
                continue
            if self.try_get(BLS_CTY.format(yy=f"{y % 100:02d}"), raw_dir / name):
                got += 1
            elif got == 0 and y == 1990:
                raise ConnectorError("bls_laus_county: BLS turned the download away. Add a free BLS_API_KEY "
                                     "(Settings > Keys; sign up at https://data.bls.gov/registrationEngine/) or save "
                                     "the county files by hand (var\\manual\\bls_laus_county)")
            time.sleep(1)
        return BLS_CTY.format(yy="YY")

    def _from_api(self, raw_dir: Path, key: str) -> str:
        """Ask the BLS API for every county's yearly average rate, 50 counties and 20 years a question.
        Spans that ended more than two years ago are carried over from the last vintage, not asked again."""
        last = self.last_vintage_dir(raw_dir)
        newest = date.today().year - 1
        fips = county_fips()
        batches = [fips[i:i + BLS_API_SERIES] for i in range(0, len(fips), BLS_API_SERIES)]
        asked = got = 0
        for start in range(1990, newest + 1, BLS_API_YEARS):
            end = min(start + BLS_API_YEARS - 1, newest)
            for i, batch in enumerate(batches):
                name = f"laus_api_{start}_{i:03d}.json"
                if last and (last / name).exists() and end < newest - 1:
                    continue
                body = {"seriesid": [f"LAUCN{f}0000000003" for f in batch], "startyear": str(start),
                        "endyear": str(end), "annualaverage": True, "registrationkey": key}
                if asked:
                    time.sleep(0.5)
                asked += 1
                try:
                    r = self.client.post(BLS_API, json=body, timeout=60)
                    doc = r.json() if r.status_code == 200 else {}
                except (httpx.HTTPError, ValueError) as exc:
                    log.info("bls_laus_county: the BLS API did not answer (%s)", exc)
                    doc = {}
                status = doc.get("status")
                if status != "REQUEST_SUCCEEDED":
                    said = "; ".join(str(m) for m in doc.get("message") or []) or f"HTTP {getattr(r, 'status_code', '?')}"
                    if got == 0:
                        raise ConnectorError(f"bls_laus_county: the BLS API turned the question away ({said[:200]}). "
                                             "Is BLS_API_KEY right? (a key allows 500 questions a day)")
                    log.info("bls_laus_county: stopped after %s answers (%s); the next refresh asks for the rest",
                             got, said[:200])
                    return BLS_API
                (raw_dir / name).write_text(json.dumps({"status": status, "Results": doc.get("Results")}), encoding="utf-8")
                got += 1
        log.info("bls_laus_county: %s answers from the BLS API (%s counties)", got, len(fips))
        return BLS_API

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        files = sorted(raw_dir.iterdir())
        for p in files:  # API answers first: a year also in a saved file keeps the API's figure
            if p.name.startswith("laus_api_") and p.suffix.lower() == ".json":
                laus_api_rows(p, rows)
        for p in files:
            if p.suffix.lower() in (".xlsx", ".xlsm", ".txt", ".csv"):
                laus_county_rows(p, rows)
        seen: set[tuple] = set()
        rows.rows = [r for r in rows.rows if (r[1], r[3]) not in seen and not seen.add((r[1], r[3]))]
        if not rows:
            raise ConnectorError(f"bls_laus_county: no county figures read from {raw_dir}")
        self.listed_indicators = [unemployment_indicator(self.source_id, "laucnty")]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- house prices
def rebase(series: dict[int, float], base: int = 2000) -> dict[int, float]:
    b = series.get(base)
    return {y: 100 * v / b for y, v in series.items()} if b else {}


def fhfa_state_rows(path: Path, rows: Rows) -> int:
    quarters: dict[str, dict[int, list[float]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 4 or r[0].strip().upper() not in POSTAL:
                continue
            y, v = num(r[1]), num(r[3])
            if y is not None and v is not None:
                quarters.setdefault(POSTAL[r[0].strip().upper()], {}).setdefault(int(y), []).append(v)
    n = 0
    for fips, ys in quarters.items():
        yearly = {y: sum(v) / len(v) for y, v in ys.items() if len(v) == 4}
        for y, v in rebase(yearly).items():
            rows.add("us_fips", fips, "usreg_house_prices", y, v)
            n += 1
        for y, v in yearly.items():
            if y - 1 in yearly:
                rows.add("us_fips", fips, "usreg_house_price_change", y, 100 * (v / yearly[y - 1] - 1))
    return n


def fhfa_county_rows(path: Path, rows: Rows) -> int:
    """FHFA's yearly county file: a header row naming FIPS code, Year, Annual Change (%), HPI and
    HPI with 2000 base (older copies lack the last)."""
    table = xlsx_rows(path) if path.suffix.lower().startswith(".xls") else list(csv.reader(path.open(encoding="utf-8-sig")))
    head_at, cols = None, {}
    for i, r in enumerate(table[:40]):
        names = [str(c or "").strip().lower() for c in r]
        if any("fips" in c for c in names) and "year" in names:
            head_at = i
            for j, c in enumerate(names):
                if "fips" in c:
                    cols["fips"] = j
                elif c == "year":
                    cols["year"] = j
                elif "change" in c:
                    cols["change"] = j
                elif "2000" in c:
                    cols["hpi2000"] = j
                elif c == "hpi":
                    cols["hpi"] = j
            break
    if head_at is None:
        return 0
    n, raw = 0, {}
    for r in table[head_at + 1:]:
        if len(r) <= max(cols.values()):
            continue
        fips, y = fips5(str(r[cols["fips"]]).split(".")[0]), num(r[cols["year"]])
        if not fips or len(fips) != 5 or y is None:
            continue
        y = int(y)
        if "hpi2000" in cols and num(r[cols["hpi2000"]]) is not None:
            rows.add("us_fips", fips, "usreg_house_prices", y, num(r[cols["hpi2000"]]))
            n += 1
        elif "hpi" in cols and num(r[cols["hpi"]]) is not None:
            raw.setdefault(fips, {})[y] = num(r[cols["hpi"]])
        if "change" in cols:
            rows.add("us_fips", fips, "usreg_house_price_change", y, num(r[cols["change"]]))
    for fips, ys in raw.items():
        for y, v in rebase(ys).items():
            rows.add("us_fips", fips, "usreg_house_prices", y, v)
            n += 1
    return n


class FHFAHPI(USConnector):
    source_id = "fhfa_hpi"

    def download(self, raw_dir: Path, release: str) -> str:
        ok = self.try_get(FHFA_STATE, raw_dir / "hpi_at_state.csv")
        ok = self.try_get(FHFA_COUNTY, raw_dir / "hpi_at_county.xlsx") or ok
        if not ok:
            raise ConnectorError("fhfa_hpi: neither FHFA file could be fetched")
        return "https://www.fhfa.gov/data/hpi/datasets"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        if (raw_dir / "hpi_at_state.csv").exists():
            fhfa_state_rows(raw_dir / "hpi_at_state.csv", rows)
        for p in raw_dir.glob("hpi_at_county.*"):
            fhfa_county_rows(p, rows)
        if not rows:
            raise ConnectorError(f"fhfa_hpi: no figures read from {raw_dir}")
        src = self.source_id
        self.listed_indicators = [
            _ind("usreg_house_prices", "House prices (US states and counties)", "FHFA all-transactions house price index, "
                 "yearly average, 2000 = 100 (repeat sales and appraisals of the same homes).", "index, 2000 = 100", "housing",
                 src, "HPI_AT", bounds=(0, 5000)),
            _ind("usreg_house_price_change", "House price change (US states and counties)", "Change in the FHFA all-transactions "
                 "house price index on the year before.", "% a year", "housing", src, "HPI_AT change", bounds=(-100, 500)),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- elections
def president_rows(path: Path, rows: Rows, county: bool) -> int:
    """MIT's president files: one row per candidate (and, for counties, per way of voting:
    a candidate's TOTAL row where given, else that candidate's modes added up). The total is
    the file's totalvotes where given, else the candidates' votes added up."""
    votes: dict[tuple[str, int], dict[str, float]] = {}
    totals: dict[tuple[str, int], float] = {}
    has_total_mode: set[tuple[str, int, str]] = set()
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        rd = csv.DictReader(f, delimiter="\t" if sample.count("\t") > sample.count(",") else ",")
        rows_ = list(rd)
    for r in rows_:
        mode = (r.get("mode") or "TOTAL").strip().upper()
        if county and mode == "TOTAL":
            f = fips5(r.get("county_fips"))
            if f:
                has_total_mode.add((f, int(num(r.get("year")) or 0), (r.get("candidate") or "").strip().upper()))
    for r in rows_:
        y = num(r.get("year"))
        if y is None:
            continue
        f = fips5(r.get("county_fips")) if county else fips_of(r.get("state_fips"))
        if not f or (county and len(f) != 5):
            continue
        k = (f, int(y))
        mode = (r.get("mode") or "TOTAL").strip().upper()
        if county and (*k, (r.get("candidate") or "").strip().upper()) in has_total_mode and mode != "TOTAL":
            continue
        party = (r.get("party_simplified") or r.get("party") or "").strip().upper()
        v = num(r.get("candidatevotes")) or 0.0
        d = votes.setdefault(k, {})
        d[party] = d.get(party, 0.0) + v
        d["_all"] = d.get("_all", 0.0) + v
        totals[k] = num(r.get("totalvotes")) or totals.get(k, 0.0)
    n = 0
    for (f, y), d in votes.items():
        total = totals.get((f, y)) or d["_all"]
        if not total:
            continue
        rows.add("us_fips", f, "usreg_pres_votes", y, total)
        rows.add("us_fips", f, "usreg_pres_dem_share", y, 100 * d.get("DEMOCRAT", 0.0) / total)
        rows.add("us_fips", f, "usreg_pres_rep_share", y, 100 * d.get("REPUBLICAN", 0.0) / total)
        n += 3
    return n


def election_indicators(source: str) -> list[dict]:
    return [
        _ind("usreg_pres_dem_share", "Democratic share, presidential vote (US states and counties)", "Share of all "
             "presidential votes cast for the Democratic candidate. MIT Election Data and Science Lab.", "%", "politics",
             source, "DEMOCRAT", bounds=(0, 100)),
        _ind("usreg_pres_rep_share", "Republican share, presidential vote (US states and counties)", "Share of all "
             "presidential votes cast for the Republican candidate. MIT Election Data and Science Lab.", "%", "politics",
             source, "REPUBLICAN", bounds=(0, 100)),
        _ind("usreg_pres_votes", "Presidential votes cast (US states and counties)", "All votes counted for president. MIT "
             "Election Data and Science Lab.", "votes", "politics", source, "totalvotes", decimals=0, bounds=(0, 1e9)),
    ]


class MITElections(USConnector):
    source_id = "mit_elections"
    fetch_every_days = 90

    def download(self, raw_dir: Path, release: str) -> str:
        meta = raw_dir / "_dataset.json"
        self.get(f"{DATAVERSE}datasets/:persistentId/?persistentId={MIT_STATE_DOI}", meta, cached=False)
        files = json.loads(meta.read_text(encoding="utf-8"))["data"]["latestVersion"]["files"]
        meta.unlink()
        pick = [f for f in files if re.search(r"president\.(csv|tab)$", f.get("label", ""))]
        if not pick:
            raise ConnectorError("mit_elections: the Dataverse listing has no president file")
        f = pick[0]
        self.get(f"{DATAVERSE}access/datafile/{f['dataFile']['id']}?format=original", raw_dir / "president_state.csv")
        return f"https://doi.org/{MIT_STATE_DOI[4:]}"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in raw_dir.glob("*.csv"):
            president_rows(p, rows, county=False)
        if not rows:
            raise ConnectorError(f"mit_elections: no votes read from {raw_dir}")
        self.listed_indicators = election_indicators(self.source_id)
        return rows.stage(con, self.source_id, vintage)


class MITCountyElections(USConnector):
    """County presidential returns 2000-: the Dataverse file needs a guestbook answer, so it is saved by hand."""
    source_id = "mit_county_elections"
    manual = True
    switch = None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("mit_county_elections: saved by hand into var\\manual\\mit_county_elections")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() in (".tab", ".csv", ".txt"):
                president_rows(p, rows, county=True)
        if not rows:
            raise ConnectorError(f"mit_county_elections: no county votes read from {raw_dir}")
        self.listed_indicators = election_indicators(self.source_id)
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- health
CHR_MEASURES = {  # code -> (indicator, multiplier)
    "v147": ("usreg_life_expectancy", 1.0), "v001": ("usreg_premature_death", 1.0), "v085": ("usreg_uninsured", 100.0),
    "v011": ("usreg_adult_obesity", 100.0), "v009": ("usreg_adult_smoking", 100.0),
}


def chr_rows(path: Path, rows: Rows) -> int:
    """analytic_dataYYYY.csv: a row of long names, a row of codes (statecode, countycode, year,
    v001_rawvalue ...), then one row per county and state."""
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.reader(f)
        first = next(rd, [])
        codes = first if "statecode" in first else next(rd, [])
        at = {c.strip(): i for i, c in enumerate(codes)}
        if "statecode" not in at:
            return 0
        n = 0
        m = re.search(r"(20\d\d)", path.name)
        for r in rd:
            if len(r) < len(codes) // 2:
                continue
            f_ = fips_of(r[at["statecode"]], r[at["countycode"]])
            y = num(r[at["year"]]) if "year" in at else (int(m.group(1)) if m else None)
            if not f_ or y is None:
                continue
            for code, (ind, mult) in CHR_MEASURES.items():
                i = at.get(f"{code}_rawvalue")
                v = num(r[i]) if i is not None and i < len(r) else None
                if v is not None:
                    rows.add("us_fips", f_, ind, int(y), v * mult)
                    n += 1
    return n


class CountyHealthRankings(USConnector):
    source_id = "chr_health"
    fetch_every_days = 90

    def download(self, raw_dir: Path, release: str) -> str:
        page = raw_dir / "_page.html"
        self.get(CHR_PAGE, page, cached=False)
        links = sorted(set(re.findall(r'href="([^"]*analytic_data(20\d\d)[^"]*\.csv)"', page.read_text(encoding="utf-8", errors="replace"))),
                       key=lambda t: t[1], reverse=True)
        page.unlink()
        got, seen = 0, set()
        for href, year in links:
            if year in seen:
                continue
            seen.add(year)
            url = href if href.startswith("http") else "https://www.countyhealthrankings.org" + href
            if self.try_get(url, raw_dir / f"analytic_data{year}.csv"):
                got += 1
            time.sleep(1)
        if not got:
            raise ConnectorError("chr_health: no analytic data file found on the County Health Rankings page")
        return CHR_PAGE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.glob("analytic_data*.csv")):
            chr_rows(p, rows)
        if not rows:
            raise ConnectorError(f"chr_health: no figures read from {raw_dir}")
        src, s = self.source_id, "County Health Rankings & Roadmaps, by release year (the data are from one to three years before)"
        self.listed_indicators = [
            _ind("usreg_life_expectancy", "Life expectancy (US states and counties)", f"Years a newborn could expect to live at "
                 f"today's death rates. {s}.", "years", "health", src, "v147", bounds=(0, 120)),
            _ind("usreg_premature_death", "Premature death (US states and counties)", f"Years of life lost before 75, per "
                 f"100,000 people (age-adjusted). {s}.", "years per 100,000", "health", src, "v001", decimals=0, bounds=(0, 1e6)),
            _ind("usreg_uninsured", "No health insurance (US states and counties)", f"Share of people under 65 without health "
                 f"insurance. {s}.", "%", "health", src, "v085", bounds=(0, 100)),
            _ind("usreg_adult_obesity", "Adult obesity (US states and counties)", f"Share of adults with a body mass index of "
                 f"30 or more. {s}.", "%", "health", src, "v011", bounds=(0, 100)),
            _ind("usreg_adult_smoking", "Adults who smoke (US states and counties)", f"Share of adults who smoke now. {s}.",
                 "%", "health", src, "v009", bounds=(0, 100)),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- energy (SEDS)
BTU_PJ = 1.055056e-3  # PJ in a billion Btu
SEDS = {"TETCB": ("usreg_energy_use", BTU_PJ), "TEPRB": ("usreg_energy_production", BTU_PJ),
        "TETPB": ("usreg_energy_use_per_person", 1.055056)}  # million Btu -> GJ


def seds_rows(path: Path, rows: Rows) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for r in (data.get("response") or {}).get("data") or []:
        st = str(r.get("stateId") or "").upper()
        ind = SEDS.get(str(r.get("seriesId") or ""))
        v, y = num(r.get("value")), num(r.get("period"))
        if st in POSTAL and ind and v is not None and y is not None:
            rows.add("us_fips", POSTAL[st], ind[0], int(y), v * ind[1])
            n += 1
    return n


class EIASEDS(USConnector):
    source_id = "eia_seds"
    needs_env = ("EIA_API_KEY",)

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("EIA_API_KEY")
        offset, page, total = 0, 1, None
        while total is None or offset < total:
            dest = raw_dir / f"seds_{page:02d}.json"
            self.get(EIA_SEDS.format(key=key, offset=offset), dest, cached=False)
            resp = json.loads(dest.read_text(encoding="utf-8")).get("response") or {}
            total = int(num(resp.get("total")) or 0)
            got = len(resp.get("data") or [])
            if not got:
                break
            offset += got
            page += 1
            time.sleep(1)
            if page > 20:
                break
        return "https://api.eia.gov/v2/seds/data/"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.glob("seds_*.json")):
            seds_rows(p, rows)
        if not rows:
            raise ConnectorError(f"eia_seds: no figures read from {raw_dir}")
        src = self.source_id
        self.listed_indicators = [
            _ind("usreg_energy_use", "Energy used (US states)", "All energy used in the state (fuels and electricity from "
                 "outside, counted once). EIA State Energy Data System, TETCB.", "PJ", "energy", src, "TETCB", decimals=0,
                 bounds=(0, 1e6)),
            _ind("usreg_energy_production", "Energy produced (US states)", "All primary energy produced in the state (coal, "
                 "oil, gas, nuclear, renewables). EIA SEDS, TEPRB.", "PJ", "energy", src, "TEPRB", decimals=0, bounds=(0, 1e6)),
            _ind("usreg_energy_use_per_person", "Energy used per person (US states)", "Energy used in the state per resident. "
                 "EIA SEDS, TETPB.", "GJ per person", "energy", src, "TETPB", decimals=0, bounds=(0, 1e4)),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- outlines
SHAPE_TOL = 0.01  # degrees (about 1 km): enough for a state or county map


def simplify(geom: dict, tol: float = SHAPE_TOL) -> dict | None:
    """A polygon outline simplified and rounded to 3 decimals (about 100 m)."""
    from shapely.geometry import mapping, shape

    try:
        g = shape(geom)
        if not g.is_valid:
            g = g.buffer(0)
        g = g.simplify(tol, preserve_topology=True)
        if g.is_empty:
            return None
        m = mapping(g)
    except Exception:  # noqa: BLE001 - a broken shape is skipped, not fatal
        return None

    def rnd(c):
        return [round(c[0], 3), round(c[1], 3)] if c and isinstance(c[0], (int, float)) else [rnd(x) for x in c]
    return {"type": m["type"], "coordinates": rnd(json.loads(json.dumps(m["coordinates"])))}


def region_shape_rows(features, parents: dict[str, dict]) -> list[tuple]:
    """(layer, id, name, rank, props, countries, geometry) rows for geo_features layer 'regions'."""
    ents = catalogue.entities()
    out = []
    for eid, geom in features:
        sub = parents.get(eid)
        if not sub:
            continue
        g = simplify(geom)
        if not g:
            continue
        country = sub["parent_id"]
        while country in parents:  # a county's country is its state's parent
            country = parents[country]["parent_id"]
        e = ents.get(eid)
        out.append(("regions", eid, e.short_name if e else eid, 1 if sub["level"] in ("state", "region") else 2,
                    {"level": sub["level"], "parent": sub["parent_id"]}, [country], g))
    return out


def subdivisions_by_id() -> dict[str, dict]:
    return {s["entity_id"]: s for s in catalogue.subdivisions()}


class USShapes(USConnector):
    source_id = "us_shapes"
    fetch_every_days = 365

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for level in ("state", "county"):
            for y in range(date.today().year, 2022, -1):
                if self.try_get(CB.format(y=y, level=level), raw_dir / f"cb_us_{level}_5m.zip"):
                    got += 1
                    break
        if got < 2:
            raise ConnectorError("us_shapes: the Census boundary files could not be fetched")
        return CB.format(y="YYYY", level="state|county")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        from worldmodel_data.connectors.networks import _shapes

        feats = []
        for level in ("state", "county"):
            zp = raw_dir / f"cb_us_{level}_5m.zip"
            if not zp.exists():
                continue
            for rec, geom in _shapes(zp):
                fips = fips_of(rec.get("STATEFP"), rec.get("COUNTYFP") if level == "county" else None)
                if fips:
                    feats.append((f"US-{STATES[fips]}" if len(fips) == 2 else f"US-{fips}", geom))
        rows = region_shape_rows(feats, subdivisions_by_id())
        if not rows:
            raise ConnectorError(f"us_shapes: no outlines read from {raw_dir}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("us_shapes: %s outlines", len(rows))
        return EMPTY_OBSERVATIONS


class NEAdmin1(Connector):
    """Natural Earth's states and provinces, for the regions the catalogue lists outside the US."""
    source_id = "ne_admin1"
    fetch_every_days = 365
    stage_version = 2  # 2: Australia's states and territories

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(NE_ADMIN1, raw_dir / NE_ADMIN1_FILE)
        return "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        path = raw_dir / NE_ADMIN1_FILE
        if not path.exists():
            raise ConnectorError(f"ne_admin1: {NE_ADMIN1_FILE} missing from {raw_dir}")
        subs = {k: v for k, v in subdivisions_by_id().items() if not k.startswith("US-")}
        feats = []
        for ft in json.loads(path.read_text(encoding="utf-8")).get("features") or []:
            code = str((ft.get("properties") or {}).get("iso_3166_2") or "")
            if code in subs and ft.get("geometry"):
                feats.append((code, ft["geometry"]))
        rows = region_shape_rows(feats, subs)
        if not rows:
            raise ConnectorError(f"ne_admin1: none of the catalogue's regions found in {path.name}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("ne_admin1: %s region outlines", len(rows))
        return EMPTY_OBSERVATIONS
