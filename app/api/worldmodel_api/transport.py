"""Transport, tourism and networks: the Transport and Tourism pages, their country cards,
rivers, basins, waterways, cables and pipelines by map window (geo_features), one feature
with what depends on it, chokepoint and port traffic. Each function takes `q`, the API's
rows(sql, params) helper."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import timedelta
from typing import Callable

from worldmodel_contract import catalogue

from worldmodel_api.nature import _events, _latest, _lon, _meta, _present

Q = Callable[[str, list], list[dict]]

TRANSPORT_TABS = {
    "sea": ["liner_shipping_connectivity", "container_port_traffic", "port_calls", "seaborne_imports_t", "seaborne_exports_t"],
    "air": ["air_passengers", "air_departures", "air_freight_tkm"],
    "land": ["rail_freight_tkm", "rail_passenger_km", "inland_waterway_freight"],
    "safety": ["road_deaths_rate"],
}
TOURISM_TABS = {
    "visitors": ["tourist_arrivals", "unt_arrivals", "unt_nights", "tourist_departures", "unt_departures"],
    "money": ["tourism_receipts_usd", "unt_receipts_usd", "tourism_share_exports", "tourism_spending_abroad_usd",
              "unt_spending_abroad_usd"],
    "standing": ["ttdi_score", "ttdi_rank", "heritage_sites", "heritage_sites_in_danger"],
    "nz": ["nz_visitor_arrivals", "nz_visitor_spend", "nz_tourism_gdp_share", "nz_tourism_jobs"],
}
GEO_LAYERS = {  # layer -> (name, the largest rank shown at each zoom: [(zoom below, rank), ...], rows at most)
    "rivers": ("Rivers", [(2.5, 2), (4, 3), (5.5, 4), (99, 5)], 6000),
    "river_names": ("River names", [(3, 2), (5, 5), (99, 12)], 1500),
    "basins": ("River basins", [(3, 1), (5, 2), (99, 3)], 1500),
    "waterways": ("Inland waterways", [(4, 1), (99, 3)], 4000),
    "cables": ("Undersea cables", [(99, 9)], 1500),
    "gas_pipelines": ("Gas pipelines", [(3, 1), (99, 5)], 4000),
    "oil_pipelines": ("Oil pipelines", [(3, 1), (99, 5)], 4000),
    "urban_centres": ("City outlines", [(3, 1), (5, 2), (99, 3)], 3000),
    "street_trees": ("Street trees", [(12, 0), (99, 1)], 8000),
    "nz_land_change": ("Land cover change (NZ)", [(7, 1), (99, 2)], 6000),
}
COVID = {"kind": "band", "title": "COVID-19 border closures", "start_date": "2020-03-01", "end_date": "2022-06-30"}


def shore_key(name: str) -> str:
    """A chokepoint name without its kind words, so "Strait of Hormuz" and "Hormuz Strait" match
    (as connectors/transport.py matches them)."""
    words = re.findall(r"[a-z]+", str(name or "").lower().replace("ø", "o"))
    return " ".join(w for w in words if w not in {"strait", "straits", "of", "the", "canal", "channel", "passage", "el"})


def _has(q: Q, table: str) -> bool:
    try:
        q(f"SELECT 1 FROM {table} LIMIT 1", [])
        return True
    except Exception:  # noqa: BLE001 - warehouses before 1.10.0
        return False


def _names(q: Q, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    return {r["entity_id"]: r["short_name"] or r["name"] for r in q(
        f"SELECT entity_id, name, short_name FROM entities WHERE entity_id IN ({', '.join('?' * len(ids))})", list(ids))}


def _iso(d) -> str | None:
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------- geo_features by window
def _spans(west: float, east: float) -> list[tuple[float, float]]:
    if east - west >= 360:
        return [(-180.0, 180.0)]
    w, e = _lon(west), _lon(east)
    return [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]


def geo(q: Q, layer: str, west: float, south: float, east: float, north: float, zoom: float = 2,
        status: str | None = None) -> dict:
    """A geo_features layer in a map window as GeoJSON: only the ranks that show at this zoom,
    biggest first."""
    if layer not in GEO_LAYERS or not _has(q, "geo_features"):
        return {"type": "FeatureCollection", "features": []}
    _, by_zoom, limit = GEO_LAYERS[layer]
    max_rank = next(r for z, r in by_zoom if zoom < z)
    spans = _spans(west, east)
    where = " OR ".join("(east >= ? AND west <= ?)" for _ in spans)
    extra, params = "", [layer] + [v for sp in spans for v in sp] + [south, north, max_rank]
    if status == "operating":
        extra = " AND rank = 1"
    got = q(f"""SELECT feature_id, name, rank, props, countries, geojson FROM geo_features
                WHERE layer_id = ? AND ({where}) AND north >= ? AND south <= ? AND coalesce(rank, 1) <= ?{extra}
                ORDER BY rank NULLS FIRST, (east - west) * (north - south) DESC LIMIT {int(limit)}""", params)
    feats = []
    for r in got:
        props = json.loads(r["props"] or "{}")
        if layer == "basins":  # the card asks for shares; the map needs less
            props = {k: props.get(k) for k in ("area", "flow", "transboundary")}
        elif layer == "cables":
            props = {k: props.get(k) for k in ("color", "rfs", "planned")}
        elif layer == "urban_centres":
            props = {k: props.get(k) for k in ("people", "growth", "now", "first")}
        feats.append({"type": "Feature", "geometry": json.loads(r["geojson"]),
                      "properties": {"id": r["feature_id"], "name": r["name"], "rank": r["rank"], "layer": layer,
                                     "countries": r["countries"] or "", **props}})
    return {"type": "FeatureCollection", "features": feats}


def feature(q: Q, layer: str, feature_id: str) -> dict | None:
    """One river, basin, waterway, cable or pipeline with everything known about it and the
    countries that depend on it: for a basin, its country split with roughly how many people
    live in its part of each country (population times the share of the country's land in it)."""
    if not _has(q, "geo_features"):
        return None
    got = q("SELECT layer_id, feature_id, name, rank, props, countries, source_id, vintage FROM geo_features "
            "WHERE layer_id = ? AND feature_id = ?", [layer, feature_id])
    if not got:
        return None
    r = got[0]
    props = json.loads(r["props"] or "{}")
    countries = [c for c in (r["countries"] or "").split(",") if c]
    names = _names(q, countries)
    out = {"layer": layer, "id": feature_id, "name": r["name"], "props": props, "source_id": r["source_id"],
           "vintage": r["vintage"], "countries": [{"id": c, "name": names.get(c, c)} for c in countries]}
    if layer == "basins":
        of = props.get("of_country") or {}
        pop = _latest_many(q, "pop_total", list(of))
        split = []
        for c, share in (props.get("shares") or {}).items():
            people = pop.get(c) * of[c] if pop.get(c) is not None and c in of else None
            split.append({"id": c, "name": names.get(c, c), "share": share, "of_country": of.get(c),
                          "people": round(people) if people is not None else None})
        out["split"] = split
        out["people"] = round(sum(s["people"] for s in split if s["people"])) or None
    return out


def _latest_many(q: Q, indicator: str, ids: list[str]) -> dict[str, float]:
    if not ids:
        return {}
    got = q(f"""SELECT entity_id, value FROM series WHERE indicator_id = ? AND entity_id IN ({', '.join('?' * len(ids))})
                AND breakdown = '' AND variant = 'central' AND status = 'E'
                QUALIFY row_number() OVER (PARTITION BY entity_id ORDER BY period_start DESC) = 1""", [indicator] + ids)
    return {r["entity_id"]: r["value"] for r in got}


def depends(q: Q, kind: str, ident: str) -> dict:
    """The countries that rely on a cable, pipeline, chokepoint or basin, for the map to highlight."""
    if kind == "chokepoints":
        shores = catalogue.transport().get("chokepoints") or {}
        ids = next((v for k, v in shores.items() if shore_key(k) == shore_key(ident)), [])
        return {"kind": kind, "id": ident, "countries": [{"id": c, "name": n} for c, n in _names(q, ids).items()],
                "note": "Countries on its shores. Ships through it carry trade for many more."}
    f = feature(q, kind, ident)
    return {"kind": kind, "id": ident, "countries": f["countries"] if f else [], "name": f["name"] if f else None}


# ----------------------------------------------------------------------------- chokepoints and ports
def chokepoints(q: Q) -> list[dict]:
    """Each chokepoint's ships a day over the last 30 days against the same 30 days a year before."""
    if not _has(q, "chokepoint_traffic"):
        return []
    last = q("SELECT max(day) AS d FROM chokepoint_traffic", [])[0]["d"]
    if not last:
        return []
    a, b = last - timedelta(days=29), last - timedelta(days=365)
    got = q("""SELECT chokepoint_id AS id, any_value(name) AS name,
                      avg(transits) FILTER (WHERE day >= ?) AS now,
                      avg(transits) FILTER (WHERE day BETWEEN ? AND ?) AS year_before,
                      avg(capacity) FILTER (WHERE day >= ?) AS capacity
               FROM chokepoint_traffic GROUP BY 1 ORDER BY now DESC NULLS LAST""", [a, b - timedelta(days=29), b, a])
    for g in got:
        g["change"] = round(100 * (g["now"] / g["year_before"] - 1), 1) if g["now"] and g["year_before"] else None
        g["now"] = round(g["now"], 1) if g["now"] is not None else None
        g["year_before"] = round(g["year_before"], 1) if g["year_before"] is not None else None
    return [{**g, "as_of": last.isoformat()} for g in got]


def chokepoint(q: Q, ident: str, start: int | None = None) -> dict:
    """One chokepoint's ships a day by type (a week's average) since `start`."""
    if not _has(q, "chokepoint_traffic"):
        return {"id": ident, "points": []}
    got = q("""SELECT date_trunc('week', day) AS w, any_value(name) AS name, avg(transits) AS transits, avg(tankers) AS tankers,
                      avg(container) AS container, avg(dry_bulk) AS dry_bulk, avg(cargo) AS cargo, avg(capacity) AS capacity
               FROM chokepoint_traffic WHERE chokepoint_id = ? AND year(day) >= ? GROUP BY 1 ORDER BY 1""",
            [ident, start or 2019])
    name = got[0]["name"] if got else ident
    return {"id": ident, "name": name, "points": [{**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in g.items()
                                                       if k not in ("w", "name")}, "week": g["w"].isoformat()} for g in got],
            "depends": depends(q, "chokepoints", name)["countries"]}


