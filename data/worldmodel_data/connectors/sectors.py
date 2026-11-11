"""Sectors: trade by product and country pair, production by country, and prices.

The stages, HS codes and production sources come from the contract's sectors.yaml.

baci
    CEPII BACI: every country's goods trade with every other, by HS product, from 1995
    (one zip per HS edition, about 2 GB; the HS 1992 edition is used so years line up).
    Each yearly file (t, i, j, k, v, q: year, exporter, importer, product, thousand US$,
    tonnes) is read with DuckDB and summed into
      - each sector stage's exports by exporter and importer (routes of at least
        US$ 1 million), with totals, in US$ and tonnes, and its imports by importer;
      - every HS chapter's exports and imports by country (the By country view), with
        the top five partners in the latest two years.
    Years from Settings: Sectors (trade from 2005 by default) to keep the warehouse lean.

usgs_mcs
    USGS Mineral Commodity Summaries, world data release (one CSV: commodity, country,
    type, unit, production for the last two years, reserves). Read for every mined or
    smelted stage that names a USGS commodity.

wmd
    World Mining Data (Austrian ministry): production of about 65 minerals by country,
    one sheet per mineral, five years per edition. Editions saved by hand build up.

faostat
    FAOSTAT bulk files (normalized CSV inside zips): crops and livestock products,
    fertilizers by nutrient, and forestry production. Only the items sectors.yaml names.

wb_pinksheet
    World Bank commodity prices (the Pink Sheet), monthly since 1960, in US$: one
    indicator per price, on the "world" entity.

iea_ev
    IEA Global EV Data: electric car sales and stock by country since 2010 (sales share,
    battery-electric and plug-in hybrid sales), the "Electric shift" on the Cars page.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_contract import sectors as sec
from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, is_country, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)

ROUTE_MIN_USD = 1_000_000
TOP_PARTNERS = 5


def _settings() -> dict:
    from worldmodel_contract.local import load_settings
    from worldmodel_data.config import paths
    return load_settings(paths().home)


def _country(name: str) -> str | None:
    if not name:
        return None
    e = catalogue.country_by_name(str(name).strip().rstrip("*").strip())
    return e


# ----------------------------------------------------------------------------- BACI
BACI_PAGE = "https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37"
BACI_BASE = "https://www.cepii.fr/DATA_DOWNLOAD/baci/data/"
BACI_SPECIAL = {"490": "TWN", "S19": "TWN"}  # "Other Asia, nes" is Taiwan


class BACI(Connector):
    source_id = "baci"
    stage_version = 2  # 2: the sectors added in version 4
    switch = "sectors_trade_fetch"
    fetch_every_days = 120

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"V(20\d\d)(\d\d)", f.name)
            if m:
                return f"{m.group(1)}-{m.group(2)}"
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        names = []
        try:
            r = self.client.get(BACI_PAGE)
            names = re.findall(r"BACI_HS92_V\d{6}\.zip", r.text)
        except Exception as exc:  # noqa: BLE001 - try the likely names next
            log.info("baci: page not read (%s)", exc)
        year = int(release[:4])
        names = list(dict.fromkeys(sorted(names, reverse=True) + [f"BACI_HS92_V{y}01.zip" for y in (year, year - 1)]))
        for n in names:
            try:
                self.get(BACI_BASE + n, raw_dir / n)
                return BACI_BASE + n
            except ConnectorError as exc:
                log.info("baci: %s skipped (%s)", n, exc)
        raise ConnectorError("baci: no BACI HS92 zip could be downloaded")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        zips = sorted(raw_dir.glob("*.zip"))
        loose = sorted(raw_dir.glob("BACI_*_Y*.csv"))
        if not zips and not loose:
            raise ConnectorError(f"baci: no BACI zip or yearly CSV in {raw_dir}")
        first = int(_settings().get("sectors_trade_from", 2005))
        tmp = Path(tempfile.mkdtemp(prefix="baci_"))
        try:
            files = list(loose)
            for z in zips:
                with zipfile.ZipFile(z) as zf:
                    for n in zf.namelist():
                        base = n.rsplit("/", 1)[-1]
                        m = re.search(r"_Y(\d{4})_", base)
                        if (m and int(m.group(1)) >= first) or base.lower().startswith("country_codes"):
                            target = tmp / base
                            with zf.open(n) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            files.append(target)
            codes = [f for f in files if f.name.lower().startswith("country_codes")] or sorted(raw_dir.glob("country_codes*.csv"))
            years = sorted((f for f in files if re.search(r"_Y(\d{4})_", f.name)), key=lambda f: f.name)
            years = [f for f in years if int(re.search(r"_Y(\d{4})_", f.name).group(1)) >= first]
            if not years:
                raise ConnectorError(f"baci: no yearly files from {first} on")
            self._codes(con, codes[0] if codes else None)
            self._hs_map(con)
            con.execute("CREATE TABLE baci_stage (y INTEGER, i VARCHAR, j VARCHAR, stage VARCHAR, v DOUBLE, q DOUBLE)")
            con.execute("CREATE TABLE baci_chapter (y INTEGER, i VARCHAR, j VARCHAR, ch VARCHAR, v DOUBLE)")
            for f in years:
                self._year(con, f)
            last2 = [r[0] for r in con.execute("SELECT DISTINCT y FROM baci_chapter ORDER BY y DESC LIMIT 2").fetchall()]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.listed_indicators = baci_indicators(self.source_id)
        return baci_query(self.source_id, vintage, last2)

    def _codes(self, con: duckdb.DuckDBPyConnection, path: Path | None) -> None:
        """BACI's numeric country codes -> entity ids, via the ISO3 code in its country list."""
        rows = []
        if path:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for r in csv.DictReader(io.StringIO(text)):
                k = {key(a): (b or "").strip() for a, b in r.items() if a}
                code = k.get("countrycode")
                iso = k.get("countryiso3") or k.get("iso3digitalpha") or ""
                ent = BACI_SPECIAL.get(code) or BACI_SPECIAL.get(iso) or entity_for("iso3", iso) or entity_for("m49", code)
                if code and ent:
                    rows.append((code.lstrip("0") or "0", ent))
        con.execute("CREATE TABLE baci_codes (code VARCHAR, entity VARCHAR)")
        if rows:
            con.executemany("INSERT INTO baci_codes VALUES (?, ?)", rows)

    def _hs_map(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE TABLE hs_map (prefix VARCHAR, stage VARCHAR)")
        con.executemany("INSERT INTO hs_map VALUES (?, ?)", sec.hs_prefixes())

    def _year(self, con: duckdb.DuckDBPyConnection, f: Path) -> None:
        p = sql_str(f.as_posix())
        con.execute(f"""CREATE OR REPLACE TEMP TABLE yr AS
            SELECT TRY_CAST(t AS INTEGER) AS y, ci.entity AS i, cj.entity AS j,
                   lpad(trim(CAST(k AS VARCHAR)), 6, '0') AS k6,
                   TRY_CAST(trim(CAST(v AS VARCHAR)) AS DOUBLE) * 1000 AS v,
                   TRY_CAST(trim(CAST(q AS VARCHAR)) AS DOUBLE) AS q
            FROM read_csv({p}, header = true, all_varchar = true) r
            JOIN baci_codes ci ON ci.code = ltrim(trim(r.i), '0')
            JOIN baci_codes cj ON cj.code = ltrim(trim(r.j), '0')""")
        con.execute("""INSERT INTO baci_chapter SELECT y, i, j, substr(k6, 1, 2), sum(v) FROM yr WHERE v > 0 GROUP BY ALL""")
        con.execute("""INSERT INTO baci_stage
            SELECT y, i, j, coalesce(m6.stage, m4.stage, m2.stage) AS stage, sum(v), sum(q)
            FROM yr
            LEFT JOIN hs_map m6 ON m6.prefix = k6
            LEFT JOIN hs_map m4 ON m4.prefix = substr(k6, 1, 4)
            LEFT JOIN hs_map m2 ON m2.prefix = substr(k6, 1, 2)
            WHERE coalesce(m6.stage, m4.stage, m2.stage) IS NOT NULL AND v > 0
            GROUP BY ALL""")


def baci_query(source_id: str, vintage: str, last2: list[int]) -> str:
    """The staged rows from the baci_stage and baci_chapter tables."""
    sid, vin = sql_str(source_id), sql_str(vintage)
    yrs = ", ".join(str(y) for y in last2) or "0"

    def obs(sel: str) -> str:
        return (f"SELECT {sid} AS source_id, {vin} AS vintage, 'iso3' AS scheme, ent AS source_code, ind AS indicator_id, "
                f"make_date(y, 1, 1) AS period_start, 'A' AS freq, bd AS breakdown, 'central' AS variant, val AS value, "
                f"'E' AS status FROM ({sel})")
    parts = [
        # stage exports and imports, totals (US$ and tonnes)
        "SELECT i AS ent, 'sx_' || stage AS ind, y, '' AS bd, sum(v) AS val FROM baci_stage GROUP BY ALL",
        "SELECT i AS ent, 'sxq_' || stage AS ind, y, '' AS bd, sum(q) AS val FROM baci_stage WHERE q IS NOT NULL GROUP BY ALL",
        "SELECT j AS ent, 'sm_' || stage AS ind, y, '' AS bd, sum(v) AS val FROM baci_stage GROUP BY ALL",
        "SELECT j AS ent, 'smq_' || stage AS ind, y, '' AS bd, sum(q) AS val FROM baci_stage WHERE q IS NOT NULL GROUP BY ALL",
        # routes
        f"SELECT i AS ent, 'sx_' || stage AS ind, y, '{sec.PARTNER}' || j AS bd, v AS val FROM baci_stage WHERE v >= {ROUTE_MIN_USD}",
        f"SELECT i AS ent, 'sxq_' || stage AS ind, y, '{sec.PARTNER}' || j AS bd, q AS val FROM baci_stage "
        f"WHERE v >= {ROUTE_MIN_USD} AND q IS NOT NULL",
        # chapters, with the top partners in the latest two years
        "SELECT i AS ent, 'tgx_' || ch AS ind, y, '' AS bd, sum(v) AS val FROM baci_chapter GROUP BY ALL",
        "SELECT j AS ent, 'tgm_' || ch AS ind, y, '' AS bd, sum(v) AS val FROM baci_chapter GROUP BY ALL",
        f"""SELECT i AS ent, 'tgx_' || ch AS ind, y, '{sec.PARTNER}' || j AS bd, v AS val FROM (
              SELECT *, row_number() OVER (PARTITION BY y, i, ch ORDER BY v DESC) AS n FROM baci_chapter WHERE y IN ({yrs}))
            WHERE n <= {TOP_PARTNERS}""",
        f"""SELECT j AS ent, 'tgm_' || ch AS ind, y, '{sec.PARTNER}' || i AS bd, v AS val FROM (
              SELECT *, row_number() OVER (PARTITION BY y, j, ch ORDER BY v DESC) AS n FROM baci_chapter WHERE y IN ({yrs}))
            WHERE n <= {TOP_PARTNERS}""",
    ]
    return " UNION ALL ".join(obs(p) for p in parts)


def baci_indicators(source_id: str) -> list[dict]:
    out = []
    note = "CEPII BACI, HS 1992 edition; exports as reported by both sides, reconciled by CEPII."
    for s, st in sec.stages():
        n = st["name"]
        for pre, what, unit in (("sx", "exports", sec.TRADE_UNIT), ("sxq", "exports (tonnes)", "tonnes"),
                                ("sm", "imports", sec.TRADE_UNIT), ("smq", "imports (tonnes)", "tonnes")):
            out.append(indicator(f"{pre}_{st['id']}", f"{n}: {what}",
                                 f"Trade in {n.lower()} (HS {', '.join(map(str, st.get('hs', [])))}), {what}. "
                                 "Routes to each partner are kept where worth at least US$ 1 million.",
                                 unit, "trade", source_id, f"{pre}_{st['id']}", decimals=0, default_on=False, notes=note,
                                 breakdowns=["partner"] if pre in ("sx", "sxq") else None, bounds=(0, 1e13)))
    for cc, name in sec.chapters().items():
        for pre, what in (("tgx", "exports"), ("tgm", "imports")):
            out.append(indicator(f"{pre}_{cc}", f"{name} (HS {cc}): {what}", f"Goods trade in HS chapter {cc}, {name.lower()}, {what}.",
                                 sec.TRADE_UNIT, "trade", source_id, f"{pre}_{cc}", decimals=0, default_on=False, notes=note,
                                 breakdowns=["partner"], bounds=(0, 1e13)))
    return out


# ----------------------------------------------------------------------------- production
def production_targets(kind: str) -> dict[str, list[tuple[str, str]]]:
    """{source item or sheet (lower case) -> (stage id, type words)} for one production source."""
    out = {}
    for _, st in sec.stages():
        p = st.get("production") or {}
        if p.get(kind):
            item, _, words = str(p[kind]).partition("|")
            out[item.strip().lower()] = out.get(item.strip().lower(), []) + [(st["id"], words.strip().lower())]
    return out


def production_indicators(source_id: str, found: set[str], note: str) -> list[dict]:
    out = []
    for s, st in sec.stages():
        if st["id"] in found:
            out.append(indicator(f"sp_{st['id']}", f"{st['name']}: production", f"Production of {st['name'].lower()}, by country.",
                                 sec.stage_unit(st), "resources", source_id, f"sp_{st['id']}", decimals=0, default_on=False,
                                 notes=note, bounds=(0, 1e13)))
        if f"sr_{st['id']}" in found:
            out.append(indicator(f"sr_{st['id']}", f"{st['name']}: reserves", f"Reserves of {st['name'].lower()} (USGS).",
                                 sec.stage_unit(st), "resources", source_id, f"sr_{st['id']}", decimals=0, default_on=False,
                                 notes=note, bounds=(0, 1e15)))
    return out


def to_tonnes(unit: str) -> float:
    """USGS units ("thousand metric dry tons", "kilograms", "metric tons") as a multiplier to tonnes."""
    u = (unit or "").lower()
    if "kilogram" in u or re.fullmatch(r"\s*kg\s*", u):
        return 0.001
    return 1e6 if "million" in u else 1000.0 if "thousand" in u else 1.0


class USGSMinerals(Connector):
    source_id = "usgs_mcs"
    stage_version = 3  # 2: the sectors added in version 4; 3: one value per country, year and stage
    fetch_every_days = 120
    SEARCH = "https://www.sciencebase.gov/catalog/items?q=%22Mineral+Commodity+Summaries%22+world+data&format=json&max=10&fields=title,files"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"MCS(20\d\d)", f.name, re.I)
            if m:
                return m.group(1)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        r = self.client.get(self.SEARCH)
        if r.status_code != 200:
            raise ConnectorError(f"usgs_mcs: ScienceBase search answered HTTP {r.status_code}")
        for item in sorted(r.json().get("items", []), key=lambda i: i.get("title", ""), reverse=True):
            for f in item.get("files", []):
                if re.search(r"world.*\.csv$", f.get("name", ""), re.I):
                    self.get(f["url"], raw_dir / f["name"])
                    return f["url"]
        raise ConnectorError("usgs_mcs: no world data CSV found on ScienceBase")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".xlsx"))
        if not files:
            raise ConnectorError(f"usgs_mcs: no CSV in {raw_dir}")
        rows, found = Rows(), set()
        for f in files:
            table = xlsx_rows(f) if f.suffix.lower() == ".xlsx" else list(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
            usgs_rows(table, rows, found)
        if not len(rows):
            raise ConnectorError("usgs_mcs: no production rows matched the sectors; the columns may have changed")
        self.listed_indicators = production_indicators(self.source_id, found, "USGS Mineral Commodity Summaries (world data release).")
        return rows.stage(con, self.source_id, vintage)


def usgs_rows(table: list[list], rows: Rows, found: set[str]) -> None:
    """USGS world data: COMMODITY, COUNTRY, TYPE, UNIT_MEAS, PROD_<year> / PROD_EST_<year>, RESERVES_<year>."""
    targets = production_targets("usgs")
    h = next((i for i, r in enumerate(table[:10]) if any(key(c) == "commodity" for c in r)), None)
    if h is None:
        return
    head = [str(c or "") for c in table[h]]
    col = {key(c): i for i, c in enumerate(head)}
    c_com, c_cty, c_type, c_unit = col.get("commodity"), col.get("country"), col.get("type"), col.get("unitmeas")
    prod = [(i, int(m.group(1))) for i, c in enumerate(head) if (m := re.search(r"prod\w*?(\d{4})", c, re.I)) and "note" not in c.lower()]
    res = [i for i, c in enumerate(head) if re.search(r"reserve", c, re.I) and "note" not in c.lower()]
    seen: set[tuple] = set()  # a country can have several rows for one stage (iron ore as usable ore and as iron content): the first counts

    def add(ent: str, ind: str, y: int, v: float) -> None:
        if (ent, ind, y) not in seen:
            seen.add((ent, ind, y))
            rows.add("iso3", ent, ind, y, v)

    for r in table[h + 1:]:
        if c_com is None or c_cty is None or c_com >= len(r):
            continue
        com, typ = str(r[c_com] or "").lower(), str(r[c_type] or "").lower() if c_type is not None else ""
        hits = [st for name, opts in targets.items() if name in com for st, words in opts if not words or words in typ]
        if not hits:
            continue
        ent = _country(str(r[c_cty] or ""))
        if not ent:
            continue
        unit = str(r[c_unit] or "metric tons").lower().strip() if c_unit is not None else "metric tons"
        scale = to_tonnes(unit)
        for st in hits:
            mult = scale * (1000 if sec.stage_unit(sec.stage(st)[1]) == "kilograms" else 1)
            for i, y in prod:
                v = num(r[i]) if i < len(r) else None
                if v is not None:
                    add(ent, f"sp_{st}", y, v * mult)
                    found.add(st)
            for i in res[:1]:
                v = num(r[i]) if i < len(r) else None
                y = max((y for _, y in prod), default=None)
                if v is not None and y:
                    add(ent, f"sr_{st}", y, v * mult)
                    found.add(f"sr_{st}")


class WorldMiningData(Connector):
    source_id = "wmd"
    stage_version = 2  # 2: the sectors added in version 4
    fetch_every_days = 120
    keeps_files = True
    URL = "https://www.world-mining-data.info/wmd/downloads/XLS/6.4.%20Production_of_Mineral_Raw_Materials_of_individual_Countries_by_Minerals.xlsx"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(self.URL, raw_dir / f"wmd_production_by_mineral_{release}.xlsx")
        return self.URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"wmd: no .xlsx in {raw_dir}")
        rows, found = Rows(), set()
        targets = production_targets("wmd")
        for f in files:  # older editions first, so a newer one's figure for the same year wins
            for sheet in xlsx_sheet_names(f):
                hits = [st for name, opts in targets.items() if key(sheet).startswith(key(name)) for st, _ in opts]
                if hits:
                    wmd_sheet(xlsx_rows(f, sheet), hits, rows, found)
        if not len(rows):
            raise ConnectorError("wmd: no production read; the sheets may have changed")
        self.listed_indicators = production_indicators(self.source_id, found, "World Mining Data (Austrian Federal Ministry of Finance).")
        rows.rows = list({r[:5]: r for r in rows.rows}.values())  # one value per country, stage and year
        return rows.stage(con, self.source_id, vintage)


