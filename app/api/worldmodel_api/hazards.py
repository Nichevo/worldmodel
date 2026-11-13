"""Hazards happening now, read live when a map layer is turned on and kept a while:

    fires      NASA FIRMS active fires: VIIRS (NOAA-20) for the last 24 hours, MODIS for the last
               7 days, from the open global files. Gathered into 0.25° cells (a dot per cell,
               sized by the fire power in it) and counted by country.
    heat       Open-Meteo forecasts of the daily high for the next 5 days at the world's big cities
               (the major_cities layer): cities forecast to reach 35 °C or more on two days or more.
    coral      NOAA Coral Reef Watch's 7-day maximum bleaching alert (5 km) for about 30 reef
               regions, read from NOAA's ERDDAP server, the highest level in each region.

Each comes back as GeoJSON with a `note` when a site did not answer, so the map still draws.
Country names for counts come from the map's own country shapes (app/web/public/geo).
"""

from __future__ import annotations

import csv
import io
import json
import math
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

FIRMS = {"24h": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv",
         "7d": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_7d.csv"}
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW.csv"
CELL = 0.25           # fires are gathered into cells this many degrees across
HOT = 35.0            # a city counts as in a heatwave at this daily high (°C) ...
HOT_DAYS = 2          # ... on this many of the next five days
KEEP = {"fires": 3 * 3600, "heat": 6 * 3600, "coral": 24 * 3600}
LEVELS = ["No stress", "Watch", "Warning", "Alert level 1", "Alert level 2"]

# Reef regions: (name, country or area, west, south, east, north). Boxes around the main reef areas.
REEFS = [
    ("Great Barrier Reef, north", "AUS", 142.5, -16.0, 147.0, -10.5), ("Great Barrier Reef, central", "AUS", 145.5, -20.0, 150.0, -16.0),
    ("Great Barrier Reef, south", "AUS", 148.0, -24.5, 153.5, -20.0), ("Coral Sea", "AUS", 147.0, -20.0, 157.0, -12.0),
    ("Ningaloo and north-west Australia", "AUS", 112.0, -24.0, 124.0, -13.0), ("Torres Strait", "AUS", 141.0, -10.8, 144.5, -9.0),
    ("New Caledonia", "NCL", 163.0, -23.0, 168.5, -19.0), ("Fiji", "FJI", 176.5, -19.5, 180.0, -15.5),
    ("Vanuatu", "VUT", 166.0, -20.5, 170.5, -13.0), ("Solomon Islands", "SLB", 155.5, -11.0, 162.5, -6.5),
    ("Samoa and Tonga", "WSM", -176.0, -22.0, -170.0, -13.0), ("Cook Islands and French Polynesia", "PYF", -160.0, -23.0, -138.0, -14.0),
    ("Papua New Guinea", "PNG", 145.0, -11.5, 155.0, -2.0), ("Coral Triangle (Indonesia)", "IDN", 115.0, -9.5, 135.0, 2.0),
    ("Philippines", "PHL", 117.0, 5.0, 127.0, 19.0), ("South China Sea (Spratlys)", "", 111.0, 6.0, 118.0, 12.0),
    ("Okinawa and southern Japan", "JPN", 123.0, 24.0, 131.0, 29.0), ("Micronesia and Palau", "FSM", 133.0, 5.0, 163.0, 10.5),
    ("Marshall Islands and Kiribati", "MHL", 165.0, -2.0, 173.0, 12.0), ("Hawaii", "USA", -161.0, 18.5, -154.5, 22.5),
    ("Andaman Sea", "THA", 92.0, 6.0, 99.0, 14.0), ("Maldives and Lakshadweep", "MDV", 71.5, -1.0, 74.5, 12.0),
    ("Chagos", "", 70.5, -8.0, 73.0, -4.5), ("Seychelles", "SYC", 52.0, -10.5, 57.0, -3.5),
    ("Madagascar and Mozambique Channel", "MDG", 40.0, -26.0, 50.0, -12.0), ("East Africa (Kenya, Tanzania)", "TZA", 38.5, -10.5, 42.0, -2.0),
    ("Red Sea", "EGY", 33.0, 13.0, 43.5, 28.0), ("Persian Gulf", "ARE", 48.0, 24.0, 57.0, 30.0),
    ("Caribbean, east", "", -66.0, 10.0, -59.0, 19.0), ("Caribbean, west and Mesoamerican Reef", "BLZ", -89.0, 15.0, -76.0, 22.0),
    ("Florida Keys and Bahamas", "USA", -82.5, 23.0, -74.0, 27.5), ("Brazil (Abrolhos)", "BRA", -40.0, -19.5, -37.5, -16.5),
]

_cache: dict[str, dict] = {}
_lock = threading.Lock()
_shapes: dict = {"tree": None, "ids": []}
SHAPES = Path(__file__).resolve().parents[2] / "web" / "public" / "geo" / "countries.json"


def _cached(key: str, make: Callable[[], dict]) -> dict:
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit["at"] < KEEP[key.split(":")[0]]:
            return hit["data"]
    data = make()
    if not data.get("note"):  # a failure is not kept, so the next look tries again
        with _lock:
            _cache[key] = {"at": time.time(), "data": data}
    return data


def _get(url: str, params: dict | None = None, timeout: float = 60) -> str:
    import httpx
    r = httpx.get(url, params=params, timeout=httpx.Timeout(timeout, connect=10), follow_redirects=True,
                  headers={"User-Agent": "worldmodel/0.1 (personal local tool)"})
    r.raise_for_status()
    return r.text


def country_of(lon: float, lat: float) -> str | None:
    """The country a point is in, from the map's own country shapes (None at sea or if they are missing)."""
    if _shapes["tree"] is None:
        try:
            from shapely.geometry import shape
            from shapely.strtree import STRtree
            feats = json.loads(SHAPES.read_text(encoding="utf-8"))["features"]
            polys = [shape(f["geometry"]) for f in feats]
            _shapes.update(tree=STRtree(polys), polys=polys, ids=[(f.get("properties") or {}).get("iso3") for f in feats])
        except Exception:  # noqa: BLE001 - no shapes: no country names
            _shapes.update(tree=False)
    if not _shapes["tree"]:
        return None
    from shapely.geometry import Point
    pt = Point(lon, lat)
    for i in _shapes["tree"].query(pt):
        if _shapes["polys"][i].contains(pt):
            return _shapes["ids"][i]
    return None


def _empty(note: str = "") -> dict:
    return {"type": "FeatureCollection", "features": [], **({"note": note} if note else {})}


# ----------------------------------------------------------------------------- fires
def fire_cells(text: str, cell: float = CELL) -> list[dict]:
    """FIRMS CSV rows gathered into cells: centre, number of fires, total fire power (MW), latest date."""
    rows = csv.DictReader(io.StringIO(text))
    cells: dict[tuple[int, int], dict] = {}
    for r in rows:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        conf = str(r.get("confidence") or "").lower()
        if conf in ("l", "low") or (conf.isdigit() and int(conf) < 30):
            continue  # low-confidence detections are often sun glint or hot ground
        k = (math.floor(lat / cell), math.floor(lon / cell))
        c = cells.setdefault(k, {"n": 0, "frp": 0.0, "lat": 0.0, "lon": 0.0, "date": ""})
        c["n"] += 1
        c["lat"] += lat
        c["lon"] += lon
        try:
            c["frp"] += float(r.get("frp") or 0)
        except ValueError:
            pass
        c["date"] = max(c["date"], str(r.get("acq_date") or ""))
    return [{"lat": c["lat"] / c["n"], "lon": c["lon"] / c["n"], "n": c["n"], "frp": round(c["frp"]), "date": c["date"]}
            for c in cells.values()]


def fires(window: str = "24h", enabled: bool = True, fetch: Callable[[str], str] | None = None) -> dict:
    window = window if window in FIRMS else "24h"
    if not enabled:
        return _empty("Live hazard layers are off (Settings > Climate).")

    def make() -> dict:
        try:
            text = fetch(FIRMS[window]) if fetch else _get(FIRMS[window], timeout=120)
        except Exception as exc:  # noqa: BLE001 - the map says why
            return _empty(f"NASA FIRMS did not answer ({type(exc).__name__}); try again later.")
        cells = fire_cells(text)
        by: dict[str, int] = defaultdict(int)
        feats = []
        for c in cells:
            iso = country_of(c["lon"], c["lat"])
            if iso:
                by[iso] += c["n"]
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(c["lon"], 3), round(c["lat"], 3)]},
                          "properties": {"n": c["n"], "frp": c["frp"], "date": c["date"], **({"country": iso} if iso else {})}})
        top = sorted(by.items(), key=lambda kv: -kv[1])
        return {"type": "FeatureCollection", "features": feats, "window": window, "fires": sum(c["n"] for c in cells),
                "countries": dict(top), "fetched": time.strftime("%Y-%m-%d %H:%M")}
    return _cached(f"fires:{window}", make)