def port(q: Q, ident: str) -> dict:
    if not _has(q, "port_traffic"):
        return {"id": ident, "months": []}
    got = q("SELECT year, month, calls, import_t, export_t, entity_id FROM port_traffic WHERE port_id = ? ORDER BY 1, 2", [ident])
    return {"id": ident, "entity_id": got[0]["entity_id"] if got else None, "months": got}


def top_ports(q: Q, entity: str | None = None, limit: int = 15) -> list[dict]:
    if not _has(q, "port_traffic"):
        return []
    full = q("""SELECT year FROM port_traffic GROUP BY year HAVING count(DISTINCT month) = 12 ORDER BY year DESC LIMIT 1""", [])
    if not full:
        return []
    year = full[0]["year"]
    where, params = "year = ?", [year]
    if entity:
        where += " AND entity_id = ?"
        params.append(entity)
    got = q(f"""SELECT port_id, any_value(entity_id) AS entity_id, sum(calls) AS calls, sum(import_t) AS import_t,
                       sum(export_t) AS export_t FROM port_traffic WHERE {where} GROUP BY 1 ORDER BY calls DESC LIMIT {int(limit)}""", params)
    names = _port_names(q)
    return [{**g, "name": names.get(g["port_id"], g["port_id"]), "year": year} for g in got]


