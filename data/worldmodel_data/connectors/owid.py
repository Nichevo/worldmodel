"""Our World in Data: the energy dataset, and single charts (conflict deaths from UCDP).

owid_energy
    https://github.com/owid/energy-data: owid-energy-data.csv (one row per country
    and year, one column per series) and owid-energy-codebook.csv (title,
    description, unit and source of each column). OWID compiles it from Ember
    (electricity), the Energy Institute Statistical Review of World Energy
    (primary energy, production) and the US EIA. Every column is stored under its
    own name as the indicator id; the main ones (ENERGY_MAIN) start switched on.

owid_grapher
    Single OWID charts, by their address: https://ourworldindata.org/grapher/<slug>.csv
    and <slug>.metadata.json (column names, units, descriptions). CHARTS lists the
    ones fetched, a second apart; a chart that has gone only warns: armed conflict
    deaths (UCDP), inequality (the World Inequality Database), values (the World
    Values Survey), and science (journal articles, patents). Each numeric column
    becomes an indicator, switched on: the chart's own id where CHARTS gives one
    (wid_income_top1), else `owid_<column>`.

Countries are matched by ISO alpha-3 code. Of OWID's own regions, only the World,
Kosovo and the World Bank income groups are kept (scheme `owid` in the crosswalk);
worldmodel builds its continents and blocs from members itself. A copy of the
files can be given instead: worldmodel-data fetch owid_energy --from DIR.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str

log = logging.getLogger(__name__)

ENERGY_BASE = "https://raw.githubusercontent.com/owid/energy-data/master/"
ENERGY_FILES = ("owid-energy-data.csv", "owid-energy-codebook.csv")
SKIP_COLUMNS = {"country", "year", "iso_code", "population", "gdp"}  # population and GDP come from the UN and the IMF
RENAME = {"greenhouse_gas_emissions": "elec_lifecycle_emissions"}  # it covers electricity generation only
ENERGY_MAIN = {
    "electricity_generation", "per_capita_electricity", "electricity_demand", "electricity_demand_per_capita",
    "net_elec_imports_share_demand", "carbon_intensity_elec", "elec_lifecycle_emissions",
    "renewables_share_elec", "low_carbon_share_elec", "fossil_share_elec", "coal_share_elec", "gas_share_elec",
    "oil_share_elec", "nuclear_share_elec", "hydro_share_elec", "solar_share_elec", "wind_share_elec",
    "primary_energy_consumption", "energy_per_capita", "energy_per_gdp", "fossil_share_energy",
    "renewables_share_energy", "low_carbon_share_energy", "oil_production", "gas_production", "coal_production",
    "oil_consumption", "gas_consumption", "coal_consumption",
}

GRAPHER = "https://ourworldindata.org/grapher/"
GRAPHER_QUERY = "?v=1&csvType=full&useColumnShortNames=true"
# (slug, what it is, indicator id or None for owid_<column>, domain). A chart with one value
# column stores it under the id; with several, under <id>_<column>. Deaths are placed where
# they occurred, not by the nationality of those killed.
CHARTS = (
    ("death-rate-in-armed-conflicts", "UCDP: deaths in armed conflicts per 100,000 people, by country where they occurred",
     None, "conflict"),
    ("death-rate-in-armed-conflicts-by-type-and-country", "UCDP: the same death rate, by type of conflict", None, "conflict"),
    # inequality: the World Inequality Database (WID), before tax, from national accounts, tax and survey data
    ("income-share-top-1-before-tax-wid", "WID: share of income going to the richest 1%, before tax", "wid_income_top1", "inequality"),
    ("income-share-top-10-before-tax-wid", "WID: share of income going to the richest 10%, before tax", "wid_income_top10", "inequality"),
    ("wealth-share-richest-1-percent", "WID: share of wealth held by the richest 1%", "wid_wealth_top1", "inequality"),
    ("wealth-share-richest-10-percent", "WID: share of wealth held by the richest 10%", "wid_wealth_top10", "inequality"),
    ("palma-ratio-wid", "WID: income of the richest 10% divided by that of the poorest 40%", "wid_palma", "inequality"),
    # values: the World Values Survey and European Values Study, through OWID
    ("self-reported-trust-attitudes", "World Values Survey: share agreeing that most people can be trusted", "wvs_trust", "values"),
    ("how-important-religion-is-in-your-life", "World Values Survey: how important religion is in people's lives",
     "wvs_religion_important", "values"),
    ("share-of-people-who-say-they-are-happy", "World Values Survey: share who say they are very or rather happy",
     "wvs_happy", "values"),
    # science
    ("scientific-publications-per-million", "Articles in scientific and technical journals per million people (NSF)",
     "science_articles_per_million", "science"),
    ("patent-applications-per-million", "Patent applications per million people (WIPO)", "patents_per_million", "science"),
    ("scholarly-publications-on-artificial-intelligence-per-million-people",
     "Scholarly publications on artificial intelligence per million people (CSET)", "ai_publications_per_million", "science"),
    # pollution (the Pollution page)
    ("death-rate-from-air-pollution-per-100000", "IHME Global Burden of Disease: deaths from outdoor and indoor air "
     "pollution per 100,000 people, age-standardised", "air_pollution_death_rate", "pollution"),
    ("share-deaths-air-pollution", "IHME Global Burden of Disease: share of all deaths caused by air pollution",
     "air_pollution_death_share", "pollution"),
    ("emissions-of-air-pollutants", "Community Emissions Data System (CEDS): emissions of sulphur dioxide, nitrogen "
     "oxides, black and organic carbon, ammonia, carbon monoxide and other air pollutants, back to 1750", "airpol", "pollution"),
    ("plastic-waste-emitted-to-the-ocean", "Meijer et al. (2021): plastic reaching the ocean from rivers and coasts, tonnes a year",
     "ocean_plastic", "pollution"),
    ("per-capita-ocean-plastic-waste", "Meijer et al. (2021): plastic reaching the ocean per person, kg a year",
     "ocean_plastic_per_capita", "pollution"),
    ("share-of-global-plastic-waste-emitted-to-the-ocean", "Meijer et al. (2021): share of the world's plastic reaching the ocean",
     "ocean_plastic_share", "pollution"),
    # nature (the Nature tab on the Climate page)
    ("global-living-planet-index", "WWF and ZSL Living Planet Index: average change in tracked wild animal populations "
     "since 1970 (1970 = 100), by region", "living_planet_index", "nature"),
    ("red-list-index", "IUCN Red List Index: 1 = no species at risk, 0 = all extinct; falling means more species "
     "moving towards extinction", "red_list_index_owid", "nature"),
    ("threatened-mammal-species", "IUCN: mammal species threatened with extinction, by country", "threatened_mammals", "nature"),
    ("threatened-bird-species", "IUCN: bird species threatened with extinction, by country", "threatened_birds", "nature"),
    ("tree-cover-loss", "Global Forest Watch: tree cover lost each year, hectares", "tree_cover_loss", "nature"),
    # democracy and autocracy (the Democracy topic)
    ("democracy-index-eiu", "Economist Intelligence Unit Democracy Index: 0 to 10 from elections, how government works, "
     "taking part, political culture and civil liberties; 8 and over full democracy, 6-8 flawed, 4-6 hybrid, under 4 "
     "authoritarian", "democracy_eiu", "democracy"),
    ("political-regime", "Regimes of the World (V-Dem): 0 closed autocracy, 1 electoral autocracy, 2 electoral democracy, "
     "3 liberal democracy", "regime_row", "democracy"),
    ("electoral-democracy-index", "V-Dem electoral democracy index: 0 to 1, how far rulers answer to voters in free and "
     "fair elections with free speech and association", "vdem_electoral", "democracy"),
    ("liberal-democracy-index", "V-Dem liberal democracy index: 0 to 1, electoral democracy plus limits on government "
     "(courts, rights, checks)", "vdem_liberal", "democracy"),
    ("political-rights-score-fh", "Freedom House political rights score: 0 to 40, higher is freer", "fh_political_rights",
     "democracy"),
    ("civil-liberties-score-fh", "Freedom House civil liberties score: 0 to 60, higher is freer", "fh_civil_liberties",
     "democracy"),
)
CHART = {c[0]: c for c in CHARTS}


class _OWID(Connector):
    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")  # OWID files carry no release name; unchanged files are not stored again

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def _stage_wide(self, con: duckdb.DuckDBPyConnection, table: str, path: Path, entity: str, code: str,
                    year: str, columns: dict[str, str]) -> None:
        """Long rows (source_code, scheme, indicator_id, period_start, value) from a wide CSV into `table`.
        columns maps CSV column -> indicator id."""
        owid_codes = self.known_codes("owid")
        con.execute(f"CREATE TEMP TABLE wide AS SELECT * FROM read_csv({sql_str(path.as_posix())}, header = true, "
                    f"all_varchar = true)")
        con.execute("CREATE TEMP TABLE colmap (col VARCHAR, indicator_id VARCHAR)")
        con.executemany("INSERT INTO colmap VALUES (?, ?)", list(columns.items()))
        cols = ", ".join(f'"{c}"' for c in columns)
        known = ", ".join(sql_str(c) for c in sorted(owid_codes)) or "''"
        con.execute(f"""
            INSERT INTO {table}
            SELECT CASE WHEN regexp_matches(coalesce(c, ''), '^[A-Z]{{3}}$') THEN c
                        WHEN coalesce(c, '') IN ({known}) THEN c ELSE e END AS source_code,
                   CASE WHEN regexp_matches(coalesce(c, ''), '^[A-Z]{{3}}$') THEN 'iso3' ELSE 'owid' END AS scheme,
                   m.indicator_id, make_date(y, 1, 1) AS period_start, v AS value
            FROM (SELECT "{entity}" AS e, nullif(trim("{code}"), '') AS c, TRY_CAST("{year}" AS INTEGER) AS y,
                         col, TRY_CAST(val AS DOUBLE) AS v
                  FROM (UNPIVOT wide ON {cols} INTO NAME col VALUE val)) u
            JOIN colmap m USING (col)
            WHERE v IS NOT NULL AND isfinite(v) AND y IS NOT NULL
              AND (regexp_matches(coalesce(c, ''), '^[A-Z]{{3}}$') OR coalesce(c, '') IN ({known}) OR e IN ({known}))""")
        con.execute("DROP TABLE wide")
        con.execute("DROP TABLE colmap")

    def _query(self, vintage: str, table: str) -> str:
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, scheme, source_code, "
                f"indicator_id, period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, value, "
                f"'E' AS status FROM {table}")


class OWIDEnergy(_OWID):
    source_id = "owid_energy"
    fetch_every_days = 14  # checked at most this often; the site answering "not changed" also skips the download

    def download(self, raw_dir: Path, release: str) -> str:
        for name in ENERGY_FILES:
            self.get(ENERGY_BASE + name, raw_dir / name)
        return " ".join(ENERGY_BASE + n for n in ENERGY_FILES)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        data = raw_dir / ENERGY_FILES[0]
        if not data.exists():
            raise ConnectorError(f"owid_energy: {data.name} missing from {raw_dir}")
        book_path = raw_dir / ENERGY_FILES[1]
        book = {}
        if book_path.exists():
            with book_path.open(encoding="utf-8-sig", newline="") as f:
                book = {r["column"]: r for r in csv.DictReader(f)}
        else:
            log.warning("owid_energy: no codebook; indicator names will be the column names")
        with data.open(encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f))
        if not {"country", "year", "iso_code"} <= set(header):
            raise ConnectorError(f"owid_energy: {data.name} lacks the country, year and iso_code columns")
        columns = {c: RENAME.get(c, c) for c in header if c not in SKIP_COLUMNS and re.fullmatch(r"[a-z0-9_]+", c)}
        con.execute("CREATE TABLE energy (source_code VARCHAR, scheme VARCHAR, indicator_id VARCHAR, "
                    "period_start DATE, value DOUBLE)")
        self._stage_wide(con, "energy", data, "country", "iso_code", "year", columns)
        ids = set(columns.values())
        self.listed_indicators = [_energy_indicator(col, ind, book.get(col, {}), ids) for col, ind in columns.items()]
        return self._query(vintage, "energy")


def _energy_indicator(col: str, ind: str, meta: dict[str, str], ids: set[str]) -> dict:
    unit = (meta.get("unit") or "").strip()
    return {
        "id": ind, "name": (meta.get("title") or col.replace("_", " ").capitalize()).strip(),
        "description": (meta.get("description") or meta.get("title") or col).strip(),
        "synonyms": [col] if col != ind else [], "domain": "energy", "unit": _short_unit(unit),
        "decimals": 0 if "twh" in unit.lower() and "per" not in unit.lower() else 1,
        "aggregation": _energy_aggregation(ind, unit, ids),
        "bounds": [-1e18, 1e18],
        "sources": [{"source_id": "owid_energy", "series": col, "scale": 1.0,
                     "notes": re.sub(r"\s*\[https?://[^\]]*\]", "", meta.get("source", "")).strip()[:500]}],
        "default_on": ind in ENERGY_MAIN,
    }


def _short_unit(unit: str) -> str:
    """'terawatt-hours (TWh)' -> 'TWh'; '%' stays; others as given."""
    m = re.search(r"\(([^()]+)\)\s*$", unit)
    return m.group(1) if m and len(m.group(1)) <= 12 else unit


def _energy_aggregation(ind: str, unit: str, ids: set[str]) -> dict:
    """How continents and blocs are built: energy amounts add up; shares and per-person
    figures are recomputed from the amounts behind them; the rest is left alone."""
    def amount(prefix: str) -> str | None:
        for c in (f"{prefix}_electricity", f"{prefix.rstrip('s')}_electricity"):
            if c in ids:
                return c
        return None

    if ind == "carbon_intensity_elec" and "electricity_generation" in ids:
        return {"method": "weighted_mean", "weight": "electricity_generation"}
    if (m := re.fullmatch(r"(.+)_share_elec", ind)) and (num := amount(m.group(1))) and "electricity_generation" in ids:
        return {"method": "ratio", "numerator": num, "denominator": "electricity_generation", "multiplier": 100}
    per_person = {"per_capita_electricity": "electricity_generation",
                  "electricity_demand_per_capita": "electricity_demand",
                  "energy_per_capita": "primary_energy_consumption"}
    if (m := re.fullmatch(r"(.+)_elec_per_capita", ind)) and (num := amount(m.group(1))):
        per_person[ind] = num
    if ind in per_person and per_person[ind] in ids:  # TWh per person to kWh per person
        return {"method": "ratio", "numerator": per_person[ind], "denominator": "pop_total", "multiplier": 1e9}
    if "twh" in unit.lower() and "per" not in unit.lower():
        return {"method": "sum"}
    return {"method": "none"}


class OWIDGrapher(_OWID):
    source_id = "owid_grapher"
    fetch_every_days = 14  # checked at most this often; the site answering "not changed" also skips the download
    stage_version = 5  # 2: long column names no longer cut to the same indicator id; 3: charts' own ids and domains; 4: pollution and nature charts; 5: democracy
    fetch_version = 3  # 2: pollution and nature charts added (fetched at the next refresh); 3: democracy charts
    pause_seconds = 1.0

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for i, (slug, *_) in enumerate(CHARTS):
            if i:
                time.sleep(self.pause_seconds)
            try:
                self.get(f"{GRAPHER}{slug}.csv{GRAPHER_QUERY}", raw_dir / f"{slug}.csv")
                self.get(f"{GRAPHER}{slug}.metadata.json{GRAPHER_QUERY}", raw_dir / f"{slug}.metadata.json")
                got.append(slug)
            except ConnectorError as exc:
                log.warning("owid_grapher: chart %s skipped (%s)", slug, exc)
                for p in raw_dir.glob(f"{slug}.*"):
                    p.unlink()
        if not got:
            raise ConnectorError("owid_grapher: none of the charts could be downloaded")
        return " ".join(f"{GRAPHER}{s}" for s in got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        con.execute("CREATE TABLE charts (source_code VARCHAR, scheme VARCHAR, indicator_id VARCHAR, "
                    "period_start DATE, value DOUBLE)")
        self.listed_indicators = []
        for path in sorted(raw_dir.glob("*.csv")):
            slug = path.stem
            meta_path = raw_dir / f"{slug}.metadata.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            with path.open(encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f))
            lower = {h.lower(): h for h in header}
            if not {"entity", "year"} <= set(lower):
                log.warning("owid_grapher: %s has no Entity and Year columns (a daily chart?); skipped", path.name)
                continue
            code = lower.get("code", lower["entity"])
            values = [h for h in header if h.lower() not in ("entity", "code", "year") and "annotation" not in h.lower()]
            _, about, own, domain = CHART.get(slug, (slug, "", None, "conflict" if "conflict" in slug else "other"))
            columns = {h: chart_id(own, h, len(values)) for h in values}
            self._stage_wide(con, "charts", path, lower["entity"], code, lower["year"], columns)
            for h, ind in columns.items():
                self.listed_indicators.append(_chart_indicator(slug, h, ind, meta.get("columns", {}).get(h, {}), about,
                                                               domain))
        if not self.listed_indicators:
            raise ConnectorError(f"owid_grapher: no chart files with yearly values in {raw_dir}")
        return self._query(vintage, "charts")


def chart_id(own: str | None, column: str, n: int) -> str:
    """The chart's own id for its only column; <own>_<column> for one of several; else owid_<column>."""
    if not own:
        return column_id(column)
    return own if n == 1 else own + column_id(column)[4:][:40]


