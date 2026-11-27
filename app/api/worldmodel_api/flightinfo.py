"""A clicked plane's published schedule and what a seat on its route costs, from free sources,
asked only when the plane's card is opened.

- Schedule: AeroDataBox's flight status by callsign (or by the plane's hex code when it sends no
  callsign), through RapidAPI with a free key (AERODATABOX_API_KEY; the free plan has a small
  monthly allowance). Scheduled, revised and actual times at both ends, status, and terminal,
  gate and baggage belt when the airport publishes them. Kept so the same flight is not asked
  again soon, and counted per month so the app stops before the allowance runs out.
- Seat prices: Travelpayouts' Aviasales data API with a free token (TRAVELPAYOUTS_TOKEN): the
  cheapest fares people found on Aviasales for the route in the last few days, by day of the
  month. These are fares seen in searches, not a live price for a seat on this flight.
- Links to look up fares by hand (Google Flights, Skyscanner, Aviasales), with no key.

Every answer actually asked (not one kept from earlier) is also saved for good, one JSON line each,
in <home>/live/planes/flight_history/ (schedules-YYYY-MM.jsonl, fares-YYYY-MM.jsonl), so delays and
fares can be looked back on later. Nothing there is deleted by the app.

Google Flights prices are not read: Google offers no API and its terms forbid automated reading.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

ADB_HOST = "aerodatabox.p.rapidapi.com"
ADB_URL = "https://aerodatabox.p.rapidapi.com/flights/{by}/{what}"
TP_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
UA = {"User-Agent": "worldmodel (personal research tool)", "Accept": "application/json"}
LIVE_KEEP = 20 * 60        # a flight still on its way is asked again after this (delays and gates change)
DONE_KEEP = 12 * 3600      # a flight that has landed or was cancelled
MISS_KEEP = 6 * 3600       # AeroDataBox knew no flight for this callsign
FARES_KEEP = 12 * 3600     # fares for a route and month
LOOKUPS_MONTH = 250        # default monthly cap on schedule look-ups (Settings > Transport)
DONE = {"arrived", "canceled", "cancelled", "diverted", "canceleduncertain"}

_lock = threading.Lock()
_memory: dict[str, dict[str, tuple[float, object]]] = {}


def adb_key() -> str:
    return (os.environ.get("AERODATABOX_API_KEY") or "").strip()


def tp_token() -> str:
    return (os.environ.get("TRAVELPAYOUTS_TOKEN") or "").strip()


def currency() -> str:
    return (os.environ.get("FARES_CURRENCY") or "NZD").strip().upper()[:3] or "NZD"


# ----------------------------------------------------------------------------- keeping answers
def _kept(store, kind: str, key: str, max_age: float):
    if store is not None:
        return store.lookup(kind, key, max_age)
    with _lock:
        hit = _memory.get(kind, {}).get(key)
    return (hit[1], hit[0]) if hit and time.time() - hit[0] < max_age else None


def _keep(store, kind: str, key: str, value, drop_after: float) -> None:
    if store is not None:
        store.keep(kind, key, value, drop_after)
        return
    with _lock:
        part = _memory.setdefault(kind, {})
        part[key] = (time.time(), value)
        for k in [k for k, v in part.items() if time.time() - v[0] > drop_after]:
            part.pop(k, None)


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def used_this_month(store) -> int:
    hit = _kept(store, "adb_month", _month(), 40 * 86400)
    return int(hit[0]) if hit and isinstance(hit[0], (int, float)) else 0


def _count_lookup(store) -> None:
    _keep(store, "adb_month", _month(), used_this_month(store) + 1, 70 * 86400)


# ----------------------------------------------------------------------------- history
def _history_dir(store):
    folder = getattr(store, "folder", None)
    return folder / "flight_history" if folder is not None else None


def save_history(store, kind: str, row: dict) -> None:
    """Add one answer to this month's history file (never fails the card)."""
    folder = _history_dir(store)
    if folder is None:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with _lock, (folder / f"{kind}-{_month()}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": int(time.time()), **row}, separators=(",", ":")) + "\n")
    except OSError as exc:
        log.warning("flight history %s: %s", kind, exc)


def _read_history(store, kind: str, since: float):
    folder = _history_dir(store)
    if folder is None or not folder.exists():
        return
    first = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m")
    for f in sorted(folder.glob(f"{kind}-*.jsonl")):
        if f.stem.split("-", 1)[1] < first:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("at", 0) >= since:
                yield row


