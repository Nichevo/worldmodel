"""Climate: the world's vital signs, one country's climate, El Niño and the other ocean
drivers, storms and alerts (the storms happening now come from GDACS when the page asks),
and climate policy. Each function takes `q`, the API's rows(sql, params) helper."""

from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict
from typing import Callable

from worldmodel_contract import catalogue

Q = Callable[[str, list], list[dict]]
SSPS = {"ssp126": "SSP1-2.6 (low emissions)", "ssp245": "SSP2-4.5 (middle)", "ssp370": "SSP3-7.0 (high)", "ssp585": "SSP5-8.5 (very high)"}
WORLD = ["temp_anomaly_world", "co2_ppm", "ch4_ppb", "n2o_ppb", "sea_level", "ocean_heat", "co2_gcp", "ghg_total_gcp"]
GASES = ["co2_gcp", "methane_emissions", "n2o_emissions"]
LIVE_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"
# NOAA's file of storms going on now (and in the last days), updated as the agencies report.
ACTIVE_URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
              "v04r01/access/csv/ibtracs.ACTIVE.list.v04r01.csv")
ACTIVE_DAYS = 4  # a storm counts as active if its last position is this recent
BASINS = {"NA": "North Atlantic", "EP": "Eastern Pacific", "WP": "Western Pacific", "NI": "North Indian", "SI": "South Indian",
          "SP": "South Pacific", "SA": "South Atlantic", "MM": "Mixed"}
_live: dict = {"at": 0.0, "data": None}
_active: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _notes() -> dict:
    try:
        return catalogue._yaml("climate.yaml").get("enso_notes", {})
    except Exception:  # noqa: BLE001 - the notes are extras
        return {}


def _series(q: Q, inds: list[str], entities: list[str], freq: str | None = "A", variants: tuple[str, ...] = ("central",)) -> dict:
    """indicator -> entity -> [[year or 'YYYY-MM', value, status, variant]], the best-ranked source each."""
    if not inds or not entities:
        return {}
    fq = "AND s.freq = ?" if freq else ""
    got = q(f"""
        SELECT s.indicator_id AS i, s.entity_id AS e, s.period_start AS d, s.freq AS f, s.value AS v, s.status AS st, s.variant AS va
        FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        WHERE s.indicator_id IN ({', '.join('?' for _ in inds)}) AND s.entity_id IN ({', '.join('?' for _ in entities)})
          AND s.breakdown = '' AND s.variant IN ({', '.join('?' for _ in variants)}) {fq}
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.entity_id, s.period_start, s.variant ORDER BY r.rank) = 1
        ORDER BY s.period_start""", list(inds) + list(entities) + list(variants) + ([freq] if freq else []))
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in got:
        when = r["d"].year if r["f"] == "A" else r["d"].strftime("%Y-%m")
        out[r["i"]][r["e"]].append([when, r["v"], r["st"], r["va"]])
    return out


def _meta(q: Q, inds: list[str]) -> dict:
    if not inds:
        return {}
    return {r["indicator_id"]: {"name": r["name"], "unit": r["unit"], "decimals": r["decimals"]}
            for r in q(f"SELECT indicator_id, name, unit, decimals FROM indicators WHERE indicator_id IN ({', '.join('?' for _ in inds)})", inds)}


def _have(q: Q, like: str) -> list[str]:
    return [r["indicator_id"] for r in q("SELECT indicator_id FROM indicators WHERE indicator_id LIKE ? ESCAPE '\\' ORDER BY indicator_id", [like])]


def phase(oni: float | None) -> dict | None:
    if oni is None:
        return None
    if oni >= 0.5:
        name = "El Niño"
    elif oni <= -0.5:
        name = "La Niña"
    else:
        name = "Neutral"
    a = abs(oni)
    strength = "" if name == "Neutral" else "very strong" if a >= 2 else "strong" if a >= 1.5 else "moderate" if a >= 1 else "weak"
    return {"name": name, "strength": strength, "value": oni}


