"""Spotting things in the satellite pictures and maps: layers the app works out itself.

    Land change     two years of a land cover map compared pixel by pixel (map layer 8). Each
                    picture's colours are read back into kinds of cover (trees, crops, built-up ...);
                    a pixel counts as changed when its kind changed in a way listed in
                    worldmodel_contract.spotting.CHANGES, the change already held the year before
                    the end year (Esri's yearly maps flicker), and enough pixels around it changed
                    the same way (no lone specks). Results are kept as small palette pictures under
                    <data folder>/basemap/derived, so a place is worked out once.
    Water           JRC Global Surface Water's transitions map, recoloured so water gained shows
                    blue and water lost red (map layer 9).
    Area summary    hectares of each kind of change (or water class) in a country or box, and the
                    squares with the most, worked out in the background from the same pictures.
    Ask the picture the satellite picture round a point, the land cover shares there and the map's
                    items nearby, for the Ask AI box.
    Area scans      an area cut into squares (zoom-13 tiles), each square's satellite picture sent to
                    a local model in Ollama that can see pictures with the list of things to look for;
                    "check" scans look at the map's own places (power plants, airports ...) instead.
                    One scan runs at a time, in the background, and only when you start it; it can be
                    paused and picks up where it stopped. Scans live in <your folder>/spotting/scans.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from worldmodel_contract import local
from worldmodel_contract.spotting import (CHANGE_IDS, CHANGE_MIN_PIXELS, CHANGE_SOURCES, CHANGES, CHECKABLE, KINDS,
                                          LC10_COLOURS, SCAN_PICTURE_ZOOM, SCAN_TAGS, SCAN_ZOOM, WATER_CLASSES,
                                          WHERE_CELLS, change_kind)
from worldmodel_api import ai, tiles

log = logging.getLogger(__name__)
Q = Callable[[str, list], list[dict]]
Fetch = Callable[[str, int, int, int, "str | None"], "tuple[bytes, str] | None"]
CIRC = 40_075_016.686  # metres round the equator


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _fetch(set_id: str, z: int, x: int, y: int, t: str | None = None):
    return tiles.tile(set_id, z, x, y, t)


def _rgba(data: bytes):
    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"), dtype=np.int32)


def _nearest(a, colours: list[tuple[int, int, int]], max_d: int):
    """Index of each pixel's nearest colour (-1 where see-through or nothing is near)."""
    import numpy as np

    rgb, alpha = a[:, :, :3], a[:, :, 3]
    cols = np.array(colours, dtype=np.int32)
    d = ((rgb[:, :, None, :] - cols[None, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1)
    idx[(alpha < 128) | (d.min(-1) > max_d ** 2)] = -1
    return idx


# ----------------------------------------------------------------------------- land cover pictures into kinds
_LC10 = [(_hex(c), k) for c, k in LC10_COLOURS.values()]


def kinds_of(src: str, data: bytes):
    """Each pixel's kind of cover (index into KINDS, -1 for none) from a land cover picture."""
    import numpy as np

    a = _rgba(data)
    if src == "lc10":
        idx = _nearest(a, [c for c, _ in _LC10], 40)
        kind_of = np.array([KINDS.index(k) if k else -1 for _, k in _LC10] + [-1])
        return kind_of[idx]  # idx -1 picks the last entry, -1
    from worldmodel_api.land import cci_kinds

    return cci_kinds(_img(data), np.ones(a.shape[:2], dtype=bool))


def _img(data: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(data))


def _lut():
    """change index (into CHANGES, -1 none) for every pair of kinds, offset by one so -1 (no reading) fits."""
    import numpy as np

    n = len(KINDS) + 1
    lut = np.full((n, n), -1, dtype=np.int16)
    for i, a in enumerate(KINDS):
        for j, b in enumerate(KINDS):
            c = change_kind(a, b)
            lut[i + 1, j + 1] = CHANGE_IDS.index(c) if c else -1
    return lut


_LUT = None


def change_classes(k0, k1, kprev=None):
    """Kind of change per pixel (index into CHANGES, -1 none) from the kinds in the first and last
    year, and (if given) the year before the last: the change must already hold then."""
    import numpy as np

    global _LUT
    if _LUT is None:
        _LUT = _lut()
    c = _LUT[k0 + 1, k1 + 1]
    if kprev is not None:
        c = np.where(_LUT[k0 + 1, kprev + 1] == c, c, -1)
    return despeckle(c)


def despeckle(c, need: int = CHANGE_MIN_PIXELS):
    """Drops changed pixels with fewer than `need` of the 3x3 around them (themselves too) changed the same way."""
    import numpy as np

    h, w = c.shape
    p = np.pad(c, 1, constant_values=-1)
    same = np.zeros((h, w), dtype=np.int16)
    for dy in range(3):
        for dx in range(3):
            same += p[dy:dy + h, dx:dx + w] == c
    return np.where((c >= 0) & (same >= need), c, -1)


def _years(src: str, y0: int, y1: int) -> tuple[int, int]:
    lo, hi = CHANGE_SOURCES[src]["years"]
    y0, y1 = max(lo, min(hi, int(y0))), max(lo, min(hi, int(y1)))
    if y1 <= y0:
        raise ValueError(f"the last year must be after the first ({lo}-{hi})")
    return y0, y1


def change_array(src: str, z: int, x: int, y: int, y0: int, y1: int, fetch: Fetch | None = None):
    """The change per pixel for one tile, or None when a year's picture could not be had."""
    import numpy as np
    from PIL import Image

    if src not in CHANGE_SOURCES:
        raise ValueError(f"unknown land cover source {src}")
    y0, y1 = _years(src, y0, y1)
    fetch = fetch or _fetch
    years = [y0, y1] + ([y1 - 1] if y1 - 1 > y0 else [])
    got = []
    for yr in years:
        t = fetch(src, z, x, y, str(yr))
        if not t:
            return None
        got.append(kinds_of(src, t[0]))
    size = got[0].shape
    for i, k in enumerate(got[1:], 1):  # pictures of another size are brought to the first's
        if k.shape != size:
            got[i] = np.asarray(Image.fromarray((k + 1).astype(np.uint8)).resize(size[::-1], Image.NEAREST), dtype=np.int32) - 1
    return change_classes(got[0], got[1], got[2] if len(got) > 2 else None)


def _derived(*parts) -> Path:
    return local.home() / "basemap" / "derived" / Path(*[str(p) for p in parts])


def _palette_png(idx, colours: list[str], show: list[bool], alpha: int = 225) -> bytes:
    """A palette picture: index i drawn in colours[i] where show[i], everything else see-through."""
    import numpy as np
    from PIL import Image

    n = len(colours)
    im = Image.fromarray(np.where(idx >= 0, idx, 255).astype(np.uint8), mode="P")
    pal = []
    for c in colours:
        pal += list(_hex(c))
    im.putpalette(pal + [0, 0, 0] * (256 - n))
    trans = bytes(alpha if i < n and show[i] else 0 for i in range(256))
    buf = io.BytesIO()
    im.save(buf, "PNG", transparency=trans, optimize=True)
    return buf.getvalue()


def _read_idx(p: Path):
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(p), dtype=np.int16)
    return np.where(a == 255, -1, a)


def _save_idx(p: Path, idx) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_palette_png(idx, [c.colour for c in CHANGES], [True] * len(CHANGES)))


