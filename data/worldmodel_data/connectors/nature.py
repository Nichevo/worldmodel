"""Climate zones, pollution and nature: the sources behind the Pollution page, the Climate
page's Zones and Nature tabs, and each country's Zones, Pollution and Nature cards. Each is
switchable in Settings > Nature and pollution.

koppen_beck
    Beck et al. (2023), Köppen-Geiger climate zones at 0.1° for six periods (1901-1930 to
    1991-2020 observed; 2041-2070 and 2071-2099 projected under SSP1-2.6, SSP2-4.5 and
    SSP5-8.5), from figshare (article 21789074; one zip of GeoTIFFs, about 1 GB, read once:
    only the 0.1° grids are kept). Stored as zone_grids (one compressed grid per period and
    path, for the map and city twins) and, per country, the share of land in each zone
    (climate_zone_share, breakdown zone=<code>) and in each of the five main groups
    (climzone_a ... climzone_e), dated at the middle year of each period. Future periods are
    projections (status P): central = SSP2-4.5, low = SSP1-2.6, high = SSP5-8.5.

berkeley_earth
    Berkeley Earth's land temperature per country (Regional/TAVG/<country>-TAVG-Trend.txt):
    the monthly anomaly against 1951-1980, averaged to years with all twelve months, and the
    absolute temperature (the file's 1951-1980 average plus the anomaly).

psmsl
    PSMSL tide gauges (annual mean sea level, revised local reference): a map layer of
    gauges with their trend in mm a year (gauges with at least 30 years).

un_sdg
    The UN SDG database (unstats.un.org/sdgapi): safely treated wastewater, water bodies
    with good quality, water stress, the Red List Index and the share of key biodiversity
    areas (land, fresh water, sea) that is protected.

nd_gain
    The Notre Dame Global Adaptation Index: how exposed a country is to climate change and
    how ready it is to adapt (gain.csv, vulnerability.csv, readiness.csv in the download zip).

griis
    The Global Register of Introduced and Invasive Species, through GBIF: introduced and
    invasive species listed for each country (one checklist each).

iucn_redlist
    The IUCN Red List API (v4, needs IUCN_API_KEY): species in each Red List category for
    New Zealand, Australia, the United States and the United Kingdom, and the critically
    endangered and extinct species by name (species_status).

eppo_pests
    EPPO Global Database (needs EPPO_API_KEY): where each pest in nature.yaml's watch list
    is found (pest_presence) and how many of them each country has.

wahis_outbreaks
    WOAH WAHIS animal disease outbreaks, from a table you download (manual): outbreaks per
    country, year and disease.

wdpa
    The World Database on Protected Areas (Protected Planet), the monthly shapefile zip
    (about 900 MB). Kept: areas of 10 km² or more everywhere and every area in New
    Zealand, simplified; the zip is deleted once read. Stored as protected_areas.

nature_curated
    Hand-checked lists in nature.yaml: animal disease outbreaks, pest and weed incursions
    (New Zealand biosecurity first), smoke and haze across borders, as events.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import math
import re
import time
import zipfile
import zlib
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np

from worldmodel_contract import catalogue
from worldmodel_contract.koppen import GROUPS, ZONES
from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, make_date, stage_events
from worldmodel_data.connectors.internet import COUNTRIES_FILE, COUNTRIES_URL, country_grid
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows

log = logging.getLogger(__name__)
NO_ROWS = EMPTY_OBSERVATIONS

# ----------------------------------------------------------------------------- Köppen-Geiger zones
PERIODS = {"1901_1930": 1916, "1931_1960": 1946, "1961_1990": 1976, "1991_2020": 2006, "2041_2070": 2056, "2071_2099": 2085}
PATHS = {"ssp126": "low", "ssp245": "central", "ssp585": "high"}
KOPPEN_ARTICLE = "https://api.figshare.com/v2/articles/21789074"
TIF_NAME = re.compile(r"(\d{4})_(\d{4})(?:_(ssp\d{3}))?_koppen_geiger_0p1\.tif$")
MEMBER = re.compile(r"(\d{4})_(\d{4})/(?:(ssp\d{3})/)?koppen_geiger_0p1\.tif$")


def read_tif(path: Path) -> np.ndarray:
    """A single-band 8-bit GeoTIFF as an array (rows from the north)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as im:
        a = np.asarray(im)
    if a.ndim == 3:
        a = a[:, :, 0]
    return a.astype(np.uint8)


def zone_shares(zones: np.ndarray, countries: np.ndarray, n_countries: int) -> np.ndarray:
    """Share (%) of each country's land in each zone, weighting cells by their area
    (cos latitude). Returns [country number, zone number] with zone 0 unused."""
    rows = zones.shape[0]
    cell = 180 / rows
    w = np.cos(np.radians(90 - (np.arange(rows) + 0.5) * cell))[:, None] * np.ones(zones.shape[1])
    land = (countries > 0) & (zones > 0) & (zones <= 30)
    idx = countries[land].astype(np.int64) * 31 + zones[land].astype(np.int64)
    sums = np.bincount(idx, weights=w[land], minlength=(n_countries + 1) * 31).reshape(n_countries + 1, 31)
    tot = sums.sum(1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, sums / tot * 100, 0)


