"""Land, cities and trees: the Land page, the city figures and outlines, New Zealand's land
cover, council trees and each sector's Land card. Each function takes `q`, the API's
rows(sql, params) helper.

City land cover is worked out here, on request, from the ESA WorldCover map pictures (the
"landcover" tile set): each pixel inside the city's GHSL outline is matched to the nearest
WorldCover colour, at zoom 12 (about 30 m a pixel in Auckland). Results are kept in
<data folder>/land/city_cover.json so a city is worked out once.
"""

from __future__ import annotations

import io
import json
import logging
import math
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from worldmodel_contract import local
from worldmodel_contract.land import (COMPARE, LAND_CARDS, LCDB_CLASSES, LCDB_LEVELS, TREES_PER_HA_CANOPY,
                                      WHERE_LAND_GOES, WORLDCOVER, lcdb_level)

from worldmodel_api import tiles
from worldmodel_api.climate import _series
from worldmodel_api.nature import _meta, _present

log = logging.getLogger(__name__)
Q = Callable[[str, list], list[dict]]

FAO = ["land_area_ha", "land_agri_ha", "land_cropland_ha", "land_arable_ha", "land_permanent_crops_ha", "land_pasture_ha",
       "land_forest_ha", "land_natural_forest_ha", "land_planted_forest_ha"]
HYDE = ["hyde_cropland_ha", "hyde_grazing_ha", "hyde_builtup_ha"]
TREES = ["gfw_tree_cover_ha", "gfw_tree_cover_pct", "gfw_tree_cover_loss_ha"]
CLIMATE = ["temp_anomaly", "wildfire_area", "ghg_total_gcp", "co2_gcp", "methane_emissions", "ghg_sector_lulucf",
           "ghg_sector_agriculture", "land_use_change_co2", "owid_co2_land_use_change_co2"]
CITY_ZOOM = 12


def _has(q: Q, table: str) -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]))


def _pts(data: dict, ind: str, ent: str) -> list:
    return [[p[0], p[1]] for p in data.get(ind, {}).get(ent, [])]


def _world(q: Q, ids: list[str]) -> dict:
    """indicator -> [[year, sum over countries]] for indicators with no world total of their own."""
    if not ids:
        return {}
    got = q(f"""SELECT s.indicator_id AS i, year(s.period_start) AS y, sum(s.value) AS v, count(*) AS n
                FROM series s JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
                WHERE s.indicator_id IN ({', '.join('?' * len(ids))}) AND s.breakdown = '' AND s.variant = 'central'
                GROUP BY 1, 2 HAVING count(*) >= 20 ORDER BY 2""", ids)
    out: dict = defaultdict(list)
    for r in got:
        out[r["i"]].append([r["y"], r["v"]])
    return out


# ----------------------------------------------------------------------------- the Land page
def overview(q: Q, entity: str = "world") -> dict:
    """Land use for a country or the world: FAOSTAT since 1961, HYDE back to 1700 (modelled
    before 1961, drawn dashed), tree cover and loss, and people (for per person)."""
    ids = _present(q, FAO + HYDE + TREES + ["pop_total"])
    if entity == "world":
        data = _series(q, ids, ["world"])
        series = {i: _pts(data, i, "world") for i in ids}
        missing = [i for i in ids if not series[i] and i not in ("gfw_tree_cover_pct",)]
        for i, pts in _world(q, missing).items():
            series[i] = pts
    else:
        data = _series(q, ids, [entity])
        series = {i: _pts(data, i, entity) for i in ids}
    return {"entity": entity, "series": {i: p for i, p in series.items() if p}, "names": _meta(q, ids),
            "modelled_before": 1961, "hyde": [i for i in HYDE if i in ids]}


