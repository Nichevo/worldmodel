"""Planes and ships now, for the part of the map in view, asked for only while the map's
live layers are on.

- Planes: OpenSky Network's state vectors for a box (anonymous, or with an API client in
  OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET for more requests a day). One request a minute
  at most with a client, every three minutes without; after a 429 nothing more is asked
  until OpenSky's wait is over, and the last planes stay on show.
- Ships: aisstream.io's websocket (AISSTREAM_API_KEY), listened to in a background thread
  for the box last asked for. Positions are kept for 20 minutes; the socket closes when no
  one has asked for five minutes. When the listener stops (bad key, blocked connection) the
  reason stays on show and it tries again after 30 seconds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time

import httpx

log = logging.getLogger(__name__)

OPENSKY = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
AISSTREAM = "wss://stream.aisstream.io/v0/stream"
PLANE_EVERY = 60.0     # seconds between OpenSky requests with an API client (and adsb.lol's)
PLANE_EVERY_ANON = 180.0  # without one: anonymous users get about 400 credits a day, 1-4 a request
SHIP_KEEP = 20 * 60    # seconds a ship's last position is shown
SHIP_IDLE = 5 * 60     # the socket closes after this long without a request
MAX_SHIPS = 4000


def _lon(v: float) -> float:
    return ((v + 180) % 360) - 180 if not -180 <= v <= 180 else v


def boxes(west: float, south: float, east: float, north: float) -> list[tuple[float, float, float, float]]:
    """The map window as one or two boxes within -180..180 (a Pacific-centred view crosses the date line)."""
    south, north = max(-90.0, south), min(90.0, north)
    if east - west >= 360:
        return [(-180.0, south, 180.0, north)]
    w, e = _lon(west), _lon(east)
    return [(w, south, e, north)] if w <= e else [(w, south, 180.0, north), (-180.0, south, e, north)]


def inside(lon: float, lat: float, bx: list[tuple[float, float, float, float]]) -> bool:
    return any(w <= lon <= e and s <= lat <= n for w, s, e, n in bx)


# ----------------------------------------------------------------------------- planes (OpenSky)
PLANE_CATEGORY = {  # OpenSky's ADS-B emitter categories
    2: "Light (under 7 t)", 3: "Small (7 to 34 t)", 4: "Large (34 to 136 t)", 5: "Large, high wake (B757)",
    6: "Heavy (over 136 t)", 7: "High performance", 8: "Helicopter", 9: "Glider", 10: "Balloon or airship",
    11: "Parachutist", 12: "Ultralight", 14: "Drone", 15: "Spacecraft",
}


def plane_group(cat) -> str:
    """How the map draws a plane, from its ADS-B category."""
    if cat in (4, 5, 6):
        return "airliner"
    if cat in (2, 3, 12):
        return "light"
    if cat == 8:
        return "helicopter"
    if cat in (9, 10, 11):
        return "glider"
    if cat == 7:
        return "fast"
    if cat == 14:
        return "drone"
    return "unknown"

class Planes:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_at = 0.0
        self.last_box: list | None = None
        self.last: dict | None = None
        self.token: tuple[str, float] | None = None
        self.blocked_until = 0.0
        self.blocked_why = ""

    def _kept(self, bx: list, error: str) -> dict:
        """The planes last read (if any), with why they are not new."""
        if not self.last:
            return {"type": "FeatureCollection", "features": [], "count": 0, "error": error}
        mins = max(1, round((time.time() - self.last_at) / 60))
        return {**self._filter(self.last, bx), "error": f"{error} Showing planes from {mins} min ago."}

    def _auth(self, client: httpx.Client) -> dict:
        cid, secret = os.environ.get("OPENSKY_CLIENT_ID"), os.environ.get("OPENSKY_CLIENT_SECRET")
        if not cid or not secret:
            return {}
        if not self.token or self.token[1] < time.time() + 60:
            r = client.post(OPENSKY_TOKEN, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret})
            r.raise_for_status()
            body = r.json()
            self.token = (body["access_token"], time.time() + float(body.get("expires_in", 1800)))
        return {"Authorization": f"Bearer {self.token[0]}"}

    def get(self, west: float, south: float, east: float, north: float) -> dict:
        bx = boxes(west, south, east, north)
        with self.lock:
            every = PLANE_EVERY if os.environ.get("OPENSKY_CLIENT_ID") and os.environ.get("OPENSKY_CLIENT_SECRET") else PLANE_EVERY_ANON
            fresh = time.time() - self.last_at < every
            if self.last and fresh and self.last_box and all(
                    any(w0 <= w and e <= e0 and s0 <= s and n <= n0 for w0, s0, e0, n0 in self.last_box) for w, s, e, n in bx):
                return self._filter(self.last, bx)
            if fresh and self.last:  # asked again too soon for a new box: what we have, marked as such
                return {**self._filter(self.last, bx), "note": f"Planes refresh every {int(every // 60)} min; moved views fill in at the next."}
            if time.time() < self.blocked_until:  # OpenSky said wait: don't spend more requests
                return self._kept(bx, self.blocked_why)
            states, error = [], None
            try:
                with httpx.Client(timeout=20) as client:
                    head = self._auth(client)
                    for w, s, e, n in bx:
                        r = client.get(OPENSKY, params={"lamin": s, "lomin": w, "lamax": n, "lomax": e, "extended": 1}, headers=head)
                        if r.status_code == 429:
                            wait = r.headers.get("X-Rate-Limit-Retry-After-Seconds")
                            wait_s = float(wait) if wait and wait.replace(".", "", 1).isdigit() else 3600.0
                            self.blocked_until = time.time() + min(wait_s, 24 * 3600)
                            hours = max(1, round(wait_s / 3600))
                            error = (f"OpenSky's daily limit is used up; planes come back in about {hours} hour{'s' if hours != 1 else ''}"
                                     " (a free OpenSky API client in Settings > Keys gives more).")
                            self.blocked_why = error
                            break
                        if r.status_code in (401, 403) and head:
                            self.token = None
                            error = "OpenSky refused the API client: check OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET in Settings > Keys."
                            break
                        r.raise_for_status()
                        states += r.json().get("states") or []
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                error = f"OpenSky did not answer ({exc.__class__.__name__})."
            if error and not states:
                return self._kept(bx, error)
            feats, seen = [], set()
            for st in states:
                if st[5] is None or st[6] is None or st[8] or st[0] in seen:  # no position, on the ground, or twice
                    continue
                seen.add(st[0])
                cat = st[17] if len(st) > 17 and isinstance(st[17], int) else None
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(st[5], 4), round(st[6], 4)]},
                              "properties": {"id": st[0], "callsign": (st[1] or "").strip() or None, "country": st[2],
                                             "altitude_m": round(st[7]) if st[7] is not None else None,
                                             "speed_kmh": round(st[9] * 3.6) if st[9] is not None else None,
                                             "heading": round(st[10]) if st[10] is not None else 0,
                                             "climb_ms": round(st[11], 1) if len(st) > 11 and st[11] is not None else None,
                                             "squawk": st[14] if len(st) > 14 else None,
                                             "seen": st[4] if len(st) > 4 else None,
                                             "category": cat, "group": plane_group(cat)}})
            self.last = {"type": "FeatureCollection", "features": feats, "at": int(time.time())}
            self.last_at, self.last_box = time.time(), bx
            return self._filter(self.last, bx)

    def table(self) -> dict:
        """Every plane from the last OpenSky answer, for the planes table."""
        rows = []
        for f in (self.last or {}).get("features") or []:
            p = dict(f["properties"])
            p["lon"], p["lat"] = f["geometry"]["coordinates"]
            p["category_name"] = PLANE_CATEGORY.get(p.get("category")) if p.get("category") is not None else None
            rows.append(p)
        return {"planes": rows, "at": (self.last or {}).get("at"), "source": "OpenSky Network",
                "note": "The planes in the map's area from the last request (the map asks every one to three minutes while Planes now is on)."}

    @staticmethod
    def _filter(found: dict, bx: list) -> dict:
        feats = [f for f in found["features"] if inside(*f["geometry"]["coordinates"], bx)]
        return {**found, "features": feats, "count": len(feats), "source": "OpenSky Network"}


# ----------------------------------------------------------------------------- military planes (adsb.lol)
ADSB_LOL_MIL = "https://api.adsb.lol/v2/mil"


class MilitaryPlanes:
    """Every plane adsb.lol's receivers flag as military, worldwide, asked for at most once a minute
    and filtered to the window. ODbL; volunteers' receivers, so coverage is thin over the sea."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_at = 0.0
        self.last: dict | None = None

    def get(self, west: float, south: float, east: float, north: float) -> dict:
        bx = boxes(west, south, east, north)
        with self.lock:
            if not self.last or time.time() - self.last_at >= PLANE_EVERY:
                try:
                    with httpx.Client(timeout=20, headers={"User-Agent": "worldmodel (personal research tool)"}) as client:
                        r = client.get(ADSB_LOL_MIL)
                        r.raise_for_status()
                        ac = r.json().get("ac") or []
                except (httpx.HTTPError, ValueError) as exc:
                    if not self.last:
                        return {"type": "FeatureCollection", "features": [], "error": f"adsb.lol did not answer ({exc.__class__.__name__})."}
                    ac = None
                if ac is not None:
                    feats = []
                    for a in ac:
                        lat, lon = a.get("lat"), a.get("lon")
                        if lat is None or lon is None or a.get("alt_baro") == "ground":
                            continue
                        alt = a.get("alt_baro")
                        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                                      "properties": {"id": a.get("hex"), "callsign": (a.get("flight") or "").strip() or None,
                                                     "registration": a.get("r"), "aircraft": a.get("t"), "description": a.get("desc"),
                                                     "military": True,
                                                     "altitude_m": round(alt * 0.3048) if isinstance(alt, (int, float)) else None,
                                                     "speed_kmh": round(a["gs"] * 1.852) if isinstance(a.get("gs"), (int, float)) else None,
                                                     "heading": round(a.get("track") or 0)}})
                    self.last = {"type": "FeatureCollection", "features": feats, "at": int(time.time())}
                    self.last_at = time.time()
            feats = [f for f in self.last["features"] if inside(*f["geometry"]["coordinates"], bx)]
            return {**self.last, "features": feats, "count": len(feats), "source": "adsb.lol (military)"}