def overview(q: Q) -> dict:
    """The world's vital signs: temperature, gases in the air, the sea, ice, emissions."""
    data = _series(q, WORLD, ["world"])
    monthly = _series(q, ["temp_anomaly_world_monthly", "co2_ppm_mlo", "enso_oni"], ["world"], "M")
    ice = _series(q, ["sea_ice_extent_min", "sea_ice_extent_max"], ["arctic", "antarctica", "world"])
    sheets = {r["e"]: r for r in q("SELECT DISTINCT entity_id AS e FROM series WHERE indicator_id = 'ice_sheet_mass'", [])}
    sheet = _series(q, ["ice_sheet_mass"], list(sheets))
    maps = ["co2_per_capita_gcp", "ghg_per_capita", "co2_consumption_per_capita", "co2_gcp", "ghg_total_gcp", "co2_share_world",
            "co2_share_cumulative", "warming_from_ghg", "temp_anomaly", "wildfire_area", "net_zero_year", "carbon_price"]
    names = _meta(q, WORLD + ["temp_anomaly_world_monthly", "co2_ppm_mlo", "sea_ice_extent_min", "ice_sheet_mass", "enso_oni"] + maps)
    oni = monthly.get("enso_oni", {}).get("world", [])
    return {
        "world": {i: [p[:2] for p in data[i]["world"]] for i in WORLD if data.get(i, {}).get("world")},
        "monthly": {i: [p[:2] for p in monthly[i]["world"]] for i in monthly if monthly[i].get("world")},
        "sea_ice": {f"{i}:{e}": [p[:2] for p in pts] for i, by in ice.items() for e, pts in by.items()},
        "ice_sheets": {e: [p[:2] for p in pts] for e, pts in sheet.get("ice_sheet_mass", {}).items()},
        "enso": phase(oni[-1][1]) | {"month": oni[-1][0]} if oni else None,
        "names": names,
        "emission_maps": [i for i in maps if i in names],
    }


def country(q: Q, entity: str) -> dict:
    temp_ids = ["temp_anomaly"] + (["nz_temp_anomaly_7station"] if entity == "NZL" else [])
    sector_ids = _have(q, "ghg\\_sector\\_%")
    nz_ids = _have(q, "nz\\_ghg\\_%") if entity == "NZL" else []
    proj_ids = [f"{p}_{s}" for p in ("proj_temp", "proj_rain") for s in SSPS]
    inds = temp_ids + GASES + sector_ids + nz_ids + ["co2_consumption", "co2_per_capita_gcp", "co2_consumption_per_capita", "ghg_per_capita",
                                                     "ghg_total_gcp", "net_zero_year", "net_zero_status", "carbon_price", "wildfire_area"]
    data = _series(q, inds, [entity])
    proj = _series(q, proj_ids, [entity], "A", ("central", "lower80", "upper80"))
    meta = _meta(q, inds + proj_ids)
    pick = lambda i: [p[:2] for p in data.get(i, {}).get(entity, [])]  # noqa: E731
    projections = {}
    for i in proj_ids:
        pts = proj.get(i, {}).get(entity, [])
        if pts:
            by: dict = defaultdict(dict)
            for y, v, _, va in pts:
                by[y][va] = v
            projections[i] = [[y, d.get("central"), d.get("lower80"), d.get("upper80")] for y, d in sorted(by.items())]
    disasters = q("""SELECT kind, subkind, title, start_date, deaths, affected, damage_usd, source_id FROM events
                     WHERE entity_id = ? AND kind = 'disaster' ORDER BY coalesce(deaths, 0) DESC, coalesce(damage_usd, 0) DESC LIMIT 12""", [entity])
    nz = data.get("net_zero_year", {}).get(entity)
    status = data.get("net_zero_status", {}).get(entity)
    return {
        "entity": entity,
        "temperature": {i: pick(i) for i in temp_ids if pick(i)},
        "gases": {i: pick(i) for i in GASES if pick(i)},
        "sectors": {i: pick(i) for i in (sector_ids + nz_ids) if pick(i)},
        "consumption": {i: pick(i) for i in ("co2_gcp", "co2_consumption", "co2_per_capita_gcp", "co2_consumption_per_capita", "ghg_per_capita", "ghg_total_gcp") if pick(i)},
        "net_zero": {"year": nz[-1][1], "status": status[-1][1] if status else None} if nz else None,
        "carbon_price": pick("carbon_price"),
        "wildfire_area": pick("wildfire_area"),
        "projections": projections,
        "disasters": [{**d, "start_date": d["start_date"].isoformat()} for d in disasters],
        "enso": {**(_notes().get(entity) or {}), **(_enso_link(q, [entity]).get(entity) or {})} or None,
        "names": meta,
    }


