"""Land, cities and trees (version 4, PR 6). Each is switchable in Settings > Land.
FAOSTAT's land use, live animals and area harvested come with the faostat source (sectors.py).

hyde_land
    HYDE 3.3 (Utrecht University / PBL), cropland and grazing land by country back to 1700,
    as Our World in Data publishes it (charts cropland-area and grazing-land), or HYDE's own
    country tables (*_c.txt, km²) saved by hand. Figures before 1961 are modelled from
    population and old maps; the source is graded exploratory and the Land page draws it
    dashed.

ghsl_ucdb
    The GHSL Urban Centre Database (European Commission JRC), R2024A (people and built-up area
    for about 11,000 urban centres, 1975 to 2025 and a 2030 projection) or the older R2019A
    (1975 to 2015). Stored as figures for the matching GeoNames city (city_series) and as one
    outline per centre (geo_features layer urban_centres, props with every year).

gfw_treecover
    Global Forest Watch country statistics (Hansen/UMD tree cover): tree cover in 2000 and
    2010 and the tree cover lost each year since 2001, at 30% canopy.

council_trees
    Street and park trees that councils list one by one: Auckland first (Auckland Council's
    open data, read a page of 2,000 at a time, a second apart), or lists saved by hand in
    var/manual/council_trees (CSV or GeoJSON; the file name starts with the council).
    Stored as points (geo_features layer street_trees) with species and planting year.

nz_lcdb
    New Zealand's Land Cover Database (Manaaki Whenua, LRIS portal; saved by hand because
    the portal needs a free login): the area in each class at each survey year, nationally
    and by region (when a regional council boundary file is saved beside it), the area that
    changed from each class to each other between surveys, and a map of the changes.

nz_forestry
    New Zealand forestry and farm-to-forest tables saved by hand (MPI National Exotic Forest
    Description, new planting, Emissions Trading Scheme forest registrations, whole farms sold
    for forestry): any table with a year column and figures, matched by its headings.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
import sqlite3
import tempfile
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
from worldmodel_contract.land import LCDB_CLASSES, nz_region

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import _values_table
from worldmodel_data.connectors.tabular import (
    Rows,
    entity_for,
    indicator,
    is_country,
    key,
    num,
    xlsx_rows,
)
from worldmodel_data.connectors.transport import iso3_of, read_table, stage_geo

log = logging.getLogger(__name__)
THIS_YEAR = date.today().year


# ----------------------------------------------------------------------------- projections
def nztm_to_lonlat(e: float, n: float) -> tuple[float, float]:
    """NZTM2000 (EPSG:2193) easting and northing to longitude and latitude (GRS80, Snyder's inverse)."""
    a, f = 6378137.0, 1 / 298.257222101
    k0, lon0, fe, fn = 0.9996, math.radians(173.0), 1_600_000.0, 10_000_000.0
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    m = (n - fn) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(p1) ** 2
    t1 = math.tan(p1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    d = (e - fe) / (n1 * k0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                           + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(p1)
    return math.degrees(lon), math.degrees(lat)


def mollweide_to_lonlat(x: float, y: float, r: float = 6378137.0) -> tuple[float, float]:
    """World Mollweide (ESRI:54009, sphere) to longitude and latitude."""
    s2 = math.sqrt(2)
    th = math.asin(max(-1.0, min(1.0, y / (r * s2))))
    lat = math.asin(max(-1.0, min(1.0, (2 * th + math.sin(2 * th)) / math.pi)))
    c = math.cos(th)
    lon = math.pi * x / (2 * r * s2 * c) if abs(c) > 1e-12 else 0.0
    return math.degrees(lon), math.degrees(lat)


def reproject(geom, fn):
    """A shapely geometry with each point passed through fn(x, y) -> (lon, lat)."""
    import numpy as np
    import shapely

    return shapely.transform(geom, lambda xy: np.array([fn(x, y) for x, y in xy], dtype=float).reshape(-1, 2))


def _proj_of(srs_text: str, srs_id: int | None):
    t = (srs_text or "").lower()
    if srs_id == 2193 or "nztm" in t or "new zealand transverse" in t:
        return nztm_to_lonlat
    if srs_id == 54009 or "mollweide" in t:
        return mollweide_to_lonlat
    return None


# ----------------------------------------------------------------------------- GeoPackage
def gpkg_geometry(blob):
    """A shapely geometry from a GeoPackage geometry blob (GP header, envelope, then WKB)."""
    from shapely import wkb

    if not blob or bytes(blob[:2]) != b"GP":
        return None
    flags = blob[3]
    if flags & 0b10000:  # empty
        return None
    env = (flags >> 1) & 0b111
    size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    return wkb.loads(bytes(blob[8 + size:]))


def gpkg_layers(path: Path) -> dict[str, dict]:
    """Each feature table in a GeoPackage: its columns, geometry column and projection."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        geo = {r[0]: (r[1], r[2]) for r in con.execute("SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns")}
        srs = {r[0]: r[1] or "" for r in con.execute("SELECT srs_id, definition FROM gpkg_spatial_ref_sys")}
        tables = [r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")]
        out = {}
        for t in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            gcol, sid = geo.get(t, (None, None))
            out[t] = {"columns": cols, "geom": gcol, "proj": _proj_of(srs.get(sid, ""), sid) if gcol else None, "srs_id": sid}
        return out
    finally:
        con.close()


def gpkg_rows(path: Path, table: str, columns: list[str]):
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        sel = ", ".join(f'"{c}"' for c in columns)
        yield from con.execute(f'SELECT {sel} FROM "{table}"')
    finally:
        con.close()


def _unzip(path: Path, suffixes: tuple[str, ...], into: Path) -> list[Path]:
    out = []
    with zipfile.ZipFile(path) as zf:
        for n in zf.namelist():
            if n.lower().endswith(suffixes) and not n.startswith("__MACOSX"):
                t = into / n.replace("/", "_")
                with zf.open(n) as src, open(t, "wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
                out.append(t)
    return out


# ----------------------------------------------------------------------------- HYDE
OWID = "https://ourworldindata.org/grapher/"
OWID_QUERY = "?v=1&csvType=full&useColumnShortNames=false"
HYDE_CHARTS = {"cropland-area": "hyde_cropland_ha", "grazing-land": "hyde_grazing_ha"}
HYDE_FILES = {"cropland": "hyde_cropland_ha", "grazing": "hyde_grazing_ha", "pasture": "hyde_pasture_ha",
              "rangeland": "hyde_rangeland_ha", "uopp": "hyde_builtup_ha"}
HYDE_FROM = 1700


def hyde_txt(text: str) -> list[tuple[str, int, float]]:
    """(m49 code, year, km²) from a HYDE country table: a header of years (1700AD, 1700, 10000BC)
    and a row per country starting with its UN number."""
    lines = [ln.split() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    years = []
    for tok in lines[0][1:]:
        m = re.fullmatch(r"(\d+)\s*(AD|BC)?", tok, re.IGNORECASE)
        years.append(None if not m else -int(m[1]) if (m[2] or "").upper() == "BC" else int(m[1]))
    out = []
    for parts in lines[1:]:
        code = parts[0]
        if not re.fullmatch(r"\d+", code):
            continue
        for y, v in zip(years, parts[1:]):
            val = num(v)
            if y is not None and val is not None:
                out.append((code, y, val))
    return out


class HYDELand(Connector):
    source_id = "hyde_land"
    switch = "land_history_fetch"
    fetch_every_days = 365
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for i, slug in enumerate(HYDE_CHARTS):
            if i:
                time.sleep(self.pause_seconds)
            try:
                self.get(f"{OWID}{slug}.csv{OWID_QUERY}", raw_dir / f"{slug}.csv")
                got.append(slug)
            except ConnectorError as exc:
                log.warning("hyde_land: %s skipped (%s)", slug, exc)
        if not got:
            raise ConnectorError("hyde_land: neither HYDE chart could be downloaded from Our World in Data")
        return " ".join(OWID + s for s in got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.iterdir()):
            name = p.stem.lower()
            if p.suffix.lower() == ".csv" and name in HYDE_CHARTS:
                ind = HYDE_CHARTS[name]
                with p.open(encoding="utf-8-sig", newline="") as f:
                    rd = csv.reader(f)
                    head = [h.lower() for h in next(rd)]
                    if "year" not in head:
                        continue
                    ci, yi = head.index("code") if "code" in head else None, head.index("year")
                    vi = next(i for i, h in enumerate(head) if h not in ("entity", "code", "year"))
                    for r in rd:
                        y, v = num(r[yi]), num(r[vi]) if vi < len(r) else None
                        ent = entity_for("iso3", r[ci]) if ci is not None else None
                        if y is None or v is None or not is_country(ent) or y < HYDE_FROM:
                            continue
                        rows.add("iso3", ent, ind, int(y), v)
            elif p.suffix.lower() == ".txt":
                ind = next((i for k, i in HYDE_FILES.items() if name.startswith(k)), None)
                if not ind or not name.endswith("_c"):
                    continue
                for code, y, km2 in hyde_txt(p.read_text(encoding="latin-1", errors="replace")):
                    ent = entity_for("m49", code)
                    if is_country(ent) and y >= HYDE_FROM:
                        rows.add("iso3", ent, ind, y, km2 * 100)
        if not len(rows):
            raise ConnectorError(f"hyde_land: no HYDE figures in {raw_dir}")
        # Grazing from pasture and rangeland when only those were saved
        have = {r[2] for r in rows.rows}
        if "hyde_grazing_ha" not in have and {"hyde_pasture_ha", "hyde_rangeland_ha"} & have:
            sums: dict[tuple, float] = defaultdict(float)
            for r in rows.rows:
                if r[2] in ("hyde_pasture_ha", "hyde_rangeland_ha"):
                    sums[(r[1], r[3].year)] += r[5]
            for (ent, y), v in sums.items():
                rows.add("iso3", ent, "hyde_grazing_ha", y, v)
        names = {"hyde_cropland_ha": ("Cropland, long run (HYDE)", "Land used for crops"),
                 "hyde_grazing_ha": ("Grazing land, long run (HYDE)", "Pasture and rangeland grazed by livestock"),
                 "hyde_pasture_ha": ("Pasture, long run (HYDE)", "Managed pasture"),
                 "hyde_rangeland_ha": ("Rangeland, long run (HYDE)", "Natural grassland grazed by livestock"),
                 "hyde_builtup_ha": ("Built-up land, long run (HYDE)", "Land under towns and cities")}
        used = {r[2] for r in rows.rows}
        self.listed_indicators = [
            indicator(i, n, f"{d}, in hectares, from {HYDE_FROM} (HYDE 3.3). Before FAOSTAT starts in 1961 these are "
                      "modelled from population and historical maps, so treat them as rough.", "ha", "land", self.source_id,
                      i, decimals=0, bounds=(0, 2e9), aggregation={"method": "sum"}, default_on=False,
                      notes="HYDE 3.3 (Klein Goldewijk et al.), via Our World in Data.")
            for i, (n, d) in names.items() if i in used]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- GHSL urban centres
GHSL_URLS = [
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/V1-1/GHS_UCDB_GLOBE_R2024A_V1_1.zip",
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_STAT_UCDB2015MT_GLOBE_R2019A/V1-2/GHS_STAT_UCDB2015MT_GLOBE_R2019A.zip",
]
POP_COL = re.compile(r"(?:^|_)POP(?:_TOT)?_(\d{4})$|^P(\d{2})$", re.IGNORECASE)
BUILT_COL = re.compile(r"(?:^|_)BU[SA]?(?:_TOT)?_(\d{4})$|^B(\d{2})$", re.IGNORECASE)


def _year2(s: str) -> int:
    y = int(s)
    return y if y > 100 else (1900 + y if y >= 50 else 2000 + y)


def ghsl_centres(path: Path) -> list[dict]:
    """Urban centres from a GHSL UCDB GeoPackage: id, name, country, lon/lat, pop {year: people},
    built {year: km²}, area km², and the outline (shapely, lon/lat). Tables are joined on the
    centre id; columns are found by their name patterns, which differ between releases."""
    from shapely.geometry import shape  # noqa: F401 - shapely is needed below

    layers = gpkg_layers(path)
    centres: dict[str, dict] = {}
    for table, info in layers.items():
        cols = info["columns"]
        idc = next((c for c in cols if re.match(r"^ID_UC", c, re.IGNORECASE)), None)
        if not idc:
            continue
        name_c = next((c for c in cols if re.search(r"UCN_MAI|UC_NM_MN", c, re.IGNORECASE)), None)
        iso_c = next((c for c in cols if re.search(r"CNT_ISO|CTR_MN_ISO", c, re.IGNORECASE)), None)
        cname_c = next((c for c in cols if re.search(r"CNT_GAD|CTR_MN_NM|CNT_NAM", c, re.IGNORECASE)), None)
        lat_c = next((c for c in cols if re.search(r"GCPNT_LAT", c, re.IGNORECASE)), None)
        lon_c = next((c for c in cols if re.search(r"GCPNT_LON", c, re.IGNORECASE)), None)
        area_c = next((c for c in cols if re.fullmatch(r"(?:GC_UCA_KM2_\d{4}|AREA|UC_AREA_KM2)", c, re.IGNORECASE)), None)
        pops = {c: _year2(m[1] or m[2]) for c in cols if (m := POP_COL.search(c))}
        built = {c: _year2(m[1] or m[2]) for c in cols if (m := BUILT_COL.search(c))}
        want = [idc] + [c for c in (name_c, iso_c, cname_c, lat_c, lon_c, area_c, info["geom"]) if c] + list(pops) + list(built)
        for r in gpkg_rows(path, table, want):
            row = dict(zip(want, r))
            cid = str(row[idc]).split(".")[0]
            c = centres.setdefault(cid, {"id": cid, "pop": {}, "built": {}})
            if name_c and row.get(name_c):
                c["name"] = str(row[name_c])
            if iso_c and row.get(iso_c):
                c["iso"] = str(row[iso_c]).split(";")[0].strip()
            if cname_c and row.get(cname_c):
                c.setdefault("country_name", str(row[cname_c]).split(";")[0].strip())
            if lat_c and num(row.get(lat_c)) is not None:
                c["lat"], c["lon"] = num(row[lat_c]), num(row[lon_c])
            if area_c and num(row.get(area_c)):
                c["area"] = num(row[area_c])
            for col, y in pops.items():
                if num(row.get(col)) is not None:
                    c["pop"][y] = num(row[col])
            for col, y in built.items():
                if num(row.get(col)) is not None:
                    c["built"][y] = num(row[col])
            if info["geom"] and row.get(info["geom"]) and "outline" not in c:
                g = gpkg_geometry(row[info["geom"]])
                if g is not None and info["proj"]:
                    g = reproject(g, info["proj"])
                c["outline"] = g
    out = []
    vals = [v for c in centres.values() for v in c["built"].values() if v]
    in_m2 = bool(vals) and sorted(vals)[len(vals) // 2] > 1e5  # built-up given in m² (median far above any km² figure)
    for c in centres.values():
        if not c["pop"]:
            continue
        if in_m2:
            c["built"] = {y: v / 1e6 for y, v in c["built"].items()}
        g = c.get("outline")
        if g is not None and (c.get("lat") is None):
            pt = g.representative_point()
            c["lon"], c["lat"] = pt.x, pt.y
        if g is not None and not c.get("area"):
            c["area"] = None
        out.append(c)
    return out


def ghsl_csv(path: Path) -> list[dict]:
    """Urban centres from the R2019A table (GHS_STAT_UCDB2015MT_GLOBE_R2019A*.csv), without outlines."""
    text = path.read_text(encoding="latin-1", errors="replace")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        cid = r.get("ID_HDC_G0") or r.get("ID_UC_G0")
        if not cid:
            continue
        pops = {_year2(m[1] or m[2]): num(v) for k, v in r.items() if k and (m := POP_COL.search(k)) and num(v) is not None}
        built = {_year2(m[1] or m[2]): num(v) for k, v in r.items() if k and (m := BUILT_COL.search(k)) and num(v) is not None}
        if not pops:
            continue
        out.append({"id": str(cid).split(".")[0], "name": r.get("UC_NM_MN"), "iso": r.get("CTR_MN_ISO"),
                    "lat": num(r.get("GCPNT_LAT")), "lon": num(r.get("GCPNT_LON")), "area": num(r.get("AREA")),
                    "pop": pops, "built": built})
    return out


class GHSLUrbanCentres(Connector):
    source_id = "ghsl_ucdb"
    switch = "land_cities_fetch"
    fetch_every_days = 365

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        n = " ".join(p.name for p in files)
        m = re.search(r"R(20\d\d)A", n)
        return m[1] if m else None

    def download(self, raw_dir: Path, release: str) -> str:
        last = None
        for url in GHSL_URLS:
            try:
                self.get(url, raw_dir / url.rsplit("/", 1)[-1])
                return url
            except ConnectorError as exc:
                last = exc
                log.warning("ghsl_ucdb: %s not fetched (%s)", url, exc)
        raise ConnectorError(f"ghsl_ucdb: the Urban Centre Database could not be downloaded ({last})")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        tmp = Path(tempfile.mkdtemp(prefix="ghsl_"))
        try:
            files = [p for p in raw_dir.iterdir() if p.suffix.lower() in (".gpkg", ".csv")]
            for z in raw_dir.glob("*.zip"):
                files += _unzip(z, (".gpkg", ".csv"), tmp)
            centres = []
            for p in sorted(files, key=lambda p: p.suffix.lower() != ".gpkg"):
                if p.suffix.lower() == ".gpkg":
                    centres = ghsl_centres(p)
                elif not centres and "ucdb" in p.name.lower():
                    centres = ghsl_csv(p)
                if centres:
                    break
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        if not centres:
            raise ConnectorError(f"ghsl_ucdb: no urban centres read from {raw_dir}")
        city, geo = [], []
        for c in centres:
            ent = entity_for("iso3", (c.get("iso") or "").upper()) or iso3_of(c.get("country_name"))
            if not ent:
                continue
            name = c.get("name") or f"Urban centre {c['id']}"
            years = sorted(c["pop"])
            for y in years:
                st = "P" if y > THIS_YEAR else "E"
                city.append((name, ent, c.get("lat"), c.get("lon"), "ghsl_population", y, st, c["pop"][y]))
                b = c["built"].get(y)
                if b:
                    city.append((name, ent, c.get("lat"), c.get("lon"), "ghsl_built_km2", y, st, b))
                    city.append((name, ent, c.get("lat"), c.get("lon"), "ghsl_density", y, st, c["pop"][y] / b))
            g = c.get("outline")
            if g is not None:
                g = g.simplify(0.002, preserve_topology=True)
                now = max((y for y in years if y <= THIS_YEAR), default=years[-1])
                first = years[0]
                p_now, p_first = c["pop"][now], c["pop"][first]
                props = {"country": ent, "pop": {str(y): round(v) for y, v in c["pop"].items()},
                         "built": {str(y): round(v, 2) for y, v in c["built"].items()}, "area": c.get("area"),
                         "now": now, "first": first, "people": round(p_now),
                         "growth": round((p_now / p_first - 1) * 100, 1) if p_first else None,
                         "lat": c.get("lat"), "lon": c.get("lon")}
                rank = 1 if p_now >= 1e6 else 2 if p_now >= 3e5 else 3
                geo.append(("urban_centres", c["id"], name, rank, props, [ent], json.loads(json.dumps(g.__geo_interface__))))
        self.city_values_query = _values_table(con, city)
        if geo:
            self.history_queries = {"geo_features": stage_geo(con, geo)}
        log.info("ghsl_ucdb: %s urban centres, %s with outlines", len(centres), len(geo))
        return Rows().stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- Global Forest Watch
GFW_URLS = [
    "https://gfw2-data.s3.amazonaws.com/country-pages/country_stats/download/global_country_stats.xlsx",
    "https://gfw2-data.s3.amazonaws.com/country-pages/country_stats/download/global_country_stats.zip",
]
GFW_THRESHOLD = 30


def gfw_rows(table: list[list]) -> list[tuple[str, str, int, float]]:
    """(entity, indicator, year, value) from GFW's country tree cover loss sheet at 30% canopy."""
    out = []
    for i, row in enumerate(table[:10]):
        heads = [str(c or "").strip().lower() for c in row]
        if "country" not in heads or "threshold" not in heads:
            continue
        ci, ti = heads.index("country"), heads.index("threshold")
        for r in table[i + 1:]:
            if len(r) <= max(ci, ti) or num(r[ti]) != GFW_THRESHOLD:
                continue
            ent = iso3_of(r[ci])
            if not is_country(ent):
                continue
            cells = dict(zip(heads, r))
            area = num(cells.get("area_ha"))
            for y, col in ((2000, "extent_2000_ha"), (2010, "extent_2010_ha")):
                v = num(cells.get(col))
                if v is not None:
                    out.append((ent, "gfw_tree_cover_ha", y, v))
                    if area:
                        out.append((ent, "gfw_tree_cover_pct", y, v / area * 100))
            for h, v in cells.items():
                m = re.fullmatch(r"tc_loss_ha_(\d{4})", h)
                if m and num(v) is not None:
                    out.append((ent, "gfw_tree_cover_loss_ha", int(m[1]), num(v)))
        return out
    return out


class GFWTreeCover(Connector):
    source_id = "gfw_treecover"
    switch = "land_trees_fetch"
    fetch_every_days = 180

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        last = None
        for url in GFW_URLS:
            try:
                self.get(url, raw_dir / url.rsplit("/", 1)[-1])
                return url
            except ConnectorError as exc:
                last = exc
        raise ConnectorError(f"gfw_treecover: the country statistics file could not be downloaded ({last}); "
                             "save it by hand from the Global Forest Watch dashboard (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        from worldmodel_data.connectors.tabular import xlsx_sheet_names

        tmp = Path(tempfile.mkdtemp(prefix="gfw_"))
        found = []
        try:
            files = [p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv")]
            for z in raw_dir.glob("*.zip"):
                files += _unzip(z, (".xlsx", ".csv"), tmp)
            for p in files:
                if p.suffix.lower() == ".xlsx":
                    sheets = xlsx_sheet_names(p)
                    pick = [s for s in sheets if "tree cover loss" in s.lower() and "country" in s.lower()] or sheets[:1]
                    for s in pick:
                        found += gfw_rows(xlsx_rows(p, s))
                else:
                    found += gfw_rows(read_table(p))
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        if not found:
            raise ConnectorError(f"gfw_treecover: no country tree cover rows at {GFW_THRESHOLD}% canopy in {raw_dir}")
        rows = Rows()
        for ent, ind, y, v in found:
            rows.add("iso3", ent, ind, y, v)
        note = "Global Forest Watch (Hansen/UMD/Google/USGS/NASA), trees taller than 5 m covering 30% or more of a 30 m cell."
        self.listed_indicators = [
            indicator("gfw_tree_cover_ha", "Tree cover (Global Forest Watch)", "Area with tree canopy of 30% or more, in 2000 "
                      "and 2010.", "ha", "land", self.source_id, "gfw_tree_cover_ha", decimals=0, bounds=(0, 2e9),
                      aggregation={"method": "sum"}, notes=note),
            indicator("gfw_tree_cover_pct", "Tree cover, share of land (Global Forest Watch)", "Tree cover (30% canopy) as a "
                      "share of the country's land, 2000 and 2010.", "%", "land", self.source_id, "gfw_tree_cover_pct",
                      decimals=1, bounds=(0, 100), notes=note),
            indicator("gfw_tree_cover_loss_ha", "Tree cover lost (Global Forest Watch)", "Tree cover removed or killed in the "
                      "year: logging, fire, clearing for farms, storms. Plantations harvested and replanted count as loss "
                      "too, and regrowth is not netted off.", "ha", "land", self.source_id, "gfw_tree_cover_loss_ha",
                      decimals=0, bounds=(0, 1e8), aggregation={"method": "sum"}, notes=note, default_on=True),
        ]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- council street trees
AUCKLAND_SEARCH = ("https://data-aucklandcouncil.opendata.arcgis.com/api/search/v1/collections/dataset/items"
                   "?q=trees&limit=30")
PAGE = 2000
MAX_PAGES = 200
COUNCIL_ENTITY = {"auckland": "NZL", "wellington": "NZL", "christchurch": "NZL"}


def tree_records(path: Path) -> list[dict]:
    """Trees from a council list: CSV with columns, or GeoJSON (ArcGIS pages). Each has lon, lat,
    species, common name, planted year and height where given. NZTM coordinates are converted."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    items = []
    if path.suffix.lower() in (".geojson", ".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        for f in data.get("features") or []:
            g = f.get("geometry") or {}
            props = {key(k): v for k, v in (f.get("properties") or f.get("attributes") or {}).items()}
            xy = g.get("coordinates") if g.get("type") == "Point" else (g.get("x"), g.get("y")) if "x" in g else None
            if xy and xy[0] is not None:
                props["_x"], props["_y"] = xy[0], xy[1]
            items.append(props)
    else:
        rdr = csv.reader(io.StringIO(text))
        head = [key(h) for h in next(rdr, [])]
        items = [dict(zip(head, r)) for r in rdr]
    out = []
    for p in items:
        x = num(p.get("_x") if p.get("_x") is not None else _pick(p, "longitude", "lon", "long", "x", "easting", "nztmx"))
        y = num(p.get("_y") if p.get("_y") is not None else _pick(p, "latitude", "lat", "y", "northing", "nztmy"))
        if x is None or y is None:
            continue
        if abs(x) > 1000:  # NZTM metres
            x, y = nztm_to_lonlat(x, y)
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            continue
        planted = _pick(p, "yearplanted", "plantedyear", "dateplanted", "planteddate", "dateofplanting", "plantingdate", "planted", "plantdate", "installdate")
        py = None
        if planted not in (None, ""):
            n = num(planted)
            if n is not None and n > 1e11:  # ArcGIS dates in milliseconds
                py = datetime.fromtimestamp(n / 1000, timezone.utc).year
            else:
                m = re.search(r"(1[89]\d\d|20\d\d)", str(planted))
                py = int(m[1]) if m else None
        species = _pick(p, "botanicalname", "species", "scientificname", "speciesname", "botanical", "latinname", "taxon", "genusspecies")
        common = _pick(p, "commonname", "common", "speciescommonname")
        out.append({"lon": round(x, 6), "lat": round(y, 6), "species": str(species).strip() if species else None,
                    "common": str(common).strip() if common else None, "planted": py,
                    "height": num(_pick(p, "heightm", "height", "treeheight", "heightmetres")),
                    "id": _pick(p, "objectid", "assetid", "treeid", "id", "fid")})
    return out


def _pick(row: dict, *names: str):
    for n in names:
        if row.get(n) not in (None, ""):
            return row[n]
    return None


class CouncilTrees(Connector):
    source_id = "council_trees"
    switch = "land_trees_fetch"
    keeps_files = True
    fetch_every_days = 180
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        """Auckland Council's open data: the tree dataset its search finds, read a page at a time."""
        r = self.client.get(AUCKLAND_SEARCH)
        if r.status_code != 200:
            raise ConnectorError(f"council_trees: Auckland open data search answered {r.status_code}")
        items = (r.json() or {}).get("features") or []
        best = None
        for it in items:
            props = it.get("properties") or {}
            title, url = str(props.get("title") or ""), str(props.get("url") or "")
            if "tree" in title.lower() and "featureserver" in url.lower() and "notable" not in title.lower():
                best = (title, url if re.search(r"/\d+$", url) else url.rstrip("/") + "/0")
                break
        if not best:
            raise ConnectorError("council_trees: Auckland's open data lists no tree dataset with a map service; "
                                 "save a tree list by hand (see Data status)")
        title, url = best
        n = 0
        for page in range(MAX_PAGES):
            if page:
                time.sleep(self.pause_seconds)
            resp = self.client.get(f"{url}/query", params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                                                          "resultOffset": page * PAGE, "resultRecordCount": PAGE})
            if resp.status_code != 200:
                if page == 0:
                    raise ConnectorError(f"council_trees: {title} answered {resp.status_code}")
                log.warning("council_trees: stopped at page %s (%s)", page, resp.status_code)
                break
            feats = (resp.json() or {}).get("features") or []
            if not feats:
                break
            (raw_dir / f"auckland_{page:03d}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}),
                                                                  encoding="utf-8")
            n += len(feats)
            if len(feats) < PAGE:
                break
        if not n:
            raise ConnectorError(f"council_trees: {title} gave no trees")
        log.info("council_trees: %s Auckland trees from %s", n, title)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        geo, counts = [], defaultdict(int)
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() not in (".csv", ".geojson", ".json"):
                continue
            council = re.split(r"[_\-\s.]", p.stem.lower())[0] or "council"
            for i, t in enumerate(tree_records(p)):
                counts[council] += 1
                fid = f"{council}-{t['id'] or f'{p.stem}-{i}'}"
                props = {"council": council, "species": t["species"], "common": t["common"], "planted": t["planted"],
                         "height": t["height"]}
                geo.append(("street_trees", fid, t["common"] or t["species"] or "Tree", 1,
                            {k: v for k, v in props.items() if v is not None}, [COUNCIL_ENTITY.get(council, "")],
                            {"type": "Point", "coordinates": [t["lon"], t["lat"]]}))
        if not geo:
            raise ConnectorError(f"council_trees: no trees with a location in {raw_dir}")
        self.history_queries = {"geo_features": stage_geo(con, geo)}
        log.info("council_trees: %s", ", ".join(f"{c} {n:,}" for c, n in counts.items()))
        return Rows().stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- NZ Land Cover Database
LCDB_CLASS_COL = re.compile(r"^class_?(\d{4})$", re.IGNORECASE)


def lcdb_records(raw_dir: Path, tmp: Path):
    """(classes {year: code}, area ha, centroid lon/lat, geometry in lon/lat or None) for each LCDB
    polygon, from a GeoPackage, a zipped or loose shapefile, or a table with an area column."""
    files = list(raw_dir.iterdir())
    for z in [p for p in files if p.suffix.lower() == ".zip"]:
        files += _unzip(z, (".gpkg", ".shp", ".dbf", ".shx", ".prj", ".csv"), tmp)
    gpkgs = [p for p in files if p.suffix.lower() == ".gpkg" and "lcdb" in p.name.lower()]
    shps = [p for p in files if p.suffix.lower() == ".shp" and "lcdb" in p.name.lower()]
    tables = [p for p in files if p.suffix.lower() in (".csv", ".xlsx") and "lcdb" in p.name.lower()]
    if gpkgs:
        for table, info in gpkg_layers(gpkgs[0]).items():
            ycols = {c: int(m[1]) for c in info["columns"] if (m := LCDB_CLASS_COL.match(c))}
            if not ycols or not info["geom"]:
                continue
            proj = info["proj"] or nztm_to_lonlat
            for r in gpkg_rows(gpkgs[0], table, list(ycols) + [info["geom"]]):
                g = gpkg_geometry(r[-1])
                if g is None:
                    continue
                yield _lcdb_one(dict(zip(ycols.values(), r[:-1])), g, proj)
        return
    if shps:
        import shapefile
        from shapely.geometry import shape

        with shapefile.Reader(str(shps[0])) as sf:
            names = [f[0] for f in sf.fields[1:]]
            ycols = {i: int(m[1]) for i, n in enumerate(names) if (m := LCDB_CLASS_COL.match(n))}
            prj = shps[0].with_suffix(".prj")
            geographic = prj.exists() and "PROJCS" not in prj.read_text(errors="replace")
            proj = None if geographic else nztm_to_lonlat
            for sr in sf.iterShapeRecords():
                g = shape(sr.shape.__geo_interface__)
                yield _lcdb_one({y: sr.record[i] for i, y in ycols.items()}, g, proj)
        return
    for t in tables:
        rows = xlsx_rows(t) if t.suffix.lower() == ".xlsx" else read_table(t)
        head = [key(h) for h in rows[0]] if rows else []
        ycols = {i: int(m[1]) for i, h in enumerate(head) if (m := re.fullmatch(r"class(\d{4})", h))}
        ai = next((i for i, h in enumerate(head) if h in ("areaha", "area", "hectares", "shapearea")), None)
        if not ycols or ai is None:
            continue
        for r in rows[1:]:
            a = num(r[ai]) if ai < len(r) else None
            if a is None:
                continue
            yield {y: _code(r[i]) for i, y in ycols.items() if i < len(r)}, (a / 1e4 if head[ai] == "shapearea" else a), None, None


def _code(v) -> int | None:
    n = num(v)
    return int(n) if n is not None else None


def _lcdb_one(classes: dict, g, proj):
    area_ha = g.area / 1e4 if proj is not None else None  # NZTM metres
    pt = g.representative_point()
    lonlat = proj(pt.x, pt.y) if proj else (pt.x, pt.y)
    if area_ha is None:  # degrees: rough area at this latitude
        area_ha = g.area * (111.32e3 ** 2) * math.cos(math.radians(lonlat[1])) / 1e4
    return {y: _code(c) for y, c in classes.items()}, area_ha, lonlat, (g, proj)


def region_index(raw_dir: Path, tmp: Path):
    """Regional council boundaries saved beside the LCDB (a file with "regional" in its name):
    a function lon/lat -> region entity id, or None when there are none."""
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    polys, ids = [], []
    files = list(raw_dir.iterdir()) + list(tmp.iterdir())
    for p in files:
        n = p.name.lower()
        if "regional" not in n:
            continue
        if p.suffix.lower() == ".gpkg":
            for table, info in gpkg_layers(p).items():
                namec = next((c for c in info["columns"] if re.search(r"(?:REGC\d*_V\d+_\d+_NAME|REGC_NAME|^NAME$)", c, re.IGNORECASE)), None)
                if not namec or not info["geom"]:
                    continue
                for nm, blob in gpkg_rows(p, table, [namec, info["geom"]]):
                    g, ent = gpkg_geometry(blob), nz_region(nm)
                    if g is not None and ent:
                        polys.append(reproject(g, info["proj"]) if info["proj"] else g)
                        ids.append(ent)
        elif p.suffix.lower() in (".geojson", ".json"):
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            for f in data.get("features", []):
                props = f.get("properties") or {}
                nm = next((v for k, v in props.items() if re.search(r"NAME", k, re.IGNORECASE) and isinstance(v, str)), None)
                ent = nz_region(nm)
                if ent and f.get("geometry"):
                    g = shape(f["geometry"])
                    if abs(g.bounds[0]) > 1000:
                        g = reproject(g, nztm_to_lonlat)
                    polys.append(g)
                    ids.append(ent)
    if not polys:
        return None
    tree = STRtree(polys)

    def find(lon: float, lat: float) -> str | None:
        pt = Point(lon, lat)
        for i in tree.query(pt):
            if polys[i].contains(pt):
                return ids[i]
        return None
    return find


class NZLCDB(Connector):
    source_id = "nz_lcdb"
    switch = "land_nz_fetch"
    manual = True
    pack = "nz"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        m = re.search(r"v(\d+(?:[._]\d+)?)", " ".join(p.name for p in files), re.IGNORECASE)
        return f"v{m[1].replace('_', '.')}" if m else None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("nz_lcdb: the LRIS portal needs a free login; save the LCDB by hand (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        import shutil

        tmp = Path(tempfile.mkdtemp(prefix="lcdb_"))
        try:
            records = list(lcdb_records(raw_dir, tmp))
            where = region_index(raw_dir, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not records:
            raise ConnectorError(f"nz_lcdb: no LCDB polygons or table with Class_<year> columns in {raw_dir}")
        cover: dict[tuple[str, int, int], float] = defaultdict(float)
        change: dict[tuple[str, int, int, int], float] = defaultdict(float)
        years = sorted({y for c, *_ in records for y in c})
        geo = []
        for i, (classes, area, lonlat, gp) in enumerate(records):
            ents = ["NZL"]
            if where and lonlat:
                reg = where(*lonlat)
                if reg:
                    ents.append(reg)
            for y, c in classes.items():
                if c is None:
                    continue
                for e in ents:
                    cover[(e, y, c)] += area
            for y0, y1 in zip(years, years[1:]):
                a, b = classes.get(y0), classes.get(y1)
                if a is None or b is None or a == b:
                    continue
                for e in ents:
                    change[(e, y1, a, b)] += area
                if y1 == years[-1] and gp is not None and area >= 1:
                    g, proj = gp
                    gl = reproject(g, proj) if proj else g
                    gl = gl.simplify(0.0002, preserve_topology=True)
                    geo.append(("nz_land_change", f"{y0}-{y1}-{i}", f"{LCDB_CLASSES.get(a, (str(a),))[0]} to "
                                f"{LCDB_CLASSES.get(b, (str(b),))[0]}", 1 if area >= 20 else 2,
                                {"from": a, "to": b, "y0": y0, "y1": y1, "ha": round(area, 1), "region": ents[-1]},
                                ["NZL"], json.loads(json.dumps(gl.__geo_interface__))))
        rows = Rows()
        for (e, y, c), a in cover.items():
            rows.add("iso3", e, "nz_lcdb_ha", y, a, breakdown=f"class={c}")
        for (e, y, a, b), v in change.items():
            rows.add("iso3", e, "nz_lcdb_change_ha", y, v, breakdown=f"change={a}>{b}")
        if geo:
            self.history_queries = {"geo_features": stage_geo(con, geo)}
        self.listed_indicators = [
            indicator("nz_lcdb_ha", "Land cover by class (NZ LCDB)", "Hectares in each Land Cover Database class at each "
                      "survey year (breakdown class=<code>; the Land page groups them into 16 kinds and 7 groups).", "ha",
                      "land", self.source_id, "nz_lcdb_ha", decimals=0, bounds=(0, 3e7), breakdowns=["class"],
                      notes="Manaaki Whenua – Landcare Research, LCDB (CC BY 4.0)."),
            indicator("nz_lcdb_change_ha", "Land cover change between surveys (NZ LCDB)", "Hectares that changed from one "
                      "class to another since the survey before (breakdown change=<from>><to>, dated at the later survey).",
                      "ha", "land", self.source_id, "nz_lcdb_change_ha", decimals=0, bounds=(0, 3e7), breakdowns=["change"],
                      notes="Manaaki Whenua – Landcare Research, LCDB (CC BY 4.0)."),
        ]
        log.info("nz_lcdb: %s polygons, surveys %s, %s changed polygons mapped%s", len(records), years, len(geo),
                 "" if where else " (no regional council file: national totals only)")
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- NZ forestry tables
NZF = {  # indicator -> (name, description, unit, words all in the column heading or file name)
    "nz_new_planting_ha": ("New forest planting (NZ)", "Hectares of new plantation forest planted in the year (MPI).", "ha",
                           ("new", "plant")),
    "nz_replanting_ha": ("Forest replanting (NZ)", "Hectares replanted after harvest (MPI).", "ha", ("replant",)),
    "nz_harvest_area_ha": ("Forest harvested (NZ)", "Hectares of plantation forest harvested (MPI).", "ha", ("harvest",)),
    "nz_plantation_ha": ("Plantation forest area (NZ)", "Net stocked plantation forest at 1 April (MPI National Exotic "
                         "Forest Description).", "ha", ("stocked",)),
    "nz_ets_forest_ha": ("Forest registered in the ETS (NZ)", "Hectares of forest land registered in the Emissions Trading "
                         "Scheme (post-1989 forest).", "ha", ("ets",)),
    "nz_farm_to_forest_ha": ("Farmland sold for forestry (NZ)", "Hectares of whole farms sold to be planted in forest "
                             "(Overseas Investment Office and MPI land-use change figures).", "ha", ("farm", "forest")),
}


def _nzf_match(text: str) -> str | None:
    return next((k for k, (*_, words) in NZF.items() if all(w in text for w in words)), None)


def nzf_figures(table: list[list], fname: str) -> list[tuple[str, str | None, int, float]]:
    """(indicator, region, year, value) from a table with a year column and figure columns, or a
    year per column. Headings (and the file name) pick the indicator."""
    out = []
    for i, row in enumerate(table[:30]):
        heads = [str(c or "").strip() for c in row]
        low = [h.lower() for h in heads]
        yi = next((j for j, h in enumerate(low) if h in ("year", "year ended", "year to march", "year ending", "date")), None)
        ri = next((j for j, h in enumerate(low) if h in ("region", "regional council", "wood supply region")), None)
        if yi is not None:
            for j, h in enumerate(low):
                if j in (yi, ri):
                    continue
                ind = _nzf_match(h) or _nzf_match(f"{h} {fname}")
                if not ind:
                    continue
                for r in table[i + 1:]:
                    if len(r) <= max(j, yi):
                        continue
                    m = re.search(r"(19\d\d|20\d\d)", str(r[yi]))
                    v = num(r[j])
                    if m and v is not None:
                        out.append((ind, nz_region(r[ri]) if ri is not None and ri < len(r) else None, int(m[1]), v))
            if out:
                return out
        ycols = {j: int(m[1]) for j, h in enumerate(heads) if (m := re.fullmatch(r"(19\d\d|20\d\d)(?:\.0)?", h))}
        if len(ycols) >= 2:
            for r in table[i + 1:]:
                label = str(r[0] or "").lower() if r else ""
                ind = _nzf_match(label) or _nzf_match(f"{label} {fname}")
                if not ind:
                    continue
                for j, y in ycols.items():
                    v = num(r[j]) if j < len(r) else None
                    if v is not None:
                        out.append((ind, None, y, v))
            if out:
                return out
    return out


class NZForestry(Connector):
    source_id = "nz_forestry"
    switch = "land_nz_fetch"
    manual = True
    keeps_files = True
    pack = "nz"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("nz_forestry: save the MPI forestry tables by hand (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() not in (".csv", ".xlsx", ".xlsm"):
                continue
            try:
                table = read_table(p)
            except Exception as exc:  # noqa: BLE001 - one unreadable file should not stop the rest
                log.warning("nz_forestry: %s not read (%s)", p.name, exc)
                continue
            for ind, reg, y, v in nzf_figures(table, p.stem.lower()):
                rows.add("iso3", reg or "NZL", ind, y, v)
        if not len(rows):
            raise ConnectorError(f"nz_forestry: no forestry figures read from {raw_dir}")
        used = {r[2] for r in rows.rows}
        self.listed_indicators = [indicator(i, n, d, u, "land", self.source_id, i, decimals=0, bounds=(0, 1e8),
                                            aggregation={"method": "sum"})
                                  for i, (n, d, u, _) in NZF.items() if i in used]
        return rows.stage(con, self.source_id, vintage)


__all__ = [
    "NZLCDB",
    "CouncilTrees",
    "GFWTreeCover",
    "GHSLUrbanCentres",
    "HYDELand",
    "NZForestry",
    "gfw_rows",
    "hyde_txt",
    "mollweide_to_lonlat",
    "nzf_figures",
    "nztm_to_lonlat",
    "tree_records",
]