# ----------------------------------------------------------------------------- ships (aisstream.io)
RETRY_AFTER = 30.0     # seconds before trying aisstream again after the listener stopped with an error
OPEN_TIMEOUT = 60      # aisstream can take 20 s or more to answer a new connection
TIDY_EVERY = 3600.0    # seconds between turning finished days into Parquet and deleting old ones
WORLD_LISTEN = 10 * 60  # how long each whole-world snapshot listens
DETAILS_EVERY = 300.0   # seconds between saves of the ships' details file
SHIP_MESSAGES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"]
# Where Ships are collected in the background (Settings > Transport). aisstream boxes are
# [[lat, lon], [lat, lon]]; these are (west, south, east, north) like boxes().
SHIP_AREAS = {
    "pacific": ("New Zealand, Australia and the South Pacific", [(110.0, -50.0, 180.0, 5.0), (-180.0, -50.0, -140.0, 5.0)]),
    "world": ("the whole world", [(-180.0, -90.0, 180.0, 90.0)]),
}


def _settings() -> dict:
    from worldmodel_contract import local

    try:
        return local.load_settings()
    except Exception:  # noqa: BLE001 - defaults if the file can't be read
        return {}


def _store():
    from worldmodel_contract import local

    from worldmodel_api.shipstore import ShipStore

    return ShipStore(local.home() / "live" / "ships")