def ranking(q: Q, indicator: str = "land_forest_ha", start: int = 1990, end: int | None = None, per: str = "change") -> dict:
    """Countries by change in a land figure between two years: hectares and per cent."""
    if indicator not in FAO + TREES + HYDE:
        raise ValueError("not a land figure")
    got = q("""SELECT s.entity_id AS e, coalesce(n.short_name, n.name) AS name, year(s.period_start) AS y, s.value AS v
               FROM series s JOIN entities n ON n.entity_id = s.entity_id AND n.type = 'country'
               WHERE s.indicator_id = ? AND s.breakdown = '' AND s.variant = 'central'""", [indicator])
    by: dict = defaultdict(dict)
    names = {}
    for r in got:
        by[r["e"]][r["y"]] = r["v"]
        names[r["e"]] = r["name"]
    last = end or max((max(v) for v in by.values() if v), default=start)
    rows = []
    for e, ys in by.items():
        a = ys.get(start) if start in ys else ys.get(min(ys, key=lambda y: abs(y - start))) if ys else None
        b = ys.get(last)
        if a is None or b is None:
            continue
        rows.append({"entity_id": e, "name": names[e], "from": a, "to": b, "change": b - a,
                     "pct": (b / a - 1) * 100 if a else None})
    key = "pct" if per == "pct" else "change"
    rows.sort(key=lambda r: (r[key] is None, -(r[key] or 0)))
    return {"indicator": indicator, "start": start, "end": last, "rows": rows}


def where(q: Q, year: int | None = None) -> dict:
    """Where the land goes: Earth's surface down to farmland for crops and for grazing, for a
    year of FAOSTAT's world totals."""
    ids = _present(q, ["land_area_ha", "land_agri_ha", "land_cropland_ha", "land_pasture_ha", "land_forest_ha"])
    data = _series(q, ids, ["world"])
    series = {i: dict((y, v) for y, v in _pts(data, i, "world")) for i in ids}
    if not any(series.values()):
        series = {i: dict(map(tuple, pts)) for i, pts in _world(q, ids).items()}
    years = sorted(set.intersection(*(set(v) for v in series.values() if v)) if any(series.values()) else set())
    y = year if year in years else (years[-1] if years else None)
    w = WHERE_LAND_GOES
    surface = w["surface_km2"] * 100
    land = surface * (1 - w["ocean_share"])
    habitable = land * (1 - w["glacier_share_of_land"] - w["barren_share_of_land"])
    got = {i: series.get(i, {}).get(y) for i in ids} if y else {}
    return {"year": y, "years": years, "surface_ha": surface, "land_ha": land, "habitable_ha": habitable,
            "agri_ha": got.get("land_agri_ha"), "cropland_ha": got.get("land_cropland_ha"),
            "pasture_ha": got.get("land_pasture_ha"), "forest_ha": got.get("land_forest_ha"),
            "livestock_calories_share": w["livestock_calories_share"], "livestock_protein_share": w["livestock_protein_share"],
            "about": w["about"]}


def against_climate(q: Q, entity: str) -> dict:
    """Land beside climate for one country: forest, farmland and tree cover lost, against
    temperature, area burned and emissions (from land use and farming where known)."""
    ids = _present(q, ["land_forest_ha", "land_agri_ha", "land_pasture_ha", "gfw_tree_cover_loss_ha"] + CLIMATE)
    data = _series(q, ids, [entity])
    return {"entity": entity, "series": {i: _pts(data, i, entity) for i in ids if _pts(data, i, entity)},
            "names": _meta(q, ids)}


# ----------------------------------------------------------------------------- sector Land cards
def card(q: Q, sector: str, entities: list[str] | None = None) -> dict | None:
    """A sector's Land card: land used against output, how intensive it is, comparisons, and
    New Zealand by region where Stats NZ gives it."""
    spec = LAND_CARDS.get(sector)
    if not spec:
        return None
    ents = entities or COMPARE
    ids = {spec["land"], spec["output"]}
    for _, a, b, *_ in spec["ratios"]:
        ids |= {a} | ({b} if b else set())
    ids = _present(q, sorted(ids))
    data = _series(q, ids, ents)
    ratios = []
    for label, a, b, unit, scale in spec["ratios"]:
        if a not in ids or (b and b not in ids):
            continue
        by = {}
        for e in ents:
            top = dict((y, v) for y, v in _pts(data, a, e))
            if b:
                bottom = dict((y, v) for y, v in _pts(data, b, e))
                pts = [[y, top[y] * scale / bottom[y]] for y in sorted(top) if bottom.get(y)]
            else:
                pts = [[y, v * scale] for y, v in sorted(top.items())]
            if pts:
                by[e] = pts
        if by:
            ratios.append({"label": label, "unit": unit, "by": by})
    regions = None
    if spec.get("nz_regions"):
        ind = spec["nz_regions"]
        got = q("""SELECT s.entity_id AS e, coalesce(n.short_name, n.name) AS name, year(s.period_start) AS y, s.value AS v
                   FROM series s JOIN entities n ON n.entity_id = s.entity_id
                   WHERE s.indicator_id = ? AND s.entity_id LIKE 'NZ-%' AND s.breakdown = '' AND s.variant = 'central'
                   QUALIFY row_number() OVER (PARTITION BY s.entity_id ORDER BY s.period_start DESC) = 1
                   ORDER BY v DESC""", [ind])
        if got:
            regions = {"label": spec["nz_regions_label"], "rows": got}
    names = {r["entity_id"]: r["short_name"] or r["name"] for r in q(
        f"SELECT entity_id, name, short_name FROM entities WHERE entity_id IN ({', '.join('?' * len(ents))})", ents)}
    return {"sector": sector, "land": {"id": spec["land"], "label": spec["land_label"],
                                       "by": {e: _pts(data, spec["land"], e) for e in ents if _pts(data, spec["land"], e)}},
            "output": {"id": spec["output"], "label": spec["output_label"],
                       "by": {e: _pts(data, spec["output"], e) for e in ents if _pts(data, spec["output"], e)}},
            "ratios": ratios, "regions": regions, "entities": ents, "names": names, "units": _meta(q, ids)}


