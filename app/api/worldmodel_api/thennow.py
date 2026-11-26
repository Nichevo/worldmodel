"""Then and now (Spotting page, part 2): which pictures of a place there are and when they were taken,
a place's before and after pictures side by side for the local AI, and Landsat timelapses since 1984.

    Surveys       LINZ's list of aerial photo surveys of New Zealand (about 760, from the 1930s to now)
                  and the outline each covers, read once from LINZ's public catalogue on AWS and kept in
                  <data folder>/basemap/linz_surveys.json (read again after 30 days). The pictures
                  themselves come through tiles.py's "aerial" set (LINZ Basemaps, free key).
    Esri versions Esri's World Imagery Wayback: which of its ~200 versions since 2014 changed the picture
                  at a place (its "tilemap" says which version each version's tile really comes from).
                  Only the dates are read here; the browser shows Esri's pictures itself, and they are
                  never saved or sent to AI (Esri's terms).
    Pair          a place's two pictures side by side with their dates, for "What changed?". An Esri
                  picture is swapped for the nearest LINZ survey (New Zealand) or EOX year (elsewhere).
    Timelapse     one Landsat picture a year since 1984 for a box (the least cloudy, from the summer
                  months if you like), from Microsoft Planetary Computer, and from the same pictures the
                  hectares of water, green land and built-up or bare land each year. Made once per box,
                  in the background, one at a time, and kept in <your folder>/spotting/timelapse/<id>.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from worldmodel_contract import local
from worldmodel_contract.thennow import (EOX_YEARS, LANDSAT_FIRST, LINZ_KEY_ENV, LANDSAT_INDEX, LANDSAT_RGB, LINZ_BASE, LINZ_CATALOG,
                                         NZ_PLACES, PC_ITEM_TILE, PC_STAC, TIMELAPSE_ATTRIBUTION, TIMELAPSE_MAX_KM,
                                         TIMELAPSE_MAX_TILES, WAYBACK_CONFIG, WAYBACK_TILEMAP, WAYBACK_ZOOM, ai_ok,
                                         in_nz, landsat_platforms, layer_ok, linz_layer, summer_months)
from worldmodel_api import tiles

log = logging.getLogger(__name__)
Get = Callable[[str], httpx.Response]
CIRC = 40_075_016.686
INDEX_DAYS = 30


def _http() -> httpx.Client:
    return tiles._http()


def _get(url: str) -> httpx.Response:
    return _http().get(url)


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(p)


# ----------------------------------------------------------------------------- LINZ surveys
_idx_lock = threading.Lock()
_idx: dict = {"rows": None, "shapes": None, "state": "idle", "error": None, "thread": None}


def _index_file() -> Path:
    return local.home() / "basemap" / "linz_surveys.json"


def parse_title(title: str) -> dict:
    """Years, detail and kind from a survey's title, e.g. 'Christchurch 0.075m Urban Aerial Photos (2015-2016)'."""
    yrs = re.search(r"\((\d{4})(?:-(\d{4}))?\)", title or "")
    gsd = re.search(r"(\d+(?:\.\d+)?)m\b", title or "")
    kind = "satellite" if "Satellite" in title else "historical" if re.search(r"\bSN ?\d", title) else \
        "urban" if "Urban" in title else "rural" if "Rural" in title else "other"
    y0 = int(yrs.group(1)) if yrs else None
    return {"year_from": y0, "year_to": int(yrs.group(2)) if yrs and yrs.group(2) else y0,
            "gsd": float(gsd.group(1)) if gsd else None, "kind": kind}


