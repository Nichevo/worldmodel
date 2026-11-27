"""Airport busy hours: flights per hour at each airport, how close the busiest hour comes to a
published limit, gates and aircraft stands, and delays where they are published.

- Flights per hour: once a day, OpenSky Network's list of each airport's arrivals and
  departures for the days just gone (its flight lists are worked out overnight), counted by
  the airport's local hour. The airports: every New Zealand airport with scheduled flights,
  the large airports of Australia and the UK, and the world's busiest
  (congestion.yaml). Uses the OpenSky API client from .env when set (more requests a day).
- Limits: congestion.yaml (caps, curfews, slot levels, each with where it is set out) and
  any CSV saved in <data folder>/manual/airport_limits.
- Gates and stands: OpenStreetMap's aeroway=gate and aeroway=parking_position within a few
  km of the airport, counted by Overpass once a month (25 airports a question).
- Delays: EUROCONTROL's open files (Europe: flights a day, arrival delay held on the ground
  for want of airport capacity, extra taxi-out and holding time, monthly) and the FAA's
  airport status now (US: ground stops, ground delay programmes, closures; read when asked).

Everything is kept under <data folder>/congestion/airports.
"""

from __future__ import annotations

import bz2
import csv
import io
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import httpx
from worldmodel_contract import catalogue, local

log = logging.getLogger(__name__)

UA = {"User-Agent": "worldmodel (personal research tool)"}
OPENSKY_FLIGHTS = "https://opensky-network.org/api/flights/{kind}"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
EUROCONTROL = "https://www.eurocontrol.int/performance/data/download/csv/{name}_{year}.csv"
EUROCONTROL_DLY = "https://www.eurocontrol.int/performance/data/download/csv/apt_dly_{year}.csv.bz2"
FAA_STATUS = "https://nasstatus.faa.gov/api/airport-status-information"
DAY = 86400
READY_AFTER = 30 * 3600   # OpenSky's flight lists for a UTC day are complete about this long after it starts
BACKFILL_DAYS = 14        # days fetched the first time an airport is added
KEEP_DAYS = 800           # days of counts kept per airport
ASK_GAP = 2.0             # seconds between OpenSky requests
ROUND_EVERY = 3 * 3600    # the collector looks for new days this often
GATES_EVERY = 30 * DAY
DELAYS_EVERY = 7 * DAY
GATES_BATCH = 25
FAA_KEEP = 300

_lock = threading.Lock()
_faa: tuple[float, dict] | None = None
_list_cache: tuple[float, list[dict]] | None = None


def root() -> Path:
    p = local.home() / "congestion" / "airports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# ----------------------------------------------------------------------------- the airports
def _layer(q, layer_id: str) -> list[dict]:
    try:
        got = q("SELECT geojson FROM layers WHERE layer_id = ?", [layer_id])
    except Exception:  # noqa: BLE001 - no warehouse yet
        return []
    if not got:
        return []
    data = got[0]["geojson"]
    return (json.loads(data) if isinstance(data, str) else data).get("features") or []


def pick_airports(features: list[dict], cfg: dict, world: bool = True) -> list[dict]:
    """The airports counted: every scheduled airport in the all_scheduled countries, the large
    ones in the large countries, and the busiest list (when world is on), by ICAO code."""
    homes = cfg.get("home_countries") or {}
    every, large = set(homes.get("all_scheduled") or []), set(homes.get("large") or [])
    busiest = [str(c).upper() for c in cfg.get("busiest_airports") or []]
    rank = {c: i for i, c in enumerate(busiest)}
    out: dict[str, dict] = {}
    for f in features:
        p = f.get("properties") or {}
        icao = str(p.get("icao") or "").upper()
        if not re.fullmatch(r"[A-Z]{4}", icao):
            continue
        country = p.get("country")
        why = ("home" if country in every else "large" if country in large and p.get("size") == "large"
               else "busiest" if world and icao in rank else None)
        if not why:
            continue
        lon, lat = (f.get("geometry") or {}).get("coordinates") or (None, None)
        if lon is None:
            continue
        out[icao] = {"icao": icao, "iata": p.get("iata"), "name": p.get("name"), "city": p.get("city"), "country": country,
                     "size": p.get("size"), "lon": round(float(lon), 5), "lat": round(float(lat), 5), "why": why,
                     "rank": rank.get(icao)}
    return sorted(out.values(), key=lambda a: (a["why"] != "home", a["rank"] if a["rank"] is not None else 999, a["icao"]))