def wmd_sheet(table: list[list], stages: list[str], rows: Rows, found: set[str]) -> None:
    """One mineral's sheet: a header row with years, then a country per row. A unit cell
    ("metr. t", "kg") applies to the whole sheet."""
    h = next((i for i, r in enumerate(table[:20]) if sum(bool(re.fullmatch(r"(19|20)\d\d", str(c or "").strip().split(".")[0])) for c in r) >= 2), None)
    if h is None:
        return
    head = table[h]
    years = [(i, int(str(c).strip().split(".")[0])) for i, c in enumerate(head) if re.fullmatch(r"(19|20)\d\d", str(c or "").strip().split(".")[0])]
    text_all = " ".join(str(c or "") for r in table[:h + 2] for c in r).lower()
    scale = 0.001 if re.search(r"\bkg\b", text_all) else 1.0
    for r in table[h + 1:]:
        name = next((str(c).strip() for c in r[:3] if c and not str(c).strip().replace(".", "").isdigit()), "")
        if not name or name.lower().startswith(("total", "world", "africa", "asia", "europe", "america", "oceania", "source")):
            continue
        ent = _country(name)
        if not ent:
            continue
        for st in stages:
            mult = scale * (1000 if sec.stage_unit(sec.stage(st)[1]) == "kilograms" else 1)
            for i, y in years:
                v = num(r[i]) if i < len(r) else None
                if v is not None:
                    rows.add("iso3", ent, f"sp_{st}", y, v * mult)
                    found.add(st)