def build_index(get: Get | None = None, workers: int = 8) -> list[dict]:
    """Read LINZ's catalogue and each survey's outline (natural colour surveys only, not near-infrared)."""
    from shapely.geometry import mapping, shape

    get = get or _get
    r = get(LINZ_CATALOG)
    r.raise_for_status()
    kids = [l for l in r.json().get("links", []) if l.get("rel") == "child" and "/rgb/" in l.get("href", "")]

    def one(link: dict) -> dict | None:
        href = link["href"].lstrip("./")
        parts = href.split("/")
        if len(parts) < 2:
            return None
        slug = parts[1]
        title = link.get("title") or slug
        if "Near-Infrared" in title:
            return None
        row = {"slug": slug, "layer": linz_layer(slug), "title": title.replace(" - Draft", ""), "region": parts[0],
               "draft": "Draft" in title, **parse_title(title)}
        try:
            g = get(LINZ_BASE + href.rsplit("/", 1)[0] + "/capture-area.geojson")
            if g.status_code != 200:
                return None
            gj = g.json()
            geom = gj.get("geometry") or (gj.get("features") or [{}])[0].get("geometry")
            shp = shape(geom).simplify(0.0005, preserve_topology=False)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            return None
        if shp.is_empty:
            return None
        row["bbox"] = [round(v, 4) for v in shp.bounds]
        row["area"] = json.loads(json.dumps(mapping(shp)))
        return row

    with ThreadPoolExecutor(workers) as pool:
        rows = [r for r in pool.map(one, kids) if r]
    rows.sort(key=lambda r: (-(r["year_to"] or 0), r["gsd"] or 9))
    return rows


def _load_shapes(rows: list[dict]):
    from shapely.geometry import shape
    return [shape(r["area"]) for r in rows]


def _index_work() -> None:
    try:
        rows = build_index()
        if not rows:
            raise RuntimeError("LINZ's catalogue listed no surveys")
        _write(_index_file(), {"built": date.today().isoformat(), "surveys": rows})
        with _idx_lock:
            _idx.update(rows=rows, shapes=_load_shapes(rows), state="done", error=None)
    except Exception as exc:  # noqa: BLE001 - shown on the page
        log.warning("then and now: could not read LINZ's list of surveys: %s", exc)
        with _idx_lock:
            _idx.update(state="error", error=f"Could not read LINZ's list of surveys: {exc}")


def surveys() -> tuple[list[dict] | None, list | None, dict]:
    """(surveys, their outlines, state). Read from the saved list, and from LINZ in the background when
    there is none yet or it is over 30 days old."""
    with _idx_lock:
        if _idx["rows"] is None:
            saved = _read(_index_file(), None)
            if saved and saved.get("surveys"):
                _idx["rows"] = saved["surveys"]
                _idx["shapes"] = _load_shapes(saved["surveys"])
                _idx["built"] = saved.get("built")
        stale = not _idx.get("built") or (date.today() - date.fromisoformat(_idx["built"])).days > INDEX_DAYS
        if (_idx["rows"] is None or stale) and _idx["state"] != "running" and not (_idx["state"] == "error" and _idx["rows"] is None
                                                                                 and _idx.get("tried", 0) > time.time() - 600):
            _idx.update(state="running", tried=time.time())
            if _idx["rows"] is not None:
                _idx["built"] = date.today().isoformat()  # do not start again while this one runs
            t = threading.Thread(target=_index_work, daemon=True, name="linz-surveys")
            _idx["thread"] = t
            t.start()
        return _idx["rows"], _idx["shapes"], {"state": _idx["state"], "error": _idx["error"], "built": _idx.get("built")}


def surveys_at(lon: float, lat: float, rows: list[dict] | None = None, shapes=None) -> list[dict]:
    """LINZ surveys whose photos cover a point, newest first."""
    from shapely.geometry import Point

    if rows is None:
        rows, shapes, _ = surveys()
    if not rows:
        return []
    p = Point(lon, lat)
    out = []
    for r, g in zip(rows, shapes or _load_shapes(rows)):
        w, s, e, n = r["bbox"]
        if w <= lon <= e and s <= lat <= n and g.covers(p):
            out.append({k: r[k] for k in ("layer", "title", "year_from", "year_to", "gsd", "kind", "region")})
    return out


# ----------------------------------------------------------------------------- Esri Wayback versions
_wb: dict = {"at": 0.0, "releases": None}


def wayback_releases(get: Get | None = None) -> list[dict]:
    """Esri's Wayback versions, newest first: [{release, date}] (the config is read once a day)."""
    if _wb["releases"] is not None and time.time() - _wb["at"] < 86400 and get is None:
        return _wb["releases"]
    r = (get or _get)(WAYBACK_CONFIG)
    r.raise_for_status()
    out = []
    for num, item in r.json().items():
        m = re.search(r"(\d{4}-\d{2}-\d{2})", item.get("itemTitle", ""))
        if m and str(num).isdigit():
            out.append({"release": int(num), "date": m.group(1)})
    out.sort(key=lambda x: x["date"], reverse=True)
    if get is None:
        _wb.update(at=time.time(), releases=out)
    return out