def change_tile(src: str, z: int, x: int, y: int, y0: int, y1: int, kinds: str | None = None, fetch: Fetch | None = None) -> bytes | None:
    """Map layer 8: the tile's changed pixels coloured by kind of change (PNG), or None if a picture was missing."""
    if src not in CHANGE_SOURCES or z < 0 or z > CHANGE_SOURCES[src]["maxzoom"] or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    y0, y1 = _years(src, y0, y1)
    p = _derived(f"change-{src}-{y0}-{y1}", z, x, f"{y}.png")
    idx = _read_idx(p) if p.is_file() and fetch is None else None
    if idx is None:
        idx = change_array(src, z, x, y, y0, y1, fetch)
        if idx is None:
            return None
        if fetch is None:
            _save_idx(p, idx)
    want = set((kinds or "").split(",")) - {""}
    return _palette_png(idx, [c.colour for c in CHANGES], [not want or c.id in want for c in CHANGES])


# ----------------------------------------------------------------------------- water gained and lost
_WATER = [_hex(w.colour) for w in WATER_CLASSES]


def water_classes(data: bytes):
    """Each pixel's JRC transitions class (index into WATER_CLASSES, -1 none)."""
    return _nearest(_rgba(data), _WATER, 45)


def water_tile(z: int, x: int, y: int, show: str = "changes", fetch: Fetch | None = None) -> bytes | None:
    """Map layer 9: JRC's transitions recoloured; with show="changes" water that stayed is left out."""
    t = (fetch or _fetch)("water", z, x, y, None)
    if not t:
        return None
    idx = water_classes(t[0])
    return _palette_png(idx, [w.draw for w in WATER_CLASSES], [show == "all" or w.group != "same" for w in WATER_CLASSES])


# ----------------------------------------------------------------------------- countries (where a point or square is)
_countries: dict = {}


def _country_shapes():
    """(iso3, name, shape) for every country outline, and a search tree over them."""
    if "tree" not in _countries:
        from shapely import STRtree
        from shapely.geometry import shape

        f = Path(__file__).resolve().parents[2] / "web" / "public" / "geo" / "countries.json"
        try:
            feats = json.loads(f.read_text(encoding="utf-8")).get("features", [])
        except FileNotFoundError:
            feats = []
        rows = []
        for ft in feats:
            try:
                rows.append(((ft.get("properties") or {}).get("iso3"), (ft.get("properties") or {}).get("name"), shape(ft["geometry"])))
            except Exception:  # noqa: BLE001 - a broken outline is skipped
                continue
        _countries["rows"] = rows
        _countries["tree"] = STRtree([r[2] for r in rows]) if rows else None
    return _countries["rows"], _countries["tree"]


def country_at(lon: float, lat: float) -> tuple[str, str] | None:
    from shapely.geometry import Point

    rows, tree = _country_shapes()
    if tree is None:
        return None
    pt = Point(lon, lat)
    for i in tree.query(pt):
        if rows[i][2].contains(pt):
            return rows[i][0], rows[i][1]
    return None


