"""Cities and the cost of living.

GeoNames (geonames): every place of 15,000 people or more, with its location,
population, region and other names; the city list everything else is matched to.
    https://download.geonames.org/export/dump/cities15000.zip, admin1CodesASCII.txt

UN World Urbanization Prospects (un_wup): city populations with their locations. The 2025
revision's File 21 has every city of 50,000 or more (cities as the Degree of Urbanisation
draws them) for each year 1975-2050, projections after 2025; cities that reach 100,000 are
kept (all of New Zealand's). The 2018 revision's File 12 (urban agglomerations of 300,000 or
more, every five years 1950-2035) is read too when saved by hand.

WhereNext (wherenext): free CC BY data on the cost of living: about 370 cities
(cost index, a single person's monthly costs, quality of life), the cost of living
by country (with groceries, rent, utilities and transport), and median pay before
and after tax for about 40 countries.

ILOSTAT (ilostat_earnings): mean monthly earnings of employees (local currency, US
dollars and PPP dollars, women and men) and the statutory minimum wage. ILOSTAT's
bulk files; if they cannot be reached, save them in var\\manual\\ilostat_earnings.

Numbeo (numbeo): loaded by hand only, about once a year. Save the pages "Cost of
Living Index by City <year>", "Crime Index by City <year>" and "Health Care Index by
City <year>" (and, if wanted, the "... by Country" ones) from numbeo.com with your
browser (File, Save page as, HTML only) into var\\manual\\numbeo and run
.\\load.bat numbeo. Each year's file is kept, so the years build up. The per-city
prices on city pages are fetched one city at a time from the app (Settings limit).

WHO Ambient Air Quality Database (who_aqdb): yearly means of PM2.5, PM10 and NO2 from
ground monitors in about 8,000 places, one Excel file updated every year or two. The
link is found on WHO's page; if WHO refuses, save the file in var\\manual\\who_aqdb.

TomTom Traffic Index (tomtom_traffic): the time to drive 10 km and how congested each of
about 500 cities is over a year. The ranking is drawn by the page's script, so it is
saved by hand: open tomtom.com/traffic-index/ranking, show all cities, and save the page
(Ctrl+S, "Webpage, Complete") or copy the table into a .txt file, in
var\\manual\\tomtom_traffic; then .\\load.bat tomtom_traffic. Each year's file is kept.
"""

from __future__ import annotations

import csv
import gzip
import html
import io
import json
import logging
import re
import unicodedata
import zipfile
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_contract.cities import NUMBEO_COLUMNS, norm_name
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)


def _values_table(con: duckdb.DuckDBPyConnection, rows: list[tuple], table: str = "city_vals") -> str:
    """Stage city figures: (city_name, country_id, lat, lon, indicator_id, year, status, value)."""
    con.execute(f"CREATE TABLE {table} (city_name VARCHAR, country_id VARCHAR, lat DOUBLE, lon DOUBLE, "
                "indicator_id VARCHAR, period_start DATE, status VARCHAR, value DOUBLE)")
    con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(n, c, la, lo, i, date(int(y), 1, 1), st, v) for n, c, la, lo, i, y, st, v in rows if v is not None])
    return f"SELECT * FROM {table}"


_NAMES: dict[str, str] | None = None
_FULL: dict[str, str] | None = None


def _full_key(s: str) -> str:
    """A country name compared loosely but keeping any bracketed part, which can be the
    only thing telling two countries apart: "Congo (Kinshasa)" and "Congo (Brazzaville)"."""
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())


def country_by_name(name: str | None) -> str | None:
    """A country's entity id from its name as a source writes it ("New Zealand", "Korea, South", "Türkiye")."""
    global _NAMES, _FULL
    if _NAMES is None or _FULL is None:
        _NAMES, _FULL = {}, {}
        for e in catalogue.entities().values():
            if e.is_group:
                continue
            for n in [e.name, e.short_name, *e.synonyms.split("|")]:
                if n and (k := norm_name(n)) and (k not in _NAMES or not e.valid_to):
                    _NAMES[k] = e.entity_id
                if n and (k := _full_key(n)) and (k not in _FULL or not e.valid_to):
                    _FULL[k] = e.entity_id
        _NAMES.update({"unitedstatesofamerica": "USA", "usa": "USA", "uk": "GBR", "southkorea": "KOR",
                       "korea": "KOR", "czechia": "CZE", "kosovo": _NAMES.get("kosovo", "XKX"),
                       "hongkong": _NAMES.get("hongkong", "HKG"), "taiwan": _NAMES.get("taiwan", "TWN")})
    if not name:
        return None
    if (hit := _FULL.get(_full_key(name))):
        return hit
    return _NAMES.get(norm_name(name))


# ----------------------------------------------------------------------------------------- GeoNames
GEONAMES = "https://download.geonames.org/export/dump/"
GEONAMES_FILES = ("cities15000.zip", "admin1CodesASCII.txt")
MAJOR_CITY = 1_000_000  # on the "Major cities" map layer: these, plus every capital


