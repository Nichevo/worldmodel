"""Trains now: where each train is and how late it runs, from the operators' live feeds (GTFS
Realtime), with each train's positions saved for its path and lateness by line.

Feeds (congestion.yaml train_feeds), each with its own free key in .env:
- Auckland Transport (AT_API_KEY), Metlink in Wellington (METLINK_API_KEY): JSON feeds of every
  bus, train and ferry; trains are picked out by the route type in the timetable (read weekly).
- Transport for NSW, Sydney Trains (TFNSW_API_KEY): protocol buffer feeds of trains only.

While "Trains now" is on and a key is set, each feed is read every 30 seconds. With "Save
train positions" on, each train's position is added to a file a day under
<data folder>/congestion/trains (kept trains_keep_days), and lateness is added up by line and
by hour of the day for the Congestion tab.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import math
import os
import struct
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from worldmodel_contract import catalogue, local

log = logging.getLogger(__name__)

UA = {"User-Agent": "worldmodel (personal research tool)"}
EVERY = 30.0
IDLE = 10 * 60          # without "Save train positions", feeds are read only this long after the map asked
TRAIL_KEEP = 2 * 3600   # seconds of each train's path kept in memory
STALE = 10 * 60         # a train not heard from this long is dropped from the map
TIMETABLE_EVERY = 7 * 86400
LATE_MIN = 5            # minutes late that count as late in the summaries
RAIL_TYPES = {2} | set(range(100, 118))


def root() -> Path:
    p = local.home() / "congestion" / "trains"
    p.mkdir(parents=True, exist_ok=True)
    return p


def feeds() -> list[dict]:
    return list(catalogue.congestion().get("train_feeds") or [])


# ----------------------------------------------------------------------------- GTFS Realtime, protocol buffers
def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = out = 0
    while True:
        c = b[i]
        i += 1
        out |= (c & 0x7F) << shift
        if not c & 0x80:
            return out, i
        shift += 7


def _fields(b: bytes):
    """(field number, wire type, value) for each field of one message."""
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {wt}")
        yield num, wt, v


def _signed(v: int) -> int:  # int32 written as varint
    return v - (1 << 64) if v >= 1 << 63 else v


def _trip(b: bytes) -> dict:
    out = {}
    for n, _, v in _fields(b):
        if n == 1:
            out["trip_id"] = v.decode("utf-8", "replace")
        elif n == 5:
            out["route_id"] = v.decode("utf-8", "replace")
        elif n == 2:
            out["start_time"] = v.decode("utf-8", "replace")
    return out


def _vehicle_desc(b: bytes) -> dict:
    out = {}
    for n, _, v in _fields(b):
        if n == 1:
            out["id"] = v.decode("utf-8", "replace")
        elif n == 2:
            out["label"] = v.decode("utf-8", "replace")
    return out


def _position(b: bytes) -> dict:
    out = {}
    names = {1: "latitude", 2: "longitude", 3: "bearing", 5: "speed"}
    for n, wt, v in _fields(b):
        if n in names and wt == 5:
            out[names[n]] = struct.unpack("<f", v)[0]
    return out


def _carriage(b: bytes, tfnsw: bool = False) -> dict:
    """One carriage: GTFS Realtime CarriageDetails (1 id, 2 label, 3 occupancy, 4 percentage,
    5 sequence) or TfNSW's CarriageDescriptor (1 name, 2 position, 3 occupancy, 4 quiet carriage)."""
    out: dict = {}
    for n, wt, v in _fields(b):
        if n in (1, 2) and wt == 2 and "label" not in out:
            out["label"] = v.decode("utf-8", "replace")
        elif n == 3 and wt == 0:
            out["occupancy_status"] = v
        elif tfnsw and n == 2 and wt == 0 or not tfnsw and n == 5 and wt == 0:
            out["sequence"] = v
        elif not tfnsw and n == 4 and wt == 0 and _signed(v) >= 0:
            out["occupancy_percentage"] = _signed(v)
        elif tfnsw and n == 4 and wt == 0:
            out["quiet"] = bool(v)
    return out


def _stop_event(b: bytes) -> dict:
    out = {}
    for n, wt, v in _fields(b):
        if n == 1 and wt == 0:
            out["delay"] = _signed(v)
        elif n == 2 and wt == 0:
            out["time"] = _signed(v)
    return out