def column_id(column: str) -> str:
    """The indicator id for a chart column: owid_ and the column name, shortened to fit.
    Long names often differ only at the end (deaths per conflict type: interstate,
    intrastate, intrastate internationalised), so a name cut short ends in a short
    hash of the whole name and two columns never share an id."""
    name = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
    if len(name) <= 60:
        return "owid_" + name
    return f"owid_{name[:51]}_{hashlib.sha1(name.encode()).hexdigest()[:8]}"


def _chart_indicator(slug: str, col: str, ind: str, meta: dict, about: str, domain: str) -> dict:
    unit = (meta.get("unit") or meta.get("shortUnit") or "").strip()
    name = (meta.get("titleShort") or meta.get("titleLong") or col.replace("_", " ")).strip()
    counts = unit.lower() in ("deaths", "conflicts", "people", "events") or unit.lower().startswith("deaths ")
    return {
        "id": ind, "name": name,
        "description": (meta.get("descriptionShort") or meta.get("description") or about or name).strip()[:1200],
        "synonyms": [slug], "domain": domain,
        "unit": unit, "decimals": 0 if counts else 2,
        "aggregation": {"method": "sum" if counts and "per" not in unit.lower() else "none"},
        "bounds": [-1e18, 1e18],
        "sources": [{"source_id": "owid_grapher", "series": f"{slug}:{col}", "scale": 1.0,
                     "notes": (meta.get("citationShort") or about)[:500]}],
        "default_on": True,
    }