class GeoNames(Connector):
    """The city list. Other names are kept (lower case, Latin letters only) so that
    other sources' spellings can be matched; the layer marks cities of a million or
    more and every capital."""
    source_id = "geonames"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for f in GEONAMES_FILES:
            self.get(GEONAMES + f, raw_dir / f)
        return " ".join(GEONAMES + f for f in GEONAMES_FILES)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        admin1 = {}
        a1 = raw_dir / "admin1CodesASCII.txt"
        if a1.exists():
            for line in a1.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    admin1[parts[0]] = parts[1]
        text = None
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as z:
                    name = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
                    text = z.read(name).decode("utf-8", errors="replace") if name else None
            elif f.name.lower().startswith("cities") and f.suffix.lower() == ".txt":
                text = f.read_text(encoding="utf-8", errors="replace")
            if text:
                break
        if not text:
            raise ConnectorError(f"geonames: no cities file (cities15000.zip or .txt) in {raw_dir}")
        cities, features = [], []
        for line in text.splitlines():
            p = line.split("\t")
            if len(p) < 19:
                continue
            country = entity_for("iso2", p[8])
            if not country:
                continue
            pop = num(p[14]) or 0
            syn = _synonyms(p[1], p[2], p[3])
            region = admin1.get(f"{p[8]}.{p[10]}", "")
            cities.append((f"gn{p[0]}", p[1], p[2], syn, country, region, num(p[4]), num(p[5]), pop, p[7], p[17],
                           num(p[15]) if p[15] else num(p[16])))
            if pop >= MAJOR_CITY or p[7] == "PPLC":
                features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(num(p[5]), 3), round(num(p[4]), 3)]},
                                 "properties": {"name": p[1], "population": int(pop), "city": f"gn{p[0]}",
                                                **({"capital": 1} if p[7] == "PPLC" else {})}})
        if not cities:
            raise ConnectorError("geonames: no cities read")
        con.execute("CREATE TABLE gn (city_key VARCHAR, name VARCHAR, ascii_name VARCHAR, synonyms VARCHAR, country_id VARCHAR, "
                    "admin1 VARCHAR, lat DOUBLE, lon DOUBLE, population DOUBLE, feature_code VARCHAR, timezone VARCHAR, "
                    "elevation DOUBLE)")
        con.executemany("INSERT INTO gn VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", cities)
        self.cities_query = "SELECT * FROM gn"
        features.sort(key=lambda f: -f["properties"]["population"])
        self.layers = [{"layer_id": "major_cities", "name": "Major cities",
                        "description": "Cities of a million people or more and every capital (GeoNames), sized by population.",
                        "kind": "point", "feature_count": len(features),
                        "geojson": json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"),
                                              ensure_ascii=False)}]
        return Rows().stage(con, self.source_id, vintage)


def _synonyms(name: str, ascii_name: str, alternates: str) -> str:
    """Other names worth matching on: Latin-letter ones, not codes such as airport codes."""
    seen = {norm_name(name), norm_name(ascii_name)}
    out = []
    for a in alternates.split(","):
        a = a.strip()
        if not a or len(a) > 40 or (len(a) <= 3 and a.isupper()) or re.search(r"\d", a):
            continue
        if not re.fullmatch(r"[A-Za-zÀ-ɏ' .\-]+", a):
            continue
        k = norm_name(a)
        if k and k not in seen:
            seen.add(k)
            out.append(k)
        if len(out) >= 25:
            break
    return "|".join(out)


# ----------------------------------------------------------------------------------------- UN WUP
# The 2025 revision: every city of 50,000 or more (cities as the Degree of Urbanisation draws
# them), 1975-2050, in thousands. The 2018 revision's file (cities over 300,000, 1950-2035) is
# read too when saved by hand.
WUP_URL = "https://population.un.org/wup/assets/Download/Cities/WUP2025-F21-DEGURBA-Cities_Pop.xlsx"
WUP_LAST_ESTIMATE = {2018: 2015, 2025: 2025}  # later years are projections
WUP_MIN_POP = 100_000  # 2025 revision: cities this big at some point (all cities in KEEP_ALL)
WUP_KEEP_ALL = {"NZL"}