def wayback_changes(lon: float, lat: float, get: Get | None = None, zoom: int = WAYBACK_ZOOM, most: int = 60) -> list[dict]:
    """The Esri versions whose picture of this place differs from the one before: start at the newest,
    ask which version its tile really comes from, then carry on from the version before that one."""
    get = get or _get
    rel = wayback_releases(None if get is _get else get)
    if not rel:
        return []
    order = [r["release"] for r in rel]
    when = {r["release"]: r["date"] for r in rel}
    x, y = tiles.tile_of(lon, lat, zoom)
    out: list[dict] = []
    i = 0
    while i < len(order) and len(out) < most:
        r = get(WAYBACK_TILEMAP.format(release=order[i], z=zoom, y=y, x=x))
        if r.status_code != 200:
            break
        j = r.json()
        if not (j.get("data") or [0])[0]:
            break
        got = (j.get("select") or [order[i]])[0]
        if got not in when:
            break
        out.append({"release": got, "date": when[got]})
        i = order.index(got) + 1
    return out


# ----------------------------------------------------------------------------- what pictures there are
def dates(lon: float, lat: float) -> dict:
    """Every picture of a place the Then and now tab can show: LINZ surveys (New Zealand), EOX years and
    Esri's current picture. Esri's older versions come from wayback_changes (slower, asked separately)."""
    nz = in_nz(lon, lat)
    rows, shapes, st = surveys() if nz else (None, None, {"state": "not needed"})
    return {"lon": round(lon, 5), "lat": round(lat, 5), "nz": nz, "linz": surveys_at(lon, lat, rows, shapes) if rows else [],
            "linz_list": st, "linz_key": bool(os.environ.get(LINZ_KEY_ENV, "").strip()),
            "eox": sorted(EOX_YEARS, reverse=True), "places": {k: list(v) for k, v in NZ_PLACES.items()}}


# ----------------------------------------------------------------------------- the pair for AI
def _source_year(src: str) -> int | None:
    kind, _, rest = src.partition(":")
    m = re.search(r"(19|20)\d{2}", rest)
    if kind == "esri":
        return date.today().year
    return int(m.group(0)) if m else None


def resolve(src: str, lon: float, lat: float, linz: list[dict] | None = None) -> tuple[str, str | None, str, str | None]:
    """(tile set, time, label, note) to read a picture source for the AI. Esri's are swapped for the
    nearest LINZ survey (New Zealand) or EOX year."""
    kind, _, rest = src.partition(":")
    if kind == "linz" and layer_ok(rest):
        row = next((r for r in (linz or []) if r["layer"] == rest), None)
        return "aerial", rest, (row["title"] if row else rest), None
    if kind == "eox" and rest in EOX_YEARS:
        return "satyears", rest, f"Sentinel-2 cloudless {rest} (EOX, 10 m)", None
    if kind == "sat":
        return "satellite", None, "Sentinel-2 cloudless 2020 (EOX, 10 m)", None
    if kind in ("esri", "wayback"):
        year = int(rest[:4]) if kind == "wayback" and re.match(r"\d{4}", rest) else date.today().year
        cands = [r for r in (linz or []) if r.get("year_to")]
        if cands:
            best = min(cands, key=lambda r: (abs(r["year_to"] - year), r["gsd"] or 9))
            return "aerial", best["layer"], best["title"], f"Esri's picture is for looking only, so the AI gets {best['title']} instead"
        yr = str(min((int(y) for y in EOX_YEARS), key=lambda y: (abs(y - year), -y)))
        return "satyears", yr, f"Sentinel-2 cloudless {yr} (EOX, 10 m)", f"Esri's picture is for looking only, so the AI gets the {yr} Sentinel-2 picture (10 m) instead"
    raise ValueError(f"unknown picture source {src!r}")


