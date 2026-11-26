"""Forecast accuracy: which model has been most right, city by city.

Every 6 hours (while the app runs and Settings > Climate > Weather allows) each model's forecast
for the next 48 hours is stored for the cities in contract forecast_skill.CITIES, every 3 hours of
it (Open-Meteo, one request a batch of cities with all the models). What actually happened is
stored hour by hour from two places:

    airport   the city's main airport's own weather reports (METAR, aviationweather.gov): measured
              temperature and wind, and whether it rained, drizzled, snowed or stormed in the hour
    analysis  Open-Meteo's best estimate of the past hours, for cities with no airport reports and
              for hours the airport missed

A forecast is checked against the airport where it has a report for that hour, else the analysis.
Scores, over the last 60 days, for each model and city, split by how far ahead the forecast was
(up to 24 hours, 24 to 48 hours):

    temperature  mean absolute error, °C
    wind         mean absolute error, km/h
    rain         balanced Brier score of a rain chance from the forecast amount (90% at 0.5 mm or
                 more in the hour, 70% at 0.1 mm, else 5%): the mean of the score on wet hours and
                 on dry hours, so an "always dry" model gains nothing in a dry spell

The best model in a city is the one with the lowest mean rank over the three. A forecast is checked
once its hour is 12 hours past (both kinds of truth are in by then) and only the day's sums are kept,
so the store stays a few MB: <data folder>/weather/scores/skill.sqlite.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from worldmodel_contract import local
from worldmodel_contract.forecast_skill import CITIES, MODELS, REGIONS

log = logging.getLogger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
METAR = "https://aviationweather.gov/api/data/metar"
USER_AGENT = "worldmodel/0.1 (personal local tool) httpx"
EVERY = 6 * 3600          # record this often
CHECK = 20 * 60           # look whether a record is due this often
AHEAD = 48                # hours of forecast kept from each run ...
STEP = 3                  # ... every this many hours
KEEP_DAYS = 62            # daily sums kept this long
WINDOW_DAYS = 60
SETTLE = 12 * 3600        # a forecast is checked once its hour is this far past
KEEP_RAW = 3 * 86400      # forecasts never checked (no truth came) and past hours go after this
BATCH = 20                # cities a request
LEADS = {"day1": (0, 24), "day2": (24, 48)}
MIN_PAIRS = 12            # checked forecasts a model needs in a city before it is ranked
KN_TO_KMH = 1.852
WET_MM = 0.1
# Present-weather codes that mean rain, drizzle, snow, hail or a storm at the airport (not "VC": nearby).
WET_WX = re.compile(r"(?<![A-Z])(?:[-+]|)(?:SH|TS|FZ)?(?:RA|DZ|SN|SG|GR|GS|PL|UP)|(?<![A-Z])TS(?![A-Z])")

_lock = threading.Lock()
_state: dict = {"thread": None, "running": False, "last": 0.0, "note": "", "error": ""}
_cache: dict = {}


def path() -> Path:
    return local.home() / "weather" / "scores" / "skill.sqlite"


def connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p, timeout=30)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS forecasts (city TEXT, model TEXT, issued INTEGER, valid INTEGER,
            temp REAL, precip REAL, wind REAL, PRIMARY KEY (city, model, issued, valid));
        CREATE TABLE IF NOT EXISTS actuals (city TEXT, valid INTEGER, source TEXT,
            temp REAL, precip REAL, wind REAL, wet INTEGER, PRIMARY KEY (city, valid, source));
        CREATE TABLE IF NOT EXISTS stations (icao TEXT PRIMARY KEY, lat REAL, lon REAL, name TEXT);
        CREATE TABLE IF NOT EXISTS runs (at INTEGER PRIMARY KEY, forecasts INTEGER, airport INTEGER, analysis INTEGER, note TEXT);
        CREATE TABLE IF NOT EXISTS sums (day INTEGER, city TEXT, model TEXT, lead TEXT, n INTEGER, air INTEGER,
            te REAL, tn INTEGER, we REAL, wn INTEGER, bw REAL, nw INTEGER, bd REAL, nd INTEGER,
            PRIMARY KEY (day, city, model, lead)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER);
    """)
    return db