# ----------------------------------------------------------------------------- cities (GHSL)
def _centre(row: dict) -> dict:
    p = json.loads(row["props"] or "{}")
    pops = {int(y): v for y, v in (p.get("pop") or {}).items()}
    built = {int(y): v for y, v in (p.get("built") or {}).items()}
    now = p.get("now") or (max(pops) if pops else None)
    first = p.get("first") or (min(pops) if pops else None)
    b_now, b_first = built.get(now), built.get(first)
    return {"id": row["feature_id"], "name": row["name"], "country": p.get("country") or row.get("countries"),
            "people": pops.get(now), "people_first": pops.get(first), "now": now, "first": first,
            "built_km2": b_now, "built_first_km2": b_first, "growth": p.get("growth"),
            "built_growth": (b_now / b_first - 1) * 100 if b_now and b_first else None,
            "density": pops.get(now) / b_now if b_now and pops.get(now) else None,
            "area": p.get("area"), "lat": p.get("lat"), "lon": p.get("lon"),
            "pop": pops, "built": built}


def cities(q: Q, sort: str = "people", country: str | None = None, limit: int = 100, search: str | None = None) -> dict:
    """Urban centres ranked by people, built-up area, growth since 1975 or density."""
    if not _has(q, "geo_features"):
        return {"rows": [], "total": 0}
    where, params = "layer_id = 'urban_centres'", []
    if country:
        where += " AND countries = ?"
        params.append(country)
    if search:
        where += " AND lower(name) LIKE ?"
        params.append(f"%{search.lower()}%")
    got = q(f"SELECT feature_id, name, props, countries FROM geo_features WHERE {where}", params)
    rows = [_centre(r) for r in got]
    key = {"people": "people", "area": "built_km2", "growth": "growth", "built_growth": "built_growth",
           "density": "density"}.get(sort, "people")
    rows.sort(key=lambda r: (r[key] is None, -(r[key] or 0)))
    names = {r["entity_id"]: r["short_name"] or r["name"] for r in q("SELECT entity_id, name, short_name FROM entities", [])}
    cover = _cover_store()
    for r in rows:
        r["country_name"] = names.get(r["country"], r["country"])
        c = cover.get(r["id"])
        r["tree_pct"] = c.get("shares", {}).get("10") if c else None
        r.pop("pop")
        r.pop("built")
    return {"rows": rows[: int(limit)], "total": len(rows), "sort": key}


def outlines(q: Q, ids: list[str]) -> dict:
    """GeoJSON outlines of urban centres, each with its figures, for Compare cities."""
    if not ids or not _has(q, "geo_features"):
        return {"type": "FeatureCollection", "features": []}
    got = q(f"""SELECT feature_id, name, props, countries, geojson FROM geo_features
                WHERE layer_id = 'urban_centres' AND feature_id IN ({', '.join('?' * len(ids))})""", ids)
    feats = []
    order = {i: n for n, i in enumerate(ids)}
    for r in sorted(got, key=lambda r: order.get(r["feature_id"], 99)):
        c = _centre(r)
        feats.append({"type": "Feature", "geometry": json.loads(r["geojson"]), "properties": c})
    return {"type": "FeatureCollection", "features": feats}