# ----------------------------------------------------------------------------- heat
def heat_cities(cities: list[dict], highs: list[list[float | None]], dates: list[str]) -> list[dict]:
    """Cities forecast to reach HOT on HOT_DAYS days or more, with their hottest day."""
    out = []
    for c, hs in zip(cities, highs):
        vals = [(d, h) for d, h in zip(dates, hs) if h is not None]
        hot = [(d, h) for d, h in vals if h >= HOT]
        if len(hot) < HOT_DAYS:
            continue
        day, peak = max(vals, key=lambda x: x[1])
        out.append({**c, "peak": round(peak, 1), "day": day, "days": len(hot)})
    return out


def heat(cities: list[dict], enabled: bool = True, fetch: Callable[[str, dict], str] | None = None) -> dict:
    """cities: [{name, country, lon, lat}] (the major_cities layer)."""
    if not enabled:
        return _empty("Live hazard layers are off (Settings > Climate).")
    if not cities:
        return _empty("No city list yet: a refresh loads the major cities layer.")

    def make() -> dict:
        found = []
        for i in range(0, len(cities), 100):  # Open-Meteo takes many places in one request
            part = cities[i:i + 100]
            params = {"latitude": ",".join(f"{c['lat']:.3f}" for c in part), "longitude": ",".join(f"{c['lon']:.3f}" for c in part),
                      "daily": "temperature_2m_max", "forecast_days": 5, "timezone": "auto"}
            try:
                got = json.loads(fetch(OPEN_METEO, params) if fetch else _get(OPEN_METEO, params))
            except Exception as exc:  # noqa: BLE001
                return _empty(f"Open-Meteo did not answer ({type(exc).__name__}); try again later.")
            got = got if isinstance(got, list) else [got]
            highs = [g.get("daily", {}).get("temperature_2m_max") or [] for g in got]
            dates = (got[0].get("daily", {}).get("time") or []) if got else []
            found += heat_cities(part, highs, dates)
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                  "properties": {k: c[k] for k in ("name", "country", "peak", "day", "days") if c.get(k) is not None}} for c in found]
        return {"type": "FeatureCollection", "features": feats, "hot": HOT, "checked": len(cities),
                "fetched": time.strftime("%Y-%m-%d %H:%M")}
    return _cached("heat:all", make)


