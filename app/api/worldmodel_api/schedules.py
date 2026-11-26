"""Are cargo ships on schedule? For cargo and container ships (AIS types 70-79):

- the ETA and destination each ship sends, kept every time they change (the ETA over time);
- the port calls we see (a ship stopped within 15 km of a port, then moving again), from which a
  ship's usual route (its loop of ports) is learned;
- the bookings in the ports' own arrival lists (Auckland, Tauranga, Port Botany, Sydney, Newcastle, Port Kembla and Melbourne, read hourly; Singapore
  with a free MPA key), every change kept;
- the lines' published schedules (Maersk, Hapag-Lloyd, CMA CGM: the DCSA Commercial Schedules
  standard), when a free key is set.

How late a ship is: against the line's schedule where there is one, else the port's booking, else
the ship's own first ETA for the voyage. Within a day either way is on time (the shipping
industry's measure); more than a day behind is late; an ETA or booking pushed back 12 hours or
more is slipping. Everything is kept in <home>/live/ships/schedules.json.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

NZ = ZoneInfo("Pacific/Auckland")
SYDNEY = ZoneInfo("Australia/Sydney")
MELBOURNE = ZoneInfo("Australia/Melbourne")
SINGAPORE = ZoneInfo("Asia/Singapore")
DAY = 86400.0
ON_TIME_H = 24.0      # within a day either way is on time
SLIP_H = 12.0         # an ETA or booking pushed back this much is slipping
CALL_GAP = 6 * 3600   # a stop at the same port within this of the last is the same call
SAME_CALL = 10 * DAY  # a port booking within this of the last one for the ship is the same call
FETCH_EVERY = 3600.0  # port lists and carrier schedules, at most this often
CARRIER_EVERY = 12 * 3600.0  # each ship's line schedule asked again after this
CARRIER_PER_ROUND = 30
SEA_DETOUR = 1.15     # a straight line under-counts the way round land
UA = {"User-Agent": "worldmodel (personal research tool)"}

NSW_URL = "https://www.portauthoritynsw.com.au/port-operations/{0}/{0}-daily-vessel-movements"
PORT_LISTS = {
    "auckland": {"name": "Auckland", "country": "New Zealand", "locode": "NZAKL", "lat": -36.843, "lon": 174.781,
                 "url": "https://www.poal.co.nz/operations/schedules/arrivals"},
    "tauranga": {"name": "Tauranga", "country": "New Zealand", "locode": "NZTRG", "lat": -37.646, "lon": 176.181,
                 "url": "https://www.port-tauranga.co.nz/operations/shipping-schedules/"},
    # Port Authority of NSW: one page per port, the same layout (names, no IMO numbers)
    "botany": {"name": "Port Botany", "country": "Australia", "locode": "AUBTB", "lat": -33.972, "lon": 151.221,
               "url": NSW_URL.format("port-botany")},
    "sydney": {"name": "Sydney Harbour", "country": "Australia", "locode": "AUSYD", "lat": -33.855, "lon": 151.195,
               "url": NSW_URL.format("sydney-harbour")},
    "newcastle": {"name": "Newcastle", "country": "Australia", "locode": "AUNTL", "lat": -32.917, "lon": 151.783,
                  "url": NSW_URL.format("newcastle-harbour")},
    "kembla": {"name": "Port Kembla", "country": "Australia", "locode": "AUPKL", "lat": -34.468, "lon": 150.906,
               "url": NSW_URL.format("port-kembla")},
    # Ports Victoria: Port Phillip (Melbourne and Geelong) on one page
    "melbourne": {"name": "Melbourne", "country": "Australia", "locode": "AUMEL", "lat": -37.840, "lon": 144.925,
                  "url": "https://ports.vic.gov.au/marine-operations/ship-movements/"},
    # Singapore: MPA's OCEANS-X APIs, with a free key (SG_OCEANSX_API_KEY); asked, not read as a page
    "singapore": {"name": "Singapore", "country": "Singapore", "locode": "SGSIN", "lat": 1.264, "lon": 103.840,
                  "env": "SG_OCEANSX_API_KEY", "url": None},
}

# MPA's vessel movement APIs. Each address can be changed in .env (SG_DUE_TO_ARRIVE_URL,
# SG_ARRIVALS_URL, SG_DUE_TO_DEPART_URL) to the one shown on the API's page in OCEANS-X; {date} is
# filled with yyyy-MM-dd. Four asks an hour against a quota of 10 a minute.
SG_BASE = "https://oceans-x.mpa.gov.sg/api/v1/vessel"
SG_ASKS = [("SG_DUE_TO_ARRIVE_URL", SG_BASE + "/duetoarrive/1.0.0/date/{date}", "expected", (0, 1)),
           ("SG_ARRIVALS_URL", SG_BASE + "/arrivals/1.0.0/date/{date}", "in_port", (0,)),
           ("SG_DUE_TO_DEPART_URL", SG_BASE + "/duetodepart/1.0.0/date/{date}", "leaving", (0,))]

# Which line runs a ship, by its name, for asking that line's schedule and for the reliability table.
LINES = [("MAERSK", "Maersk", "maersk"), ("SEALAND", "Maersk", "maersk"), ("CMA CGM", "CMA CGM", "cmacgm"),
         ("ANL ", "CMA CGM (ANL)", "cmacgm"), ("APL ", "CMA CGM (APL)", "cmacgm"), ("HAPAG", "Hapag-Lloyd", "hlag"),
         ("MSC ", "MSC", None), ("EVER ", "Evergreen", None), ("COSCO", "COSCO", None), ("OOCL", "OOCL", None),
         ("ONE ", "ONE", None), ("HMM ", "HMM", None), ("YM ", "Yang Ming", None), ("KOTA ", "PIL", None),
         ("SWIRE", "Swire", None), ("PACIFIC ", "Pacific Forum Line", None)]

# The lines' DCSA Commercial Schedules APIs. The address can be changed with <NAME>_SCHEDULES_URL
# in .env if a line moves it (the address shown in your developer account wins).
CARRIERS = {
    "maersk": {"name": "Maersk", "env": ["MAERSK_CONSUMER_KEY"], "url": "https://api.maersk.com/dcsa/cs/v1",
               "headers": lambda e: {"Consumer-Key": e["MAERSK_CONSUMER_KEY"]}},
    "hlag": {"name": "Hapag-Lloyd", "env": ["HLAG_CLIENT_ID", "HLAG_CLIENT_SECRET"], "url": "https://api.hlag.com/hlag/external/v1/dcsa/cs/v1",
             "headers": lambda e: {"X-IBM-Client-Id": e["HLAG_CLIENT_ID"], "X-IBM-Client-Secret": e["HLAG_CLIENT_SECRET"]}},
    "cmacgm": {"name": "CMA CGM", "env": ["CMACGM_API_KEY"], "url": "https://apis.cma-cgm.net/operation/commercialschedules/dcsa/v1",
               "headers": lambda e: {"KeyId": e["CMACGM_API_KEY"]}},
}


def is_cargo(kind) -> bool:
    return isinstance(kind, int) and 70 <= kind <= 79


def line_of(name: str | None) -> tuple[str, str | None] | None:
    """(line, carrier id or None) from a ship's name, or None when the name doesn't say."""
    n = f"{(name or '').upper().strip()} "
    for prefix, line, carrier in LINES:
        if n.startswith(prefix):
            return line, carrier
    return None


def _key(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def eta_ts(text: str | None, now: float) -> float | None:
    """The ETA a ship sends ('27/11 22:00 UTC', no year) as seconds, in the year that puts it
    nearest to now."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{2})", str(text or ""))
    if not m:
        return None
    day, month, hour, minute = (int(x) for x in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60):
        return None  # 24:60 and day 0 mean 'not given'
    year = datetime.fromtimestamp(now, timezone.utc).year
    best = None
    for y in (year - 1, year, year + 1):
        try:
            t = datetime(y, month, day, hour, minute, tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if best is None or abs(t - now) < abs(best - now):
            best = t
    return best


def _km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def sea_nm(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Rough distance by sea in nautical miles: the straight line plus 15%."""
    return _km(lon1, lat1, lon2, lat2) * SEA_DETOUR / 1.852


# ----------------------------------------------------------------------------- port lists
def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", cell))).strip()


def parse_poal(html: str) -> list[dict]:
    """Port of Auckland's expected arrivals: cells are named by their headers attribute and times
    are <time datetime="...">."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = {}
        for name, body in re.findall(r'<td[^>]*headers="view-field-([a-z0-9-]+)-table-column"[^>]*>(.*?)</td>', row, re.S):
            t = re.search(r'datetime="([^"]+)"', body)
            cells[name] = datetime.fromisoformat(t.group(1)).timestamp() if t else _text(body)
        if not cells.get("vessel"):
            continue
        out.append({"name": cells["vessel"], "imo": _imo(cells.get("lloyds-no")),
                    "voyage": cells.get("voyage-ib") or cells.get("voyage-ob") or None,
                    "arrival": _num(cells.get("arrival")), "departs": _num(cells.get("departure")),
                    "prev": cells.get("prev-port") or None, "next": cells.get("next-port") or None, "state": "expected"})
    return out


TAURANGA_TABLES = {"11": "in_port", "2": "expected", "3": "departed"}


def parse_tauranga(html: str) -> list[dict]:
    """Port of Tauranga's shipping schedules: tables 'In Port' (11), 'Expected Arrivals' (2) and
    'Departed Vessels' (3), times in New Zealand time as 27/11/2026 15:30."""
    out = []
    for tid, body in re.findall(r'<table[^>]*id=["\']pot-data-table-(\d+)["\'][^>]*>(.*?)</table>', html, re.S):
        state = TAURANGA_TABLES.get(tid)
        if not state:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            c = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(c) < 9 or not c[0]:
                continue
            out.append({"name": c[0], "imo": _imo(c[1]), "voyage": None, "arrival": _nz_time(c[2]), "departs": _nz_time(c[3]),
                        "cargo": None if c[6] in ("", "-") else c[6], "prev": c[7] or None, "next": c[8] or None, "state": state})
    return out


def _near_year(day: int, month: int, hour: int, minute: int, tz, now: float) -> float | None:
    """A local date and time given without a year, in the year that puts it nearest to now."""
    year, best = datetime.fromtimestamp(now, tz).year, None
    for y in (year - 1, year, year + 1):
        try:
            t = datetime(y, month, day, hour, minute, tzinfo=tz).timestamp()
        except ValueError:
            continue
        if best is None or abs(t - now) < abs(best - now):
            best = t
    return best


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_nsw(html: str, now: float | None = None) -> list[dict]:
    """A Port Authority of NSW 'daily vessel movements' page: one row per arrival, departure or
    shift, times in Sydney time as 'Fri 27 Nov<br>08:00' with no year. Rows of one ship are joined
    into one booking: arriving (expected), or in port with its departure time."""
    now = now or time.time()
    ships: dict[str, dict] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = {name: body for name, body in re.findall(r'<td[^>]*headers="view-([a-z-]+)-table-column"[^>]*>(.*?)</td>', row, re.S)}
        name = _text(cells.get("vessel-name", ""))
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\D+?(\d{1,2}):(\d{2})", _text(cells.get("time", "").replace("<br>", " ")))
        if not name or not m or m.group(2).lower() not in MONTHS:
            continue
        t = _near_year(int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)), int(m.group(4)), SYDNEY, now)
        kind, in_port = _text(cells.get("movement-type", "")).lower(), _text(cells.get("in-port", "")).lower() == "yes"
        s = ships.setdefault(_key(name), {"name": name, "imo": None, "voyage": None, "arrival": None, "departs": None,
                                          "cargo": None, "prev": None, "next": None, "state": "expected", "kind": None})
        s["kind"] = s["kind"] or _text(cells.get("vessel-type", "")) or None
        if kind.startswith("arr"):
            s["arrival"], s["prev"] = t, _text(cells.get("origin", "")) or None
        elif kind.startswith("dep"):
            s["departs"], s["next"] = t, _text(cells.get("destination", "")) or None
            if in_port:
                s["state"] = "in_port"
    out = []
    for s in ships.values():  # ships already in port with no arrival row left are skipped: no time to keep
        s["cargo"] = s.pop("kind")
        if s["arrival"]:
            out.append(s)
    return out