FAO_BULK = "https://bulks-faostat.fao.org/production/"
FAO_FILES = ("Production_Crops_Livestock_E_All_Data_(Normalized).zip", "Inputs_FertilizersNutrient_E_All_Data_(Normalized).zip",
             "Forestry_E_All_Data_(Normalized).zip", "Inputs_LandUse_E_All_Data_(Normalized).zip")

# Land use (Inputs_LandUse, element "Area", 1000 ha): FAOSTAT item (lower case) -> (indicator id, name).
FAO_LAND = {
    "land area": ("land_area_ha", "Land area"),
    "agricultural land": ("land_agri_ha", "Agricultural land"),
    "cropland": ("land_cropland_ha", "Cropland"),
    "arable land": ("land_arable_ha", "Arable land"),
    "permanent crops": ("land_permanent_crops_ha", "Permanent crops"),
    "permanent meadows and pastures": ("land_pasture_ha", "Permanent meadows and pastures"),
    "forest land": ("land_forest_ha", "Forest land"),
    "naturally regenerating forest": ("land_natural_forest_ha", "Naturally regenerating forest"),
    "planted forest": ("land_planted_forest_ha", "Planted forest"),
}
# Shares of land area worked out from them, for the map.
FAO_LAND_SHARES = {"land_forest_ha": "land_forest_pct", "land_agri_ha": "land_agri_pct", "land_cropland_ha": "land_cropland_pct",
                   "land_pasture_ha": "land_pasture_pct"}