def _countries_for(grid_shape: tuple[int, int], geojson: Path) -> tuple[np.ndarray, list[str]]:
    cell = 180 / grid_shape[0]
    grid, codes = country_grid(geojson, cell, 0)
    if grid.shape != grid_shape:  # a grid in another size: nearest cell
        r = (np.arange(grid_shape[0]) * grid.shape[0] // grid_shape[0])
        c = (np.arange(grid_shape[1]) * grid.shape[1] // grid_shape[1])
        grid = grid[r][:, c]
    return grid, codes


class KoppenBeck(Connector):
    source_id = "koppen_beck"
    switch = "nature_zones_fetch"
    frozen = True  # a published set; fetched again only when fetch_version rises
    stage_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return "2023-v2"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "2023-v2" if any(TIF_NAME.search(f.name) for f in files) else None

    def download(self, raw_dir: Path, release: str) -> str:
        meta = self.client.get(KOPPEN_ARTICLE)
        meta.raise_for_status()
        files = meta.json().get("files") or []
        pick = [f for f in files if f.get("name", "").lower().endswith(".zip") and "tif" in f["name"].lower()]
        if not pick:
            raise ConnectorError("koppen_beck: no GeoTIFF zip listed on figshare article 21789074; save the 0.1° "
                                 "tifs by hand (see Data status)")
        url = pick[0]["download_url"]
        zpath = raw_dir / "_koppen_tif.zip"
        self.get(url, zpath, cached=False)
        try:
            with zipfile.ZipFile(zpath) as z:
                got = 0
                for name in z.namelist():
                    m = MEMBER.search(name.replace("\\", "/"))
                    if m and (m[3] is None or m[3] in PATHS):
                        out = f"{m[1]}_{m[2]}{'_' + m[3] if m[3] else ''}_koppen_geiger_0p1.tif"
                        (raw_dir / out).write_bytes(z.read(name))
                        got += 1
                    elif name.lower().endswith("legend.txt"):
                        (raw_dir / "legend.txt").write_bytes(z.read(name))
        finally:
            zpath.unlink(missing_ok=True)
        if not got:
            raise ConnectorError("koppen_beck: the zip held no koppen_geiger_0p1.tif grids")
        self.get(COUNTRIES_URL, raw_dir / COUNTRIES_FILE)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        tifs = sorted(p for p in raw_dir.iterdir() if TIF_NAME.search(p.name))
        if not tifs:
            raise ConnectorError(f"koppen_beck: no *_koppen_geiger_0p1.tif grids in {raw_dir}")
        countries_file = raw_dir / COUNTRIES_FILE
        if not countries_file.exists():
            raise ConnectorError(f"koppen_beck: {COUNTRIES_FILE} is needed beside the grids (from {COUNTRIES_URL})")
        rows, grids, cgrid, codes = Rows(), [], None, []
        for path in tifs:
            m = TIF_NAME.search(path.name)
            period, scen = f"{m[1]}_{m[2]}", m[3] or "historical"
            if period not in PERIODS or (scen != "historical" and scen not in PATHS):
                continue
            z = read_tif(path)
            grids.append((f"{m[1]}-{m[2]}", scen, int(z.shape[1]), int(z.shape[0]), zlib.compress(z.tobytes(), 6)))
            if cgrid is None or cgrid.shape != z.shape:
                cgrid, codes = _countries_for(z.shape, countries_file)
            shares = zone_shares(z, cgrid, len(codes))
            year, status = PERIODS[period], ("E" if scen == "historical" else "P")
            variant = "central" if scen == "historical" else PATHS[scen]
            for n, code in enumerate(codes, start=1):
                s = shares[n]
                if s.sum() <= 0:
                    continue
                for g, (_, members) in GROUPS.items():
                    rows.rows.append(("iso3", code, f"climzone_{g.lower()}", date(year, 1, 1), "", float(round(s[list(members)].sum(), 3)),
                                      status, variant))
                for zn in range(1, 31):
                    if s[zn] >= 0.05:
                        rows.rows.append(("iso3", code, "climate_zone_share", date(year, 1, 1), f"zone={ZONES[zn][0]}",
                                          float(round(s[zn], 3)), status, variant))
        con.execute("CREATE TABLE zg (period VARCHAR, scenario VARCHAR, width INTEGER, height INTEGER, grid BLOB)")
        con.executemany("INSERT INTO zg VALUES (?, ?, ?, ?, ?)", grids)
        self.history_queries = {"zone_grids": "SELECT * FROM zg"}
        con.execute("CREATE TABLE kz (scheme VARCHAR, source_code VARCHAR, indicator_id VARCHAR, period_start DATE, "
                    "breakdown VARCHAR, value DOUBLE, status VARCHAR, variant VARCHAR)")
        if rows.rows:
            con.executemany("INSERT INTO kz VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows.rows)
        note = ("Beck et al. 2023 (CC BY 4.0), 0.1° grids; a period is dated at its middle year. Future periods are "
                "projections: the middle path SSP2-4.5, with SSP1-2.6 as low and SSP5-8.5 as high.")
        self.listed_indicators = [indicator(
            f"climzone_{g.lower()}", f"Land in {name.lower()} climates", f"Share of the country's land in the {name.lower()} "
            f"Köppen-Geiger zones (group {g}), for 30-year periods.", "%", "climate", self.source_id, f"group_{g}",
            decimals=1, bounds=(0, 100.01), notes=note) for g, (name, _) in GROUPS.items()] + [indicator(
                "climate_zone_share", "Land in each climate zone", "Share of the country's land in each of the 30 "
                "Köppen-Geiger zones (breakdown zone=Cfb and so on), for 30-year periods.", "%", "climate",
                self.source_id, "zone_share", decimals=1, bounds=(0, 100.01), notes=note)]
        log.info("koppen_beck: %s grids, %s country figures", len(grids), len(rows.rows))
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, scheme, source_code, "
                "indicator_id, period_start, 'A' AS freq, breakdown, variant, value, status FROM kz")


# ----------------------------------------------------------------------------- Berkeley Earth
BERKELEY = "https://berkeley-earth-temperature.s3.us-west-1.amazonaws.com/Regional/TAVG/{slug}-TAVG-Trend.txt"
BERKELEY_SLUGS = {"USA": "united-states", "GBR": "united-kingdom", "KOR": "south-korea", "PRK": "north-korea",
                  "COD": "democratic-republic-of-the-congo", "COG": "congo", "CIV": "côte-d'ivoire", "RUS": "russia",
                  "CZE": "czech-republic", "MKD": "macedonia", "SWZ": "swaziland", "TLS": "timor-leste",
                  "MMR": "burma", "CPV": "cape-verde", "VNM": "vietnam", "LAO": "laos", "IRN": "iran", "SYR": "syria",
                  "BOL": "bolivia", "VEN": "venezuela", "TZA": "tanzania", "MDA": "moldova", "BRN": "brunei"}


def berkeley_slug(entity_id: str, name: str) -> str:
    if entity_id in BERKELEY_SLUGS:
        return BERKELEY_SLUGS[entity_id]
    return re.sub(r"[^a-z0-9'()]+", "-", name.lower()).strip("-")


def berkeley_years(text: str) -> tuple[dict[int, float], float | None]:
    """Yearly mean anomaly (years with all twelve months) and the 1951-1980 absolute mean."""
    base = None
    m = re.search(r"Estimated Jan 1951-Dec 1980 absolute temperature \(C\):\s*(-?[\d.]+)", text)
    if m:
        base = float(m[1])
    months: dict[int, list[float]] = defaultdict(list)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("%"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        v = num(parts[2])
        if v is None or v != v:
            continue
        months[int(parts[0])].append(v)
    return {y: sum(v) / 12 for y, v in months.items() if len(v) == 12}, base


class BerkeleyEarth(Connector):
    source_id = "berkeley_earth"
    switch = "nature_climate_extras_fetch"
    fetch_every_days = 90
    gap = 0.3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for e in catalogue.entities().values():
            if e.type != "country":
                continue
            slug = berkeley_slug(e.entity_id, e.name)
            r = self.client.get(BERKELEY.format(slug=slug))
            if r.status_code == 200 and r.text.lstrip().startswith("%"):
                (raw_dir / f"{e.entity_id}-TAVG-Trend.txt").write_text(r.text, encoding="utf-8")
                got += 1
            time.sleep(self.gap)
        if not got:
            raise ConnectorError("berkeley_earth: no country files could be read")
        return BERKELEY.format(slug="<country>")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p in sorted(raw_dir.glob("*-TAVG-Trend.txt")):
            ent = p.name.split("-TAVG")[0]
            years, base = berkeley_years(p.read_text(encoding="utf-8", errors="replace"))
            for y, a in years.items():
                rows.add("iso3", ent, "be_temp_anomaly", y, round(a, 3))
                if base is not None:
                    rows.add("iso3", ent, "be_temp_mean", y, round(base + a, 3))
        if not len(rows):
            raise ConnectorError(f"berkeley_earth: no temperatures read from {raw_dir}")
        note = "Berkeley Earth land temperature (CC BY 4.0); years with all twelve months."
        self.listed_indicators = [
            indicator("be_temp_anomaly", "Land temperature against 1951-1980 (Berkeley Earth)", "The year's average "
                      "land temperature minus the 1951-1980 average, in °C.", "°C", "climate", self.source_id, "anomaly",
                      decimals=2, bounds=(-10, 10), notes=note),
            indicator("be_temp_mean", "Average land temperature (Berkeley Earth)", "The year's average land "
                      "temperature over the country, in °C.", "°C", "climate", self.source_id, "absolute",
                      decimals=1, bounds=(-40, 40), notes=note)]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- PSMSL tide gauges
PSMSL_URL = "https://psmsl.org/data/obtaining/rlr.annual.data/rlr_annual.zip"
PSMSL_MISSING = -99999


def trend(points: list[tuple[int, float]]) -> float | None:
    """Least-squares slope (per year)."""
    if len(points) < 2:
        return None
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    return sum((p[0] - mx) * (p[1] - my) for p in points) / sxx if sxx else None


def psmsl_gauges(zpath: Path, min_years: int = 30) -> list[dict]:
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        flist = next((n for n in names if n.endswith("filelist.txt")), None)
        if not flist:
            raise ConnectorError("psmsl: filelist.txt missing from the zip")
        stations = {}
        for line in z.read(flist).decode("utf-8", "replace").splitlines():
            parts = [p.strip() for p in line.split(";")]
            if len(parts) >= 4 and parts[0].isdigit():
                stations[parts[0]] = (num(parts[1]), num(parts[2]), parts[3].title())
        data = {re.sub(r"\D", "", Path(n).stem): n for n in names if n.endswith(".rlrdata")}
        out = []
        for sid, (lat, lon, name) in stations.items():
            if sid not in data or lat is None or lon is None:
                continue
            pts = []
            for line in z.read(data[sid]).decode("utf-8", "replace").splitlines():
                parts = [p.strip() for p in line.split(";")]
                if len(parts) >= 2:
                    y, v = num(parts[0]), num(parts[1])
                    if y is not None and v is not None and v != PSMSL_MISSING:
                        pts.append((int(y), v))
            if len(pts) < min_years:
                continue
            t_all = trend(pts)
            recent = [p for p in pts if p[0] >= pts[-1][0] - 29]
            t_30 = trend(recent) if len(recent) >= 20 else None
            out.append({"id": sid, "name": name, "lat": lat, "lon": lon, "from": pts[0][0], "to": pts[-1][0],
                        "years": len(pts), "trend": round(t_all, 2) if t_all is not None else None,
                        "trend30": round(t_30, 2) if t_30 is not None else None})
        return out


class PSMSL(Connector):
    source_id = "psmsl"
    switch = "nature_climate_extras_fetch"
    fetch_every_days = 182

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(PSMSL_URL, raw_dir / "rlr_annual.zip")
        return PSMSL_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        z = next(iter(sorted(raw_dir.glob("*.zip"))), None)
        if z is None:
            raise ConnectorError(f"psmsl: rlr_annual.zip not found in {raw_dir}")
        gauges = psmsl_gauges(z)
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [g["lon"], g["lat"]]},
                  "properties": {k: v for k, v in g.items() if k not in ("lat", "lon")}} for g in gauges]
        self.layers = [{"layer_id": "tide_gauges", "name": "Tide gauges (sea level trend)",
                        "description": "PSMSL tide gauges with at least 30 years: how fast the sea has risen against "
                                       "the land there, in mm a year (all years, and the last 30). Land rising or "
                                       "sinking is included, as it is what the coast feels.",
                        "kind": "point", "geojson": json.dumps({"type": "FeatureCollection", "features": feats})}]
        log.info("psmsl: %s tide gauges", len(feats))
        return NO_ROWS


