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
import csv
import json
import logging
import math
import os
import threading
import time

import httpx

from worldmodel_api.airlines import airline

log = logging.getLogger(__name__)

OPENSKY = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
AISSTREAM = "wss://stream.aisstream.io/v0/stream"
ROUTES_PER_ROUND = 100  # routes asked of adsbdb per part (one request each, 0.3 s apart; the table refreshes after each)
ROUTES_PER_RUN = 2000   # ... and per background run, about 12 minutes
PLANE_EVERY = 60.0     # seconds between OpenSky requests with an API client (and adsb.lol's)
PLANE_WORLD_EVERY = 5 * 60.0        # background whole-world requests with an OpenSky API client
PLANE_WORLD_EVERY_ANON = 30 * 60.0  # ... and without one (48 a day, about half the anonymous credits)
TABLE_KEEP = 45.0  # seconds the planes table (and its counts) is kept before being worked out again
SAVED_FILL = 40 * 60.0  # a view outside the last OpenSky box shows saved positions up to this old
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


def _nm(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def along(coords: list, nm: float) -> tuple[float, float, bool]:
    """The point `nm` nautical miles along a path ([lon, lat] points), and whether it is the end
    (the ship would be there by now). Works across the date line."""
    left = max(0.0, nm)
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        if lon2 - lon1 > 180:
            lon2 -= 360
        elif lon1 - lon2 > 180:
            lon2 += 360
        step = _nm(lon1, lat1, lon2, lat2)
        if step >= left and step > 0:
            f = left / step
            return _lon(lon1 + (lon2 - lon1) * f), lat1 + (lat2 - lat1) * f, False
        left -= step
    return _lon(coords[-1][0]), coords[-1][1], True


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
    def __init__(self, store=None, settings=None) -> None:
        self._store = store
        self._settings_fn = settings
        self._aircraft = None
        self.tidied = 0.0
        self.keeper: threading.Thread | None = None
        self.world_at = 0.0
        self.world_note: str | None = None
        self.route_thread: threading.Thread | None = None
        self.route_failed: dict[str, float] = {}
        self.route_note: str | None = None
        self.route_pause = 0.0
        self.lock = threading.Lock()
        self._fetching = False
        self.last_at = 0.0
        self.last_box: list | None = None
        self.last: dict | None = None
        self.token: tuple[str, float] | None = None
        self.blocked_until = 0.0
        self.blocked_why = ""
        self._tables: dict = {}
        self._tables_lock = threading.Lock()
        self._table_build = threading.Lock()

    @property
    def store(self):
        if self._store is None:
            from worldmodel_contract import local

            from worldmodel_api.planestore import PlaneStore

            self._store = PlaneStore(local.home() / "live" / "planes")
        return self._store

    def settings(self) -> dict:
        return (self._settings_fn or _settings)() or {}

    @property
    def aircraft(self):
        if self._aircraft is None:
            from worldmodel_api.aircraftdb import AircraftDb

            self._aircraft = AircraftDb(self.store.folder)
        return self._aircraft

    def describe(self, p: dict) -> dict:
        """Add what the aircraft database knows (type, model, registration, flag, military) and a better
        map group when the plane sent no ADS-B category: by its type, else airliner when its callsign is
        an airline's."""
        info = self.aircraft.find(p.get("id")) if self.settings().get("planes_types", True) else {}
        al = airline(p.get("callsign"))
        p.update(type=info.get("type"), model=info.get("model"), reg=info.get("reg"), flag=info.get("flag"),
                 military=bool(info.get("military")), airline=al["name"] if al else None, airline_code=al["code"] if al else None)
        if (p.get("group") or "unknown") == "unknown":
            p["group"] = info.get("group") or ("airliner" if al else "unknown")
        return p

    def collecting(self) -> bool:
        return bool(self.settings().get("planes_collect", True))

    def world_every(self) -> float:
        """Seconds between background whole-world requests (0: off). A world request costs OpenSky
        4 credits: anonymous users get about 400 a day, an API client about 4,000."""
        s = self.settings()
        if not (s.get("live_planes", True) and s.get("planes_collect", True) and s.get("planes_world", True)):
            return 0.0
        client = os.environ.get("OPENSKY_CLIENT_ID") and os.environ.get("OPENSKY_CLIENT_SECRET")
        return PLANE_WORLD_EVERY if client else PLANE_WORLD_EVERY_ANON

    def start(self) -> None:
        """At app start: ask OpenSky for the whole world every so often and save it (Settings > Transport)."""
        if self.keeper and self.keeper.is_alive():
            return
        self.keeper = threading.Thread(target=self._keep, daemon=True, name="planes-world")
        self.keeper.start()

    def _keep(self) -> None:
        time.sleep(60)  # let the app start first
        while True:
            try:
                if self.settings().get("planes_types", True):
                    if self.aircraft.due():
                        self.aircraft.download()
                    elif not len(self.aircraft.keys):
                        self.aircraft.load()
            except Exception as exc:  # noqa: BLE001 - planes still show, by ADS-B category only
                log.warning("aircraft database: %s", exc)
            try:
                every = self.world_every()
                if every and time.time() - self.world_at >= every:
                    self.world_at = time.time()
                    got = self.get(-180, -90, 180, 90)
                    self.world_note = (f"Whole world at {time.strftime('%H:%M')}: {len(got.get('features') or []):,} planes."
                                       + (f" {got['error']}" if got.get("error") else ""))
            except Exception as exc:  # noqa: BLE001 - keep going
                log.warning("planes world: %s", exc)
            time.sleep(30)

    def _save(self, feats: list) -> None:
        """Keep every OpenSky answer's planes (Settings > Transport), and tidy the files hourly."""
        if not self.collecting():
            return
        try:
            self.store.add_many(feats)
            if time.time() - self.tidied >= TIDY_EVERY:
                self.tidied = time.time()
                keep = int(self.settings().get("planes_keep_days") or 30)
                threading.Thread(target=self.store.tidy, args=(keep,), daemon=True, name="planes-tidy").start()
        except Exception as exc:  # noqa: BLE001 - the map still gets its planes
            log.warning("plane store: %s", exc)

    def saved_at(self, when: float, west: float, south: float, east: float, north: float) -> dict:
        """Planes where they were at a saved time (the map's time slider)."""
        bx = boxes(west, south, east, north)
        try:
            found = self.store.at(when, bx)
        except Exception as exc:  # noqa: BLE001 - shown on the map
            return {"type": "FeatureCollection", "features": [], "count": 0, "error": f"Could not read saved planes ({exc.__class__.__name__})."}
        feats = []
        for v in found:
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(v["lon"], 4), round(v["lat"], 4)]},
                          "properties": self.describe({k: x for k, x in v.items() if k not in ("lat", "lon")})})
        when_txt = time.strftime("%d %b %Y %H:%M", time.localtime(when))
        return {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "OpenSky Network (saved)", "at": int(when),
                "note": f"Planes as saved at {when_txt}" + ("" if feats else ": none saved for this area and time")}

    def status(self) -> dict:
        from worldmodel_api.journeys import ROUTE_ERRORS

        try:
            out = self.store.status()
        except Exception as exc:  # noqa: BLE001
            out = {"days": 0, "bytes": 0, "first": None, "last": None, "error": str(exc)}
        return {**out, "collecting": self.collecting(), "keep_days": int(self.settings().get("planes_keep_days") or 30),
                "world_every_minutes": round(self.world_every() / 60), "world_note": self.world_note, "route_note": self.route_note,
                "route_errors": list(ROUTE_ERRORS)}

    def _kept(self, bx: list, error: str) -> dict:
        """The planes last read (if any), with why they are not new."""
        if not self.last:
            return {"type": "FeatureCollection", "features": [], "count": 0, "error": error}
        mins = max(1, round((time.time() - self.last_at) / 60))
        return {**self._with_saved(self._filter(self.last, bx), bx, outside_only=False), "error": f"{error} Showing planes from {mins} min ago."}

    def _with_saved(self, found: dict, bx: list, note: str | None = None, outside_only: bool = True) -> dict:
        """Planes of the last answer, plus the saved positions (from the whole-world requests and other
        views, up to SAVED_FILL old) of planes in the view that answer did not cover, so a view
        outside the last box still shows planes until its own request."""
        if not self.collecting():
            return {**found, **({"note": note} if note else {})}
        try:
            saved = self.store.at(time.time(), bx, back=SAVED_FILL)
        except Exception as exc:  # noqa: BLE001 - the last answer is still shown
            log.warning("plane store: %s", exc)
            saved = []
        have = {f["properties"].get("id") for f in found["features"]}
        extra = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(v["lon"], 4), round(v["lat"], 4)]},
                  "properties": self.describe({**{k: x for k, x in v.items() if k not in ("lat", "lon")}, "saved": True})}
                 for v in saved if v["id"] not in have and not (outside_only and self.last_box and inside(v["lon"], v["lat"], self.last_box))]
        if not extra:
            return {**found, **({"note": note} if note else {})}
        feats = found["features"] + extra
        mins = max(1, round(max(0.0, time.time() - min(f["properties"].get("seen") or time.time() for f in extra)) / 60))
        words = f"{len(extra):,} of these planes are where they were last saved (up to {mins} min ago)."
        return {**found, "features": feats, "count": len(feats), "note": f"{note} {words}" if note else words}

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
        every = PLANE_EVERY if os.environ.get("OPENSKY_CLIENT_ID") and os.environ.get("OPENSKY_CLIENT_SECRET") else PLANE_EVERY_ANON
        # The lock covers only the checks and the swap of the new answer: OpenSky can take up to
        # 20 s, and other views asking meanwhile get what is already here instead of waiting.
        with self.lock:
            fresh = time.time() - self.last_at < every
            if self.last and fresh and self.last_box and all(
                    any(w0 <= w and e <= e0 and s0 <= s and n <= n0 for w0, s0, e0, n0 in self.last_box) for w, s, e, n in bx):
                return self._filter(self.last, bx)
            if fresh and self.last:  # asked again too soon for a new box: what we have, marked as such
                return self._with_saved(self._filter(self.last, bx), bx,
                                        f"Planes refresh every {int(every // 60)} min; moved views fill in at the next.")
            if time.time() < self.blocked_until:  # OpenSky said wait: don't spend more requests
                return self._kept(bx, self.blocked_why)
            busy = self._fetching
            self._fetching = True
        if busy:  # another view is asking OpenSky right now
            return self._kept(bx, "Planes are being fetched; they show at the next reload.")
        try:
            states, error = self._ask(bx)
            if error and not states:
                return self._kept(bx, error)
            feats = self._features(states)
            with self.lock:
                self.last = {"type": "FeatureCollection", "features": feats, "at": int(time.time())}
                self.last_at, self.last_box = time.time(), bx
            self._save(feats)
            return self._filter(self.last, bx)
        finally:
            with self.lock:
                self._fetching = False

    def _ask(self, bx: list) -> tuple[list, str | None]:
        """OpenSky's states for the boxes (one request each), and why it stopped, if it did."""
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
        return states, error

    def _features(self, states: list) -> list:
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
            self.describe(feats[-1]["properties"])
        return feats

    def flights(self, icao: str | None, callsign: str | None, days: float = 30) -> dict:
        """The flights saved for one aircraft, or for every aircraft that flew a callsign, with each
        one's route when it was looked up (kept 3 days)."""
        from worldmodel_api.journeys import ROUTE_HISTORY, _key

        found = self.store.flights(time.time() - days * 86400, time.time() + 60, icao=icao, callsign=callsign)
        for f in found[:300]:
            hit = self.store.lookup("route", _key(f["callsign"]), ROUTE_HISTORY) if f["callsign"] and airline(f["callsign"]) else None
            ports = ((hit[0] or {}).get("airports") or []) if hit else []
            f["from"], f["to"] = (_place(ports[0]), _place(ports[-1])) if len(ports) >= 2 else (None, None)
            f["airline"] = (airline(f["callsign"]) or {}).get("name")
        return {"flights": found[:300], "days": days, "icao": icao, "callsign": callsign,
                "note": "Cut from the positions saved here (every 4 minutes while in the air and in a fetched area): a new flight starts "
                        "when the callsign changes, after 3 hours unheard, or when the plane was low before and after 20 minutes or more unheard. Planes out of the map's "
                        "view are only seen at the whole-world requests, so short flights there can be missed or joined."}

    def table(self, hours: float = 1) -> dict:
        """Every plane from the last OpenSky answer, and (when saving) every plane saved in the last
        `hours`, each at its latest position, for the planes table. Kept TABLE_KEEP seconds (the
        table, its counts and the Plane counts filters all ask, and reading a day of positions is slow)."""
        key = (hours, (self.last or {}).get("at"))
        with self._tables_lock:
            hit = self._tables.get(key)
        if hit and time.monotonic() - hit[0] < TABLE_KEEP:
            return hit[1]
        with self._table_build:  # one build at a time: the table, its counts and filters ask together
            with self._tables_lock:
                hit = self._tables.get(key)
            if hit and time.monotonic() - hit[0] < TABLE_KEEP:
                return hit[1]
            out = self._table(hours)
        with self._tables_lock:
            self._tables = {k: v for k, v in self._tables.items() if time.monotonic() - v[0] < TABLE_KEEP}
            self._tables[key] = (time.monotonic(), out)
        return out

    def _table(self, hours: float) -> dict:
        feats = {f["properties"]["id"]: f for f in (self.last or {}).get("features") or []}
        if self.collecting() and hours > 0:
            try:
                for v in self.store.at(time.time(), [(-180, -90, 180, 90)], back=hours * 3600):
                    if v["id"] not in feats:
                        feats[v["id"]] = {"geometry": {"coordinates": [v["lon"], v["lat"]]},
                                          "properties": {k: x for k, x in v.items() if k not in ("lat", "lon")}}
            except Exception as exc:  # noqa: BLE001 - the last answer still shows
                log.warning("plane store: table: %s", exc)
        self._fill_routes(list(feats.values()))
        rows = []
        for f in feats.values():
            p = dict(f["properties"])
            p["lon"], p["lat"] = f["geometry"]["coordinates"]
            p["category_name"] = PLANE_CATEGORY.get(p.get("category")) if p.get("category") is not None else None
            if "airline_code" not in p:
                self.describe(p)
            al = airline(p.get("callsign"))
            p["airline"], p["airline_code"], p["airline_country"] = (al["name"], al["code"], al["country"]) if al else (None, None, None)
            p["from"] = p["to"] = None
            if al:
                from worldmodel_api.journeys import ROUTE_HISTORY, _key

                hit = self.store.lookup("route", _key(p["callsign"]), ROUTE_HISTORY)
                ports = ((hit[0] or {}).get("airports") or []) if hit else []
                if len(ports) >= 2:
                    p["from"], p["to"] = _place(ports[0]), _place(ports[-1])
                    p["route_plausible"] = hit[0].get("plausible", True)
            rows.append(p)
        return {"planes": rows, "at": (self.last or {}).get("at"), "source": "OpenSky Network", "route_note": self.route_note,
                "note": "The planes in the map's area from the last request (the map asks every one to three minutes while Planes now is on)"
                        + (f", and every plane saved in the last {hours:g} hour{'s' if hours != 1 else ''}." if self.collecting() and hours > 0 else ".")}

    @staticmethod
    def _filter(found: dict, bx: list) -> dict:
        feats = [f for f in found["features"] if inside(*f["geometry"]["coordinates"], bx)]
        return {**found, "features": feats, "count": len(feats), "source": "OpenSky Network"}

    def _fill_routes(self, feats: list) -> None:
        """Ask adsbdb, in the background and a few at a time, the routes of airline flights in the
        table not yet known; each answer is kept (3 days), so a callsign is asked only once."""
        if (self.route_thread and self.route_thread.is_alive()) or time.time() < self.route_pause:
            return
        from worldmodel_api.journeys import ROUTE_HISTORY, ROUTE_KEEP, ROUTE_MISS, _key

        def known(cs):
            hit = self.store.lookup("route", cs, ROUTE_KEEP)
            return hit is not None and (hit[0] is not None or time.time() - hit[1] < ROUTE_MISS)

        want = []
        for f in feats:
            p = f["properties"]
            cs = _key(p.get("callsign") or "")
            if cs and airline(cs) and not known(cs) and time.time() - self.route_failed.get(cs, 0) > 3600:
                lon, lat = f["geometry"]["coordinates"]
                want.append((cs, lat, lon))
        if not want:
            return

        def run(todo):
            from worldmodel_api import journeys

            asked = found = 0
            for k in range(0, len(todo), ROUTES_PER_ROUND):  # a part at a time, each shown in the table as it comes
                batch = todo[k:k + ROUTES_PER_ROUND]
                try:
                    got = journeys.routes(batch)
                except Exception as exc:  # noqa: BLE001 - tried again later
                    log.warning("adsbdb routes: %s", exc)
                    self.route_note = f"Routes: adsbdb did not answer at {time.strftime('%H:%M')} ({exc.__class__.__name__}: {str(exc)[:160]}); trying again in 10 minutes."
                    self.route_pause = time.time() + 600
                    return
                self.store.keep_many("route", {cs: got[cs] for cs, _, _ in batch if cs in got}, ROUTE_HISTORY)
                with self._tables_lock:  # the tables kept show the new routes at their next ask
                    self._tables = {}
                asked += len(got)
                found += sum(1 for cs, _, _ in batch if got.get(cs))
                left = len(todo) - k - len(got)
                self.route_note = (f"Routes: asked adsbdb for {asked:,} flights by {time.strftime('%H:%M')}, {found:,} found"
                                   + (f"; {left:,} still to ask." if left > 0 else "."))
                for cs, _, _ in batch:
                    if cs in got and got[cs] is None:
                        self.route_failed[cs] = time.time()
                if len(got) < len(batch):  # adsbdb asked us to slow down: the rest next time
                    return

        self.route_thread = threading.Thread(target=run, args=(want[:ROUTES_PER_RUN],), daemon=True, name="plane-routes")
        self.route_thread.start()