# Live animals (element "Stocks"); dairy cows come from raw milk of cattle, element "Milk Animals".
FAO_STOCKS = {"cattle": "livestock_cattle_head", "sheep": "livestock_sheep_head", "goats": "livestock_goats_head",
              "swine / pigs": "livestock_pigs_head"}


# Units kept: weight for crops and livestock, volume for forestry (logs, sawn timber). Counts (eggs as "1000 no") are left out.
FAO_UNITS = {"t": 1.0, "tonnes": 1.0, "1000 t": 1000.0, "1000 tonnes": 1000.0, "m3": 1.0, "1000 m3": 1000.0}


class FAOSTAT(Connector):
    source_id = "faostat"
    # 3: production in tonnes only (eggs also come as counts); 4: forestry in cubic metres again (3 dropped it);
    # 5: land use, live animals, dairy cows, area harvested and nitrogen per hectare (version 4, PR 6)
    stage_version = 5
    fetch_version = 2  # 2: the land use file
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for n in FAO_FILES:
            self.get(FAO_BULK + n, raw_dir / n)
        return FAO_BULK

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        targets = {item: [st for st, _ in opts] for item, opts in production_targets("fao").items()}
        con.execute("CREATE TABLE fao_items (item VARCHAR, stage VARCHAR)")
        con.executemany("INSERT INTO fao_items VALUES (?, ?)", [(i, st) for i, sts in targets.items() for st in sts]
                        + [(i, f"land:{ind}") for i, (ind, _) in FAO_LAND.items()]
                        + [(i, f"stock:{ind}") for i, ind in FAO_STOCKS.items()]
                        + [("nutrient nitrogen n (total)", "fert:fert_n_per_ha")])
        tmp = Path(tempfile.mkdtemp(prefix="fao_"))
        try:
            csvs = sorted(raw_dir.glob("*.csv"))
            for z in sorted(raw_dir.glob("*.zip")):
                with zipfile.ZipFile(z) as zf:
                    for n in zf.namelist():
                        if n.lower().endswith(".csv") and "all_data" in n.lower() and "flag" not in n.lower():
                            t = tmp / n.rsplit("/", 1)[-1]
                            with zf.open(n) as src, open(t, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            csvs.append(t)
            if not csvs:
                raise ConnectorError(f"faostat: no bulk CSV in {raw_dir}")
            con.execute("CREATE TABLE fao (m49 VARCHAR, stage VARCHAR, element VARCHAR, y INTEGER, unit VARCHAR, v DOUBLE)")
            for f in csvs:
                cols = [d[0] for d in con.execute(f"DESCRIBE SELECT * FROM read_csv({sql_str(f.as_posix())}, header = true, all_varchar = true, encoding = 'latin-1')").fetchall()]
                m49 = next((c for c in cols if key(c) in ("areacodem49", "m49code")), None)
                if m49 is None or "Item" not in cols or "Element" not in cols:
                    continue
                con.execute(f"""INSERT INTO fao
                    SELECT replace("{m49}", '''', ''), fi.stage, lower(trim(r."Element")), TRY_CAST("Year" AS INTEGER),
                           lower("Unit"), TRY_CAST("Value" AS DOUBLE)
                    FROM read_csv({sql_str(f.as_posix())}, header = true, all_varchar = true, encoding = 'latin-1') r
                    JOIN fao_items fi ON lower(trim(r."Item")) = fi.item
                    WHERE lower(trim(r."Element")) IN ('production', 'area harvested', 'stocks', 'milk animals', 'area',
                                                       'use per area of cropland')""")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        rows, found = Rows(), set()
        land: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
        for m, st, element, y, unit, v in con.execute("SELECT * FROM fao WHERE v IS NOT NULL AND y IS NOT NULL").fetchall():
            ent = entity_for("m49", m)
            if not is_country(ent):
                continue
            kind, _, ind = st.partition(":")
            if ind:  # land use, animals, fertiliser
                if kind == "land" and element == "area" and unit in ("1000 ha", "ha"):
                    val = v * (1000.0 if unit == "1000 ha" else 1.0)
                    land[(ent, y)][ind] = val
                elif kind == "stock" and element == "stocks" and unit in ("an", "head", "1000 an", "1000 head"):
                    val = v * (1000.0 if unit.startswith("1000") else 1.0)
                elif kind == "fert" and element == "use per area of cropland":
                    val = v
                else:
                    continue
                rows.add("iso3", ent, ind, y, val)
                found.add(ind)
                continue
            if element == "milk animals":
                if st == "milk":
                    rows.add("iso3", ent, "livestock_dairy_cows", y, v * (1000.0 if unit.startswith("1000") else 1.0))
                    found.add("livestock_dairy_cows")
                continue
            if element == "area harvested":
                if unit == "ha":
                    rows.add("iso3", ent, f"sa_{st}", y, v)
                    found.add(f"sa_{st}")
                continue
            if element != "production" or unit not in FAO_UNITS:
                continue  # eggs also come as numbers of eggs ("1000 no")
            rows.add("iso3", ent, f"sp_{st}", y, v * FAO_UNITS[unit])
            found.add(st)
        for (ent, y), got in land.items():
            area = got.get("land_area_ha")
            for ind, share in FAO_LAND_SHARES.items():
                if area and got.get(ind) is not None:
                    rows.add("iso3", ent, share, y, got[ind] / area * 100)
                    found.add(share)
        if not len(rows):
            raise ConnectorError("faostat: no production rows for the sector items")
        self.listed_indicators = production_indicators(self.source_id, found, "FAOSTAT (FAO), production.") + \
            fao_land_indicators(self.source_id, found)
        return rows.stage(con, self.source_id, vintage)


def fao_land_indicators(source_id: str, found: set[str]) -> list[dict]:
    """Land use, animals, area harvested and fertiliser per hectare, as FAOSTAT gives them."""
    out = []
    note = "FAOSTAT (FAO): land use, crops and livestock."
    for ind, name in FAO_LAND.values():
        if ind in found:
            out.append(indicator(ind, f"{name} (FAOSTAT)", f"{name} in hectares, FAOSTAT land use (from 1961).", "ha", "land",
                                 source_id, ind, decimals=0, bounds=(0, 2e9), aggregation={"method": "sum"}, notes=note,
                                 default_on=ind in ("land_forest_ha", "land_agri_ha", "land_cropland_ha", "land_pasture_ha")))
    for base, ind in FAO_LAND_SHARES.items():
        if ind in found:
            name = next(n for i, n in FAO_LAND.values() if i == base)
            out.append(indicator(ind, f"{name}, share of land (FAOSTAT)", f"{name} as a share of land area (FAOSTAT).", "%",
                                 "land", source_id, ind, decimals=1, bounds=(0, 100), notes=note, default_on=True,
                                 aggregation={"method": "ratio", "numerator": base, "denominator": "land_area_ha",
                                              "multiplier": 100}))
    animals = {"livestock_cattle_head": "Cattle", "livestock_sheep_head": "Sheep", "livestock_goats_head": "Goats",
               "livestock_pigs_head": "Pigs", "livestock_dairy_cows": "Dairy cows (cows milked)"}
    for ind, name in animals.items():
        if ind in found:
            out.append(indicator(ind, f"{name} (FAOSTAT)", f"{name}: live animals counted in the year (FAOSTAT).", "head", "land",
                                 source_id, ind, decimals=0, bounds=(0, 2e9), aggregation={"method": "sum"}, notes=note,
                                 default_on=False))
    for _, st in sec.stages():
        if f"sa_{st['id']}" in found:
            out.append(indicator(f"sa_{st['id']}", f"{st['name']}: area harvested", f"Hectares of {st['name'].lower()} "
                                 "harvested in the year (FAOSTAT).", "ha", "land", source_id, f"sa_{st['id']}", decimals=0,
                                 bounds=(0, 5e8), aggregation={"method": "sum"}, notes=note, default_on=False))
    if "fert_n_per_ha" in found:
        out.append(indicator("fert_n_per_ha", "Nitrogen fertiliser per hectare of cropland (FAOSTAT)",
                             "Nitrogen (N) put on farmland, per hectare of cropland (FAOSTAT fertilisers by nutrient).",
                             "kg/ha", "land", source_id, "fert_n_per_ha", decimals=1, bounds=(0, 5000), notes=note,
                             default_on=False))
    return out


# ----------------------------------------------------------------------------- prices
PINK_PAGE = "https://www.worldbank.org/en/research/commodity-markets"


class PinkSheet(Connector):
    source_id = "wb_pinksheet"
    stage_version = 2  # 2: the sectors added in version 4
    fetch_every_days = 25

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        r = self.client.get(PINK_PAGE)
        links = re.findall(r'href="([^"]+CMO-Historical-Data-Monthly\.xlsx)"', r.text, re.I)
        if not links:
            raise ConnectorError("wb_pinksheet: no link to CMO-Historical-Data-Monthly.xlsx on the commodity markets page")
        url = links[0] if links[0].startswith("http") else "https://www.worldbank.org" + links[0]
        self.get(url, raw_dir / "CMO-Historical-Data-Monthly.xlsx")
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.xlsx"))
        if not files:
            raise ConnectorError(f"wb_pinksheet: no .xlsx in {raw_dir}")
        names = xlsx_sheet_names(files[-1])
        sheet = next((n for n in names if key(n) == "monthlyprices"), names[0])
        points, units = pink_prices(xlsx_rows(files[-1], sheet))
        if not points:
            raise ConnectorError("wb_pinksheet: no prices read; the sheet layout may have changed")
        con.execute("CREATE TABLE pink (pid VARCHAR, d DATE, v DOUBLE)")
        con.executemany("INSERT INTO pink VALUES (?, ?, ?)", points)
        self.listed_indicators = [indicator(f"price_{pid}", f"{label.strip()} price", f"World Bank commodity price: {label.strip()}, monthly.",
                                            units.get(pid, "US$"), "prices", self.source_id, f"price_{pid}", decimals=2,
                                            frequency="M", default_on=False, bounds=(0, 1e7),
                                            notes="World Bank Commodity Price Data (The Pink Sheet), nominal US$.")
                                  for pid, label in sec.prices().items() if pid in units]
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, 'world' AS source_code, "
                "'price_' || pid AS indicator_id, d AS period_start, 'M' AS freq, '' AS breakdown, 'central' AS variant, "
                "v AS value, 'E' AS status FROM pink")