# ----------------------------------------------------------------------------- UN SDG database
SDG_URL = "https://unstats.un.org/sdgapi/v1/sdg/Series/Data?seriesCode={code}&pageSize=100000"
SDG_SERIES = {
    # code: (indicator id, name, description, unit, domain, bounds, decimals)
    "EN_WWT_WWDS": ("wastewater_treated_share", "Household wastewater safely treated",
                    "Share of household wastewater flows that are safely treated (SDG 6.3.1).", "%", "pollution", (0, 100.01), 1),
    "EN_H2O_OPAMBQ": ("water_quality_good_share", "Water bodies with good water quality",
                      "Share of rivers, lakes and groundwater bodies tested whose water quality is good (SDG 6.3.2).",
                      "%", "pollution", (0, 100.01), 1),
    "ER_H2O_STRESS": ("water_stress", "Water stress", "Fresh water taken out as a share of the fresh water available "
                      "after what nature needs (SDG 6.4.2); above 100% the country uses more than is renewed.",
                      "%", "pollution", (0, 100000), 1),
    "ER_RSK_LST": ("red_list_index", "Red List Index", "How close the country's species are to extinction on average "
                   "(1 = none threatened, 0 = all extinct; SDG 15.5.1).", "index", "nature", (0, 1.0001), 3),
    "ER_PTD_TERR": ("kba_land_protected", "Key nature areas on land that are protected",
                    "Average share of each key biodiversity area on land covered by protected areas (SDG 15.1.2).",
                    "%", "nature", (0, 100.01), 1),
    "ER_PTD_FRWRT": ("kba_fresh_protected", "Key fresh-water nature areas that are protected",
                     "Average share of each key biodiversity area in fresh water covered by protected areas (SDG 15.1.2).",
                     "%", "nature", (0, 100.01), 1),
    "ER_MRN_MPA": ("kba_sea_protected", "Key marine nature areas that are protected",
                   "Average share of each key biodiversity area at sea covered by protected areas (SDG 14.5.1).",
                   "%", "nature", (0, 100.01), 1),
}
TOTAL_DIMS = {"ALLAREA", "BOTHSEX", "ALLAGE", "_T", "TOTAL", "_Z", "ALL", ""}


