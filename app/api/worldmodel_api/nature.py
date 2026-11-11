"""Climate zones, pollution and nature: map tiles of the Köppen-Geiger zones, a country's
zones now and ahead with city climate twins, the Pollution page, the Climate page's
Nature tab, protected areas by map window, and climate pledges as points on emissions
charts. Each function takes `q`, the API's rows(sql, params) helper."""

from __future__ import annotations

import math
import struct
import threading
import zlib
from collections import defaultdict
from typing import Callable

from worldmodel_contract import catalogue
from worldmodel_contract.koppen import GROUP_COLOURS, GROUPS, ZONES, group_of

Q = Callable[[str, list], list[dict]]
SCENARIOS = {"ssp126": "SSP1-2.6 (low emissions)", "ssp245": "SSP2-4.5 (middle)", "ssp585": "SSP5-8.5 (very high)"}
NOW = "1991-2020"
TILE = 256
TWIN_MIN_POP = 300_000

# Indicators each page tab shows, in order; those not loaded are left out.
POLLUTION_TABS = {
    "air": ["pm25_exposure", "pm25_above_who_share", "air_pollution_death_rate", "air_pollution_death_share"],
    "water": ["safe_drinking_water", "wastewater_treated_share", "water_quality_good_share", "water_stress",
              "freshwater_withdrawal_share"],
    "ocean": ["ocean_plastic", "ocean_plastic_per_capita", "ocean_plastic_share", "kba_sea_protected", "protected_sea_share"],
    "borders": ["co2_trade_share", "co2_consumption", "co2_gcp"],
}
NATURE_LOSING = ["living_planet_index", "red_list_index", "red_list_index_owid", "threatened_mammals", "threatened_birds",
                 "threatened_fish_wdi", "threatened_plants_wdi", "iucn_threatened", "iucn_cr", "iucn_ex", "tree_cover_loss"]
NATURE_INVASIVE = ["introduced_species", "watched_pests_present", "animal_disease_outbreaks"]
NATURE_RECOVERING = ["protected_land_share", "protected_sea_share", "protected_total_share", "kba_land_protected",
                     "kba_fresh_protected", "kba_sea_protected", "forest_area_share"]

_grids: dict[tuple, tuple[int, int, bytes]] = {}
_lock = threading.Lock()


# ----------------------------------------------------------------------------- helpers
def _present(q: Q, ids: list[str]) -> list[str]:
    if not ids:
        return []
    got = {r["indicator_id"] for r in q(f"SELECT indicator_id FROM indicators WHERE indicator_id IN ({', '.join('?' * len(ids))})", ids)}
    return [i for i in ids if i in got]


def _like(q: Q, like: str) -> list[str]:
    return [r["indicator_id"] for r in q("SELECT indicator_id FROM indicators WHERE indicator_id LIKE ? ESCAPE '\\' ORDER BY 1", [like])]


def _latest(q: Q, ids: list[str], entity: str) -> dict:
    """indicator -> {year, value}: the latest central value of each, best-ranked source."""
    if not ids:
        return {}
    got = q(f"""
        SELECT s.indicator_id AS i, year(s.period_start) AS y, s.value AS v, s.source_id AS src
        FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        WHERE s.indicator_id IN ({', '.join('?' * len(ids))}) AND s.entity_id = ? AND s.breakdown = ''
          AND s.variant = 'central' AND s.status = 'E'
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id ORDER BY s.period_start DESC, r.rank) = 1""", ids + [entity])
    return {r["i"]: {"year": r["y"], "value": r["v"], "source_id": r["src"]} for r in got}


def _meta(q: Q, ids: list[str]) -> dict:
    if not ids:
        return {}
    return {r["indicator_id"]: {"name": r["name"], "unit": r["unit"], "decimals": r["decimals"]}
            for r in q(f"SELECT indicator_id, name, unit, decimals FROM indicators WHERE indicator_id IN ({', '.join('?' * len(ids))})", ids)}


def _events(q: Q, kinds: list[str], entity: str | None = None, limit: int = 200) -> list[dict]:
    where = f"kind IN ({', '.join('?' * len(kinds))})" + (" AND entity_id = ?" if entity else "")
    got = q(f"""SELECT kind, subkind, title, start_date, end_date, precision, place, url, detail, list(entity_id ORDER BY entity_id) AS entities
                FROM events WHERE {where}
                GROUP BY kind, subkind, title, start_date, end_date, precision, place, url, detail
                ORDER BY start_date DESC LIMIT {int(limit)}""", kinds + ([entity] if entity else []))
    return [{**e, "start_date": e["start_date"].isoformat() if e["start_date"] else None,
             "end_date": e["end_date"].isoformat() if e["end_date"] else None} for e in got]