class Ships:
    """aisstream.io ships. With "Collect ships" on (the default) one connection stays open while the
    app runs, for the area chosen in Settings, and every ship's position is saved (shipstore.py),
    so the map shows ships at once and where they were at any saved time. With it off the
    connection is only open while the map asks, for the area in view, and nothing is saved."""

    def __init__(self, store=None, settings=_settings) -> None:
        self.lock = threading.Lock()
        self.ships: dict[int, dict] = {}
        self.box: list | None = None
        self.asked = 0.0
        self.thread: threading.Thread | None = None
        self.keeper: threading.Thread | None = None
        self.error: str | None = None
        self.failed_at = 0.0
        self.messages = 0          # messages read since the listener last started
        self.connected = False
        self.resubscribe = threading.Event()
        self._store = store
        self._settings_fn = settings
        self._settings: tuple[float, dict] = (0.0, {})
        self.tidied = 0.0
        self.details_saved = time.time()
        self.world_thread: threading.Thread | None = None
        self.world_at = 0.0          # when the last whole-world snapshot started
        self.world_note: str | None = None

    def settings(self) -> dict:
        """Settings, read again at most every 10 seconds (take() asks for each message)."""
        if time.time() - self._settings[0] > 10:
            self._settings = (time.time(), self._settings_fn() or {})
        return self._settings[1]

    @property
    def store(self):
        if self._store is None:
            self._store = _store()
        return self._store

    # ------------------------------------------------------------------ what to listen to
    @staticmethod
    def key() -> str:
        return (os.environ.get("AISSTREAM_API_KEY") or "").strip()

    def collecting(self) -> bool:
        s = self.settings()
        return bool(self.key()) and bool(s.get("live_ships", True)) and bool(s.get("ships_collect", True))

    def area(self) -> tuple[str, list]:
        return SHIP_AREAS.get(str(self.settings().get("ships_area") or "pacific"), SHIP_AREAS["pacific"])

    def wanted_boxes(self) -> list:
        if self.collecting():
            return self.area()[1]
        with self.lock:
            return list(self.box or [])

    def wanted(self) -> bool:
        return self.collecting() or time.time() - self.asked < SHIP_IDLE

    def world_every(self) -> float:
        """Seconds between whole-world snapshots (0: none). Only with the Pacific area collected."""
        if not self.collecting() or str(self.settings().get("ships_area") or "pacific") == "world":
            return 0.0
        return max(0.0, float(self.settings().get("ships_world_every_hours") or 0)) * 3600

    # ------------------------------------------------------------------ running
    def start(self) -> None:
        """At app start: fill the map from what was saved lately, and keep the collector going."""
        if self.keeper and self.keeper.is_alive():
            return
        try:
            for v in self.store.recent(SHIP_KEEP):
                if v.get("lat") is not None:
                    self.ships[v["id"]] = {k: x for k, x in v.items() if x is not None}
        except Exception as exc:  # noqa: BLE001 - an empty map until ships report
            log.warning("ship store: could not read recent ships: %s", exc)
        self.keeper = threading.Thread(target=self._keep, daemon=True, name="aisstream-keeper")
        self.keeper.start()

    def _keep(self) -> None:
        while True:
            try:
                if self.collecting():
                    self.ensure()
                every = self.world_every()
                if every and time.time() - self.world_at >= every and not (self.world_thread and self.world_thread.is_alive()):
                    self.world_at = time.time()
                    self.world_thread = threading.Thread(target=self._world, args=(self.key(),), daemon=True, name="aisstream-world")
                    self.world_thread.start()
                if time.time() - self.details_saved >= DETAILS_EVERY:
                    self.details_saved = time.time()
                    self.store.save_details(int(self.settings().get("ships_keep_days") or 30))
                if time.time() - self.tidied >= TIDY_EVERY:
                    self.tidied = time.time()
                    self.store.tidy(int(self.settings().get("ships_keep_days") or 30))
            except Exception as exc:  # noqa: BLE001 - keep going
                log.warning("ship collector: %s", exc)
            time.sleep(RETRY_AFTER)

    def ensure(self) -> None:
        """(Re)start the listener, but keep the reason it last stopped on show and wait a little before
        trying again, so a bad key or a blocked connection is seen rather than retried on every request."""
        key = self.key()
        if not key:
            return
        with self.lock:
            if (not self.thread or not self.thread.is_alive()) and time.time() - self.failed_at >= RETRY_AFTER:
                self.thread = threading.Thread(target=self._run, args=(key,), daemon=True, name="aisstream")
                self.thread.start()

    # ------------------------------------------------------------------ the map
    def get(self, west: float, south: float, east: float, north: float, at: float | None = None) -> dict:
        bx = boxes(west, south, east, north)
        if at is not None:
            return self.saved_at(at, bx)
        if not self.key():
            return {"type": "FeatureCollection", "features": [], "count": 0,
                    "error": "Ships now needs a free aisstream.io key: add AISSTREAM_API_KEY in Settings > Keys (or .env)."}
        collecting = self.collecting()
        with self.lock:
            self.asked = time.time()
            if not collecting and bx != self.box:
                self.box = bx
                self.resubscribe.set()
        self.ensure()
        with self.lock:
            now = time.time()
            for k in [k for k, v in self.ships.items() if now - v["seen"] > SHIP_KEEP]:
                del self.ships[k]
            feats = [_ship_feature(v) for v in self.ships.values() if "lat" in v and inside(v["lon"], v["lat"], bx)][:MAX_SHIPS]
            if self.connected and self.messages:
                note = f"{self.messages:,} reports read since connecting."
            elif self.connected:
                note = "Connected to aisstream.io, waiting for the first reports (a few minutes for a new area)."
            else:
                note = "Connecting to aisstream.io (it can take up to a minute)…"
        if collecting:
            label, area = self.area()
            note = f"Collecting ships for {label}. {note}"
            if not any(w <= e2 and w2 <= e and s <= n2 and s2 <= n for w, s, e, n in bx for w2, s2, e2, n2 in area):
                note = f"Ships are collected for {label} only; change the area in Settings > Transport. {note}"
        out = {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "aisstream.io", "note": note,
               "collecting": collecting}
        if self.error:
            out["error"] = self.error
        return out

    def saved_at(self, when: float, bx: list) -> dict:
        """Ships where they were at a saved time (the map's ships time slider)."""
        try:
            every = self.world_every()
            found = self.store.at(when, bx, self.area()[1] if every else None, every + WORLD_LISTEN if every else 0)
        except Exception as exc:  # noqa: BLE001 - shown on the map
            return {"type": "FeatureCollection", "features": [], "count": 0, "error": f"Could not read saved ships ({exc.__class__.__name__})."}
        feats = [_ship_feature(v) for v in found][:MAX_SHIPS]
        when_txt = time.strftime("%d %b %Y %H:%M", time.localtime(when))
        return {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "aisstream.io (saved)",
                "note": f"Ships as saved at {when_txt}" + ("" if feats else ": none saved for this area and time"), "at": int(when)}

    def track(self, mmsi: int, hours: float = 24, end: float | None = None) -> dict:
        end = end or time.time()
        pts = self.store.track(mmsi, end - hours * 3600, end)
        live = self.ships.get(mmsi)
        if live and "lat" in live and (not pts or live["seen"] > pts[-1][0]) and live["seen"] <= end:
            pts.append((int(live["seen"]), live["lon"], live["lat"], live.get("speed_kn")))
        # Split where the ship crosses the date line, so the map doesn't draw a line round the world.
        lines, cur = [], []
        for p in pts:
            if cur and abs(p[1] - cur[-1][0]) > 180:
                lines.append(cur)
                cur = []
            cur.append([round(p[1], 4), round(p[2], 4)])
        if cur:
            lines.append(cur)
        lines = [ln for ln in lines if len(ln) >= 2]
        geom = None if not lines else {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}
        name = (live or {}).get("name") or self.store.names.get(mmsi)
        feats = [{"type": "Feature", "geometry": geom, "properties": {"id": mmsi, "name": name}}] if geom else []
        return {"type": "FeatureCollection", "features": feats, "points": len(pts), "hours": hours,
                "from": pts[0][0] if pts else None, "to": pts[-1][0] if pts else None}

    def _row(self, mmsi: int, d: dict) -> dict:
        from worldmodel_api.shipflags import flag

        live = self.ships.get(mmsi) or {}
        f = flag(mmsi)
        kind = d.get("kind") or live.get("kind")
        last = max(d.get("last_seen") or 0, live.get("seen") or 0) or None
        return {"id": mmsi, "name": d.get("name") or live.get("name"), "imo": d.get("imo") or live.get("imo"),
                "callsign": d.get("callsign"), "flag": f[1] if f else None, "flag_code": f[0] if f else None,
                "kind": kind, "type": ship_type_name(kind), "group": ship_group(kind),
                "length_m": d.get("length_m"), "width_m": d.get("width_m"), "draught_m": d.get("draught_m"),
                "destination": d.get("destination"), "eta": d.get("eta"),
                "status": NAV_STATUS.get(d.get("status")) if isinstance(d.get("status"), int) else None,
                "speed_kn": live.get("speed_kn", d.get("speed_kn")), "heading": live.get("heading", d.get("heading")),
                "lat": live.get("lat", d.get("lat")), "lon": live.get("lon", d.get("lon")),
                "first_seen": d.get("first_seen"), "last_seen": last}

    def table(self, q: str = "", group: str = "", flag_code: str = "", sort: str = "last_seen", limit: int = 200,
              offset: int = 0, hours: float = 0) -> dict:
        """Every ship seen (saved details while collecting, else those in memory), filtered and sorted."""
        with self.lock:
            ids = set(self.store.details) | set(self.ships)
            rows = [self._row(m, self.store.details.get(m, {})) for m in ids]
        if hours:
            cut = time.time() - hours * 3600
            rows = [r for r in rows if (r["last_seen"] or 0) >= cut]
        if q:
            ql = q.lower()
            rows = [r for r in rows if any(ql in str(r.get(k) or "").lower() for k in ("name", "id", "imo", "callsign", "destination", "flag"))]
        if group:
            rows = [r for r in rows if r["group"] == group]
        if flag_code:
            rows = [r for r in rows if r["flag_code"] == flag_code.upper()]
        groups: dict[str, int] = {}
        for r in rows:
            groups[r["group"]] = groups.get(r["group"], 0) + 1
        desc = sort.startswith("-") or sort in ("last_seen", "length_m", "speed_kn", "first_seen")
        key = sort.lstrip("-")
        if key not in ("last_seen", "first_seen", "name", "length_m", "speed_kn", "flag", "type", "destination"):
            key = "last_seen"
        num = key in ("last_seen", "first_seen", "length_m", "speed_kn")
        rows.sort(key=lambda r: (r.get(key) is None, (-(r.get(key) or 0)) if num and desc else str(r.get(key) or "").lower() if not num else (r.get(key) or 0)))
        return {"rows": rows[offset:offset + limit], "total": len(rows), "groups": groups, "collecting": self.collecting()}

    def detail(self, mmsi: int) -> dict | None:
        with self.lock:
            d = self.store.details.get(mmsi)
            if d is None and mmsi not in self.ships:
                return None
            row = self._row(mmsi, d or {})
        row["links"] = [
            {"label": "MarineTraffic", "href": f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{mmsi}"},
            {"label": "VesselFinder", "href": f"https://www.vesselfinder.com/vessels/details/{mmsi}"},
        ]
        if row.get("imo"):
            row["links"].append({"label": "Equasis (IMO)", "href": "https://www.equasis.org/"})
        return row

    def status(self) -> dict:
        label, _ = self.area()
        st = self.store.status()
        return {**st, "collecting": self.collecting(), "area": label, "connected": self.connected, "error": self.error,
                "keep_days": int(self.settings().get("ships_keep_days") or 30), "in_memory": len(self.ships),
                "world_every_hours": self.world_every() / 3600, "world_note": self.world_note}

    # ------------------------------------------------------------------ whole-world snapshots
    def _world(self, key: str) -> None:
        """Listen to the whole world for ten minutes and save what reports (every few hours)."""
        try:
            got = asyncio.run(self._listen_world(key))
            self.world_note = f"Last whole-world snapshot {time.strftime('%H:%M', time.localtime(self.world_at))}: {got:,} reports."
        except Exception as exc:  # noqa: BLE001 - shown in the status
            self.world_note = f"Whole-world snapshot failed: {_ship_error(exc).split(';')[0]}."
            log.warning("aisstream world snapshot: %s", exc)

    async def _listen_world(self, key: str) -> int:
        import websockets

        got, until = 0, time.time() + WORLD_LISTEN
        async with websockets.connect(AISSTREAM, open_timeout=OPEN_TIMEOUT, ping_interval=30, max_size=2**22) as ws:
            await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": [[[-90, -180], [90, 180]]],
                                      "FilterMessageTypes": SHIP_MESSAGES}))
            while time.time() < until and self.collecting():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                got += 1
                self.take(msg, count=False)
        return got

    # ------------------------------------------------------------------ the connection
    def _run(self, key: str) -> None:
        try:
            asyncio.run(self._listen(key))
        except Exception as exc:  # noqa: BLE001 - shown on the map, not raised
            why = self.error or _ship_error(exc)
            with self.lock:
                self.error, self.failed_at, self.connected = why, time.time(), False
            log.warning("aisstream stopped: %s (%s)", why, exc)
        else:
            self.connected = False

    async def _listen(self, key: str) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("the websockets package is missing; run update.bat") from exc

        self.messages = 0
        while self.wanted():
            bx = self.wanted_boxes()
            if not bx:
                return
            self.resubscribe.clear()
            async with websockets.connect(AISSTREAM, open_timeout=OPEN_TIMEOUT, ping_interval=30, max_size=2**22) as ws:
                await ws.send(json.dumps({"APIKey": key,
                                          "BoundingBoxes": [[[s, w], [n, e]] for w, s, e, n in bx],
                                          "FilterMessageTypes": SHIP_MESSAGES}))
                self.connected = True
                checked = time.time()
                while not self.resubscribe.is_set():
                    if time.time() - checked > 30:  # settings changed (area, collecting on or off)?
                        checked = time.time()
                        if not self.wanted() or self.wanted_boxes() != bx:
                            break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    self.take(json.loads(raw))

    def take(self, msg: dict, count: bool = True) -> None:
        """One aisstream message into the ships kept (and saved, while collecting). The whole-world
        snapshot passes count=False so its reports don't clear the main connection's error."""
        if msg.get("error"):
            self.error = f"aisstream.io refused: {msg['error']}" + (" (check AISSTREAM_API_KEY in Settings > Keys)"
                                                                    if "key" in str(msg["error"]).lower() else "")
            return
        meta = msg.get("MetaData") or {}
        mmsi = meta.get("MMSI")
        if not mmsi:
            return
        body = (msg.get("Message") or {}).get(msg.get("MessageType") or "") or {}
        with self.lock:
            if count:
                self.messages += 1
                self.error = None
            s = self.ships.setdefault(mmsi, {"id": mmsi, "seen": int(time.time())})
            name = (meta.get("ShipName") or body.get("Name") or "").strip()
            if name:
                s["name"] = name
            kind_msg = msg.get("MessageType")
            if kind_msg in ("ShipStaticData", "StaticDataReport"):
                static = _static(kind_msg, body)
                if static.get("imo"):
                    s["imo"] = static["imo"]
                if static.get("kind"):
                    s["kind"] = static["kind"]
                    self.store.kinds[mmsi] = static["kind"]
                if static.get("name"):
                    s["name"] = static["name"]
                saving = True
            else:
                saving = False
        if saving:
            if self.collecting():
                self.store.note(mmsi, **static)
            return
        with self.lock:
            lat, lon = meta.get("latitude"), meta.get("longitude")
            if lat is None or lon is None:
                return
            s.update(lat=round(lat, 4), lon=round(lon, 4), seen=int(time.time()),
                     speed_kn=body.get("Sog"), heading=body.get("TrueHeading") if body.get("TrueHeading") not in (None, 511) else body.get("Cog"))
            ship = dict(s)
        if self.collecting():
            try:
                self.store.add(mmsi, ship["lat"], ship["lon"], ship.get("speed_kn"), ship.get("heading"), ship.get("name"),
                               kind=ship.get("kind"))
                self.store.note(mmsi, name=ship.get("name"), lat=ship["lat"], lon=ship["lon"], speed_kn=ship.get("speed_kn"),
                                heading=ship.get("heading"), status=(body.get("NavigationalStatus") if isinstance(body.get("NavigationalStatus"), int) else None))
            except OSError as exc:
                log.warning("ship store: could not save: %s", exc)


