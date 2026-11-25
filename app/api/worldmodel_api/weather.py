"""Weather now and forecasts for the map, read from the internet while a weather layer is on:

    forecast maps  NOAA GFS (the free global model), from NOAA's NOMADS subset service: 2 m temperature,
                   rain rate, total cloud, 10 m wind and sea-level pressure, every 3 hours for the next
                   days (Settings > Climate > Weather), at 1°, 0.5° or 0.25°. One run is downloaded at a time,
                   kept under <data folder>/weather/gfs/<detail>/<run>/ and the older run deleted once the new
                   one is complete, so the folder never grows past two runs. Tiles are drawn here.
    satellite      NASA GIBS geostationary infrared (Himawari over Asia and the Pacific, GOES East and West
                   over the Americas), the latest picture (about every 10 minutes, an hour behind), with clear
                   ground made see-through so the map shows under the clouds.
    point          A place's forecast: Open-Meteo (best model for the place, hourly, no key) or MET Norway
                   (yr.no). Kept 30 minutes per place.

Rain radar comes straight from RainViewer in the browser (web/lib/weather.ts).
GRIB2 files are read with ecCodes (the `eccodes` package; its wheels carry the library on Windows too).
"""

from __future__ import annotations

import io
import logging
import math
import shutil
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from worldmodel_contract import local

log = logging.getLogger(__name__)

USER_AGENT = "worldmodel/0.1 (personal local tool) httpx"
NOMADS = "https://nomads.ncep.noaa.gov"
# detail -> (filter script suffix, file name part, grid step in degrees, rough MB per 3-hourly step)
DETAILS = {"1p00": ("1p00", "pgrb2.1p00", 1.0, 0.3), "0p50": ("0p50", "pgrb2full.0p50", 0.5, 1.3),
           "0p25": ("0p25", "pgrb2.0p25", 0.25, 5.2)}
FILTER_VARS = ("TMP", "TCDC", "PRATE", "UGRD", "VGRD", "PRMSL")
FILTER_LEVELS = ("2_m_above_ground", "10_m_above_ground", "entire_atmosphere", "surface", "mean_sea_level")
STEP_HOURS = 3
RUN_EVERY = 6               # GFS runs at 00, 06, 12 and 18 UTC ...
RUN_READY_HOURS = 3.5       # ... and the files start to appear about 3.5 hours later
CHECK_EVERY = 30 * 60       # look for a newer run at most this often (seconds)
GAP = 0.6                   # seconds between downloads (NOMADS asks for under 120 a minute)

# What the map can show, with units and the colours they are drawn in.
FIELDS = {
    "temp": {"label": "Temperature", "unit": "°C"},
    "rain": {"label": "Rain and snow", "unit": "mm/h"},
    "cloud": {"label": "Cloud cover", "unit": "%"},
    "wind": {"label": "Wind", "unit": "km/h"},
    "pressure": {"label": "Pressure", "unit": "hPa"},
}
# value -> RGBA stops (linear between stops; below the first is the first, above the last the last)
RAMPS: dict[str, list[tuple[float, tuple[int, int, int, int]]]] = {
    "temp": [(-40, (145, 0, 165, 210)), (-25, (90, 60, 190, 210)), (-10, (59, 96, 200, 210)), (0, (150, 200, 240, 210)),
             (8, (110, 195, 160, 210)), (15, (200, 220, 110, 210)), (22, (250, 205, 90, 210)), (30, (240, 130, 70, 210)),
             (38, (200, 30, 40, 210)), (46, (110, 0, 20, 210))],
    "rain": [(0.05, (120, 180, 255, 0)), (0.2, (120, 180, 255, 150)), (1, (40, 120, 230, 190)), (2.5, (30, 170, 70, 210)),
             (5, (250, 210, 40, 220)), (10, (245, 120, 30, 225)), (25, (210, 20, 30, 230)), (50, (180, 0, 160, 235))],
    "cloud": [(5, (235, 240, 245, 0)), (30, (225, 230, 236, 70)), (70, (205, 212, 220, 160)), (100, (180, 188, 198, 215))],
    "wind": [(5, (230, 245, 230, 0)), (15, (200, 235, 200, 110)), (30, (120, 200, 190, 150)), (50, (60, 140, 200, 175)),
             (75, (40, 70, 170, 190)), (100, (120, 30, 150, 200)), (140, (80, 0, 60, 210))],
}
LEGENDS = {  # shown in the app's key: (value, colour) pairs
    k: [(v, "#%02x%02x%02x" % c[:3]) for v, c in stops] for k, stops in RAMPS.items()
}
ISOBAR_HPA = 4

