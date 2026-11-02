"""Cities and the cost of living.

GeoNames (geonames): every place of 15,000 people or more, with its location,
population, region and other names; the city list everything else is matched to.
    https://download.geonames.org/export/dump/cities15000.zip, admin1CodesASCII.txt

UN World Urbanization Prospects 2018 (un_wup): the population of every urban
agglomeration of 300,000 or more, every five years 1950-2035 (projections from
2020), with its location. File 12 of the 2018 revision; it no longer changes.

WhereNext (wherenext): free CC BY data on the cost of living: about 370 cities
(cost index, a single person's monthly costs, quality of life), the cost of living
by country (with groceries, rent, utilities and transport), and median pay before
and after tax for about 40 countries.

ILOSTAT (ilostat_earnings): mean monthly earnings of employees (local currency, US
dollars and PPP dollars, women and men) and the statutory minimum wage. ILOSTAT's
bulk files; if they cannot be reached, save them in var\\manual\\ilostat_earnings.

Numbeo (numbeo): loaded by hand only, about once a year. Save the page "Cost of
Living Index by City <year>" (and, if wanted, "... by Country") from numbeo.com
with your browser (File, Save page as, HTML only) into var\\manual\\numbeo and run
.\\load.bat numbeo. Each year's file is kept, so the years build up. The per-city
prices on city pages are fetched one city at a time from the app (Settings limit).
"""

from __future__ import annotations

import csv
import gzip
import html
import io
import json
import logging
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_contract.cities import NUMBEO_COLUMNS, norm_name
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows

log = logging.getLogger(__name__)


def _values_table(con: duckdb.DuckDBPyConnection, rows: list[tuple], table: str = "city_vals") -> str:
    """Stage city figures: (city_name, country_id, lat, lon, indicator_id, year, status, value)."""
    con.execute(f"CREATE TABLE {table} (city_name VARCHAR, country_id VARCHAR, lat DOUBLE, lon DOUBLE, "
                "indicator_id VARCHAR, period_start DATE, status VARCHAR, value DOUBLE)")
    con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(n, c, la, lo, i, date(int(y), 1, 1), st, v) for n, c, la, lo, i, y, st, v in rows if v is not None])
    return f"SELECT * FROM {table}"


_NAMES: dict[str, str] | None = None


def country_by_name(name: str | None) -> str | None:
    """A country's entity id from its name as a source writes it ("New Zealand", "Korea, South", "Türkiye")."""
    global _NAMES
    if _NAMES is None:
        _NAMES = {}
        for e in catalogue.entities().values():
            if e.is_group:
                continue
            for n in [e.name, e.short_name, *e.synonyms.split("|")]:
                if n and (k := norm_name(n)) and (k not in _NAMES or not e.valid_to):
                    _NAMES[k] = e.entity_id
        _NAMES.update({"unitedstatesofamerica": "USA", "usa": "USA", "uk": "GBR", "southkorea": "KOR",
                       "korea": "KOR", "czechia": "CZE", "kosovo": _NAMES.get("kosovo", "XKX"),
                       "hongkong": _NAMES.get("hongkong", "HKG"), "taiwan": _NAMES.get("taiwan", "TWN")})
    return _NAMES.get(norm_name(name)) if name else None


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
WUP_URL = "https://population.un.org/wup/Download/Files/WUP2018-F12-Cities_Over_300K.xls"
WUP_LAST_ESTIMATE = 2015  # the 2018 revision's estimates run to 2015; 2020 on are projections


def sheet_rows(path: Path) -> list[list]:
    """Rows of the first data sheet of an .xls or .xlsx file."""
    if path.suffix.lower() == ".xlsx":
        return xlsx_rows(path)
    import xlrd  # old Excel format, as the UN's file is

    book = xlrd.open_workbook(str(path))
    sheet = next((s for s in book.sheets() if s.name.lower() == "data"), book.sheet_by_index(0))
    return [sheet.row_values(i) for i in range(sheet.nrows)]


class UNWUP(Connector):
    source_id = "un_wup"
    frozen = True

    def default_release(self, fetched_at: datetime) -> str:
        return "2018"

    def release_from_files(self, files: list[Path]) -> str | None:
        m = next((re.search(r"WUP(\d{4})", f.name) for f in files if re.search(r"WUP(\d{4})", f.name)), None)
        return m.group(1) if m else None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(WUP_URL, raw_dir / Path(WUP_URL).name)
        return WUP_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = [f for f in sorted(raw_dir.iterdir()) if f.suffix.lower() in (".xls", ".xlsx")]
        if not files:
            raise ConnectorError(f"un_wup: no .xls file in {raw_dir}")
        rows = sheet_rows(files[0])
        head_i = next((i for i, r in enumerate(rows[:40]) if any(key(c) == "urbanagglomeration" for c in r)), None)
        if head_i is None:
            raise ConnectorError("un_wup: no 'Urban Agglomeration' heading in the file")
        head = [key(c) for c in rows[head_i]]
        col = {k: head.index(k) for k in ("countrycode", "urbanagglomeration", "latitude", "longitude") if k in head}
        if len(col) < 4:
            raise ConnectorError(f"un_wup: missing columns, found {rows[head_i]}")
        years = [(i, int(float(c))) for i, c in enumerate(rows[head_i]) if re.fullmatch(r"\d{4}(\.0)?", str(c).strip())]
        out = []
        for r in rows[head_i + 1:]:
            if len(r) <= max(col.values()) or not r[col["urbanagglomeration"]]:
                continue
            country = entity_for("m49", int(num(r[col["countrycode"]]) or 0))
            if not country:
                continue
            name = str(r[col["urbanagglomeration"]]).strip()
            lat, lon = num(r[col["latitude"]]), num(r[col["longitude"]])
            for i, y in years:
                v = num(r[i])
                if v is not None:
                    out.append((name, country, lat, lon, "city_population", y,
                                "P" if y > WUP_LAST_ESTIMATE else "E", v * 1000))
        if not out:
            raise ConnectorError("un_wup: no city populations read")
        self.city_values_query = _values_table(con, out)
        return Rows().stage(con, self.source_id, vintage)


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
# Tried in order; ILOSTAT has moved its bulk files before.
ILO_URLS = ("https://rplumber.ilo.org/data/indicator/?id={id}&type=code&format=.csv.gz",
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
            for pattern in ILO_URLS:
                url = pattern.format(id=sid)
                try:
                    self.get(url, raw_dir / f"{sid}.csv.gz")
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
            sid = next((s for s in ILO_SERIES if f.name.upper().startswith(s)), None)
            if not sid:
                continue
            for r in _ilo_rows(f):
                cur = ILO_CURRENCY.get(r.get("classif1", ""))
                y = re.match(r"(\d{4})", r.get("time", ""))
                if not cur or not y:
                    continue
                if sid.startswith("EAR_4MTH"):
                    sex = {"SEX_T": "", "SEX_F": "_women", "SEX_M": "_men"}.get(r.get("sex", ""))
                    if sex is None:
                        continue
                    ind = f"ilo_earnings_{cur}{sex}"
                else:
                    ind = f"ilo_min_wage_{cur}"
                rows.add("iso3", r.get("ref_area"), ind, int(y.group(1)), num(r.get("obs_value")))
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


def _ilo_rows(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


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
        raise ConnectorError("numbeo: loaded by hand. Save numbeo.com's 'Cost of Living Index by City' page in "
                             r"var\manual\numbeo and run .\load.bat numbeo")

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
            raise ConnectorError(f"numbeo: no Cost of Living Index table found in {raw_dir}; save the page as HTML")
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