def sdg_rows(code: str, data: list[dict]) -> list[tuple[str, int, float]]:
    """(M49 code, year, value): one per place and year, preferring totals over breakdowns."""
    best: dict[tuple[str, int], tuple[int, float]] = {}
    for d in data:
        geo, year, v = d.get("geoAreaCode"), num(d.get("timePeriodStart")), num(d.get("value"))
        if geo is None or year is None or v is None:
            continue
        dims = d.get("dimensions") or {}
        score = sum(1 for k, val in dims.items() if k != "Reporting Type" and str(val) not in TOTAL_DIMS)
        score += 0 if dims.get("Reporting Type", "G") == "G" else 1
        k = (str(geo), int(year))
        if k not in best or score < best[k][0]:
            best[k] = (score, v)
    return [(g, y, v) for (g, y), (_, v) in best.items()]


class UNSDG(Connector):
    source_id = "un_sdg"
    switch = "nature_pollution_fetch"
    fetch_every_days = 90
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for code in SDG_SERIES:
            try:
                self.get(SDG_URL.format(code=code), raw_dir / f"{code}.json", cached=False)
                got += 1
            except Exception as exc:  # noqa: BLE001 - one series failing should not stop the others
                log.warning("un_sdg: %s not read (%s)", code, exc)
            time.sleep(1)
        if not got:
            raise ConnectorError("un_sdg: no series could be read from unstats.un.org")
        return SDG_URL.format(code="<series>")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, inds = Rows(), []
        for code, (iid, name, desc, unit, domain, bounds, dec) in SDG_SERIES.items():
            p = raw_dir / f"{code}.json"
            if not p.exists():
                continue
            body = json.loads(p.read_text(encoding="utf-8"))
            data = body.get("data") if isinstance(body, dict) else body
            n = 0
            for geo, y, v in sdg_rows(code, data or []):
                ent = entity_for("m49", geo)
                if ent:
                    rows.add("iso3", ent, iid, y, v)
                    n += 1
            if n:
                inds.append(indicator(iid, name, desc, unit, domain, self.source_id, code, decimals=dec, bounds=bounds,
                                      notes=f"UN SDG database, series {code}."))
        if not len(rows):
            raise ConnectorError(f"un_sdg: no figures read from {raw_dir}")
        self.listed_indicators = inds
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- ND-GAIN
NDGAIN_PAGES = ("https://gain.nd.edu/our-work/country-index/download-data/", "https://gain-new.crc.nd.edu/about/download")
NDGAIN_FILES = {"gain.csv": ("nd_gain", "Climate adaptation readiness score (ND-GAIN)",
                             "The ND-GAIN index: readiness to adapt minus vulnerability to climate change, scaled 0 to 100 "
                             "(higher is better placed).", "score", (0, 100), 1),
                "vulnerability.csv": ("nd_gain_vulnerability", "Vulnerability to climate change (ND-GAIN)",
                                      "How exposed and sensitive the country is to climate change and how little it can "
                                      "cope (0 to 1, higher is more vulnerable).", "index", (0, 1), 3),
                "readiness.csv": ("nd_gain_readiness", "Readiness to adapt to climate change (ND-GAIN)",
                                  "How ready the economy, government and society are to use investment for adaptation "
                                  "(0 to 1, higher is readier).", "index", (0, 1), 3)}