def sheet_rows(path: Path, sheet: str | None = None) -> list[list]:
    """Rows of the data sheet ("Data", else the first) of an .xls or .xlsx file."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        names = xlsx_sheet_names(path)
        return xlsx_rows(path, next((n for n in names if n.lower() == "data"), 0))
    import xlrd  # old Excel format, as the UN's 2018 file is

    book = xlrd.open_workbook(str(path))
    sheet = next((s for s in book.sheets() if s.name.lower() == "data"), book.sheet_by_index(0))
    return [sheet.row_values(i) for i in range(sheet.nrows)]


def read_wup(path: Path) -> list[tuple]:
    """City populations from one WUP file: (name, country, lat, lon, indicator, year, status, value)."""
    m = re.search(r"WUP(\d{4})", path.name)
    rows = sheet_rows(path)
    head_i = next((i for i, r in enumerate(rows[:40])
                   if any(key(c) in ("urbanagglomeration", "cityname") for c in r)), None)
    if head_i is None:
        if re.search(r"WPP\d{4}", path.name):
            raise ConnectorError(f"un_wup: {path.name} is a World Population Prospects file (country totals), not "
                                 "city populations; move it to the 'old' folder")
        raise ConnectorError(f"un_wup: no 'City_Name' or 'Urban Agglomeration' heading in {path.name}")
    head = [key(c) for c in rows[head_i]]
    new = "cityname" in head
    revision = int(m.group(1)) if m else (2025 if new else 2018)
    names = {"name": ("cityname", "urbanagglomeration"), "lat": ("pwcentlatitude", "latitude"),
             "lon": ("pwcentlongitude", "longitude"), "iso3": ("iso3code",), "m49": ("locid", "countrycode")}
    col = {k: next((head.index(c) for c in cands if c in head), None) for k, cands in names.items()}
    if col["name"] is None or col["lat"] is None or col["lon"] is None or (col["iso3"] is None and col["m49"] is None):
        raise ConnectorError(f"un_wup: missing columns in {path.name}, found {rows[head_i]}")
    years = [(i, int(float(c))) for i, c in enumerate(rows[head_i]) if re.fullmatch(r"\d{4}(\.0)?", str(c).strip())]
    last = WUP_LAST_ESTIMATE.get(revision, revision)
    out = []
    for r in rows[head_i + 1:]:
        if len(r) <= max(v for v in col.values() if v is not None) or not r[col["name"]]:
            continue
        country = (entity_for("iso3", r[col["iso3"]]) if col["iso3"] is not None else None) \
            or (entity_for("m49", int(num(r[col["m49"]]) or 0)) if col["m49"] is not None else None)
        if not country:
            continue
        values = [(y, num(r[i])) for i, y in years]
        if new and country not in WUP_KEEP_ALL and max((v or 0 for _, v in values), default=0) * 1000 < WUP_MIN_POP:
            continue
        name = str(r[col["name"]]).strip()
        lat, lon = num(r[col["lat"]]), num(r[col["lon"]])
        for y, v in values:
            if v is not None:
                out.append((name, country, lat, lon, "city_population", y, "P" if y > last else "E", v * 1000))
    return out


class UNWUP(Connector):
    source_id = "un_wup"
    frozen = True  # one file per revision; a new revision's file saved in var\manual\un_wup is loaded
    stage_version = 2  # 2: the 2025 revision's cities file
    fetch_version = 2  # 2: WUP2025-F21 (the 2018 file was taken down)

    def default_release(self, fetched_at: datetime) -> str:
        return "2025"

    def release_from_files(self, files: list[Path]) -> str | None:
        m = next((re.search(r"WUP(\d{4})", f.name) for f in files if re.search(r"WUP(\d{4})", f.name)), None)
        return m.group(1) if m else None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(WUP_URL, raw_dir / Path(WUP_URL).name)
        return WUP_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = [f for f in sorted(raw_dir.iterdir()) if f.suffix.lower() in (".xls", ".xlsx")]
        if not files:
            raise ConnectorError(f"un_wup: no .xls or .xlsx file in {raw_dir}")
        # newest revision first; the cities file before any other WUP file
        def order(f: Path) -> tuple:
            m = re.search(r"WUP(\d{4})", f.name)
            return (-(int(m.group(1)) if m else 0), not re.search(r"cities_(pop|over)", f.name, re.I), f.name)

        files.sort(key=order)
        problems = []
        for f in files:
            try:
                out = read_wup(f)
            except ConnectorError as exc:
                problems.append(str(exc))
                continue
            if out:
                for p in problems:
                    log.warning("%s", p)
                self.city_values_query = _values_table(con, out)
                return Rows().stage(con, self.source_id, vintage)
            problems.append(f"un_wup: no city populations read from {f.name}")
        raise ConnectorError("; ".join(problems))


# ----------------------------------------------------------------------------------------- WhereNext
WHERENEXT = "https://getwherenext.com/api/data/"
WHERENEXT_FILES = {"best-value-cities-2026": "cities.json", "cost-of-living": "cost_of_living.json",
                   "median-salaries": "median_salaries.json"}
WN_COUNTRY = {  # field -> (indicator, name, unit, decimals, description)
    "cost_index": ("wn_cost_index", "Cost of living index (WhereNext)", "index (world = 100)", 0,
                   "WhereNext's cost of living index for the country, built on World Bank price levels; world = 100."),
    "monthly_estimate_usd": ("wn_monthly_cost_usd", "Monthly cost for one person (WhereNext)", "US$", 0,
                             "WhereNext's estimate of a single person's monthly living costs, rent included, in US dollars."),
    "grocery_index": ("wn_grocery_index", "Groceries index (WhereNext)", "index", 0, "WhereNext's grocery price index."),
    "rent_index": ("wn_rent_index", "Rent index (WhereNext)", "index", 0, "WhereNext's rent index."),
    "utilities_index": ("wn_utilities_index", "Utilities index (WhereNext)", "index", 0, "WhereNext's utilities price index."),
    "transport_index": ("wn_transport_index", "Transport index (WhereNext)", "index", 0, "WhereNext's transport price index."),
}
WN_PAY = {
    "medianGrossUSD": ("wn_median_gross_usd", "Median pay before tax (WhereNext)", "US$ a year", 0,
                       "Median annual pay of full-time employees before income tax and social contributions, in US dollars, "
                       "from the national statistics office (collected by WhereNext)."),
    "medianNetUSD": ("wn_median_net_usd", "Median take-home pay (WhereNext)", "US$ a year", 0,
                     "Median annual pay after income tax and employee social contributions, in US dollars (WhereNext)."),
    "medianNetUSDPPP": ("wn_median_net_ppp", "Median take-home pay, PPP (WhereNext)", "PPP $ a year", 0,
                        "Median annual take-home pay in purchasing-power-parity dollars, so it buys the same everywhere (WhereNext)."),
}


class WhereNext(Connector):
    source_id = "wherenext"
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for slug, name in WHERENEXT_FILES.items():
            self.get(WHERENEXT + slug, raw_dir / name)
        return " ".join(WHERENEXT + s for s in WHERENEXT_FILES)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, city = Rows(), []
        cities = _json(raw_dir / "cities.json")
        if cities:
            year = _year((cities.get("meta") or {}).get("updated"), release)
            for c in cities.get("data") or []:
                country = entity_for("iso2", c.get("countryCode")) or country_by_name(c.get("country"))
                if not country or not c.get("name"):
                    continue
                for field, ind in (("costIndex", "wn_city_cost_index"), ("monthlyCostEstimate", "wn_city_monthly_cost_usd"),
                                   ("qualityScore", "wn_city_quality_score"), ("valueScore", "wn_city_value_score")):
                    city.append((c["name"], country, c.get("lat"), c.get("lng") or c.get("lon"), ind, year, "E", num(c.get(field))))
        col = _json(raw_dir / "cost_of_living.json")
        if col:
            year = _year((col.get("meta") or {}).get("updated"), release)
            for c in col.get("data") or []:
                for field, (ind, *_rest) in WN_COUNTRY.items():
                    rows.add("iso2", c.get("country_code"), ind, year, num(c.get(field)))
        pay = _json(raw_dir / "median_salaries.json")
        if pay:
            for c in pay.get("countries") or []:
                year = c.get("dataYear") or _year(pay.get("dateModified"), release)
                for field, (ind, *_rest) in WN_PAY.items():
                    rows.add("iso2", c.get("code"), ind, year, num(c.get(field)))
                g, n = num(c.get("medianGrossLocal")), num(c.get("medianNetLocal"))
                if g and n:
                    rows.add("iso2", c.get("code"), "wn_take_home_share", year, 100 * n / g)
        if not len(rows) and not city:
            raise ConnectorError(f"wherenext: nothing read from {raw_dir}")
        if city:
            self.city_values_query = _values_table(con, city)
        self.listed_indicators = [
            indicator(ind, n, d, u, "living", self.source_id, field, decimals=dec)
            for field, (ind, n, u, dec, d) in {**WN_COUNTRY, **WN_PAY}.items()
        ] + [indicator("wn_take_home_share", "Take-home share of median pay (WhereNext)",
                       "Median pay after income tax and employee social contributions as a share of pay before them.",
                       "%", "living", self.source_id, "medianNetLocal/medianGrossLocal", decimals=0)]
        return rows.stage(con, self.source_id, vintage)


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _year(stamp, release: str) -> int:
    m = re.match(r"(\d{4})", str(stamp or ""))
    return int(m.group(1)) if m else int(release[:4])


# ----------------------------------------------------------------------------------------- ILOSTAT
ILO_SERIES = ("EAR_4MTH_SEX_CUR_NB_A", "EAR_4MMN_CUR_NB_A")
# Newer ILOSTAT names for the same figures, as files saved from its data explorer are called
# (EAR_EMTA: mean monthly earnings of employees). Hourly earnings (EAR_EHRA) are not used.
ILO_ALIASES = {"EAR_EMTA_SEX_CUR_NB_A": "EAR_4MTH_SEX_CUR_NB_A"}
# Tried in order; ILOSTAT has moved its bulk files before. The first is what ILO's own R
# package (Rilostat) uses since 2025: an R data file (.rds).
ILO_URLS = ("https://rplumber.ilo.org/files/indicator/{id}.rds",
            "https://rplumber.ilo.org/data/indicator/?id={id}&type=code&format=.csv.gz",
            "https://rplumber.ilo.org/files/website/bulk/indicator/{id}.csv.gz",
            "https://www.ilo.org/ilostat-files/WEB_bulk_download/indicator/{id}.csv.gz")
ILO_CURRENCY = {"CUR_TYPE_PPP": "ppp", "CUR_TYPE_USD": "usd", "CUR_TYPE_LCU": "lcu"}
ILO_UNIT = {"ppp": "PPP $ a month", "usd": "US$ a month", "lcu": "local currency a month"}
ILO_CUR_NAME = {"ppp": "PPP dollars", "usd": "US dollars", "lcu": "local currency"}


class ILOEarnings(Connector):
    source_id = "ilostat_earnings"
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for sid in ILO_SERIES:
            last = None
            ids = [sid] + [k for k, v in ILO_ALIASES.items() if v == sid]
            tries = [(i, pattern.format(id=i)) for i in ids for pattern in ILO_URLS]
            for i, url in tries:
                try:
                    self.get(url, raw_dir / (f"{i}.rds" if url.endswith(".rds") else f"{i}.csv.gz"))
                    got.append(url)
                    break
                except ConnectorError as exc:
                    last = exc
            else:
                raise ConnectorError(f"ilostat: {sid} could not be downloaded ({last})")
        return " ".join(got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() not in (".csv", ".gz", ".xlsx", ".rds"):
                continue
            named = next((s for s in ILO_SERIES if f.name.upper().startswith(s)), None) or \
                next((v for k, v in ILO_ALIASES.items() if f.name.upper().startswith(k)), None)
            if named is None and f.name.upper().startswith("EAR_EHRA"):
                continue
            for r in _ilo_rows(f):
                sid = named or _ilo_series(r)
                cur = _ilo_currency(r.get("classif1", "") or r.get("classif1.label", ""))
                y = re.match(r"(\d{4})", str(r.get("time", "")))
                if not sid or not cur or not y:
                    continue
                if sid.startswith("EAR_4MTH"):
                    sex = _ilo_sex(r.get("sex", "") or r.get("sex.label", ""))
                    if sex is None:
                        continue
                    ind = f"ilo_earnings_{cur}{sex}"
                else:
                    ind = f"ilo_min_wage_{cur}"
                area = str(r.get("ref_area", "") or "").strip()
                if re.fullmatch(r"[A-Z]{3}", area):
                    rows.add("iso3", area, ind, int(y.group(1)), num(r.get("obs_value")))
                else:
                    ent = country_by_name(area or str(r.get("ref_area.label", "")))
                    if ent:
                        rows.add("iso3", ent, ind, int(y.group(1)), num(r.get("obs_value")))
        if not len(rows):
            raise ConnectorError(f"ilostat: nothing read from {raw_dir}")
        listed = []
        for cur in ILO_CURRENCY.values():
            for sex, who in (("", ""), ("_women", ", women"), ("_men", ", men")):
                listed.append(indicator(
                    f"ilo_earnings_{cur}{sex}", f"Average monthly earnings{who} ({ILO_CUR_NAME[cur]})",
                    f"Mean monthly earnings of employees{who.replace(', ', ' (') + ')' if who else ''}, before tax, in "
                    f"{ILO_CUR_NAME[cur]}{' (2017 PPP, so a dollar buys the same everywhere)' if cur == 'ppp' else ''}. ILOSTAT.",
                    ILO_UNIT[cur], "living", self.source_id, f"EAR_4MTH_SEX_CUR_NB_A:{cur}{sex}", decimals=0,
                    default_on=cur == "ppp" and not sex))
            listed.append(indicator(
                f"ilo_min_wage_{cur}", f"Minimum wage ({ILO_CUR_NAME[cur]})",
                f"Statutory nominal gross monthly minimum wage, in {ILO_CUR_NAME[cur]}. ILOSTAT.",
                ILO_UNIT[cur], "living", self.source_id, f"EAR_4MMN_CUR_NB_A:{cur}", decimals=0, default_on=cur == "ppp"))
        self.listed_indicators = listed
        return rows.stage(con, self.source_id, vintage)


def _ilo_series(r: dict) -> str | None:
    """The series of a row from a file saved from ILOSTAT's data explorer (named any way)."""
    ind = str(r.get("indicator", "") or "") + " " + str(r.get("indicator.label", "") or "")
    if "EAR_4MTH" in ind or re.search(r"average monthly earnings", ind, re.I):
        return "EAR_4MTH_SEX_CUR_NB_A"
    if "EAR_4MMN" in ind or re.search(r"minimum wage", ind, re.I):
        return "EAR_4MMN_CUR_NB_A"
    return None