def _zone_of(q, lon: float, lat: float) -> str | None:
    """The time zone at a point, from the time zone outlines (geo_features 'timezones')."""
    try:
        from shapely.geometry import Point, shape
        got = q("""SELECT props, geojson FROM geo_features WHERE layer_id = 'timezones'
                   AND west <= ? AND east >= ? AND south <= ? AND north >= ?""", [lon, lon, lat, lat])
    except Exception:  # noqa: BLE001 - no outlines loaded
        return None
    pt = Point(lon, lat)
    for r in got:
        try:
            if shape(json.loads(r["geojson"])).contains(pt):
                return (json.loads(r["props"] or "{}")).get("tz")
        except Exception:  # noqa: BLE001
            continue
    return None


def airports(q, settings: dict | None = None) -> list[dict]:
    """The airports counted, each with its time zone (kept an hour)."""
    global _list_cache
    with _lock:
        if _list_cache and time.time() - _list_cache[0] < 3600:
            return _list_cache[1]
    s = settings or {}
    cfg = catalogue.congestion()
    got = pick_airports(_layer(q, "airports"), cfg, world=bool(s.get("airport_hours_world", True)))
    zones_file = root() / "zones.json"
    zones = _read(zones_file, {})
    fallback = cfg.get("country_time_zones") or {}
    changed = False
    for a in got:
        if a["icao"] not in zones:
            zones[a["icao"]] = _zone_of(q, a["lon"], a["lat"]) or fallback.get(a["country"]) or ""
            changed = changed or bool(zones[a["icao"]])
        a["tz"] = zones.get(a["icao"]) or fallback.get(a["country"]) or _lon_zone(a["lon"])
    if changed:
        _write(zones_file, zones)
    with _lock:
        _list_cache = (time.time(), got)
    return got


def _lon_zone(lon: float) -> str:
    """A whole-hour zone from the longitude, when nothing better is known (Etc/GMT signs are reversed)."""
    h = max(-12, min(14, round(lon / 15)))
    return "UTC" if h == 0 else f"Etc/GMT{'-' if h > 0 else '+'}{abs(h)}"


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


# ----------------------------------------------------------------------------- counting
def count_flights(arrivals: list[dict], departures: list[dict], tz: ZoneInfo) -> dict[str, dict[str, list[int]]]:
    """OpenSky's arrival and departure lists as {local day: {"arr": [24], "dep": [24]}}."""
    out: dict[str, dict[str, list[int]]] = {}

    def add(ts, kind):
        if not ts:
            return
        t = datetime.fromtimestamp(int(ts), UTC).astimezone(tz)
        d = out.setdefault(t.date().isoformat(), {"arr": [0] * 24, "dep": [0] * 24})
        d[kind][t.hour] += 1

    for f in arrivals or []:
        add(f.get("lastSeen"), "arr")
    for f in departures or []:
        add(f.get("firstSeen"), "dep")
    return out


def merge_counts(store: dict, utc_day: str, counts: dict[str, dict[str, list[int]]]) -> None:
    """Adds one UTC day's flights into the airport's store. A local day spans two UTC days, so
    each UTC day's part is kept on its own and added up when read."""
    store.setdefault("parts", {})[utc_day] = counts
    done = store.setdefault("done", [])
    if utc_day not in done:
        done.append(utc_day)
        done.sort()


def local_days(store: dict, tz: ZoneInfo) -> dict[str, dict[str, list[int]]]:
    """Whole local days only: those every UTC day touching them has been fetched for."""
    done = set(store.get("done") or [])
    total: dict[str, dict[str, list[int]]] = {}
    for part in (store.get("parts") or {}).values():
        for day, c in part.items():
            t = total.setdefault(day, {"arr": [0] * 24, "dep": [0] * 24})
            for k in ("arr", "dep"):
                t[k] = [a + b for a, b in zip(t[k], c.get(k) or [0] * 24)]
    out = {}
    for day, c in total.items():
        start = datetime.fromisoformat(day).replace(tzinfo=tz)
        first = start.astimezone(UTC).date()
        last = (start + timedelta(hours=23, minutes=59)).astimezone(UTC).date()
        need = {(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)}
        if need <= done:
            out[day] = c
    return dict(sorted(out.items()))