def _area_shape(entity: str | None, bbox: list | tuple | None):
    """(shape, box, name) of the area: a country's outline or a box."""
    from shapely.geometry import box as mkbox

    if entity:
        rows, _ = _country_shapes()
        hit = next((r for r in rows if r[0] == entity.upper()), None)
        if not hit:
            raise ValueError(f"no outline for {entity}")
        g = hit[2]
        w, s, e, n = g.bounds
        if e - w > 300:  # across the date line (New Zealand's islands, Fiji, Russia): the eastern-hemisphere part only
            from shapely.geometry import box as b2
            east = g.intersection(b2(0, -90, 180, 90))
            g = east if not east.is_empty and east.area > g.area * 0.5 else g
        return g, g.bounds, hit[1]
    if not bbox or len(bbox) != 4:
        raise ValueError("give a country or a box (west, south, east, north)")
    w, s, e, n = (float(v) for v in bbox)
    if not (-180 <= w < e <= 180 and -85 <= s < n <= 85):
        raise ValueError("the box must be west < east and south < north, inside -180..180 and -85..85")
    return mkbox(w, s, e, n), (w, s, e, n), "Box"


def _land_tiles(g, bounds, z: int) -> list[tuple[int, int]]:
    """Tiles at zoom z whose square touches the area and some land."""
    from shapely.geometry import box as mkbox

    rows, tree = _country_shapes()
    out = []
    for x, y in tiles.tiles_in(tuple(bounds), z):
        sq = mkbox(*tiles.lonlat_box(z, x, y))
        if not g.intersects(sq):
            continue
        if tree is not None and not any(rows[i][2].intersects(sq) for i in tree.query(sq)):
            continue
        out.append((x, y))
    return out


def _pixel_lonlat(z: int, x: int, y: int, size: int):
    import numpy as np

    lon0, s_, lon1, n_ = tiles.lonlat_box(z, x, y)
    px = (np.arange(size) + 0.5) / size
    lons = lon0 + px * (lon1 - lon0)
    lats = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + px) / 2 ** z))))
    return np.meshgrid(lons, lats)


def _ha(z: int, size: int, lat_g):
    import numpy as np

    return ((CIRC / 2 ** z / size) * np.cos(np.radians(lat_g))) ** 2 / 10_000


# ----------------------------------------------------------------------------- area summaries (background)
DETAIL_TILES = {"quick": 150, "fine": 1500}
_sum_lock = threading.Lock()
_sum_job: dict = {"state": "idle"}


def _spot_dir() -> Path:
    return local.user_dir() / "spotting"


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


def _summaries_file() -> Path:
    return _spot_dir() / "summaries.json"


def summary_key(req: dict) -> str:
    area = req.get("entity") or ",".join(f"{float(v):.2f}" for v in req.get("bbox") or [])
    if req["kind"] == "water":
        return f"water|{area}|{req.get('detail', 'quick')}"
    return f"land|{req['src']}|{req['from']}|{req['to']}|{area}|{req.get('detail', 'quick')}"


def summaries() -> dict:
    with _sum_lock:
        return {"job": dict(_sum_job), "saved": _read(_summaries_file(), {})}


def _norm_summary(req: dict) -> dict:
    kind = req.get("kind", "land")
    if kind not in ("land", "water"):
        raise ValueError("kind must be land or water")
    out = {"kind": kind, "detail": req.get("detail", "quick") if req.get("detail") in DETAIL_TILES else "quick",
           "entity": (req.get("entity") or "").upper() or None, "bbox": req.get("bbox")}
    if kind == "land":
        src = req.get("src", "lc10")
        if src not in CHANGE_SOURCES:
            raise ValueError(f"unknown land cover source {src}")
        y0, y1 = _years(src, req.get("from", CHANGE_SOURCES[src]["years"][0]), req.get("to", CHANGE_SOURCES[src]["years"][1]))
        out.update(src=src, **{"from": y0, "to": y1})
    _area_shape(out["entity"], out["bbox"])  # checks the area now, so a bad one fails at once
    return out


def summary_start(req: dict) -> dict:
    req = _norm_summary(req)
    with _sum_lock:
        if _sum_job.get("state") == "running":
            raise RuntimeError("another area is being worked out; wait for it to finish")
        _sum_job.clear()
        _sum_job.update(state="running", key=summary_key(req), req=req, done=0, total=0, step="Starting")
    threading.Thread(target=_summary_work, args=(req,), daemon=True, name="spot-summary").start()
    return summaries()


