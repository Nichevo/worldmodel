"""CIA World Factbook, every edition from 1990 to the last one (2025), from an archive.

The CIA stopped the Factbook in February 2026. Its editions are kept, parsed into
one SQLite database, by the CIA World Factbooks Archive 1990-2025 project
(https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025, MIT licence for
the code; the Factbook itself is public domain):

    https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025/releases/download/v3.5/factbook.db

(about 690 MB, downloaded once: the archive is frozen, so a refresh does not fetch
it again once a vintage exists). The tables read:

* Countries (one row per entity and edition: Year, FIPS Code, Name) and
  MasterCountries (each entity across editions, with an ISO alpha-2 code where it
  has one).
* CountryCategories and CountryFields: every field's text as published, by section.
* FieldNameMappings: the archive's map from each edition's field names to one
  canonical name (and which "fields" are parser noise).
* FieldValues: numbers the archive parsed out of the text, one per sub-field.

What is stored:

* The text of every field of every edition, as texts.parquet beside the vintage
  (the warehouse's `texts` table): the country pages show any edition, and how one
  field read over the years.
* About 60 numeric series (SERIES below), as observations dated by the year each
  figure is an estimate for. Where several editions give a figure for the same year
  the latest edition's (most revised) is kept. Most are Factbook-only series under
  `fb_` ids (oil and gas reserves, airports, railways, merchant fleet and so on);
  a few are an extra source for indicators other sources already have (population,
  life expectancy, GDP growth, military spending) so the source comparison can show
  where the Factbook differed.

The archive's own parsed numbers are not used as they are: their scaling is uneven
("3.011 million metric tons" is stored as 3.011). The number is read again from the
text it came from, with its "thousand / million / billion / trillion", and each
series keeps only values inside a plausible range (which also drops the odd
mis-parsed fragment). Early editions are rougher: some 1990s figures are GNP rather
than GDP, or at exchange rates rather than purchasing power.

Countries are matched by ISO alpha-2 code, except states that no longer exist
(Soviet Union, Czechoslovakia, East Germany, the two Yemens, Yugoslavia, Serbia and
Montenegro, Netherlands Antilles), which are matched by the name in each edition,
the World and the EU (scheme `fips`). Gaza Strip and West Bank are profiled
separately in the Factbook and are left out. A copy of factbook.db can be given
instead: worldmodel-data fetch cia_factbook --from FILE.
"""

from __future__ import annotations

import csv
import logging
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str

log = logging.getLogger(__name__)

URL = "https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025/releases/download/v3.5/factbook.db"
FILE = "factbook.db"
SOURCE = "cia_factbook"

# States that no longer exist, by the name an edition gives them -> iso3 code in the crosswalk.
BY_NAME = {
    "soviet union": "SUN", "czechoslovakia": "CSK", "german democratic republic": "DDR",
    "yemen arab republic": "YAR", "yemen, people's democratic republic of": "YMD", "yugoslavia": "YUG",
    "serbia and montenegro": "SCG", "netherlands antilles": "ANT",
}
# FIPS codes with no ISO code -> scheme fips (World, EU) or iso3 (Kosovo); None leaves it out.
BY_FIPS: dict[str, tuple[str, str] | None] = {
    "XX": ("fips", "XX"), "EE": ("fips", "EE"), "KV": ("iso3", "XKX"), "GZ": None, "WE": None,
}
# Where several Factbook entities share an ISO code (UK and the Channel Islands, say), the one that is the country.
PRIMARY = {"GB": "UK", "AU": "AS", "PF": "FP", "RE": "RE", "SJ": "SV", "UM": None, "PS": None}

MULTIPLIER = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
NUMBER = re.compile(r"(-)?\s*\$?\s*(-)?(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|trillion)?", re.I)
YEAR = re.compile(r"\b((?:19|20)\d\d)\b")
FISCAL = re.compile(r"\bFY\s?(\d\d)(?:/(\d\d))?\b")
JUNK = ("skip to content", "javascript must be enabled")


@dataclass(frozen=True)
class Series:
    id: str
    name: str
    parts: tuple[tuple[str, str], ...]  # (canonical field name, regex for the sub-field name), in order of preference
    unit: str
    domain: str
    lo: float
    hi: float
    decimals: int = 1
    on: bool = True           # switched on by default (Factbook-only series)
    dated: bool = True        # False: a figure with no year is taken as of its edition
    agg: str = "none"
    description: str = ""

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(f for f, _ in self.parts)