def pink_prices(table: list[list]) -> tuple[list[tuple], dict[str, str]]:
    """Monthly rows ("1960M01") under a row of commodity names and a row of units."""
    from datetime import date
    first = next((i for i, r in enumerate(table) if r and re.fullmatch(r"\d{4}M\d{2}", str(r[0] or "").strip())), None)
    if first is None:
        return [], {}
    head = next((table[i] for i in range(first - 1, -1, -1) if sum(bool(c) for c in table[i]) > 5 and not str(table[i][1] or "").startswith("(")), None)
    unit_row = next((table[i] for i in range(first - 1, -1, -1) if any(str(c or "").startswith("(") for c in table[i])), [])
    if head is None:
        return [], {}
    cols = {}
    for pid, label in sec.prices().items():
        want = key(label)
        i = next((j for j, c in enumerate(head) if key(str(c or "").replace("*", "")) == want), None)
        if i is None:
            i = next((j for j, c in enumerate(head) if key(str(c or "")).startswith(want)), None)
        if i is not None:
            cols[pid] = i
    units = {pid: ("US$ " + str(unit_row[i]).strip("() ").replace("$/", "per ").replace("$", "").strip()) if i < len(unit_row) and unit_row[i] else "US$"
             for pid, i in cols.items()}
    points = []
    for r in table[first:]:
        m = re.fullmatch(r"(\d{4})M(\d{2})", str(r[0] or "").strip())
        if not m:
            continue
        d = date(int(m.group(1)), int(m.group(2)), 1)
        for pid, i in cols.items():
            v = num(r[i]) if i < len(r) else None
            if v is not None:
                points.append((pid, d, v))
    return points, units