# ----------------------------------------------------------------------------- climate zone grids and tiles
def legend() -> dict:
    return {"zones": [{"n": n, "code": c, "name": name, "colour": "#%02x%02x%02x" % rgb, "group": group_of(n)}
                      for n, (c, name, rgb) in ZONES.items()],
            "groups": [{"code": g, "name": name, "colour": "#%02x%02x%02x" % GROUP_COLOURS[g]} for g, (name, _) in GROUPS.items()],
            "scenarios": SCENARIOS}


def periods(q: Q) -> list[dict]:
    return q("SELECT period, scenario FROM zone_grids ORDER BY period, scenario", [])


def grid(q: Q, build: str, period: str, scenario: str) -> tuple[int, int, bytes] | None:
    """(width, height, one byte per cell), kept for the four grids last asked for."""
    k = (build, period, scenario)
    with _lock:
        if k in _grids:
            return _grids[k]
    got = q("SELECT width, height, grid FROM zone_grids WHERE period = ? AND scenario = ?", [period, scenario])
    if not got:
        return None
    w, h, blob = got[0]["width"], got[0]["height"], got[0]["grid"]
    out = (w, h, zlib.decompress(bytes(blob)))
    with _lock:
        while len(_grids) >= 4:
            _grids.pop(next(iter(_grids)))
        _grids[k] = out
    return out


def zone_at(g: tuple[int, int, bytes], lat: float, lon: float, reach: int = 3) -> int:
    """The zone at a place; for a coastal city whose cell is sea, the nearest land cell within reach."""
    w, h, data = g
    r0 = min(h - 1, max(0, int((90 - lat) / 180 * h)))
    c0 = int((lon + 180) / 360 * w) % w
    if data[r0 * w + c0]:
        return data[r0 * w + c0]
    for d in range(1, reach + 1):
        for dr in range(-d, d + 1):
            for dc in range(-d, d + 1):
                if max(abs(dr), abs(dc)) == d and 0 <= r0 + dr < h:
                    z = data[(r0 + dr) * w + (c0 + dc) % w]
                    if z:
                        return z
    return 0


def _png(width: int, height: int, rows: list[bytes], palette: list[tuple[int, int, int]]) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", b"".join(bytes(c) for c in palette)) + chunk(b"tRNS", b"\x00" + b"\xff" * (len(palette) - 1))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


ZONE_PALETTE = [(0, 0, 0)] + [ZONES[n][2] for n in range(1, 31)]
GROUP_PALETTE = [(0, 0, 0)] + [GROUP_COLOURS[g] for g in GROUPS]
GROUP_TABLE = bytes([0] + [list(GROUPS).index(group_of(n)) + 1 for n in range(1, 31)] + [0] * 225)
ZONE_TABLE = bytes(list(range(31)) + [0] * 225)


def tile(g: tuple[int, int, bytes], z: int, x: int, y: int, groups: bool = False) -> bytes:
    """A 256-pixel Web Mercator tile of the zones, sea and missing cells see-through."""
    w, h, data = g
    n = 2 ** z
    x %= n
    cols = [int((x * TILE + px + 0.5) / (TILE * n) * w) % w for px in range(TILE)]
    rows = []
    for py in range(TILE):
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y * TILE + py + 0.5) / (TILE * n)))))
        r = min(h - 1, max(0, int((90 - lat) / 180 * h)))
        line = data[r * w:(r + 1) * w]
        rows.append(bytes(map(line.__getitem__, cols)).translate(GROUP_TABLE if groups else ZONE_TABLE))
    return _png(TILE, TILE, rows, GROUP_PALETTE if groups else ZONE_PALETTE)


_tiles: dict[tuple, bytes] = {}


def tile_png(q: Q, build: str, period: str, scenario: str, z: int, x: int, y: int, groups: bool) -> bytes | None:
    """A tile as PNG, the last 2,000 kept."""
    k = (build, period, scenario, z, x % (2 ** z), y, groups)
    if k in _tiles:
        return _tiles[k]
    g = grid(q, build, period, scenario)
    if g is None:
        return None
    png = tile(g, z, x, y, groups)
    with _lock:
        if len(_tiles) >= 2000:
            _tiles.pop(next(iter(_tiles)))
        _tiles[k] = png
    return png


# ----------------------------------------------------------------------------- a country's zones and city twins
def _scen_for(period: str, scenario: str) -> str:
    return "historical" if int(period[:4]) <= 2020 else scenario