def P(*pairs: str) -> tuple[tuple[str, str], ...]:
    """P(field, sub, field, sub, ...): the parts of a series."""
    return tuple(zip(pairs[::2], pairs[1::2]))


_V = r"value(_\d+)?"  # "value", "value_2024", "value_1" ...

SERIES: tuple[Series, ...] = (
    # Extra source for indicators other sources have.
    Series("pop_total", "Population", P("Population", "total"), "people", "population", 1e3, 2e9, 0),
    Series("life_expectancy", "Life expectancy at birth", P("Life expectancy at birth", "total_population"),
           "years", "population", 20, 95),
    Series("tfr", "Total fertility rate", P("Total fertility rate", _V), "children per woman", "population", 0.5, 9.5, 2),
    Series("median_age", "Median age", P("Median age", "total"), "years", "population", 10, 65),
    Series("cbr", "Crude birth rate", P("Birth rate", _V), "per 1,000 people", "population", 2, 70),
    Series("cdr", "Crude death rate", P("Death rate", _V), "per 1,000 people", "population", 0.5, 50),
    Series("infant_mortality", "Infant mortality rate", P("Infant mortality rate", "total"),
           "deaths per 1,000 live births", "population", 0.5, 250),
    Series("net_migration_rate", "Net migration rate", P("Net migration rate", _V), "per 1,000 people",
           "population", -80, 80),
    Series("gdp_growth", "Real GDP growth", P("Real GDP growth rate", _V), "%", "economy", -60, 100),
    Series("inflation", "Inflation (consumer prices)", P("Inflation rate (consumer prices)", _V), "%", "economy",
           -30, 50_000),
    Series("unemployment", "Unemployment rate", P("Unemployment rate", _V), "% of labour force", "labour", 0, 95),
    Series("military_spending_gdp", "Military spending", P("Military expenditures", r"pct_gdp(_\d+)?",
                                                           "Military expenditures - percent of GDP", _V),
           "% of GDP", "military", 0, 40),
    # Economy.
    Series("fb_gdp_ppp", "GDP at purchasing power parity (Factbook)", P("Real GDP (purchasing power parity)", _V),
           "US dollars", "economy", 1e7, 1e15, 0, False, agg="sum"),
    Series("fb_gdp_per_capita_ppp", "GDP per person at purchasing power parity (Factbook)",
           P("Real GDP per capita", _V), "US dollars", "economy", 100, 300_000, 0, False),
    Series("fb_public_debt", "Public debt", P("Public debt", _V), "% of GDP", "government", 0, 600),
    Series("fb_taxes_revenue_gdp", "Taxes and other revenues", P("Taxes and other revenues", _V), "% of GDP",
           "government", 0, 200, on=False),
    Series("fb_budget_revenues", "Government revenues", P("Budget", "revenues"), "US dollars", "government", 1e5,
           1e14, 0, False, agg="sum"),
    Series("fb_budget_expenditures", "Government expenditures", P("Budget", "expenditures"), "US dollars",
           "government", 1e5, 1e14, 0, False, agg="sum"),
    Series("fb_exports", "Exports of goods and services (Factbook)", P("Exports", _V), "US dollars", "trade", 1e5,
           1e14, 0, False, agg="sum"),
    Series("fb_imports", "Imports of goods and services (Factbook)", P("Imports", _V), "US dollars", "trade", 1e5,
           1e14, 0, False, agg="sum"),
    Series("fb_current_account", "Current account balance (Factbook)", P("Current account balance", _V),
           "US dollars", "trade", -5e12, 5e12, 0, False, agg="sum"),
    Series("fb_reserves", "Reserves of foreign exchange and gold (Factbook)",
           P("Reserves of foreign exchange and gold", _V), "US dollars", "finance", 1e4, 1e14, 0, False, agg="sum"),
    Series("fb_external_debt", "External debt", P("Debt - external", _V), "US dollars", "debt", 1e5, 1e15, 0,
           agg="sum"),
    Series("fb_labour_force", "Labour force (Factbook)", P("Labor force", _V), "people", "labour", 500, 1.5e9, 0,
           False, agg="sum"),
    Series("fb_poverty_national", "Population below the national poverty line",
           P("Population below poverty line", _V), "%", "poverty", 0, 100),
    Series("fb_gini", "Gini index (Factbook)", P("Gini Index coefficient - distribution of family income", _V),
           "index", "poverty", 15, 80, on=False),
    Series("fb_industrial_production_growth", "Industrial production growth",
           P("Industrial production growth rate", _V), "%", "economy", -80, 150),
    # Energy and resources.
    Series("fb_oil_production", "Crude oil production", P("Crude oil - production", _V, "Oil - production", _V),
           "barrels per day", "energy", 0, 2e7, 0, agg="sum"),
    Series("fb_petroleum_production", "Total petroleum production", P("Petroleum", "total_petroleum_production"),
           "barrels per day", "energy", 0, 3e7, 0, agg="sum"),
    Series("fb_oil_reserves", "Proven crude oil reserves", P("Crude oil - proved reserves", _V,
                                                             "Oil - proved reserves", _V,
                                                             "Petroleum", "crude_oil_estimated_reserves"),
           "barrels", "energy", 0, 5e11, 0, agg="sum"),
    Series("fb_refined_consumption", "Refined petroleum consumption",
           P("Refined petroleum products - consumption", _V, "Oil - consumption", _V,
             "Petroleum", "refined_petroleum_consumption"), "barrels per day", "energy", 0, 3e7, 0, agg="sum"),
    Series("fb_gas_production", "Natural gas production", P("Natural gas - production", _V, "Natural gas", "production"),
           "cubic metres", "energy", 0, 2e12, 0, agg="sum"),
    Series("fb_gas_consumption", "Natural gas consumption",
           P("Natural gas - consumption", _V, "Natural gas", "consumption"), "cubic metres", "energy", 0, 2e12, 0,
           agg="sum"),
    Series("fb_gas_exports", "Natural gas exports", P("Natural gas - exports", _V, "Natural gas", "exports"),
           "cubic metres", "energy", 0, 1e12, 0, agg="sum"),
    Series("fb_gas_imports", "Natural gas imports", P("Natural gas - imports", _V, "Natural gas", "imports"),
           "cubic metres", "energy", 0, 1e12, 0, agg="sum"),
    Series("fb_gas_reserves", "Proven natural gas reserves",
           P("Natural gas - proved reserves", _V, "Natural gas", "proven_reserves"), "cubic metres", "energy", 0,
           1e14, 0, agg="sum"),
    Series("fb_coal_production", "Coal production", P("Coal", "production"), "metric tonnes", "energy", 0, 1e10, 0,
           agg="sum"),
    Series("fb_coal_reserves", "Proven coal reserves", P("Coal", "proven_reserves"), "metric tonnes", "energy", 0,
           1e12, 0, agg="sum"),
    Series("fb_elec_capacity", "Electricity generating capacity",
           P("Electricity - installed generating capacity", _V, "Electricity - capacity", _V,
             "Electricity", "installed_generating_capacity"), "kW", "energy", 0, 1e10, 0, agg="sum"),
    Series("fb_elec_consumption", "Electricity consumption (Factbook)",
           P("Electricity - consumption", _V, "Electricity", "consumption"), "kWh", "energy", 0, 2e13, 0, False,
           agg="sum"),
    Series("fb_energy_per_capita", "Energy consumption per person (Factbook)", P("Energy consumption per capita", _V),
           "million Btu per person", "energy", 0, 2000, on=False),
    Series("fb_co2_emissions", "Carbon dioxide emissions from energy (Factbook)",
           P("Carbon dioxide emissions", "total|" + _V), "metric tonnes", "environment", 0, 2e10, 0, False, agg="sum"),
    # Transport and communications.
    Series("fb_airports", "Airports", P("Airports", "total|" + _V), "airports", "infrastructure", 0, 20_000, 0,
           dated=False, agg="sum"),
    Series("fb_railways_km", "Railways", P("Railways", "total|" + _V), "km", "infrastructure", 0, 300_000, 0,
           dated=False, agg="sum"),
    Series("fb_roadways_km", "Roads", P("Roadways", "total|" + _V), "km", "infrastructure", 0, 8e6, 0, dated=False,
           agg="sum"),
    Series("fb_waterways_km", "Navigable waterways", P("Waterways", _V), "km", "infrastructure", 0, 200_000, 0,
           dated=False, agg="sum"),
    Series("fb_merchant_marine", "Merchant fleet", P("Merchant marine", "total|" + _V), "ships", "infrastructure", 0,
           30_000, 0, dated=False, agg="sum"),
    Series("fb_internet_users_share", "Internet users (Factbook)", P("Internet users", "percent_of_population"),
           "% of population", "infrastructure", 0, 100, on=False),
    Series("fb_mobile_per_100", "Mobile phone subscriptions per 100 people (Factbook)",
           P("Telephones - mobile cellular", "subscriptions_per_100"), "per 100 people", "infrastructure", 0, 400, 0,
           on=False),
    # People and health.
    Series("fb_literacy", "Literacy (Factbook)", P("Literacy", "total_population"), "% of people 15 and over",
           "education", 0, 100, on=False),
    Series("fb_school_life_expectancy", "School life expectancy",
           P("School life expectancy (primary to tertiary education)", "total"), "years", "education", 0, 30),
    Series("fb_obesity", "Adult obesity", P("Obesity - adult prevalence rate", _V), "% of adults", "health", 0, 80),
    Series("fb_alcohol_per_capita", "Alcohol consumption per person", P("Alcohol consumption per capita", "total"),
           "litres of pure alcohol", "health", 0, 30),
    Series("fb_tobacco_use", "Tobacco use", P("Tobacco use", "total"), "% of adults", "health", 0, 90),
    Series("fb_mother_age_first_birth", "Mother's mean age at first birth", P("Mother's mean age at first birth", _V),
           "years", "population", 14, 40),
    Series("fb_urban_share", "Urban population (Factbook)", P("Urbanization", "urban_population"), "% of population",
           "cities", 0, 100, on=False),
    # Geography.
    Series("fb_area_total", "Area (Factbook)", P("Area", "total"), "sq km", "geography", 0.1, 2e7, 0, False,
           dated=False, agg="sum"),
    Series("fb_coastline_km", "Coastline", P("Coastline", _V), "km", "geography", 0, 300_000, 0, dated=False,
           agg="sum"),
    Series("fb_land_boundaries_km", "Land borders", P("Land boundaries", "total|" + _V), "km", "geography", 0, 30_000,
           0, dated=False),
    Series("fb_elevation_highest", "Highest point", P("Elevation", "highest"), "metres", "geography", 0, 9_000, 0,
           dated=False),
    Series("fb_elevation_mean", "Mean elevation", P("Elevation", "mean"), "metres", "geography", 0, 6_000, 0,
           dated=False),
)
SHARED = {"pop_total", "life_expectancy", "tfr", "median_age", "cbr", "cdr", "infant_mortality", "net_migration_rate",
          "gdp_growth", "inflation", "unemployment", "military_spending_gdp"}