def history(store, number: str | None = None, frm: str | None = None, to: str | None = None, days: float = 365) -> dict:
    """Saved schedules for a flight number (or callsign), and saved fares for a route, oldest first.
    Schedules give one row per flight date (the last answer saved for it)."""
    since = time.time() - days * 86400
    want = "".join(ch for ch in str(number or "").upper() if ch.isalnum())
    flights: dict[str, dict] = {}
    if want:
        for row in _read_history(store, "schedules", since):
            f = row.get("flight") or {}
            names = {"".join(ch for ch in str(f.get(k) or "").upper() if ch.isalnum()) for k in ("number", "callsign")}
            if want not in names:
                continue
            dep, arr = f.get("departure") or {}, f.get("arrival") or {}
            day = str((dep.get("scheduled") or {}).get("local") or "")[:10] or str(row["at"])
            flights[f"{f.get('number')}|{day}"] = {"saved": row["at"], "date": day, "number": f.get("number"), "status": f.get("status"),
                "from": (dep.get("airport") or {}).get("iata"), "to": (arr.get("airport") or {}).get("iata"),
                "late_leave_min": dep.get("late_min"), "late_arrive_min": arr.get("late_min"), "gate": dep.get("gate"),
                "aircraft": (f.get("aircraft") or {}).get("reg")}
    fares_seen = []
    if frm and to:
        route = f"{frm.upper()}-{to.upper()}"
        for row in _read_history(store, "fares", since):
            if row.get("route") != route:
                continue
            prices = [r.get("price") for r in row.get("rows") or [] if isinstance(r.get("price"), (int, float))]
            if prices:
                fares_seen.append({"saved": row["at"], "month": row.get("month"), "currency": row.get("currency"),
                                   "cheapest": min(prices), "count": len(prices)})
    return {"flights": sorted(flights.values(), key=lambda r: r["date"]), "fares": fares_seen}


# ----------------------------------------------------------------------------- schedule
def _t(end: dict, name: str) -> dict | None:
    """A time from AeroDataBox: {"utc": "2026-11-28 01:00Z", "local": "2026-11-28 14:00+13:00"};
    older answers had scheduledTimeUtc / scheduledTimeLocal instead."""
    v = end.get(name)
    if isinstance(v, dict) and (v.get("utc") or v.get("local")):
        return {"utc": v.get("utc"), "local": v.get("local")}
    base = name[:-4] if name.endswith("Time") else name
    utc, local = end.get(f"{base}TimeUtc"), end.get(f"{base}TimeLocal")
    return {"utc": utc, "local": local} if utc or local else None


def _epoch(t: dict | None) -> float | None:
    s = (t or {}).get("utc")
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def _end(e: dict | None) -> dict | None:
    if not isinstance(e, dict):
        return None
    a = e.get("airport") or {}
    out = {"airport": {"name": a.get("name") or a.get("shortName"), "city": a.get("municipalityName"), "iata": a.get("iata"),
                       "icao": a.get("icao"), "country": a.get("countryCode"), "tz": a.get("timeZone")},
           "scheduled": _t(e, "scheduledTime"), "revised": _t(e, "revisedTime"), "predicted": _t(e, "predictedTime"),
           "runway": _t(e, "runwayTime"), "terminal": e.get("terminal"), "gate": e.get("gate"),
           "check_in": e.get("checkInDesk"), "baggage": e.get("baggageBelt"), "quality": e.get("quality") or []}
    s = _epoch(out["scheduled"])
    best = _epoch(out["runway"]) or _epoch(out["revised"]) or _epoch(out["predicted"])
    out["late_min"] = round((best - s) / 60) if s and best else None
    return out


def parse_flight(f: dict) -> dict:
    al = f.get("airline") or {}
    ac = f.get("aircraft") or {}
    return {"number": f.get("number"), "callsign": f.get("callSign"), "status": f.get("status"),
            "airline": {"name": al.get("name"), "iata": al.get("iata"), "icao": al.get("icao")},
            "aircraft": {"reg": ac.get("reg"), "model": ac.get("model"), "hex": (ac.get("modeS") or "").lower() or None},
            "cargo": bool(f.get("isCargo")), "codeshare": f.get("codeshareStatus"), "updated": f.get("lastUpdatedUtc"),
            "departure": _end(f.get("departure")), "arrival": _end(f.get("arrival"))}


def _when(end: dict | None) -> float | None:
    if not end:
        return None
    return _epoch(end.get("runway")) or _epoch(end.get("revised")) or _epoch(end.get("predicted")) or _epoch(end.get("scheduled"))


