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
    ones fetched, a second apart; a chart that has gone only warns. Each numeric
    column becomes an indicator `owid_<column>`, switched on.

Countries are matched by ISO alpha-3 code. Of OWID's own regions, only the World,
Kosovo and the World Bank income groups are kept (scheme `owid` in the crosswalk);
worldmodel builds its continents and blocs from members itself. A copy of the
files can be given instead: worldmodel-data fetch owid_energy --from DIR.
"""

from __future__ import annotations

import csv
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
# (slug, what it is). Deaths are placed where they occurred, not by the nationality of those killed.
CHARTS = (
    ("death-rate-in-armed-conflicts", "UCDP: deaths in armed conflicts per 100,000 people, by country where they occurred"),
    ("deaths-in-armed-conflicts-based-on-where-they-occurred", "UCDP: deaths in armed conflicts, by country where they occurred"),
)


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
    pause_seconds = 1.0

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for i, (slug, _) in enumerate(CHARTS):
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
            columns = {h: "owid_" + re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")[:60] for h in values}
            self._stage_wide(con, "charts", path, lower["entity"], code, lower["year"], columns)
            about = dict(CHARTS).get(slug, "")
            for h, ind in columns.items():
                self.listed_indicators.append(_chart_indicator(slug, h, ind, meta.get("columns", {}).get(h, {}), about))
        if not self.listed_indicators:
            raise ConnectorError(f"owid_grapher: no chart files with yearly values in {raw_dir}")
        return self._query(vintage, "charts")


def _chart_indicator(slug: str, col: str, ind: str, meta: dict, about: str) -> dict:
    unit = (meta.get("unit") or meta.get("shortUnit") or "").strip()
    name = (meta.get("titleShort") or meta.get("titleLong") or col.replace("_", " ")).strip()
    counts = unit.lower() in ("deaths", "conflicts", "people", "events") or unit.lower().startswith("deaths ")
    return {
        "id": ind, "name": name,
        "description": (meta.get("descriptionShort") or meta.get("description") or about or name).strip()[:1200],
        "synonyms": [slug], "domain": "conflict" if "conflict" in slug or "war" in slug else "other",
        "unit": unit, "decimals": 0 if counts else 2,
        "aggregation": {"method": "sum" if counts and "per" not in unit.lower() else "none"},
        "bounds": [-1e18, 1e18],
        "sources": [{"source_id": "owid_grapher", "series": f"{slug}:{col}", "scale": 1.0,
                     "notes": (meta.get("citationShort") or about)[:500]}],
        "default_on": True,
    }
