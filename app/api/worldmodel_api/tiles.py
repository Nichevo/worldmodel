"""Picture tiles under the map's colours: shaded relief, satellite and night lights,
with copies saved on this PC so the maps draw quickly and work offline where saved.

    relief     AWS Terrain Tiles (Terrarium heights: SRTM, GMTED and ETOPO1/GEBCO sea depths),
               free on the Registry of Open Data on AWS. The browser shades and colours them.
    satellite  Sentinel-2 cloudless by EOX (contains modified Copernicus Sentinel data, CC BY-NC-SA 4.0,
               fine for a personal tool).
    night      NASA Black Marble (2012 and 2016 composites) and last night's VIIRS picture, from NASA GIBS.

Tiles are kept as files under <data folder>/basemap/tiles/<set>/<time>/<z>/<x>/<y>.<ext>, so
they count toward the map files limit. A saved area is a box and a zoom range; areas.json
lists them with their size. The tile route serves a saved tile when there is one and
fetches the rest online (Settings > Maps > "Saved copies first"); nothing is saved while
browsing, only by "Save this area" and the starter copies.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from worldmodel_contract import local

log = logging.getLogger(__name__)

USER_AGENT = "worldmodel/0.1 (personal local tool) httpx"
GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{t}/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png"
SETS: dict[str, dict] = {
    "relief": {"url": "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "ext": "png", "maxzoom": 15,
               "kb": 70, "label": "Shaded relief",
               "attribution": "Heights: AWS Terrain Tiles (SRTM, GMTED, ETOPO1)"},
    "satellite": {"url": "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg", "ext": "jpg",
                  "maxzoom": 15, "kb": 30, "label": "Satellite",
                  "attribution": "Sentinel-2 cloudless 2020 by EOX (Copernicus Sentinel data 2020)"},
    "night": {"url": GIBS, "ext": "png", "maxzoom": 8, "kb": 45, "label": "Night lights",
              "times": {"2016": ("VIIRS_Black_Marble", "2016-01-01"), "2012": ("VIIRS_Black_Marble", "2012-01-01"),
                        "latest": ("VIIRS_SNPP_DayNightBand_ENCC", None)},
              "attribution": "Night lights: NASA Earth Observatory Black Marble, VIIRS (NASA GIBS)"},
}
# The starter copies (Settings > Maps): world relief to zoom 6, New Zealand's relief and satellite
# closer in, and the newest yearly night lights for the whole world at overview zoom.
NZ = (165.8, -47.5, 178.9, -34.0)
WORLD = (-180.0, -85.0, 180.0, 85.0)
STARTER = [
    {"id": "starter-relief-world", "set": "relief", "t": "-", "name": "World", "bbox": WORLD, "minzoom": 0, "maxzoom": 6},
    {"id": "starter-relief-nzl", "set": "relief", "t": "-", "name": "New Zealand", "bbox": NZ, "minzoom": 7, "maxzoom": 10},
    {"id": "starter-satellite-world", "set": "satellite", "t": "-", "name": "World", "bbox": WORLD, "minzoom": 0, "maxzoom": 4},
    {"id": "starter-satellite-nzl", "set": "satellite", "t": "-", "name": "New Zealand", "bbox": NZ, "minzoom": 5, "maxzoom": 11},
    {"id": "starter-night-world", "set": "night", "t": "2016", "name": "World", "bbox": WORLD, "minzoom": 0, "maxzoom": 6},
]
WORKERS = 2          # tiles fetched at once while saving
MAX_TILES = 400_000  # one saved area at most

_lock = threading.Lock()
_job: dict = {"state": "idle"}
_client_lock = threading.Lock()
_client: httpx.Client | None = None


def root() -> Path:
    return local.home() / "basemap" / "tiles"


def _http() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        return _client


def _human(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


# ----------------------------------------------------------------------------- tile maths
def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    lat = max(-85.0511, min(85.0511, lat))
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_in(bbox: tuple[float, float, float, float], z: int):
    """Every tile (x, y) at zoom z touching the box (west may be more than east across the date line)."""
    w, s, e, n = bbox
    spans = [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]
    for a, b in spans:
        x0, y0 = tile_of(a, n, z)
        x1, y1 = tile_of(b, s, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield x, y


def count(bbox, minzoom: int, maxzoom: int) -> int:
    total = 0
    for z in range(minzoom, maxzoom + 1):
        w, s, e, n = bbox
        spans = [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]
        for a, b in spans:
            x0, y0 = tile_of(a, n, z)
            x1, y1 = tile_of(b, s, z)
            total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


# ----------------------------------------------------------------------------- where tiles come from
def _time(set_id: str, t: str | None) -> tuple[str, str]:
    """(folder name, url time) for a set: relief and satellite have one picture, night lights several."""
    st = SETS[set_id]
    if "times" not in st:
        return "-", ""
    key = t if t in st["times"] else "2016"
    layer, when = st["times"][key]
    if when is None:  # last night: yesterday's picture (today's is still being made)
        when = (date.today() - timedelta(days=1)).isoformat()
        return f"latest-{when}", when
    return key, when


def upstream(set_id: str, z: int, x: int, y: int, t: str | None = None) -> str:
    st = SETS[set_id]
    if "times" in st:
        key = t if t in st["times"] else "2016"
        layer = st["times"][key][0]
        _, when = _time(set_id, key)
        return st["url"].format(layer=layer, t=when, z=z, x=x, y=y)
    return st["url"].format(z=z, x=x, y=y)


def path_of(set_id: str, folder: str, z: int, x: int, y: int) -> Path:
    return root() / set_id / folder / str(z) / str(x) / f"{y}.{SETS[set_id]['ext']}"


def tile(set_id: str, z: int, x: int, y: int, t: str | None = None, online: bool = True) -> tuple[bytes, str] | None:
    """A tile's bytes and media type: the saved copy if there is one, else online (not saved)."""
    if set_id not in SETS or z < 0 or z > SETS[set_id]["maxzoom"] or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    media = "image/jpeg" if SETS[set_id]["ext"] == "jpg" else "image/png"
    folder, _ = _time(set_id, t)
    p = path_of(set_id, folder, z, x, y)
    if p.is_file():
        return p.read_bytes(), media
    if not online:
        return None
    try:
        r = _http().get(upstream(set_id, z, x, y, t))
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content:
        return None
    return r.content, r.headers.get("content-type", media)