def centre_for_city(q: Q, city_id: str) -> dict | None:
    """The GHSL urban centre a GeoNames city sits in (or the nearest, within 25 km)."""
    if not _has(q, "geo_features"):
        return None
    c = q("SELECT name, country_id, lat, lon FROM cities WHERE city_id = ?", [city_id])
    if not c or c[0]["lat"] is None:
        return None
    lat, lon = c[0]["lat"], c[0]["lon"]
    got = q("""SELECT feature_id, name, props, countries, geojson FROM geo_features
               WHERE layer_id = 'urban_centres' AND west <= ? + 0.25 AND east >= ? - 0.25 AND south <= ? + 0.25 AND north >= ? - 0.25""",
            [lon, lon, lat, lat])
    best, best_d = None, 1e9
    try:
        from shapely.geometry import Point, shape
    except ImportError:  # pragma: no cover
        shape = None
    for r in got:
        cen = _centre(r)
        if shape is not None and shape(json.loads(r["geojson"])).contains(Point(lon, lat)):
            best, best_d = r, 0
            break
        d = math.hypot((cen["lon"] or 0) - lon, ((cen["lat"] or 0) - lat)) * 111
        if d < best_d:
            best, best_d = r, d
    if best is None or best_d > 25:
        return None
    out = _centre(best)
    out["cover"] = _cover_store().get(out["id"])
    out["geometry"] = json.loads(best["geojson"])
    return out


# ----------------------------------------------------------------------------- city land cover from pictures
_cover_lock = threading.Lock()
_cover_job: dict = {"state": "idle"}
_cover_waiting: list[str] = []


def _cover_file():
    return local.home() / "land" / "city_cover.json"


def _cover_store() -> dict:
    try:
        return json.loads(_cover_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _palette():
    return [(int(code), tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))) for code, (_, c) in WORLDCOVER.items()]


