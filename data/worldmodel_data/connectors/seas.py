"""Borders out at sea for the map: countries' economic zones and the airspace each country's
air traffic control covers.

marine_regions
    Marine Regions' Maritime Boundaries (v12, Flanders Marine Institute, CC BY 4.0): the
    lines between countries' exclusive economic zones and their 200 nautical mile outer
    limits, from the Marine Regions web feature service, simplified to about 2 km and kept
    as the map layer eez_lines. The zones' own list gives each country's sea area
    (eez_area_km2, its own zones plus its territories'). If the service refuses, save the
    two GeoJSON files in var\\manual\\marine_regions.
vatsim_airspace
    Flight information region outlines from the VATSIM VAT-Spy data project (CC BY-SA
    4.0), drawn from the official charts for flight simulator controllers: each region
    (map layer airspace, rank 2) and, joined up, each country's airspace (rank 1). Good for
    seeing who covers what; not for navigation.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb
from worldmodel_contract import catalogue

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import country_by_name
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.networks import dp_line, lines_of, multiline
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, num
from worldmodel_data.connectors.transport import stage_geo

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- economic zones
MR_WFS = ("https://geo.vliz.be/geoserver/MarineRegions/wfs?service=WFS&version=1.0.0&request=GetFeature"
          "&outputFormat=application/json&typeName=")
MR_LINES = MR_WFS + "MarineRegions:eez_boundaries"
MR_ZONES = MR_WFS + "MarineRegions:eez&propertyName=mrgid,geoname,pol_type,iso_sov1,iso_ter1,territory1,sovereign1,area_km2"
LINES_FILE, ZONES_FILE = "eez_boundaries.geojson", "eez_zones.geojson"
EEZ_TOL = 0.02  # degrees, about 2 km


def _features(path: Path) -> list[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return d.get("features") or [] if isinstance(d, dict) else []


def eez_line_rows(features: list[dict]) -> list[tuple]:
    """geo_features rows (layer eez_lines): each boundary line, simplified."""
    rows = []
    for i, ft in enumerate(features):
        p = ft.get("properties") or {}
        lines = [dp_line(ln, EEZ_TOL, 3) for ln in lines_of(ft.get("geometry") or {})]
        geom = multiline([ln for ln in lines if ln])
        if not geom:
            continue
        kind = str(p.get("line_type") or "").strip()
        outer = "200" in kind
        countries = [c for c in (country_by_name(p.get("sovereign1")), country_by_name(p.get("sovereign2"))) if c]
        rows.append(("eez_lines", str(p.get("line_id") or i), p.get("line_name") or kind or "Maritime boundary", 1,
                     {"type": kind, "outer": outer, "eez1": p.get("eez1"), "eez2": p.get("eez2"),
                      "km": round(num(p.get("length_km")) or 0) or None}, countries, geom))
    return rows


def eez_areas(features: list[dict]) -> dict[str, float]:
    """Each sovereign country's sea area in km²: its 200 NM zones, its territories' included
    (joint regimes and overlapping claims left out)."""
    out: dict[str, float] = defaultdict(float)
    for ft in features:
        p = ft.get("properties") or {}
        if str(p.get("pol_type") or "").replace(" ", "").upper() != "200NM":
            continue
        area = num(p.get("area_km2"))
        iso = str(p.get("iso_sov1") or "").strip().upper()
        ent = entity_for("iso3", iso) if iso else None
        ent = ent or country_by_name(p.get("sovereign1"))
        if area and ent:
            out[ent] += area
    return dict(out)


class MarineRegionsEEZ(Connector):
    source_id = "marine_regions"
    switch = "sea_borders_fetch"
    fetch_every_days = 180  # Marine Regions updates the zones every year or two

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(MR_LINES, raw_dir / LINES_FILE)
        self.get(MR_ZONES, raw_dir / ZONES_FILE)
        return "https://www.marineregions.org (web feature service)"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(f for f in raw_dir.iterdir() if f.suffix.lower() in (".json", ".geojson"))
        lines, zones = [], []
        for f in files:  # files saved by hand may have other names: told apart by their fields
            feats = _features(f)
            if not feats:
                continue
            p = feats[0].get("properties") or {}
            if "line_type" in p or "line_name" in p:
                lines += feats
            elif "pol_type" in p or "area_km2" in p:
                zones += feats
        rows = eez_line_rows(lines)
        if not rows and not zones:
            raise ConnectorError(f"marine_regions: no boundary lines or zones read from {raw_dir}")
        if rows:
            self.history_queries = {"geo_features": stage_geo(con, rows)}
        year = int(release[:4])
        obs = Rows()
        for ent, area in eez_areas(zones).items():
            obs.add("iso3", ent, "eez_area_km2", year, round(area))
        self.listed_indicators = [indicator(
            "eez_area_km2", "Sea area (exclusive economic zone)",
            "The sea a country has the sole right to fish and mine, out to 200 nautical miles from its coasts (and its "
            "territories'), less where neighbours' zones meet. Marine Regions.", "km²", "land", self.source_id,
            "eez:200NM:area_km2", decimals=0, aggregation={"method": "sum"})]
        log.info("marine_regions: %s boundary lines, sea areas for %s countries", len(rows), len(obs))
        return obs.stage(con, self.source_id, vintage) if len(obs) else EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- airspace
VATSIM = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/"
VATSIM_FILES = ("Boundaries.geojson", "VATSpy.dat")
AIR_TOL = 0.02
# VAT-Spy's country names that are not country names, and boundaries it gives no country.
VATSIM_COUNTRIES = {"Bosnia-Herzegovina": "BIH", "Serbia-Montenegro": "SRB", "Fiji-Tonga": "FJI", "Surinam": "SUR",
                    "French Guyana": "FRA", "Puerto Rico, USA": "USA", "Dutch Caribbean": "NLD", "Hong Kong SAR": "HKG"}
VATSIM_IDS = {"UTDD": "TJK", "UTAA": "TKM", "UTAK": "TKM", "UTAT": "TKM", "UTAV": "TKM"}


def vatspy(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """From VATSpy.dat: ICAO prefix -> country name, and boundary id -> region name."""
    prefixes, names, section, own = {}, {}, "", set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("["):
            section = line
            continue
        parts = line.split("|")
        if section == "[Countries]" and len(parts) >= 2 and parts[1]:
            prefixes.setdefault(parts[1].strip(), parts[0].strip())
        elif section == "[FIRs]" and len(parts) >= 4:
            boundary = parts[3].strip() or parts[0].strip()
            name = re.sub(r"(\s+[\d.*()]+)+$", "", parts[1].strip())  # "Brisbane (Arafura) 133.7* (125.7)": no radio frequencies
            if boundary and name and (boundary not in names or parts[0].strip() == boundary and boundary not in own):
                names[boundary] = name
                if parts[0].strip() == boundary:
                    own.add(boundary)  # the region's own entry names it, not a neighbour's that uses its outline
    return prefixes, names


def _country_of(fid: str, prefixes: dict[str, str]) -> str | None:
    base = fid.split("-")[0]
    if base in VATSIM_IDS:
        return VATSIM_IDS[base]
    name = prefixes.get(base[:2]) or prefixes.get(base[:1])
    if not name:
        return None
    return VATSIM_COUNTRIES.get(name) or country_by_name(name)


def _rings(geom) -> list[list[list[float]]]:
    """A shapely (multi)polygon as its rings, simplified."""
    polys = getattr(geom, "geoms", [geom])
    out = []
    for p in polys:
        if p.is_empty or not hasattr(p, "exterior"):
            continue
        for ring in [p.exterior, *p.interiors]:
            r = dp_line([list(c[:2]) for c in ring.coords], AIR_TOL, 3)
            if len(r) >= 4:
                if r[0] != r[-1]:
                    r.append(r[0])
                out.append(r)
    return out


def _polygon(geom) -> dict | None:
    polys = []
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty or not hasattr(p, "exterior"):
            continue
        rings = _rings(p)
        if rings:
            polys.append(rings)
    if not polys:
        return None
    return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}


def airspace_rows(features: list[dict], prefixes: dict[str, str], names: dict[str, str]) -> list[tuple]:
    """geo_features rows (layer airspace): each region (rank 2) and each country's whole airspace (rank 1)."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    rows, by_country, regions = [], defaultdict(list), defaultdict(list)
    for ft in features:
        p = ft.get("properties") or {}
        fid = str(p.get("id") or "").strip()
        try:
            g = shape(ft.get("geometry"))
        except Exception:  # noqa: BLE001 - a broken outline is skipped
            continue
        if not fid or g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        country = _country_of(fid, prefixes)
        regions[fid].append((g, country, p))
        if country:
            by_country[country].append(g)
    for fid, parts in regions.items():
        g = unary_union([x for x, _, _ in parts]) if len(parts) > 1 else parts[0][0]
        country, p = parts[0][1], parts[0][2]
        geom = _polygon(g)
        if geom:
            rows.append(("airspace", f"fir:{fid}", names.get(fid) or fid, 2,
                         {"icao": fid, "country": country, "oceanic": str(p.get("oceanic")) == "1", "kind": "region"},
                         [country] if country else [], geom))
    for country, geoms in by_country.items():
        geom = _polygon(unary_union(geoms))
        if geom:
            firs = sorted({names.get(f) or f for f, parts in regions.items() if parts[0][1] == country})
            ent = catalogue.entities().get(country)
            rows.append(("airspace", f"country:{country}", f"{ent.short_name if ent else country} airspace", 1, {"country": country, "kind": "country", "firs": firs[:30]},
                         [country], geom))
    return rows


class VatsimAirspace(Connector):
    source_id = "vatsim_airspace"
    switch = "sea_borders_fetch"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for f in VATSIM_FILES:
            self.get(VATSIM + f, raw_dir / f)
        return VATSIM

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        geo = next((f for f in raw_dir.iterdir() if f.suffix.lower() in (".geojson", ".json")), None)
        if not geo:
            raise ConnectorError(f"vatsim_airspace: Boundaries.geojson missing from {raw_dir}")
        dat = next((f for f in raw_dir.iterdir() if f.suffix.lower() == ".dat"), None)
        prefixes, names = vatspy(dat.read_text(encoding="utf-8", errors="replace")) if dat else ({}, {})
        rows = airspace_rows(_features(geo), prefixes, names)
        if not rows:
            raise ConnectorError(f"vatsim_airspace: no outlines read from {geo.name}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("vatsim_airspace: %s regions, %s countries", sum(r[3] == 2 for r in rows), sum(r[3] == 1 for r in rows))
        return EMPTY_OBSERVATIONS