def _yearly_oni(q: Q) -> dict[int, float]:
    pts = _series(q, ["enso_oni"], ["world"], "M").get("enso_oni", {}).get("world", [])
    by: dict = defaultdict(list)
    for when, v, *_ in pts:
        by[int(when[:4])].append(v)
    return {y: sum(v) / len(v) for y, v in by.items() if len(v) >= 9}


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 15:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2) if sx and sy else None


def _enso_link(q: Q, entities: list[str] | None = None) -> dict:
    """How each country's yearly temperature (after taking out its warming trend) has moved
    with the year's average El Niño index: a correlation from -1 to 1."""
    oni = _yearly_oni(q)
    if not oni:
        return {}
    where = "" if entities is None else f"AND s.entity_id IN ({', '.join('?' for _ in entities)})"
    got = q(f"""SELECT s.entity_id AS e, year(s.period_start) AS y, s.value AS v FROM series s
                JOIN entities en ON en.entity_id = s.entity_id
                WHERE s.indicator_id = 'temp_anomaly' AND s.freq = 'A' AND s.breakdown = '' AND s.variant = 'central'
                  AND en.type = 'country' {where}""", list(entities or []))
    by: dict = defaultdict(list)
    for r in got:
        if r["y"] in oni:
            by[r["e"]].append((r["y"], r["v"]))
    out = {}
    for e, pts in by.items():
        if len(pts) < 15:
            continue
        ys = [p[0] for p in pts]
        my = sum(ys) / len(ys)
        vs = [p[1] for p in pts]
        mv = sum(vs) / len(vs)
        den = sum((y - my) ** 2 for y in ys)
        slope = sum((y - my) * (v - mv) for y, v in pts) / den if den else 0
        resid = [v - (mv + slope * (y - my)) for y, v in pts]
        r = _corr([oni[y] for y in ys], resid)
        if r is not None:
            out[e] = {"temp_r": r, "years": len(pts)}
    return out


def enso(q: Q) -> dict:
    data = _series(q, ["enso_oni", "iod_dmi", "sam_index"], ["world"], "M")
    episodes = q("""SELECT subkind, title, start_date, end_date, size FROM events WHERE kind = 'enso' ORDER BY start_date""", [])
    names = {r["entity_id"]: r["short_name"] or r["name"] for r in q("SELECT entity_id, name, short_name FROM entities", [])}
    link = _enso_link(q)
    notes = _notes()
    oni = data.get("enso_oni", {}).get("world", [])
    table = sorted(({"entity_id": e, "name": names.get(e, e), **v, "note": bool(notes.get(e))} for e, v in link.items()),
                   key=lambda r: -abs(r["temp_r"]))
    return {"series": {i: [p[:2] for p in data[i]["world"]] for i in data if data[i].get("world")},
            "phase": phase(oni[-1][1]) | {"month": oni[-1][0]} if oni else None,
            "episodes": [{**e, "start_date": e["start_date"].isoformat(), "end_date": e["end_date"].isoformat() if e["end_date"] else None} for e in episodes],
            "notes": {e: {**n, "name": names.get(e, e)} for e, n in notes.items()}, "link": table}