def decode_feed(b: bytes) -> list[dict]:
    """A GTFS Realtime FeedMessage as entities shaped like the JSON feeds:
    {id, vehicle: {trip, position, timestamp, vehicle, stop_id}, trip_update: {trip, vehicle, delay, stop_time_update}}."""
    out = []
    for n, _, ent in _fields(b):
        if n != 2:
            continue
        e: dict = {}
        for fn, wt, v in _fields(ent):
            if fn == 1:
                e["id"] = v.decode("utf-8", "replace")
            elif fn == 4:  # VehiclePosition
                vp: dict = {}
                for k, w2, x in _fields(v):
                    if k == 1:
                        vp["trip"] = _trip(x)
                    elif k == 2:
                        vp["position"] = _position(x)
                    elif k == 5 and w2 == 0:
                        vp["timestamp"] = x
                    elif k == 7:
                        vp["stop_id"] = x.decode("utf-8", "replace")
                    elif k == 8:
                        vp["vehicle"] = _vehicle_desc(x)
                    elif k == 9 and w2 == 0:
                        vp["occupancy_status"] = x
                    elif k == 10 and w2 == 0:
                        vp["occupancy_percentage"] = x
                    elif k in (11, 1007) and w2 == 2:  # standard multi_carriage_details; TfNSW's consist extension
                        vp.setdefault("carriages", []).append(_carriage(x, tfnsw=k == 1007))
                e["vehicle"] = vp
            elif fn == 3:  # TripUpdate
                tu: dict = {"stop_time_update": []}
                for k, w2, x in _fields(v):
                    if k == 1:
                        tu["trip"] = _trip(x)
                    elif k == 3:
                        tu["vehicle"] = _vehicle_desc(x)
                    elif k == 5 and w2 == 0:
                        tu["delay"] = _signed(x)
                    elif k == 2:
                        st: dict = {}
                        for k2, _, y in _fields(x):
                            if k2 == 2:
                                st["arrival"] = _stop_event(y)
                            elif k2 == 3:
                                st["departure"] = _stop_event(y)
                            elif k2 == 4:
                                st["stop_id"] = y.decode("utf-8", "replace")
                        tu["stop_time_update"].append(st)
                e["trip_update"] = tu
        out.append(e)
    return out


# GTFS Realtime OccupancyStatus, by number and by name (JSON feeds send either).
OCCUPANCY = ["empty", "many_seats", "few_seats", "standing", "crushed", "full", "not_accepting", "no_data", "not_boardable"]
OCCUPANCY_LABEL = {"empty": "Empty", "many_seats": "Many seats free", "few_seats": "Few seats free", "standing": "Standing room only",
                   "crushed": "Crowded, little standing room", "full": "Full", "not_accepting": "Not taking passengers",
                   "not_boardable": "Not for passengers"}


_OCC_NAMES = {"empty": "empty", "many_seats_available": "many_seats", "few_seats_available": "few_seats",
              "standing_room_only": "standing", "crushed_standing_room_only": "crushed", "full": "full",
              "not_accepting_passengers": "not_accepting", "no_data_available": "no_data", "not_boardable": "not_boardable"}