def _port_names(q: Q) -> dict[str, str]:
    try:
        row = q("SELECT geojson FROM layers WHERE layer_id = 'ports'", [])
    except Exception:  # noqa: BLE001
        return {}
    if not row:
        return {}
    return {f["properties"].get("id"): f["properties"].get("name") for f in json.loads(row[0]["geojson"])["features"]}


def top_airports(q: Q, entity: str | None = None, limit: int = 15) -> list[dict]:
    if not _has(q, "airport_traffic"):
        return []
    where, params = "passengers IS NOT NULL", []
    if entity:
        where += " AND entity_id = ?"
        params.append(entity)
    got = q(f"""SELECT airport, any_value(name) AS name, any_value(entity_id) AS entity_id, max(year) AS year,
                       arg_max(passengers, year) AS passengers, arg_max(freight_t, year) AS freight_t
                FROM airport_traffic WHERE {where} GROUP BY 1 ORDER BY passengers DESC LIMIT {int(limit)}""", params)
    return got


def _geo_counts(q: Q) -> dict[str, int]:
    if not _has(q, "geo_features"):
        return {}
    return {r["layer_id"]: r["n"] for r in q("SELECT layer_id, count(*) AS n FROM geo_features GROUP BY 1", [])}


def _layer_counts(q: Q, ids: list[str]) -> dict[str, int]:
    got = q(f"SELECT layer_id, feature_count FROM layers WHERE layer_id IN ({', '.join('?' * len(ids))})", ids)
    return {r["layer_id"]: r["feature_count"] for r in got}