def _vic_time(text: str) -> float | None:
    for fmt in ("%b %d %Y %I:%M%p", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=MELBOURNE).timestamp()
        except ValueError:
            continue
    return None


VIC_TABLES = {"Expected Arrivals": "expected", "Actual Arrivals": "arrived", "Expected Departures": "leaving",
              "Actual Departures": "departed", "In Port": "in_port"}


def parse_vic(html: str) -> list[dict]:
    """Ports Victoria's ship movements: tables of expected and actual arrivals and departures, and
    ships in port, each under its own heading, in Melbourne time. Names carry a pilot code such as
    '(BM)', which is dropped."""
    ships: dict[str, dict] = {}
    for part in re.split(r'(?=<!-- In Port -->|<h3>)', html):
        head = re.match(r"(?:<h3>([^<]+)</h3>|<!-- (In Port) -->)", part)
        table = VIC_TABLES.get((head.group(1) or head.group(2)).strip()) if head else None
        if not table:
            continue
        body = re.search(r"<tbody>(.*?)</tbody>", part, re.S)
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S):
            c = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(c) < 5 or not c[0]:
                continue
            name = re.sub(r"\s*\([A-Z]{1,3}\)$", "", c[0])
            s = ships.setdefault(_key(name), {"name": name, "imo": None, "voyage": None, "arrival": None, "departs": None,
                                              "cargo": None, "prev": None, "next": None, "state": "expected"})
            if table == "in_port":
                s.update(arrival=_vic_time(c[2]) or s["arrival"], departs=_vic_time(c[3]) or s["departs"], next=c[4] or s["next"], state="in_port")
            elif table in ("expected", "arrived"):
                s["arrival"], s["prev"] = _vic_time(c[1]), c[2] or None
                if table == "arrived" and s["state"] == "expected":
                    s["state"] = "in_port"
            elif table in ("leaving", "departed"):
                s["departs"], s["next"] = _vic_time(c[1]), c[3] or None
                if table == "departed":
                    s["state"] = "departed"
    return [s for s in ships.values() if s["arrival"]]