def occupancy(v) -> str | None:
    """An occupancy status as one of OCCUPANCY (None when unknown)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or str(v).isdigit():
        i = int(v)
        got = OCCUPANCY[i] if 0 <= i < len(OCCUPANCY) else None
    else:
        got = _OCC_NAMES.get(str(v).lower().strip())
    return None if got == "no_data" else got


def _snake(d):
    """camelCase keys (some JSON feeds) as snake_case, all the way down."""
    if isinstance(d, list):
        return [_snake(x) for x in d]
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        key = "".join("_" + c.lower() if c.isupper() else c for c in str(k)).lstrip("_")
        out[key] = _snake(v)
    return out


def entities(body: bytes, content_type: str = "") -> list[dict]:
    """Entities from a feed answer, JSON (plain or wrapped in {"response": ...}) or protocol buffers."""
    text = body.lstrip()[:1]
    if "json" in content_type or text in (b"{", b"["):
        d = json.loads(body)
        if isinstance(d, dict):
            d = d.get("response", d)
        ents = (d.get("entity") or d.get("entities") or []) if isinstance(d, dict) else d
        return _snake(ents if isinstance(ents, list) else [])
    return decode_feed(body)


def _delay_of(tu: dict) -> int | None:
    """A trip update's delay in seconds: its own, else the first stop's arrival or departure."""
    if tu.get("delay") is not None:
        return int(tu["delay"])
    for st in tu.get("stop_time_update") or []:
        for k in ("arrival", "departure"):
            d = (st.get(k) or {}).get("delay")
            if d is not None:
                return int(d)
    return None


def trains_from(ents: list[dict], rail_routes: set[str] | None, routes: dict[str, str], now: float) -> list[dict]:
    """Each train with a position: id, label, route and line name, place, heading, speed, when, delay (s)."""
    delays: dict[str, int] = {}
    for e in ents:
        tu = e.get("trip_update")
        if not tu:
            continue
        d = _delay_of(tu)
        if d is None:
            continue
        for k in ((tu.get("trip") or {}).get("trip_id"), (tu.get("vehicle") or {}).get("id")):
            if k:
                delays[str(k)] = d
    out = []
    for e in ents:
        vp = e.get("vehicle")
        if not vp or not vp.get("position"):
            continue
        trip, veh, pos = vp.get("trip") or {}, vp.get("vehicle") or {}, vp["position"]
        route = str(trip.get("route_id") or "")
        if rail_routes is not None and route not in rail_routes:
            continue
        lat, lon = pos.get("latitude"), pos.get("longitude")
        if lat is None or lon is None or (abs(lat) < 0.01 and abs(lon) < 0.01):
            continue
        vid = str(veh.get("id") or e.get("id") or "")
        ts = vp.get("timestamp")
        try:
            ts = float(ts) if ts else now
        except (TypeError, ValueError):
            ts = now
        delay = delays.get(str(trip.get("trip_id") or "")) if trip.get("trip_id") else None
        if delay is None:
            delay = delays.get(vid)
        out.append({"id": vid, "label": veh.get("label") or None, "route": route or None, "line": routes.get(route) or route or None,
                    "trip": trip.get("trip_id"), "lon": round(float(lon), 5), "lat": round(float(lat), 5),
                    "heading": round(float(pos["bearing"])) if pos.get("bearing") is not None else None,
                    "speed_kmh": round(float(pos["speed"]) * 3.6) if pos.get("speed") is not None else None,
                    "at": ts, "delay_s": delay, **_crowding(vp)})
    return out


def _crowding(vp: dict) -> dict:
    """How full the train is, and each carriage in order where the feed lists them."""
    out: dict = {}
    occ = occupancy(vp.get("occupancy_status"))
    if occ:
        out["occupancy"] = occ
    if vp.get("occupancy_percentage") is not None:
        try:
            out["occupancy_pct"] = int(vp["occupancy_percentage"])
        except (TypeError, ValueError):
            pass
    cars = []
    for i, c in enumerate(sorted(vp.get("carriages") or vp.get("multi_carriage_details") or [],
                                 key=lambda c: (c.get("sequence") or c.get("carriage_sequence") or 0))):
        cars.append({"n": i + 1, "label": c.get("label") or c.get("id") or None, "occupancy": occupancy(c.get("occupancy_status")),
                     **({"quiet": True} if c.get("quiet") else {})})
    if cars:
        out["carriages"] = cars
        if "occupancy" not in out:  # the fullest carriage, when only carriages are given
            known = [OCCUPANCY.index(c["occupancy"]) for c in cars if c["occupancy"] in OCCUPANCY[:6]]
            if known:
                out["occupancy"] = OCCUPANCY[max(known)]
    return out


def _bearing(path: list) -> float | None:
    """The way a train is going, from the last two places in its path at least 20 m apart."""
    if len(path) < 2:
        return None
    _, lon2, lat2 = path[-1][:3]
    for p in reversed(path[:-1]):
        lon1, lat1 = p[1], p[2]
        dy = (lat2 - lat1) * 111_320
        dx = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat2))
        if dx * dx + dy * dy >= 400:
            return round(math.degrees(math.atan2(dx, dy)) % 360)
    return None


def rail_routes_from_zip(data: bytes) -> dict[str, str]:
    """{route_id: line name} for the rail routes in a GTFS timetable zip."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("routes.txt")), None)
        if not name:
            return out
        with z.open(name) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
                try:
                    kind = int(r.get("route_type") or -1)
                except ValueError:
                    continue
                if kind in RAIL_TYPES:
                    out[r["route_id"]] = (r.get("route_long_name") or r.get("route_short_name") or r["route_id"]).strip()
    return out