def pair(lon: float, lat: float, zoom: int, a: str, b: str, fetch=None, size: int = 512) -> dict:
    """Two pictures of a place side by side (before left, after right) with their names written above,
    as one JPEG for the local AI."""
    from PIL import Image, ImageDraw

    from worldmodel_api import spotting

    linz = surveys_at(lon, lat) if in_nz(lon, lat) else []
    out = {"lon": round(lon, 5), "lat": round(lat, 5), "notes": []}
    pics = []
    for key, src in (("before", a), ("after", b)):
        set_id, t, label, note = resolve(src, lon, lat, linz)
        if not ai_ok(f"{'linz' if set_id == 'aerial' else 'eox' if set_id == 'satyears' else 'sat'}:{t}"):
            raise ValueError("that picture may not be sent to AI")
        z = min(zoom, tiles.SETS[set_id]["maxzoom"])
        got = spotting.picture(lon, lat, z, size, set_id=set_id, t=t, fetch=fetch)
        if not got:
            hint = " (is LINZ_BASEMAPS_API_KEY set under Data status > Keys you can add?)" if set_id == "aerial" else ""
            raise RuntimeError(f"no picture could be had for {label}{hint}")
        pics.append(Image.open(io.BytesIO(got[0])).convert("RGB"))
        out[key] = {"label": label, "set": set_id, "t": t}
        out["km"] = got[1]["km"]
        if note:
            out["notes"].append(note)
    bar = 30
    canvas = Image.new("RGB", (size * 2 + 8, size + bar), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    for i, (im, key) in enumerate(zip(pics, ("before", "after"))):
        canvas.paste(im, (i * (size + 8), bar))
        d.text((i * (size + 8) + 6, 8), f"{'BEFORE' if i == 0 else 'AFTER'}: {out[key]['label']}"[:90], fill=(0, 0, 0))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=88)
    out["jpeg"] = buf.getvalue()
    out["picture"] = "data:image/jpeg;base64," + base64.b64encode(out["jpeg"]).decode()
    return out


# ----------------------------------------------------------------------------- Landsat timelapse
_tl_lock = threading.Lock()
_tl_worker: dict = {"thread": None, "current": None}


def _tl_dir() -> Path:
    return local.user_dir() / "spotting" / "timelapse"


def _tl_meta_path(tid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{6,60}", tid):
        raise ValueError("bad timelapse id")
    return _tl_dir() / tid / "meta.json"


def timelapses() -> list[dict]:
    d = _tl_dir()
    out = [m for p in sorted(d.glob("*/meta.json")) if (m := _read(p, None))] if d.is_dir() else []
    return sorted(out, key=lambda m: m.get("created", ""), reverse=True)


def box_km(bbox) -> tuple[float, float]:
    w, s, e, n = bbox
    mid = math.radians((s + n) / 2)
    return (e - w) * 111.32 * math.cos(mid), (n - s) * 111.32


def tile_zoom(bbox, most: int = TIMELAPSE_MAX_TILES) -> int:
    """The closest zoom (12 at most, about 30 m) at which the box fits in `most` tiles."""
    for z in range(12, 4, -1):
        if sum(1 for _ in tiles.tiles_in(tuple(bbox), z)) <= most:
            return z
    return 5


def timelapse_create(req: dict) -> dict:
    bbox = [float(v) for v in req.get("bbox") or []]
    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise ValueError("give a box: west, south, east, north")
    wkm, hkm = box_km(bbox)
    if max(wkm, hkm) > TIMELAPSE_MAX_KM:
        raise ValueError(f"the box is {max(wkm, hkm):.0f} km across; zoom in to {TIMELAPSE_MAX_KM} km or less")
    if max(wkm, hkm) < 1:
        raise ValueError("the box is under 1 km across; Landsat's 30 m pixels would show very little")
    name = str(req.get("name") or "").strip()[:80] or f"{(bbox[1] + bbox[3]) / 2:.2f}, {(bbox[0] + bbox[2]) / 2:.2f}"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "box"
    tid = f"{slug}-{uuid.uuid4().hex[:6]}"
    s = local.load_settings()
    meta = {"id": tid, "name": name, "bbox": [round(v, 5) for v in bbox], "km": [round(wkm, 1), round(hkm, 1)],
            "zoom": tile_zoom(bbox), "summers": bool(req.get("summers", s.get("timelapse_summers", True))),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "state": "queued",
            "years": [], "done": 0, "total": date.today().year - LANDSAT_FIRST + 1, "attribution": TIMELAPSE_ATTRIBUTION}
    _write(_tl_meta_path(tid), meta)
    _tl_kick()
    return meta


def timelapse_delete(tid: str) -> bool:
    p = _tl_meta_path(tid)
    if not p.is_file():
        return False
    with _tl_lock:
        m = _read(p, {})
        if m.get("state") in ("running", "queued"):
            m["state"] = "stopped"
            _write(p, m)
    shutil.rmtree(p.parent, ignore_errors=True)
    return True


def frame_path(tid: str, year: int) -> Path | None:
    p = _tl_meta_path(tid).parent / f"{int(year)}.jpg"
    return p if p.is_file() else None


def timelapse_recover() -> None:
    for m in timelapses():
        if m.get("state") in ("running", "queued"):
            with _tl_lock:
                m["state"] = "queued"
                _write(_tl_meta_path(m["id"]), m)
    if any(m.get("state") == "queued" for m in timelapses()):
        _tl_kick()


def _tl_kick() -> None:
    with _tl_lock:
        t = _tl_worker.get("thread")
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_tl_work, daemon=True, name="timelapse")
        _tl_worker["thread"] = t
    t.start()