class CIAFactbook(Connector):
    source_id = SOURCE
    frozen = True  # the archive does not change: a refresh skips it once a vintage exists

    def default_release(self, fetched_at: datetime) -> str:
        return "1990-2025"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "1990-2025"

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(URL, raw_dir / FILE)
        if not _is_sqlite(raw_dir / FILE):
            raise ConnectorError(f"GET {URL} did not return a SQLite database")
        return URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        db = next((p for p in sorted(raw_dir.iterdir()) if _is_sqlite(p)), None)
        if db is None:
            raise ConnectorError(f"{SOURCE}: no factbook.db in {raw_dir}")
        src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            codes = entity_codes(src)
            work = Path(tempfile.mkdtemp(prefix="factbook-"))
            try:
                obs_csv, n_obs = _write_observations(src, codes, work / "observations.csv")
                texts_csv, n_texts = _write_texts(src, codes, work / "texts.csv")
                con.execute(f"CREATE TABLE fb_obs AS SELECT * FROM read_csv({sql_str(obs_csv.as_posix())}, header = true, "
                            "columns = {'scheme': 'VARCHAR', 'source_code': 'VARCHAR', 'indicator_id': 'VARCHAR', "
                            "'year': 'INTEGER', 'value': 'DOUBLE'})")
                con.execute(f"CREATE TABLE fb_texts AS SELECT * FROM read_csv({sql_str(texts_csv.as_posix())}, header = true, "
                            "columns = {'scheme': 'VARCHAR', 'source_code': 'VARCHAR', 'edition': 'INTEGER', "
                            "'section': 'VARCHAR', 'field': 'VARCHAR', 'field_key': 'VARCHAR', 'content': 'VARCHAR', "
                            "'position': 'INTEGER'}, max_line_size = 4000000)")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        finally:
            src.close()
        log.info("%s: %s values in %s series, %s text fields", SOURCE, n_obs, len(SERIES), n_texts)
        self.listed_indicators = [_indicator(s) for s in SERIES]
        self.texts_query = (f"SELECT '{SOURCE}' AS source_id, {sql_str(vintage)} AS vintage, scheme, source_code, edition, "
                            "section, field, field_key, content, position FROM fb_texts")
        return (f"SELECT '{SOURCE}' AS source_id, {sql_str(vintage)} AS vintage, scheme, source_code, indicator_id, "
                "make_date(year, 1, 1) AS period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, value, "
                "'E' AS status FROM fb_obs")


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def entity_codes(src: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """CountryID -> (scheme, code) in worldmodel's crosswalk, for every edition's entity that maps."""
    shared: dict[str, int] = {}
    for (iso2,) in src.execute("SELECT ISOAlpha2 FROM MasterCountries WHERE ISOAlpha2 IS NOT NULL"):
        shared[iso2] = shared.get(iso2, 0) + 1
    out = {}
    for cid, year, name, fips, iso2 in src.execute("""
            SELECT c.CountryID, c.Year, c.Name, m.CanonicalCode, m.ISOAlpha2
            FROM Countries c LEFT JOIN MasterCountries m USING (MasterCountryID)"""):
        key = (name or "").strip().lower()
        if key == "yugoslavia" and year > 1992:  # what Serbia and Montenegro called itself until 2003
            out[cid] = ("iso3", "SCG")
        elif key in BY_NAME:
            out[cid] = ("iso3", BY_NAME[key])
        elif fips in BY_FIPS:
            if BY_FIPS[fips]:
                out[cid] = BY_FIPS[fips]
        elif iso2 and (shared[iso2] == 1 and iso2 not in PRIMARY or PRIMARY.get(iso2) == fips):
            out[cid] = ("iso2", iso2)
    return out


def _write_observations(src: sqlite3.Connection, codes: dict[int, tuple[str, str]], path: Path) -> tuple[Path, int]:
    by_field: dict[str, list[tuple[Series, re.Pattern]]] = {}
    for s in SERIES:
        for f, sub in s.parts:
            by_field.setdefault(f, []).append((s, re.compile(rf"^(?:{sub})$")))
    names = ", ".join("?" * len(by_field))
    rows = src.execute(f"""
        SELECT c.CountryID, c.Year, coalesce(m.CanonicalName, cf.FieldName), fv.SubField, fv.NumericVal, fv.DateEst,
            fv.SourceFragment, fv.FieldID, cf.Content
        FROM FieldValues fv
        JOIN CountryFields cf USING (FieldID)
        JOIN Countries c USING (CountryID)
        LEFT JOIN FieldNameMappings m ON m.OriginalName = cf.FieldName
        WHERE coalesce(m.CanonicalName, cf.FieldName) IN ({names}) AND fv.NumericVal IS NOT NULL
            AND coalesce(m.IsNoise, 0) = 0
        ORDER BY c.Year, fv.ValueID""", list(by_field))
    best: dict[tuple[tuple[str, str], str, int], tuple[int, float]] = {}  # -> (edition, value)
    cursor: dict[int, int] = {}  # FieldID -> where in its text the last fragment was found
    for cid, edition, field, sub, numeric, date_est, fragment, fid, content in rows:
        code = codes.get(cid)
        if code is None:
            continue
        # The text just after this value, where an undated fragment's "(2019 est.)" usually is.
        frag = (fragment or "").strip()
        at = (content or "").find(frag, cursor.get(fid, 0)) if frag else -1
        if at >= 0:
            cursor[fid] = at + len(frag)
        after = content[at:at + len(frag) + 30] if at >= 0 else ""
        for s, pattern in by_field[field]:
            if not pattern.match(sub or ""):
                continue
            value = number(fragment, numeric)
            if value is None or not s.lo <= value <= s.hi:
                continue
            year = estimate_year(sub, fragment, date_est, after)
            if year is None:
                if s.dated:
                    continue
                year = edition
            if not 1950 <= year <= edition + 1:
                continue
            key = (code, s.id, year)
            have = best.get(key)
            if have is None or have[0] < edition:  # a later edition revises; within one, the first value stands
                best[key] = (edition, value)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scheme", "source_code", "indicator_id", "year", "value"])
        for ((scheme, code), ind, year), (_, value) in sorted(best.items()):
            w.writerow([scheme, code, ind, year, f"{value:.12g}"])
    return path, len(best)


def _write_texts(src: sqlite3.Connection, codes: dict[int, tuple[str, str]], path: Path) -> tuple[Path, int]:
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scheme", "source_code", "edition", "section", "field", "field_key", "content", "position"])
        for cid, edition, section, field, key, content, fid in src.execute("""
                SELECT c.CountryID, c.Year, cc.CategoryTitle, cf.FieldName, coalesce(m.CanonicalName, cf.FieldName),
                    cf.Content, cf.FieldID
                FROM CountryFields cf
                JOIN Countries c USING (CountryID)
                JOIN CountryCategories cc USING (CategoryID)
                LEFT JOIN FieldNameMappings m ON m.OriginalName = cf.FieldName
                WHERE coalesce(m.IsNoise, 0) = 0 AND cc.CategoryTitle <> 'Full Content'
                ORDER BY c.CountryID, cf.FieldID"""):
            code = codes.get(cid)
            text = (content or "").strip()
            if code is None or not text or any(j in text[:200].lower() for j in JUNK):
                continue
            w.writerow([code[0], code[1], edition, (section or "").strip(), (field or "").strip(), (key or "").strip(),
                        text, fid])
            n += 1
    return path, n


def number(fragment: str | None, parsed: float | None) -> float | None:
    """The figure in a text fragment, scaled by any "million" after it; the archive's number if none is found."""
    text = (fragment or "").split(":", 1)[-1] if ":" in (fragment or "")[:60] else (fragment or "")
    m = NUMBER.search(text)
    if not m:
        return parsed
    try:
        value = float(m.group(3).replace(",", ""))
    except ValueError:
        return parsed
    if m.group(4):
        value *= MULTIPLIER[m.group(4).lower()]
    return -value if (m.group(1) or m.group(2)) else value


def estimate_year(sub: str | None, fragment: str | None, date_est: str | None, after: str = "") -> int | None:
    """The year a figure is for: from a sub-field like value_2024, the fragment's "(2023 est.)", the archive's
    date, or a bracketed year just after the figure in the field's text."""
    m = re.search(r"_((?:19|20)\d\d)$", sub or "")
    if m:
        return int(m.group(1))
    for text in (fragment or "", f"({date_est})" if date_est else "", after):
        for part in re.findall(r"\(([^()]*)\)", text):
            y = _year(part)
            if y:
                return y
    return None


def _year(text: str) -> int | None:
    m = FISCAL.search(text)
    if m:
        yy = int(m.group(2) or m.group(1))
        return 2000 + yy if yy < 50 else 1900 + yy
    m = YEAR.search(text)
    return int(m.group(1)) if m else None


def _indicator(s: Series) -> dict:
    agg = {"method": s.agg}
    return {
        "id": s.id, "name": s.name, "domain": s.domain, "unit": s.unit, "decimals": s.decimals,
        "description": s.description or f"{s.name}, as the CIA World Factbook gave it (fields: {', '.join(s.fields)}). "
                                       "Figures from every edition 1990-2025, each dated by the year it is an "
                                       "estimate for; where editions differ the latest is kept. The Factbook ended "
                                       "in 2026, so this series is frozen.",
        "synonyms": ["CIA World Factbook", *s.fields], "aggregation": agg,
        # The range a country's figure must fall in; group totals (sums) may go far beyond it.
        "bounds": [min(s.lo, 0), 1e18] if s.agg == "sum" else [s.lo, s.hi],
        "sources": [{"source_id": SOURCE, "series": s.id, "scale": 1.0,
                     "notes": "CIA World Factbook, all editions 1990-2025 (archive by the CIA World Factbooks "
                              "Archive project)"}],
        "default_on": s.on and s.id not in SHARED,
    }