# ----------------------------------------------------------------------------- the reader
class Trains:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now: dict[str, dict[str, dict]] = {}      # feed -> train id -> latest
        self.trails: dict[str, list] = {}              # "feed:id" -> [[t, lon, lat], ...]
        self.errors: dict[str, str] = {}
        self.read_at: dict[str, float] = {}
        self.asked = 0.0
        self.thread: threading.Thread | None = None
        self.routes: dict[str, dict[str, str]] = {}
        self.summary: dict = {}
        self._summary_day = ""

    # -- set-up
    def _timetable(self, client: httpx.Client, f: dict, key: str) -> dict[str, str] | None:
        """The feed's rail routes, from the static timetable (kept a week); None for rail-only feeds."""
        if f.get("rail_only"):
            path = root() / f"routes_{f['id']}.json"
            if f["id"] not in self.routes:
                try:
                    self.routes[f["id"]] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    self.routes[f["id"]] = {}
            return None
        path = root() / f"routes_{f['id']}.json"
        fresh = path.exists() and time.time() - path.stat().st_mtime < TIMETABLE_EVERY
        if f["id"] not in self.routes or not fresh:
            got = None
            if not fresh and f.get("timetable"):
                try:
                    r = client.get(f["timetable"], headers=self._headers(f, key), timeout=300)
                    r.raise_for_status()
                    got = rail_routes_from_zip(r.content)
                    path.write_text(json.dumps(got), encoding="utf-8")
                except Exception as exc:  # noqa: BLE001 - last week's list, if any
                    log.info("trains %s timetable: %s", f["id"], exc)
            if got is None:
                try:
                    got = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    got = {}
            self.routes[f["id"]] = got
        return set(self.routes[f["id"]])

    @staticmethod
    def _headers(f: dict, key: str) -> dict:
        return {**UA, f.get("header") or "x-api-key": f"{f.get('header_prefix') or ''}{key}", "Accept": "application/json, application/x-protobuf"}

    def read_feed(self, client: httpx.Client, f: dict, now: float | None = None) -> list[dict]:
        now = now or time.time()
        key = os.environ.get(f["key"], "").strip()
        if not key:
            raise RuntimeError(f"No {f['key']} in .env (free from {f.get('signup')})")
        rail = self._timetable(client, f, key)
        if rail is not None and not rail:
            raise RuntimeError("the timetable's list of train routes could not be read yet")
        ents: list[dict] = []
        for url in (f["positions"], f.get("updates")):
            if not url:
                continue
            r = client.get(url, headers=self._headers(f, key), timeout=30)
            if r.status_code in (401, 403):
                raise RuntimeError(f"the key in {f['key']} was refused ({r.status_code})")
            r.raise_for_status()
            ents += entities(r.content, r.headers.get("content-type", ""))
        return trains_from(ents, rail, self.routes.get(f["id"]) or {}, now)

    # -- running
    def poll(self, client: httpx.Client, settings: dict, now: float | None = None) -> None:
        now = now or time.time()
        for f in feeds():
            if not os.environ.get(f["key"], "").strip():
                self.errors[f["id"]] = f"No {f['key']} in .env"
                continue
            try:
                got = self.read_feed(client, f, now)
            except Exception as exc:  # noqa: BLE001 - shown on the map and the Congestion tab
                self.errors[f["id"]] = str(exc)[:300]
                continue
            self.errors.pop(f["id"], None)
            self.read_at[f["id"]] = now
            with self.lock:
                cur = self.now.setdefault(f["id"], {})
                for t in got:
                    t["feed"] = f["id"]
                    cur[t["id"]] = t
                    trail = self.trails.setdefault(f"{f['id']}:{t['id']}", [])
                    if not trail or trail[-1][1:] != [t["lon"], t["lat"]]:
                        trail.append([round(t["at"]), t["lon"], t["lat"]])
                    while trail and trail[0][0] < now - TRAIL_KEEP:
                        trail.pop(0)
                for k in [k for k, v in cur.items() if v["at"] < now - STALE]:
                    del cur[k]
            if settings.get("trains_collect", True):
                self._save(f, got, now)

    def _save(self, f: dict, got: list[dict], now: float) -> None:
        tz = ZoneInfo(f.get("tz") or "UTC")
        local_now = datetime.fromtimestamp(now, tz)
        day = local_now.date().isoformat()
        path = root() / f"{f['id']}_{day}.jsonl.gz"
        with gzip.open(path, "at", encoding="utf-8") as fh:
            for t in got:
                fh.write(json.dumps([round(t["at"]), t["id"], t.get("route"), t["lon"], t["lat"], t.get("delay_s")], separators=(",", ":")) + "\n")
        # lateness by line and by hour (each reading of each train counts once)
        sp = root() / "summary.json"
        if not self.summary:
            try:
                self.summary = json.loads(sp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.summary = {}
        cell = self.summary.setdefault(f["id"], {}).setdefault(day, {"lines": {}, "hours": [[0, 0, 0] for _ in range(24)]})
        for t in got:
            d = t.get("delay_s")
            if d is None:
                continue
            ln = cell["lines"].setdefault(t.get("line") or t.get("route") or "?", [0, 0, 0])
            hr = cell["hours"][local_now.hour]
            for c in (ln, hr):
                c[0] += 1
                c[1] += max(0, d)
                c[2] += 1 if d >= LATE_MIN * 60 else 0
        if day != self._summary_day or int(now) % 300 < EVERY:
            self._summary_day = day
            sp.write_text(json.dumps(self.summary, separators=(",", ":")), encoding="utf-8")

    def tidy(self, keep_days: int, today: date | None = None) -> None:
        cut = ((today or date.today()) - timedelta(days=keep_days)).isoformat()
        for p in root().glob("*_*.jsonl.gz"):
            if p.name.split("_", 1)[1][:10] < cut:
                p.unlink(missing_ok=True)
        for days in self.summary.values():
            for d in [d for d in days if d < cut]:
                del days[d]

    def start(self, settings_fn) -> None:
        if self.thread and self.thread.is_alive():
            return

        def run():
            time.sleep(30)
            last_tidy = 0.0
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                while True:
                    s = settings_fn() or {}
                    wanted = s.get("trains_live", True) and (s.get("trains_collect", True) or time.time() - self.asked < IDLE)
                    if wanted and any(os.environ.get(f["key"]) for f in feeds()):
                        try:
                            self.poll(client, s)
                        except Exception as exc:  # noqa: BLE001
                            log.warning("trains: %s", exc)
                        if time.time() - last_tidy > 3600:
                            self.tidy(int(s.get("trains_keep_days") or 14))
                            last_tidy = time.time()
                    time.sleep(EVERY)

        self.thread = threading.Thread(target=run, daemon=True, name="trains")
        self.thread.start()

    # -- reading
    def geojson(self, west: float, south: float, east: float, north: float, on: bool = True) -> dict:
        self.asked = time.time()
        if not on:
            return {"type": "FeatureCollection", "features": [], "error": "Trains now is switched off (Settings > Transport)."}
        feats = []
        names = {f["id"]: f["name"] for f in feeds()}
        with self.lock:
            for fid, cur in self.now.items():
                for t in cur.values():
                    lon, lat = t["lon"], t["lat"]
                    if not (south <= lat <= north and (west <= lon <= east if west <= east else lon >= west or lon <= east)):
                        continue
                    d = t.get("delay_s")
                    heading = t.get("heading")
                    if heading is None:
                        heading = _bearing(self.trails.get(f"{fid}:{t['id']}") or [])
                    cars = t.get("carriages") or []
                    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                  "properties": {"id": f"{fid}:{t['id']}", "network": names.get(fid, fid), "line": t.get("line"),
                                                 "label": t.get("label"), "heading": heading, "speed_kmh": t.get("speed_kmh"),
                                                 "delay_min": round(d / 60, 1) if d is not None else None, "at": t["at"],
                                                 "occupancy": t.get("occupancy"), "cars": len(cars) or None,
                                                 # MapLibre properties are flat: the carriages as text
                                                 "carriages": json.dumps(cars) if cars else None}})
        out: dict = {"type": "FeatureCollection", "features": feats}
        missing = [f for f in feeds() if not os.environ.get(f["key"], "").strip()]
        if not feats:
            errs = "; ".join(f"{names.get(k, k)}: {v}" for k, v in self.errors.items())
            out["note"] = errs or ("Trains show a minute after the layer is turned on" if len(missing) < len(feeds())
                                   else "Trains need a free key: " + ", ".join(f"{f['key']} ({f['name']})" for f in missing))
        return out

    def trail(self, ident: str) -> dict:
        fid, _, vid = ident.partition(":")
        with self.lock:
            t = (self.now.get(fid) or {}).get(vid)
            path = list(self.trails.get(ident) or [])
        return {"id": ident, "train": t, "path": path}

    def day_path(self, ident: str, day: str) -> list[list]:
        fid, _, vid = ident.partition(":")
        p = root() / f"{fid}_{day}.jsonl.gz"
        out = []
        if not p.exists():
            return out
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r[1] == vid:
                    out.append([r[0], r[3], r[4], r[5]])
        return out

    def status(self) -> dict:
        out = []
        for f in feeds():
            with self.lock:
                n = len(self.now.get(f["id"]) or {})
            out.append({"id": f["id"], "name": f["name"], "operator": f["operator"], "key": f["key"], "signup": f.get("signup"),
                        "has_key": bool(os.environ.get(f["key"], "").strip()), "trains": n, "read_at": self.read_at.get(f["id"]),
                        "error": self.errors.get(f["id"])})
        return {"feeds": out}

    def lateness(self, days: int = 7) -> dict:
        """Each network's lines, worst first, and lateness by hour of the day, over the last days."""
        if not self.summary:
            try:
                self.summary = json.loads((root() / "summary.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.summary = {}
        out = []
        for f in feeds():
            got = self.summary.get(f["id"]) or {}
            keys = sorted(got)[-days:]
            lines: dict[str, list[int]] = {}
            hours = [[0, 0, 0] for _ in range(24)]
            daily = []
            for d in keys:
                tot = [0, 0, 0]
                for ln, c in got[d]["lines"].items():
                    acc = lines.setdefault(ln, [0, 0, 0])
                    for i in range(3):
                        acc[i] += c[i]
                        tot[i] += c[i]
                for h, c in enumerate(got[d]["hours"]):
                    for i in range(3):
                        hours[h][i] += c[i]
                daily.append({"day": d, "late_pct": round(100 * tot[2] / tot[0], 1) if tot[0] else None,
                              "avg_delay_min": round(tot[1] / tot[0] / 60, 2) if tot[0] else None})
            out.append({"id": f["id"], "name": f["name"], "operator": f["operator"], "on_time_minutes": f.get("on_time_minutes", LATE_MIN),
                        "days": keys, "daily": daily,
                        "lines": sorted(({"line": ln, "late_pct": round(100 * c[2] / c[0], 1), "avg_delay_min": round(c[1] / c[0] / 60, 2),
                                          "readings": c[0]} for ln, c in lines.items() if c[0] >= 20), key=lambda x: -x["late_pct"]),
                        "hours": [{"hour": h, "late_pct": round(100 * c[2] / c[0], 1) if c[0] else None,
                                   "avg_delay_min": round(c[1] / c[0] / 60, 2) if c[0] else None} for h, c in enumerate(hours)]})
        return {"networks": out, "late_minutes": LATE_MIN}


TRAINS = Trains()


# ----------------------------------------------------------------------------- monthly punctuality, files saved by hand
def punctuality() -> list[dict]:
    """Monthly or period on-time figures from CSV files in <data folder>/manual/rail_punctuality:
    a column naming the network or operator, one for the month (or date / period end) and one
    for the share on time (per cent). Each series keeps its file name as its source."""
    folder = local.home() / "manual" / "rail_punctuality"
    out: dict[tuple[str, str], dict] = {}
    if not folder.is_dir():
        return []
    for p in sorted(folder.glob("*.csv")):
        try:
            with p.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except OSError:
            continue
        if not rows:
            continue
        cols = {c.lower().strip(): c for c in rows[0] if c}
        net_c = next((cols[c] for c in cols if any(w in c for w in ("network", "operator", "line", "service"))), None)
        when_c = next((cols[c] for c in cols if any(w in c for w in ("month", "period", "date"))), None)
        val_c = next((cols[c] for c in cols if any(w in c for w in ("on time", "on_time", "ontime", "punctual", "ppm", "%"))), None)
        if not when_c or not val_c:
            continue
        for r in rows:
            try:
                v = float(str(r.get(val_c) or "").replace("%", "").strip())
            except ValueError:
                continue
            name = (r.get(net_c) or p.stem).strip() if net_c else p.stem
            s = out.setdefault((p.name, name), {"network": name, "source": p.name, "points": []})
            s["points"].append([str(r.get(when_c) or "").strip()[:10], v])
    for s in out.values():
        s["points"].sort()
    return list(out.values())