def _tl_work() -> None:
    while True:
        with _tl_lock:
            waiting = sorted((m for m in timelapses() if m.get("state") == "queued"), key=lambda m: m["created"])
            if not waiting:
                _tl_worker["current"] = None
                return
            m = waiting[0]
            m["state"] = "running"
            _write(_tl_meta_path(m["id"]), m)
            _tl_worker["current"] = m["id"]
        try:
            run_timelapse(m["id"])
        except Exception as exc:  # noqa: BLE001 - shown on the page
            log.warning("timelapse %s: %s", m["id"], exc)
            with _tl_lock:
                cur = _read(_tl_meta_path(m["id"]), None)
                if cur:
                    cur.update(state="error", error=str(exc)[:300])
                    _write(_tl_meta_path(m["id"]), cur)


def season(year: int, lat: float, summers: bool) -> str:
    """The STAC date range to look in for a year's picture: its summer, or the whole year."""
    if not summers:
        return f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z"
    a, b = summer_months(lat)
    if a > b:  # December of the year before to March
        return f"{year - 1}-{a:02d}-01T00:00:00Z/{year}-{b:02d}-{_month_end(year, b)}T23:59:59Z"
    return f"{year}-{a:02d}-01T00:00:00Z/{year}-{b:02d}-{_month_end(year, b)}T23:59:59Z"