# ----------------------------------------------------------------------------- pages and cards
def transport(q: Q, min_deaths: int = 10) -> dict:
    tabs = {k: _present(q, v) for k, v in TRANSPORT_TABS.items()}
    ids = [i for v in tabs.values() for i in v]
    accidents = [e for e in _accidents(q, None, min_deaths, 300)]
    return {"tabs": tabs, "names": _meta(q, ids), "chokepoints": chokepoints(q), "ports": top_ports(q),
            "airports": top_airports(q), "infrastructure": _events(q, ["infrastructure"], None, 300),
            "accidents": accidents, "min_deaths": min_deaths,
            "loaded": {**_geo_counts(q), **_layer_counts(q, ["ports", "chokepoints", "ports_all", "airports", "shipping_lanes",
                                                               "cable_landings", "lng_terminals"])},
            "chokepoint_shores": catalogue.transport().get("chokepoints") or {}}


def _accidents(q: Q, entity: str | None, min_deaths: int, limit: int) -> list[dict]:
    where = "kind = 'transport' AND coalesce(deaths, 0) >= ?" + (" AND entity_id = ?" if entity else "")
    got = q(f"""SELECT subkind, title, start_date, place, url, detail, max(deaths) AS deaths,
                       list(DISTINCT entity_id ORDER BY entity_id) AS entities
                FROM events WHERE {where} GROUP BY subkind, title, start_date, place, url, detail
                ORDER BY start_date DESC LIMIT {int(limit)}""", [min_deaths] + ([entity] if entity else []))
    return [{**e, "start_date": _iso(e["start_date"])} for e in got]