def _cities(q: Q, min_pop: float, entity: str | None = None) -> list[dict]:
    try:
        return q(f"""SELECT city_id, name, country_id, lat, lon, population FROM cities
                     WHERE population >= ? {"AND country_id = ?" if entity else ""} ORDER BY population DESC""",
                 [min_pop] + ([entity] if entity else []))
    except Exception:  # noqa: BLE001 - warehouses without cities
        return []


def twins(q: Q, build: str, cities: list[dict], scenario: str = "ssp245", period: str = "2071-2099") -> list[dict]:
    """For each city, its climate zone now and in `period`, and a city whose zone now is the
    one it is heading for, as close in latitude as possible (rough: only the zone is compared)."""
    now, later = grid(q, build, NOW, "historical"), grid(q, build, period, scenario)
    if not now or not later:
        return []
    pool = [(c, zone_at(now, c["lat"], c["lon"])) for c in _cities(q, TWIN_MIN_POP)]
    by_zone: dict[int, list[dict]] = defaultdict(list)
    for c, z in pool:
        by_zone[z].append(c)
    out = []
    for c in cities:
        z0, z1 = zone_at(now, c["lat"], c["lon"]), zone_at(later, c["lat"], c["lon"])
        twin = None
        if z1 and z1 != z0:
            cands = [t for t in by_zone.get(z1, []) if t["country_id"] != c["country_id"]] or by_zone.get(z1, [])
            if cands:
                t = min(cands, key=lambda t: (abs(abs(t["lat"]) - abs(c["lat"])) // 3, -t["population"]))
                twin = {"name": t["name"], "country_id": t["country_id"], "city_id": t["city_id"]}
        out.append({"city_id": c["city_id"], "name": c["name"], "population": c["population"],
                    "now": ZONES.get(z0, ("", "", ()))[0] or None, "later": ZONES.get(z1, ("", "", ()))[0] or None,
                    "twin": twin})
    return out


def country(q: Q, build: str, entity: str, scenario: str = "ssp245") -> dict:
    """Share of land in each zone and main group per period (with the paths ahead), the share
    of city dwellers in each zone now, and the big cities' climate twins."""
    got = q("""SELECT year(period_start) AS y, breakdown AS b, variant AS v, value FROM series
               WHERE indicator_id = 'climate_zone_share' AND entity_id = ? ORDER BY 1""", [entity])
    zones: dict = defaultdict(lambda: defaultdict(dict))
    for r in got:
        zones[r["v"]][r["y"]][r["b"].removeprefix("zone=")] = r["value"]
    groups = q("""SELECT indicator_id AS i, year(period_start) AS y, variant AS v, value FROM series
                  WHERE indicator_id LIKE 'climzone\\_%' ESCAPE '\\' AND entity_id = ? ORDER BY 2""", [entity])
    gout: dict = defaultdict(lambda: defaultdict(dict))
    for r in groups:
        gout[r["v"]][r["y"]][r["i"][-1].upper()] = r["value"]
    big = _cities(q, 15_000, entity)
    people: dict[str, float] = defaultdict(float)
    now = grid(q, build, NOW, "historical")
    if now:
        for c in big:
            z = zone_at(now, c["lat"], c["lon"])
            if z:
                people[ZONES[z][0]] += c["population"] or 0
    total = sum(people.values())
    return {
        "entity": entity,
        "zones": {v: {str(y): d for y, d in by.items()} for v, by in zones.items()},
        "groups": {v: {str(y): d for y, d in by.items()} for v, by in gout.items()},
        "people": {k: round(v / total * 100, 1) for k, v in sorted(people.items(), key=lambda kv: -kv[1])} if total else {},
        "people_note": "Share of people living in this country's towns and cities of 15,000 or more (GeoNames), by the zone each is in.",
        "twins": twins(q, build, big[:12], scenario),
        "scenario": scenario,
        "legend": legend(),
    }


# ----------------------------------------------------------------------------- pledges
def pledges(q: Q, entity: str, indicator: str = "ghg_total_gcp") -> dict:
    """Climate pledges (nature.yaml) as points: the base year's emissions cut by the pledge."""
    items = catalogue.nature().get("pledges", {}).get(entity, [])
    out = []
    for p in items:
        base = q("""SELECT s.value FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
                    WHERE s.indicator_id = ? AND s.entity_id = ? AND year(s.period_start) = ? AND s.breakdown = '' AND s.variant = 'central'
                    ORDER BY r.rank LIMIT 1""", [indicator, entity, p["base_year"]])
        b = base[0]["value"] if base else None
        out.append({**p, "base_value": b, "target": b * (1 - p["cut"] / 100) if b is not None else None,
                    "target_low": b * (1 - p["cut_high"] / 100) if b is not None and p.get("cut_high") else None})
    return {"entity": entity, "indicator": indicator, "pledges": out,
            "note": "Worked out from this app's emissions in the base year; pledges count forests and other things their own way, so read the point as a guide."}


# ----------------------------------------------------------------------------- pollution and nature pages
def pollution(q: Q) -> dict:
    tabs = {t: _present(q, ids) for t, ids in POLLUTION_TABS.items()}
    tabs["air"] += _like(q, "airpol%")
    ids = [i for v in tabs.values() for i in v]
    return {"tabs": tabs, "names": _meta(q, ids), "events": _events(q, ["pollution"])}


def pollution_country(q: Q, entity: str) -> dict:
    tabs = pollution(q)["tabs"]
    ids = [i for v in tabs.values() for i in v]
    return {"entity": entity, "tabs": tabs, "latest": _latest(q, ids, entity), "names": _meta(q, ids),
            "events": _events(q, ["pollution"], entity, 30)}


def _pests(q: Q, entity: str | None = None) -> list[dict]:
    watch = catalogue.nature().get("pests", [])
    try:
        rows = q("""SELECT pest_code, entity_id, bool_or(present) AS present, list(DISTINCT status) AS statuses
                    FROM pest_presence GROUP BY 1, 2""", [])
    except Exception:  # noqa: BLE001 - warehouses before 1.9.0
        rows = []
    by: dict = defaultdict(list)
    here: dict = {}
    for r in rows:
        if r["present"]:
            by[r["pest_code"]].append(r["entity_id"])
        if entity and r["entity_id"] == entity:
            here[r["pest_code"]] = {"present": r["present"], "statuses": r["statuses"]}
    return [{**p, "countries": len(by.get(p["code"], [])), "loaded": bool(rows),
             **({"here": here.get(p["code"])} if entity else {})} for p in watch]


def nature(q: Q) -> dict:
    losing, invasive, recovering = _present(q, NATURE_LOSING), _present(q, NATURE_INVASIVE), _present(q, NATURE_RECOVERING)
    n = catalogue.nature()
    try:
        pa = q("SELECT count(*) AS n, sum(area_km2) AS km2 FROM protected_areas", [])[0]
    except Exception:  # noqa: BLE001
        pa = {"n": 0, "km2": None}
    return {"losing": losing, "invasive": invasive, "recovering": recovering,
            "names": _meta(q, losing + invasive + recovering),
            "disease": _events(q, ["animal_disease"]), "pest_events": _events(q, ["pest"]), "pests": _pests(q),
            "comebacks": n.get("comebacks", []), "restoration": n.get("restoration", []), "protected": pa}


def nature_country(q: Q, entity: str) -> dict:
    page = nature(q)
    ids = page["losing"] + page["invasive"] + page["recovering"]
    try:
        species = q("""SELECT scientific_name, category, year, url FROM species_status WHERE entity_id = ?
                       ORDER BY CASE category WHEN 'EX' THEN 0 WHEN 'EW' THEN 1 ELSE 2 END, scientific_name""", [entity])
    except Exception:  # noqa: BLE001
        species = []
    n = catalogue.nature()
    return {"entity": entity, "latest": _latest(q, ids, entity), "names": page["names"], "species": species,
            "pests": _pests(q, entity), "events": _events(q, ["animal_disease", "pest"], entity, 40),
            "comebacks": [c for c in n.get("comebacks", []) if entity in c.get("countries", [])],
            "restoration": [r for r in n.get("restoration", []) if entity in r.get("countries", [])]}


def _lon(v: float) -> float:
    return (v + 180) % 360 - 180


def protected(q: Q, west: float, south: float, east: float, north: float, limit: int = 1500) -> dict:
    """Protected areas overlapping a map window, the largest first, as GeoJSON. The window may
    cross the date line (a Pacific-centred map): longitudes are wrapped into -180..180."""
    import json

    if east - west >= 360:
        spans = [(-180.0, 180.0)]
    else:
        w, e = _lon(west), _lon(east)
        spans = [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]
    where = " OR ".join("(east >= ? AND west <= ?)" for _ in spans)
    try:
        got = q(f"""SELECT wdpa_id, name, designation, iucn_cat, entity_id, marine, area_km2, year, geojson FROM protected_areas
                    WHERE ({where}) AND north >= ? AND south <= ?
                    ORDER BY area_km2 DESC NULLS LAST LIMIT ?""", [v for sp in spans for v in sp] + [south, north, limit])
    except Exception:  # noqa: BLE001 - warehouses before 1.9.0
        got = []
    feats = [{"type": "Feature", "geometry": json.loads(r.pop("geojson")), "properties": r} for r in got]
    return {"type": "FeatureCollection", "features": feats}