def area_summary(req: dict, fetch: Fetch | None = None, progress: Callable[[int, int], None] | None = None) -> dict:
    """Hectares of each kind of change (land) or water class (water) in the area, and the squares with the most."""
    import numpy as np
    from shapely import contains_xy

    g, bounds, name = _area_shape(req.get("entity"), req.get("bbox"))
    cap = DETAIL_TILES[req.get("detail", "quick")]
    land = req["kind"] == "land"
    top = CHANGE_SOURCES[req["src"]]["maxzoom"] if land else tiles.SETS["water"]["maxzoom"]
    z = top
    while z > 2 and tiles.count(bounds, z, z) > cap * 4:  # a cheap first cut before checking for land
        z -= 1
    sq = _land_tiles(g, bounds, z)
    while z > 2 and len(sq) > cap:
        z -= 1
        sq = _land_tiles(g, bounds, z)
    labels = [c.id for c in CHANGES] if land else [str(w.code) for w in WATER_CLASSES]
    total = np.zeros(len(labels))
    spots = []
    got = missing = 0
    for i, (x, y) in enumerate(sq):
        if progress:
            progress(i, len(sq))
        if land:
            idx = change_array(req["src"], z, x, y, req["from"], req["to"], fetch)
        else:
            t = (fetch or _fetch)("water", z, x, y, None)
            idx = water_classes(t[0]) if t else None
        if idx is None:
            missing += 1
            continue
        got += 1
        lon_g, lat_g = _pixel_lonlat(z, x, y, idx.shape[0])
        inside = contains_xy(g, lon_g, lat_g) & (idx >= 0)
        if not inside.any():
            continue
        ha = _ha(z, idx.shape[0], lat_g)
        per = np.bincount(idx[inside], weights=ha[inside], minlength=len(labels))[:len(labels)]
        total += per
        changed = per if land else per * np.array([w.group in ("gained", "lost") for w in WATER_CLASSES])
        if changed.sum() > 0:
            w_, s_, e_, n_ = tiles.lonlat_box(z, x, y)
            spots.append({"lon": round((w_ + e_) / 2, 4), "lat": round((s_ + n_) / 2, 4), "ha": round(float(changed.sum()), 1),
                          "main": labels[int(changed.argmax())], "z": z, "x": x, "y": y})
    if not got:
        raise RuntimeError("no pictures could be read for this area (is the map service reachable? Settings > Maps)")
    lat_mid = (bounds[1] + bounds[3]) / 2
    out = {**req, "name": name, "zoom": z, "squares": len(sq), "read": got, "missing": missing,
           "pixel_m": round(CIRC / 2 ** z / 256 * math.cos(math.radians(lat_mid))),
           "ha": {k: round(float(v), 1) for k, v in zip(labels, total)},
           "hot_spots": sorted(spots, key=lambda s: -s["ha"])[:25],
           "worked_out": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return out


def _summary_work(req: dict) -> None:
    def progress(i: int, n: int) -> None:
        with _sum_lock:
            _sum_job.update(done=i, total=n, step=f"Square {i + 1:,} of {n:,}")

    try:
        res = area_summary(req, progress=progress)
        with _sum_lock:
            saved = _read(_summaries_file(), {})
            saved[summary_key(req)] = res
            if len(saved) > 200:
                for k in sorted(saved, key=lambda k: saved[k].get("worked_out", ""))[: len(saved) - 200]:
                    saved.pop(k)
            _write(_summaries_file(), saved)
            _sum_job.update(state="done", done=res["squares"], total=res["squares"], step="Done")
    except Exception as exc:  # noqa: BLE001 - shown on the page
        log.warning("spotting summary: %s", exc)
        with _sum_lock:
            _sum_job.update(state="error", error=str(exc))


# ----------------------------------------------------------------------------- pictures of a place
def picture(lon: float, lat: float, zoom: int, size: int = 512, set_id: str = "satellite", t: str | None = None,
            fetch: Fetch | None = None) -> tuple[bytes, dict] | None:
    """A size x size JPEG of the satellite (or another set's) picture centred on a point, put together
    from the tiles round it, and how many km across it is. None if no tile could be had."""
    from PIL import Image

    fetch = fetch or _fetch
    zoom = max(1, min(zoom, tiles.SETS[set_id]["maxzoom"]))
    n = 2 ** zoom
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(max(-85.05, min(85.05, lat))))) / math.pi) / 2 * n
    half = size / 2 / 256
    x0, x1 = math.floor(fx - half), math.floor(fx + half)
    y0, y1 = max(0, math.floor(fy - half)), min(n - 1, math.floor(fy + half))
    canvas = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256), (0, 0, 0))
    got = 0
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            tt = fetch(set_id, zoom, tx % n, ty, t)
            if not tt:
                continue
            im = Image.open(io.BytesIO(tt[0])).convert("RGB")
            if im.size != (256, 256):
                im = im.resize((256, 256))
            canvas.paste(im, ((tx - x0) * 256, (ty - y0) * 256))
            got += 1
    if not got:
        return None
    left = round((fx - x0) * 256 - size / 2)
    top = round((fy - y0) * 256 - size / 2)
    crop = canvas.crop((left, top, left + size, top + size))
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=85)
    km = CIRC / n / 256 * size * math.cos(math.radians(lat)) / 1000
    return buf.getvalue(), {"km": round(km, 2), "zoom": zoom, "tiles": got}


def square_picture(z: int, x: int, y: int, fetch: Fetch | None = None) -> bytes | None:
    """A zoom-z square's satellite picture at two zooms closer (four tiles put together, 512 x 512 JPEG)."""
    w, s, e, n = tiles.lonlat_box(z, x, y)
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / 2 ** z))))
    got = picture((w + e) / 2, lat, z + (SCAN_PICTURE_ZOOM - SCAN_ZOOM), 256 * 2 ** (SCAN_PICTURE_ZOOM - SCAN_ZOOM), fetch=fetch)
    return got[0] if got else None


def _sea_share(jpeg: bytes) -> float:
    """How much of a satellite picture is open sea (dark blue), to skip squares with nothing to see."""
    import numpy as np

    a = _rgba(jpeg)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    sea = (b >= r + 8) & (b >= g - 4) & (r < 70) & (g < 110) & (b < 140)
    return float(sea.mean())