def _km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, h)))


def _typed_from(dest) -> str | None:
    """The FROM of a destination typed as FROM>TO (some crews do), else None."""
    text = str(dest or "")
    return text.split(">")[0].strip() or None if ">" in text else None


def _place(a: dict) -> dict:
    return {"name": a.get("name"), "iata": a.get("iata"), "icao": a.get("icao"), "city": a.get("city"), "country": a.get("country")}


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
RETRY_MOST = 10 * 60   # ... doubling after each failure in a row, up to this
WORLD_RETRY = 15 * 60  # a whole-world snapshot cut short is tried again this much later
PING_TIMEOUT = 90      # seconds to wait for aisstream's answer to a keepalive ping
MAX_QUEUE = 20_000     # reports held while this side catches up (see _listen)
STALE = 300            # seconds without a report before the connection is opened again
OPEN_TIMEOUT = 60      # aisstream can take 20 s or more to answer a new connection
TIDY_EVERY = 3600.0    # seconds between turning finished days into Parquet and deleting old ones
WORLD_LISTEN = 10 * 60  # how long each whole-world snapshot listens
WORLD_FIRST_AFTER = 30 * 60  # the first whole-world snapshot this long after the app starts
DETAILS_EVERY = 300.0   # seconds between saves of the ships' details file
SHIP_MESSAGES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"]
# Where Ships are collected in the background (Settings > Transport). aisstream boxes are
# [[lat, lon], [lat, lon]]; these are (west, south, east, north) like boxes().
SHIP_AREAS = {
    "pacific": ("New Zealand, Australia and the South Pacific", [(110.0, -50.0, 180.0, 5.0), (-180.0, -50.0, -140.0, 5.0)]),
    "world": ("the whole world", [(-180.0, -90.0, 180.0, 90.0)]),
}