def _ilo_currency(v: str) -> str | None:
    if v in ILO_CURRENCY:
        return ILO_CURRENCY[v]
    v = v.lower()
    return "ppp" if "ppp" in v else "usd" if "u.s. dollar" in v or "us dollar" in v else "lcu" if "local currency" in v else None


def _ilo_sex(v: str) -> str | None:
    return {"SEX_T": "", "SEX_F": "_women", "SEX_M": "_men"}.get(v) if v.startswith("SEX_") else \
        {"total": "", "female": "_women", "male": "_men"}.get(v.lower().split(":")[-1].strip())


def _ilo_rows(path: Path) -> list[dict]:
    """Rows of an ILOSTAT bulk file (.csv.gz or .csv, code columns) or a file saved from its data
    explorer (CSV or Excel, possibly with ".label" columns instead of codes)."""
    if path.suffix.lower() == ".rds":
        import rdata  # reads R's .rds files; only needed here

        frame = rdata.read_rds(str(path))
        cols = [str(c) for c in frame.columns]
        return [{c: ("" if v is None or (isinstance(v, float) and v != v) else str(v)) for c, v in zip(cols, r)}
                for r in frame.itertuples(index=False, name=None)]
    if path.suffix.lower() == ".xlsx":
        table = xlsx_rows(path, 0)
        hi = next((i for i, r in enumerate(table[:10]) if any(str(c or "").startswith("ref_area") for c in r)), 0)
        head = [str(c or "").strip() for c in table[hi]]
        return [dict(zip(head, ["" if c is None else str(c) for c in r])) for r in table[hi + 1:]]
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and "obs_value" not in rows[0] and {"Area", "Year"} <= set(rows[0]):
        return _ilo_wide(rows, path.name)
    return rows