def storms(q: Q) -> dict:
    """Storm counts by year and basin from the storm tracks layer, for the chart beside the map."""
    got = q("SELECT geojson FROM layers WHERE layer_id = 'storm_tracks'", [])
    if not got:
        return {"years": [], "basins": [], "counts": [], "strong": []}
    feats = json.loads(got[0]["geojson"]).get("features", [])
    counts: dict = defaultdict(lambda: defaultdict(int))
    strong: dict = defaultdict(int)
    strong_by: dict = defaultdict(lambda: defaultdict(int))
    for f in feats:
        p = f.get("properties") or {}
        counts[p.get("year")][p.get("basin")] += 1
        if (p.get("cat") or 0) >= 3:
            strong[p.get("year")] += 1
            strong_by[p.get("year")][p.get("basin")] += 1
    years = sorted(y for y in counts if y)
    basins = sorted({b for y in counts.values() for b in y if b})
    return {"years": years, "basins": basins, "counts": [[counts[y].get(b, 0) for b in basins] for y in years],
            "strong": [strong.get(y, 0) for y in years], "strong_by": [[strong_by[y].get(b, 0) for b in basins] for y in years],
            "total": len(feats)}


def live(enabled: bool) -> dict:
    """What GDACS lists as happening now (cyclones, floods, droughts, fires, quakes), kept 15 minutes."""
    if not enabled:
        return {"off": True, "rows": []}
    with _lock:
        if _live["data"] is not None and time.time() - _live["at"] < 900:
            return _live["data"]
    import httpx
    try:
        r = httpx.get(LIVE_URL, timeout=httpx.Timeout(20, connect=5), follow_redirects=True)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as exc:  # noqa: BLE001 - the page says why
        return {"error": f"GDACS did not answer ({type(exc).__name__}); the map shows stored data only.", "rows": []}
    rows = []
    for f in feats:
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        if g.get("type") != "Point" or not g.get("coordinates"):
            continue
        rows.append({"id": f"{p.get('eventtype')}{p.get('eventid')}", "type": p.get("eventtype"), "name": p.get("name") or p.get("eventname"),
                     "alert": (p.get("alertlevel") or "").lower(), "country": p.get("country"), "from": p.get("fromdate"),
                     "lon": g["coordinates"][0], "lat": g["coordinates"][1], "url": (p.get("url") or {}).get("report")})
    out = {"rows": rows, "fetched": time.strftime("%Y-%m-%d %H:%M")}
    with _lock:
        _live.update(at=time.time(), data=out)
    return out


def active_storms(enabled: bool, fetch: Callable[[], str] | None = None) -> dict:
    """Tropical storms going on now as GeoJSON lines (NOAA IBTrACS, kept an hour). On a failure the
    collection is empty and says why, so the map still draws."""
    empty = {"type": "FeatureCollection", "features": []}
    if not enabled:
        return {**empty, "note": "Live storm data is off (Settings: Climate)."}
    with _lock:
        if _active["data"] is not None and time.time() - _active["at"] < 3600:
            return _active["data"]
    try:
        text = fetch() if fetch else _get_text(ACTIVE_URL)
    except Exception as exc:  # noqa: BLE001 - the map says why
        return {**empty, "note": f"NOAA did not answer ({type(exc).__name__}); try again later."}
    out = {"type": "FeatureCollection", "features": active_features(text, time.time()), "fetched": time.strftime("%Y-%m-%d %H:%M")}
    with _lock:
        _active.update(at=time.time(), data=out)
    return out


def _get_text(url: str) -> str:
    import httpx
    r = httpx.get(url, timeout=httpx.Timeout(30, connect=5), follow_redirects=True)
    r.raise_for_status()
    return r.text