def ndgain_rows(name: str, text: str) -> list[tuple[str, int, float]]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        iso = (r.get("ISO3") or r.get("iso3") or "").strip()
        for k, v in r.items():
            if k and k.strip().isdigit() and iso:
                x = num(v)
                if x is not None:
                    out.append((iso, int(k), x))
    return out


class NDGAIN(Connector):
    source_id = "nd_gain"
    switch = "nature_climate_extras_fetch"
    fetch_every_days = 182

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for page in NDGAIN_PAGES:
            try:
                r = self.client.get(page)
                if r.status_code != 200:
                    continue
            except Exception:  # noqa: BLE001 - try the next page
                continue
            links = re.findall(r'href="([^"]+\.zip)"', r.text)
            if links:
                url = links[0] if links[0].startswith("http") else str(r.url.join(links[0]))
                self.get(url, raw_dir / "nd_gain.zip")
                return url
        raise ConnectorError("nd_gain: no download link found on the ND-GAIN pages; save the zip by hand (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        texts: dict[str, str] = {}
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() == ".zip":
                with zipfile.ZipFile(p) as z:
                    for n in z.namelist():
                        base = Path(n).name.lower()
                        if base in NDGAIN_FILES and base not in texts:
                            texts[base] = z.read(n).decode("utf-8-sig", "replace")
            elif p.name.lower() in NDGAIN_FILES:
                texts[p.name.lower()] = p.read_text(encoding="utf-8-sig", errors="replace")
        rows, inds = Rows(), []
        for f, (iid, name, desc, unit, bounds, dec) in NDGAIN_FILES.items():
            if f not in texts:
                continue
            for iso, y, v in ndgain_rows(f, texts[f]):
                rows.add("iso3", iso, iid, y, v)
            inds.append(indicator(iid, name, desc, unit, "climate", self.source_id, f, decimals=dec,
                                  bounds=(bounds[0], bounds[1] * 1.0001), notes="University of Notre Dame Global Adaptation Initiative."))
        if not len(rows):
            raise ConnectorError(f"nd_gain: none of gain.csv, vulnerability.csv, readiness.csv found in {raw_dir}")
        self.listed_indicators = inds
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- GRIIS through GBIF
GBIF = "https://api.gbif.org/v1"


def griis_country(title: str) -> str | None:
    """'Global Register of Introduced and Invasive Species - New Zealand' -> NZL."""
    m = re.search(r"Invasive Species\s*[-–:]\s*(.+)$", title or "")
    return catalogue.country_by_name(m[1].strip()) if m else None


class GRIIS(Connector):
    source_id = "griis"
    switch = "nature_species_fetch"
    fetch_every_days = 182
    gap = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        found, offset = [], 0
        while True:
            r = self.client.get(f"{GBIF}/dataset/search", params={"q": "Global Register of Introduced and Invasive Species",
                                                                     "type": "CHECKLIST", "limit": 200, "offset": offset})
            r.raise_for_status()
            body = r.json()
            found += [d for d in body.get("results", []) if "Introduced and Invasive" in (d.get("title") or "")]
            offset += 200
            if body.get("endOfRecords", True) or offset > 2000:
                break
            time.sleep(self.gap)
        out = []
        for d in found:
            time.sleep(self.gap)
            try:
                c = self.client.get(f"{GBIF}/species/search", params={"datasetKey": d["key"], "rank": "SPECIES", "limit": 0})
                c.raise_for_status()
                out.append({"key": d["key"], "title": d.get("title"), "modified": d.get("modified") or d.get("pubDate"),
                            "species": c.json().get("count")})
            except Exception as exc:  # noqa: BLE001 - one checklist failing should not stop the rest
                log.warning("griis: %s not counted (%s)", d.get("title"), exc)
        if not out:
            raise ConnectorError("griis: no GRIIS checklists found on GBIF")
        (raw_dir / "griis_checklists.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        return f"{GBIF}/dataset/search?q=GRIIS"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "griis_checklists.json"
        if not p.exists():
            raise ConnectorError(f"griis: griis_checklists.json not found in {raw_dir}")
        rows, missed = Rows(), set()
        for d in json.loads(p.read_text(encoding="utf-8")):
            ent = griis_country(d.get("title") or "")
            year = int(str(d.get("modified") or release)[:4])
            if ent and d.get("species") is not None:
                rows.add("iso3", ent, "introduced_species", year, float(d["species"]))
            elif not ent:
                missed.add(d.get("title") or "?")
        if missed:
            log.info("griis: %s checklists not matched to a country", len(missed))
        self.listed_indicators = [indicator(
            "introduced_species", "Introduced and invasive species listed", "Species brought in by people and now living "
            "wild in the country, as listed in its GRIIS checklist (the year is when the list was last updated).",
            "species", "nature", self.source_id, "species", decimals=0, bounds=(0, 100000),
            notes="Global Register of Introduced and Invasive Species, through GBIF (CC BY 4.0). Lists differ in how "
                  "thoroughly they were compiled.")]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- IUCN Red List
IUCN = "https://api.iucnredlist.org/api/v4/countries/{code}"
IUCN_COUNTRIES = {"NZ": "NZL", "AU": "AUS", "US": "USA", "GB": "GBR"}
IUCN_CATS = {"EX": "Extinct", "EW": "Extinct in the wild", "CR": "Critically endangered", "EN": "Endangered",
             "VU": "Vulnerable", "NT": "Near threatened", "LC": "Least concern", "DD": "Data deficient"}


def iucn_counts(assessments: list[dict]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    seen = set()
    for a in assessments:
        if a.get("latest") is False:
            continue
        sid = a.get("sis_taxon_id") or a.get("taxon_scientific_name")
        if sid in seen:
            continue
        seen.add(sid)
        cat = (a.get("red_list_category_code") or "").upper()
        if cat in IUCN_CATS:
            out[cat] += 1
        out["all"] += 1
    return out


class IUCNRedList(Connector):
    source_id = "iucn_redlist"
    switch = "nature_species_fetch"
    needs_env = ("IUCN_API_KEY",)
    fetch_every_days = 182
    gap = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        token = self.env("IUCN_API_KEY")
        for code in IUCN_COUNTRIES:
            items, page = [], 1
            while page < 400:
                r = self.client.get(IUCN.format(code=code), params={"page": page, "latest": "true"},
                                    headers={"Authorization": f"Bearer {token}"})
                if r.status_code in (401, 403):
                    raise ConnectorError(f"iucn_redlist: the API refused the key ({r.status_code})")
                r.raise_for_status()
                got = r.json().get("assessments") or []
                items += got
                total = int(r.headers.get("total-pages") or 0)
                if not got or (total and page >= total):
                    break
                page += 1
                time.sleep(self.gap)
            (raw_dir / f"iucn_{code}.json").write_text(json.dumps({"assessments": items}), encoding="utf-8")
        return IUCN.format(code="<country>")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, species = Rows(), []
        year = int(release[:4])
        for code, ent in IUCN_COUNTRIES.items():
            p = raw_dir / f"iucn_{code}.json"
            if not p.exists():
                continue
            items = json.loads(p.read_text(encoding="utf-8")).get("assessments") or []
            c = iucn_counts(items)
            for cat in IUCN_CATS:
                rows.add("iso3", ent, f"iucn_{cat.lower()}", year, float(c.get(cat, 0)))
            rows.add("iso3", ent, "iucn_threatened", year, float(c.get("CR", 0) + c.get("EN", 0) + c.get("VU", 0)))
            rows.add("iso3", ent, "iucn_assessed", year, float(c.get("all", 0)))
            for a in items:
                cat = (a.get("red_list_category_code") or "").upper()
                if cat in ("EX", "EW", "CR") and a.get("latest") is not False:
                    sid, aid = a.get("sis_taxon_id"), a.get("assessment_id")
                    url = f"https://www.iucnredlist.org/species/{sid}/{aid}" if sid and aid else None
                    species.append((ent, a.get("taxon_scientific_name"), cat, num(a.get("year_published")), url))
        if not len(rows):
            raise ConnectorError(f"iucn_redlist: no iucn_<country>.json files in {raw_dir}")
        con.execute("CREATE TABLE sp (country_code VARCHAR, scientific_name VARCHAR, category VARCHAR, year INTEGER, url VARCHAR)")
        con.executemany("INSERT INTO sp VALUES (?, ?, ?, ?, ?)", [(e, n, c, int(y) if y else None, u) for e, n, c, y, u in species if n])
        self.history_queries = {"species_status": "SELECT DISTINCT * FROM sp"}
        note = "IUCN Red List API; species assessed for the country, counted on the day of the fetch."
        self.listed_indicators = [indicator(
            f"iucn_{c.lower()}", f"Species: {label.lower()} (IUCN)", f"Species found in the country assessed as "
            f"{label.lower()} on the IUCN Red List.", "species", "nature", self.source_id, c, decimals=0,
            bounds=(0, 200000), notes=note) for c, label in IUCN_CATS.items()] + [
            indicator("iucn_threatened", "Threatened species (IUCN)", "Species found in the country assessed as "
                      "critically endangered, endangered or vulnerable.", "species", "nature", self.source_id,
                      "threatened", decimals=0, bounds=(0, 200000), notes=note),
            indicator("iucn_assessed", "Species assessed (IUCN)", "Species found in the country with a Red List "
                      "assessment.", "species", "nature", self.source_id, "assessed", decimals=0, bounds=(0, 500000),
                      notes=note)]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- EPPO pests
EPPO = "https://data.eppo.int/api/rest/1.0/taxon/{code}/distribution"


def pest_present(status: str | None) -> bool:
    s = (status or "").lower()
    return s.startswith("present") or s.startswith("transient")


class EPPOPests(Connector):
    source_id = "eppo_pests"
    switch = "nature_species_fetch"
    needs_env = ("EPPO_API_KEY",)
    fetch_every_days = 90
    gap = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        token = self.env("EPPO_API_KEY")
        got = 0
        for pest in catalogue.nature().get("pests", []):
            r = self.client.get(EPPO.format(code=pest["code"]), params={"authtoken": token})
            if r.status_code in (401, 403):
                raise ConnectorError(f"eppo_pests: the API refused the key ({r.status_code})")
            if r.status_code == 200:
                (raw_dir / f"eppo_{pest['code']}.json").write_text(r.text, encoding="utf-8")
                got += 1
            time.sleep(self.gap)
        if not got:
            raise ConnectorError("eppo_pests: no pest distributions read")
        return EPPO.format(code="<pest>")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pests = {p["code"]: p for p in catalogue.nature().get("pests", [])}
        presence, counts = [], defaultdict(set)
        for p in sorted(raw_dir.glob("eppo_*.json")):
            code = p.stem[5:]
            items = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(items, dict):
                items = items.get("distribution") or items.get("data") or []
            for d in items:
                ent = entity_for("iso2", d.get("country_iso"))
                if not ent:
                    continue
                present = pest_present(d.get("status"))
                presence.append((code, pests.get(code, {}).get("name", code), ent, d.get("state") or None,
                                 d.get("status"), present))
                if present:
                    counts[ent].add(code)
        if not presence:
            raise ConnectorError(f"eppo_pests: no eppo_<code>.json files in {raw_dir}")
        con.execute("CREATE TABLE pp (pest_code VARCHAR, pest_name VARCHAR, country_code VARCHAR, state VARCHAR, "
                    "status VARCHAR, present BOOLEAN)")
        con.executemany("INSERT INTO pp VALUES (?, ?, ?, ?, ?, ?)", presence)
        self.history_queries = {"pest_presence": "SELECT DISTINCT * FROM pp"}
        rows = Rows()
        year = int(release[:4])
        for ent in {r[2] for r in presence}:
            rows.add("iso3", ent, "watched_pests_present", year, float(len(counts.get(ent, ()))))
        self.listed_indicators = [indicator(
            "watched_pests_present", "Watched pests present", f"How many of the {len(pests)} pests and diseases on the "
            "watch list (nature.yaml) EPPO records as present in the country.", "pests", "nature", self.source_id,
            "present", decimals=0, bounds=(0, 1000), notes="EPPO Global Database; counted on the day of the fetch.")]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- WAHIS (a file you download)
def _col(header: list[str], *names: str) -> int | None:
    keys = [key(h) for h in header]
    for n in map(key, names):
        for i, k in enumerate(keys):
            if k == n or k.startswith(n):
                return i
    return None


def wahis_rows(table: list[list]) -> list[tuple[str, int, str, float]]:
    """(entity, year, disease, outbreaks) from a WAHIS export: a row per outbreak or per
    country, disease and period with a count column."""
    head_at = next((i for i, r in enumerate(table[:20]) if any(key(c) in ("country", "countryname") for c in r if c)), None)
    if head_at is None:
        raise ConnectorError("wahis: no Country column found")
    header = [str(c or "") for c in table[head_at]]
    ci = _col(header, "country")
    di = _col(header, "disease")
    yi = _col(header, "year", "start_date", "outbreak_start", "event_start", "report_date", "date")
    ni = _col(header, "outbreaks", "new_outbreaks", "number_of_outbreaks")
    if ci is None or di is None or yi is None:
        raise ConnectorError("wahis: the table needs Country, Disease and a year or date column")
    out: dict[tuple, float] = defaultdict(float)
    for r in table[head_at + 1:]:
        if len(r) <= max(ci, di, yi):
            continue
        ent = catalogue.country_by_name(str(r[ci] or ""))
        m = re.search(r"(19|20)\d{2}", str(r[yi] or ""))
        if not ent or not m or not r[di]:
            continue
        n = num(r[ni]) if ni is not None and ni < len(r) else 1.0
        out[(ent, int(m[0]), str(r[di]).strip())] += n if n is not None else 1.0
    return [(e, y, d, v) for (e, y, d), v in out.items()]


class WAHISOutbreaks(Connector):
    source_id = "wahis_outbreaks"
    manual = True
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("wahis_outbreaks: download the outbreak table from WAHIS and load it (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, n = Rows(), 0
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() in (".xlsx", ".xlsm"):
                table = xlsx_rows(p)
            elif p.suffix.lower() == ".csv":
                table = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig", errors="replace"))))
            else:
                continue
            for ent, y, disease, v in wahis_rows(table):
                rows.add("iso3", ent, "animal_disease_outbreaks", y, v, breakdown=f"disease={disease[:60]}")
                n += 1
        if not n:
            raise ConnectorError(f"wahis_outbreaks: no outbreaks read from {raw_dir}")
        # The total per country and year, for maps and charts.
        tot: dict[tuple, float] = defaultdict(float)
        for _, ent, _, d, bd, v, _ in rows.rows:
            tot[(ent, d.year)] += v
        for (ent, y), v in tot.items():
            rows.add("iso3", ent, "animal_disease_outbreaks", y, v)
        self.listed_indicators = [indicator(
            "animal_disease_outbreaks", "Animal disease outbreaks reported", "Outbreaks of listed animal diseases "
            "reported to the World Organisation for Animal Health (breakdown disease=<name>).", "outbreaks",
            "nature", self.source_id, "outbreaks", decimals=0, bounds=(0, 1e6), notes="WOAH WAHIS, from a table you download.")]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- WDPA protected areas
WDPA_URL = "https://d1gam3xoknrgr2.cloudfront.net/current/WDPA_{mon}{year}_Public_shp.zip"
WDPA_MIN_KM2 = 10.0
WDPA_ALL_IN = {"NZL"}
WDPA_FILE = "wdpa_selected.geojson.gz"
WDPA_TOL = 0.01


def _box(geometry: dict) -> dict | None:
    """A small area's bounding box (smaller than simplify keeps), so it still shows on the map."""
    pts = [p for ring in (geometry.get("coordinates") or []) for p in (ring if geometry["type"] == "Polygon" else ring[0])]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, s, e, n = (round(v, 3) for v in (min(xs), min(ys), max(xs), max(ys)))
    return {"type": "Polygon", "coordinates": [[[w, s], [w, n], [e, n], [e, s], [w, s]]]}


def wdpa_months(today: date) -> list[tuple[str, int]]:
    out, y, m = [], today.year, today.month
    for _ in range(3):
        out.append((date(y, m, 1).strftime("%b"), y))
        m -= 1
        if not m:
            y, m = y - 1, 12
    return out


def wdpa_select(shp_zips: list[Path], dest: Path, min_km2: float = WDPA_MIN_KM2) -> int:
    """Read the polygon layers of the WDPA shapefile zips, keep the large areas (and every
    area in WDPA_ALL_IN), simplify them and write them as gzipped GeoJSON. Returns how many."""
    import shapefile  # pyshp

    from worldmodel_data.connectors.history import simplify

    feats = []
    for zp in shp_zips:
        with zipfile.ZipFile(zp) as z:
            inner = [n for n in z.namelist() if n.lower().endswith(".zip")]
            sets = [(z, n[:-4]) for n in z.namelist() if n.lower().endswith("polygons.shp")]
            for n in inner:  # the monthly zip holds three zips of shapefiles
                zz = zipfile.ZipFile(io.BytesIO(z.read(n)))
                sets += [(zz, m[:-4]) for m in zz.namelist() if m.lower().endswith("polygons.shp")]
            for zf, stem in sets:
                r = shapefile.Reader(shp=io.BytesIO(zf.read(stem + ".shp")), shx=io.BytesIO(zf.read(stem + ".shx")),
                                     dbf=io.BytesIO(zf.read(stem + ".dbf")), encoding="utf-8", encodingErrors="replace")
                fields = [f[0] for f in r.fields[1:]]
                for i, rec in enumerate(r.iterRecords()):
                    d = dict(zip(fields, rec))
                    area = num(d.get("GIS_AREA")) or num(d.get("REP_AREA")) or 0
                    iso = str(d.get("ISO3") or "")[:3]
                    if area < min_km2 and iso not in WDPA_ALL_IN:
                        continue
                    if str(d.get("STATUS") or "").lower() in ("proposed", "not reported"):
                        continue
                    g = r.shape(i).__geo_interface__
                    small = simplify(g, WDPA_TOL) or simplify(g, 0) or _box(g)
                    if small is None:
                        continue
                    feats.append({"type": "Feature", "geometry": small, "properties": {
                        "id": str(d.get("WDPAID") or ""), "name": d.get("NAME") or d.get("ORIG_NAME"),
                        "desig": d.get("DESIG_ENG") or d.get("DESIG"), "iucn": d.get("IUCN_CAT"), "iso3": iso,
                        "marine": str(d.get("MARINE") or ""), "area": round(area, 2), "year": d.get("STATUS_YR")}})
    with gzip.open(dest, "wt", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
    return len(feats)


class WDPA(Connector):
    source_id = "wdpa"
    switch = "nature_protected_fetch"
    fetch_every_days = 182

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"WDPA_([A-Z][a-z]{2})(\d{4})", f.name)
            if m:
                return datetime.strptime(f"{m[1]} {m[2]}", "%b %Y").strftime("%Y-%m")
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        last = None
        for mon, year in wdpa_months(date.today()):
            url = WDPA_URL.format(mon=mon, year=year)
            zpath = raw_dir / f"WDPA_{mon}{year}_Public_shp.zip"
            try:
                self.get(url, zpath, cached=False)
            except Exception as exc:  # noqa: BLE001 - the month's file may not be out yet
                last = exc
                zpath.unlink(missing_ok=True)
                continue
            try:
                n = wdpa_select([zpath], raw_dir / WDPA_FILE)
            finally:
                zpath.unlink(missing_ok=True)  # about 900 MB; only the selection is kept
            log.info("wdpa: %s protected areas kept", n)
            return url
        raise ConnectorError(f"wdpa: no monthly WDPA file could be downloaded ({last}); save one by hand (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        sel = raw_dir / WDPA_FILE
        if not sel.exists():
            zips = sorted(raw_dir.glob("WDPA*.zip"))
            if not zips:
                raise ConnectorError(f"wdpa: neither {WDPA_FILE} nor a WDPA shapefile zip in {raw_dir}")
            wdpa_select(zips, sel)
        from worldmodel_data.connectors.history import _bounds_and_centre

        with gzip.open(sel, "rt", encoding="utf-8") as f:
            feats = json.load(f)["features"]
        rows = []
        for ft in feats:
            p, g = ft["properties"], ft["geometry"]
            west, south, east, north, lat, lon = _bounds_and_centre(g)
            year = num(p.get("year"))
            rows.append((p.get("id"), p.get("name"), p.get("desig"), p.get("iucn"), p.get("iso3"), p.get("marine"),
                         num(p.get("area")), int(year) if year else None, lat, lon, west, south, east, north,
                         json.dumps(g, separators=(",", ":"))))
        con.execute("CREATE TABLE pa (wdpa_id VARCHAR, name VARCHAR, designation VARCHAR, iucn_cat VARCHAR, country_code VARCHAR, "
                    "marine VARCHAR, area_km2 DOUBLE, year INTEGER, lat DOUBLE, lon DOUBLE, west DOUBLE, south DOUBLE, "
                    "east DOUBLE, north DOUBLE, geojson VARCHAR)")
        con.executemany(f"INSERT INTO pa VALUES ({', '.join('?' * 15)})", rows)
        self.history_queries = {"protected_areas": "SELECT DISTINCT ON (wdpa_id) * FROM pa"}
        log.info("wdpa: %s protected areas", len(rows))
        return NO_ROWS


# ----------------------------------------------------------------------------- hand-checked lists
NATURE_KINDS = {"animal_disease": "animal_disease", "pest": "pest", "pollution": "pollution"}


class NatureCurated(Connector):
    source_id = "nature_curated"
    frozen = True
    stage_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return str(catalogue.nature().get("checked_until", fetched_at.year))

    def release_from_files(self, files: list[Path]) -> str | None:
        return self.default_release(datetime.now())

    def download(self, raw_dir: Path, release: str) -> str:
        (raw_dir / "nature_events.json").write_text(json.dumps(catalogue.nature().get("events", []), indent=1), encoding="utf-8")
        return "hand-checked lists in worldmodel_contract nature.yaml"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "nature_events.json"
        items = json.loads(p.read_text(encoding="utf-8")) if p.exists() else catalogue.nature().get("events", [])
        events = []
        for i, e in enumerate(items):
            start, prec = make_date(*[int(x) for x in str(e["start"]).split("-")])
            end = None
            if e.get("end"):
                parts = [int(x) for x in str(e["end"]).split("-")]
                end, _ = make_date(*parts)
                if len(parts) == 1:
                    end = date(parts[0], 12, 31)
            for ent in e["countries"]:
                events.append((ent, f"nature:{i}:{ent}", NATURE_KINDS[e["kind"]], e.get("subkind"), e["title"], start, end,
                               prec, None, None, None, None, None, e.get("place"), e.get("url"), e.get("detail")))
        self.events_query = stage_events(con, self.source_id, vintage, events, set())
        return NO_ROWS