def _get(url: str, params: dict, timeout: float = 60):
    import httpx
    r = httpx.get(url, params=params, timeout=httpx.Timeout(timeout, connect=15), follow_redirects=True,
                  headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _epoch(t: str) -> int:
    """'2026-11-26T03:00' (UTC) -> seconds."""
    return int(datetime.strptime(t[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp())


def place(db: sqlite3.Connection, c) -> tuple[float, float]:
    """Where a city's forecasts are asked for: its airport once known (so forecast and report match), else the city."""
    if c.icao:
        row = db.execute("SELECT lat, lon FROM stations WHERE icao = ?", (c.icao,)).fetchone()
        if row:
            return row[0], row[1]
    return c.lat, c.lon


def _col(hourly: dict, key: str, j: int) -> float | None:
    a = hourly.get(key) or []
    return _num(a[j]) if j < len(a) else None


# ----------------------------------------------------------------------------- recording
def record_forecasts(db: sqlite3.Connection, now: int, get: Callable[[str, dict], object]) -> int:
    """Each model's next 48 hours (every 3 hours) for every city, as issued now."""
    issued = now - now % 3600
    rows = []
    for i in range(0, len(CITIES), BATCH):
        part = CITIES[i:i + BATCH]
        at = [place(db, c) for c in part]
        got = get(OPEN_METEO, {"latitude": ",".join(f"{a[0]:.3f}" for a in at), "longitude": ",".join(f"{a[1]:.3f}" for a in at),
                               "hourly": "temperature_2m,precipitation,wind_speed_10m", "models": ",".join(MODELS),
                               "forecast_days": 3, "timezone": "GMT", "wind_speed_unit": "kmh"})
        got = got if isinstance(got, list) else [got]
        for c, g in zip(part, got):
            hr = (g or {}).get("hourly") or {}
            times = hr.get("time") or []
            for j, t in enumerate(times):
                valid = _epoch(t)
                lead = (valid - issued) / 3600
                if lead <= 0 or lead > AHEAD or (valid // 3600) % STEP:
                    continue
                for m in MODELS:
                    temp, precip, wind = (_col(hr, f"{k}_{m}", j) for k in ("temperature_2m", "precipitation", "wind_speed_10m"))
                    if temp is None and precip is None:
                        continue
                    rows.append((c.id, m, issued, valid, temp, precip, wind))
    db.executemany("INSERT OR REPLACE INTO forecasts VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def metar_hours(reports: list[dict]) -> dict[int, dict]:
    """Airport reports -> what happened each whole hour (UTC, hour-ending): the temperature and wind
    of the report nearest the hour (within 25 minutes), and wet when any report in the hour before
    names rain, drizzle, snow, hail or a storm at the airport."""
    near: dict[int, tuple[float, dict]] = {}
    wet: dict[int, bool] = {}
    for r in reports:
        t = r.get("obsTime")
        if not isinstance(t, (int, float)):
            continue
        t = int(t)
        hour = int(round(t / 3600) * 3600)
        gap = abs(t - hour)
        if gap <= 25 * 60 and (hour not in near or gap < near[hour][0]):
            near[hour] = (gap, r)
        ending = (t // 3600 + (0 if t % 3600 == 0 else 1)) * 3600  # the hour this report falls in
        raw = str(r.get("wxString") or "")
        wet[ending] = wet.get(ending, False) or bool(WET_WX.search(raw.replace("VC", " ")))
    out = {}
    for hour, (_, r) in near.items():
        temp, wind = _num(r.get("temp")), _num(r.get("wspd"))
        out[hour] = {"temp": temp, "wind": wind * KN_TO_KMH if wind is not None else None, "wet": int(wet.get(hour, False))}
    for hour, w in wet.items():
        out.setdefault(hour, {"temp": None, "wind": None, "wet": int(w)})
    return out


def record_airports(db: sqlite3.Connection, get: Callable[[str, dict], object], hours: int = 8) -> int:
    """The last hours of every airport's reports; also learns where each airport is."""
    by_icao = {c.icao: c for c in CITIES if c.icao}
    ids = list(by_icao)
    n = 0
    for i in range(0, len(ids), 40):
        got = get(METAR, {"ids": ",".join(ids[i:i + 40]), "format": "json", "hours": hours}) or []
        per: dict[str, list[dict]] = {}
        for r in got if isinstance(got, list) else []:
            per.setdefault(str(r.get("icaoId")), []).append(r)
        for icao, reps in per.items():
            c = by_icao.get(icao)
            if not c:
                continue
            r0 = reps[0]
            if _num(r0.get("lat")) is not None and _num(r0.get("lon")) is not None:
                db.execute("INSERT OR REPLACE INTO stations VALUES (?,?,?,?)", (icao, float(r0["lat"]), float(r0["lon"]), r0.get("name")))
            for hour, v in metar_hours(reps).items():
                db.execute("INSERT OR REPLACE INTO actuals VALUES (?,?,?,?,?,?,?)",
                           (c.id, hour, "airport", v["temp"], None, v["wind"], v["wet"]))
                n += 1
    return n


def record_analysis(db: sqlite3.Connection, now: int, get: Callable[[str, dict], object]) -> int:
    """Open-Meteo's estimate of the past day's hours for every city (finished hours only)."""
    n = 0
    for i in range(0, len(CITIES), BATCH):
        part = CITIES[i:i + BATCH]
        at = [place(db, c) for c in part]
        got = get(OPEN_METEO, {"latitude": ",".join(f"{a[0]:.3f}" for a in at), "longitude": ",".join(f"{a[1]:.3f}" for a in at),
                               "hourly": "temperature_2m,precipitation,wind_speed_10m", "past_days": 2, "forecast_days": 1,
                               "timezone": "GMT", "wind_speed_unit": "kmh"})
        got = got if isinstance(got, list) else [got]
        for c, g in zip(part, got):
            hr = (g or {}).get("hourly") or {}
            for j, t in enumerate(hr.get("time") or []):
                valid = _epoch(t)
                if valid > now - 3600:
                    break
                temp = _num((hr.get("temperature_2m") or [None] * (j + 1))[j])
                precip = _num((hr.get("precipitation") or [None] * (j + 1))[j])
                wind = _num((hr.get("wind_speed_10m") or [None] * (j + 1))[j])
                db.execute("INSERT OR REPLACE INTO actuals VALUES (?,?,?,?,?,?,?)",
                           (c.id, valid, "analysis", temp, precip, wind, None if precip is None else int(precip >= WET_MM)))
                n += 1
    return n


def record(now: int | None = None, get: Callable[[str, dict], object] | None = None) -> dict:
    """One round: forecasts now, what happened lately; then old rows go."""
    now = int(now or time.time())
    get = get or _get
    out = {"at": now, "forecasts": 0, "airport": 0, "analysis": 0, "note": ""}
    notes = []
    db = connect()
    try:
        for key, step in (("airport", lambda: record_airports(db, get)), ("analysis", lambda: record_analysis(db, now, get)),
                          ("forecasts", lambda: record_forecasts(db, now, get))):
            try:
                out[key] = step()
            except Exception as exc:  # noqa: BLE001 - one part failing keeps the others
                notes.append(f"{key}: {type(exc).__name__}: {str(exc)[:120]}")
        out["checked"] = check(db, now)
        out["note"] = "; ".join(notes)
        db.execute("DELETE FROM forecasts WHERE valid < ?", (now - KEEP_RAW,))
        db.execute("DELETE FROM actuals WHERE valid < ?", (now - KEEP_RAW,))
        db.execute("DELETE FROM sums WHERE day < ?", ((now - KEEP_DAYS * 86400) // 86400,))
        db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)", (now, out["forecasts"], out["airport"], out["analysis"], out["note"]))
        db.commit()
    finally:
        db.close()
    _cache.clear()
    return out


# ----------------------------------------------------------------------------- the background round
def last_run() -> float:
    if not path().exists():
        return 0.0
    db = connect()
    try:
        row = db.execute("SELECT MAX(at) FROM runs WHERE forecasts > 0").fetchone()
    finally:
        db.close()
    return float(row[0] or 0)


def _loop(settings_fn: Callable[[], dict]) -> None:
    while True:
        try:
            s = settings_fn()
            if s.get("weather_skill", True) and s.get("weather_maps", True) and time.time() - last_run() >= EVERY - 60:
                _state["running"] = True
                got = record()
                _state.update(last=time.time(), note=got["note"], error="" if got["forecasts"] else got["note"] or "no forecasts came")
        except Exception as exc:  # noqa: BLE001 - tried again next round
            log.warning("forecast scoring round stopped: %s", exc)
            _state["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        finally:
            _state["running"] = False
        time.sleep(CHECK)


def start(settings_fn: Callable[[], dict]) -> None:
    """Record every 6 hours while the app runs (the first round a minute after it starts)."""
    with _lock:
        t = _state.get("thread")
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=lambda: (time.sleep(60), _loop(settings_fn)), name="forecast-skill", daemon=True)
        _state["thread"] = t
        t.start()


# ----------------------------------------------------------------------------- scoring
def chance(precip: float | None) -> float | None:
    """A rain chance from a forecast amount (the same steps as single-run models get in WeatherTrack-style scoring)."""
    if precip is None:
        return None
    return 0.9 if precip >= 0.5 else 0.7 if precip >= WET_MM else 0.05


def pairs(db: sqlite3.Connection, lo: int, hi: int) -> list[tuple]:
    """(city, model, f_temp, f_precip, f_wind, a_temp, a_wind, a_wet, source, lead, day) for every forecast
    for an hour from lo up to hi: the airport's report for the hour where there is one, else the analysis."""
    return db.execute("""
        WITH truth AS (
            SELECT city, valid,
                   COALESCE(MAX(CASE WHEN source = 'airport' THEN temp END), MAX(CASE WHEN source = 'analysis' THEN temp END)) AS temp,
                   COALESCE(MAX(CASE WHEN source = 'airport' THEN wind END), MAX(CASE WHEN source = 'analysis' THEN wind END)) AS wind,
                   COALESCE(MAX(CASE WHEN source = 'airport' THEN wet END), MAX(CASE WHEN source = 'analysis' THEN wet END)) AS wet,
                   CASE WHEN MAX(CASE WHEN source = 'airport' AND temp IS NOT NULL THEN 1 END) = 1 THEN 'airport' ELSE 'analysis' END AS src
            FROM actuals WHERE valid >= ? AND valid < ? GROUP BY city, valid)
        SELECT f.city, f.model, f.temp, f.precip, f.wind, t.temp, t.wind, t.wet, t.src,
               CASE WHEN f.valid - f.issued <= 24 * 3600 THEN 'day1' ELSE 'day2' END, f.valid / 86400
        FROM forecasts f JOIN truth t ON t.city = f.city AND t.valid = f.valid
        WHERE f.valid >= ? AND f.valid < ? AND f.valid - f.issued > 0 AND f.valid - f.issued <= ? * 3600
    """, (lo, hi, lo, hi, AHEAD)).fetchall()


SUMS = ("n", "air", "te", "tn", "we", "wn", "bw", "nw", "bd", "nd")


def _add(a: dict, ft, fp, fw, at, aw, wet, src) -> None:
    a["n"] += 1
    a["air"] += src == "airport"
    if ft is not None and at is not None:
        a["te"] += abs(ft - at)
        a["tn"] += 1
    if fw is not None and aw is not None:
        a["we"] += abs(fw - aw)
        a["wn"] += 1
    p = chance(fp)
    if p is not None and wet is not None:
        if wet:
            a["bw"] += (p - 1) ** 2
            a["nw"] += 1
        else:
            a["bd"] += p ** 2
            a["nd"] += 1


def check(db: sqlite3.Connection, now: int) -> int:
    """Check every forecast whose hour has settled since the last round, adding it to the day's sums."""
    row = db.execute("SELECT v FROM meta WHERE k = 'checked_until'").fetchone()
    hi = now - SETTLE
    lo = row[0] if row else hi - KEEP_RAW
    if hi <= lo:
        return 0
    acc: dict[tuple, dict] = {}
    rows = pairs(db, lo, hi)
    for city, model, ft, fp, fw, at, aw, wet, src, lead, day in rows:
        _add(acc.setdefault((day, city, model, lead), dict.fromkeys(SUMS, 0)), ft, fp, fw, at, aw, wet, src)
    cols = ", ".join(SUMS)
    db.executemany(f"""INSERT INTO sums (day, city, model, lead, {cols}) VALUES (?,?,?,?,{",".join("?" * len(SUMS))})
        ON CONFLICT (day, city, model, lead) DO UPDATE SET {", ".join(f"{c} = {c} + excluded.{c}" for c in SUMS)}""",
                   [(*k, *(a[c] for c in SUMS)) for k, a in acc.items()])
    db.execute("INSERT OR REPLACE INTO meta VALUES ('checked_until', ?)", (hi,))
    db.execute("DELETE FROM forecasts WHERE valid < ?", (hi,))
    return len(rows)


def score_rows(rows: list[tuple]) -> dict[str, dict[str, dict]]:
    """Checked pairs (city, model, f_temp, f_precip, f_wind, a_temp, a_wind, a_wet, source) -> city -> model -> scores."""
    acc: dict[tuple, dict] = {}
    for city, model, ft, fp, fw, at, aw, wet, src, *_ in rows:
        _add(acc.setdefault((city, model), dict.fromkeys(SUMS, 0)), ft, fp, fw, at, aw, wet, src)
    return scores(acc)


def scores(acc: dict[tuple, dict]) -> dict[str, dict[str, dict]]:
    """(city, model) -> sums  ->  city -> model -> {temp, wind, rain, n, airport_share, wet_hours}."""
    out: dict[str, dict[str, dict]] = {}
    for (city, model), a in acc.items():
        if a["nw"] and a["nd"]:  # balanced: wet and dry hours count the same
            rain = (a["bw"] / a["nw"] + a["bd"] / a["nd"]) / 2
        elif a["nw"] + a["nd"]:
            rain = (a["bw"] + a["bd"]) / (a["nw"] + a["nd"])
        else:
            rain = None
        out.setdefault(city, {})[model] = {
            "temp": round(a["te"] / a["tn"], 2) if a["tn"] else None, "wind": round(a["we"] / a["wn"], 1) if a["wn"] else None,
            "rain": round(rain, 3) if rain is not None else None, "n": a["n"], "airport_share": round(a["air"] / a["n"], 2) if a["n"] else 0,
            "wet_hours": a["nw"],
        }
    return out


def rank(models: dict[str, dict]) -> list[dict]:
    """Models in a city, best first: the mean of their ranks on temperature, wind and rain (equal scores share a rank;
    equal means: the better temperature)."""
    ok = {m: s for m, s in models.items() if s["n"] >= MIN_PAIRS}
    ranks: dict[str, list[int]] = {m: [] for m in ok}
    for k in ("temp", "wind", "rain"):
        have = sorted((s[k], m) for m, s in ok.items() if s[k] is not None)
        for _, m in have:  # equal scores share the better rank
            ranks[m].append(1 + sum(v < ok[m][k] for v, _ in have))
    out = [{"model": m, "name": MODELS.get(m, m), **ok[m], "mean_rank": round(sum(r) / len(r), 2) if r else None}
           for m, r in ranks.items()]
    out.sort(key=lambda x: (x["mean_rank"] if x["mean_rank"] is not None else 99, x["temp"] if x["temp"] is not None else 99))
    out += [{"model": m, "name": MODELS.get(m, m), **s, "mean_rank": None} for m, s in models.items() if m not in ok]
    return out


def table(lead: str = "day1", now: int | None = None) -> dict:
    """Every city's models ranked, its best, and the regions' best, for one lead window."""
    lead = lead if lead in LEADS else "day1"
    now = int(now or time.time())
    key = (lead, now // 600)
    if key in _cache:
        return _cache[key]
    info = {"last_round": None, "days": 0, "rounds": 0, "running": _state.get("running", False),
            "note": _state.get("note", ""), "error": _state.get("error", "")}
    if not path().exists():
        return {"lead": lead, "cities": [], "regions": [], **info}
    db = connect()
    try:
        got = db.execute(f"SELECT city, model, {', '.join(f'SUM({c})' for c in SUMS)} FROM sums WHERE lead = ? AND day >= ? "
                         "GROUP BY city, model", (lead, (now - WINDOW_DAYS * 86400) // 86400)).fetchall()
        scored = scores({(r[0], r[1]): dict(zip(SUMS, r[2:])) for r in got})
        first, last, rounds = db.execute("SELECT MIN(at), MAX(at), COUNT(*) FROM runs WHERE forecasts > 0").fetchone()
        at = {c.id: place(db, c) for c in CITIES}
    finally:
        db.close()
    info.update(last_round=datetime.fromtimestamp(last, timezone.utc).isoformat().replace("+00:00", "Z") if last else None,
                days=round((now - first) / 86400, 1) if first else 0, rounds=rounds)
    cities = []
    for c in CITIES:
        ranked = rank(scored.get(c.id, {}))
        best = ranked[0] if ranked and ranked[0]["mean_rank"] is not None else None
        cities.append({"id": c.id, "name": c.name, "country": c.country, "region": c.region, "icao": c.icao,
                       "lat": at[c.id][0], "lon": at[c.id][1], "best": best["model"] if best else None,
                       "best_name": best["name"] if best else None, "models": ranked})
    regions = []
    for r in REGIONS:
        wins: dict[str, int] = {}
        for c in cities:
            if c["region"] == r and c["best"]:
                wins[c["best"]] = wins.get(c["best"], 0) + 1
        top = sorted(wins.items(), key=lambda kv: -kv[1])
        regions.append({"region": r, "cities": sum(c["region"] == r for c in cities),
                        "wins": [{"model": m, "name": MODELS.get(m, m), "cities": n} for m, n in top]})
    out = {"lead": lead, "cities": cities, "regions": regions, "models": MODELS, **info}
    _cache.clear()
    _cache[key] = out
    return out


def near(lat: float, lon: float, lead: str = "day1", within_km: float = 600) -> dict:
    """The nearest scored city (within 600 km) and its best model, for a place's forecast card."""
    t = table(lead)
    best, dist = None, None
    for c in t["cities"]:
        if not c["best"]:
            continue
        d = _km(lat, lon, c["lat"], c["lon"])
        if d <= within_km and (dist is None or d < dist):
            best, dist = c, d
    if best is None:
        return {"city": None, "days": t["days"]}
    top = best["models"][0]
    return {"city": best["name"], "city_id": best["id"], "km": round(dist), "best": top["model"], "best_name": top["name"],
            "temp": top["temp"], "wind": top["wind"], "rain": top["rain"], "n": top["n"], "airport_share": top["airport_share"],
            "order": [m["model"] for m in best["models"]], "days": t["days"]}


def _km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(h)))


def layer(lead: str = "day1") -> dict:
    """The cities as GeoJSON points, coloured on the map by their best model."""
    t = table(lead)
    feats = []
    for c in t["cities"]:
        top = c["models"][0] if c["models"] and c["best"] else None
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                      "properties": {"name": c["name"], "country": c["country"], "best": c["best"] or "", "best_name": c["best_name"] or "",
                                     "temp": top["temp"] if top else None, "n": top["n"] if top else 0,
                                     "airport": c["icao"] or "", "airport_share": top["airport_share"] if top else None,
                                     "runner_up": c["models"][1]["name"] if top and len(c["models"]) > 1 and c["models"][1]["mean_rank"] is not None else "",
                                     "days": t["days"]}})
    return {"type": "FeatureCollection", "features": feats, "days": t["days"], "rounds": t["rounds"],
            **({"note": "Forecast scoring has not run yet: it starts a minute after the app does, then every 6 hours."} if not t["rounds"] else {})}


def status() -> dict:
    t = table()
    return {k: t[k] for k in ("last_round", "days", "rounds", "running", "note", "error")}


def dumps(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"))