def pick_flight(flights: list[dict], now: float | None = None, hex_code: str | None = None) -> dict | None:
    """The flight that is in the air now (left, not yet arrived), else the one whose departure is
    nearest to now. Flights flown by this plane (its hex code) come first."""
    now = time.time() if now is None else now
    if hex_code:
        mine = [f for f in flights if (f.get("aircraft") or {}).get("hex") == hex_code.lower()]
        flights = mine or flights
    best, best_d = None, float("inf")
    for f in flights:
        dep, arr = _when(f.get("departure")), _when(f.get("arrival"))
        if dep and arr and dep - 3600 <= now <= arr + 1800:
            d = 0.0
        elif dep:
            d = abs(dep - now)
        else:
            continue
        if d < best_d:
            best, best_d = f, d
    return best or (flights[0] if flights else None)


def schedule(store, icao24: str, callsign: str | None, settings: dict | None = None, client: httpx.Client | None = None) -> dict:
    """The published schedule of the flight this plane is flying, kept for a while once asked."""
    settings = settings or {}
    cap = int(settings.get("flight_lookups_month", LOOKUPS_MONTH) or 0)
    cs = "".join(ch for ch in str(callsign or "").upper() if ch.isalnum())
    by, what = ("callsign", cs) if cs else ("icao24", icao24.lower())
    out: dict = {"flight": None, "found": 0, "used_month": used_this_month(store), "cap_month": cap, "source": "AeroDataBox"}
    hit = _kept(store, "schedule", f"{by}:{what}", DONE_KEEP)
    if hit:
        value, at = hit
        f = (value or {}).get("flight") if isinstance(value, dict) else None
        status = str((f or {}).get("status") or "").lower()
        age = time.time() - at
        fresh = age < (MISS_KEEP if not f else DONE_KEEP if status in DONE else LIVE_KEEP)
        if fresh:
            return {**out, **value, "kept_at": int(at)}
    if cap <= 0:
        return {**out, "note": "Schedule look-ups are off (Settings > Transport: Flight schedule look-ups a month)."}
    key = adb_key()
    if not key:
        return {**out, "needs_key": "AERODATABOX_API_KEY",
                "note": "Add a free AeroDataBox key (AERODATABOX_API_KEY in Settings > Keys) to see this flight's published times, delays and gate."}
    if out["used_month"] >= cap:
        return {**out, "note": f"This month's {cap} schedule look-ups are used up (Settings > Transport), so none until next month."}
    own = client is None
    client = client or httpx.Client(timeout=20, headers=UA)
    try:
        r = client.get(ADB_URL.format(by=by, what=quote(what)), params={"withAircraftImage": "false", "withLocation": "false"},
                       headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": ADB_HOST})
        _count_lookup(store)
        out["used_month"] += 1
        left = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit") and "remaining" in k.lower()}
        if left:
            out["allowance_left"] = left
        if r.status_code in (204, 404):
            value = {"flight": None, "found": 0, "note": f"AeroDataBox has no published flight for {what} around now (private, military and many cargo flights have none)."}
            _keep(store, "schedule", f"{by}:{what}", value, 2 * 86400)
            return {**out, **value}
        if r.status_code in (401, 403):
            return {**out, "error": f"AeroDataBox refused the key (HTTP {r.status_code}); check AERODATABOX_API_KEY and that the free plan is subscribed on RapidAPI."}
        if r.status_code == 429:
            return {**out, "error": "AeroDataBox says too many requests or the month's allowance is used up (HTTP 429)."}
        r.raise_for_status()
        body = r.json()
        rows = body if isinstance(body, list) else (body.get("items") or [body]) if isinstance(body, dict) else []
        flights = [parse_flight(f) for f in rows if isinstance(f, dict)]
        for f in flights:
            save_history(store, "schedules", {"by": by, "what": what, "hex": icao24.lower(), "flight": f})
        chosen = pick_flight(flights, hex_code=icao24)
        value = {"flight": chosen, "found": len(flights)}
        _keep(store, "schedule", f"{by}:{what}", value, 2 * 86400)
        return {**out, **value}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.info("AeroDataBox %s %s: %s", by, what, exc)
        return {**out, "error": f"AeroDataBox did not answer ({exc.__class__.__name__})."}
    finally:
        if own:
            client.close()


# ----------------------------------------------------------------------------- seat prices
def fare_links(frm: str, to: str, day: str | None) -> list[dict]:
    """Pages where fares for the route can be checked by hand (no key, nothing read by the app)."""
    frm, to = frm.upper(), to.upper()
    links = []
    q = f"Flights from {frm} to {to}" + (f" on {day}" if day else "")
    links.append({"label": "Google Flights", "href": f"https://www.google.com/travel/flights?q={quote(q)}"})
    sky = f"https://www.skyscanner.net/transport/flights/{frm.lower()}/{to.lower()}/"
    if day and len(day) == 10:
        sky += f"{day[2:4]}{day[5:7]}{day[8:10]}/"
    links.append({"label": "Skyscanner", "href": sky})
    av = f"https://www.aviasales.com/search/{frm}{day[8:10]}{day[5:7]}{to}1" if day and len(day) == 10 else "https://www.aviasales.com/"
    links.append({"label": "Aviasales", "href": av})
    return links


def _fare_row(d: dict) -> dict:
    link = d.get("link")
    return {"price": d.get("price"), "date": (d.get("departure_at") or "")[:10] or None, "departs": d.get("departure_at"),
            "airline": d.get("airline"), "flight": d.get("flight_number"), "transfers": d.get("transfers"),
            "minutes": d.get("duration_to") or d.get("duration"), "from": d.get("origin_airport") or d.get("origin"),
            "to": d.get("destination_airport") or d.get("destination"),
            "link": f"https://www.aviasales.com{link}" if isinstance(link, str) and link.startswith("/") else None}


def fares(store, frm: str, to: str, day: str | None, airline: str | None = None, number: str | None = None,
          settings: dict | None = None, client: httpx.Client | None = None) -> dict:
    """Cheapest fares seen for a route in the month of `day` (YYYY-MM-DD), the cheapest that day,
    and this flight's own fare if someone searched it."""
    settings = settings or {}
    frm, to = (frm or "").upper()[:3], (to or "").upper()[:3]
    cur = currency()
    out: dict = {"from": frm, "to": to, "day": day, "currency": cur, "links": fare_links(frm, to, day), "source": "Travelpayouts (Aviasales)",
                 "cheapest_month": None, "cheapest_day": None, "this_flight": None, "count": 0}
    if not settings.get("flight_fares", True):
        return {**out, "note": "Fares are off (Settings > Transport: Seat prices for a plane's route); the links still work."}
    token = tp_token()
    if not token:
        return {**out, "needs_key": "TRAVELPAYOUTS_TOKEN",
                "note": "Add a free Travelpayouts token (TRAVELPAYOUTS_TOKEN in Settings > Keys) to see fares people found for this route lately."}
    month = (day or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:7]
    kkey = f"{frm}-{to}-{month}-{cur}"
    hit = _kept(store, "fares", kkey, FARES_KEEP)
    if hit:
        rows, at = hit
        out["kept_at"] = int(at)
    else:
        own = client is None
        client = client or httpx.Client(timeout=20, headers=UA)
        try:
            r = client.get(TP_URL, params={"origin": frm, "destination": to, "departure_at": month, "one_way": "true",
                                           "direct": "false", "sorting": "price", "limit": 100, "currency": cur.lower()},
                           headers={"X-Access-Token": token})
            if r.status_code in (401, 403):
                return {**out, "error": f"Travelpayouts refused the token (HTTP {r.status_code}); check TRAVELPAYOUTS_TOKEN."}
            if r.status_code == 429:
                return {**out, "error": "Travelpayouts says too many requests (HTTP 429); try again in a minute."}
            r.raise_for_status()
            body = r.json()
            if isinstance(body, dict) and body.get("success") is False:
                return {**out, "error": f"Travelpayouts: {str(body.get('error') or 'no answer')[:120]}"}
            rows = [_fare_row(d) for d in (body.get("data") or []) if isinstance(d, dict)] if isinstance(body, dict) else []
            _keep(store, "fares", kkey, rows, 3 * 86400)
            save_history(store, "fares", {"route": f"{frm}-{to}", "month": month, "currency": cur, "rows": rows})
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.info("Travelpayouts %s: %s", kkey, exc)
            return {**out, "error": f"Travelpayouts did not answer ({exc.__class__.__name__})."}
        finally:
            if own:
                client.close()
    rows = [r for r in rows if isinstance(r.get("price"), (int, float))]
    out["count"] = len(rows)
    if rows:
        out["cheapest_month"] = min(rows, key=lambda r: r["price"])
        same = [r for r in rows if day and r["date"] == day]
        out["cheapest_day"] = min(same, key=lambda r: r["price"]) if same else None
        num = "".join(ch for ch in str(number or "") if ch.isdigit())
        al = (airline or "").upper()
        mine = [r for r in same if num and al and str(r.get("airline") or "").upper() == al and str(r.get("flight") or "") == num]
        out["this_flight"] = min(mine, key=lambda r: r["price"]) if mine else None
    else:
        out["note"] = "No fares seen for this route this month (Aviasales keeps only fares people searched in the last few days)."
    return out