# ----------------------------------------------------------------------------- electric cars
# The IEA moved the explorer's route from /evs to /electric-vehicles in October 2026; the old one is tried second.
IEA_EV_URLS = ["https://api.iea.org/electric-vehicles?parameter={}&mode=Cars&category=Historical&csv=true",
               "https://api.iea.org/evs?parameter={}&mode=Cars&category=Historical&csv=true"]
IEA_EV_URL = IEA_EV_URLS[0]
IEA_EV_PARAMS = ("EV sales share", "EV stock share", "EV sales", "EV stock")


class IEAEV(Connector):
    source_id = "iea_ev"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"(20\d\d)", f.name)
            if m:
                return m.group(1)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for p in IEA_EV_PARAMS:
            dest = raw_dir / f"iea_ev_{p.replace(' ', '_').lower()}.csv"
            for i, url in enumerate(IEA_EV_URLS):
                try:
                    self.get(url.format(p.replace(" ", "%20")), dest)
                    break
                except ConnectorError:
                    if i == len(IEA_EV_URLS) - 1:
                        raise
        return IEA_EV_URL.format("...")

    PARAMS = {  # (parameter, powertrain) -> (indicator, name, unit)
        ("ev sales share", "ev"): ("ev_sales_share", "Electric share of new car sales", "%"),
        ("ev stock share", "ev"): ("ev_stock_share", "Electric share of cars on the road", "%"),
        ("ev sales", "bev"): ("ev_sales_bev", "Battery-electric car sales", "cars"),
        ("ev sales", "phev"): ("ev_sales_phev", "Plug-in hybrid car sales", "cars"),
        ("ev stock", "bev"): ("ev_stock_bev", "Battery-electric cars on the road", "cars"),
        ("ev stock", "phev"): ("ev_stock_phev", "Plug-in hybrid cars on the road", "cars"),
    }

    @staticmethod
    def _records(f: Path):
        """Rows as dicts: the Data Explorer CSV, or the long table in the yearly Excel file
        ("EV data by country 2026.xlsx", sheet GEVO_EV_2026: region_country, category,
        parameter, mode, powertrain, year, unit, value). Other files yield nothing."""
        if f.suffix.lower() == ".csv":
            yield from csv.DictReader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace")))
            return
        sheets = [n for n in xlsx_sheet_names(f) if n.upper().startswith("GEVO_EV")]
        for sheet in sheets[:1]:
            data = xlsx_rows(f, sheet)
            head = next((n for n, r in enumerate(data[:10]) if r and "parameter" in [str(c).strip().lower() for c in r if c]), None)
            if head is None:
                continue
            cols = ["region" if str(c).strip().lower() == "region_country" else (str(c).strip() if c is not None else "")
                    for c in data[head]]
            for r in data[head + 1:]:
                yield dict(zip(cols, r))

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv")) + sorted(f for f in raw_dir.iterdir() if f.suffix.lower() in (".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"iea_ev: no CSV or Excel file in {raw_dir}")
        rows, found = Rows(), set()
        for f in files:
            for r in self._records(f):
                k = {key(a): ("" if b is None else str(b)).strip() for a, b in r.items() if a}
                if k.get("mode", "cars").lower() != "cars" or k.get("category", "historical").lower() != "historical":
                    continue
                hit = self.PARAMS.get((k.get("parameter", "").lower(), k.get("powertrain", "").lower()))
                region = k.get("region", "")
                ent = "world" if region.lower() == "world" else "eu" if region.lower() in ("eu27", "eu 27", "european union") else _country(region)
                y, v = num(k.get("year")), num(k.get("value"))
                if hit and ent and y and v is not None:
                    rows.add("iso3", ent, hit[0], int(y), v)
                    found.add(hit[0])
        if not len(rows):
            raise ConnectorError("iea_ev: no electric car rows read")
        self.listed_indicators = [indicator(i, n, f"{n} (IEA Global EV Data).", u, "transport", self.source_id, i,
                                            decimals=1 if u == "%" else 0, default_on=i == "ev_sales_share",
                                            bounds=(0, 100) if u == "%" else (0, 1e9))
                                  for i, n, u in self.PARAMS.values() if i in found]
        return rows.stage(con, self.source_id, vintage)