def _sg_time(v) -> float | None:
    """A Singapore time: ISO text with or without a zone (none means Singapore time), or epoch ms."""
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        t = datetime.fromisoformat(v.strip().replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=SINGAPORE)).timestamp()


def _find(d: dict, *words: str):
    """The first value whose key holds all of the words, ignoring case (the APIs' field names vary:
    duetoArriveTime, dueToArriveTime, arrivedTime ...)."""
    for k, v in d.items():
        low = k.lower()
        if all(w in low for w in words) and v not in (None, ""):
            return v
    return None


def parse_sg(body, state: str) -> list[dict]:
    """One answer of MPA's due to arrive, arrivals or due to depart API: a list of records each with
    vesselParticulars (vesselName, imoNumber, callSign, flag), a time and where from or to."""
    recs = body
    if isinstance(body, dict):
        recs = next((v for v in body.values() if isinstance(v, list)), [])
    out = []
    for r in recs if isinstance(recs, list) else []:
        if not isinstance(r, dict):
            continue
        vp = r.get("vesselParticulars") or r.get("vessel") or {}
        if isinstance(vp, list):
            vp = vp[0] if vp else {}
        name = (vp.get("vesselName") or r.get("vesselName") or "").strip()
        if not name:
            continue
        t = _sg_time(_find(r, "time"))
        row = {"name": name, "imo": _imo(vp.get("imoNumber") or r.get("imoNumber")), "voyage": None, "arrival": None,
               "departs": None, "cargo": None, "prev": None, "next": None, "state": state}
        # locationTo on arrivals is a berth or anchorage in Singapore, not the next port: not kept
        place = _find(r, "last", "port") or _find(r, "location", "from")
        if state == "leaving":
            dest = _find(r, "next", "port") or _find(r, "location", "to")
            row.update(departs=t, next=dest or None, state="in_port")
        else:
            row.update(arrival=t, prev=place or None)
        out.append(row)
    return out