def here(q: Q, lon: float, lat: float, zoom: int = 15, fetch: Fetch | None = None) -> dict:
    """For Ask the picture: the satellite picture round a point, what covers the ground there and the map's items nearby."""
    from worldmodel_api.land import classify
    from worldmodel_contract.land import WORLDCOVER
    import numpy as np

    pic = picture(lon, lat, zoom, fetch=fetch)
    if not pic:
        raise RuntimeError("no satellite picture could be had for this place (offline, and no saved copy here?)")
    data, info = pic
    out = {"lon": round(lon, 5), "lat": round(lat, 5), "km": info["km"], "zoom": info["zoom"],
           "picture": "data:image/jpeg;base64," + base64.b64encode(data).decode()}
    c = country_at(lon, lat)
    out["country"] = {"id": c[0], "name": c[1]} if c else None
    cover = picture(lon, lat, min(info["zoom"], tiles.SETS["landcover"]["maxzoom"]), set_id="landcover",
                    t=local.load_settings().get("land_cover_year", "2021"), fetch=fetch)
    if cover:
        from PIL import Image
        counts = classify(Image.open(io.BytesIO(cover[0])), np.ones((512, 512), dtype=bool))
        tot = sum(counts.values()) or 1
        out["cover"] = [{"label": WORLDCOVER[k][0], "share": round(v / tot * 100, 1)}
                        for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v / tot >= 0.01]
    else:
        out["cover"] = []
    out["nearby"] = nearby(q, lon, lat, max(1.0, info["km"]))
    return out


def nearby(q: Q, lon: float, lat: float, km: float, limit: int = 20) -> list[dict]:
    """The map's dot layers' items within km of a point, nearest first."""
    try:
        has = q("SELECT 1 FROM information_schema.tables WHERE table_name = 'layer_items'", [])
    except Exception:  # noqa: BLE001 - no warehouse yet
        return []
    if not has:
        return []
    dlat = km / 111.32
    dlon = km / (111.32 * max(0.05, math.cos(math.radians(lat))))
    found = q("""SELECT layer_id, name, category, size, lat, lon FROM layer_items
                 WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT 400""",
              [lat - dlat, lat + dlat, lon - dlon, lon + dlon])
    for r in found:
        r["km"] = round(math.hypot((r["lat"] - lat) * 111.32, (r["lon"] - lon) * 111.32 * math.cos(math.radians(lat))), 2)
    return sorted(found, key=lambda r: r["km"])[:limit]


# ----------------------------------------------------------------------------- the local models
def vision_models(settings: dict | None = None) -> dict:
    """Models in Ollama that can see pictures, smallest first, and the ones picked for asking and scanning."""
    s = settings or local.load_settings()
    try:
        installed = ai.models(s)
    except Exception as exc:  # noqa: BLE001 - shown on the page
        return {"models": [], "ask": None, "scan": None, "error": ai._ollama_problem(exc, s)}
    sees = [m for m in installed if m["name"] and ai.can_see(m["name"], s)]
    sees.sort(key=lambda m: m.get("size") or 0)
    names = [m["name"] for m in sees]
    ask_m = s.get("spot_ask_model") if s.get("spot_ask_model") in names else (names[-1] if names else None)
    scan_m = s.get("spot_scan_model") if s.get("spot_scan_model") in names else (names[0] if names else None)
    return {"models": sees, "ask": ask_m, "scan": scan_m, "error": None if names else
            "None of your Ollama models can see pictures. Install one, for example: ollama pull qwen2.5vl:7b"}


def _json_answer(text: str) -> dict:
    text = ai.strip_thinking(text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError(f"the model did not answer in JSON: {text[:200]}")


def look(model: str, jpeg: bytes, prompt: str, schema: dict, settings: dict, timeout: float = 300) -> dict:
    """One picture and question to a local model, answered as JSON in the shape of schema."""
    body = {"model": model, "stream": False, "format": schema, "keep_alive": "15m",
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(jpeg).decode()]}]}
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5)) as c:
        r = c.post(f"{ai.ollama_url(settings)}/api/chat", json=body)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama answered {r.status_code}: {ai._ollama_error_text(r)}")
    return _json_answer((r.json().get("message") or {}).get("content", ""))


def scan_schema(tags: list[str]) -> dict:
    return {"type": "object", "required": ["seen"], "properties": {"seen": {"type": "array", "items": {
        "type": "object", "required": ["tag", "sure", "where"],
        "properties": {"tag": {"type": "string", "enum": tags}, "sure": {"type": "number"},
                       "where": {"type": "string", "enum": list(WHERE_CELLS)}, "note": {"type": "string"}}}}}}


CHECK_SCHEMA = {"type": "object", "required": ["looks_like", "sure"],
                "properties": {"looks_like": {"type": "string", "enum": ["yes", "no", "unsure"]},
                               "sure": {"type": "number"}, "note": {"type": "string"}}}
_TAGS = {t.id: t for t in SCAN_TAGS}


def scan_prompt(tags: list[str], lon: float, lat: float, km: float, country: str | None) -> str:
    lines = "\n".join(f"- {t}: {_TAGS[t].label}, which looks like {_TAGS[t].looks}" for t in tags)
    return (f"This is a satellite picture about {km:.1f} km across (10 m pixels, cloud-free, 2020), centred at "
            f"{abs(lat):.3f}°{'S' if lat < 0 else 'N'} {abs(lon):.3f}°{'W' if lon < 0 else 'E'}{f' in {country}' if country else ''}. "
            f"North is up.\nWhich of these can you clearly see in it?\n{lines}\n"
            "Only list what you can actually see; at this detail cars, small boats and single buildings are too small. "
            "For each, give the tag, how sure you are from 0 to 1, where in the picture it is "
            f"({', '.join(WHERE_CELLS)}) and a short note. An empty list is the right answer when none are there. "
            "Answer in JSON only.")