def _ilo_wide(rows: list[dict], name: str) -> list[dict]:
    """A table saved from ILOSTAT's newer data explorer: Area, Year, Total, Male, Female (one
    currency, chosen on the site and not written in the file). The currency comes from the file
    name when it says (PPP, USD, LCU or local); otherwise it is taken as PPP dollars, the
    explorer's usual choice for comparing countries."""
    up = name.upper()
    cur = ("CUR_TYPE_USD" if "USD" in up else "CUR_TYPE_LCU" if "LCU" in up or "LOCAL" in up else "CUR_TYPE_PPP")
    if cur == "CUR_TYPE_PPP" and "PPP" not in up:
        log.info("ilostat: %s does not name its currency; read as PPP dollars", name)
    out = []
    for r in rows:
        for col, sex in (("Total", "SEX_T"), ("Male", "SEX_M"), ("Female", "SEX_F")):
            if col in r and str(r[col] or "").strip():
                out.append({"ref_area": "", "ref_area.label": r["Area"], "time": r["Year"], "sex": sex,
                            "classif1": cur, "obs_value": r[col]})
    return out


# ----------------------------------------------------------------------------------------- Numbeo
class Numbeo(Connector):
    """Numbeo's yearly "Cost of Living Index by City" (and "by Country") tables, saved by hand."""
    source_id = "numbeo"
    manual = True
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("numbeo: loaded by hand. Save numbeo.com's 'Cost of Living Index by City', 'Crime Index "
                             r"by City' and 'Health Care Index by City' pages in var\manual\numbeo and run .\load.bat numbeo")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, city = Rows(), []
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() not in (".html", ".htm", ".csv", ".xlsx", ".txt"):
                continue
            table, title = numbeo_table(f)
            if not table:
                log.warning("numbeo: no index table in %s", f.name)
                continue
            m = re.search(r"(19|20)\d{2}", title or "") or re.search(r"(19|20)\d{2}", f.name)
            year = int(m.group(0)) if m else int(release[:4])
            head = [key(h) for h in table[0]]
            where = next((i for i, h in enumerate(head) if h in ("city", "country")), None)
            if where is None:
                continue
            by_country = head[where] == "country"
            cols = {i: NUMBEO_COLUMNS[h] for i, h in enumerate(head) if h in NUMBEO_COLUMNS}
            for r in table[1:]:
                if len(r) <= max(cols, default=0):
                    continue
                place = r[where].strip()
                if by_country:
                    country = country_by_name(place)
                    for i, ind in cols.items():
                        if country:
                            rows.add("iso3", catalogue.entities()[country].iso3 or country, ind, year, num(r[i]))
                    continue
                parts = [p.strip() for p in place.split(",")]
                country = country_by_name(parts[-1]) if len(parts) > 1 else None
                if not country:
                    continue
                for i, ind in cols.items():
                    city.append((parts[0], country, None, None, ind, year, "E", num(r[i])))
        if not city and not len(rows):
            raise ConnectorError(f"numbeo: no Cost of Living, Crime or Health Care Index table found in {raw_dir}; "
                                 "save the page as HTML")
        if city:
            self.city_values_query = _values_table(con, city)
        from worldmodel_contract.cities import CITY_INDICATORS
        self.listed_indicators = [
            indicator(ind, CITY_INDICATORS[ind][0], CITY_INDICATORS[ind][3].replace("in the city", "in the country"),
                      CITY_INDICATORS[ind][1], "living", self.source_id, f"by country:{ind}", decimals=1, default_on=False)
            for ind in NUMBEO_COLUMNS.values()]
        return rows.stage(con, self.source_id, vintage)