_SETTINGS_CACHE: list = [0.0, {}]
SETTINGS_TTL = 5.0  # seconds: describe() asks once per plane, thousands of times a request


def _settings() -> dict:
    """Settings, read from disk at most every SETTINGS_TTL seconds (a change in Settings shows within that)."""
    from worldmodel_contract import local

    now = time.monotonic()
    if now - _SETTINGS_CACHE[0] < SETTINGS_TTL:
        return _SETTINGS_CACHE[1]
    try:
        got = local.load_settings()
    except Exception:  # noqa: BLE001 - defaults if the file can't be read
        got = {}
    _SETTINGS_CACHE[:] = [now, got]
    return got


def forget_settings() -> None:
    """Read the settings afresh next time (after Settings are saved)."""
    _SETTINGS_CACHE[0] = 0.0


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
        self.fails = 0               # failures in a row since aisstream last sent anything
        self.conn_at = 0.0           # when the current connection opened, and reports on it so far
        self.conn_got = 0
        self.sweep_got = 0           # reports and new ships in the current whole-world snapshot
        self.sweep_new = 0
        self.sweep_at = 0.0
        self.messages = 0          # messages read since the listener last started
        self.connected = False
        self.resubscribe = threading.Event()
        self._store = store
        self._settings_fn = settings
        self._settings: tuple[float, dict] = (0.0, {})
        self.tidied = 0.0
        self.details_saved = time.time()
        self.world_at = 0.0          # when the last whole-world snapshot started (0: not yet planned)
        self.world_until = 0.0       # while before this, the one connection listens to the whole world
        self.ports_fn = None         # () -> the port index (journeys.ports), set by the API at start
        self._port_grid: tuple[float, dict] | None = None
        self.world_note: str | None = None
        self._schedules = None

    @property
    def schedules(self):
        """Cargo ships' ETA history, port calls and bookings (schedules.py)."""
        if self._schedules is None:
            from worldmodel_api.schedules import Schedules

            self._schedules = Schedules(self.store.folder)
        return self._schedules

    def schedules_on(self) -> bool:
        return self.collecting() and bool(self.settings().get("ship_schedules", True))

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
            # aisstream.io drops a key's connections when a second one opens, so the whole-world
            # snapshot uses the same connection: it widens to the world for ten minutes, then back.
            return SHIP_AREAS["world"][1] if time.time() < self.world_until else self.area()[1]
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
        self.schedules.start(self.settings, self.followed_cargo)

    def followed_cargo(self, days: float = 2) -> list[dict]:
        """Cargo ships with an IMO number heard in the last `days`, newest first (whose lines' schedules are asked)."""
        from worldmodel_api.schedules import is_cargo

        cut = time.time() - days * 86400
        got = [{"id": m, "imo": d.get("imo"), "name": d.get("name"), "seen": d.get("last_seen") or 0}
               for m, d in list(self.store.details.items()) if is_cargo(d.get("kind")) and d.get("imo") and (d.get("last_seen") or 0) >= cut]
        return sorted(got, key=lambda r: -r["seen"])

    def _keep(self) -> None:
        while True:
            try:
                if self.collecting():
                    self.ensure()
                every = self.world_every()
                if every and not self.world_at:  # the first snapshot half an hour after the app starts
                    self.world_at = time.time() - max(0.0, every - WORLD_FIRST_AFTER)
                if every and time.time() - self.world_at >= every and self.connected:
                    self.world_at, self.world_until = time.time(), time.time() + WORLD_LISTEN
                    self.sweep_at, self.sweep_got, self.sweep_new = time.time(), 0, 0
                    self.resubscribe.set()
                self.store.flush()  # positions waiting in memory, when reports are few
                if time.time() - self.details_saved >= DETAILS_EVERY:
                    self.details_saved = time.time()
                    self.store.save_details(int(self.settings().get("ships_keep_days") or 30))
                    if self._schedules is not None:
                        self._schedules.save(int(self.settings().get("schedules_keep_days") or 90))
                if time.time() - self.tidied >= TIDY_EVERY:
                    self.tidied = time.time()
                    self.store.tidy(int(self.settings().get("ships_keep_days") or 30))
            except Exception as exc:  # noqa: BLE001 - keep going
                log.warning("ship collector: %s", exc)
            time.sleep(RETRY_AFTER)

    def retry_wait(self) -> float:
        """Seconds to wait after the last failure: 30 s, doubling for each failure in a row, at most 10 minutes."""
        return min(RETRY_MOST, RETRY_AFTER * 2 ** max(0, self.fails - 1))

    def ensure(self) -> None:
        """(Re)start the listener, but keep the reason it last stopped on show and wait a little before
        trying again, so a bad key or a blocked connection is seen rather than retried on every request."""
        key = self.key()
        if not key:
            return
        with self.lock:
            if (not self.thread or not self.thread.is_alive()) and time.time() - self.failed_at >= self.retry_wait():
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
            feats = [_ship_feature(v, self.store.details) for v in self.ships.values() if "lat" in v and inside(v["lon"], v["lat"], bx)][:MAX_SHIPS]
            live_ids = set(self.ships)
        quiet = self.quiet_ships(bx, live_ids, now)
        feats += quiet[:max(0, MAX_SHIPS - len(feats))]
        with self.lock:
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
        if quiet:
            note = f"{note} Also {len(quiet):,} ships not heard lately, drawn faded (Settings > Transport)."
        out = {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "aisstream.io", "note": note,
               "collecting": collecting, "quiet": len(quiet)}
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
        feats = [_ship_feature(v, self.store.details) for v in found][:MAX_SHIPS]
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

    def quiet_ships(self, bx: list, live_ids: set, now: float) -> list[dict]:
        """Ships not heard for a while (up to ships_quiet_days, 0: none), drawn faded: moved on along
        the way by sea to the port they named, at their last speed, when that port and way are known;
        else at the last spot heard. Properties quiet (hours since heard) and estimated."""
        days = float(self.settings().get("ships_quiet_days", 3) or 0)
        if days <= 0:
            return []
        index = {}
        if self.ports_fn is not None:
            try:
                index = self.ports_fn()
            except Exception:  # noqa: BLE001 - no ports loaded yet: last spots only
                index = {}
        from worldmodel_api.journeys import match_port
        from worldmodel_api.seapath import sea_path_soon

        cut = now - days * 86400
        with self.lock:
            olds = [(m, d) for m, d in self.store.details.items()
                    if m not in live_ids and d.get("lat") is not None and cut <= (d.get("last_seen") or 0) <= now - SHIP_KEEP]
        out = []
        for mmsi, d in olds:
            lon, lat, est, there = d["lon"], d["lat"], False, False
            sog, hours = d.get("speed_kn"), (now - d["last_seen"]) / 3600
            port = match_port(d.get("destination"), index) if index and d.get("destination") else None
            if port and port.get("lon") is not None and isinstance(sog, (int, float)) and sog >= 2:
                sea = sea_path_soon(lon, lat, port["lon"], port["lat"])
                if sea and len(sea["coords"]) >= 2:
                    lon, lat, there = along(sea["coords"], sog * hours)
                    est = True
            if not inside(lon, lat, bx):
                continue
            f = _ship_feature({"id": mmsi, "lat": round(lat, 4), "lon": round(lon, 4), "name": d.get("name"), "imo": d.get("imo"),
                               "kind": d.get("kind"), "seen": d["last_seen"], "length_m": d.get("length_m"),
                               "speed_kn": sog, "heading": d.get("heading")})
            f["properties"].update(quiet=round(hours, 1), estimated=est, at_port=there)
            out.append(f)
        return out

    def port_near(self, lon: float, lat: float, within_km: float = 15) -> dict | None:
        """The World Port Index port nearest a stopped ship, if one is within_km (ports_fn is set by
        the API at start; ports are kept in 1-degree cells so this is quick)."""
        if self.ports_fn is None:
            return None
        if self._port_grid is None or time.time() - self._port_grid[0] > 3600:
            grid: dict[tuple[int, int], list[dict]] = {}
            try:
                index = self.ports_fn()
            except Exception as exc:  # noqa: BLE001 - no ports loaded yet
                log.info("ports for ships: %s", exc)
                index = {}
            seen = set()
            for pt in list((index.get("code") or {}).values()) + list((index.get("name") or {}).values()):
                if id(pt) in seen or pt.get("lat") is None:
                    continue
                seen.add(id(pt))
                grid.setdefault((math.floor(pt["lat"]), math.floor(pt["lon"])), []).append(pt)
            self._port_grid = (time.time(), grid)
        grid = self._port_grid[1]
        best, best_d = None, within_km
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for pt in grid.get((math.floor(lat) + dy, (math.floor(lon) + dx + 180) % 360 - 180), []):
                    d = _km(lon, lat, pt["lon"], pt["lat"])
                    if d < best_d:
                        best, best_d = pt, d
        return {k: best.get(k) for k in ("name", "country", "locode")} if best else None

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
                "first_seen": d.get("first_seen"), "last_seen": last,
                "last_port": d.get("last_port"), "last_port_at": d.get("last_port_at"),
                "from_typed": _typed_from(d.get("destination"))}

    def table(self, q: str = "", group: str = "", flag_code: str = "", sort: str = "last_seen", limit: int = 200,
              offset: int = 0, hours: float = 0, to: str = "", ports: dict | None = None, came: str = "",
              schedule_fn=None, ontime: str = "", from_country: str = "", to_country: str = "", box: str = "") -> dict:
        """Every ship seen (saved details while collecting, else those in memory), filtered and sorted.
        With a port index each row gets the port its destination names; `to` keeps ships whose
        destination, port or port country contains it."""
        with self.lock:
            ids = set(self.store.details) | set(self.ships)
            rows = [self._row(m, self.store.details.get(m, {})) for m in ids]
        if box:  # only ships inside the map view ("west,south,east,north")
            from worldmodel_api.livestats import in_box, parse_box

            b = parse_box(box)
            rows = [r for r in rows if in_box(r.get("lon"), r.get("lat"), b)]
        if ports is not None:
            from worldmodel_api.journeys import match_port

            for r in rows:
                pt = match_port(r.get("destination"), ports)
                r["to_port"] = {k: pt.get(k) for k in ("name", "country", "locode")} if pt else None
                pf = match_port(r.get("from_typed"), ports) if r.get("from_typed") and not r.get("last_port") else None
                r["from_port"] = {k: pf.get(k) for k in ("name", "country", "locode")} if pf else None
        # the countries ships came from and are going to, for the filters' lists (counted before those filters)
        def came_country(r):
            return (r.get("last_port") or {}).get("country") or (r.get("from_port") or {}).get("country")

        def to_country_of(r):
            return (r.get("to_port") or {}).get("country")

        from_counts: dict[str, int] = {}
        to_counts: dict[str, int] = {}
        for r in rows:
            if came_country(r):
                from_counts[came_country(r)] = from_counts.get(came_country(r), 0) + 1
            if to_country_of(r):
                to_counts[to_country_of(r)] = to_counts.get(to_country_of(r), 0) + 1
        if from_country:
            rows = [r for r in rows if (came_country(r) or "").lower() == from_country.lower()]
        if to_country:
            rows = [r for r in rows if (to_country_of(r) or "").lower() == to_country.lower()]
        if came:
            cl = came.lower()
            rows = [r for r in rows if cl in " ".join(str(x or "") for x in (
                r.get("from_typed"), *((r.get("last_port") or {}).values()), *((r.get("from_port") or {}).values()))).lower()]
        if to:
            tl = to.lower()
            rows = [r for r in rows if tl in " ".join(str(x or "") for x in (
                r.get("destination"), *((r.get("to_port") or {}).values()))).lower()]
        if hours:
            cut = time.time() - hours * 3600
            rows = [r for r in rows if (r["last_seen"] or 0) >= cut]
        if schedule_fn is not None:  # cargo ships: on time, slipping, late (schedules.py)
            for r in rows:
                if r["group"] == "cargo":
                    st = schedule_fn(r["id"]) or {}
                    r["on_time"], r["late_h"] = st.get("state"), st.get("late_h")
                    r["eta_moved_h"], r["estimate_at"] = st.get("moved_h"), (st.get("estimate") or {}).get("at")
        if ontime:
            rows = [r for r in rows if r.get("on_time") == ontime or (ontime == "any" and r.get("on_time") not in (None, "none"))]
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
        return {"rows": rows[offset:offset + limit], "total": len(rows), "groups": groups, "collecting": self.collecting(),
                "countries": {"from": sorted(from_counts.items(), key=lambda kv: (-kv[1], kv[0])),
                              "to": sorted(to_counts.items(), key=lambda kv: (-kv[1], kv[0]))}}

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
    # ------------------------------------------------------------------ the connection
    def _run(self, key: str) -> None:
        try:
            asyncio.run(self._listen(key))
        except Exception as exc:  # noqa: BLE001 - shown on the map, not raised
            self.fails += 1
            refused = self.error if (self.error or "").startswith("aisstream.io refused") else None
            why = refused or _ship_error(exc, self.retry_wait())
            was_world = time.time() < self.world_until
            if was_world:  # the snapshot failed: back to the area, try again in 15 minutes
                self.world_until = 0.0
                every = self.world_every()
                if every:
                    self.world_at = time.time() - max(0.0, every - WORLD_RETRY)
                self.world_note = f"Whole-world snapshot cut short ({why.split(';')[0]}); trying again in {WORLD_RETRY // 60} minutes."
            if was_world:
                self.log_sweep("sweep", self.sweep_at, "cut short", self.sweep_got, self.sweep_new, why.split(";")[0])
            if self.conn_at:
                self.log_sweep("connection", self.conn_at, "dropped", self.conn_got, None, why.split(";")[0])
                self.conn_at = 0.0
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
            world, got = bx == SHIP_AREAS["world"][1] and self.area()[1] != bx, 0
            # The whole world sends hundreds of reports a second: a short queue (the default 16) stops the
            # reading whenever this loop falls behind, so the server's pong waits behind unread reports and the
            # keepalive gives up ("1011 keepalive ping timeout", every minute or two). A long queue and a
            # longer pong wait ride out the bursts; a connection silent for STALE seconds is opened again.
            async with websockets.connect(AISSTREAM, open_timeout=OPEN_TIMEOUT, ping_interval=30, ping_timeout=PING_TIMEOUT,
                                          max_size=2**22, max_queue=MAX_QUEUE) as ws:
                await ws.send(json.dumps({"APIKey": key,
                                          "BoundingBoxes": [[[s, w], [n, e]] for w, s, e, n in bx],
                                          "FilterMessageTypes": SHIP_MESSAGES}))
                self.connected = True
                if not self.conn_at:
                    self.conn_at, self.conn_got = time.time(), 0
                checked = heard = time.time()
                while not self.resubscribe.is_set():
                    if time.time() - checked > 30:  # settings changed (area, collecting on or off)?
                        checked = time.time()
                        if not self.wanted() or self.wanted_boxes() != bx:
                            break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        if time.time() - heard > STALE:
                            raise ConnectionError(f"no reports for {STALE // 60} minutes") from None
                        continue
                    heard = time.time()
                    got += 1
                    self.conn_got += 1
                    if world:
                        self.sweep_got += 1
                    msg = json.loads(raw)
                    if not msg.get("error"):
                        self.fails = 0
                    self.take(msg)
            if world:
                self.world_until = 0.0
                self.world_note = (f"Last whole-world snapshot {time.strftime('%H:%M', time.localtime(self.world_at))}: "
                                   f"{got:,} reports, {self.sweep_new:,} ships not seen before.")
                self.log_sweep("sweep", self.sweep_at or self.world_at, "finished", got, self.sweep_new, "")

    # ------------------------------------------------------------------ sweep and drop log
    SWEEP_COLUMNS = ("start", "end", "what", "outcome", "minutes", "reports", "new_ships", "why")

    def log_sweep(self, what: str, start: float, outcome: str, reports: int, new: int | None, why: str) -> None:
        """One line in <home>/live/ships/sweeps.csv for each whole-world snapshot and each dropped
        connection, so how often aisstream cuts off, and how much each sweep brings, can be seen."""
        end = time.time()
        try:
            f = self.store.folder / "sweeps.csv"
            f.parent.mkdir(parents=True, exist_ok=True)
            new_file = not f.exists()
            with f.open("a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if new_file:
                    w.writerow(self.SWEEP_COLUMNS)
                w.writerow([int(start), int(end), what, outcome, round((end - start) / 60, 1), reports, "" if new is None else new, why])
        except OSError as exc:
            log.warning("ship sweep log: %s", exc)

    def sweeps(self, days: float = 7) -> dict:
        """The sweep and drop log for the last `days`, newest first, with totals."""
        rows = []
        try:
            with (self.store.folder / "sweeps.csv").open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        if time.time() - int(r["start"]) <= days * 86400:
                            rows.append({"start": int(r["start"]), "end": int(r["end"]), "what": r["what"], "outcome": r["outcome"],
                                         "minutes": float(r["minutes"] or 0), "reports": int(r["reports"] or 0),
                                         "new_ships": int(r["new_ships"]) if r.get("new_ships") else None, "why": r.get("why") or None})
                    except (KeyError, ValueError):
                        continue
        except OSError:
            pass
        rows.reverse()
        sw = [r for r in rows if r["what"] == "sweep"]
        return {"rows": rows[:200], "days": days, "totals": {
            "sweeps": len(sw), "finished": sum(r["outcome"] == "finished" for r in sw), "cut_short": sum(r["outcome"] != "finished" for r in sw),
            "reports": sum(r["reports"] for r in sw), "new_ships": sum(r["new_ships"] or 0 for r in sw),
            "drops": sum(r["what"] == "connection" for r in rows)}}

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
            if mmsi not in self.ships and time.time() < self.world_until:
                self.sweep_new += 1
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
                if static.get("length_m"):
                    s["length_m"] = static["length_m"]
                saving = True
            else:
                saving = False
        if saving:
            if self.collecting():
                self.store.note(mmsi, **static)
                if self.schedules_on() and _cargo(static.get("kind") or s.get("kind")) and ("eta" in static or "destination" in static):
                    self.schedules.note_eta(mmsi, static.get("destination"), static.get("eta"))
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
                saved = self.store.add(mmsi, ship["lat"], ship["lon"], ship.get("speed_kn"), ship.get("heading"), ship.get("name"),
                                       kind=ship.get("kind"))
                sog = ship.get("speed_kn")
                cargo = self.schedules_on() and _cargo(ship.get("kind"))
                if saved and isinstance(sog, (int, float)) and sog < 0.5:  # stopped: in which port?
                    port = self.port_near(ship["lon"], ship["lat"])
                    if port:
                        self.store.note(mmsi, last_port=port, last_port_at=int(time.time()))
                        if cargo:
                            self.schedules.note_stop(mmsi, port)
                elif cargo and isinstance(sog, (int, float)) and sog >= 3:
                    self.schedules.note_move(mmsi)
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


def _cargo(kind) -> bool:
    return isinstance(kind, int) and 70 <= kind <= 79


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


def _ship_feature(v: dict, details: dict | None = None) -> dict:
    props = {k: v[k] for k in ("id", "name", "imo", "speed_kn", "heading", "seen", "kind", "length_m") if v.get(k) is not None}
    if "length_m" not in props and details is not None:  # its length from what it said before (saved details)
        length = (details.get(v.get("id")) or {}).get("length_m")
        if isinstance(length, (int, float)) and length > 0:
            props["length_m"] = length
    props["group"] = ship_group(v.get("kind"))
    if not isinstance(props.get("heading"), (int, float)) or not 0 <= props["heading"] < 360:
        props["heading"] = 0
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]}, "properties": props}


def _wait_words(seconds: float) -> str:
    return f"{int(seconds)} s" if seconds < 90 else f"{round(seconds / 60)} minutes"


def _ship_error(exc: Exception, wait: float = RETRY_AFTER) -> str:
    """Why the aisstream listener stopped, in words."""
    name = exc.__class__.__name__
    text = str(exc)
    if "ConnectionClosed" in name and "keepalive" in text:
        return f"aisstream.io connection timed out ({text}); trying again in {_wait_words(wait)}."
    if "ConnectionClosed" in name:
        return f"aisstream.io closed the connection ({text or name}); trying again in {_wait_words(wait)}. A wrong or expired key is the usual cause."
    if "InvalidStatus" in name or "InvalidHandshake" in name or "Proxy" in name:
        return f"aisstream.io would not connect ({text or name}); trying again in {_wait_words(wait)}."
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, OSError)):
        return f"Could not reach aisstream.io ({name}: {text}); trying again in {_wait_words(wait)}."
    return f"aisstream.io: {text or name}; trying again in {_wait_words(wait)}."


PLANES = Planes()
MIL_PLANES = MilitaryPlanes()
SHIPS = Ships()
