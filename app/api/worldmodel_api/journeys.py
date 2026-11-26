"""Where a clicked ship or plane has come from and is going.

- Ships: the path saved while collecting (shipstore.py), and the destination its crew typed into
  its AIS set, matched to a port in the World Port Index by UN/LOCODE ("NZ AKL", "NZAKL") or name.
- Planes: the path of its flight so far from OpenSky's tracks endpoint (one request per click),
  and the route its callsign flies from adsb.lol's route database (airline flights only).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable

import httpx

log = logging.getLogger(__name__)

Q = Callable[[str, list], list[dict]]
OPENSKY_TRACK = "https://opensky-network.org/api/tracks/all"
ADSB_ROUTES = "https://api.adsb.lol/api/0/routeset"
ADSB_HEX = "https://api.adsb.lol/v2/hex/{}"
ROUTE_KEEP = 6 * 3600
TRACK_KEEP = 30 * 60      # a plane's path is asked of OpenSky at most once in this time
AIRCRAFT_KEEP = 24 * 3600  # registration and type change rarely
_lock = threading.Lock()
_index: dict[str, tuple[float, dict]] = {}
_routes: dict[str, tuple[float, dict | None]] = {}
_tracks: dict[str, tuple[float, dict]] = {}
_aircraft_kept: dict[str, tuple[float, dict | None]] = {}


def _layer(q: Q, layer_id: str) -> list[dict]:
    try:
        got = q("SELECT geojson FROM layers WHERE layer_id = ?", [layer_id])
    except Exception:  # noqa: BLE001 - no layers table yet
        return []
    if not got:
        return []
    data = got[0]["geojson"]
    return (json.loads(data) if isinstance(data, str) else data).get("features") or []


def _cached(name: str, build: Callable[[], dict]) -> dict:
    with _lock:
        hit = _index.get(name)
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
    value = build()
    with _lock:
        _index[name] = (time.time(), value)
    return value


def _key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


# ----------------------------------------------------------------------------- ships
def ports(q: Q) -> dict:
    def build() -> dict:
        by_code, by_name = {}, {}
        for f in _layer(q, "ports_all"):
            p, (lon, lat) = f.get("properties") or {}, f["geometry"]["coordinates"]
            port = {"name": p.get("name"), "country": p.get("country"), "locode": p.get("locode"), "lon": lon, "lat": lat}
            if p.get("locode"):
                by_code[_key(p["locode"])] = port
            if p.get("name"):
                by_name.setdefault(_key(p["name"]), port)
        return {"code": by_code, "name": by_name}
    return _cached("ports", build)


def match_port(dest: str | None, index: dict) -> dict | None:
    """The port a ship's typed destination names, if one can be told: the part after the last
    '>' (some crews type FROM>TO), as a UN/LOCODE or a port name."""
    if not dest:
        return None
    text = str(dest).upper().split(">")[-1].strip()
    if not text:
        return None
    k = _key(text)
    if len(k) == 5 and k in index["code"]:
        return index["code"][k]
    for word in re.split(r"[\s,./\-]+", text):
        w = _key(word)
        if len(w) >= 4 and w in index["name"]:
            return index["name"][w]
    if k in index["name"]:
        return index["name"][k]
    return None


def ship_journey(q: Q, ships, mmsi: int, hours: float = 72) -> dict:
    track = ships.track(mmsi, hours)
    detail = ships.detail(mmsi) or {}
    port = match_port(detail.get("destination"), ports(q))
    return {"track": track, "destination": detail.get("destination"), "eta": detail.get("eta"), "port": port,
            "from_time": track.get("from"), "now": [detail.get("lon"), detail.get("lat")] if detail.get("lat") is not None else None,
            "note": None if track.get("points") else "No saved path yet: paths are saved while ships are collected (Settings > Transport)."}


# ----------------------------------------------------------------------------- planes
def airports(q: Q) -> dict:
    def build() -> dict:
        out = {}
        for f in _layer(q, "airports"):
            p, (lon, lat) = f.get("properties") or {}, f["geometry"]["coordinates"]
            a = {"name": p.get("name"), "iata": p.get("iata"), "icao": p.get("icao"), "city": p.get("city"), "lon": lon, "lat": lat}
            for c in (p.get("iata"), p.get("icao")):
                if c:
                    out[_key(c)] = a
        return out
    return _cached("airports", build)


def _route(callsign: str, lat: float | None, lon: float | None) -> dict | None:
    cs = _key(callsign)
    if not cs:
        return None
    with _lock:
        hit = _routes.get(cs)
        if hit and time.time() - hit[0] < ROUTE_KEEP:
            return hit[1]
    got = None
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "worldmodel (personal research tool)"}) as client:
            r = client.post(ADSB_ROUTES, json={"planes": [{"callsign": cs, "lat": lat or 0, "lng": lon or 0}]})
            r.raise_for_status()
            body = r.json()
            first = (body[0] if isinstance(body, list) and body else None) or {}
            if first.get("airport_codes") and first.get("airport_codes") != "unknown":
                got = {"codes": first.get("airport_codes"), "plausible": bool(first.get("plausible", True)),
                       "airports": [{"name": a.get("name"), "iata": a.get("iata"), "icao": a.get("icao"), "city": a.get("location"),
                                     "country": a.get("countryiso2"), "lon": a.get("lon"), "lat": a.get("lat")}
                                    for a in first.get("_airports") or []]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.info("adsb.lol route for %s: %s", cs, exc)
        return None  # not kept: try again on the next click
    with _lock:
        _routes[cs] = (time.time(), got)
    return got


def _nearest_airport(index: dict, lon: float, lat: float, within_km: float = 25) -> dict | None:
    import math

    best, best_d = None, within_km
    seen = set()
    for a in index.values():
        if id(a) in seen:
            continue
        seen.add(id(a))
        dlat, dlon = math.radians(a["lat"] - lat), math.radians(a["lon"] - lon)
        h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(a["lat"])) * math.sin(dlon / 2) ** 2
        d = 6371 * 2 * math.asin(math.sqrt(h))
        if d < best_d:
            best, best_d = a, d
    return best


def plane_journey(q: Q, auth: Callable[[httpx.Client], dict], icao24: str, callsign: str | None,
                  lat: float | None, lon: float | None) -> dict:
    """A plane's path, route and details. Each part is kept once asked (path 30 minutes, route
    6 hours, aircraft a day), so clicking the same plane again asks no one."""
    icao24 = icao24.lower()
    with _lock:
        hit = _tracks.get(icao24)
    if hit and time.time() - hit[0] < TRACK_KEEP:
        out = {**hit[1], "kept_at": int(hit[0])}
    else:
        out = _track(q, auth, icao24)
        if out.get("track") or out.get("kept_ok"):
            with _lock:
                _tracks[icao24] = (time.time(), out)
                for k in [k for k, v in _tracks.items() if time.time() - v[0] > TRACK_KEEP]:
                    _tracks.pop(k, None)
    out = {k: v for k, v in out.items() if k != "kept_ok"}
    if callsign:
        from worldmodel_api.airlines import airline

        out["airline"] = airline(callsign)
        out["route"] = _route(callsign, lat, lon)
    with _lock:
        hit_a = _aircraft_kept.get(icao24)
    if hit_a and time.time() - hit_a[0] < AIRCRAFT_KEEP:
        out["aircraft"] = hit_a[1]
    else:
        out["aircraft"] = _aircraft(icao24)
        if out["aircraft"]:
            with _lock:
                _aircraft_kept[icao24] = (time.time(), out["aircraft"])
    return out


def _track(q: Q, auth: Callable[[httpx.Client], dict], icao24: str) -> dict:
    """The plane's path this flight from OpenSky; kept_ok marks an answer worth keeping (a path, or no flight)."""
    out: dict = {"track": None, "route": None, "from_airport": None, "note": None}
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(OPENSKY_TRACK, params={"icao24": icao24.lower(), "time": 0}, headers=auth(client))
            if r.status_code == 404:
                out["note"] = "OpenSky has no path for this flight yet."
                out["kept_ok"] = True
            elif r.status_code == 429:
                out["note"] = "OpenSky's daily limit is used up, so no path for now."
            else:
                r.raise_for_status()
                path = (r.json() or {}).get("path") or []
                lines, cur = [], []
                for p in path:
                    if p[1] is None or p[2] is None:
                        continue
                    pt = [round(p[2], 4), round(p[1], 4)]
                    if cur and abs(pt[0] - cur[-1][0]) > 180:
                        lines.append(cur)
                        cur = []
                    cur.append(pt)
                if cur:
                    lines.append(cur)
                lines = [ln for ln in lines if len(ln) >= 2]
                if lines:
                    geom = {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}
                    out["track"] = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {"id": icao24}}],
                                    "from": path[0][0], "points": len(path)}
                    start = lines[0][0]
                    out["from_airport"] = _nearest_airport(airports(q), start[0], start[1])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        out["note"] = f"OpenSky did not answer for the path ({exc.__class__.__name__})."
    return out


def _aircraft(icao24: str) -> dict | None:
    """Registration, type and more from adsb.lol's receivers, when one hears the plane now."""
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "worldmodel (personal research tool)"}) as client:
            r = client.get(ADSB_HEX.format(icao24.lower()))
            r.raise_for_status()
            ac = (r.json().get("ac") or [None])[0]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return None
    if not ac:
        return None
    alt = ac.get("nav_altitude_mcp") or ac.get("nav_altitude_fms")
    return {"registration": ac.get("r"), "type": ac.get("t"), "description": ac.get("desc"), "operator": ac.get("ownOp"),
            "year": ac.get("year"), "category": ac.get("category"), "emergency": None if ac.get("emergency") in (None, "none") else ac["emergency"],
            "squawk": ac.get("squawk"), "target_altitude_m": round(alt * 0.3048) if isinstance(alt, (int, float)) else None,
            "military": bool((ac.get("dbFlags") or 0) & 1)}