TILE = 256
MAX_TILES = 3000
MAX_STEPS = 10      # decoded forecast steps kept in memory (about 6 MB each at 0.5°)
WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Freezing fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Showers", 81: "Showers",
       82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorms",
       96: "Thunderstorms with hail", 99: "Thunderstorms with hail"}

_lock = threading.Lock()
_state: dict = {"thread": None, "checked": 0.0, "note": "", "fetching": None, "error": ""}
_steps: "OrderedDict[tuple, dict]" = OrderedDict()
_tiles: "OrderedDict[tuple, bytes]" = OrderedDict()
_points: dict[tuple, tuple[float, dict]] = {}
_clouds: "OrderedDict[tuple, tuple[float, bytes]]" = OrderedDict()


def folder() -> Path:
    return local.home() / "weather" / "gfs"


def _get(url: str, params: dict | None = None, timeout: float = 60):
    import httpx
    r = httpx.get(url, params=params, timeout=httpx.Timeout(timeout, connect=15), follow_redirects=True,
                  headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r


# ----------------------------------------------------------------------------- runs and steps
def run_id(t: datetime) -> str:
    return t.strftime("%Y%m%d%H")


def run_time(rid: str) -> datetime:
    return datetime.strptime(rid, "%Y%m%d%H").replace(tzinfo=timezone.utc)


def steps_for(days: int) -> list[int]:
    return list(range(0, int(days) * 24 + 1, STEP_HOURS))


def candidates(now: datetime | None = None, n: int = 4) -> list[str]:
    """The runs most likely to be out by now, newest first."""
    now = now or datetime.now(timezone.utc)
    t = now - timedelta(hours=RUN_READY_HOURS)
    t = t.replace(minute=0, second=0, microsecond=0, hour=t.hour - t.hour % RUN_EVERY)
    return [run_id(t - timedelta(hours=RUN_EVERY * i)) for i in range(n)]


def file_name(rid: str, detail: str, step: int) -> str:
    return f"gfs.t{rid[8:10]}z.{DETAILS[detail][1]}.f{step:03d}"


def filter_url(rid: str, detail: str, step: int) -> tuple[str, dict]:
    """NOMADS' subset service: only the fields the map draws, the whole globe."""
    params = {"dir": f"/gfs.{rid[:8]}/{rid[8:10]}/atmos", "file": file_name(rid, detail, step)}
    params.update({f"var_{v}": "on" for v in FILTER_VARS})
    params.update({f"lev_{lv}": "on" for lv in FILTER_LEVELS})
    return f"{NOMADS}/cgi-bin/filter_gfs_{DETAILS[detail][0]}.pl", params


def index_url(rid: str, detail: str, step: int) -> str:
    return f"{NOMADS}/pub/data/nccf/com/gfs/prod/gfs.{rid[:8]}/{rid[8:10]}/atmos/{file_name(rid, detail, step)}.idx"


def stored(detail: str) -> dict[str, list[int]]:
    """Runs on disk for a detail, each with the steps it has, newest first."""
    base = folder() / detail
    out: dict[str, list[int]] = {}
    if base.exists():
        for d in sorted(base.iterdir(), reverse=True):
            if d.is_dir() and len(d.name) == 10 and d.name.isdigit():
                out[d.name] = sorted(int(f.stem[1:]) for f in d.glob("f*.grib2") if f.stem[1:].isdigit())
    return out


def serving(detail: str, days: int) -> tuple[str | None, list[int]]:
    """The run the map draws: the newest with every step; else (first download) the one with most steps."""
    runs = {r: s for r, s in stored(detail).items() if s}
    want = set(steps_for(days))
    for rid, have in runs.items():
        if want <= set(have):
            return rid, [s for s in have if s in want]
    if runs:
        rid = max(runs, key=lambda r: (len(runs[r]), r))
        return rid, [s for s in runs[rid] if s in want]
    return None, []


def status(settings: dict, start: bool = True) -> dict:
    """What the map can show now, and (when on and due) a look for a newer run in the background."""
    on = bool(settings.get("weather_maps", True))
    detail = str(settings.get("weather_detail", "0p50"))
    detail = detail if detail in DETAILS else "0p50"
    days = int(settings.get("weather_days", 7))
    rid, steps = serving(detail, days)
    if on and start:
        _maybe_start(detail, days)
    return {
        "on": on, "detail": detail, "days": days, "run": rid,
        "run_time": run_time(rid).isoformat().replace("+00:00", "Z") if rid else None,
        "steps": steps, "step_hours": STEP_HOURS, "all_steps": steps_for(days),
        "fetching": _state.get("fetching"), "note": _state.get("note", ""), "error": _state.get("error", ""),
        "fields": FIELDS, "legends": LEGENDS, "isobar_hpa": ISOBAR_HPA,
        "mb_per_run": round(DETAILS[detail][3] * len(steps_for(days))),
    }


def _maybe_start(detail: str, days: int) -> None:
    with _lock:
        t = _state.get("thread")
        if t is not None and t.is_alive():
            return
        rid, have = serving(detail, days)
        complete = rid is not None and set(steps_for(days)) <= set(have)
        # Looked lately: wait, unless hours are missing (more days asked for) and the last look went well.
        if time.time() - _state["checked"] < CHECK_EVERY and (complete or _state.get("error") or _state.get("note")):
            return
        _state["checked"] = time.time()
        t = threading.Thread(target=_fetch_safe, args=(detail, days), name="weather-gfs", daemon=True)
        _state["thread"] = t
        t.start()


def _fetch_safe(detail: str, days: int) -> None:
    try:
        fetch(detail, days)
    except Exception as exc:  # noqa: BLE001 - the map keeps the run it has
        log.warning("weather download stopped: %s", exc)
        _state["error"] = (f"NOAA's forecast files did not download ({type(exc).__name__}: {str(exc)[:160]}); "
                           "the map keeps what it has and tries again in 30 minutes.")
    finally:
        _state["fetching"] = None


def newest_ready(detail: str, days: int, head: Callable[[str], bool] | None = None) -> str | None:
    """The newest run whose last step NOAA has published (all earlier steps come out before it)."""
    last = steps_for(days)[-1]

    def _head(url: str) -> bool:
        import httpx
        try:
            return httpx.head(url, timeout=20, headers={"User-Agent": USER_AGENT}).status_code == 200
        except httpx.HTTPError:
            return False
    head = head or _head
    for rid in candidates():
        if head(index_url(rid, detail, last)):
            return rid
    return None


def fetch(detail: str, days: int, get: Callable[[str, dict], bytes] | None = None,
          head: Callable[[str], bool] | None = None, gap: float = GAP) -> str | None:
    """Download the newest complete run's steps not yet on disk, then drop older runs."""
    get = get or (lambda url, params: _get(url, params, timeout=180).content)
    rid = newest_ready(detail, days, head)
    if rid is None:
        _state["note"] = "NOAA has no newer forecast run out yet (or did not answer)."
        return None
    have = stored(detail)
    current, _ = serving(detail, days)
    if current and current >= rid and set(steps_for(days)) <= set(have.get(current, [])):
        _state.update(note="", error="")
        return current
    out = folder() / detail / rid
    out.mkdir(parents=True, exist_ok=True)
    todo = [s for s in steps_for(days) if s not in set(have.get(rid, []))]
    for i, step in enumerate(todo):
        _state["fetching"] = {"run": rid, "step": step, "done": i, "of": len(todo)}
        url, params = filter_url(rid, detail, step)
        data = get(url, params)
        if not data.startswith(b"GRIB"):
            raise ValueError(f"step {step} was not a GRIB file")
        tmp = out / f"f{step:03d}.part"
        tmp.write_bytes(data)
        tmp.replace(out / f"f{step:03d}.grib2")
        if gap:
            time.sleep(gap)
    # The new run is complete: older runs (and other details) go.
    for d in folder().glob("*/*"):
        if d.is_dir() and d != out:
            shutil.rmtree(d, ignore_errors=True)
    with _lock:
        _steps.clear()
        _tiles.clear()
    _state.update(note="", error="")
    return rid


# ----------------------------------------------------------------------------- reading a step
WANT = {("2t", "heightAboveGround"): ("temp", lambda a: a - 273.15),
        ("prate", "surface"): ("rain", lambda a: a * 3600.0),
        ("tcc", "atmosphere"): ("cloud", lambda a: a),
        ("10u", "heightAboveGround"): ("u", lambda a: a),
        ("10v", "heightAboveGround"): ("v", lambda a: a),
        ("prmsl", "meanSea"): ("pressure", lambda a: a / 100.0)}


def decode(path: Path) -> dict:
    """A GRIB2 file -> {"lat0", "dlat", "lon0", "dlon", "fields": {name: 2-D float32, north row first}}.
    Instant values are preferred over averages (step 0 has no rain or cloud: those are left out)."""
    import eccodes  # noqa: PLC0415 - only the weather layers need it
    fields: dict[str, np.ndarray] = {}
    kinds: dict[str, str] = {}
    grid: dict = {}
    with open(path, "rb") as fh:
        while True:
            h = eccodes.codes_grib_new_from_file(fh)
            if h is None:
                break
            try:
                key = (eccodes.codes_get(h, "shortName"), eccodes.codes_get(h, "typeOfLevel"))
                if key not in WANT:
                    continue
                name, conv = WANT[key]
                kind = eccodes.codes_get(h, "stepType")
                if name in fields and kinds[name] == "instant":
                    continue
                ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
                lat_a = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
                lat_b = eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
                lon_a = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
                dlon = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
                dlat = eccodes.codes_get(h, "jDirectionIncrementInDegrees")
                vals = np.asarray(eccodes.codes_get_values(h), dtype=np.float32).reshape(nj, ni)
                if lat_a < lat_b:  # rows run south to north: flip so the first row is the northernmost
                    vals = vals[::-1]
                    lat_a = lat_b
                fields[name] = conv(vals).astype(np.float32)
                kinds[name] = kind
                grid = {"lat0": float(lat_a), "dlat": float(dlat), "lon0": float(lon_a) % 360.0, "dlon": float(dlon),
                        "ni": int(ni), "nj": int(nj)}
            finally:
                eccodes.codes_release(h)
    if "u" in fields and "v" in fields:
        fields["wind"] = np.hypot(fields["u"], fields["v"]) * 3.6
    return {**grid, "fields": fields}


def load_step(detail: str, rid: str, step: int) -> dict | None:
    key = (detail, rid, step)
    with _lock:
        if key in _steps:
            _steps.move_to_end(key)
            return _steps[key]
    path = folder() / detail / rid / f"f{step:03d}.grib2"
    if not path.exists():
        return None
    got = decode(path)
    # Step 0 has no rain or cloud: borrow them from step 3 when it is there.
    if step == 0 and ("rain" not in got["fields"] or "cloud" not in got["fields"]):
        nxt = folder() / detail / rid / f"f{STEP_HOURS:03d}.grib2"
        if nxt.exists():
            more = decode(nxt)["fields"]
            for k in ("rain", "cloud"):
                if k not in got["fields"] and k in more:
                    got["fields"][k] = more[k]
    with _lock:
        _steps[key] = got
        while len(_steps) > MAX_STEPS:
            _steps.popitem(last=False)
    return got


def sample(g: dict, name: str, lat: np.ndarray, lon: np.ndarray) -> np.ndarray | None:
    """Bilinear values of a field at points (any shape); NaN outside the grid."""
    a = g["fields"].get(name)
    if a is None:
        return None
    nj, ni = a.shape
    fi = (g["lat0"] - lat) / g["dlat"]
    fj = ((lon - g["lon0"]) % 360.0) / g["dlon"]
    i0 = np.clip(np.floor(fi).astype(int), 0, nj - 1)
    i1 = np.clip(i0 + 1, 0, nj - 1)
    wraps = abs(ni * g["dlon"] - 360.0) < 1e-6
    j0 = np.floor(fj).astype(int) % ni if wraps else np.clip(np.floor(fj).astype(int), 0, ni - 1)
    j1 = (j0 + 1) % ni if wraps else np.clip(j0 + 1, 0, ni - 1)
    ti = np.clip(fi - np.floor(fi), 0, 1).astype(np.float32)
    tj = (fj - np.floor(fj)).astype(np.float32)
    v = a[i0, j0] * (1 - ti) * (1 - tj) + a[i0, j1] * (1 - ti) * tj + a[i1, j0] * ti * (1 - tj) + a[i1, j1] * ti * tj
    out = np.array(v, dtype=np.float32)
    out[(fi < -0.5) | (fi > nj - 0.5)] = np.nan
    if not wraps:  # a part of the world (tests, or a region file): nothing past its edges
        out[fj > ni - 0.5] = np.nan
    return out


def at(settings: dict, lat: float, lon: float, step: int) -> dict:
    """Every field's value at a point for one step (the map's line under the pointer)."""
    st = status(settings, start=False)
    if not st["run"] or step not in st["steps"]:
        return {"step": step, "values": {}}
    g = load_step(st["detail"], st["run"], step)
    if g is None:
        return {"step": step, "values": {}}
    la, lo = np.array([lat], dtype=np.float64), np.array([lon], dtype=np.float64)
    vals: dict[str, float | None] = {}
    for k in ("temp", "rain", "cloud", "wind", "pressure", "u", "v"):
        s = sample(g, k, la, lo)
        vals[k] = None if s is None or not np.isfinite(s[0]) else round(float(s[0]), 2)
    if vals.get("u") is not None and vals.get("v") is not None:
        vals["from_deg"] = round((math.degrees(math.atan2(-vals["u"], -vals["v"])) + 360) % 360)
    return {"step": step, "valid": (run_time(st["run"]) + timedelta(hours=step)).isoformat().replace("+00:00", "Z"), "values": vals}


# ----------------------------------------------------------------------------- tiles
def _lonlat(z: int, x: int, y: int, size: int = TILE, extra: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Longitude and latitude of each pixel centre of a Web Mercator tile (extra pixels right and below)."""
    n = 2 ** z
    px = (np.arange(size + extra) + 0.5 + x * size) / (size * n)
    py = (np.arange(size + extra) + 0.5 + y * size) / (size * n)
    lon = px * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py))))
    m = size + extra
    return np.broadcast_to(lon[None, :], (m, m)), np.broadcast_to(lat[:, None], (m, m))


def colour(values: np.ndarray, stops: list[tuple[float, tuple[int, int, int, int]]]) -> np.ndarray:
    xs = np.array([s[0] for s in stops], dtype=np.float32)
    out = np.zeros(values.shape + (4,), dtype=np.uint8)
    v = np.nan_to_num(values, nan=-1e9)
    for c in range(4):
        out[..., c] = np.interp(v, xs, np.array([s[1][c] for s in stops], dtype=np.float32)).astype(np.uint8)
    out[~np.isfinite(values)] = 0
    return out


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def render(g: dict, field: str, z: int, x: int, y: int) -> bytes:
    """A 256-pixel tile of one field (see-through where there is nothing to show)."""
    if field == "pressure":
        lon, lat = _lonlat(z, x, y, extra=1)
        p = sample(g, "pressure", lat, lon)
        rgba = np.zeros((TILE, TILE, 4), dtype=np.uint8)
        if p is not None:
            ok = np.isfinite(p)
            q = np.nan_to_num(p, nan=0)
            lvl, big = np.floor(q / ISOBAR_HPA), np.floor(q / (ISOBAR_HPA * 5))
            both = ok[:TILE, :TILE] & ok[:TILE, 1:] & ok[1:, :TILE]
            edge = both & ((lvl[:TILE, :TILE] != lvl[:TILE, 1:]) | (lvl[:TILE, :TILE] != lvl[1:, :TILE]))
            major = both & ((big[:TILE, :TILE] != big[:TILE, 1:]) | (big[:TILE, :TILE] != big[1:, :TILE]))
            rgba[edge] = (40, 40, 60, 160)
            rgba[major] = (20, 20, 40, 235)
        return _png(rgba)
    lon, lat = _lonlat(z, x, y)
    v = sample(g, field, lat, lon)
    if v is None:
        return _png(np.zeros((TILE, TILE, 4), dtype=np.uint8))
    rgba = colour(v, RAMPS[field])
    if field == "wind":
        rgba = _arrows(rgba, g, lat, lon)
    return _png(rgba)


def _arrows(rgba: np.ndarray, g: dict, lat: np.ndarray, lon: np.ndarray, every: int = 32) -> np.ndarray:
    """Arrows pointing the way the wind blows, longer for stronger wind, every 32 pixels."""
    from PIL import Image, ImageDraw
    img = Image.fromarray(np.ascontiguousarray(rgba), "RGBA")
    d = ImageDraw.Draw(img)
    c = np.arange(every // 2, TILE, every)
    la, lo = lat[np.ix_(c, c)], lon[np.ix_(c, c)]
    u, v = sample(g, "u", la, lo), sample(g, "v", la, lo)
    if u is None or v is None:
        return rgba
    ink = (25, 30, 40, 215)
    for a, py in enumerate(c):
        for b, px in enumerate(c):
            uu, vv = float(u[a, b]), float(v[a, b])
            if not (math.isfinite(uu) and math.isfinite(vv)):
                continue
            ms = math.hypot(uu, vv)
            if ms * 3.6 < 2:
                continue
            ln = 7 + min(ms * 3.6, 100) / 100 * 15
            dx, dy = uu / ms, -vv / ms  # screen: x east, y down
            x0, y0, x1, y1 = px - dx * ln / 2, py - dy * ln / 2, px + dx * ln / 2, py + dy * ln / 2
            d.line([(x0, y0), (x1, y1)], fill=ink, width=2 if ms * 3.6 >= 50 else 1)
            hx, hy = x1 - dx * 5, y1 - dy * 5
            d.polygon([(x1, y1), (hx - dy * 3, hy + dx * 3), (hx + dy * 3, hy - dx * 3)], fill=ink)
    return np.asarray(img)


def tile(settings: dict, field: str, run: str, step: int, z: int, x: int, y: int) -> bytes | None:
    if field not in FIELDS or not (0 <= z <= 10) or not (0 <= y < 2 ** z):
        return None
    detail = str(settings.get("weather_detail", "0p50"))
    detail = detail if detail in DETAILS else "0p50"
    x %= 2 ** z
    key = (detail, run, step, field, z, x, y)
    with _lock:
        if key in _tiles:
            _tiles.move_to_end(key)
            return _tiles[key]
    g = load_step(detail, run, step)
    if g is None:
        return None
    png = render(g, field, z, x, y)
    with _lock:
        _tiles[key] = png
        while len(_tiles) > MAX_TILES:
            _tiles.popitem(last=False)
    return png


# ----------------------------------------------------------------------------- clouds from satellite
GIBS_GEO = ("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/default/"
            "GoogleMapsCompatible_Level6/{z}/{y}/{x}.png")
GEO_LAYERS = ("Himawari_AHI_Band13_Clean_Infrared", "GOES-West_ABI_Band13_Clean_Infrared", "GOES-East_ABI_Band13_Clean_Infrared")
CLOUD_KEEP = 10 * 60


def cloud_pixels(rgba: np.ndarray) -> np.ndarray:
    """Infrared picture -> clouds: grey pixels get whiter and more solid the colder (brighter) they are,
    warm ground goes see-through; the coloured coldest cloud tops stay as they are."""
    out = np.zeros_like(rgba)
    r, g, b, a = (rgba[..., i].astype(np.int16) for i in range(4))
    grey = (abs(r - g) < 12) & (abs(g - b) < 12)
    level = np.clip((r.astype(np.float32) - 120) / (210 - 120), 0, 1)
    out[..., 0] = np.where(grey, 250, rgba[..., 0])
    out[..., 1] = np.where(grey, 252, rgba[..., 1])
    out[..., 2] = np.where(grey, 255, rgba[..., 2])
    out[..., 3] = np.where(a == 0, 0, np.where(grey, (level ** 0.8 * 235).astype(np.uint8), 235))
    return out


def clouds_tile(z: int, x: int, y: int, get: Callable[[str], bytes] | None = None) -> bytes:
    """The three geostationary satellites' latest infrared, made into see-through clouds (tiles to zoom 6)."""
    from PIL import Image
    zz = min(z, 6)
    k = 2 ** (z - zz)
    x %= 2 ** z
    key = (z, x, y)
    with _lock:
        hit = _clouds.get(key)
        if hit and time.time() - hit[0] < CLOUD_KEEP:
            return hit[1]
    get = get or (lambda url: _get(url, timeout=30).content)
    best = np.zeros((TILE, TILE, 4), dtype=np.uint8)
    for layer in GEO_LAYERS:
        try:
            raw = get(GIBS_GEO.format(layer=layer, z=zz, x=x // k, y=y // k))
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:  # noqa: BLE001 - a satellite missing leaves its part empty
            continue
        if k > 1:  # past zoom 6: cut the part of the parent tile and enlarge it
            s = TILE // k
            ox, oy = (x % k) * s, (y % k) * s
            im = im.crop((ox, oy, ox + s, oy + s)).resize((TILE, TILE), Image.BILINEAR)
        c = cloud_pixels(np.asarray(im))
        take = c[..., 3] > best[..., 3]
        best[take] = c[take]
    png = _png(best)
    with _lock:
        _clouds[key] = (time.time(), png)
        while len(_clouds) > 1500:
            _clouds.popitem(last=False)
    return png


# ----------------------------------------------------------------------------- one place's forecast
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
MET_NORWAY = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
POINT_KEEP = 30 * 60


def point(settings: dict, lat: float, lon: float, get: Callable[[str, dict], dict] | None = None) -> dict:
    """Weather now and the hourly forecast for a place, from the source picked in Settings."""
    src = str(settings.get("weather_point", "open_meteo"))
    days = max(1, min(10, int(settings.get("weather_days", 7))))
    lat, lon = round(max(-90.0, min(90.0, lat)), 2), round(((lon + 180) % 360) - 180, 2)
    key = (src, days, lat, lon)
    hit = _points.get(key)
    if hit and time.time() - hit[0] < POINT_KEEP:
        return hit[1]
    get = get or (lambda url, params: _get(url, params, timeout=30).json())
    try:
        if src == "met_norway":
            out = met_norway(get(MET_NORWAY, {"lat": lat, "lon": lon}), days)
        else:
            out = open_meteo(get(OPEN_METEO, {
                "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": days, "wind_speed_unit": "kmh",
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,cloud_cover,wind_speed_10m,"
                           "wind_direction_10m,wind_gusts_10m,weather_code,pressure_msl",
                "hourly": "temperature_2m,precipitation,precipitation_probability,cloud_cover,wind_speed_10m,wind_direction_10m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
                         "wind_speed_10m_max,wind_direction_10m_dominant,sunrise,sunset",
            }))
    except Exception as exc:  # noqa: BLE001 - shown on the card
        name = "MET Norway" if src == "met_norway" else "Open-Meteo"
        return {"lat": lat, "lon": lon, "source": src, "error": f"{name} did not answer ({type(exc).__name__}); try again in a minute."}
    out.update(lat=lat, lon=lon)
    _points[key] = (time.time(), out)
    if len(_points) > 500:
        for k in sorted(_points, key=lambda k: _points[k][0])[:100]:
            _points.pop(k, None)
    return out


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _words(code) -> str | None:
    try:
        return WMO.get(int(code))
    except (TypeError, ValueError):
        return None


def open_meteo(d: dict) -> dict:
    cur, hr, dy = d.get("current") or {}, d.get("hourly") or {}, d.get("daily") or {}

    def h(k: str) -> list:
        return [_num(v) for v in hr.get(k, [])]

    def dd(k: str, i: int):
        col = dy.get(k) or []
        return col[i] if i < len(col) else None
    return {
        "source": "open_meteo", "source_name": "Open-Meteo", "link": "https://open-meteo.com/",
        "timezone": d.get("timezone"), "utc_offset_s": int(d.get("utc_offset_seconds") or 0), "elevation": _num(d.get("elevation")),
        "now": {"time": cur.get("time"), "temp": _num(cur.get("temperature_2m")), "feels": _num(cur.get("apparent_temperature")),
                "humidity": _num(cur.get("relative_humidity_2m")), "rain": _num(cur.get("precipitation")),
                "cloud": _num(cur.get("cloud_cover")), "wind": _num(cur.get("wind_speed_10m")),
                "gust": _num(cur.get("wind_gusts_10m")), "from_deg": _num(cur.get("wind_direction_10m")),
                "pressure": _num(cur.get("pressure_msl")), "code": cur.get("weather_code"), "words": _words(cur.get("weather_code"))},
        "hourly": {"time": hr.get("time", []), "temp": h("temperature_2m"), "rain": h("precipitation"),
                   "rain_chance": h("precipitation_probability"), "cloud": h("cloud_cover"), "wind": h("wind_speed_10m"),
                   "from_deg": h("wind_direction_10m"), "code": hr.get("weather_code", [])},
        "daily": [{"date": t, "high": _num(dd("temperature_2m_max", i)), "low": _num(dd("temperature_2m_min", i)),
                   "rain": _num(dd("precipitation_sum", i)), "rain_chance": _num(dd("precipitation_probability_max", i)),
                   "wind": _num(dd("wind_speed_10m_max", i)), "from_deg": _num(dd("wind_direction_10m_dominant", i)),
                   "code": dd("weather_code", i), "words": _words(dd("weather_code", i)),
                   "sunrise": dd("sunrise", i), "sunset": dd("sunset", i)}
                  for i, t in enumerate(dy.get("time", []))],
    }


# MET Norway symbol codes -> words (the part before _day/_night/_polartwilight).
MET_WORDS = {"clearsky": "Clear", "fair": "Mostly clear", "partlycloudy": "Partly cloudy", "cloudy": "Cloudy", "fog": "Fog",
             "lightrain": "Light rain", "rain": "Rain", "heavyrain": "Heavy rain", "lightrainshowers": "Light showers",
             "rainshowers": "Showers", "heavyrainshowers": "Heavy showers", "lightsleet": "Light sleet", "sleet": "Sleet",
             "heavysleet": "Heavy sleet", "lightsnow": "Light snow", "snow": "Snow", "heavysnow": "Heavy snow",
             "lightsnowshowers": "Light snow showers", "snowshowers": "Snow showers", "heavysnowshowers": "Heavy snow showers",
             "rainandthunder": "Rain and thunder", "heavyrainandthunder": "Heavy rain and thunder",
             "rainshowersandthunder": "Thundery showers", "lightrainandthunder": "Light rain and thunder"}


def _met_words(code: str | None) -> str | None:
    base = (code or "").split("_")[0]
    return MET_WORDS.get(base, base or None)


def met_norway(d: dict, days: int) -> dict:
    """MET Norway's compact forecast in the same shape as Open-Meteo's (times in UTC, no rain chance)."""
    ts = (d.get("properties") or {}).get("timeseries") or []
    end = None
    hourly: dict[str, list] = {k: [] for k in ("time", "temp", "rain", "rain_chance", "cloud", "wind", "from_deg", "code")}
    for t in ts:
        when = datetime.fromisoformat(t["time"].replace("Z", "+00:00"))
        end = end or when + timedelta(days=days)
        if when > end:
            break
        data = t.get("data") or {}
        det = (data.get("instant") or {}).get("details") or {}
        nxt = data.get("next_1_hours") or data.get("next_6_hours") or {}
        hourly["time"].append(when.strftime("%Y-%m-%dT%H:%M"))
        hourly["temp"].append(_num(det.get("air_temperature")))
        hourly["rain"].append(_num((nxt.get("details") or {}).get("precipitation_amount")))
        hourly["rain_chance"].append(None)
        hourly["cloud"].append(_num(det.get("cloud_area_fraction")))
        ws = _num(det.get("wind_speed"))
        hourly["wind"].append(round(ws * 3.6, 1) if ws is not None else None)
        hourly["from_deg"].append(_num(det.get("wind_from_direction")))
        hourly["code"].append((nxt.get("summary") or {}).get("symbol_code"))
    data0 = (ts[0].get("data") or {}) if ts else {}
    det0 = (data0.get("instant") or {}).get("details") or {}
    n1 = data0.get("next_1_hours") or {}
    days_out: dict[str, dict] = {}
    for i, t in enumerate(hourly["time"]):
        day = days_out.setdefault(t[:10], {"date": t[:10], "high": None, "low": None, "rain": 0.0, "rain_chance": None, "wind": None,
                                            "from_deg": None, "code": None, "words": None, "sunrise": None, "sunset": None})
        v = hourly["temp"][i]
        if v is not None:
            day["high"] = v if day["high"] is None else max(day["high"], v)
            day["low"] = v if day["low"] is None else min(day["low"], v)
        day["rain"] = round(day["rain"] + (hourly["rain"][i] or 0), 1)
        w = hourly["wind"][i]
        if w is not None and (day["wind"] is None or w > day["wind"]):
            day["wind"] = w
        if t[11:13] == "12" or day["code"] is None:
            day["code"] = hourly["code"][i]
            day["words"] = _met_words(hourly["code"][i])
    ws0 = _num(det0.get("wind_speed"))
    code0 = (n1.get("summary") or {}).get("symbol_code")
    return {
        "source": "met_norway", "source_name": "MET Norway (yr.no)", "link": "https://www.yr.no/",
        "timezone": "UTC", "utc_offset_s": 0, "elevation": None,
        "now": {"time": hourly["time"][0] if hourly["time"] else None, "temp": _num(det0.get("air_temperature")), "feels": None,
                "humidity": _num(det0.get("relative_humidity")), "rain": _num((n1.get("details") or {}).get("precipitation_amount")),
                "cloud": _num(det0.get("cloud_area_fraction")), "wind": round(ws0 * 3.6, 1) if ws0 is not None else None,
                "gust": None, "from_deg": _num(det0.get("wind_from_direction")), "pressure": _num(det0.get("air_pressure_at_sea_level")),
                "code": code0, "words": _met_words(code0)},
        "hourly": hourly,
        "daily": list(days_out.values()),
    }
