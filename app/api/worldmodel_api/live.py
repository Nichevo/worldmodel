"""Planes and ships now, for the part of the map in view, asked for only while the map's
live layers are on.

- Planes: OpenSky Network's state vectors for a box (anonymous, or with an API client in
  OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET for more requests a day). One request a minute
  at most; answers are kept for 60 seconds.
- Ships: aisstream.io's websocket (AISSTREAM_API_KEY), listened to in a background thread
  for the box last asked for. Positions are kept for 20 minutes; the socket closes when no
  one has asked for five minutes.
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
PLANE_EVERY = 60.0     # seconds between OpenSky requests
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
            fresh = time.time() - self.last_at < PLANE_EVERY
            if self.last and fresh and self.last_box and all(
                    any(w0 <= w and e <= e0 and s0 <= s and n <= n0 for w0, s0, e0, n0 in self.last_box) for w, s, e, n in bx):
                return self._filter(self.last, bx)
            if fresh and self.last:  # asked again too soon for a new box: what we have, marked as such
                return {**self._filter(self.last, bx), "note": "Planes refresh once a minute; moved views fill in at the next."}
            states, error = [], None
            try:
                with httpx.Client(timeout=20) as client:
                    head = self._auth(client)
                    for w, s, e, n in bx:
                        r = client.get(OPENSKY, params={"lamin": s, "lomin": w, "lamax": n, "lomax": e}, headers=head)
                        if r.status_code == 429:
                            error = "OpenSky's daily limit is used up; planes come back tomorrow (an OpenSky API client gives more)."
                            break
                        r.raise_for_status()
                        states += r.json().get("states") or []
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                error = f"OpenSky did not answer ({exc.__class__.__name__})."
            if error and not states:
                return {"type": "FeatureCollection", "features": [], "error": error}
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


# ----------------------------------------------------------------------------- ships (aisstream.io)
class Ships:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ships: dict[int, dict] = {}
        self.box: list | None = None
        self.asked = 0.0
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.resubscribe = threading.Event()

    def get(self, west: float, south: float, east: float, north: float) -> dict:
        key = os.environ.get("AISSTREAM_API_KEY")
        bx = boxes(west, south, east, north)
        if not key:
            return {"type": "FeatureCollection", "features": [], "count": 0,
                    "error": "Ships now needs a free aisstream.io key: add AISSTREAM_API_KEY to .env (see Data status > Keys)."}
        with self.lock:
            self.asked = time.time()
            if bx != self.box:
                self.box = bx
                self.resubscribe.set()
            if not self.thread or not self.thread.is_alive():
                self.error = None
                self.thread = threading.Thread(target=self._run, args=(key,), daemon=True, name="aisstream")
                self.thread.start()
            now = time.time()
            for k in [k for k, v in self.ships.items() if now - v["seen"] > SHIP_KEEP]:
                del self.ships[k]
            feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]},
                      "properties": {k: v[k] for k in ("id", "name", "speed_kn", "heading", "seen") if v.get(k) is not None}}
                     for v in self.ships.values() if "lat" in v and inside(v["lon"], v["lat"], bx)][:MAX_SHIPS]
        out = {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "aisstream.io",
               "note": "Ships appear as they report; a new area fills in over a few minutes."}
        if self.error:
            out["error"] = self.error
        return out

    def _run(self, key: str) -> None:
        try:
            asyncio.run(self._listen(key))
        except Exception as exc:  # noqa: BLE001 - shown on the map, not raised
            self.error = f"aisstream.io: {exc}"
            log.warning("aisstream stopped: %s", exc)

    async def _listen(self, key: str) -> None:
        import websockets

        while time.time() - self.asked < SHIP_IDLE:
            with self.lock:
                bx = list(self.box or [])
            self.resubscribe.clear()
            async with websockets.connect(AISSTREAM, open_timeout=20, ping_interval=30) as ws:
                await ws.send(json.dumps({"APIKey": key,
                                          "BoundingBoxes": [[[s, w], [n, e]] for w, s, e, n in bx],
                                          "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport", "ShipStaticData"]}))
                while time.time() - self.asked < SHIP_IDLE and not self.resubscribe.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    self.take(json.loads(raw))

    def take(self, msg: dict) -> None:
        """One aisstream message into the ships kept."""
        if msg.get("error"):
            self.error = f"aisstream.io: {msg['error']}"
            return
        meta = msg.get("MetaData") or {}
        mmsi = meta.get("MMSI")
        if not mmsi:
            return
        body = (msg.get("Message") or {}).get(msg.get("MessageType") or "") or {}
        with self.lock:
            s = self.ships.setdefault(mmsi, {"id": mmsi, "seen": int(time.time())})
            name = (meta.get("ShipName") or body.get("Name") or "").strip()
            if name:
                s["name"] = name
            if msg.get("MessageType") == "ShipStaticData":
                return
            lat, lon = meta.get("latitude"), meta.get("longitude")
            if lat is None or lon is None:
                return
            s.update(lat=round(lat, 4), lon=round(lon, 4), seen=int(time.time()),
                     speed_kn=body.get("Sog"), heading=body.get("TrueHeading") if body.get("TrueHeading") not in (None, 511) else body.get("Cog"))


PLANES = Planes()
SHIPS = Ships()
