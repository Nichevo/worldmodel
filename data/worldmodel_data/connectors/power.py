"""Power plants and power lines for the map's Energy layers (Settings > Transport and
networks, "Power plants and power lines").

wri_gppd
    WRI's Global Power Plant Database (version 1.3, CC BY 4.0): about 35,000 plants with
    their fuel, capacity (MW), owner and year built, from the CSV on WRI's GitHub. Stored as
    the map layer power_plants. The database stopped being updated in 2021.
gridfinder
    gridfinder (Arderne et al. 2020, CC BY 4.0, Zenodo): high and medium voltage lines,
    those mapped in OpenStreetMap and those predicted from night lights and roads, as one
    GeoPackage of about 700 MB. Read once and kept as lines simplified to about 1 km and
    gathered by 1° square (geo_features layer power_lines), mapped lines rank 1, predicted 2.
osm_power_sites
    The grounds of power plants as OpenStreetMap maps them (power=plant areas, ODbL), with the
    kind of plant, read through Overpass one 20° square at a time (geo_features layer power_sites).
    A busy server (its queue full) is asked again after a wait, then the other public servers.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
import struct
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.networks import dp_line, lines_of, multiline
from worldmodel_data.connectors.tabular import num
from worldmodel_data.connectors.transport import stage_geo

log = logging.getLogger(__name__)

GPPD_URL = "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv"
GRIDFINDER_URL = "https://zenodo.org/records/3628142/files/grid.gpkg?download=1"
LINE_TOL = 0.01  # degrees (about 1 km) when simplifying power lines
FUELS = {"Hydro", "Geothermal", "Wind", "Solar", "Nuclear", "Coal", "Gas", "Oil", "Biomass", "Waste", "Storage", "Wave and Tidal",
         "Cogeneration", "Petcoke", "Other"}


def plant_features(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lat, lon = num(r.get("latitude")), num(r.get("longitude"))
            if lat is None or lon is None:
                continue
            fuel = (r.get("primary_fuel") or "Other").strip()
            year = num(r.get("commissioning_year"))
            out.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                "name": r.get("name"), "fuel": fuel if fuel in FUELS else "Other", "mw": round(num(r.get("capacity_mw")) or 0, 1) or None,
                "year": int(year) if year else None, "owner": (r.get("owner") or "").strip()[:80] or None, "country": r.get("country"),
            }))
    out.sort(key=lambda f: -(f["properties"].get("mw") or 0))
    return out


class WRIPowerPlants(Connector):
    source_id = "wri_gppd"
    switch = "power_fetch"
    fetch_every_days = 180

    def default_release(self, fetched_at: datetime) -> str:
        return "1.3.0"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "1.3.0"

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(GPPD_URL, raw_dir / "global_power_plant_database.csv")
        return GPPD_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv"))
        feats = plant_features(files[0]) if files else []
        if not feats:
            raise ConnectorError(f"wri_gppd: no power plants read in {raw_dir}")
        self.layers = [{"layer_id": "power_plants", "name": "Power plants", "kind": "point", "feature_count": len(feats),
                        "description": "Power plants sized by capacity and coloured by fuel (WRI Global Power Plant Database 1.3, 2021).",
                        "geojson": collection(feats)}]
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- GeoPackage lines
def _gpkg_wkb(blob: bytes) -> bytes:
    """The WKB inside a GeoPackage geometry blob (after its header and envelope)."""
    if blob[:2] != b"GP":
        return blob
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((flags >> 1) & 0x07, 0)
    return blob[8 + env:]


def _wkb_lines(b: bytes) -> list[list[list[float]]]:
    """Lines from a WKB LineString or MultiLineString (2D, or with Z/M dropped)."""
    out: list = []

    def read(i: int) -> int:
        order = "<" if b[i] == 1 else ">"
        (t,) = struct.unpack_from(order + "I", b, i + 1)
        dims = 3 if (t // 1000) in (1, 2) or t & 0x80000000 or t & 0x40000000 else 4 if t // 1000 == 3 else 2
        base = (t & 0xFFFF) % 1000
        i += 5
        if base == 2:
            (n,) = struct.unpack_from(order + "I", b, i)
            i += 4
            pts = struct.unpack_from(order + "d" * (n * dims), b, i)
            out.append([[pts[k], pts[k + 1]] for k in range(0, len(pts), dims)])
            return i + 8 * n * dims
        if base in (5, 7):  # MultiLineString, GeometryCollection
            (n,) = struct.unpack_from(order + "I", b, i)
            i += 4
            for _ in range(n):
                i = read(i)
            return i
        raise ValueError(f"geometry type {t}")
    read(0)
    return out


def grid_rows(path: Path, tol: float = LINE_TOL) -> list[tuple]:
    """geo_features rows: power lines simplified and gathered by 1° square and by mapped or predicted."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchall()
        if not tables:
            raise ConnectorError(f"gridfinder: no geometry table in {path.name}")
        table, gcol = tables[0]
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
        src = "source" if "source" in cols else None
        squares: dict[tuple[int, int, int], list] = defaultdict(list)
        for g, s in con.execute(f'SELECT "{gcol}", {f"{src}" if src else "NULL"} FROM "{table}"'):
            if not g:
                continue
            rank = 1 if s and "osm" in str(s).lower() else 2
            try:
                lines = _wkb_lines(_gpkg_wkb(bytes(g)))
            except (ValueError, struct.error):
                continue
            for ln in lines:
                if len(ln) < 2:
                    continue
                d = dp_line(ln, tol, 3)
                if not d:
                    continue
                squares[(int(d[0][0] // 1), int(d[0][1] // 1), rank)].append(d)
    finally:
        con.close()
    rows = []
    for (x, y, rank), lines in squares.items():
        rows.append(("power_lines", f"{x}_{y}_{rank}", "Power lines (mapped)" if rank == 1 else "Power lines (predicted)", rank,
                     {"rank": rank}, [], multiline(lines)))
    return rows


class Gridfinder(Connector):
    source_id = "gridfinder"
    switch = "power_fetch"
    fetch_every_days = 3650  # a 2020 release that is not updated: read once
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return "1.1.1"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "1.1.1"

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(GRIDFINDER_URL, raw_dir / "grid.gpkg")
        return GRIDFINDER_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.gpkg"))
        if not files:
            raise ConnectorError(f"gridfinder: grid.gpkg missing from {raw_dir}")
        rows = grid_rows(files[0])
        if not rows:
            raise ConnectorError(f"gridfinder: no power lines read in {files[0].name}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("gridfinder: %s squares of power lines", len(rows))
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- plant grounds (OpenStreetMap)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# The main Overpass server turns queries away when its queue is full ("at capacity", 429/502/503/504);
# then each square is asked again after a wait, and of the other public Overpass servers in turn.
OVERPASS_URLS = [OVERPASS_URL, "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
BUSY_WAITS = (30,)      # seconds before asking a busy server once more, then the next server
BOX_DEG = 10            # the world read in 10° squares (504 over land and sea); small queries get a slot sooner
BOXES_A_RUN = 200       # at most this many squares in one refresh...
RUN_MINUTES = 20        # ...and no more than this long; the rest the next time, starting where this one stopped
ASK_TIMEOUT = 240       # seconds to wait for one answer (the query itself may run 180)
SITE_TOL = 0.00003      # degrees (about 3 m) when simplifying an outline
SITE_MIN_M2 = 1000      # smaller grounds (a plant that is one building) are left out
# The squares read first: New Zealand, Australia, the United Kingdom, the United States
FIRST = [(174, -41), (172, -44), (170, -46), (176, -38), (145, -37), (151, -33), (115, -32), (-1, 52), (-100, 40), (-80, 35)]
# OpenStreetMap's plant:source values as the power plant layer's fuels
OSM_FUEL = {
    "coal": "Coal", "lignite": "Coal", "gas": "Gas", "natural_gas": "Gas", "lng": "Gas", "biogas": "Biomass", "oil": "Oil",
    "diesel": "Oil", "gasoline": "Oil", "fuel_oil": "Oil", "nuclear": "Nuclear", "hydro": "Hydro", "water": "Hydro",
    "wind": "Wind", "solar": "Solar", "photovoltaic": "Solar", "biomass": "Biomass", "biofuel": "Biomass", "wood": "Biomass",
    "waste": "Waste", "geothermal": "Geothermal", "tidal": "Wave and Tidal", "wave": "Wave and Tidal", "battery": "Storage",
}


def site_boxes() -> list[tuple[int, int]]:
    """The squares' south-west corners, the key countries' squares first."""
    boxes = [(w, s) for s in range(-60, 80, BOX_DEG) for w in range(-180, 180, BOX_DEG)]
    first = []
    for lon, lat in FIRST:
        b = (int((lon + 180) // BOX_DEG) * BOX_DEG - 180, int((lat + 60) // BOX_DEG) * BOX_DEG - 60)
        if b not in first:
            first.append(b)
    return first + [b for b in boxes if b not in first]


def site_query(w: float, s: float, size: float) -> str:
    return (f'[out:json][timeout:180][maxsize:268435456];(way["power"="plant"]({s},{w},{s + size},{w + size});'
            f'relation["power"="plant"]({s},{w},{s + size},{w + size}););out body geom;')  # body: a relation's members too


def osm_fuel(tags: dict) -> str:
    raw = str(tags.get("plant:source") or tags.get("generator:source") or "").lower()
    for part in re.split(r"[;,]", raw):
        f = OSM_FUEL.get(part.strip())
        if f:
            return f
    if tags.get("plant:method") == "photovoltaic":
        return "Solar"
    return "Other"


def osm_mw(tags: dict) -> float | None:
    """'850 MW', '1.2 GW', '500 kW', '850' (MW): megawatts."""
    m = re.match(r"\s*([\d.]+(?:,\d{3})*)\s*([kKmMgG]?)\s*[wW]?[pP]?", str(tags.get("plant:output:electricity") or ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(2).lower()
    v = v / 1000 if unit == "k" else v * 1000 if unit == "g" else v
    return round(v, 1) if v > 0 else None


def _join_rings(parts: list[list[list[float]]]) -> list[list[list[float]]]:
    """Ways joined end to end into closed rings (a relation's outer or inner members)."""
    rings, open_ = [], []
    for p in parts:
        if len(p) >= 4 and p[0] == p[-1]:
            rings.append(p)
        elif len(p) >= 2:
            open_.append(list(p))
    while open_:
        cur = open_.pop()
        grew = True
        while grew and cur[0] != cur[-1]:
            grew = False
            for i, p in enumerate(open_):
                if p[0] == cur[-1]:
                    cur += p[1:]
                elif p[-1] == cur[-1]:
                    cur += p[::-1][1:]
                elif p[-1] == cur[0]:
                    cur = p[:-1] + cur
                elif p[0] == cur[0]:
                    cur = p[::-1][:-1] + cur
                else:
                    continue
                open_.pop(i)
                grew = True
                break
        if len(cur) >= 4 and cur[0] == cur[-1]:
            rings.append(cur)
    return rings


def _hull(pts: list[list[float]]) -> list[list[float]]:
    """The convex hull of points as a closed ring (monotone chain)."""
    p = sorted(set(map(tuple, pts)))
    if len(p) < 3:
        return []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    ring = [list(q) for q in lower[:-1] + upper[:-1]]
    return ring + [ring[0]] if len(ring) >= 3 else []


def _inside(pt: list[float], ring: list[list[float]]) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def ring_m2(ring: list[list[float]]) -> float:
    """A ring's area in square metres (flat, scaled by latitude: fine at a plant's size)."""
    if len(ring) < 4:
        return 0.0
    lat = sum(p[1] for p in ring) / len(ring)
    kx, ky = 111_320 * np.cos(np.radians(lat)), 110_540
    a = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))
    return abs(a) / 2 * kx * ky


def _simple_ring(ring: list[list[float]]) -> list[list[float]]:
    pts = dp_line(ring[:-1] if ring[0] == ring[-1] else ring, SITE_TOL, places=5)  # open: the ends are the same point
    if len(pts) < 3:
        return []
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts if len(pts) >= 4 else []


def site_rows(body: dict) -> list[tuple]:
    """geo_features rows (layer power_sites) from an Overpass answer: each plant's grounds with its
    fuel, capacity and operator; rank 1 for a square kilometre and more, 2 for 5 ha, else 3."""
    rows = []
    for el in body.get("elements") or []:
        t = el.get("tags") or {}
        pt = lambda g: [[round(p["lon"], 6), round(p["lat"], 6)] for p in g if "lon" in p]  # noqa: E731
        if el.get("type") == "way":
            outers, inners = _join_rings([pt(el.get("geometry") or [])]), []
        elif el.get("type") == "relation":
            mem = [m for m in el.get("members") or [] if m.get("type") == "way" and m.get("geometry")]
            if t.get("type") == "multipolygon":  # outer and inner rings, each perhaps drawn as several ways
                outers = _join_rings([pt(m["geometry"]) for m in mem if m.get("role") in ("outer", "")])
                inners = _join_rings([pt(m["geometry"]) for m in mem if m.get("role") == "inner"])
            else:  # a site (a hydro scheme: powerhouse, dam, switchyard...): each closed area it holds
                outers = _join_rings([g for g in (pt(m["geometry"]) for m in mem) if len(g) >= 4 and g[0] == g[-1]])
                inners = []
                dots = [[round(m["lon"], 6), round(m["lat"], 6)] for m in el.get("members") or []
                        if m.get("type") == "node" and "lon" in m]
                if not outers and len(dots) >= 3:  # a wind farm drawn as its turbines: the ground they stand on
                    hull = _hull(dots)
                    outers = [hull] if len(hull) >= 4 else []
        else:
            continue
        polys = []
        for o in outers:
            so = _simple_ring(o)
            if not so:
                continue
            holes = [h for h in (_simple_ring(i) for i in inners if _inside(i[0], o)) if h]
            polys.append([so, *holes])
        area = sum(ring_m2(p[0]) - sum(ring_m2(h) for h in p[1:]) for p in polys)
        if not polys or area < SITE_MIN_M2:
            continue
        geom = {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}
        name = t.get("name:en") or t.get("name")
        fuel = osm_fuel(t)
        rank = 1 if area >= 1e6 else 2 if area >= 5e4 else 3
        props = {"name": name, "fuel": fuel, "mw": osm_mw(t), "operator": (t.get("operator") or "")[:80] or None,
                 "ha": round(area / 1e4, 1), "osm": f"{el['type']}/{el['id']}"}
        rows.append(("power_sites", f"{el['type'][0]}{el['id']}", name or f"{fuel} power plant", rank, props, [], geom))
    return rows


class OSMPowerSites(Connector):
    """The grounds of power plants as mapped in OpenStreetMap (power=plant areas), each with its
    kind of plant (plant:source), for the map's power plant grounds. Read through Overpass, one
    20° square at a time, ten seconds apart, 40 squares a refresh (the world in about four
    monthly refreshes, then each square again after a year), stopping at the first refusal."""

    source_id = "osm_power_sites"
    switch = "power_sites_fetch"
    fetch_every_days = 30
    keeps_files = True
    gap = 10.0  # Overpass is shared by everyone: one query at a time, well apart
    stage_version = 2  # 2: site relations' areas
    fetch_version = 3  # 2: busy servers asked again, then the other public Overpass servers; relations with their members
    # 3: 10° squares with lighter queries, 20 minutes a refresh at most, progress kept after each square
    _server = 0  # the Overpass server that answered last

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        prev = self.last_vintage_dir(raw_dir)
        done: dict[str, str] = {}
        if prev and (prev / "fetched.json").exists():
            try:
                done = json.loads((prev / "fetched.json").read_text(encoding="utf-8"))
            except ValueError:
                done = {}
        today = date.today()
        due = []
        for w, s in site_boxes():
            k = f"{BOX_DEG}:{w}_{s}"
            last = done.get(k)
            if last and (today - datetime.strptime(last, "%Y-%m-%d").date()).days < 330:
                continue
            due.append((w, s))
        got = 0
        self._until = time.monotonic() + RUN_MINUTES * 60
        for w, s in due[:BOXES_A_RUN]:
            if time.monotonic() > self._until:
                log.info("osm_power_sites: %s minutes used; the rest waits for the next refresh", RUN_MINUTES)
                break
            ok = self._read_box(raw_dir, w, s, BOX_DEG)
            if ok is None:
                break  # refused or out of time: the rest waits for the next refresh
            done[f"{BOX_DEG}:{w}_{s}"] = today.isoformat()
            got += 1
            # kept after each square, so a refresh that is stopped part way resumes where it was
            (raw_dir / "fetched.json").write_text(json.dumps(done, sort_keys=True), encoding="utf-8")
        (raw_dir / "fetched.json").write_text(json.dumps(done, sort_keys=True), encoding="utf-8")
        log.info("osm_power_sites: %s of %s squares due read this time", got, len(due))
        if not got and not any(raw_dir.glob("osm_power_*.json")) and not (prev and any(prev.glob("osm_power_*.json"))):
            raise ConnectorError("osm_power_sites: the Overpass servers were all busy or refused; nothing read yet, "
                                 "the next refresh tries again")
        return OVERPASS_URL

    def _ask(self, query: str):
        """An Overpass answer to a query: the server that answered last first, a busy one asked
        again after a wait, then the next. None when none would answer."""
        order = OVERPASS_URLS[self._server:] + OVERPASS_URLS[:self._server]
        for url in order:
            for wait in (0, *BUSY_WAITS):
                if time.monotonic() + wait > getattr(self, "_until", float("inf")):
                    return None  # out of time for this refresh
                if wait:
                    time.sleep(wait)
                try:
                    r = self.client.post(url, data={"data": query}, timeout=ASK_TIMEOUT)
                except Exception as exc:  # noqa: BLE001
                    log.warning("osm_power_sites: %s did not answer (%s)", url.split("/")[2], exc)
                    break  # unreachable: try the next server
                busy = r.status_code in (429, 502, 503, 504) or b"at capacity" in r.content[:600]
                if not busy:
                    self._server = OVERPASS_URLS.index(url)
                    return r
                log.info("osm_power_sites: %s is busy (%s)%s", url.split("/")[2], r.status_code,
                         "; asking again shortly" if wait != BUSY_WAITS[-1] else "")
        return None

    def _read_box(self, raw_dir: Path, w: float, s: float, size: float, depth: int = 0) -> bool | None:
        """One square into osm_power_<w>_<s>_<size>.json; a square too big to answer in time is
        read as four smaller ones. None: no Overpass server would answer, stop."""
        r = self._ask(site_query(w, s, size))
        if r is None:
            log.warning("osm_power_sites: no Overpass server would answer for the square at %s,%s; "
                        "the rest waits for the next refresh", w, s)
            return None
        time.sleep(self.gap)
        tail = r.content[-2000:]
        too_big = r.status_code == 200 and b'"remark"' in tail and (b"runtime error" in tail or b"Timeout" in tail)
        if too_big and depth < 2:
            half = size / 2
            for dw, ds in ((0, 0), (half, 0), (0, half), (half, half)):
                if self._read_box(raw_dir, w + dw, s + ds, half, depth + 1) is None:
                    return None
            return True
        if r.status_code != 200 or too_big or not r.content.lstrip().startswith(b"{"):
            log.warning("osm_power_sites: Overpass answered %s for the square at %s,%s; stopping until the next refresh",
                        r.status_code, w, s)
            return None
        (raw_dir / f"osm_power_{w:g}_{s:g}_{size:g}.json").write_bytes(r.content)
        return True

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, seen = [], set()
        files = sorted(raw_dir.glob("osm_power_*.json"))
        for f in files:
            try:
                body = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                log.warning("osm_power_sites: %s is not a whole answer; skipped", f.name)
                continue
            for row in site_rows(body):
                if row[1] not in seen:  # a plant across two squares comes twice
                    seen.add(row[1])
                    rows.append(row)
        if not files:
            raise ConnectorError(f"osm_power_sites: no Overpass answers (osm_power_*.json) in {raw_dir}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("osm_power_sites: %s plant grounds from %s squares", len(rows), len(files))
        return EMPTY_OBSERVATIONS