def profile(days: dict[str, dict[str, list[int]]], last: int = 28) -> dict:
    """Average flights each local hour (arrivals plus departures) on weekdays and weekends over
    the last `last` whole days, the busiest weekday hour, and flights a day."""
    keys = sorted(days)[-last:]
    wk = [days[d] for d in keys if date.fromisoformat(d).weekday() < 5]
    we = [days[d] for d in keys if date.fromisoformat(d).weekday() >= 5]

    def avg(group, kind=None):
        if not group:
            return [None] * 24
        return [round(mean((g["arr"][h] + g["dep"][h]) if kind is None else g[kind][h] for g in group), 1) for h in range(24)]

    weekday = avg(wk)
    peak = max(range(24), key=lambda h: weekday[h] or 0) if wk else None
    return {"weekday": weekday, "weekend": avg(we), "weekday_arr": avg(wk, "arr"), "weekday_dep": avg(wk, "dep"),
            "peak_hour": peak, "peak_flights": weekday[peak] if peak is not None else None,
            "per_day": round(mean(sum(days[d]["arr"]) + sum(days[d]["dep"]) for d in keys), 1) if keys else None,
            "days": len(keys), "from": keys[0] if keys else None, "to": keys[-1] if keys else None}


def daily_series(days: dict[str, dict[str, list[int]]]) -> list[dict]:
    """Each day's flights and busiest hour."""
    return [{"day": d, "flights": sum(c["arr"]) + sum(c["dep"]),
             "peak": max(a + b for a, b in zip(c["arr"], c["dep"]))} for d, c in sorted(days.items())]


def record(days: dict[str, dict[str, list[int]]]) -> float | None:
    """The busiest single hour seen in the last year."""
    keys = sorted(days)[-366:]
    return max((max(a + b for a, b in zip(days[d]["arr"], days[d]["dep"])) for d in keys), default=None)