def check_prompt(layer: str, name: str, category: str | None, km: float) -> str:
    return (f"This satellite picture is about {km:.1f} km across (10 m pixels, cloud-free, 2020), north up. A map says "
            f"there is {CHECKABLE[layer]} at the centre of the picture, named \"{name}\"{f' ({category})' if category else ''}. "
            "Does the picture show one at or near the centre? Answer looks_like yes, no or unsure, how sure you are "
            "from 0 to 1, and a short note on what you see there. Answer in JSON only.")


# ----------------------------------------------------------------------------- area scans (background)
_scan_lock = threading.Lock()
_worker: dict = {"thread": None, "current": None}
_DIRTY_EVERY = 10
TILE_SECONDS = 1.5  # first guess at a square's time, before a scan has its own


def _scans_dir() -> Path:
    return _spot_dir() / "scans"


def _meta_path(sid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{6,40}", sid):
        raise ValueError("bad scan id")
    return _scans_dir() / f"{sid}.json"


def _found_path(sid: str) -> Path:
    return _scans_dir() / f"{sid}.found.json"


def _pic_dir(sid: str) -> Path:
    return _scans_dir() / sid


def scans() -> list[dict]:
    out = []
    d = _scans_dir()
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name.endswith(".found.json"):
                continue
            m = _read(p, None)
            if m:
                m.pop("todo", None)
                out.append(m)
    return sorted(out, key=lambda m: m.get("created", ""), reverse=True)


def _meta(sid: str) -> dict:
    m = _read(_meta_path(sid), None)
    if not m:
        raise KeyError(sid)
    return m


def estimate(q: Q, req: dict) -> dict:
    """How many squares (or places) a scan would look at, and roughly how long it would take."""
    todo = _todo(q, req)
    secs = len(todo) * TILE_SECONDS * (1.3 if req.get("mode") == "check" else 1)
    return {"count": len(todo), "minutes": round(secs / 60), "per": TILE_SECONDS,
            "note": "Squares mostly sea are skipped without asking the model, so land-light areas go faster."}


def _todo(q: Q, req: dict) -> list:
    g, bounds, _ = _area_shape(req.get("entity"), req.get("bbox"))
    if req.get("mode") == "check":
        from shapely import contains_xy
        import numpy as np

        layers = [l for l in req.get("layers") or [] if l in CHECKABLE]
        if not layers:
            raise ValueError(f"pick the map's places to check: {', '.join(CHECKABLE)}")
        w, s, e, n = bounds
        found = q(f"""SELECT layer_id, item_id, name, category, lat, lon FROM layer_items
                      WHERE layer_id IN ({', '.join('?' * len(layers))}) AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                      ORDER BY layer_id, name""", [*layers, s, n, w, e])
        if not found:
            return []
        inside = contains_xy(g, np.array([r["lon"] for r in found]), np.array([r["lat"] for r in found]))
        return [[r["layer_id"], r["item_id"], r["name"], r["category"], r["lon"], r["lat"]] for r, ok in zip(found, inside) if ok]
    return [[SCAN_ZOOM, x, y] for x, y in _land_tiles(g, bounds, SCAN_ZOOM)]


def scan_create(q: Q, req: dict) -> dict:
    mode = req.get("mode", "scan")
    if mode not in ("scan", "check"):
        raise ValueError("mode must be scan or check")
    tags = [t for t in req.get("tags") or [t.id for t in SCAN_TAGS] if t in _TAGS]
    if mode == "scan" and not tags:
        raise ValueError("pick at least one thing to look for")
    s = local.load_settings()
    model = req.get("model") or vision_models(s)["scan"]
    if not model:
        raise ValueError("no model that can see pictures is installed in Ollama")
    _, _, name = _area_shape(req.get("entity"), req.get("bbox"))
    todo = _todo(q, {**req, "mode": mode})
    if not todo:
        raise ValueError("nothing to look at in that area")
    sid = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    meta = {"id": sid, "name": req.get("name") or f"{'Check' if mode == 'check' else 'Scan'} of {name}", "mode": mode,
            "entity": (req.get("entity") or "").upper() or None, "bbox": req.get("bbox"), "tags": tags if mode == "scan" else [],
            "layers": [l for l in req.get("layers") or [] if l in CHECKABLE] if mode == "check" else [],
            "model": model, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": "queued", "total": len(todo), "done": 0, "skipped": 0, "found": 0, "errors": 0, "seconds": 0.0,
            "todo": todo}
    _write(_meta_path(sid), meta)
    _write(_found_path(sid), [])
    _kick()
    meta.pop("todo")
    return meta


def scan_action(sid: str, action: str) -> dict:
    with _scan_lock:
        m = _meta(sid)
        if action == "pause" and m["state"] in ("queued", "running"):
            m["state"] = "paused"
        elif action == "resume" and m["state"] in ("paused", "error", "stopped"):
            m["state"] = "queued"
            m.pop("error", None)
        elif action == "stop" and m["state"] in ("queued", "running", "paused"):
            m["state"] = "stopped"
        elif action not in ("pause", "resume", "stop"):
            raise ValueError("action must be pause, resume or stop")
        _write(_meta_path(sid), m)
    _kick()
    m.pop("todo", None)
    return m


def scan_delete(sid: str) -> bool:
    import shutil

    with _scan_lock:
        p = _meta_path(sid)
        if not p.is_file():
            return False
        m = _read(p, {})
        if m.get("state") == "running":
            m["state"] = "stopped"
            _write(p, m)
        p.unlink(missing_ok=True)
        _found_path(sid).unlink(missing_ok=True)
        shutil.rmtree(_pic_dir(sid), ignore_errors=True)
    return True


def recover() -> None:
    """At start: a scan left running when the app stopped waits, paused, until you resume it."""
    for m in scans():
        if m.get("state") in ("running", "queued"):
            with _scan_lock:
                full = _meta(m["id"])
                full["state"] = "paused"
                full["note"] = "Paused when the app stopped; Resume carries on where it was."
                _write(_meta_path(m["id"]), full)


def _kick() -> None:
    with _scan_lock:
        t = _worker.get("thread")
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_work, daemon=True, name="spot-scan")
        _worker["thread"] = t
    t.start()