def merge_sg(parts: list[list[dict]]) -> list[dict]:
    """Due to arrive, arrived and due to depart joined into one booking per ship; a departure with
    no arrival in the lists is kept only when the ship's arrival is already booked (record_bookings
    then keeps the earlier arrival)."""
    ships: dict[str, dict] = {}
    for rows in parts:
        for r in rows:
            k = str(r["imo"] or _key(r["name"]))
            if k not in ships:
                ships[k] = dict(r)
                continue
            s = ships[k]
            for k in ("arrival", "departs", "prev", "next"):
                if r[k] and not (k == "arrival" and s["state"] == "in_port" and s["arrival"]):
                    s[k] = r[k]
            if r["state"] == "in_port":
                s["state"] = "in_port"
    return [s for s in ships.values() if s["arrival"]]


PARSERS = {"auckland": parse_poal, "tauranga": parse_tauranga, "botany": parse_nsw, "sydney": parse_nsw,
           "newcastle": parse_nsw, "kembla": parse_nsw, "melbourne": parse_vic}


def _imo(v) -> int | None:
    s = re.sub(r"\D", "", str(v or ""))
    return int(s) if len(s) == 7 else None


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) else None


def _nz_time(text: str) -> float | None:
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y %H:%M").replace(tzinfo=NZ).timestamp()
    except ValueError:
        return None


# ----------------------------------------------------------------------------- carrier schedules
def parse_dcsa(body) -> dict:
    """The port calls in a DCSA Commercial Schedules vessel-schedules answer: each call's port
    (UN/LOCODE and name) with planned, estimated and actual arrival and departure."""
    service, calls = None, []

    def walk(x, svc):
        nonlocal service
        if isinstance(x, list):
            for v in x:
                walk(v, svc)
        elif isinstance(x, dict):
            svc = x.get("carrierServiceName") or x.get("carrierServiceCode") or svc
            if "transportCalls" in x:
                service = service or svc
                for tc in x.get("transportCalls") or []:
                    loc = tc.get("location") or {}
                    call = {"locode": loc.get("UNLocationCode") or tc.get("UNLocationCode"),
                            "port": loc.get("locationName") or loc.get("UNLocationCode"),
                            "voyage": tc.get("carrierExportVoyageNumber") or tc.get("carrierImportVoyageNumber")}
                    for ts in tc.get("timestamps") or []:
                        kind = {"ARRI": "arr", "DEPA": "dep"}.get(ts.get("eventTypeCode"))
                        cls = {"PLN": "planned", "EST": "estimated", "ACT": "actual"}.get(ts.get("eventClassifierCode"))
                        if kind and cls and ts.get("eventDateTime"):
                            try:
                                call[f"{kind}_{cls}"] = datetime.fromisoformat(ts["eventDateTime"].replace("Z", "+00:00")).timestamp()
                            except ValueError:
                                pass
                    calls.append(call)
            else:
                for v in x.values():
                    walk(v, svc)

    walk(body, None)
    return {"service": service, "calls": calls}


