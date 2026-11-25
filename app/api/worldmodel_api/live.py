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
                        r = client.get(OPENSKY, params={"lamin": s, "lomin": w, "lamax": n, "lomax": e}, headers=head)
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
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(st[5], 4), round(st[6], 4)]},
                              "properties": {"id": st[0], "callsign": (st[1] or "").strip() or None, "country": st[2],
                                             "altitude_m": round(st[7]) if st[7] is not None else None,
                                             "speed_kmh": round(st[9] * 3.6) if st[9] is not None else None,
                                             "heading": round(st[10]) if st[10] is not None else 0}})
            self.last = {"type": "FeatureCollection", "features": feats, "at": int(time.time())}
            self.last_at, self.last_box = time.time(), bx
            return self._filter(self.last, bx)

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


class Ships:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ships: dict[int, dict] = {}
        self.box: list | None = None
        self.asked = 0.0
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.failed_at = 0.0
        self.messages = 0          # messages read since the listener last started
        self.connected = False
        self.resubscribe = threading.Event()

    def get(self, west: float, south: float, east: float, north: float) -> dict:
        key = (os.environ.get("AISSTREAM_API_KEY") or "").strip()
        bx = boxes(west, south, east, north)
        if not key:
            return {"type": "FeatureCollection", "features": [], "count": 0,
                    "error": "Ships now needs a free aisstream.io key: add AISSTREAM_API_KEY in Settings > Keys (or .env)."}
        with self.lock:
            self.asked = time.time()
            if bx != self.box:
                self.box = bx
                self.resubscribe.set()
            # (Re)start the listener, but keep the reason it last stopped on show and wait a little
            # before trying again, so a bad key or a blocked connection is seen rather than retried
            # silently on every request.
            if (not self.thread or not self.thread.is_alive()) and time.time() - self.failed_at >= RETRY_AFTER:
                self.thread = threading.Thread(target=self._run, args=(key,), daemon=True, name="aisstream")
                self.thread.start()
            now = time.time()
            for k in [k for k, v in self.ships.items() if now - v["seen"] > SHIP_KEEP]:
                del self.ships[k]
            feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]},
                      "properties": {k: v[k] for k in ("id", "name", "imo", "speed_kn", "heading", "seen") if v.get(k) is not None}}
                     for v in self.ships.values() if "lat" in v and inside(v["lon"], v["lat"], bx)][:MAX_SHIPS]
            if self.connected and self.messages:
                note = f"{self.messages:,} reports read so far; a new area fills in over a few minutes."
            elif self.connected:
                note = "Connected to aisstream.io, waiting for the first reports (a few minutes for a new area)."
            else:
                note = "Connecting to aisstream.io…"
        out = {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "aisstream.io", "note": note}
        if self.error:
            out["error"] = self.error
        return out

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
        while time.time() - self.asked < SHIP_IDLE:
            with self.lock:
                bx = list(self.box or [])
            self.resubscribe.clear()
            async with websockets.connect(AISSTREAM, open_timeout=20, ping_interval=30, max_size=2**22) as ws:
                await ws.send(json.dumps({"APIKey": key,
                                          "BoundingBoxes": [[[s, w], [n, e]] for w, s, e, n in bx],
                                          "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport", "ShipStaticData"]}))
                self.connected = True
                while time.time() - self.asked < SHIP_IDLE and not self.resubscribe.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    self.take(json.loads(raw))

    def take(self, msg: dict) -> None:
        """One aisstream message into the ships kept."""
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
            self.messages += 1
            self.error = None
            s = self.ships.setdefault(mmsi, {"id": mmsi, "seen": int(time.time())})
            name = (meta.get("ShipName") or body.get("Name") or "").strip()
            if name:
                s["name"] = name
            if msg.get("MessageType") == "ShipStaticData":
                if body.get("ImoNumber"):
                    s["imo"] = body["ImoNumber"]
                return
            lat, lon = meta.get("latitude"), meta.get("longitude")
            if lat is None or lon is None:
                return
            s.update(lat=round(lat, 4), lon=round(lon, 4), seen=int(time.time()),
                     speed_kn=body.get("Sog"), heading=body.get("TrueHeading") if body.get("TrueHeading") not in (None, 511) else body.get("Cog"))


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