# ----------------------------------------------------------------------------- saved areas
def _areas_file() -> Path:
    return root() / "areas.json"


def areas() -> list[dict]:
    try:
        return json.loads(_areas_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_areas(rows: list[dict]) -> None:
    _areas_file().parent.mkdir(parents=True, exist_ok=True)
    _areas_file().write_text(json.dumps(rows, indent=1), encoding="utf-8")


def status() -> dict:
    s = local.load_settings()
    with _lock:
        job = dict(_job)
    rows = areas()
    have = {a["id"] for a in rows}
    return {"sets": [{"id": k, "label": v["label"], "maxzoom": v["maxzoom"], "attribution": v["attribution"],
                      "times": list(v.get("times", {}))} for k, v in SETS.items()],
            "areas": rows, "bytes": sum(a.get("bytes", 0) for a in rows), "size": _human(sum(a.get("bytes", 0) for a in rows)),
            "job": job, "mode": s["map_tiles"], "starter": s["map_tiles_starter"],
            "starter_done": all(a["id"] in have for a in STARTER), "starter_size": _human(sum(estimate_bytes(a) for a in STARTER))}


def estimate_bytes(area: dict) -> float:
    return count(tuple(area["bbox"]), area["minzoom"], area["maxzoom"]) * SETS[area["set"]]["kb"] * 1000


def check(area: dict) -> dict:
    """How many tiles and roughly how big; whether it fits the map files limit and the disk."""
    st = SETS.get(area.get("set", ""))
    if not st:
        raise ValueError("unknown picture set")
    maxzoom = min(int(area["maxzoom"]), st["maxzoom"])
    minzoom = max(0, min(int(area.get("minzoom", 0)), maxzoom))
    n = count(tuple(area["bbox"]), minzoom, maxzoom)
    need = n * st["kb"] * 1000
    s = local.load_settings()
    used = local._size(local.home() / "basemap")
    limit = s["basemap_limit_gb"] * local.GB
    free = shutil.disk_usage(local.home() if local.home().exists() else Path.cwd()).free
    why = None
    if n > MAX_TILES:
        why = f"{n:,} tiles is more than one area may hold ({MAX_TILES:,}); pick a smaller area or zoom"
    elif used + need > limit:
        why = f"needs about {_human(need)} but the map files limit leaves {_human(max(0, limit - used))} (Settings > Storage)"
    elif need > free:
        why = f"needs about {_human(need)} but the disk has {_human(free)} free"
    return {"tiles": n, "bytes": need, "size": _human(need), "fits": why is None, "why": why,
            "minzoom": minzoom, "maxzoom": maxzoom}


def save(area: dict) -> dict:
    """Start saving an area in the background (one job at a time; more wait their turn)."""
    c = check(area)
    if not c["fits"]:
        raise ValueError(c["why"])
    area = {**area, "minzoom": c["minzoom"], "maxzoom": c["maxzoom"], "bbox": [float(v) for v in area["bbox"]]}
    area.setdefault("t", "-")
    area.setdefault("id", f"{area['set']}-{area.get('t', '-')}-{int(time.time())}")
    return _queue([area])


def start_starter() -> dict:
    have = {a["id"] for a in areas()}
    todo = [dict(a) for a in STARTER if a["id"] not in have]
    return _queue(todo) if todo else status()["job"]


_waiting: list[dict] = []


def _queue(items: list[dict]) -> dict:
    with _lock:
        _waiting.extend(items)
        if _job.get("state") == "running":
            return dict(_job)
        _job.clear()
        _job.update(state="running", step="Getting ready", done=0, total=0,
                    started=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    threading.Thread(target=_work, daemon=True, name="tiles").start()
    with _lock:
        return dict(_job)


def _work() -> None:
    while True:
        with _lock:
            if not _waiting:
                _job.update(state="done", step="Saved", finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                return
            area = _waiting.pop(0)
        try:
            _save_one(area)
        except Exception as exc:  # noqa: BLE001 - shown on the Settings page
            log.warning("tiles: %s", exc)
            with _lock:
                _job.update(state="failed", error=f"{area.get('name', 'area')}: {exc}")
                _waiting.clear()
            return


def _save_one(area: dict) -> None:
    set_id, t = area["set"], area.get("t", "-")
    folder, _ = _time(set_id, None if t == "-" else t)
    todo = [(z, x, y) for z in range(area["minzoom"], area["maxzoom"] + 1) for x, y in tiles_in(tuple(area["bbox"]), z)]
    label = f"{SETS[set_id]['label']}, {area.get('name', 'area')}"
    with _lock:
        _job.update(step=f"Saving {label}", done=0, total=len(todo))
    written = 0
    failed = 0

    def one(zxy):
        z, x, y = zxy
        p = path_of(set_id, folder, z, x, y)
        if p.is_file():
            return p.stat().st_size, False
        try:
            r = _http().get(upstream(set_id, z, x, y, None if t == "-" else t))
        except httpx.HTTPError:
            return 0, True
        if r.status_code == 404:  # nothing there (open sea at depth on some sets): fine
            return 0, False
        if r.status_code != 200:
            return 0, True
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        return len(r.content), False

    with ThreadPoolExecutor(WORKERS) as pool:
        for i, (n, bad) in enumerate(pool.map(one, todo), 1):
            written += n
            failed += bad
            if failed > 50 and failed > i // 10:
                raise RuntimeError(f"the picture site stopped answering ({failed} tiles failed); try again later")
            if i % 200 == 0:
                with _lock:
                    _job["done"] = i
    rows = [a for a in areas() if a["id"] != area["id"]]
    rows.append({**area, "t": t, "folder": folder, "tiles": len(todo), "bytes": written, "missing": failed,
                 "saved": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _write_areas(rows)
    with _lock:
        _job["done"] = len(todo)


def remove(area_id: str) -> bool:
    """Delete a saved area's tiles (those no other saved area of the same set also holds)."""
    rows = areas()
    area = next((a for a in rows if a["id"] == area_id), None)
    if not area:
        return False
    rest = [a for a in rows if a["id"] != area_id]
    others = [a for a in rest if a["set"] == area["set"] and a.get("folder") == area.get("folder")]

    folder = area.get("folder", "-")
    for z in range(area["minzoom"], area["maxzoom"] + 1):
        cover = {xy for o in others if o["minzoom"] <= z <= o["maxzoom"] for xy in tiles_in(tuple(o["bbox"]), z)}
        for x, y in tiles_in(tuple(area["bbox"]), z):
            if (x, y) in cover:
                continue
            p = path_of(area["set"], folder, z, x, y)
            if p.is_file():
                p.unlink()
    _write_areas(rest)
    return True


def country_box(iso3: str) -> tuple[float, float, float, float] | None:
    """A country's bounding box from the app's country shapes (the main part when it crosses the date line)."""
    shapes = Path(__file__).resolve().parents[2] / "web" / "public" / "geo" / "countries.json"
    try:
        geo = json.loads(shapes.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    for f in geo.get("features", []):
        if (f.get("properties") or {}).get("iso3") != iso3.upper():
            continue
        pts = []
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for ring in poly:
                pts.extend(ring)
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        w, e = min(lons), max(lons)
        if e - w > 300:  # across the date line (Fiji, Russia, New Zealand's islands): shift west longitudes
            shifted = [lon + 360 if lon < 0 else lon for lon in lons]
            w, e = min(shifted), max(shifted)
            w, e = (w + 180) % 360 - 180, (e + 180) % 360 - 180
        return (round(w, 3), round(min(lats), 3), round(e, 3), round(max(lats), 3))
    return None