def active_features(text: str, now: float) -> list[dict]:
    """One line per storm whose last position is within ACTIVE_DAYS of now: name, basin, the
    strongest category so far (0 = tropical storm), highest wind in knots, last position time."""
    import csv
    import io
    from datetime import datetime, timezone
    rows = csv.reader(io.StringIO(text))
    head = [c.strip().lower() for c in next(rows, [])]
    col = {c: i for i, c in enumerate(head)}
    if not all(c in col for c in ("sid", "basin", "name", "iso_time", "lat", "lon")):
        return []

    def num(v: str) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    tracks: dict[str, dict] = {}
    for r in rows:
        if len(r) < len(head):
            continue
        try:
            t = datetime.strptime(r[col["iso_time"]].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue  # the units row under the header
        lat, lon = num(r[col["lat"]]), num(r[col["lon"]])
        if lat is None or lon is None:
            continue
        s = tracks.setdefault(r[col["sid"]], {"name": r[col["name"]].strip().title(), "basin": r[col["basin"]].strip() or "NA",
                                              "pts": [], "cat": -9, "wind": 0.0, "last": t})
        if s["pts"] and abs(lon - s["pts"][-1][0]) > 180:  # keep the line continuous across 180°
            lon += 360 if lon < s["pts"][-1][0] else -360
        s["pts"].append([lon, lat])
        s["last"] = max(s["last"], t)
        cat = num(r[col["usa_sshs"]]) if "usa_sshs" in col else None
        wind = num(r[col["usa_wind"]]) if "usa_wind" in col else None
        if wind is None and "wmo_wind" in col:
            wind = num(r[col["wmo_wind"]])
        if cat is not None and cat > s["cat"]:
            s["cat"] = int(cat)
        if wind and wind > s["wind"]:
            s["wind"] = wind
    out = []
    for sid, s in tracks.items():
        if now - s["last"].timestamp() > ACTIVE_DAYS * 86400 or not s["pts"]:
            continue
        pts = s["pts"] if len(s["pts"]) > 1 else s["pts"] * 2  # a storm just named: a dot-length line
        name = "Unnamed" if s["name"] in ("", "Not_Named", "Unnamed") else s["name"]
        out.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": pts},
                    "properties": {"name": name, "basin": BASINS.get(s["basin"], s["basin"]), "cat": max(s["cat"], 0),
                                   "wind": int(s["wind"]) or None, "last": s["last"].strftime("%Y-%m-%d %H:%M"), "sid": sid}})
    return out


def policy(q: Q) -> dict:
    names = {r["entity_id"]: r["short_name"] or r["name"] for r in q("SELECT entity_id, name, short_name FROM entities", [])}
    latest = q("""SELECT indicator_id AS i, entity_id AS e, value AS v, year(period_start) AS y FROM series
                  WHERE indicator_id IN ('net_zero_year', 'net_zero_status', 'carbon_price', 'ghg_per_capita', 'co2_share_world')
                    AND breakdown = '' AND variant = 'central'
                  QUALIFY row_number() OVER (PARTITION BY indicator_id, entity_id ORDER BY period_start DESC) = 1""", [])
    by: dict = defaultdict(dict)
    for r in latest:
        by[r["e"]][r["i"]] = r["v"]
        if r["i"] == "carbon_price":
            by[r["e"]]["carbon_price_year"] = r["y"]
    paris = {r["e"]: r["d"].isoformat() for r in q("""SELECT entity_id AS e, min(start_date) AS d FROM events
             WHERE kind = 'treaty' AND title ILIKE '%Paris Agreement%' GROUP BY 1""", [])}
    rows = [{"entity_id": e, "name": names.get(e, e), **v, "paris": paris.get(e)} for e, v in by.items()
            if "net_zero_year" in v or "carbon_price" in v]
    rows.sort(key=lambda r: -(r.get("co2_share_world") or 0))
    return {"rows": rows, "paris_count": len(paris)}
