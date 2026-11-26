"""Where a clicked ship or plane has come from and is going.

- Ships: the path saved while collecting (shipstore.py), and the destination its crew typed into
  its AIS set, matched to a port in the World Port Index by UN/LOCODE ("NZ AKL", "NZAKL") or name.
- Planes: the path of its flight so far from OpenSky's tracks endpoint (one request per click),
  and the route its callsign flies from adsbdb's route database (airline flights only).
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
ROUTES_URL = "https://api.adsbdb.com/v0/callsign/{}"  # adsb.lol's routeset now answers only its own map page
ADSB_HEX = "https://api.adsb.lol/v2/hex/{}"
ROUTE_KEEP = 3 * 86400  # a callsign flies the same route for days: looked up again after this
ROUTE_HISTORY = 60 * 86400  # ... but kept this long on disk, for the routes of past flights
ROUTE_MISS = 6 * 3600  # a callsign adsbdb had no route for is asked again after this
TRACK_KEEP = 30 * 60      # a plane's path is asked of OpenSky at most once in this time
AIRCRAFT_KEEP = 90 * 86400  # registration and type change rarely
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
    sea = None  # the way by sea to the port, through the lanes and straits (seapath.py)
    if port and port.get("lon") is not None and detail.get("lat") is not None:
        from worldmodel_api.seapath import sea_path
        sea = sea_path(detail["lon"], detail["lat"], port["lon"], port["lat"])
    return {"track": track, "sea_path": sea, "destination": detail.get("destination"), "eta": detail.get("eta"), "port": port,
            "came_from": detail.get("last_port"), "came_from_at": detail.get("last_port_at"),
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


def _parse_route(body) -> dict | None:
    """adsbdb's answer for a callsign: {"response": {"flightroute": {origin, midpoint?, destination}}}."""
    resp = body.get("response") if isinstance(body, dict) else None
    fr = resp.get("flightroute") if isinstance(resp, dict) else None
    if not isinstance(fr, dict):
        return None
    stops = [a for a in (fr.get("origin"), fr.get("midpoint"), fr.get("destination")) if isinstance(a, dict)]
    if len(stops) < 2:
        return None
    return {"codes": "-".join(a.get("icao_code") or a.get("iata_code") or "?" for a in stops), "plausible": True,
            "airports": [{"name": a.get("name"), "iata": a.get("iata_code"), "icao": a.get("icao_code"), "city": a.get("municipality"),
                          "country": a.get("country_iso_name"), "lon": a.get("longitude"), "lat": a.get("latitude")} for a in stops]}


ROUTE_ERRORS: list[str] = []  # the last few failed route requests, for the planes status
ROUTE_GAP = 0.3  # seconds between adsbdb requests: one callsign per request, asked politely


class RouteError(Exception):
    """adsbdb did not give a usable answer (busy, down, or something other than JSON)."""


def _ask_route(client: httpx.Client, cs: str) -> dict | None:
    r = client.get(ROUTES_URL.format(cs))
    if r.status_code == 404:
        return None  # adsbdb answers 404 {"response": "unknown callsign"}: no route known
    if r.status_code == 429:
        raise RouteError("adsbdb says too many requests (HTTP 429)")
    if r.status_code != 200:
        raise RouteError(f"HTTP {r.status_code}, {len(r.content)} bytes")
    try:
        body = r.json()
    except ValueError:
        raise RouteError(f"HTTP {r.status_code} but not JSON ({len(r.content)} bytes: {r.text[:60]!r})") from None
    return _parse_route(body)


def routes(planes: list[tuple[str, float | None, float | None]]) -> dict[str, dict | None]:
    """Routes for many callsigns from adsbdb, one request each with a short gap. Callsigns it has
    no route for map to None; callsigns not reached (it stopped answering part way) are left out,
    so they are asked again later. Raises when not even the first could be asked."""
    out: dict[str, dict | None] = {}
    with httpx.Client(timeout=20, headers={"User-Agent": "worldmodel (personal research tool)", "Accept": "application/json"}) as client:
        for i, (cs, _lat, _lon) in enumerate(planes):
            k = _key(cs)
            if not k or k in out:
                continue
            if i:
                time.sleep(ROUTE_GAP)
            try:
                out[k] = _ask_route(client, k)
            except (httpx.HTTPError, RouteError):
                if not out:
                    raise
                break
    return out