# ----------------------------------------------------------------------------- limits
def limits() -> dict[str, dict]:
    """Published limits by ICAO code: congestion.yaml, then the user's own CSV files."""
    out = {k.upper(): dict(v or {}) for k, v in (catalogue.congestion().get("airport_limits") or {}).items()}
    folder = local.home() / "manual" / "airport_limits"
    if folder.is_dir():
        for p in sorted(folder.glob("*.csv")):
            try:
                with p.open(encoding="utf-8-sig", newline="") as fh:
                    for r in csv.DictReader(fh):
                        r = {str(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
                        icao = r.get("icao", "").upper()
                        if not re.fullmatch(r"[A-Z]{4}", icao):
                            continue
                        got = out.setdefault(icao, {})
                        for k in ("hourly_limit", "annual_limit", "slot_level"):
                            if r.get(k):
                                try:
                                    got[k] = int(float(r[k]))
                                except ValueError:
                                    pass
                        for k in ("curfew", "note", "source", "limit_kind", "link"):
                            if r.get(k):
                                got[k] = r[k]
                        got.setdefault("source", f"Your file {p.name}")
            except OSError:
                continue
    return out


def curfew_hours(text: str | None) -> list[int]:
    """'23:00-06:00' as the local hours it covers: [23, 0, 1, 2, 3, 4, 5]."""
    m = re.fullmatch(r"\s*(\d{1,2}):?(\d{2})?\s*-\s*(\d{1,2}):?(\d{2})?\s*", str(text or ""))
    if not m:
        return []
    a, b = int(m[1]) % 24, int(m[3]) % 24
    out, h = [], a
    while h != b and len(out) < 24:
        out.append(h)
        h = (h + 1) % 24
    return out


# ----------------------------------------------------------------------------- gates (OpenStreetMap)
def gates_query(batch: list[dict]) -> str:
    parts = []
    for a in batch:
        r = 4000 if a.get("size") == "large" else 2500
        parts.append(f'nwr["aeroway"="gate"](around:{r},{a["lat"]},{a["lon"]});out count;'
                     f'nwr["aeroway"="parking_position"](around:{r},{a["lat"]},{a["lon"]});out count;')
    return "[out:json][timeout:180];" + "".join(parts)


def gates_counts(body: dict, batch: list[dict]) -> dict[str, dict]:
    """Overpass's counts, two per airport in order (gates, then stands)."""
    counts = [int(((e.get("tags") or {}).get("total")) or 0) for e in body.get("elements") or [] if e.get("type") == "count"]
    out = {}
    for i, a in enumerate(batch):
        if 2 * i + 1 < len(counts):
            out[a["icao"]] = {"gates": counts[2 * i], "stands": counts[2 * i + 1]}
    return out


# ----------------------------------------------------------------------------- delays
def eurocontrol_rows(text: str) -> list[dict]:
    return [{str(k or "").strip().upper(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def _f(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def eurocontrol_months(traffic: list[dict], dly: list[dict], taxi: list[dict], asma: list[dict]) -> dict[str, dict[str, dict]]:
    """{ICAO: {"2026-01": {flights, flights_ifr, arr_delay_min (ATFM, per arrival), taxi_add_min (per
    departure), asma_add_min (per arrival)}}} from EUROCONTROL's files."""
    out: dict[str, dict[str, dict]] = {}

    def cell(icao, month):
        return out.setdefault(icao, {}).setdefault(month, {})

    for r in traffic:
        icao, d = r.get("APT_ICAO"), r.get("FLT_DATE", "")[:7]
        if not icao or not d:
            continue
        c = cell(icao, d)
        c["flights"] = c.get("flights", 0) + (_f(r.get("FLT_TOT_1")) or 0)
        c["days"] = c.get("days", 0) + 1
    arr: dict[tuple[str, str], list[float]] = {}
    for r in dly:
        icao, d = r.get("APT_ICAO"), r.get("FLT_DATE", "")[:7]
        flights, delay = _f(r.get("FLT_ARR_1")), _f(r.get("DLY_APT_ARR_1"))
        if icao and d and flights:
            a = arr.setdefault((icao, d), [0.0, 0.0])
            a[0] += flights
            a[1] += delay or 0
    for (icao, d), (n, mins) in arr.items():
        cell(icao, d)["arr_delay_min"] = round(mins / n, 2) if n else None
    for rows, key in ((taxi, "taxi_add_min"), (asma, "asma_add_min")):
        for r in rows:
            icao = r.get("APT_ICAO")
            y, m = r.get("YEAR"), r.get("MONTH_NUM")
            n, add = _f(r.get("TOTAL_REF_NB_FL")), _f(r.get("TOTAL_ADD_TIME_MIN"))
            if icao and y and m and n:
                cell(icao, f"{y}-{int(m):02d}")[key] = round((add or 0) / n, 2)
    for months in out.values():
        for c in months.values():
            if c.get("days"):
                c["flights_a_day"] = round(c.pop("flights", 0) / c.pop("days"), 1)
    return out


def faa_status(xml_text: str) -> dict[str, list[dict]]:
    """The FAA's airport status now: {FAA code: [{kind, reason, detail}]}."""
    out: dict[str, list[dict]] = {}
    try:
        rootel = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for dt in rootel.iter("Delay_type"):
        kind = (dt.findtext("Name") or "").strip()
        for el in dt.iter():
            code = el.findtext("ARPT")
            if not code or el.tag in ("Delay_type",):
                continue
            bits = [f"{c.tag.replace('_', ' ')}: {(c.text or '').strip()}" for c in el
                    if c.tag not in ("ARPT", "Reason") and (c.text or "").strip()]
            for sub in el.iter("Arrival_Departure"):
                bits.append(f"{sub.get('Type', '')} {sub.findtext('Min') or ''}-{sub.findtext('Max') or ''} ({sub.findtext('Trend') or ''})".strip())
            out.setdefault(code.strip().upper(), []).append({"kind": kind, "reason": (el.findtext("Reason") or "").strip()[:200],
                                                             "detail": "; ".join(b for b in bits if b and not b.endswith(": "))[:300]})
    return out


def faa_now() -> dict:
    global _faa
    with _lock:
        if _faa and time.time() - _faa[0] < FAA_KEEP:
            return _faa[1]
    try:
        with httpx.Client(timeout=20, headers=UA) as c:
            r = c.get(FAA_STATUS)
            r.raise_for_status()
            got = {"at": time.time(), "airports": faa_status(r.text)}
    except Exception as exc:  # noqa: BLE001
        got = {"at": time.time(), "airports": {}, "error": f"FAA airport status could not be read: {exc}"}
    with _lock:
        _faa = (time.time(), got)
    return got


# ----------------------------------------------------------------------------- the collector
class Collector:
    """Once every few hours: new days of flights for each airport, gates once a month and the
    EUROCONTROL files once a week. Stops for the round at OpenSky's first refusal."""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.state = _read(root() / "status.json", {})
        self.busy = False

    def status(self) -> dict:
        return dict(self.state, busy=self.busy)

    def _save_state(self, **kw) -> None:
        self.state.update(kw)
        _write(root() / "status.json", self.state)

    def start(self, q, settings_fn) -> None:
        if self.thread and self.thread.is_alive():
            return

        def run():
            time.sleep(120)
            while True:
                s = settings_fn() or {}
                try:
                    if s.get("airport_hours_fetch", True):
                        self.round(q, s)
                except Exception as exc:  # noqa: BLE001 - tried again next round
                    log.warning("airport busy hours: %s", exc)
                    self._save_state(error=str(exc)[:300])
                time.sleep(ROUND_EVERY)

        self.thread = threading.Thread(target=run, daemon=True, name="airport-hours")
        self.thread.start()

    def round(self, q, s: dict, client: httpx.Client | None = None, now: float | None = None) -> dict:
        now = now or time.time()
        self.busy = True
        own = client is None
        client = client or httpx.Client(timeout=60, headers=UA, follow_redirects=True)
        done = 0
        try:
            todo = airports(q, s)
            self._save_state(airports=len(todo), round_started=now)
            err = None
            for a in todo:
                try:
                    done += self.fetch_airport(client, a, now)
                except _Refused as exc:
                    err = str(exc)
                    break
            self._save_state(round_ended=time.time(), days_fetched=done, error=err)
            if s.get("airport_gates_fetch", True) and now - float(self.state.get("gates_at") or 0) > GATES_EVERY:
                self.fetch_gates(client, todo)
            if s.get("airport_delays_fetch", True) and now - float(self.state.get("delays_at") or 0) > DELAYS_EVERY:
                self.fetch_eurocontrol(client, now)
        finally:
            self.busy = False
            if own:
                client.close()
        return self.status()

    def _headers(self, client: httpx.Client) -> dict:
        try:
            from worldmodel_api import live
            return live.PLANES._auth(client)
        except Exception:  # noqa: BLE001 - asked without an account
            return {}

    def fetch_airport(self, client: httpx.Client, a: dict, now: float) -> int:
        path = root() / f"{a['icao']}.json"
        store = _read(path, {})
        tz = _tz(a["tz"])
        done = set(store.get("done") or [])
        today = datetime.fromtimestamp(now, UTC).date()
        want = []
        for back in range(1, BACKFILL_DAYS + 1):
            d = today - timedelta(days=back)
            start = datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()
            if now - start >= READY_AFTER and d.isoformat() not in done:
                want.append((d, start))
        got = 0
        for d, start in sorted(want):
            lists = {}
            for kind in ("arrival", "departure"):
                r = client.get(OPENSKY_FLIGHTS.format(kind=kind), headers=self._headers(client),
                               params={"airport": a["icao"], "begin": int(start), "end": int(start + DAY - 1)})
                if r.status_code == 404:  # OpenSky: no flights in the window
                    lists[kind] = []
                elif r.status_code in (401, 403, 429):
                    raise _Refused(f"OpenSky refused the flight lists ({r.status_code}); tried again in a few hours")
                else:
                    r.raise_for_status()
                    lists[kind] = r.json() or []
                time.sleep(ASK_GAP)
            merge_counts(store, d.isoformat(), count_flights(lists["arrival"], lists["departure"], tz))
            got += 1
        if got:
            cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
            store["parts"] = {k: v for k, v in (store.get("parts") or {}).items() if k >= cut}
            store["done"] = [k for k in store.get("done") or [] if k >= cut]
            store.update(icao=a["icao"], tz=a["tz"], updated=now)
            _write(path, store)
        return got

    def fetch_gates(self, client: httpx.Client, todo: list[dict]) -> None:
        got = _read(root() / "gates.json", {})
        for i in range(0, len(todo), GATES_BATCH):
            batch = todo[i:i + GATES_BATCH]
            try:
                r = client.post(OVERPASS_URL, data={"data": gates_query(batch)}, timeout=240)
                if r.status_code in (406, 429, 504):
                    log.info("airport gates: Overpass answered %s; the rest next month", r.status_code)
                    break
                r.raise_for_status()
                got.update(gates_counts(r.json(), batch))
            except Exception as exc:  # noqa: BLE001
                log.info("airport gates: %s", exc)
                break
            time.sleep(10)
        _write(root() / "gates.json", got)
        self._save_state(gates_at=time.time())

    def fetch_eurocontrol(self, client: httpx.Client, now: float) -> None:
        year = datetime.fromtimestamp(now, UTC).year
        months = _read(root() / "eurocontrol.json", {})
        for y in (year - 1, year):
            try:
                def text(url):
                    r = client.get(url, timeout=120)
                    r.raise_for_status()
                    return r.content
                traffic = eurocontrol_rows(text(EUROCONTROL.format(name="airport_traffic", year=y)).decode("utf-8-sig", "replace"))
                try:
                    dly = eurocontrol_rows(bz2.decompress(text(EUROCONTROL_DLY.format(year=y))).decode("utf-8-sig", "replace"))
                except Exception:  # noqa: BLE001 - the delay file comes later in the year
                    dly = []
                taxi = eurocontrol_rows(text(EUROCONTROL.format(name="taxi_out_additional_time", year=y)).decode("utf-8-sig", "replace"))
                asma = eurocontrol_rows(text(EUROCONTROL.format(name="asma_additional_time", year=y)).decode("utf-8-sig", "replace"))
            except Exception as exc:  # noqa: BLE001
                log.info("EUROCONTROL %s: %s", y, exc)
                continue
            for icao, m in eurocontrol_months(traffic, dly, taxi, asma).items():
                months.setdefault(icao, {}).update(m)
        _write(root() / "eurocontrol.json", months)
        self._save_state(delays_at=time.time())


class _Refused(Exception):
    pass


COLLECTOR = Collector()


# ----------------------------------------------------------------------------- reading
def _summary(a: dict, lim: dict, gates: dict) -> dict:
    store = _read(root() / f"{a['icao']}.json", {})
    days = local_days(store, _tz(a["tz"]))
    pr = profile(days)
    l = lim.get(a["icao"]) or {}
    rec = record(days)
    peak = pr["peak_flights"]
    use = None
    against = None
    if peak and l.get("hourly_limit"):
        use, against = round(100 * peak / l["hourly_limit"]), "limit"
    elif peak and rec:
        use, against = round(100 * peak / rec), "record"
    g = gates.get(a["icao"]) or {}
    return {**a, "per_day": pr["per_day"], "peak_hour": pr["peak_hour"], "peak_flights": peak, "record_hour": rec,
            "hourly_limit": l.get("hourly_limit"), "annual_limit": l.get("annual_limit"), "slot_level": l.get("slot_level"),
            "curfew": l.get("curfew"), "use": use, "against": against, "gates": g.get("gates"), "stands": g.get("stands"),
            "days": pr["days"]}


def airport_list(q, settings: dict | None = None) -> dict:
    lim, gates = limits(), _read(root() / "gates.json", {})
    rows = [_summary(a, lim, gates) for a in airports(q, settings)]
    return {"airports": rows, "status": COLLECTOR.status(), "has_counts": any(r["days"] for r in rows)}


def airport_detail(q, icao: str, settings: dict | None = None) -> dict | None:
    icao = icao.upper()
    a = next((x for x in airports(q, settings) if x["icao"] == icao or (x.get("iata") or "").upper() == icao), None)
    if not a:
        return None
    lim = limits()
    gates = _read(root() / "gates.json", {})
    store = _read(root() / f"{a['icao']}.json", {})
    days = local_days(store, _tz(a["tz"]))
    euro = (_read(root() / "eurocontrol.json", {}).get(a["icao"]) or {})
    out = {**_summary(a, lim, gates), "profile": profile(days), "daily": daily_series(days),
           "limit": lim.get(a["icao"]), "curfew_hours": curfew_hours((lim.get(a["icao"]) or {}).get("curfew")),
           "eurocontrol": [{"month": k, **v} for k, v in sorted(euro.items())]}
    if a.get("country") == "USA" and a.get("iata"):
        f = faa_now()
        out["faa"] = {"now": f["airports"].get(a["iata"].upper(), []), "error": f.get("error"), "at": f["at"]}
    return out


def map_features(q, settings: dict | None = None) -> dict:
    feats = []
    for r in airport_list(q, settings)["airports"]:
        props = {k: r.get(k) for k in ("icao", "iata", "name", "per_day", "peak_hour", "peak_flights", "use", "against",
                                       "hourly_limit", "gates", "stands", "curfew", "country")}
        props["id"] = r["icao"]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": props})
    return {"type": "FeatureCollection", "features": feats,
            **({"note": "No flights counted yet: the app counts them once a day from OpenSky (Settings > Transport > Airport busy hours)."}
               if not any(f["properties"]["per_day"] for f in feats) else {})}