def transport_country(q: Q, entity: str, min_deaths: int = 10) -> dict:
    tabs = {k: _present(q, v) for k, v in TRANSPORT_TABS.items()}
    ids = [i for v in tabs.values() for i in v]
    out = {"entity": entity, "tabs": tabs, "names": _meta(q, ids), "latest": _latest(q, ids, entity),
           "ports": top_ports(q, entity, 8), "airports": top_airports(q, entity, 8),
           "accidents": _accidents(q, entity, min_deaths, 20), "infrastructure": _events(q, ["infrastructure"], entity, 20)}
    if _has(q, "geo_features"):
        like = f"%{entity}%"
        got = q("""SELECT layer_id, feature_id, name, props FROM geo_features
                   WHERE layer_id IN ('cables', 'gas_pipelines', 'oil_pipelines', 'basins') AND countries LIKE ?""", [like])
        by: dict[str, list] = defaultdict(list)
        for g in got:
            p = json.loads(g["props"] or "{}")
            item = {"id": g["feature_id"], "name": g["name"]}
            if g["layer_id"] == "basins":
                share = (p.get("shares") or {}).get(entity)
                if not share or share < 0.01 and (p.get("of_country") or {}).get(entity, 0) < 0.05:
                    continue
                item.update(area=p.get("area"), share=share, of_country=(p.get("of_country") or {}).get(entity),
                            transboundary=p.get("transboundary"), countries=len(p.get("shares") or {}))
            elif g["layer_id"] == "cables":
                item.update(rfs=p.get("rfs"), planned=p.get("planned"))
            else:
                item.update(status=p.get("status"))
            by[g["layer_id"]].append(item)
        by["basins"].sort(key=lambda b: -(b.get("of_country") or 0))
        out["networks"] = {k: v[:40] for k, v in by.items()}
        out["counts"] = {k: len(v) for k, v in by.items()}
    return out


def tourism(q: Q) -> dict:
    tabs = {k: _present(q, v) for k, v in TOURISM_TABS.items()}
    ids = [i for v in tabs.values() for i in v]
    top = []
    for ind in ("tourist_arrivals", "unt_arrivals"):
        if ind in ids:
            top = q("""SELECT s.entity_id, e.short_name AS name, year(s.period_start) AS year, s.value FROM series s
                       JOIN entities e USING (entity_id)
                       WHERE s.indicator_id = ? AND s.breakdown = '' AND s.variant = 'central' AND e.type = 'country'
                       QUALIFY row_number() OVER (PARTITION BY s.entity_id ORDER BY s.period_start DESC) = 1
                       ORDER BY s.value DESC LIMIT 20""", [ind])
            top = [{**t, "indicator": ind} for t in top]
            break
    return {"tabs": tabs, "names": _meta(q, ids), "top": top, "covid": COVID,
            "loaded": _layer_counts(q, ["heritage_sites", "visited_sites", "airports"])}


def tourism_country(q: Q, entity: str) -> dict:
    tabs = {k: _present(q, v) for k, v in TOURISM_TABS.items()}
    ids = [i for v in tabs.values() for i in v]
    origins = []
    for ind in ("nz_visitor_arrivals", "unt_arrivals"):
        if ind not in ids:
            continue
        got = q("""SELECT breakdown, year(period_start) AS year, value FROM series
                   WHERE indicator_id = ? AND entity_id = ? AND breakdown LIKE 'origin=%' AND variant = 'central'
                   QUALIFY row_number() OVER (PARTITION BY breakdown ORDER BY period_start DESC) = 1
                   ORDER BY value DESC LIMIT 10""", [ind, entity])
        if got:
            names = _names(q, [g["breakdown"][7:] for g in got])
            origins = [{"id": g["breakdown"][7:], "name": names.get(g["breakdown"][7:], g["breakdown"][7:]), "year": g["year"],
                        "value": g["value"], "indicator": ind} for g in got]
            break
    sites = []
    try:
        row = q("SELECT geojson FROM layers WHERE layer_id = 'heritage_sites'", [])
        if row:
            sites = [f["properties"] for f in json.loads(row[0]["geojson"])["features"]
                     if entity in str(f["properties"].get("countries") or "").split(",")]
    except Exception:  # noqa: BLE001
        sites = []
    sites.sort(key=lambda s: s.get("year") or 0)
    return {"entity": entity, "tabs": tabs, "names": _meta(q, ids), "latest": _latest(q, ids, entity),
            "origins": origins, "sites": sites, "covid": COVID}

