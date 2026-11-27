"""Road traffic: official roadside counters, kept, and TomTom's live traffic tiles, shown only.

- New Zealand: NZTA's state highway traffic monitoring sites (about 4,000, each with five
  years of average daily traffic) and their daily counts (open ArcGIS services, CC BY 4.0).
  Daily totals only; telemetry sites send them weekly, others less often.
- England: National Highways WebTRIS, 15-minute counts and average speeds on motorways and
  major A roads (open). About 300 sites are kept, one per small square of the network, as
  hourly totals; WebTRIS's figures lag by some weeks.
- New South Wales: Transport for NSW's permanent counting stations, hourly (free key,
  TFNSW_API_KEY, the same key as Sydney's trains).
- TomTom traffic flow tiles: how fast traffic moves now against free flow, drawn over the map.
  TomTom's free terms are for showing the tiles, not keeping them, so nothing is saved
  (TOMTOM_API_KEY, free).

Kept under <data folder>/congestion/roads, read again once a week.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean
from urllib.parse import quote

import httpx
from worldmodel_contract import local

log = logging.getLogger(__name__)

UA = {"User-Agent": "worldmodel (personal research tool)"}
NZTA_SITES = "https://services.arcgis.com/CXBb7LAjgIIdcsPt/arcgis/rest/services/Assets_SHTrafficMonitoringSites/FeatureServer/0/query"
NZTA_COUNTS = "https://services.arcgis.com/CXBb7LAjgIIdcsPt/ArcGIS/rest/services/TMS_Telemetry_Sites/FeatureServer/0/query"
WEBTRIS = "https://webtris.nationalhighways.co.uk/api/v1.0"
NSW = "https://api.transport.nsw.gov.au/v1/roads/spatial"
TOMTOM = "https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png"
DAY = 86400
FETCH_EVERY = 7 * DAY
FIRST_DAYS = 400          # days of NZ counts fetched the first time
WEBTRIS_SITES = 300
WEBTRIS_FIRST_DAYS = 120
KEEP_DAYS = 800
PAGE = 2000
SOURCES = {
    "nzta": {"name": "NZTA state highway counts", "country": "NZL", "hourly": False,
             "link": "https://www.nzta.govt.nz/resources/state-highway-traffic-volumes"},
    "webtris": {"name": "National Highways WebTRIS", "country": "GBR", "hourly": True, "link": "https://webtris.nationalhighways.co.uk/"},
    "nsw": {"name": "Transport for NSW traffic counts", "country": "AUS", "hourly": True,
            "link": "https://opendata.transport.nsw.gov.au/dataset/nsw-roads-traffic-volume-counts-api"},
}

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def root() -> Path:
    p = local.home() / "congestion" / "roads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(name: str, default):
    path = root() / name
    try:
        mt = path.stat().st_mtime
    except OSError:
        return default
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] == mt:
            return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    with _lock:
        _cache[name] = (mt, data)
    return data


def _write(name: str, data) -> None:
    path = root() / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# ----------------------------------------------------------------------------- New Zealand
def nzta_sites(features: list[dict]) -> dict[str, dict]:
    out = {}
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        ref = str(a.get("siteref") or "").strip()
        if not ref or g.get("x") is None:
            continue
        aadt = [a.get(k) for k in ("aadt5yearsago", "aadt4yearsago", "aadt3yearsago", "aadt2yearsago", "aadt1yearago")]
        out[ref] = {"name": f"SH{a.get('sh')} {a.get('description') or ''}".strip(), "region": a.get("region"),
                    "lon": round(g["x"], 5), "lat": round(g["y"], 5), "kind": a.get("sitetype"),
                    "heavy_pct": a.get("percentheavy"), "aadt": aadt}
    return out


def nzta_counts(features: list[dict], into: dict[str, dict[str, float]]) -> int:
    """ArcGIS statistics rows {SiteRef, startDate (ms), vehicles} into {site: {day: vehicles}}."""
    n = 0
    for f in features:
        a = f.get("attributes") or {}
        ref, ms, v = a.get("SiteRef"), a.get("startDate"), a.get("vehicles")
        if not ref or ms is None or v is None:
            continue
        day = datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()
        into.setdefault(str(ref), {})[day] = float(v)
        n += 1
    return n


def fetch_nzta(client: httpx.Client, today: date) -> int:
    sites, feats, offset = {}, [], 0
    while True:
        r = client.get(NZTA_SITES, params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "json",
                                            "resultOffset": offset, "resultRecordCount": PAGE})
        r.raise_for_status()
        got = r.json().get("features") or []
        feats += got
        if len(got) < PAGE:
            break
        offset += PAGE
    sites = nzta_sites(feats)
    if sites:
        _write("nzta_sites.json", sites)
    counts = _read("nzta_counts.json", {})
    last = max((d for v in counts.values() for d in v), default=None)
    start = (date.fromisoformat(last) - timedelta(days=21)) if last else today - timedelta(days=FIRST_DAYS)
    n = 0
    stats = json.dumps([{"statisticType": "sum", "onStatisticField": "trafficCount", "outStatisticFieldName": "vehicles"}])
    while start <= today:
        end = min(today, start + timedelta(days=30))
        offset = 0
        while True:
            r = client.get(NZTA_COUNTS, params={
                "where": f"startDate >= DATE '{start.isoformat()}' AND startDate < DATE '{(end + timedelta(days=1)).isoformat()}'",
                "groupByFieldsForStatistics": "SiteRef,startDate", "outStatistics": stats, "f": "json",
                "resultOffset": offset, "resultRecordCount": PAGE, "orderByFields": "SiteRef,startDate"})
            r.raise_for_status()
            got = r.json().get("features") or []
            n += nzta_counts(got, counts)
            if len(got) < PAGE:
                break
            offset += PAGE
            time.sleep(0.5)
        start = end + timedelta(days=1)
    _trim(counts, today)
    _write("nzta_counts.json", counts)
    return n


# ----------------------------------------------------------------------------- England
def webtris_pick(sites: list[dict], n: int = WEBTRIS_SITES) -> list[dict]:
    """Active motorway and A-road sites, one per small square, spread over the network."""
    ok = [s for s in sites if s.get("Status") == "Active" and s.get("Longitude") is not None and str(s.get("Name") or "")[:1] in "MA"]
    for size in (0.1, 0.15, 0.2, 0.3, 0.45, 0.7, 1.0):
        cells: dict[tuple[int, int], dict] = {}
        for s in sorted(ok, key=lambda s: int(s["Id"]) if str(s["Id"]).isdigit() else 0):
            cells.setdefault((int(s["Longitude"] // size), int(s["Latitude"] // size)), s)
        if len(cells) <= n:
            return list(cells.values())
    return list(cells.values())[:n]


def webtris_rows(rows: list[dict], into: dict[str, dict]) -> int:
    """WebTRIS 15-minute rows as {day: {"v": [24 vehicles], "mph": [24]}}."""
    n = 0
    acc: dict[str, dict[int, list[float]]] = {}
    for r in rows:
        day = str(r.get("Report Date") or "")[:10]
        t = str(r.get("Time Period Ending") or "")
        try:
            h = int(t[:2])
            m = int(t[3:5])
        except ValueError:
            continue
        h = h if m > 0 else (h - 1) % 24  # "01:00" ends the 00:45-01:00 quarter
        try:
            v = float(r.get("Total Volume") or 0)
        except ValueError:
            continue
        try:
            mph = float(r.get("Avg mph") or "nan")
        except ValueError:
            mph = float("nan")
        a = acc.setdefault(day, {}).setdefault(h, [0.0, 0.0, 0.0])
        a[0] += v
        if mph == mph:
            a[1] += mph * v
            a[2] += v
        n += 1
    for day, hours in acc.items():
        into[day] = {"v": [round(hours.get(h, [0])[0]) if h in hours else None for h in range(24)],
                     "mph": [round(hours[h][1] / hours[h][2], 1) if h in hours and hours[h][2] else None for h in range(24)]}
    return n


def fetch_webtris(client: httpx.Client, today: date) -> int:
    r = client.get(f"{WEBTRIS}/sites")
    r.raise_for_status()
    all_sites = r.json().get("sites") or []
    picked = webtris_pick(all_sites)
    sites = {str(s["Id"]): {"name": s.get("Name"), "description": s.get("Description"), "lon": round(s["Longitude"], 5),
                            "lat": round(s["Latitude"], 5)} for s in picked}
    _write("webtris_sites.json", sites)
    data = _read("webtris_hours.json", {})
    n = 0
    for sid in sites:
        got = data.setdefault(sid, {})
        last = max(got, default=None)
        start = date.fromisoformat(last) + timedelta(days=1) if last else today - timedelta(days=WEBTRIS_FIRST_DAYS)
        while start <= today:
            end = min(today, start + timedelta(days=30))
            rows, page = [], 1
            while True:
                rr = client.get(f"{WEBTRIS}/reports/Daily", params={"sites": sid, "start_date": start.strftime("%d%m%Y"),
                                                                   "end_date": end.strftime("%d%m%Y"), "page": page, "page_size": 10000})
                if rr.status_code == 204:
                    break
                rr.raise_for_status()
                body = rr.json()
                rows += body.get("Rows") or []
                if not any(l.get("rel") == "nextPage" for l in (body.get("Header") or {}).get("links") or []):
                    break
                page += 1
            n += webtris_rows(rows, got)
            start = end + timedelta(days=1)
            time.sleep(0.3)
    for sid in list(data):
        if sid not in sites:
            del data[sid]
    _trim(data, today)
    _write("webtris_hours.json", data)
    return n


# ----------------------------------------------------------------------------- New South Wales
def _nsw_query(client: httpx.Client, key: str, sql: str) -> list[dict]:
    r = client.get(NSW, params={"format": "geojson", "q": sql}, headers={"Authorization": f"apikey {key}"})
    r.raise_for_status()
    return [dict(f.get("properties") or {}, _geom=f.get("geometry")) for f in r.json().get("features") or []]


def nsw_hours(rows: list[dict], into: dict[str, dict]) -> int:
    """Hourly permanent count rows (station_key, date, hour_00 .. hour_23, all directions and
    classes) summed into {station: {day: {"v": [24]}}}."""
    n = 0
    for r in rows:
        st, day = str(r.get("station_key") or ""), str(r.get("date") or "")[:10]
        if not st or not day:
            continue
        cell = into.setdefault(st, {}).setdefault(day, {"v": [0] * 24})
        for h in range(24):
            v = r.get(f"hour_{h:02d}")
            if v not in (None, ""):
                try:
                    cell["v"][h] = (cell["v"][h] or 0) + round(float(v))
                except ValueError:
                    pass
        n += 1
    return n


def fetch_nsw(client: httpx.Client, today: date) -> int:
    key = os.environ.get("TFNSW_API_KEY", "").strip()
    if not key:
        return 0
    stations = {}
    for p in _nsw_query(client, key, "select * from road_traffic_counts_station_reference"):
        if str(p.get("permanent_station", "true")).lower() not in ("true", "1", "yes", "t"):
            continue
        lat, lon = p.get("wgs84_latitude"), p.get("wgs84_longitude")
        if lat is None and p.get("_geom"):
            lon, lat = (p["_geom"].get("coordinates") or [None, None])[:2]
        if lat is None or lon is None:
            continue
        stations[str(p.get("station_key"))] = {"name": " ".join(str(p.get(k) or "") for k in ("road_name", "suburb")).strip() or p.get("name"),
                                               "lon": round(float(lon), 5), "lat": round(float(lat), 5)}
    if stations:
        _write("nsw_sites.json", stations)
    data = _read("nsw_hours.json", {})
    last = max((d for v in data.values() for d in v), default=None)
    start = date.fromisoformat(last) - timedelta(days=7) if last else today - timedelta(days=120)
    n = 0
    while start <= today:
        end = min(today, start + timedelta(days=14))
        n += nsw_hours(_nsw_query(client, key, f"select * from road_traffic_counts_hourly_permanent where date >= '{start}' and date <= '{end}'"), data)
        start = end + timedelta(days=1)
        time.sleep(1)
    _trim(data, today)
    _write("nsw_hours.json", data)
    return n


def _trim(data: dict, today: date) -> None:
    cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
    for v in data.values():
        for d in [d for d in v if d < cut]:
            del v[d]


# ----------------------------------------------------------------------------- collector
class Collector:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.busy = False

    def status(self) -> dict:
        st = _read("status.json", {})
        return dict(st, busy=self.busy)

    def start(self, settings_fn) -> None:
        if self.thread and self.thread.is_alive():
            return

        def run():
            time.sleep(180)
            while True:
                s = settings_fn() or {}
                if s.get("road_counts_fetch", True) and time.time() - float(self.status().get("at") or 0) > FETCH_EVERY:
                    self.run_once()
                time.sleep(6 * 3600)

        self.thread = threading.Thread(target=run, daemon=True, name="road-counts")
        self.thread.start()

    def run_once(self, client: httpx.Client | None = None, today: date | None = None) -> dict:
        today = today or datetime.now(UTC).date()
        self.busy = True
        own = client is None
        client = client or httpx.Client(timeout=120, headers=UA, follow_redirects=True)
        out: dict = {"at": time.time(), "errors": {}}
        try:
            for sid, fn in (("nzta", fetch_nzta), ("webtris", fetch_webtris), ("nsw", fetch_nsw)):
                try:
                    out[sid] = fn(client, today)
                except Exception as exc:  # noqa: BLE001 - the others still run
                    log.warning("road counts %s: %s", sid, exc)
                    out["errors"][sid] = str(exc)[:300]
        finally:
            self.busy = False
            if own:
                client.close()
        _write("status.json", out)
        return out


COLLECTOR = Collector()


# ----------------------------------------------------------------------------- reading
def _daily(source: str, days: dict) -> dict[str, float]:
    """{day: vehicles} for any source."""
    if source == "nzta":
        return {d: v for d, v in days.items()}
    return {d: sum(x for x in c.get("v") or [] if x) for d, c in days.items() if any(c.get("v") or [])}


def vs_normal(daily: dict[str, float]) -> tuple[float | None, float | None]:
    """The last 7 days' average against the same weekdays of the 8 weeks before (per cent)."""
    keys = sorted(daily)
    if not keys:
        return None, None
    last = date.fromisoformat(keys[-1])
    recent = [daily[d] for d in keys if (last - date.fromisoformat(d)).days < 7]
    before = [daily[d] for d in keys if 7 <= (last - date.fromisoformat(d)).days < 63]
    now = mean(recent) if recent else None
    if not now or len(before) < 14:
        return now, None
    return now, round(100 * (now / mean(before) - 1), 1)