# ----------------------------------------------------------------------------- the store
def _booked(call: dict) -> float:
    return call.get("arrival") or call["first"][1]


def _one_per_call(calls: list[dict]) -> list[dict]:
    """A port's bookings for one ship with copies of the same call joined (older versions could add
    a call again each hour when the ship was listed for several calls): the copy with the longest
    history is kept."""
    out: list[dict] = []
    for c in sorted(calls, key=lambda c: -len(c.get("versions") or [])):
        if not any(abs(_booked(c) - _booked(o)) <= SAME_CALL / 2 for o in out):
            out.append(c)
    return sorted(out, key=_booked)


class Schedules:
    def __init__(self, folder: Path) -> None:
        self.file = folder / "schedules.json"
        self.lock = threading.Lock()
        self.etas: dict[int, list] = {}        # mmsi -> [[seen, destination, eta], ...] (changes only)
        self.calls: dict[int, list] = {}       # mmsi -> [{port, arrived, left}, ...]
        self.bookings: dict[str, list] = {}    # "<locode>|<imo or name>" -> calls booked at that port
        self.carrier: dict[str, dict] = {}     # imo -> {at, carrier, service, calls, error}
        self.notes: dict[str, str] = {}        # source -> last result, shown in the status
        self.dirty = False
        self.thread: threading.Thread | None = None
        self._load()

    def _load(self) -> None:
        try:
            got = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.etas = {int(k): v for k, v in (got.get("etas") or {}).items()}
        self.calls = {int(k): v for k, v in (got.get("calls") or {}).items()}
        self.bookings = {k: _one_per_call(v) for k, v in (got.get("bookings") or {}).items()}
        self.carrier = got.get("carrier") or {}
        self.notes = got.get("notes") or {}

    def save(self, keep_days: int = 90, now: float | None = None) -> None:
        if not self.dirty:
            return
        now = now or time.time()
        cut = now - keep_days * DAY
        with self.lock:
            self.etas = {k: [e for e in v if e[0] >= cut] for k, v in self.etas.items()}
            self.etas = {k: v for k, v in self.etas.items() if v}
            self.calls = {k: [c for c in v if (c.get("left") or c["arrived"]) >= cut] for k, v in self.calls.items()}
            self.calls = {k: v for k, v in self.calls.items() if v}
            self.bookings = {k: [b for b in v if (b.get("arrival") or b["first"][0]) >= cut] for k, v in self.bookings.items()}
            self.bookings = {k: v for k, v in self.bookings.items() if v}
            data = json.dumps({"etas": {str(k): v for k, v in self.etas.items()}, "calls": {str(k): v for k, v in self.calls.items()},
                               "bookings": self.bookings, "carrier": self.carrier, "notes": self.notes}, separators=(",", ":"))
            self.dirty = False
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(self.file)

    # ------------------------------------------------------------------ what ships say and do
    def note_eta(self, mmsi: int, destination: str | None, eta_text: str | None, now: float | None = None) -> None:
        """Keep a ship's destination and ETA when either changes."""
        now = now or time.time()
        eta = eta_ts(eta_text, now)
        dest = (destination or "").strip() or None
        if eta is None and dest is None:
            return
        with self.lock:
            hist = self.etas.setdefault(mmsi, [])
            if hist and hist[-1][1] == dest and hist[-1][2] == eta:
                return
            hist.append([int(now), dest, int(eta) if eta else None])
            del hist[:-200]
            self.dirty = True

    def note_stop(self, mmsi: int, port: dict, now: float | None = None) -> None:
        """A ship stopped near a port: a new call, or the one it is on."""
        now = int(now or time.time())
        key = _key(port.get("locode") or port.get("name"))
        with self.lock:
            calls = self.calls.setdefault(mmsi, [])
            last = calls[-1] if calls else None
            if last and _key(last["port"].get("locode") or last["port"].get("name")) == key and \
                    (last.get("left") is None or now - last["left"] < CALL_GAP):
                last["left"], last["last"] = None, now
            else:
                calls.append({"port": {k: port.get(k) for k in ("name", "country", "locode")}, "arrived": now, "left": None, "last": now})
                del calls[:-60]
            self.dirty = True

    def note_move(self, mmsi: int, now: float | None = None) -> None:
        """A ship moving again: its open call ends (when it was last seen stopped)."""
        calls = self.calls.get(mmsi)
        if calls and calls[-1].get("left") is None:
            with self.lock:
                calls[-1]["left"] = int(now or time.time())
                self.dirty = True

    # ------------------------------------------------------------------ port lists
    def record_bookings(self, where: str, rows: list[dict], now: float | None = None) -> int:
        """Keep each booking in a port's list, and every change to its times."""
        now = int(now or time.time())
        port = PORT_LISTS[where]
        n = 0
        with self.lock:
            for r in rows:
                if not r.get("arrival"):
                    continue
                key = f"{port['locode']}|{r.get('imo') or _key(r['name'])}"
                calls = self.bookings.setdefault(key, [])
                # a liner can be listed for several calls weeks apart: match the nearest, not only the last
                last = min((c for c in calls if abs(r["arrival"] - _booked(c)) <= SAME_CALL),
                           key=lambda c: abs(r["arrival"] - _booked(c)), default=None)
                if not last:
                    last = {"port": port["name"], "locode": port["locode"], "name": r["name"], "imo": r.get("imo"),
                            "first": [now, int(r["arrival"])], "versions": [], "arrival": None, "departs": None}
                    calls.append(last)
                    calls.sort(key=_booked)
                    del calls[:-20]
                for k in ("voyage", "prev", "next", "cargo"):
                    if r.get(k):
                        last[k] = r[k]
                arr, dep = int(r["arrival"]), int(r["departs"]) if r.get("departs") else None
                if r["state"] in ("in_port", "departed"):  # the port's own times are actual
                    last["arrived_at"] = arr
                    if r["state"] == "departed" and dep:
                        last["departed_at"] = dep
                if last["arrival"] != arr or last["departs"] != dep:
                    if r["state"] == "expected" or not last["versions"]:
                        last["versions"].append([now, arr, dep])
                        del last["versions"][:-50]
                    if r["state"] == "expected":
                        last["arrival"], last["departs"] = arr, dep
                    elif last["arrival"] is None:
                        last["arrival"], last["departs"] = arr, dep
                last["state"], last["seen"] = r["state"], now
                n += 1
            self.dirty = True
        return n

    def fetch_ports(self, client: httpx.Client) -> None:
        for where, port in PORT_LISTS.items():
            if port.get("env") and not os.environ.get(port["env"]):
                self.notes[where] = f"{port['name']}: needs a free key ({port['env']} in Settings > Keys)."
                continue
            try:
                if where == "singapore":
                    rows = self.ask_singapore(client)
                else:
                    r = client.get(port["url"])
                    r.raise_for_status()
                    rows = PARSERS[where](r.text)
                n = self.record_bookings(where, rows)
                self.notes[where] = f"{port['name']}: {n} ships in the list at {time.strftime('%H:%M')}."
                if not rows:
                    self.notes[where] = f"{port['name']}: the list came back empty at {time.strftime('%H:%M')} (has the page changed?)."
            except (httpx.HTTPError, ValueError) as exc:
                why = str(exc) if type(exc) is ValueError and str(exc).startswith("the key") else exc.__class__.__name__
                self.notes[where] = f"{port['name']}: could not read the list at {time.strftime('%H:%M')} ({why})."
                log.warning("port list %s: %s", where, exc)

    @staticmethod
    def ask_singapore(client: httpx.Client, now: float | None = None) -> list[dict]:
        """MPA's due to arrive (today and tomorrow), arrivals and due to depart (today), in Singapore dates."""
        now = now or time.time()
        head = {"apikey": os.environ["SG_OCEANSX_API_KEY"], "Accept": "application/json"}
        parts = []
        for env, default, state, days in SG_ASKS:
            for d in days:
                date = datetime.fromtimestamp(now + d * DAY, SINGAPORE).strftime("%Y-%m-%d")
                r = client.get((os.environ.get(env) or default).replace("{date}", date), headers=head)
                if r.status_code in (401, 403):
                    raise ValueError(f"the key was refused (HTTP {r.status_code}); check SG_OCEANSX_API_KEY and that the app is subscribed")
                if r.status_code == 404:
                    continue  # nothing for that day, or the address moved (see SG_*_URL)
                r.raise_for_status()
                parts.append(parse_sg(r.json(), state))
                time.sleep(1)
        return merge_sg(parts)

    # ------------------------------------------------------------------ carriers
    @staticmethod
    def carrier_ready(cid: str) -> bool:
        return all(os.environ.get(e) for e in CARRIERS[cid]["env"])

    def ask_carrier(self, client: httpx.Client, cid: str, imo: int) -> dict:
        c = CARRIERS[cid]
        base = (os.environ.get(f"{cid.upper()}_SCHEDULES_URL") or c["url"]).rstrip("/")
        env = {e: os.environ.get(e, "") for e in c["env"]}
        try:
            r = client.get(f"{base}/vessel-schedules", params={"vesselIMONumber": str(imo)}, headers={**UA, **c["headers"](env)})
            if r.status_code in (401, 403):
                got = {"error": f"{c['name']} refused the key (HTTP {r.status_code}); check it in Settings > Keys."}
            elif r.status_code == 404:
                got = {"error": f"{c['name']} has no schedule for this ship (or the address has moved: {cid.upper()}_SCHEDULES_URL)."}
            else:
                r.raise_for_status()
                got = parse_dcsa(r.json())
        except (httpx.HTTPError, ValueError) as exc:
            got = {"error": f"{c['name']} did not answer ({exc.__class__.__name__})."}
        got.update(at=int(time.time()), carrier=cid)
        with self.lock:
            self.carrier[str(imo)] = got
            self.dirty = True
        return got

    def fetch_carriers(self, client: httpx.Client, ships: list[dict]) -> None:
        """Ask each line's schedule for its ships seen lately (a few dozen an hour at most)."""
        asked = 0
        for s in ships:
            if asked >= CARRIER_PER_ROUND:
                break
            ln = line_of(s.get("name"))
            if not ln or not ln[1] or not s.get("imo") or not self.carrier_ready(ln[1]):
                continue
            had = self.carrier.get(str(s["imo"]))
            if had and time.time() - had.get("at", 0) < CARRIER_EVERY:
                continue
            self.ask_carrier(client, ln[1], s["imo"])
            asked += 1
        if asked:
            self.notes["carriers"] = f"Asked the lines' schedules for {asked} ships at {time.strftime('%H:%M')}."

    # ------------------------------------------------------------------ background
    def start(self, settings_fn, ships_fn) -> None:
        """Every hour: the port lists, then the lines' schedules (Settings > Transport)."""
        if self.thread and self.thread.is_alive():
            return

        def run():
            time.sleep(90)
            while True:
                s = settings_fn() or {}
                try:
                    if s.get("ship_schedules", True):
                        with httpx.Client(timeout=30, follow_redirects=True, headers=UA) as client:
                            if s.get("port_lists_fetch", True):
                                self.fetch_ports(client)
                            if s.get("carrier_schedules", True):
                                self.fetch_carriers(client, ships_fn())
                        self.save(int(s.get("schedules_keep_days") or 90))
                except Exception as exc:  # noqa: BLE001 - tried again next hour
                    log.warning("ship schedules: %s", exc)
                time.sleep(FETCH_EVERY)

        self.thread = threading.Thread(target=run, daemon=True, name="ship-schedules")
        self.thread.start()

    # ------------------------------------------------------------------ reading
    def voyages(self, mmsi: int) -> list[dict]:
        """The ETA history cut into voyages (a new one when the destination changes), newest last."""
        out: list[dict] = []
        for seen, dest, eta in self.etas.get(mmsi, []):
            if not out or _key(dest) != _key(out[-1]["destination"]):
                out.append({"destination": dest, "started": seen, "history": []})
            if eta:
                out[-1]["history"].append([seen, eta])
        for v in out:
            h = v["history"]
            v["first_eta"] = h[0][1] if h else None
            v["eta"] = h[-1][1] if h else None
            v["moved_h"] = round((h[-1][1] - h[0][1]) / 3600, 1) if h else None
        return out

    def _call_over(self, b: dict, mmsi: int | None, now: float) -> bool:
        """A booked call is over: the port says the ship left, we saw it leave that port, or it is
        two days past its booked departure."""
        if b.get("departed_at") and b["departed_at"] < now:
            return True
        booked = b.get("arrival") or b["first"][1]
        for c in self.calls.get(mmsi, []) if mmsi else []:
            if c.get("left") and _key(c["port"].get("locode") or c["port"].get("name")) in (_key(b["locode"]), _key(b["port"])) \
                    and abs(c["arrived"] - booked) < 3 * DAY and c["left"] < now:
                return True
        return bool(b.get("departs") and b["departs"] + 2 * DAY < now)

    def booking_for(self, imo: int | None, name: str | None, now: float, mmsi: int | None = None) -> dict | None:
        """The ship's nearest booking in a port list: the next one, else the latest within 3 days."""
        best = None
        for key, calls in self.bookings.items():
            if key.split("|", 1)[1] not in (str(imo or ""), _key(name)):
                continue
            for b in calls:
                arr = b.get("arrived_at") or b.get("arrival") or 0
                if self._call_over(b, mmsi, now):  # the ship is on its next voyage
                    continue
                if arr < now - 3 * DAY:
                    continue
                if best is None or arr < (best.get("arrived_at") or best.get("arrival") or 0):
                    best = b
        return best

    def route(self, mmsi: int) -> dict:
        """The ports a ship called at, in order, and its loop once seen twice."""
        calls = self.calls.get(mmsi, [])
        seq = [c["port"].get("name") or c["port"].get("locode") for c in calls]
        seq = [p for i, p in enumerate(seq) if i == 0 or p != seq[i - 1]]
        out = {"ports": seq[-12:], "loop": None, "times": 0, "round_days": None}
        if len(seq) < 3:
            return out
        last = seq[-1]
        prev = [i for i in range(len(seq) - 1) if seq[i] == last]
        if not prev:
            return out
        loop = seq[prev[-1]:len(seq) - 1]
        times = sum(1 for i in range(len(seq) - len(loop) + 1) if seq[i:i + len(loop)] == loop)
        visits = [c["arrived"] for c in calls if (c["port"].get("name") or c["port"].get("locode")) == last]
        gaps = [b - a for a, b in zip(visits, visits[1:]) if b - a > 2 * DAY]
        out.update(loop=loop + [last] if times >= 2 else None, times=times,
                   round_days=round(sum(gaps) / len(gaps) / DAY, 1) if gaps and times >= 2 else None)
        return out

    def status(self, mmsi: int, detail: dict, live: dict | None, dest_port: dict | None, now: float | None = None) -> dict:
        """How late a ship is, three ways, and our own estimate of its arrival."""
        now = now or time.time()
        voy = self.voyages(mmsi)
        v = voy[-1] if voy else None
        live = live or {}
        lat, lon, sog = live.get("lat", detail.get("lat")), live.get("lon", detail.get("lon")), live.get("speed_kn", detail.get("speed_kn"))
        book = self.booking_for(detail.get("imo"), detail.get("name"), now, mmsi)
        if not dest_port and book:  # going to a port whose list it is booked in
            dest_port = next((p for p in PORT_LISTS.values() if p["locode"] == book["locode"]), None)
        estimate = None
        if dest_port and lat is not None and dest_port.get("lat") is not None and isinstance(sog, (int, float)) and sog >= 3:
            from worldmodel_api.seapath import sea_path_soon
            sea = sea_path_soon(lon, lat, dest_port["lon"], dest_port["lat"])
            nm = sea["nm"] if sea and sea["nm"] else sea_nm(lon, lat, dest_port["lon"], dest_port["lat"])
            estimate = {"at": int(now + nm / sog * 3600), "nm": round(nm), "speed_kn": sog, "port": dest_port.get("name")}
        carrier = self.carrier.get(str(detail.get("imo"))) if detail.get("imo") else None
        out = {"voyage": v, "estimate": estimate, "booking": book, "carrier": carrier, "measured_by": None, "late_h": None,
               "moved_h": None, "state": "none"}
        actual_at = None
        # 1. the line's schedule: the next call with a planned arrival
        ccall = None
        if carrier and carrier.get("calls"):
            for c in carrier["calls"]:
                if c.get("arr_planned") and (c.get("arr_actual") or c.get("arr_estimated") or c["arr_planned"]) >= now - 2 * DAY:
                    ccall = c
                    break
        if ccall:
            got = ccall.get("arr_actual") or ccall.get("arr_estimated") or (estimate["at"] if estimate else None)
            if got:
                out.update(measured_by="line", late_h=round((got - ccall["arr_planned"]) / 3600, 1), line_call=ccall)
        # 2. the port's booking
        if out["late_h"] is None and book:
            first = book["versions"][0][1] if book.get("versions") else book["first"][1]
            actual_at = book.get("arrived_at") or self._arrived(mmsi, book["locode"], first)
            got = actual_at or book.get("arrival")
            if got:
                out.update(measured_by="port", late_h=round((got - first) / 3600, 1),
                           moved_h=round(((book.get("arrival") or first) - first) / 3600, 1))
        # 3. the ship's own first ETA this voyage
        if out["late_h"] is None and v and v.get("first_eta"):
            port = dest_port or {}
            actual_at = self._arrived(mmsi, port.get("locode") or port.get("name"), v["first_eta"]) if port else None
            got = actual_at or v["eta"]
            out.update(measured_by="ship", late_h=round((got - v["first_eta"]) / 3600, 1))
        if v and v.get("moved_h") is not None:
            out["moved_h"] = max(out["moved_h"] or 0, v["moved_h"])
        out["arrived_at"] = actual_at
        late = out["late_h"]
        if late is None:
            out["state"] = "none"
        elif late > ON_TIME_H:
            out["state"] = "late"
        elif late < -ON_TIME_H:
            out["state"] = "early"
        elif (out["moved_h"] or 0) >= SLIP_H:
            out["state"] = "slipping"
        else:
            out["state"] = "on_time"
        return out

    def _arrived(self, mmsi: int, port_key: str | None, near: float) -> int | None:
        """When we saw the ship stop at a port, within 3 days of a booked time."""
        if not port_key:
            return None
        k = _key(port_key)
        for c in reversed(self.calls.get(mmsi, [])):
            if k in (_key(c["port"].get("locode")), _key(c["port"].get("name"))) and abs(c["arrived"] - near) < 3 * DAY:
                return c["arrived"]
        return None