NAV_STATUS = {0: "Under way (engine)", 1: "At anchor", 2: "Not under command", 3: "Restricted manoeuvrability",
              4: "Constrained by draught", 5: "Moored", 6: "Aground", 7: "Fishing", 8: "Under way (sailing)"}
SHIP_TYPE = {30: "Fishing", 31: "Towing", 32: "Towing (long)", 33: "Dredging", 34: "Diving", 35: "Military", 36: "Sailing",
             37: "Pleasure craft", 50: "Pilot", 51: "Search and rescue", 52: "Tug", 53: "Port tender", 54: "Anti-pollution",
             55: "Law enforcement", 58: "Medical", 59: "Special craft"}


def ship_type_name(code) -> str | None:
    if not isinstance(code, int) or code <= 0:
        return None
    if code in SHIP_TYPE:
        return SHIP_TYPE[code]
    for lo, name in ((20, "Wing in ground"), (40, "High-speed craft"), (60, "Passenger"), (70, "Cargo"), (80, "Tanker"), (90, "Other")):
        if lo <= code <= lo + 9:
            return name
    return "Other"


def _static(kind: str, body: dict) -> dict:
    """The details in a ShipStaticData (class A) or StaticDataReport (class B) message."""
    out: dict = {}
    if kind == "StaticDataReport":
        a, b = body.get("ReportA") or {}, body.get("ReportB") or {}
        if a.get("Valid") and (a.get("Name") or "").strip():
            out["name"] = a["Name"].strip()
        if b.get("Valid"):
            body = {"Type": b.get("ShipType"), "CallSign": b.get("CallSign"), "Dimension": b.get("Dimension")}
        else:
            return out
    else:
        if (body.get("Name") or "").strip():
            out["name"] = body["Name"].strip()
        if body.get("ImoNumber"):
            out["imo"] = body["ImoNumber"]
        if (body.get("Destination") or "").strip():
            out["destination"] = body["Destination"].strip()
        eta = body.get("Eta") or {}
        if eta.get("Month") and eta.get("Day"):
            out["eta"] = f"{eta['Day']:02d}/{eta['Month']:02d} {eta.get('Hour', 0):02d}:{eta.get('Minute', 0):02d} UTC"
        if body.get("MaximumStaticDraught"):
            out["draught_m"] = body["MaximumStaticDraught"]
    if (body.get("CallSign") or "").strip():
        out["callsign"] = body["CallSign"].strip()
    if isinstance(body.get("Type"), int) and body["Type"] > 0:
        out["kind"] = body["Type"]
    dim = body.get("Dimension") or {}
    if isinstance(dim, dict) and any(dim.get(k) for k in "ABCD"):
        out["length_m"] = (dim.get("A") or 0) + (dim.get("B") or 0) or None
        out["width_m"] = (dim.get("C") or 0) + (dim.get("D") or 0) or None
    return out