def _sources() -> dict[str, tuple[dict, dict]]:
    return {"nzta": (_read("nzta_sites.json", {}), _read("nzta_counts.json", {})),
            "webtris": (_read("webtris_sites.json", {}), _read("webtris_hours.json", {})),
            "nsw": (_read("nsw_sites.json", {}), _read("nsw_hours.json", {}))}


def sites_geojson(west: float = -180, south: float = -90, east: float = 180, north: float = 90) -> dict:
    feats = []
    for src, (sites, data) in _sources().items():
        for sid, s in sites.items():
            lon, lat = s["lon"], s["lat"]
            if not (south <= lat <= north and (west <= lon <= east if west <= east else lon >= west or lon <= east)):
                continue
            daily = _daily(src, data.get(sid) or {})
            now, vs = vs_normal(daily)
            aadt = next((a for a in reversed(s.get("aadt") or []) if a), None)
            if now is None and not aadt:
                continue
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {"id": f"{src}:{sid}", "name": s.get("name"), "source": src, "source_name": SOURCES[src]["name"],
                                         "vehicles": round(now) if now else aadt, "vs_normal": vs,
                                         "latest": max(daily) if daily else None, "hourly": SOURCES[src]["hourly"]}})
    out = {"type": "FeatureCollection", "features": feats}
    if not feats:
        out["note"] = "No traffic counts kept yet: they are read once a week (Settings > Transport > Road traffic counts)."
    return out