def _next_queued() -> str | None:
    waiting = [m for m in scans() if m.get("state") == "queued"]
    return sorted(waiting, key=lambda m: m.get("created", ""))[0]["id"] if waiting else None


def _work(fetch: Fetch | None = None, settings: dict | None = None) -> None:
    while True:
        with _scan_lock:
            sid = _next_queued()
            if not sid:
                _worker["current"] = None
                return
            m = _meta(sid)
            m["state"] = "running"
            _write(_meta_path(sid), m)
            _worker["current"] = sid
        try:
            run_scan(sid, fetch=fetch, settings=settings)
        except Exception as exc:  # noqa: BLE001 - shown on the page
            log.warning("spotting scan %s: %s", sid, exc)
            with _scan_lock:
                m = _meta(sid)
                m.update(state="error", error=str(exc))
                _write(_meta_path(sid), m)


def run_scan(sid: str, fetch: Fetch | None = None, settings: dict | None = None, looker=None) -> dict:
    """Works through a scan's list from where it got to, saving as it goes, until done, paused or stopped."""
    s = settings or local.load_settings()
    looker = looker or look
    m = _meta(sid)
    found = _read(_found_path(sid), [])
    errors_in_row = 0
    while m["done"] < len(m["todo"]):
        with _scan_lock:
            cur = _read(_meta_path(sid), {})
            if cur.get("state") != "running":  # paused or stopped from the page
                return cur
        item = m["todo"][m["done"]]
        t0 = time.monotonic()
        try:
            hits = _look_square(m, item, s, fetch, looker) if m["mode"] == "scan" else _look_place(m, item, s, fetch, looker)
            errors_in_row = 0
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            m["errors"] += 1
            errors_in_row += 1
            m["last_error"] = str(exc)[:300]
            hits = []
            if errors_in_row >= 5:
                with _scan_lock:
                    cur = _read(_meta_path(sid), {})
                    cur.update({k: m[k] for k in ("done", "found", "errors", "skipped", "seconds", "last_error")},
                               state="error", error=f"Five squares in a row failed; the last said: {m['last_error']}")
                    _write(_meta_path(sid), cur)
                    _write(_found_path(sid), found)
                return cur
        if hits is None:
            m["skipped"] += 1
        else:
            found += hits
            m["found"] = len(found)
            m["seconds"] = round(m["seconds"] + time.monotonic() - t0, 1)
        m["done"] += 1
        if m["done"] % _DIRTY_EVERY == 0 or m["done"] == len(m["todo"]) or hits:
            with _scan_lock:
                cur = _read(_meta_path(sid), {})
                cur.update({k: m[k] for k in ("done", "found", "errors", "skipped", "seconds")})
                if "last_error" in m:
                    cur["last_error"] = m["last_error"]
                _write(_meta_path(sid), cur)
                _write(_found_path(sid), found)
                m["state"] = cur.get("state")
    with _scan_lock:
        cur = _read(_meta_path(sid), {})
        cur.update({k: m[k] for k in ("done", "found", "errors", "skipped", "seconds")}, state="done",
                   finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        _write(_meta_path(sid), cur)
        _write(_found_path(sid), found)
    return cur


def _cell_point(z: int, x: int, y: int, where: str) -> tuple[float, float]:
    i = WHERE_CELLS.index(where) if where in WHERE_CELLS else 4
    col, row = i % 3, i // 3
    n = 2 ** z
    fx, fy = x + (col + 0.5) / 3, y + (row + 0.5) / 3
    return fx / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * fy / n))))


def _look_square(m: dict, item: list, s: dict, fetch, looker) -> list[dict] | None:
    z, x, y = item
    pic = square_picture(z, x, y, fetch)
    if pic is None:
        raise RuntimeError("no satellite picture for this square")
    if _sea_share(pic) > 0.97:
        return None
    w, s_, e, n = tiles.lonlat_box(z, x, y)
    lon, lat = (w + e) / 2, (s_ + n) / 2
    c = country_at(lon, lat)
    km = CIRC / 2 ** z * math.cos(math.radians(lat)) / 1000
    ans = looker(m["model"], pic, scan_prompt(m["tags"], lon, lat, km, c[1] if c else None), scan_schema(m["tags"]), s)
    out = []
    for h in ans.get("seen") or []:
        if not isinstance(h, dict) or h.get("tag") not in m["tags"]:
            continue
        try:
            sure = max(0.0, min(1.0, float(h.get("sure", 0))))
        except (TypeError, ValueError):
            sure = 0.0
        plon, plat = _cell_point(z, x, y, str(h.get("where", "centre")))
        out.append({"id": f"{z}-{x}-{y}-{h['tag']}", "tag": h["tag"], "sure": round(sure, 2), "where": h.get("where"),
                    "note": str(h.get("note") or "")[:300], "lon": round(plon, 5), "lat": round(plat, 5),
                    "z": z, "x": x, "y": y, "country": c[0] if c else None, "mark": None})
    out = list({o["id"]: o for o in out}.values())
    if out:
        _keep_picture(m["id"], f"{z}-{x}-{y}", pic)
    return out