def classify(img, mask) -> dict[int, int]:
    """Pixels of a WorldCover picture counted by class (nearest colour), where mask is true."""
    import numpy as np

    a = np.asarray(img.convert("RGBA"), dtype=np.int32)
    rgb, alpha = a[:, :, :3], a[:, :, 3]
    pal = _palette()
    cols = np.array([c for _, c in pal], dtype=np.int32)
    d = ((rgb[:, :, None, :] - cols[None, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1)
    ok = mask & (alpha > 0) & (d.min(-1) < 60 ** 2)
    out: dict[int, int] = {}
    for k, (code, _) in enumerate(pal):
        n = int(((idx == k) & ok).sum())
        if n:
            out[code] = n
    return out


def _tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2 ** z
    lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon0, lat0, lon1, lat1


def city_cover_compute(geometry: dict, year: str = "2021", zoom: int = CITY_ZOOM, fetch=None) -> dict:
    """Shares (%) of each WorldCover class inside an outline, from the land cover pictures."""
    import numpy as np
    from PIL import Image
    from shapely import contains_xy
    from shapely.geometry import shape

    geom = shape(geometry)
    w, s, e, n = geom.bounds
    counts: dict[int, int] = defaultdict(int)
    got = missing = 0
    fetch = fetch or (lambda z, x, y: tiles.tile("landcover", z, x, y, year))
    for x, y in tiles.tiles_in((w, s, e, n), zoom):
        t = fetch(zoom, x, y)
        if not t:
            missing += 1
            continue
        img = Image.open(io.BytesIO(t[0]))
        size = img.size[0]
        lon0, lat0, lon1, lat1 = _tile_bounds(zoom, x, y)
        px = (np.arange(size) + 0.5) / size
        lons = lon0 + px * (lon1 - lon0)
        # Mercator: rows are evenly spaced in y, not latitude
        ytile = y + px
        lats = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ytile / 2 ** zoom))))
        lon_g, lat_g = np.meshgrid(lons, lats)
        mask = contains_xy(geom, lon_g, lat_g)
        if not mask.any():
            continue
        got += 1
        for k, v in classify(img, mask).items():
            counts[k] += v
    total = sum(counts.values())
    if not total:
        raise RuntimeError("no land cover pictures could be read for this city")
    shares = {str(k): round(v / total * 100, 2) for k, v in sorted(counts.items())}
    return {"shares": shares, "tiles": got, "missing": missing, "zoom": zoom, "year": year,
            "worked_out": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def city_cover_start(q: Q, ids: list[str]) -> dict:
    """Queue urban centres to work out (one at a time, in the background)."""
    s = local.load_settings()
    if not s.get("land_city_cover", True):
        raise ValueError("City land cover is switched off (Settings > Land)")
    have = _cover_store()
    todo = [i for i in ids if i not in have]
    geoms = {r["feature_id"]: (r["name"], json.loads(r["props"] or "{}"), json.loads(r["geojson"])) for r in q(
        f"SELECT feature_id, name, props, geojson FROM geo_features WHERE layer_id = 'urban_centres' AND feature_id IN "
        f"({', '.join('?' * len(todo))})", todo)} if todo else {}
    with _cover_lock:
        queued = {w[0] for w in _cover_waiting}
        for i in todo:
            if i in geoms and i not in queued:
                _cover_waiting.append((i, *geoms[i]))
        if _cover_job.get("state") == "running" or not _cover_waiting:
            return dict(_cover_job)
        _cover_job.clear()
        _cover_job.update(state="running", done=0, total=len(_cover_waiting))
    threading.Thread(target=_cover_work, args=(s.get("land_cover_year", "2021"),), daemon=True, name="city-cover").start()
    with _cover_lock:
        return dict(_cover_job)


def _cover_work(year: str) -> None:
    while True:
        with _cover_lock:
            if not _cover_waiting:
                _cover_job.update(state="done")
                return
            cid, name, props, geom = _cover_waiting.pop(0)
            _cover_job.update(step=f"Working out {name}")
        try:
            res = city_cover_compute(geom, year)
            people = (props.get("pop") or {}).get(str(props.get("now")))
            res.update(name=name, country=props.get("country"), people=people)
            res.update(trees_estimate(res["shares"], props.get("area"), geom, people))
            with _cover_lock:
                store = _cover_store()
                store[cid] = res
                _cover_file().parent.mkdir(parents=True, exist_ok=True)
                _cover_file().write_text(json.dumps(store, indent=1), encoding="utf-8")
                _cover_job["done"] = _cover_job.get("done", 0) + 1
        except Exception as exc:  # noqa: BLE001 - shown on the page
            log.warning("city cover %s: %s", name, exc)
            with _cover_lock:
                _cover_job.update(error=f"{name}: {exc}")


def _area_km2(geom: dict) -> float:
    from shapely.geometry import shape

    g = shape(geom)
    lat = (g.bounds[1] + g.bounds[3]) / 2
    return g.area * 111.32 ** 2 * math.cos(math.radians(lat))


def trees_estimate(shares: dict, area_km2: float | None, geom: dict, people: float | None) -> dict:
    """Tree cover area, an estimated tree count (TREES_PER_HA_CANOPY a hectare of canopy) and
    trees per person. Always labelled an estimate."""
    area = area_km2 or _area_km2(geom)
    tree_km2 = area * (shares.get("10", 0) + shares.get("95", 0)) / 100
    trees = tree_km2 * 100 * TREES_PER_HA_CANOPY
    return {"area_km2": round(area, 1), "tree_km2": round(tree_km2, 2), "trees_estimate": round(trees, -2),
            "trees_per_person": round(trees / people, 2) if people else None}


def city_cover(q: Q) -> dict:
    """Every city worked out so far, with the job's state, and the class names and colours."""
    with _cover_lock:
        job = dict(_cover_job)
    store = _cover_store()
    rows = [{"id": k, **v} for k, v in store.items()]
    rows.sort(key=lambda r: -(r.get("shares", {}).get("10") or 0))
    return {"rows": rows, "job": job, "classes": {str(k): {"name": n, "color": c} for k, (n, c) in WORLDCOVER.items()},
            "trees_per_ha": TREES_PER_HA_CANOPY}


# ----------------------------------------------------------------------------- New Zealand land cover
def nz(q: Q, level: int = 2, region: str = "NZL", y0: int | None = None, y1: int | None = None) -> dict:
    """LCDB area by class (grouped to the level asked) at each survey, the from-to changes
    between two surveys, and each region's totals for the latest survey."""
    level = level if level in LCDB_LEVELS else 2
    got = q("""SELECT entity_id AS e, year(period_start) AS y, breakdown AS b, value AS v FROM series
               WHERE indicator_id = 'nz_lcdb_ha' AND variant = 'central' AND breakdown LIKE 'class=%'""", [])
    if not got:
        return {"years": [], "cover": {}, "flows": [], "regions": [], "level": level, "levels": LCDB_LEVELS}
    cover: dict = defaultdict(lambda: defaultdict(float))
    by_region: dict = defaultdict(lambda: defaultdict(float))
    years = sorted({r["y"] for r in got})
    for r in got:
        code = int(r["b"].split("=", 1)[1])
        name = lcdb_level(code, level)
        if r["e"] == region:
            cover[r["y"]][name] += r["v"]
        if r["e"] != "NZL" and r["y"] == years[-1]:
            by_region[r["e"]][name] += r["v"]
    y1 = y1 if y1 in years else years[-1]
    y0 = y0 if y0 in years and y0 < y1 else (years[-2] if len(years) > 1 else years[0])
    ch = q("""SELECT year(period_start) AS y, breakdown AS b, value AS v FROM series
              WHERE indicator_id = 'nz_lcdb_change_ha' AND entity_id = ? AND variant = 'central'""", [region])
    flows: dict = defaultdict(float)
    # Change between surveys further apart: the sum of the steps in between (a class may change twice)
    for r in ch:
        if y0 < r["y"] <= y1:
            a, b = (int(x) for x in r["b"].split("=", 1)[1].split(">"))
            na, nb = lcdb_level(a, level), lcdb_level(b, level)
            if na != nb:
                flows[(na, nb)] += r["v"]
    names = {r["entity_id"]: r["short_name"] or r["name"] for r in q("SELECT entity_id, name, short_name FROM entities WHERE entity_id LIKE 'NZ-%'", [])}
    classes = sorted({lcdb_level(c, level) for c in LCDB_CLASSES})
    return {"years": years, "level": level, "levels": LCDB_LEVELS, "region": region, "y0": y0, "y1": y1, "classes": classes,
            "cover": {y: dict(v) for y, v in cover.items()},
            "flows": sorted(({"from": a, "to": b, "ha": v} for (a, b), v in flows.items()), key=lambda f: -f["ha"]),
            "regions": sorted(({"id": e, "name": names.get(e, e), "cover": dict(v), "total": sum(v.values())}
                               for e, v in by_region.items()), key=lambda r: r["name"])}


# ----------------------------------------------------------------------------- council trees
def street_trees(q: Q, council: str | None = None) -> dict:
    """What a council's tree list holds: how many, the commonest species, planting by year."""
    if not _has(q, "geo_features"):
        return {"councils": [], "total": 0}
    councils = q("""SELECT json_extract_string(props, '$.council') AS c, count(*) AS n FROM geo_features
                    WHERE layer_id = 'street_trees' GROUP BY 1 ORDER BY 2 DESC""", [])
    if not councils:
        return {"councils": [], "total": 0}
    c = council or councils[0]["c"]
    species = q("""SELECT coalesce(json_extract_string(props, '$.common'), json_extract_string(props, '$.species'), 'Not named') AS name,
                          any_value(json_extract_string(props, '$.species')) AS species, count(*) AS n,
                          avg(TRY_CAST(json_extract_string(props, '$.height') AS DOUBLE)) AS height
                   FROM geo_features WHERE layer_id = 'street_trees' AND json_extract_string(props, '$.council') = ?
                   GROUP BY 1 ORDER BY 3 DESC LIMIT 25""", [c])
    planted = q("""SELECT TRY_CAST(json_extract_string(props, '$.planted') AS INTEGER) AS y, count(*) AS n FROM geo_features
                   WHERE layer_id = 'street_trees' AND json_extract_string(props, '$.council') = ? AND y IS NOT NULL
                   GROUP BY 1 ORDER BY 1""", [c])
    total = next((r["n"] for r in councils if r["c"] == c), 0)
    box = q("""SELECT min(west) AS w, min(south) AS s, max(east) AS e, max(north) AS n FROM geo_features
               WHERE layer_id = 'street_trees' AND json_extract_string(props, '$.council') = ?""", [c])
    return {"council": c, "councils": councils, "total": total, "species": species, "planted": planted,
            "bbox": [box[0][k] for k in ("w", "s", "e", "n")] if box else None}