_TAG = re.compile(r"<[^>]+>")


def _cell(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s))).strip()


def numbeo_table(path: Path) -> tuple[list[list[str]], str]:
    """The index table of a saved Numbeo page (or a CSV or Excel copy of it): rows of
    cell texts, headings first; and the page title."""
    if path.suffix.lower() == ".xlsx":
        rows = [[("" if c is None else str(c)) for c in r] for r in xlsx_rows(path)]
        i = next((i for i, r in enumerate(rows) if any(key(c) in NUMBEO_COLUMNS for c in r)), None)
        return (rows[i:] if i is not None else []), path.stem
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".csv", ".txt") and "<table" not in text.lower():
        rows = list(csv.reader(io.StringIO(text)))
        i = next((i for i, r in enumerate(rows) if any(key(c) in NUMBEO_COLUMNS for c in r)), None)
        return (rows[i:] if i is not None else []), path.stem
    title = _cell(m.group(1)) if (m := re.search(r"<title>(.*?)</title>", text, re.S | re.I)) else ""
    for t in re.findall(r"<table[^>]*>(.*?)</table>", text, re.S | re.I):
        heads = [_cell(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", t, re.S | re.I)]
        if not any(key(h) in NUMBEO_COLUMNS for h in heads):
            continue
        out = [heads]
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I):
            cells = [_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if cells:
                # Rank columns are often empty headings with numbered cells; line cells up from the right.
                if len(cells) < len(heads):
                    cells = [""] * (len(heads) - len(cells)) + cells
                elif len(cells) > len(heads):
                    cells = cells[len(cells) - len(heads):]
                out.append(cells)
        return out, title
    return [], title


# ----------------------------------------------------------------------------------------- WHO air quality
WHO_AQ_PAGE = "https://www.who.int/data/gho/data/themes/air-pollution/who-air-quality-database"
WHO_AQ_KNOWN = ("https://cdn.who.int/media/docs/default-source/air-pollution-documents/air-quality-and-health/"
                "who-ambient-air-quality-database-version-2026-v8.xlsx?sfvrsn=95d122a4_5&download=true")
WHO_AQ_LINK = re.compile(r"""href=["']([^"']*who[-_]ambient[-_]air[-_]quality[-_]database[^"']*\.xlsx[^"']*)["']""", re.I)
WHO_AQ_FILE = "who_aqdb.xlsx"
# Heading words (compared loosely) for each column the file has had over its versions.
WHO_AQ_COLS = {
    "city": ("cityorlocality", "city", "cityname", "locality"),
    "iso3": ("iso3", "iso3code", "iso"),
    "country": ("whocountryname", "countryname", "country"),
    "year": ("measurementyear", "year"),
    "lat": ("latitude", "lat"),
    "lon": ("longitude", "lon", "long"),
}
WHO_AQ_POLLUTANTS = {"pm25": "who_pm25_city", "pm10": "who_pm10_city", "no2": "who_no2_city"}


def who_aq_columns(head: list) -> dict[str, int]:
    """Which column holds what in a WHO air quality sheet (by heading), or {} if it is not one."""
    keys = [key(h) for h in head]
    out: dict[str, int] = {}
    for name, words in WHO_AQ_COLS.items():
        hit = next((i for w in words for i, k in enumerate(keys) if k == w), None)
        if hit is not None:
            out[name] = hit
    for pol in WHO_AQ_POLLUTANTS:
        # "PM2.5 (μg/m3)" or "pm25_concentration"; not the coverage columns beside them.
        hit = next((i for i, k in enumerate(keys) if k.startswith(pol)
                    and not any(w in k for w in ("cov", "temporal", "station", "type"))), None)
        if hit is not None:
            out[pol] = hit
    return out if {"city", "year"} <= out.keys() and any(p in out for p in WHO_AQ_POLLUTANTS) else {}


def who_aq_rows(rows: list[list]) -> list[tuple]:
    """City figures from the rows of a WHO air quality sheet: the mean of each place's
    measurements for a year, as (city, country, lat, lon, indicator, year, status, value)."""
    i = next((i for i, r in enumerate(rows[:30]) if who_aq_columns(r)), None)
    if i is None:
        return []
    cols = who_aq_columns(rows[i])
    sums: dict[tuple, list[float]] = {}
    where: dict[tuple, tuple] = {}

    def cell(r, name):
        j = cols.get(name)
        return r[j] if j is not None and j < len(r) else None

    for r in rows[i + 1:]:
        city = str(cell(r, "city") or "").strip()
        city = re.sub(r"\s*/\s*[A-Z]{3}$", "", city)  # "Auckland/NZL"
        year = re.match(r"(19|20)\d{2}", str(cell(r, "year") or "").strip())
        if not city or not year:
            continue
        iso = str(cell(r, "iso3") or "").strip().upper()
        country = entity_for("iso3", iso) if iso else None
        country = country or country_by_name(str(cell(r, "country") or ""))
        if not country:
            continue
        lat, lon = num(cell(r, "lat")), num(cell(r, "lon"))
        for pol, ind in WHO_AQ_POLLUTANTS.items():
            v = num(cell(r, pol))
            if v is None or v < 0 or v > 1000:
                continue
            k = (city, country, ind, int(year.group(0)))
            sums.setdefault(k, []).append(v)
            if lat is not None and lon is not None:
                where.setdefault((city, country), (lat, lon))
    out = []
    for (city, country, ind, y), vs in sums.items():
        lat, lon = where.get((city, country), (None, None))
        out.append((city, country, lat, lon, ind, y, "E", round(sum(vs) / len(vs), 2)))
    return out


class WHOAirQuality(Connector):
    """WHO Ambient Air Quality Database: yearly PM2.5, PM10 and NO2 by city."""
    source_id = "who_aqdb"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        urls = []
        try:
            r = self.client.get(WHO_AQ_PAGE)
            if r.status_code == 200:
                for link in WHO_AQ_LINK.findall(r.text):
                    link = html.unescape(link)
                    urls.append(link if link.startswith("http") else "https://www.who.int" + link)
        except Exception as exc:  # noqa: BLE001 - the known address is tried next
            log.info("who_aqdb: could not read %s (%s); trying the known address", WHO_AQ_PAGE, exc)
        # The newest version first: the page lists them by year in the file name.
        urls.sort(key=lambda u: re.findall(r"(20\d\d)", u)[-1:] or ["0"], reverse=True)
        tried = []
        for url in dict.fromkeys([*urls, WHO_AQ_KNOWN]):
            try:
                self.get(url, raw_dir / WHO_AQ_FILE)
                return url
            except ConnectorError as exc:
                tried.append(str(exc))
                (raw_dir / WHO_AQ_FILE).unlink(missing_ok=True)
        raise ConnectorError("who_aqdb: could not download the WHO Ambient Air Quality Database; tried:\n  "
                             + "\n  ".join(tried) + f"\nSave the Excel file from {WHO_AQ_PAGE} in var\\manual\\who_aqdb")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        city: list[tuple] = []
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() not in (".xlsx", ".csv"):
                continue
            if f.suffix.lower() == ".csv":
                text = f.read_bytes().decode("utf-8-sig", errors="replace")
                city += who_aq_rows(list(csv.reader(io.StringIO(text))))
                continue
            from openpyxl import load_workbook

            with open(f, "rb") as fh:
                names = load_workbook(fh, read_only=True).sheetnames
            for sheet in names:  # the data sheet is not always first (a read-me comes first)
                got = who_aq_rows(xlsx_rows(f, sheet))
                if got:
                    city += got
                    break
        if not city:
            raise ConnectorError(f"who_aqdb: no city air quality figures read from {raw_dir}; the file's layout may have changed")
        self.city_values_query = _values_table(con, city)
        return Rows().stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------------------- TomTom
TOMTOM_PAGE = "https://www.tomtom.com/traffic-index/ranking/"
_TT_TIME = re.compile(r"(\d{1,3})\s*min(?:utes?)?\s*(?:(\d{1,2})\s*s(?:ec(?:onds?)?)?)?", re.I)


def tomtom_minutes(v) -> float | None:
    """"27 min 40 s" -> 27.67; a plain number is taken as minutes."""
    if v is None:
        return None
    m = _TT_TIME.search(str(v))
    if m:
        return round(int(m.group(1)) + int(m.group(2) or 0) / 60, 2)
    return num(str(v).replace("min", "").strip())


def _tt_place(city: str, country: str | None) -> tuple[str, str | None] | None:
    city = re.sub(r"\s+", " ", city).strip()
    if country:
        return city, country_by_name(country)
    if "," in city:  # "Auckland, New Zealand"
        a, b = city.rsplit(",", 1)
        return a.strip(), country_by_name(b)
    words = city.split()  # "Auckland New Zealand": the country is the last one to three words
    for n in (3, 2, 1):
        if len(words) > n and words[-n].lower() not in ("city", "of", "de") and (c := country_by_name(" ".join(words[-n:]))):
            return " ".join(words[:-n]), c
    return None


def tomtom_rows(table: list[list[str]]) -> list[tuple[str, str, float | None, float | None]]:
    """(city, country, minutes per 10 km, congestion %) from a ranking table, headings first."""
    head = [key(h) for h in table[0]]

    def find(*words):
        return next((i for i, h in enumerate(head) if any(w in h for w in words)), None)

    c_city, c_country = find("city"), find("country")
    c_time = find("10km", "traveltime", "averagetime", "time")
    c_cong = find("congestion")
    if c_city is None or (c_time is None and c_cong is None):
        return []
    out = []
    for r in table[1:]:
        if len(r) <= c_city:
            continue
        place = _tt_place(r[c_city], r[c_country] if c_country is not None and c_country < len(r) else None)
        if not place or not place[1] or not place[0]:
            continue
        t = tomtom_minutes(r[c_time]) if c_time is not None and c_time < len(r) else None
        g = num(str(r[c_cong]).replace("%", "").strip()) if c_cong is not None and c_cong < len(r) else None
        if t is not None or g is not None:
            out.append((place[0], place[1], t, g))
    return out


def tomtom_text_rows(text: str) -> list[tuple[str, str, float | None, float | None]]:
    """The ranking read from a page's visible text: lines such as
    "12 | Auckland | New Zealand | 23 min 10 s | 41%" (cells split by tags or tabs)."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "|", text).replace("\t", "|")
    text = re.sub(r"\s*\|[\s|]*", "|", html.unescape(text))
    out, seen = [], set()
    row = re.compile(r"\|(\d{1,3})\|([^|\d][^|]{1,40})\|(?:([^|\d][^|]{1,40})\|)?(\d{1,3}\s*min[^|]*)"
                     r"(?:\|(?:[^|%]*\|){0,3}?(\d{1,3})\s*%)?")
    for m in row.finditer("|" + text + "|"):
        place = _tt_place(m.group(2), m.group(3))
        if not place or not place[1] or (place[0], place[1]) in seen:
            continue
        seen.add((place[0], place[1]))
        out.append((place[0], place[1], tomtom_minutes(m.group(4)), num(m.group(5)) if m.group(5) else None))
    return out


def tomtom_file(path: Path) -> tuple[list[tuple], str]:
    """The ranking in a saved TomTom page, a CSV, Excel or text copy of it; and its title."""
    if path.suffix.lower() == ".xlsx":
        rows = [[("" if c is None else str(c)) for c in r] for r in xlsx_rows(path)]
        i = next((i for i, r in enumerate(rows[:20]) if any("city" in key(c) for c in r)), None)
        return (tomtom_rows(rows[i:]) if i is not None else []), path.stem
    text = path.read_text(encoding="utf-8", errors="replace")
    title = _cell(m.group(1)) if (m := re.search(r"<title>(.*?)</title>", text, re.S | re.I)) else path.stem
    if "<" not in text[:2000]:  # a CSV or text copy of the table
        delim = "\t" if "\t" in text else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        i = next((i for i, r in enumerate(rows[:20]) if any("city" in key(c) for c in r)), None)
        got = tomtom_rows(rows[i:]) if i is not None else []
        return (got or tomtom_text_rows(text)), title
    for t in re.findall(r"<table[^>]*>(.*?)</table>", text, re.S | re.I):
        heads = [_cell(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", t, re.S | re.I)]
        if not any("city" in key(h) for h in heads):
            continue
        body = [[_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
                for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I)]
        got = tomtom_rows([heads, *[b for b in body if b]])
        if got:
            return got, title
    return tomtom_text_rows(text), title


class TomTomTraffic(Connector):
    """TomTom Traffic Index ranking, saved by hand once a year."""
    source_id = "tomtom_traffic"
    manual = True
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError(f"tomtom_traffic: loaded by hand. Save the ranking at {TOMTOM_PAGE} in "
                             r"var\manual\tomtom_traffic and run .\load.bat tomtom_traffic")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        city: list[tuple] = []
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() not in (".html", ".htm", ".csv", ".xlsx", ".txt"):
                continue
            got, title = tomtom_file(f)
            if not got:
                log.warning("tomtom_traffic: no ranking found in %s", f.name)
                continue
            m = re.search(r"(19|20)\d{2}", title or "") or re.search(r"(19|20)\d{2}", f.name)
            # The index is for a whole year and comes out early the next; a page saved in
            # January 2026 with no year in it is the 2025 index.
            year = int(m.group(0)) if m else int(release[:4]) - 1
            for name, country, t, g in got:
                city.append((name, country, None, None, "tomtom_travel_10km", year, "E", t))
                city.append((name, country, None, None, "tomtom_congestion", year, "E", g))
        if not city:
            raise ConnectorError(f"tomtom_traffic: no ranking found in {raw_dir}; save the page with "
                                 "'Webpage, Complete' or copy the table into a .txt file")
        self.city_values_query = _values_table(con, city)
        return Rows().stage(con, self.source_id, vintage)