def _look_place(m: dict, item: list, s: dict, fetch, looker) -> list[dict] | None:
    layer, item_id, name, category, lon, lat = item
    pic = picture(lon, lat, 15, fetch=fetch)
    if pic is None:
        raise RuntimeError("no satellite picture for this place")
    data, info = pic
    ans = looker(m["model"], data, check_prompt(layer, name, category, info["km"]), CHECK_SCHEMA, s)
    verdict = ans.get("looks_like") if ans.get("looks_like") in ("yes", "no", "unsure") else "unsure"
    try:
        sure = max(0.0, min(1.0, float(ans.get("sure", 0))))
    except (TypeError, ValueError):
        sure = 0.0
    key = re.sub(r"[^A-Za-z0-9_-]", "_", f"{layer}-{item_id}")[:120]
    _keep_picture(m["id"], key, data)
    return [{"id": key, "layer": layer, "item_id": item_id, "name": name, "category": category, "verdict": verdict,
             "sure": round(sure, 2), "note": str(ans.get("note") or "")[:300], "lon": lon, "lat": lat, "mark": None}]


def _keep_picture(sid: str, key: str, data: bytes) -> None:
    d = _pic_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.jpg").write_bytes(data)


def picture_path(sid: str, key: str) -> Path | None:
    _meta_path(sid)  # checks the id
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", key):
        return None
    p = _pic_dir(sid) / f"{key}.jpg"
    return p if p.is_file() else None


def found(sid: str) -> list[dict]:
    _meta_path(sid)
    return _read(_found_path(sid), [])


def mark(sid: str, item_id: str, value: str | None) -> dict:
    """Your yes / no on one thing a scan reported (None takes the mark off)."""
    if value not in ("yes", "no", None):
        raise ValueError("mark must be yes, no or empty")
    with _scan_lock:
        items = _read(_found_path(sid), None)
        if items is None:
            raise KeyError(sid)
        hit = next((i for i in items if i["id"] == item_id), None)
        if not hit:
            raise KeyError(item_id)
        hit["mark"] = value
        _write(_found_path(sid), items)
    return hit


def hit_rates() -> list[dict]:
    """For each thing scans look for: how often the model reported it, and how often your marks said it was right."""
    rows = {t.id: {"tag": t.id, "label": t.label, "found": 0, "yes": 0, "no": 0} for t in SCAN_TAGS}
    checks: dict[str, dict] = {}
    for m in scans():
        for it in _read(_found_path(m["id"]), []):
            if m["mode"] == "scan" and it.get("tag") in rows:
                r = rows[it["tag"]]
            elif m["mode"] == "check":
                r = checks.setdefault(f"check:{it.get('verdict')}", {"tag": f"check:{it.get('verdict')}",
                                      "label": f"Check said {it.get('verdict')}", "found": 0, "yes": 0, "no": 0})
            else:
                continue
            r["found"] += 1
            if it.get("mark") in ("yes", "no"):
                r[it["mark"]] += 1
    out = [r for r in [*rows.values(), *checks.values()] if r["found"]]
    for r in out:
        marked = r["yes"] + r["no"]
        r["right_pct"] = round(r["yes"] / marked * 100) if marked else None
    return out


def layer(min_sure: float | None = None) -> list[dict]:
    """Map layer 0, Spotted by AI: what scans reported at least min_sure (not marked wrong), and the
    map's places a check said do not look like what the map says."""
    ms = local.load_settings().get("spot_min_sure", 0.6) if min_sure is None else min_sure
    out = []
    for m in scans():
        for it in _read(_found_path(m["id"]), []):
            if it.get("mark") == "no":
                continue
            if m["mode"] == "scan" and (it.get("sure", 0) >= ms or it.get("mark") == "yes"):
                out.append({"scan": m["id"], "id": it["id"], "kind": "tag", "tag": it["tag"], "label": _TAGS[it["tag"]].label if it["tag"] in _TAGS else it["tag"],
                            "sure": it.get("sure"), "note": it.get("note"), "lon": it["lon"], "lat": it["lat"], "mark": it.get("mark")})
            elif m["mode"] == "check" and it.get("verdict") == "no" and it.get("sure", 0) >= ms:
                out.append({"scan": m["id"], "id": it["id"], "kind": "check", "tag": "check_no", "label": f"Doesn't look like {it.get('layer', '').replace('_', ' ')}",
                            "name": it.get("name"), "sure": it.get("sure"), "note": it.get("note"), "lon": it["lon"], "lat": it["lat"], "mark": it.get("mark")})
    return out


def status() -> dict:
    with _scan_lock:
        cur = _worker.get("current")
    return {"running": cur, "scans": scans()}