def _month_end(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


def pick_scene(features: list[dict], bbox) -> dict | None:
    """The least cloudy scene that covers the whole box (else the least cloudy one at all)."""
    w, s, e, n = bbox

    def covers(f):
        b = f.get("bbox") or [0, 0, 0, 0]
        return b[0] <= w and b[1] <= s and b[2] >= e and b[3] >= n
    feats = sorted(features, key=lambda f: (not covers(f), (f.get("properties") or {}).get("eo:cloud_cover", 100)))
    return feats[0] if feats else None


def find_scene(year: int, bbox, summers: bool, post=None) -> dict | None:
    lat = (bbox[1] + bbox[3]) / 2
    body = {"collections": ["landsat-c2-l2"], "bbox": bbox, "datetime": season(year, lat, summers), "limit": 30,
            "query": {"eo:cloud_cover": {"lt": 40}, "platform": {"in": landsat_platforms(year)}},
            "sortby": [{"field": "eo:cloud_cover", "direction": "asc"}]}
    r = (post or (lambda u, j: _http().post(u, json=j, timeout=60)))(PC_STAC, body)
    if r.status_code != 200:
        raise RuntimeError(f"Planetary Computer's search answered {r.status_code}")
    return pick_scene(r.json().get("features") or [], bbox)


def _mosaic(item: str, query: str, z: int, bbox, get: Get):
    """The box's picture from one scene, put together from the data API's tiles (RGBA; clear where no data)."""
    from PIL import Image

    xs = [x for x, _ in tiles.tiles_in(tuple(bbox), z)]
    ys = [y for _, y in tiles.tiles_in(tuple(bbox), z)]
    x0, y0 = min(xs), min(ys)
    canvas = Image.new("RGBA", ((max(xs) - x0 + 1) * 256, (max(ys) - y0 + 1) * 256), (0, 0, 0, 0))

    def one(xy):
        x, y = xy
        r = get(PC_ITEM_TILE.format(z=z, x=x, y=y, item=item, query=query))
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            return xy, None
        return xy, Image.open(io.BytesIO(r.content)).convert("RGBA")

    with ThreadPoolExecutor(4) as pool:
        for (x, y), im in pool.map(one, list(tiles.tiles_in(tuple(bbox), z))):
            if im is not None:
                canvas.paste(im, ((x - x0) * 256, (y - y0) * 256))
    # crop to the box
    n = 2 ** z
    fx = lambda lon: ((lon + 180) / 360 * n - x0) * 256  # noqa: E731
    fy = lambda lat: ((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n - y0) * 256  # noqa: E731
    w, s, e, nn = bbox
    return canvas.crop((round(fx(w)), round(fy(nn)), round(fx(e)), round(fy(s))))


def measure(index_rgba, z: int, lat: float) -> dict:
    """Hectares of water, green and built-up or bare land in a picture of the three index bytes."""
    import numpy as np

    a = np.asarray(index_rgba)
    ok = a[:, :, 3] > 0
    px_ha = (CIRC / 2 ** z / 256 * math.cos(math.radians(lat))) ** 2 / 10_000
    out = {"water": 0.0, "green": 0.0, "built": 0.0}
    if not ok.any():
        return {**out, "seen": 0.0}
    wv, gv, bv = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    water = ok & (wv > 140)
    green = ok & ~water & (gv > 166)
    built = ok & ~water & ~green & (bv > 127) & (gv < 153)
    out["water"] = round(float(water.sum()) * px_ha, 1)
    out["green"] = round(float(green.sum()) * px_ha, 1)
    out["built"] = round(float(built.sum()) * px_ha, 1)
    out["seen"] = round(float(ok.mean()), 3)
    return out


def run_timelapse(tid: str, get: Get | None = None, post=None) -> dict:
    """Make a timelapse's frames and figures, year by year, saving as it goes (a stopped one carries on)."""
    get = get or _get
    m = _read(_tl_meta_path(tid), None)
    if not m:
        raise KeyError(tid)
    bbox, z = m["bbox"], m["zoom"]
    lat = (bbox[1] + bbox[3]) / 2
    have = {y["year"] for y in m.get("years", [])}
    fails = 0
    for year in range(LANDSAT_FIRST, date.today().year + 1):
        cur = _read(_tl_meta_path(tid), None)
        if not cur or cur.get("state") != "running":
            return cur or m
        if year in have:
            continue
        row: dict = {"year": year}
        try:
            f = find_scene(year, bbox, m["summers"], post)
            if f is None:
                row["missing"] = "no cloud-free picture that year"
            else:
                props = f.get("properties") or {}
                rgb = _mosaic(f["id"], LANDSAT_RGB, z, bbox, get)
                idx = _mosaic(f["id"], LANDSAT_INDEX, z, bbox, get)
                frame = rgb.convert("RGB")
                buf = io.BytesIO()
                frame.save(buf, "JPEG", quality=82)
                (_tl_meta_path(tid).parent / f"{year}.jpg").write_bytes(buf.getvalue())
                row.update(scene=f["id"], date=str(props.get("datetime", ""))[:10], cloud=props.get("eo:cloud_cover"),
                           platform=props.get("platform"), **measure(idx, z, lat))
            fails = 0
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            fails += 1
            row["missing"] = f"could not be read: {exc}"[:200]
            if fails >= 5:
                raise RuntimeError(f"five years in a row failed; the last said: {exc}") from exc
        with _tl_lock:
            cur = _read(_tl_meta_path(tid), None)
            if not cur:
                return m
            cur["years"] = sorted([*[y for y in cur.get("years", []) if y["year"] != year], row], key=lambda y: y["year"])
            cur["done"] = len(cur["years"])
            _write(_tl_meta_path(tid), cur)
    with _tl_lock:
        cur = _read(_tl_meta_path(tid), {})
        cur.update(state="done", finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        _write(_tl_meta_path(tid), cur)
    return cur


def tl_status() -> dict:
    with _tl_lock:
        cur = _tl_worker.get("current")
    return {"running": cur, "timelapses": timelapses()}