def ship_group(code) -> str:
    """The kind of ship from its AIS type code, as the map colours it."""
    c = code if isinstance(code, int) else None
    if c is None or c <= 0:
        return "unknown"
    if 70 <= c <= 79:
        return "cargo"
    if 80 <= c <= 89:
        return "tanker"
    if 60 <= c <= 69:
        return "passenger"
    if c == 30:
        return "fishing"
    if c in (31, 32, 50, 52, 53):
        return "tug"
    if c in (36, 37):
        return "leisure"
    if 40 <= c <= 49:
        return "fast"
    if c in (35, 51, 55, 58):
        return "official"  # military, search and rescue, law enforcement, medical
    return "other"


def _ship_feature(v: dict) -> dict:
    props = {k: v[k] for k in ("id", "name", "imo", "speed_kn", "heading", "seen", "kind") if v.get(k) is not None}
    props["group"] = ship_group(v.get("kind"))
    if not isinstance(props.get("heading"), (int, float)) or not 0 <= props["heading"] < 360:
        props["heading"] = 0
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]}, "properties": props}


def _ship_error(exc: Exception) -> str:
    """Why the aisstream listener stopped, in words."""
    name = exc.__class__.__name__
    text = str(exc)
    if "ConnectionClosed" in name:
        return f"aisstream.io closed the connection ({text or name}); trying again in {int(RETRY_AFTER)} s. A wrong or expired key is the usual cause."
    if "InvalidStatus" in name or "InvalidHandshake" in name or "Proxy" in name:
        return f"aisstream.io would not connect ({text or name}); trying again in {int(RETRY_AFTER)} s."
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, OSError)):
        return f"Could not reach aisstream.io ({name}: {text}); trying again in {int(RETRY_AFTER)} s."
    return f"aisstream.io: {text or name}; trying again in {int(RETRY_AFTER)} s."


PLANES = Planes()
MIL_PLANES = MilitaryPlanes()
SHIPS = Ships()
