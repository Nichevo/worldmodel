"""Rivers, basins, waterways, undersea cables, pipelines and LNG terminals: lines and areas
for the map's Transport and trade and Earth layers, stored in geo_features (one row a
feature with its box, so the API sends only what is in view) and, for small point sets,
as ordinary map layers.

- hydrosheds: HydroRIVERS rivers (flow order 6 or less, 1 m3/s and up; in New Zealand order
  7 too, 0.1 m3/s and up), named where they run along one of Natural Earth's named rivers
  (the world file plus its Europe, North America and Australia supplements); whole river
  basins from HydroBASINS level 4 (joined by their main basin), each basin's country split,
  outflow and name.
- waterways: inland waterways ships use: the US National Waterway Network, Europe's
  CEMT-classed waterways and about 30 big rivers from OpenStreetMap (Overpass).
- submarine_cables: TeleGeography's Submarine Cable Map (cables, landing points, and
  each cable's owners, year and landing countries, read a few at a time and kept).
- gem_infrastructure: Global Energy Monitor's gas and oil pipeline and LNG terminal
  trackers, saved by hand (the files sit behind a short form).
- ne_railways: Natural Earth's railroads (the world's main and through lines, intercity and
  freight), gathered by 1° square.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import re
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import numpy as np

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.tabular import key, num
from worldmodel_data.connectors.transport import header_rows, iso3_of, read_table, stage_geo

log = logging.getLogger(__name__)
NO_ROWS = EMPTY_OBSERVATIONS

NE_RIVERS_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_rivers_lake_centerlines.geojson"
NE_RIVERS_FILE = "ne_10m_rivers_lake_centerlines.geojson"
# Natural Earth's regional supplements: many more named rivers (scalerank 10 to 12)
NE_RIVER_EXTRAS = tuple(f"ne_10m_rivers_{r}.geojson" for r in ("europe", "north_america", "australia"))
NE_GEOJSON = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
GRID_CELL = 0.1  # degrees, for country and basin grids


# ----------------------------------------------------------------------------- shared geometry
def dp_line(points, tol: float, places: int = 3) -> list[list[float]]:
    """A line simplified (Douglas-Peucker) and rounded, repeats dropped."""
    from worldmodel_data.connectors.history import _dp

    a = np.asarray(points, dtype=float)
    if a.ndim != 2 or len(a) < 2:
        return []
    a = a[:, :2]
    s = np.round(_dp(a, tol) if tol else a, places)
    s = s[np.r_[True, np.any(np.diff(s, axis=0) != 0, axis=1)]]
    return s.tolist() if len(s) >= 2 else []


def chain(lines: list[list[list[float]]]) -> list[list[list[float]]]:
    """Join lines where one ends exactly where the next starts (river reaches into rivers)."""
    starts = defaultdict(list)
    for i, ln in enumerate(lines):
        starts[tuple(ln[0])].append(i)
    ends = Counter(tuple(ln[-1]) for ln in lines)
    used = [False] * len(lines)
    out = []
    # Begin at lines nothing flows into, so each chain is followed from its top.
    order = sorted(range(len(lines)), key=lambda i: ends.get(tuple(lines[i][0]), 0))
    for i in order:
        if used[i]:
            continue
        used[i] = True
        cur = list(lines[i])
        while True:
            nxt = [j for j in starts.get(tuple(cur[-1]), []) if not used[j]]
            if len(nxt) != 1 or ends[tuple(cur[-1])] != 1:
                break
            used[nxt[0]] = True
            cur.extend(lines[nxt[0]][1:])
        out.append(cur)
    return out


def lines_of(geom: dict) -> list[list[list[float]]]:
    if not geom:
        return []
    if geom.get("type") == "LineString":
        return [geom["coordinates"]]
    if geom.get("type") == "MultiLineString":
        return list(geom["coordinates"])
    if geom.get("type") == "GeometryCollection":
        return [ln for g in geom.get("geometries") or [] for ln in lines_of(g)]
    return []


def multiline(lines: list) -> dict | None:
    lines = [ln for ln in lines if len(ln) >= 2]
    if not lines:
        return None
    return {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}


def parse_wkt(text: str) -> dict | None:
    """LINESTRING / MULTILINESTRING / POINT WKT (as GEM's trackers give routes) as GeoJSON."""
    s = str(text or "").strip()
    m = re.match(r"^(MULTILINESTRING|LINESTRING|POINT|MULTIPOINT)\s*(?:Z|M|ZM)?\s*\((.*)\)\s*$", s, re.I | re.S)
    if not m:
        return None
    kind, body = m[1].upper(), m[2]

    def pts(t: str) -> list[list[float]]:
        out = []
        for pair in t.split(","):
            v = pair.strip().strip("()").split()
            if len(v) >= 2:
                try:
                    out.append([float(v[0]), float(v[1])])
                except ValueError:
                    return []
        return out

    if kind == "POINT":
        p = pts(body)
        return {"type": "Point", "coordinates": p[0]} if p else None
    if kind == "LINESTRING":
        return multiline([pts(body)])
    parts = re.findall(r"\(([^()]*)\)", body)
    if kind == "MULTIPOINT":
        p = pts(",".join(parts) if parts else body)
        return {"type": "MultiPoint", "coordinates": p} if p else None
    return multiline([pts(x) for x in parts])


class Grids:
    """Country numbers on a 0.1 degree grid (from Natural Earth countries), to say which
    countries a line passes through or a basin covers."""

    def __init__(self, countries_geojson: Path, cell: float = GRID_CELL):
        from worldmodel_data.connectors.internet import country_grid

        self.cell = cell
        self.grid, self.codes = country_grid(countries_geojson, cell, reach=2)

    def rc(self, lon: float, lat: float) -> tuple[int, int]:
        r = min(self.grid.shape[0] - 1, max(0, int((90 - lat) / self.cell)))
        c = int(((lon + 180) % 360) / self.cell) % self.grid.shape[1]
        return r, c

    def at(self, lon: float, lat: float) -> str | None:
        n = int(self.grid[self.rc(lon, lat)])
        return self.codes[n - 1] if n else None

    def along(self, lines, every: int = 1) -> list[str]:
        """Countries a set of lines passes through, most points first."""
        seen = Counter()
        for ln in lines:
            for p in ln[::max(1, every)]:
                c = self.at(p[0], p[1])
                if c:
                    seen[c] += 1
        return [c for c, _ in seen.most_common()]


def countries_file(raw_dir: Path, connector: Connector) -> Path | None:
    """Natural Earth's countries beside the raw files (fetched with them), or an earlier copy."""
    from worldmodel_data.connectors.internet import COUNTRIES_FILE

    p = raw_dir / COUNTRIES_FILE
    if p.exists():
        return p
    return connector.earlier_copy(raw_dir, COUNTRIES_FILE)


def get_countries(raw_dir: Path, connector: Connector) -> None:
    from worldmodel_data.connectors.internet import COUNTRIES_FILE, COUNTRIES_URL

    connector.get(COUNTRIES_URL, raw_dir / COUNTRIES_FILE)


def entity_ids(codes: list[str]) -> list[str]:
    return [e for e in (iso3_of(c) for c in codes) if e]


# ----------------------------------------------------------------------------- HydroSHEDS
HYDRO_REGIONS = ("af", "ar", "as", "au", "eu", "gr", "na", "sa", "si")
HYRIV_URL = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{reg}_shp.zip"
HYBAS_URL = "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_{reg}_lev04_v1c.zip"
RIVER_MAX_ORDER = 6      # flow order 6 is 1 to 10 m3/s, 5 is 10 to 100; 1 is the Amazon
RIVER_NZ_ORDER = 7       # New Zealand keeps order 7 too (0.1 to 1 m3/s) ...
RIVER_NZ_BOX = (165.5, -47.8, 179.0, -34.0)  # ... inside this box (west, south, east, north)
RIVER_TOL = 0.01         # degrees (about 1 km)
RIVER_CELL = {4: 6.0, 5: 3.0, 6: 1.5, 7: 1.5}  # smaller rivers are stored by square (degrees), so a
                                                # map window gets only the stretches near it
RIVERS_FILE = "rivers1_{reg}.jsonl.gz"  # rivers_{reg} (order 5 and up only) before; kept as a fallback
BASIN_TOL = 0.03
BASIN_MIN_KM2 = 20000    # whole basins smaller than this are left out ...
BASIN_ALL_IN = {"NZL"}   # ... except where they are mostly in these countries (down to 500 km2)


def _shapes(zp: Path):
    """(fields dict, geo_interface) for every shape in the shapefile(s) inside a zip."""
    import shapefile  # pyshp

    with zipfile.ZipFile(zp) as z:
        for name in z.namelist():
            if not name.lower().endswith(".shp"):
                continue
            stem = name[:-4]
            r = shapefile.Reader(shp=io.BytesIO(z.read(stem + ".shp")), shx=io.BytesIO(z.read(stem + ".shx")),
                                 dbf=io.BytesIO(z.read(stem + ".dbf")), encoding="utf-8", encodingErrors="replace")
            fields = [f[0] for f in r.fields[1:]]
            for sr in r.iterShapeRecords():
                yield dict(zip(fields, sr.record)), sr.shape.__geo_interface__


def in_nz(pt) -> bool:
    w, s, e, n = RIVER_NZ_BOX
    return w <= pt[0] <= e and s <= pt[1] <= n


def rivers_select(zp: Path, dest: Path, max_order: int = RIVER_MAX_ORDER) -> int:
    """Keep the reaches of flow order max_order or less (in New Zealand, RIVER_NZ_ORDER or
    less), simplified: gzipped JSON lines of
    [main river id, flow order, flow m3/s, length km, is outlet, coordinates]."""
    n = 0
    with gzip.open(dest, "wt", encoding="utf-8") as out:
        for d, g in _shapes(zp):
            order = int(num(d.get("ORD_FLOW")) or 99)
            if order > max_order and not (order <= RIVER_NZ_ORDER and in_nz((g.get("coordinates") or [[0, 0]])[0])):
                continue
            for ln in lines_of(g):
                pts = dp_line(ln, RIVER_TOL)
                if pts:
                    out.write(json.dumps([int(num(d.get("MAIN_RIV")) or 0), order, num(d.get("DIS_AV_CMS")),
                                          num(d.get("LENGTH_KM")), int(num(d.get("NEXT_DOWN")) or 0) == 0, pts],
                                         separators=(",", ":")) + "\n")
                    n += 1
    return n


def basins_select(zp: Path, dest: Path) -> int:
    """Level-4 basin units with their main basin id and area, simplified, as gzipped GeoJSON."""
    from worldmodel_data.connectors.history import simplify

    feats = []
    for d, g in _shapes(zp):
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        small = simplify(g, BASIN_TOL) or simplify(g, 0)
        if small:
            feats.append({"type": "Feature", "geometry": small, "properties": {
                "id": int(num(d.get("HYBAS_ID")) or 0), "main": int(num(d.get("MAIN_BAS")) or 0),
                "area": num(d.get("SUB_AREA")), "endo": int(num(d.get("ENDO")) or 0)}})
    with gzip.open(dest, "wt", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
    return len(feats)


def basin_records(units: list[dict], grids: Grids, named_rivers: list[dict], outlets: list[tuple]) -> list[dict]:
    """Whole basins from their level-4 units: area, shape, country split (share of the basin
    in each country, and share of each country's land in the basin), outflow and a name."""
    from worldmodel_data.connectors.internet import _fill

    by_main: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        by_main[u["properties"]["main"]].append(u)
    mains = list(by_main)
    idx = {m: i + 1 for i, m in enumerate(mains)}
    bgrid = np.zeros(grids.grid.shape, dtype=np.int32)
    for m, parts in by_main.items():
        for u in parts:
            g = u["geometry"]
            for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
                _fill(bgrid, poly, idx[m], grids.cell)
    # Cell areas shrink towards the poles
    lat = 90 - (np.arange(bgrid.shape[0]) + 0.5) * grids.cell
    w = np.cos(np.radians(lat))[:, None] * np.ones((1, bgrid.shape[1]))
    country_cells = np.bincount(grids.grid.ravel(), weights=w.ravel(), minlength=len(grids.codes) + 1)
    pair = bgrid.astype(np.int64) * (len(grids.codes) + 1) + grids.grid
    mask = bgrid.ravel() > 0
    pc = np.bincount(pair.ravel()[mask], weights=w.ravel()[mask])
    split: dict[int, dict[str, float]] = defaultdict(dict)
    for k in np.nonzero(pc)[0]:
        b, c = divmod(int(k), len(grids.codes) + 1)
        if c:
            split[b][grids.codes[c - 1]] = float(pc[k])
    # Outflow: the biggest river mouth inside each basin
    flow: dict[int, float] = {}
    for lon, lat_, q in outlets:
        r, c = grids.rc(lon, lat_)
        for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            rr, cc = r + dr, (c + dc) % bgrid.shape[1]
            if 0 <= rr < bgrid.shape[0] and bgrid[rr, cc]:
                b = int(bgrid[rr, cc])
                flow[b] = max(flow.get(b, 0), q or 0)
                break
    # Names: the Natural Earth river with most points in the basin (bigger rivers first)
    votes: dict[int, Counter] = defaultdict(Counter)
    for rv in named_rivers:
        weight = 10 - min(9, rv["rank"])
        for ln in rv["lines"]:
            for p in ln[::3]:
                r, c = grids.rc(p[0], p[1])
                b = int(bgrid[r, c])
                if b:
                    votes[b][rv["name"]] += weight
    out = []
    for m, parts in by_main.items():
        b = idx[m]
        area = sum(u["properties"]["area"] or 0 for u in parts)
        cells = split.get(b, {})
        total = sum(cells.values()) or 1
        shares = {c: round(v / total, 4) for c, v in sorted(cells.items(), key=lambda x: -x[1]) if v / total >= 0.005}
        of_country = {c: round(cells[c] / country_cells[grids.codes.index(c) + 1], 4) for c in shares
                      if country_cells[grids.codes.index(c) + 1]}
        main_country = next(iter(shares), None)
        if area < BASIN_MIN_KM2 and not (main_country in BASIN_ALL_IN and area >= 500):
            continue
        polys = []
        for u in parts:
            g = u["geometry"]
            polys += [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        name = votes[b].most_common(1)[0][0] if votes.get(b) else None
        out.append({"id": str(m), "name": f"{name} basin" if name else None, "area": round(area),
                    "shares": shares, "of_country": of_country, "flow": round(flow[b], 1) if flow.get(b) else None,
                    "endorheic": any(u["properties"].get("endo") for u in parts),
                    "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    return out


def name_rank(scalerank: int) -> int:
    """The flow order a named river shows with at least: famous rivers show before their
    water alone would show them (Natural Earth's scalerank: 0 the biggest, 10 to 12 regional)."""
    return 3 if scalerank <= 3 else 4 if scalerank <= 5 else 5 if scalerank <= 7 else 6


class RiverNames:
    """Natural Earth's named rivers as points every ~1 km on a 0.05 degree grid, to name the
    HydroRIVERS reaches that run along them."""

    CELL = 0.05
    TOL = 0.04  # degrees: Natural Earth's lines are drawn for 1:10 million, so a few km out

    def __init__(self, paths: list[Path | None]):
        self.names: list[tuple[str, int]] = []
        self.grid: dict[tuple[int, int], list[tuple[float, float, int]]] = defaultdict(list)
        ids: dict[tuple[str, int], int] = {}
        for path in paths:
            if not path or not path.exists():
                continue
            try:
                feats = json.loads(path.read_text(encoding="utf-8")).get("features") or []
            except (OSError, ValueError) as exc:
                log.warning("hydrosheds: %s not read (%s)", path.name, exc)
                continue
            for f in feats:
                p = f.get("properties") or {}
                cla = str(p.get("featurecla") or "")
                name = clean_river_name(p.get("name_en") or p.get("name"))
                if not name or not ("River" in cla or cla == "Lake Centerline"):
                    continue
                rank = int(num(p.get("scalerank")) if num(p.get("scalerank")) is not None else 9)
                i = ids.setdefault((name, rank), len(self.names))
                if i == len(self.names):
                    self.names.append((name, rank))
                for ln in lines_of(f.get("geometry")):
                    for x, y in densify(ln, 0.01):
                        self.grid[(int(x // self.CELL), int(y // self.CELL))].append((x, y, i))
        # Squares next to a named river: most reaches are nowhere near one and are passed quickly
        self.near = {(cx + dx, cy + dy) for cx, cy in self.grid for dx in (-1, 0, 1) for dy in (-1, 0, 1)}

    def __bool__(self) -> bool:
        return bool(self.names)

    def at(self, x: float, y: float) -> int | None:
        cx, cy = int(x // self.CELL), int(y // self.CELL)
        best, best_d = None, self.TOL * self.TOL
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, py, i in self.grid.get((cx + dx, cy + dy), ()):
                    d = (px - x) ** 2 + (py - y) ** 2
                    if d <= best_d:
                        best, best_d = i, d
        return best

    def name_of(self, pts, order: int | None = None) -> tuple[str, int] | None:
        """The named river a reach runs along: the one nearest at least three of five points
        spread along it (so a side stream that only meets a big river is not named after it),
        and not a big river for a stream far smaller than it (order: the reach's flow order)."""
        if not self.names or len(pts) < 2:
            return None
        if (int(pts[0][0] // self.CELL), int(pts[0][1] // self.CELL)) not in self.near and \
                (int(pts[-1][0] // self.CELL), int(pts[-1][1] // self.CELL)) not in self.near and len(pts) <= 2:
            return None
        sample = [(x, y) for x, y in spread(pts, 5) if (int(x // self.CELL), int(y // self.CELL)) in self.near]
        if len(sample) < 3:
            return None
        votes = Counter(i for i in (self.at(x, y) for x, y in sample) if i is not None)
        if not votes:
            return None
        i, n = votes.most_common(1)[0]
        if n < 3 or (order is not None and order > name_rank(self.names[i][1]) + 2):
            return None
        return self.names[i]


def clean_river_name(name) -> str | None:
    """'Waikato River' and 'Waikato' are the same river; Natural Earth writes both."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    if not s:
        return None
    s = re.sub(r"\s+River$", "", s)
    return s or None


def densify(line, step: float) -> list[tuple[float, float]]:
    """Points along a line no more than `step` degrees apart."""
    out = []
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
    if line:
        out.append((line[-1][0], line[-1][1]))
    return out


def spread(line, n: int) -> list[tuple[float, float]]:
    """n points spread evenly by distance along a line, its two ends included."""
    seg = [((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for (x0, y0), (x1, y1) in zip(line, line[1:])]
    total = sum(seg)
    if not total:
        return [(line[0][0], line[0][1])] * n
    out, at, i, done = [], 0.0, 0, 0.0
    for k in range(n):
        want = total * k / (n - 1)
        while i < len(seg) - 1 and done + seg[i] < want:
            done += seg[i]
            i += 1
        t = min(1.0, max(0.0, (want - done) / seg[i])) if seg[i] else 0.0
        (x0, y0), (x1, y1) = line[i], line[i + 1]
        out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def river_key(main: int, order: int, name: str | None, first) -> tuple:
    """Which stored line a reach joins: its main river, flow order and name, and for smaller
    rivers the square its first point is in."""
    size = RIVER_CELL.get(order)
    cell = (int(first[0] // size), int(first[1] // size)) if size else None
    return (main, order, name, cell)


def river_id(k: tuple) -> str:
    main, order, name, cell = k
    parts = [str(main), str(order)] + ([key(name)] if name else []) + ([f"{cell[0]}_{cell[1]}"] if cell else [])
    return ":".join(parts)


def ne_named_rivers(path: Path) -> list[dict]:
    """Natural Earth's named rivers: name, rank (scalerank, 0 biggest) and lines."""
    if not path or not path.exists():
        return []
    by_name: dict[str, dict] = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        p = f.get("properties") or {}
        name = p.get("name_en") or p.get("name")
        if not name or p.get("featurecla") != "River":
            continue
        r = by_name.setdefault(name, {"name": name, "rank": int(num(p.get("scalerank")) or 9), "lines": []})
        r["rank"] = min(r["rank"], int(num(p.get("scalerank")) or 9))
        r["lines"] += lines_of(f.get("geometry"))
    return list(by_name.values())


class HydroSHEDS(Connector):
    source_id = "hydrosheds"
    switch = "rivers_fetch"
    fetch_every_days = 3650  # HydroSHEDS v1 does not change
    keeps_files = True       # a region that failed today keeps the copy from before
    gap = 2.0
    fetch_version = 2        # 2: rivers down to 1 m3/s (0.1 in New Zealand) and Natural Earth's regional river names
    stage_version = 2        # 2: rivers named, ranked for the zoom they show from, smaller ones stored by square

    def default_release(self, fetched_at: datetime) -> str:
        return "v1"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "v1"

    def download(self, raw_dir: Path, release: str) -> str:
        get_countries(raw_dir, self)
        self.get(NE_RIVERS_URL, raw_dir / NE_RIVERS_FILE)
        for name in NE_RIVER_EXTRAS:  # names for more rivers; the map works without them
            try:
                self.get(NE_GEOJSON + name, raw_dir / name)
            except Exception as exc:  # noqa: BLE001
                log.warning("hydrosheds: %s not fetched (%s)", name, exc)
        prev = self.last_vintage_dir(raw_dir)
        failed = []
        for reg in HYDRO_REGIONS:
            for kind, url, select, out in (("rivers", HYRIV_URL, rivers_select, RIVERS_FILE.format(reg=reg)),
                                           ("basins", HYBAS_URL, basins_select, f"basins_{reg}.geojson.gz")):
                if prev and (prev / out).exists():
                    continue  # read before: keeps_files carries it over
                zp = raw_dir / f"{kind}_{reg}.zip"
                try:
                    self.get(url.format(reg=reg), zp, cached=False)
                    n = select(zp, raw_dir / out)
                    log.info("hydrosheds: %s %s kept from %s", n, kind, reg)
                except Exception as exc:  # noqa: BLE001 - Greenland has no rivers file; one region failing is not all
                    failed.append(f"{kind} {reg} ({exc})")
                    (raw_dir / out).unlink(missing_ok=True)
                finally:
                    zp.unlink(missing_ok=True)  # up to 700 MB; only the selection is kept
                time.sleep(self.gap)
        if failed:
            log.warning("hydrosheds: not read this time: %s", "; ".join(failed[:6]))
        return "https://www.hydrosheds.org"

    def _read_zips(self, raw_dir: Path) -> None:
        """Files saved by hand: select from any HydroRIVERS or HydroBASINS zips."""
        for zp in sorted(raw_dir.glob("*.zip")):
            n = zp.name.lower()
            m = re.search(r"_(af|ar|as|au|eu|gr|na|sa|si)_", n)
            reg = m[1] if m else n[:-4]
            if "hydrorivers" in n and not (raw_dir / RIVERS_FILE.format(reg=reg)).exists():
                rivers_select(zp, raw_dir / RIVERS_FILE.format(reg=reg))
            elif "hybas" in n and not (raw_dir / f"basins_{reg}.geojson.gz").exists():
                basins_select(zp, raw_dir / f"basins_{reg}.geojson.gz")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        self._read_zips(raw_dir)
        rows, outlets = [], []
        ne_files = [raw_dir / n if (raw_dir / n).exists() else self.earlier_copy(raw_dir, n)
                    for n in (NE_RIVERS_FILE, *NE_RIVER_EXTRAS)]
        names = RiverNames(ne_files)
        # Rivers: each main river's reaches by flow order and name (smaller ones by square too),
        # chained into lines. A region read before this version has only order 5 and up.
        groups: dict[tuple, dict] = {}
        for reg in HYDRO_REGIONS:
            f = raw_dir / RIVERS_FILE.format(reg=reg)
            f = f if f.exists() else raw_dir / f"rivers_{reg}.jsonl.gz"
            if not f.exists():
                continue
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    main, order, q, length, outlet, pts = json.loads(line)
                    named_as = names.name_of(pts, order)
                    k = river_key(main, order, named_as[0] if named_as else None, pts[0])
                    g = groups.setdefault(k, {"lines": [], "flow": 0.0, "length": 0.0, "rank": order})
                    g["lines"].append(pts)
                    g["flow"] = max(g["flow"], q or 0)
                    g["length"] += length or 0
                    if named_as:
                        g["rank"] = min(g["rank"], name_rank(named_as[1]))
                    if outlet:
                        outlets.append((pts[-1][0], pts[-1][1], q))
        cfile = countries_file(raw_dir, self)
        grids = Grids(cfile) if cfile else None
        n_named = 0
        for k, g in groups.items():
            main, order, name, _ = k
            lines = chain(g["lines"])
            countries = entity_ids(grids.along(lines, 4)) if grids else []
            n_named += bool(name)
            # rank: the zoom it shows from (flow order, or sooner for a well-known river);
            # order: how much water, for the line's width
            rows.append(("rivers", river_id(k), name, g["rank"],
                         {"flow": round(g["flow"], 1), "length": round(g["length"]), "order": order, "river": main},
                         countries, multiline(lines)))
        named = ne_named_rivers(ne_files[0])
        for rv in named:
            lines = [dp_line(ln, RIVER_TOL) for ln in rv["lines"]]
            rows.append(("river_names", key(rv["name"]), rv["name"], rv["rank"], {"name": rv["name"]},
                         entity_ids(grids.along(lines, 4)) if grids else [], multiline(lines)))
        # Basins
        units = []
        for f in sorted(raw_dir.glob("basins_*.geojson.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                units += json.load(fh)["features"]
        nb = 0
        if units and grids:
            for b in basin_records(units, grids, named, outlets):
                shares = {e: v for e, v in ((iso3_of(c), v) for c, v in b["shares"].items()) if e}
                of_country = {e: v for e, v in ((iso3_of(c), v) for c, v in b["of_country"].items()) if e}
                rank = 1 if b["area"] >= 500000 else 2 if b["area"] >= 100000 else 3
                rows.append(("basins", b["id"], b["name"], rank,
                             {"area": b["area"], "shares": shares, "of_country": of_country, "flow": b["flow"],
                              "endorheic": b["endorheic"], "transboundary": len([v for v in shares.values() if v >= 0.01]) > 1},
                             list(shares), b["geometry"]))
                nb += 1
        if not rows:
            raise ConnectorError(f"hydrosheds: no rivers_*.jsonl.gz or basins_*.geojson.gz in {raw_dir}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("hydrosheds: %s river lines (%s named), %s named rivers, %s basins", len(groups), n_named, len(named), nb)
        return NO_ROWS


# ----------------------------------------------------------------------------- inland waterways
NTAD_URL = ("https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/"
            "NTAD_Navigable_Waterway_Network_Lines/FeatureServer/0/query")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WATERWAY_TOL = 0.005


def overpass_lines(body: dict) -> list[dict]:
    """Ways from an Overpass `out geom` answer: name, CEMT class, kind and line."""
    out = []
    for el in body.get("elements") or []:
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        t = el.get("tags") or {}
        out.append({"name": t.get("name:en") or t.get("name"), "cemt": t.get("CEMT"), "kind": t.get("waterway"),
                    "line": [[p["lon"], p["lat"]] for p in el["geometry"]]})
    return out


class Waterways(Connector):
    source_id = "waterways"
    switch = "transport_waterways_fetch"
    fetch_every_days = 365
    keeps_files = True
    gap = 10.0  # Overpass is shared by everyone: one query at a time, well apart

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        get_countries(raw_dir, self)
        # United States: National Waterway Network, a page at a time
        try:
            offset, page = 0, 0
            while page < 50:
                q = {"where": "1=1", "outFields": "*", "f": "geojson", "resultOffset": offset, "resultRecordCount": 2000,
                     "outSR": 4326}
                dest = raw_dir / f"ntad_{page:03d}.geojson"
                self.get(f"{NTAD_URL}?{urlencode(q)}", dest, cached=False)
                body = json.loads(dest.read_text(encoding="utf-8"))
                got = len(body.get("features") or [])
                if not got:
                    dest.unlink(missing_ok=True)
                    break
                offset += got
                page += 1
                if got < 2000 and not body.get("exceededTransferLimit") and not (body.get("properties") or {}).get("exceededTransferLimit"):
                    break
                time.sleep(1)
        except Exception as exc:  # noqa: BLE001
            log.warning("waterways: US National Waterway Network not read (%s); save it by hand (see Data status)", exc)
        # Europe and the big rivers: OpenStreetMap through Overpass, stopping at the first refusal
        ww = catalogue.transport().get("waterways") or {}
        queries = []
        eu = ww.get("europe")
        if eu:
            w, s, e, n = eu["bbox"]
            queries.append(("osm_europe.json", f'[out:json][timeout:300];way["waterway"]{eu.get("filter", "")}({s},{w},{n},{e});out tags geom;'))
        for r in ww.get("rivers") or []:
            nm = r["name"].replace('"', "")
            queries.append((f"osm_river_{key(nm)}.json",
                            f'[out:json][timeout:180];(relation["waterway"="river"]["name:en"="{nm}"];'
                            f'relation["waterway"="river"]["name"="{nm}"];relation["waterway"="canal"]["name:en"="{nm}"];);'
                            "way(r);out tags geom;"))
        prev = self.last_vintage_dir(raw_dir)
        for name, q in queries:
            if prev and (prev / name).exists() and name != "osm_europe.json":
                continue  # river lines barely change: kept from before (keeps_files)
            try:
                r = self.client.post(OVERPASS_URL, data={"data": q}, timeout=360)
            except Exception as exc:  # noqa: BLE001
                log.warning("waterways: Overpass did not answer (%s); the rest waits for the next refresh", exc)
                break
            if r.status_code != 200:
                log.warning("waterways: Overpass answered %s for %s; stopping until the next refresh", r.status_code, name)
                break
            (raw_dir / name).write_bytes(r.content)
            time.sleep(self.gap)
        return f"{NTAD_URL}; {OVERPASS_URL}"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        cfile = countries_file(raw_dir, self)
        grids = Grids(cfile) if cfile else None
        rows = []
        # US
        us: dict[str, list] = defaultdict(list)
        for f in sorted(raw_dir.glob("ntad_*.geojson")) + sorted(raw_dir.glob("*waterway*network*.geojson")):
            for ft in json.loads(f.read_text(encoding="utf-8")).get("features") or []:
                p = {k.lower(): v for k, v in (ft.get("properties") or {}).items()}
                name = p.get("rivername") or p.get("linkname") or p.get("name") or "Waterway"
                for ln in lines_of(ft.get("geometry")):
                    pts = dp_line(ln, WATERWAY_TOL)
                    if pts:
                        us[str(name).title()].append(pts)
        for name, lines in us.items():
            lines = chain(lines)
            rows.append(("waterways", f"us:{key(name)}", name, 2, {"name": name, "where": "United States",
                                                                   "source": "US National Waterway Network"}, ["USA"],
                         multiline(lines)))
        # Europe, by name and CEMT class
        ww = catalogue.transport().get("waterways") or {}
        eu: dict[tuple[str, str], list] = defaultdict(list)
        f = raw_dir / "osm_europe.json"
        if f.exists():
            for w in overpass_lines(json.loads(f.read_text(encoding="utf-8"))):
                pts = dp_line(w["line"], WATERWAY_TOL)
                if pts:
                    eu[(w["name"] or "Waterway", str(w["cemt"] or ""))].append(pts)
        for (name, cemt), lines in eu.items():
            lines = chain(lines)
            big = cemt.upper().startswith(("V", "VI", "VII"))
            rows.append(("waterways", f"eu:{key(name)}:{key(cemt)}", name, 1 if big else 2,
                         {"name": name, "cemt": cemt or None, "where": "Europe", "source": "OpenStreetMap (CEMT class)"},
                         entity_ids(grids.along(lines, 5)) if grids else [], multiline(lines)))
        # The big rivers
        for r in ww.get("rivers") or []:
            f = raw_dir / f"osm_river_{key(r['name'])}.json"
            if not f.exists():
                continue
            lines = chain([p for p in (dp_line(w["line"], WATERWAY_TOL) for w in overpass_lines(json.loads(f.read_text(encoding="utf-8")))) if p])
            if lines:
                rows.append(("waterways", f"river:{key(r['name'])}", r["name"], 1,
                             {"name": r["name"], "to": r.get("to"), "where": "Big rivers", "source": "OpenStreetMap"},
                             r.get("countries") or [], multiline(lines)))
        if not rows:
            raise ConnectorError(f"waterways: no National Waterway Network pages or OpenStreetMap answers in {raw_dir}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("waterways: %s waterways", len(rows))
        return NO_ROWS


# ----------------------------------------------------------------------------- undersea cables
CABLE_API = "https://www.submarinecablemap.com/api/v3"
CABLE_DETAILS_A_RUN = 150  # new cables' details read in one refresh; the rest next time


def cable_countries(detail: dict) -> list[str]:
    out = []
    for lp in detail.get("landing_points") or []:
        c = lp.get("country") or str(lp.get("name") or "").split(",")[-1].strip()
        e = iso3_of(c)
        if e and e not in out:
            out.append(e)
    return out


class SubmarineCables(Connector):
    source_id = "submarine_cables"
    switch = "cables_fetch"
    fetch_every_days = 30
    keeps_files = True  # each cable's details are read once and kept
    gap = 2.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        get_countries(raw_dir, self)
        self.get(f"{CABLE_API}/cable/cable-geo.json", raw_dir / "cable-geo.json")
        self.get(f"{CABLE_API}/landing-point/landing-point-geo.json", raw_dir / "landing-point-geo.json")
        prev = self.last_vintage_dir(raw_dir)
        ids = []
        for ft in json.loads((raw_dir / "cable-geo.json").read_text(encoding="utf-8")).get("features") or []:
            cid = (ft.get("properties") or {}).get("id")
            if cid and cid not in ids:
                ids.append(cid)
        todo = [c for c in ids if not (prev and (prev / f"cable_{c}.json").exists())][:CABLE_DETAILS_A_RUN]
        for cid in todo:
            try:
                self.get(f"{CABLE_API}/cable/{cid}.json", raw_dir / f"cable_{cid}.json", cached=False)
            except Exception as exc:  # noqa: BLE001 - stop at the first refusal; the rest next time
                log.warning("submarine_cables: details stopped at %s (%s); the rest come with later refreshes", cid, exc)
                (raw_dir / f"cable_{cid}.json").unlink(missing_ok=True)
                break
            time.sleep(self.gap)
        return CABLE_API

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        geo = raw_dir / "cable-geo.json"
        if not geo.exists():
            raise ConnectorError(f"submarine_cables: cable-geo.json missing from {raw_dir}")
        details = {}
        for f in raw_dir.glob("cable_*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                details[str(d.get("id") or f.stem[6:])] = d
            except json.JSONDecodeError:
                continue
        # Landing points: a small point layer, and a fallback for which countries a cable reaches
        lps, lp_feats = [], []
        lpf = raw_dir / "landing-point-geo.json"
        if lpf.exists():
            for ft in json.loads(lpf.read_text(encoding="utf-8")).get("features") or []:
                p = ft.get("properties") or {}
                g = ft.get("geometry") or {}
                if g.get("type") != "Point":
                    continue
                country = iso3_of(str(p.get("name") or "").split(",")[-1].strip())
                lps.append((g["coordinates"][0], g["coordinates"][1], country))
                lp_feats.append(feature(g, {"id": p.get("id"), "name": p.get("name"), "country": country}))
        lp_arr = np.asarray([(x, y) for x, y, _ in lps], dtype=float) if lps else None
        by_cable: dict[str, dict] = {}
        for ft in json.loads(geo.read_text(encoding="utf-8")).get("features") or []:
            p = ft.get("properties") or {}
            cid = str(p.get("id") or p.get("feature_id") or "")
            c = by_cable.setdefault(cid, {"name": p.get("name"), "color": p.get("color"), "lines": []})
            c["lines"] += [dp_line(ln, 0.02) for ln in lines_of(ft.get("geometry"))]
        rows = []
        for cid, c in by_cable.items():
            d = details.get(cid) or {}
            countries = cable_countries(d)
            if not countries and lp_arr is not None:  # the landing points nearest its ends
                for ln in c["lines"]:
                    for end in (ln[:1] + ln[-1:]) if ln else []:
                        dist = np.hypot(lp_arr[:, 0] - end[0], lp_arr[:, 1] - end[1])
                        i = int(np.argmin(dist))
                        if dist[i] < 0.5 and lps[i][2] and lps[i][2] not in countries:
                            countries.append(lps[i][2])
            rfs = d.get("rfs_year") or (re.search(r"\d{4}", str(d.get("rfs") or "")) or [None])[0]
            rows.append(("cables", cid, d.get("name") or c["name"], 1,
                         {"color": c["color"], "rfs": rfs, "length": d.get("length"), "owners": d.get("owners"),
                          "planned": d.get("is_planned"), "url": d.get("url"),
                          "landings": [lp.get("name") for lp in d.get("landing_points") or []][:40]},
                         countries, multiline([ln for ln in c["lines"] if ln])))
        if lp_feats:
            self.layers = [{"layer_id": "cable_landings", "name": "Cable landing points", "kind": "point",
                            "description": "Where undersea cables come ashore (TeleGeography Submarine Cable Map).",
                            "feature_count": len(lp_feats), "geojson": collection(lp_feats)}]
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("submarine_cables: %s cables (%s with details), %s landing points", len(rows), len(details), len(lp_feats))
        return NO_ROWS


# ----------------------------------------------------------------------------- GEM pipelines and LNG
PIPE_TOL = 0.01
STATUS_RANK = {"operating": 1, "construction": 2, "in development": 2, "proposed": 3, "shelved": 4, "cancelled": 5,
               "mothballed": 4, "retired": 5, "idle": 4}


def gem_kind(path: Path, row: dict) -> str:
    """gas_pipelines, oil_pipelines or lng_terminals, from the file name or columns."""
    n = path.name.lower()
    if "lng" in n or "terminal" in n or row.get("terminalname") or row.get("terminalid"):
        return "lng_terminals"
    if "oil" in n or "ngl" in n or str(row.get("fuel") or "").lower() in ("oil", "ngl"):
        return "oil_pipelines"
    return "gas_pipelines"


class GEMInfrastructure(Connector):
    source_id = "gem_infrastructure"
    switch = "energy_infrastructure_fetch"
    manual = True
    keeps_files = True  # the gas, oil and LNG files are saved one at a time

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"(20\d{2})[-_ ]?(0[1-9]|1[0-2])?", f.name)
            if m:
                return f"{m[1]}-{m[2]}" if m[2] else m[1]
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("gem_infrastructure: save Global Energy Monitor's tracker files by hand (see Data status)")

    def _rows(self, path: Path) -> list[dict]:
        if path.suffix.lower() in (".geojson", ".json"):
            out = []
            for f in json.loads(path.read_text(encoding="utf-8")).get("features") or []:
                out.append({key(k): v for k, v in (f.get("properties") or {}).items()} | {"_geom": f.get("geometry")})
            return out
        table = read_table(path)
        return header_rows(table, ("status",)) or header_rows(table, ("country",))

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        cfile = countries_file(raw_dir, self)
        grids = Grids(cfile) if cfile else None
        rows, lng = [], []
        for path in sorted(raw_dir.iterdir()):
            if path.suffix.lower() not in (".xlsx", ".csv", ".geojson", ".json") or path.name.startswith("ne_"):
                continue
            for r in self._rows(path):
                kind = gem_kind(path, r)
                name = r.get("pipelinename") or r.get("terminalname") or r.get("projectname") or r.get("name")
                if not name:
                    continue
                status = str(r.get("status") or "").strip().lower()
                countries = [c for c in (iso3_of(x.strip()) for x in re.split(r"[;,]", str(r.get("countries") or r.get("country") or ""))
                                         if x.strip()) if c]
                if kind == "lng_terminals":
                    lat, lon = num(r.get("latitude") or r.get("lat")), num(r.get("longitude") or r.get("lon"))
                    if lat is None or lon is None:
                        continue
                    lng.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                        "name": name, "status": status, "facility": r.get("facilitytype") or r.get("type"),
                        "capacity": num(r.get("capacityinmtpa") or r.get("capacitymtpa") or r.get("capacity")),
                        "country": countries[0] if countries else None, "owner": r.get("owner") or r.get("parent"),
                        "start": r.get("startyear") or r.get("startyear1"), "url": r.get("wiki") or r.get("wikiurl") or r.get("url")}))
                    continue
                geom = r.get("_geom") or parse_wkt(r.get("wktformat") or r.get("wkt") or r.get("route") or "")
                lines = [p for p in (dp_line(ln, PIPE_TOL) for ln in lines_of(geom)) if p]
                if not lines:
                    continue
                if not countries and grids:
                    countries = entity_ids(grids.along(lines, 3))
                pid = str(r.get("projectid") or r.get("pipelineid") or r.get("id") or f"{key(name)}:{key(r.get('segmentname') or '')}")
                rows.append((kind, pid, name, STATUS_RANK.get(status, 3), {
                    "status": status or None, "fuel": r.get("fuel"), "segment": r.get("segmentname"),
                    "capacity": num(r.get("capacity") or r.get("capacitybcm/y") or r.get("capacitybcmy") or r.get("capacityboed")),
                    "capacity_unit": r.get("capacityunits") or r.get("capacityunit"),
                    "length_km": num(r.get("lengthmergedkm") or r.get("lengthknownkm") or r.get("lengthestimatekm")),
                    "start": r.get("startyear1") or r.get("startyear"), "owner": r.get("owner") or r.get("parent"),
                    "url": r.get("wiki") or r.get("wikiurl") or r.get("url")}, countries, multiline(lines)))
        if lng:
            self.layers = [{"layer_id": "lng_terminals", "name": "LNG terminals", "kind": "point",
                            "description": "Liquefied gas import and export terminals, operating and planned (Global Energy Monitor).",
                            "feature_count": len(lng), "geojson": collection(lng)}]
        if not rows and not lng:
            raise ConnectorError(f"gem_infrastructure: no pipeline routes or terminals read from {raw_dir}")
        if rows:
            self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("gem_infrastructure: %s pipelines, %s LNG terminals", len(rows), len(lng))
        return NO_ROWS


# ----------------------------------------------------------------------------- railways
NE_RAIL_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_railroads.geojson"
NE_RAIL_FILE = "ne_10m_railroads.geojson"
RAIL_TOL = 0.005  # degrees (about 500 m)


def rail_rank(scalerank) -> int:
    """Natural Earth draws its most important lines from the smallest scales: 1 main lines
    (scalerank 5 and under), 2 other through lines (6-7), 3 the rest (8 and up)."""
    try:
        s = int(scalerank)
    except (TypeError, ValueError):
        return 3
    return 1 if s <= 5 else 2 if s <= 7 else 3


def rail_rows(path: Path, grids: "Grids | None") -> list[tuple]:
    """geo_features rows: railway lines simplified and gathered by 1° square and rank, so the
    map asks only for the squares in view."""
    squares: dict[tuple[int, int, int], list] = defaultdict(list)
    for ft in json.loads(path.read_text(encoding="utf-8")).get("features") or []:
        rank = rail_rank((ft.get("properties") or {}).get("scalerank"))
        for ln in lines_of(ft.get("geometry")):
            d = dp_line(ln, RAIL_TOL, 3)
            if d:
                squares[(int(d[0][0] // 1), int(d[0][1] // 1), rank)].append(d)
    rows = []
    for (x, y, rank), lines in squares.items():
        countries = entity_ids(grids.along(lines, every=4)) if grids else []
        rows.append(("railways", f"{x}_{y}_{rank}", "Railways", rank, {"rank": rank}, countries, multiline(lines)))
    return rows


class NERailways(Connector):
    """Natural Earth railroads (public domain): the world's railway lines, intercity and freight,
    at about 1:10 million."""
    source_id = "ne_railways"
    switch = "railways_fetch"
    fetch_every_days = 365  # Natural Earth changes rarely

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        get_countries(raw_dir, self)
        self.get(NE_RAIL_URL, raw_dir / NE_RAIL_FILE)
        return "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/railroads/"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        path = raw_dir / NE_RAIL_FILE
        if not path.exists():
            raise ConnectorError(f"ne_railways: {NE_RAIL_FILE} missing from {raw_dir}")
        cf = countries_file(raw_dir, self)
        rows = rail_rows(path, Grids(cf) if cf else None)
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("ne_railways: %s squares of railway lines", len(rows))
        return NO_ROWS