def _route(callsign: str, lat: float | None, lon: float | None) -> tuple[dict | None, bool]:
    """The route a callsign flies (adsbdb), and whether the answer is worth keeping (not an error)."""
    cs = _key(callsign)
    if not cs:
        return None, False
    try:
        got = routes([(cs, lat, lon)]).get(cs)
    except (httpx.HTTPError, RouteError, ValueError, KeyError, TypeError) as exc:
        log.warning("adsbdb route for %s: %s", cs, exc)
        ROUTE_ERRORS.append(f"{time.strftime('%H:%M')} {exc.__class__.__name__}: {str(exc)[:160]}")
        del ROUTE_ERRORS[:-5]
        return None, False  # not kept: try again on the next click
    return got, True


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
                  lat: float | None, lon: float | None, store=None) -> dict:
    """A plane's path, route and details. Each part is kept once asked (path 30 minutes, route
    3 days, aircraft 90 days; on disk when a store is given, else in memory), so clicking the same
    plane again asks no one. With no path from OpenSky, the positions saved locally are drawn."""
    icao24 = icao24.lower()
    hit = _kept(store, _tracks, "track", icao24, TRACK_KEEP)
    if hit:
        out = {**hit[0], "kept_at": int(hit[1])}
    else:
        out = _track(q, auth, icao24)
        if out.get("track") or out.get("kept_ok"):
            _keep(store, _tracks, "track", icao24, out, 2 * 86400)
    out = {k: v for k, v in out.items() if k != "kept_ok"}
    if not out.get("track") and store is not None:
        saved = _saved_track(store, icao24)
        if saved:
            out["track"] = saved
            out["note"] = ((out.get("note") or "") + " The path drawn is from the positions saved here.").strip()
    if callsign:
        from worldmodel_api.airlines import airline

        out["airline"] = airline(callsign)
        cs = _key(callsign)
        hit = _kept(store, _routes, "route", cs, ROUTE_KEEP)
        if hit and hit[0] is None and time.time() - hit[1] > ROUTE_MISS:
            hit = None  # "no route" answers are asked again sooner
        if hit:
            out["route"] = hit[0]
        else:
            out["route"], ok = _route(callsign, lat, lon)
            if not ok and ROUTE_ERRORS:
                out["note"] = ((out.get("note") or "") + f" The route look-up at adsbdb failed ({ROUTE_ERRORS[-1].split(' ', 1)[1]}).").strip()
            if ok:
                _keep(store, _routes, "route", cs, out["route"], ROUTE_HISTORY if store is not None else ROUTE_KEEP)
    hit = _kept(store, _aircraft_kept, "aircraft", icao24, AIRCRAFT_KEEP)
    if hit:
        out["aircraft"] = hit[0]
    else:
        out["aircraft"] = _aircraft(icao24)
        if out["aircraft"]:
            _keep(store, _aircraft_kept, "aircraft", icao24, out["aircraft"], AIRCRAFT_KEEP)
    return out


def _kept(store, memory: dict, kind: str, key: str, max_age: float):
    """(value, when) kept for a look-up, from the store's file if there is one, else memory."""
    if store is not None:
        return store.lookup(kind, key, max_age)
    with _lock:
        hit = memory.get(key)
    return (hit[1], hit[0]) if hit and time.time() - hit[0] < max_age else None


def _keep(store, memory: dict, kind: str, key: str, value, drop_after: float) -> None:
    if store is not None:
        store.keep(kind, key, value, drop_after)
        return
    with _lock:
        memory[key] = (time.time(), value)
        for k in [k for k, v in memory.items() if time.time() - v[0] > drop_after]:
            memory.pop(k, None)


def _saved_track(store, icao24: str, hours: float = 18) -> dict | None:
    """This flight's path from the positions saved here: the last run with no gap over an hour."""
    try:
        pts = store.track(icao24, time.time() - hours * 3600, time.time())
    except Exception as exc:  # noqa: BLE001 - no saved path then
        log.info("saved plane track %s: %s", icao24, exc)
        return None
    run: list = []
    for p in pts:
        if run and p[0] - run[-1][0] > 3600:
            run = []
        run.append(p)
    if len(run) < 2:
        return None
    lines, cur = [], []
    for _, x, y in run:
        if cur and abs(x - cur[-1][0]) > 180:
            lines.append(cur)
            cur = []
        cur.append([round(x, 4), round(y, 4)])
    lines.append(cur)
    lines = [ln for ln in lines if len(ln) >= 2]
    if not lines:
        return None
    geom = {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {"id": icao24}}],
            "from": run[0][0], "points": len(run)}


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