# ----------------------------------------------------------------------------- coral
def reef_level(text: str) -> tuple[int | None, str]:
    """The highest 7-day bleaching alert in an ERDDAP CSV (two header lines), and its date."""
    lines = text.splitlines()[2:]
    best, day = None, ""
    for ln in csv.reader(lines):
        if len(ln) < 4:
            continue
        try:
            v = int(float(ln[3]))
        except ValueError:
            continue  # NaN: land or no data
        if 0 <= v <= 4 and (best is None or v > best):
            best = v
        day = ln[0][:10] or day
    return best, day


def coral(enabled: bool = True, fetch: Callable[[str], str] | None = None) -> dict:
    if not enabled:
        return _empty("Live hazard layers are off (Settings > Climate).")

    def make() -> dict:
        feats, failed, day = [], 0, ""
        for name, iso, w, s, e, n in REEFS:
            q = f"CRW_BAA_7D_MAX[(last)][({n}):5:({s})][({w}):5:({e})]"
            try:
                level, d = reef_level(fetch(q) if fetch else _get(f"{ERDDAP}?{q}", timeout=60))
            except Exception:  # noqa: BLE001 - one region missing is not the end
                failed += 1
                if failed >= 3 and not feats:
                    return _empty("NOAA Coral Reef Watch did not answer; try again later.")
                continue
            day = day or d
            if level is None:
                continue
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
                          "properties": {"name": name, "country": iso or None, "level": level, "label": LEVELS[level]}})
            if not fetch:
                time.sleep(0.3)  # polite to NOAA between regions
        feats.sort(key=lambda f: -f["properties"]["level"])
        return {"type": "FeatureCollection", "features": feats, "date": day, "fetched": time.strftime("%Y-%m-%d %H:%M")}
    return _cached("coral:all", make)


def country(iso: str, enabled: bool, cities: list[dict]) -> dict:
    """A country card's line: fires in the last 7 days, hot cities, reef regions under alert. Only what is
    already kept is used, so a country page never waits on three websites."""
    with _lock:
        got = {k: v["data"] for k, v in _cache.items()}
    f7 = got.get("fires:7d") or got.get("fires:24h")
    h = got.get("heat:all")
    c = got.get("coral:all")
    return {
        "fires": (f7 or {}).get("countries", {}).get(iso) if f7 else None, "fires_window": (f7 or {}).get("window"),
        "hot": [ft["properties"] for ft in (h or {}).get("features", []) if ft["properties"].get("country") == iso] if h else None,
        "reefs": [ft["properties"] for ft in (c or {}).get("features", []) if ft["properties"].get("country") == iso] if c else None,
        "enabled": enabled,
    }