def site(site_id: str) -> dict | None:
    src, _, sid = site_id.partition(":")
    if src not in SOURCES:
        return None
    sites, data = _sources()[src]
    s = sites.get(sid)
    if not s:
        return None
    days = data.get(sid) or {}
    daily = _daily(src, days)
    now, vs = vs_normal(daily)
    meta = SOURCES[src]
    out = {"id": site_id, **s, "source": src, "source_name": meta["name"], "link": meta["link"], "hourly": meta["hourly"],
           "country": meta["country"], "daily": [{"day": d, "vehicles": round(v)} for d, v in sorted(daily.items())],
           "vehicles_now": round(now) if now else None, "vs_normal": vs}
    if SOURCES[src]["hourly"]:
        keys = sorted(days)[-56:]

        def avg(sel, field="v"):
            group = [days[d][field] for d in keys if sel(date.fromisoformat(d)) and days[d].get(field)]
            return [round(mean(g[h] for g in group if g[h] is not None), 1) if any(g[h] is not None for g in group) else None
                    for h in range(24)] if group else [None] * 24

        out["hours"] = {"weekday": avg(lambda d: d.weekday() < 5), "weekend": avg(lambda d: d.weekday() >= 5),
                        "weekday_mph": avg(lambda d: d.weekday() < 5, "mph") if src == "webtris" else None,
                        "from": keys[0] if keys else None, "to": keys[-1] if keys else None}
    else:
        by_wd: dict[int, list[float]] = {}
        for d, v in daily.items():
            if (date.fromisoformat(max(daily)) - date.fromisoformat(d)).days < 91:
                by_wd.setdefault(date.fromisoformat(d).weekday(), []).append(v)
        out["weekdays"] = [round(mean(by_wd[i])) if by_wd.get(i) else None for i in range(7)]
    return out


# ----------------------------------------------------------------------------- TomTom tiles
def tomtom_tile(z: int, x: int, y: int) -> tuple[int, bytes, str]:
    """One live traffic flow tile from TomTom, passed straight through (not kept)."""
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if not key:
        return 404, b"", "text/plain"
    try:
        with httpx.Client(timeout=15, headers=UA) as c:
            r = c.get(TOMTOM.format(z=z, x=x, y=y), params={"key": key, "tileSize": 256})
        return r.status_code, r.content, r.headers.get("content-type", "image/png")
    except Exception:  # noqa: BLE001
        return 502, b"", "text/plain"


def quote_id(s: str) -> str:
    return quote(s, safe="")
