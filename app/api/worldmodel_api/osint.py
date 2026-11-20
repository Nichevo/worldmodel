"""Detail from the OSINT communities, for the app: located fighting and unrest on the map, a
country's month-by-month picture (also under each CrisisWatch rating), war trackers, sanctions
in force, military strength and arms deals.

Functions take `rows` (main.rows) so they can be tested on a small database. Every query
tolerates a warehouse without these tables (before schema 1.12.0): it answers empty."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

from worldmodel_contract import osint

Rows = Callable[..., list[dict]]


def _safe(rows: Rows, sql: str, params: list | None = None) -> list[dict]:
    try:
        return rows(sql, params or [])
    except Exception:  # noqa: BLE001 - warehouses before 1.12.0
        return []


def _iso(d) -> str | None:
    return d.isoformat() if hasattr(d, "isoformat") else (str(d) if d else None)


def _month(d) -> str:
    return _iso(d)[:7]


# ----------------------------------------------------------------------------- located events on the map
def map_events(rows: Rows, west: float, south: float, east: float, north: float, *, days: int = 30, end: str | None = None,
               kinds: list[str] | None = None, sources: list[str] | None = None, limit: int = 4000) -> dict:
    """Located events in a map window, the biggest first: a GeoJSON FeatureCollection."""
    last = _safe(rows, "SELECT max(day) AS d FROM conflict_events")
    newest = last[0]["d"] if last and last[0]["d"] else None
    if newest is None:
        return {"type": "FeatureCollection", "features": [], "count": 0, "loaded": False}
    stop = date.fromisoformat(end) if end else newest
    start = stop - timedelta(days=days)
    where = ["day > ? AND day <= ?", "lat BETWEEN ? AND ?"]
    params: list = [start, stop, south, north]
    if east - west < 360:
        w, e = ((west + 180) % 360) - 180, ((east + 180) % 360) - 180
        if w <= e:
            where.append("lon BETWEEN ? AND ?")
            params += [w, e]
        else:
            where.append("(lon >= ? OR lon <= ?)")
            params += [w, e]
    if kinds:
        where.append("kind IN (SELECT unnest(?))")
        params.append(kinds)
    if sources:
        where.append("source_id IN (SELECT unnest(?))")
        params.append(sources)
    got = _safe(rows, f"""SELECT event_id, entity_id, day, kind, subkind, deaths, lat, lon, place, admin1, actors, note,
        source_id FROM conflict_events WHERE {' AND '.join(where)} AND lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY coalesce(deaths, 0) DESC, day DESC LIMIT ?""", [*params, limit])
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
              "properties": {"id": r["event_id"], "entity": r["entity_id"], "day": _iso(r["day"]), "kind": r["kind"],
                             "group": osint.EVENT_KINDS.get(r["kind"], ("", "other"))[1], "label": osint.EVENT_KINDS.get(r["kind"], (r["kind"],))[0],
                             "subkind": r["subkind"], "deaths": r["deaths"], "place": r["place"], "admin1": r["admin1"],
                             "actors": r["actors"], "note": r["note"], "source": r["source_id"]}} for r in got]
    return {"type": "FeatureCollection", "features": feats, "count": len(feats), "from": _iso(start), "to": _iso(stop),
            "newest": _iso(newest), "loaded": True, "capped": len(feats) >= limit}


# ----------------------------------------------------------------------------- a country month by month
CW_SCORE = {"deteriorated": -1, "risk_alert": -1, "unchanged": 0, "improved": 1, "resolution_opportunity": 1}


def country_months(rows: Rows, entity: str, months: int = 24) -> dict:
    """A country's months: deaths in fighting (UCDP and ACLED, apart), ACLED events by kind, internet outages,
    sanctions newly listed, and the CrisisWatch rating, with months where the rating and the events disagree."""
    since = (date.today().replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    out: dict[str, dict] = {}

    def m(key: str) -> dict:
        return out.setdefault(key, {"month": key, "ucdp_deaths": None, "acled_deaths": None, "violence": 0, "protests": 0,
                                    "riots": 0, "outages": 0, "outage_causes": [], "sanctions_added": 0, "crisiswatch": None,
                                    "crisiswatch_text": None, "civilians": None})

    for r in _safe(rows, """SELECT strftime(day, '%Y-%m') AS m, source_id, kind, count(*) AS n, sum(deaths) AS deaths,
            sum(civilians) AS civ FROM conflict_events WHERE entity_id = ? AND day >= ? GROUP BY 1, 2, 3""", [entity, since]):
        row = m(r["m"])
        if r["source_id"] in ("ucdp_ged", "ucdp_candidate"):
            row["ucdp_deaths"] = (row["ucdp_deaths"] or 0) + (r["deaths"] or 0)
            if r["kind"] == "onesided":
                row["civilians"] = (row["civilians"] or 0) + (r["deaths"] or 0)
        elif r["source_id"] == "acled":
            if r["kind"] in osint.VIOLENCE:
                row["acled_deaths"] = (row["acled_deaths"] or 0) + (r["deaths"] or 0)
                row["violence"] += r["n"]
            elif r["kind"] == "protest":
                row["protests"] += r["n"]
            elif r["kind"] == "riot":
                row["riots"] += r["n"]
    for r in _safe(rows, """SELECT strftime(start_date, '%Y-%m') AS m, subkind, count(*) AS n FROM events
            WHERE entity_id = ? AND kind = 'outage' AND start_date >= ? GROUP BY 1, 2""", [entity, since]):
        row = m(r["m"])
        row["outages"] += r["n"]
        if r["subkind"] and r["subkind"] not in row["outage_causes"]:
            row["outage_causes"].append(r["subkind"])
    for r in _safe(rows, """SELECT strftime(first_seen, '%Y-%m') AS m, count(*) AS n FROM sanction_listings
            WHERE list_contains(string_split(targets, ','), ?) AND first_seen >= ? GROUP BY 1""", [entity, since]):
        m(r["m"])["sanctions_added"] += r["n"]
    for r in _safe(rows, """SELECT strftime(start_date, '%Y-%m') AS m, subkind, detail FROM events
            WHERE entity_id = ? AND kind = 'crisiswatch' AND start_date >= ?""", [entity, since]):
        row = m(r["m"])
        row["crisiswatch"], row["crisiswatch_text"] = r["subkind"], (r["detail"] or "")[:600] or None
    items = [out[k] for k in sorted(out)]
    _flag(items)
    has = {"ucdp": any(i["ucdp_deaths"] is not None for i in items), "acled": any(i["acled_deaths"] is not None or i["protests"]
           for i in items), "outages": any(i["outages"] for i in items), "sanctions": any(i["sanctions_added"] for i in items),
           "crisiswatch": any(i["crisiswatch"] for i in items)}
    return {"entity_id": entity, "since": _iso(since), "months": items, "has": has}


def _activity(i: dict) -> float:
    return max(i["ucdp_deaths"] or 0, i["acled_deaths"] or 0) + i["violence"] + 0.2 * (i["protests"] + i["riots"])


def _flag(items: list[dict]) -> None:
    """Mark months where CrisisWatch and the events point different ways: rated worse while events fell to
    under two-thirds of the three months before, or rated better while they rose by half or more."""
    for n, i in enumerate(items):
        i["mismatch"] = None
        score = CW_SCORE.get(i["crisiswatch"] or "")
        before = items[max(0, n - 3):n]
        if score in (None, 0) or len(before) < 2:
            continue
        base = sum(_activity(b) for b in before) / len(before)
        now = _activity(i)
        if base < 5 and now < 5:
            continue
        if score < 0 and now < base * 2 / 3:
            i["mismatch"] = "Rated worse, but recorded violence fell"
        elif score > 0 and now >= base * 1.5:
            i["mismatch"] = "Rated better, but recorded violence rose"


def crisiswatch_month(rows: Rows, month: str) -> dict:
    """For one month on the CrisisWatch map: each country's deaths, events, outages and new sanctions, and
    whether its rating and the recorded events point different ways (against the three months before)."""
    y, mo = int(month[:4]), int(month[5:7])
    first = date(y, mo, 1)
    nxt = date(y + (mo == 12), mo % 12 + 1, 1)
    back = date(y - (mo <= 3), (mo - 4) % 12 + 1, 1)  # three months before
    cells: dict[str, dict[str, dict]] = defaultdict(dict)

    def cell(ent: str, m: str) -> dict:
        return cells[ent].setdefault(m, {"month": m, "ucdp_deaths": None, "acled_deaths": None, "violence": 0, "protests": 0,
                                         "riots": 0, "outages": 0, "sanctions_added": 0, "crisiswatch": None})

    for r in _safe(rows, """SELECT entity_id, strftime(day, '%Y-%m') AS m, source_id, kind, count(*) AS n, sum(deaths) AS d
            FROM conflict_events WHERE day >= ? AND day < ? AND entity_id IS NOT NULL GROUP BY 1, 2, 3, 4""", [back, nxt]):
        c = cell(r["entity_id"], r["m"])
        if r["source_id"].startswith("ucdp"):
            c["ucdp_deaths"] = (c["ucdp_deaths"] or 0) + (r["d"] or 0)
        elif r["kind"] in osint.VIOLENCE:
            c["acled_deaths"] = (c["acled_deaths"] or 0) + (r["d"] or 0)
            c["violence"] += r["n"]
        elif r["kind"] == "protest":
            c["protests"] += r["n"]
        elif r["kind"] == "riot":
            c["riots"] += r["n"]
    for r in _safe(rows, """SELECT entity_id, strftime(start_date, '%Y-%m') AS m, kind, subkind, count(*) AS n FROM events
            WHERE kind IN ('outage', 'crisiswatch') AND start_date >= ? AND start_date < ? GROUP BY 1, 2, 3, 4""", [back, nxt]):
        c = cell(r["entity_id"], r["m"])
        if r["kind"] == "outage":
            c["outages"] += r["n"]
        else:
            c["crisiswatch"] = r["subkind"]
    for r in _safe(rows, """SELECT t AS entity_id, count(*) AS n FROM (SELECT unnest(string_split(targets, ',')) AS t
            FROM sanction_listings WHERE first_seen >= ? AND first_seen < ?) WHERE t <> '' GROUP BY 1""", [first, nxt]):
        cell(r["entity_id"], month)["sanctions_added"] += r["n"]
    months = []
    d = back
    while d < nxt:
        months.append(d.strftime("%Y-%m"))
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    by: dict[str, dict] = {}
    for ent, got in cells.items():
        items = [got.get(m) or {"month": m, "ucdp_deaths": None, "acled_deaths": None, "violence": 0, "protests": 0, "riots": 0,
                                "outages": 0, "sanctions_added": 0, "crisiswatch": None} for m in months]
        _flag(items)
        now = items[-1]
        if not any((now["ucdp_deaths"], now["acled_deaths"], now["violence"], now["protests"], now["riots"], now["outages"],
                    now["sanctions_added"], now["mismatch"])):
            continue
        by[ent] = {"ucdp_deaths": now["ucdp_deaths"], "acled_deaths": now["acled_deaths"], "events": now["violence"],
                   "protests": now["protests"] + now["riots"], "outages": now["outages"], "sanctions_added": now["sanctions_added"],
                   "mismatch": now["mismatch"]}
    return {"month": month, "countries": by}


# ----------------------------------------------------------------------------- war trackers
def wars(rows: Rows) -> dict:
    out = []
    for w in osint.wars():
        latest = _safe(rows, """SELECT side, basis, count, day FROM war_losses WHERE war_id = ? AND category = 'total'
            AND status = 'total' QUALIFY row_number() OVER (PARTITION BY side, basis ORDER BY day DESC) = 1""", [w["id"]])
        area = _safe(rows, "SELECT day, area_km2 FROM war_areas WHERE war_id = ? ORDER BY day DESC LIMIT 1", [w["id"]])
        out.append({**{k: w.get(k) for k in ("id", "name", "short", "sides", "note", "map")}, "began": _iso(w.get("began")),
                    "latest": [{**r, "day": _iso(r["day"])} for r in latest],
                    "area": {"day": _iso(area[0]["day"]), "km2": area[0]["area_km2"]} if area else None})
    return {"wars": out}


def war(rows: Rows, war_id: str) -> dict | None:
    w = osint.war(war_id)
    if not w:
        return None
    losses = _safe(rows, """SELECT side, basis, category, status, day, count, source_id FROM war_losses WHERE war_id = ?
        ORDER BY day""", [war_id])
    series: dict[str, dict] = {}
    for r in losses:
        key = f"{r['side']}|{r['basis']}|{r['category']}|{r['status']}"
        s = series.setdefault(key, {"side": r["side"], "basis": r["basis"], "category": r["category"], "status": r["status"],
                                    "source": r["source_id"], "points": []})
        s["points"].append([_iso(r["day"]), r["count"]])
    latest: dict[str, dict] = {}
    for s in series.values():
        if s["status"] != "total" or not s["points"]:
            continue
        d = latest.setdefault(s["category"], {"category": s["category"], "label": osint.LOSS_CATEGORIES.get(s["category"], s["category"])})
        d[f"{s['side']}_{s['basis']}"] = s["points"][-1][1]
        d[f"{s['side']}_{s['basis']}_day"] = s["points"][-1][0]
        # the change over the last 30 days the series covers
        cut = (date.fromisoformat(s["points"][-1][0]) - timedelta(days=30)).isoformat()
        prior = [p for p in s["points"] if p[0] <= cut]
        d[f"{s['side']}_{s['basis']}_30d"] = s["points"][-1][1] - prior[-1][1] if prior else None
    statuses = {}
    for s in series.values():
        if s["basis"] == "seen" and s["category"] == "total" and s["points"]:
            statuses.setdefault(s["side"], {})[s["status"]] = s["points"][-1][1]
    areas = _safe(rows, "SELECT day, area_km2, holder, land_of FROM war_areas WHERE war_id = ? ORDER BY day", [war_id])
    aid = []
    if w.get("aid"):
        aid = _safe(rows, """SELECT s.entity_id, s.indicator_id, s.value, year(s.period_start) AS year, e.short_name AS name
            FROM series s JOIN entities e USING (entity_id) WHERE s.indicator_id IN ('ukraine_aid_military_eur',
            'ukraine_aid_financial_eur', 'ukraine_aid_humanitarian_eur', 'ukraine_aid_total_eur') AND s.breakdown = ''
            QUALIFY row_number() OVER (PARTITION BY s.entity_id, s.indicator_id ORDER BY s.period_start DESC) = 1""")
    donors: dict[str, dict] = {}
    for r in aid:
        d = donors.setdefault(r["entity_id"], {"entity_id": r["entity_id"], "name": r["name"], "year": r["year"]})
        d[r["indicator_id"].removeprefix("ukraine_aid_").removesuffix("_eur")] = r["value"]
    events = _safe(rows, """SELECT strftime(day, '%Y-%m') AS m, source_id, sum(deaths) AS deaths, count(*) AS n
        FROM conflict_events WHERE entity_id IN (SELECT unnest(?)) AND day >= ? AND kind IN (SELECT unnest(?))
        GROUP BY 1, 2 ORDER BY 1""", [w["sides"], w.get("began") or date(2000, 1, 1), sorted(osint.VIOLENCE)])
    return {**{k: w.get(k) for k in ("id", "name", "short", "sides", "note", "map", "oryx")}, "began": _iso(w.get("began")),
            "series": list(series.values()), "latest": sorted(latest.values(), key=lambda d: list(osint.LOSS_CATEGORIES).index(d["category"])
                                                              if d["category"] in osint.LOSS_CATEGORIES else 99),
            "statuses": statuses, "areas": [[_iso(a["day"]), a["area_km2"]] for a in areas],
            "front": {"holder": areas[-1]["holder"], "land_of": areas[-1]["land_of"]} if areas else None,
            "aid": sorted(donors.values(), key=lambda d: -(d.get("total") or 0)),
            "fighting": [{"month": e["m"], "source": e["source_id"], "deaths": e["deaths"], "events": e["n"]} for e in events]}


def front_line(rows: Rows, war_id: str, day: str | None = None) -> dict:
    """The held land on a day (the nearest kept day on or before it, else the latest)."""
    where, params = "layer_id = 'front_line' AND feature_id LIKE ?", [f"{war_id}:%"]
    if day:
        where += " AND feature_id <= ?"
        params.append(f"{war_id}:{day}")
    got = _safe(rows, f"SELECT feature_id, name, props, geojson FROM geo_features WHERE {where} ORDER BY feature_id DESC LIMIT 1", params)
    if not got:
        return {"type": "FeatureCollection", "features": []}
    g = got[0]
    days = [r["feature_id"].split(":", 1)[1] for r in _safe(rows, """SELECT feature_id FROM geo_features
        WHERE layer_id = 'front_line' AND feature_id LIKE ? ORDER BY feature_id""", [f"{war_id}:%"])]
    return {"type": "FeatureCollection", "days": days,
            "features": [{"type": "Feature", "geometry": json.loads(g["geojson"]), "properties": {**json.loads(g["props"] or "{}"), "name": g["name"]}}]}


# ----------------------------------------------------------------------------- sanctions now
def sanctions(rows: Rows, schema: str | None = None) -> dict:
    where, params = "", []
    if schema:
        where, params = "WHERE schema = ?", [schema]
    counts = _safe(rows, f"""SELECT target, authority, sum(listed) AS listed, sum(added_365) AS added FROM sanction_counts
        {where} GROUP BY 1, 2""", params)
    if not counts:
        return {"loaded": False, "authorities": [], "rows": [], "recent": [], "schemas": []}
    names = {r["entity_id"]: r["short_name"] for r in _safe(rows, "SELECT entity_id, short_name FROM entities")}
    by: dict[str, dict] = {}
    for c in counts:
        if c["target"] == "none":
            continue
        t = by.setdefault(c["target"], {"target": c["target"], "name": names.get(c["target"], c["target"]), "cells": {}, "total": 0, "added": 0})
        t["cells"][c["authority"]] = {"listed": c["listed"], "added": c["added"]}
        t["total"] += c["listed"]
        t["added"] += c["added"]
    auths = [{"id": a, "name": osint.AUTHORITY_NAMES.get(a, a), "key": i < 4}
             for i, a in enumerate(osint.MATRIX_AUTHORITIES)]
    recent = _safe(rows, f"""SELECT os_id, name, schema, targets, authorities, first_seen FROM sanction_listings
        {where} ORDER BY first_seen DESC NULLS LAST LIMIT 60""", params)
    schemas = _safe(rows, "SELECT schema, sum(listed) AS n FROM sanction_counts GROUP BY 1 ORDER BY 2 DESC")
    return {"loaded": True, "authorities": auths, "authority_names": osint.AUTHORITY_NAMES,
            "rows": sorted(by.values(), key=lambda t: -t["total"]),
            "recent": [{**r, "first_seen": _iso(r["first_seen"]), "targets": [x for x in (r["targets"] or "").split(",") if x],
                        "authorities": [x for x in (r["authorities"] or "").split(",") if x]} for r in recent],
            "schemas": schemas}


def sanctions_search(rows: Rows, q: str, limit: int = 50) -> list[dict]:
    got = _safe(rows, """SELECT os_id, name, schema, targets, authorities, first_seen FROM sanction_listings
        WHERE name ILIKE ? ORDER BY first_seen DESC NULLS LAST LIMIT ?""", [f"%{q}%", limit])
    return [{**r, "first_seen": _iso(r["first_seen"]), "url": f"https://www.opensanctions.org/entities/{r['os_id']}/"} for r in got]


_SHIP_IDS: tuple[float, set[str]] | None = None


def sanctioned_ship_ids(rows: Rows) -> set[str]:
    """IMO and MMSI numbers of sanctioned ships, cached for an hour."""
    import time
    global _SHIP_IDS
    if _SHIP_IDS and time.time() - _SHIP_IDS[0] < 3600:
        return _SHIP_IDS[1]
    ids = set()
    for r in _safe(rows, "SELECT identifiers FROM sanction_listings WHERE schema = 'Vessel' AND identifiers IS NOT NULL"):
        ids.update(x for x in r["identifiers"].split(",") if x)
    _SHIP_IDS = (time.time(), ids)
    return ids


# ----------------------------------------------------------------------------- military strength and arms deals
def military(rows: Rows, entities: list[str]) -> dict:
    """Global Firepower's counts for the countries asked for (latest edition each), with the change since the
    edition before, each measure's rank among all countries, and a second source where the app has one."""
    latest = _safe(rows, "SELECT max(edition) AS e FROM military_strength")
    edition = latest[0]["e"] if latest else None
    if not edition:
        return {"loaded": False, "measures": [], "countries": []}
    all_rows = _safe(rows, """SELECT entity_id, edition, measure, value FROM military_strength
        WHERE edition >= ? - 2""", [edition])
    held: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for r in all_rows:
        held[(r["entity_id"], r["measure"])][r["edition"]] = r["value"]
    now: dict[tuple[str, str], tuple[int, float]] = {}
    before: dict[tuple[str, str], float] = {}
    for k, eds in held.items():
        order = sorted(eds, reverse=True)
        now[k] = (order[0], eds[order[0]])
        if len(order) > 1:
            before[k] = eds[order[1]]
    ranks: dict[tuple[str, str], tuple[int, int]] = {}
    by_measure: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (ent, mid), (_, v) in now.items():
        by_measure[mid].append((ent, v))
    for mid, vals in by_measure.items():
        lower_better = mid == "gfp_power_index"
        ordered = sorted(vals, key=lambda x: x[1] if lower_better else -x[1])
        for i, (ent, v) in enumerate(ordered):
            ranks[(ent, mid)] = (i + 1, len(ordered))
    also = {}
    if entities:
        for r in _safe(rows, """SELECT entity_id, indicator_id, value, year(period_start) AS year FROM series
                WHERE indicator_id IN (SELECT unnest(?)) AND entity_id IN (SELECT unnest(?)) AND breakdown = ''
                AND variant = 'central' QUALIFY row_number() OVER (PARTITION BY entity_id, indicator_id ORDER BY period_start DESC) = 1""",
                       [sorted(set(osint.GFP_ALSO.values())), entities]):
            also[(r["entity_id"], r["indicator_id"])] = (r["value"], r["year"])
    names = {r["entity_id"]: r["short_name"] for r in _safe(rows, "SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [entities or [""]])}
    measures = [{"id": mid, "name": name, "unit": unit, "group": group, "group_name": osint.GFP_GROUPS[group],
                 "also": osint.GFP_ALSO.get(mid)} for mid, _, name, unit, group in osint.GFP_MEASURES]
    countries = []
    for ent in entities:
        vals = {}
        for m in measures:
            k = (ent, m["id"])
            if k not in now:
                continue
            v = now[k][1]
            alt = also.get((ent, m["also"])) if m["also"] else None
            vals[m["id"]] = {"value": v, "edition": now[k][0], "before": before.get(k), "rank": ranks.get(k, (None, None))[0],
                             "of": ranks.get(k, (None, None))[1], "also": {"value": alt[0], "year": alt[1]} if alt else None}
        countries.append({"entity_id": ent, "name": names.get(ent, ent), "values": vals})
    return {"loaded": True, "edition": edition, "measures": measures, "countries": countries}


def military_map(rows: Rows, measure: str) -> dict:
    got = _safe(rows, """SELECT entity_id, value, edition FROM military_strength WHERE measure = ?
        QUALIFY row_number() OVER (PARTITION BY entity_id ORDER BY edition DESC) = 1""", [measure])
    return {"measure": measure, "values": {r["entity_id"]: r["value"] for r in got},
            "edition": max((r["edition"] for r in got), default=None)}


def arms(rows: Rows, entity: str, since: int = 2000) -> dict:
    """Who a country buys major weapons from and sells them to (SIPRI), by trend-indicator value since `since`."""
    def partners(col: str, other: str) -> list[dict]:
        return _safe(rows, f"""SELECT {other} AS partner, sum(coalesce(tiv, 0)) AS tiv, count(*) AS deals,
            max(coalesce(delivered_to, ordered)) AS last FROM arms_deals WHERE {col} = ? AND coalesce(delivered_to, ordered, 0) >= ?
            GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", [entity, since])
    deals = _safe(rows, """SELECT supplier, recipient, ordered, delivered_from, delivered_to, weapon, description, number, tiv,
        status FROM arms_deals WHERE (supplier = ? OR recipient = ?) ORDER BY coalesce(delivered_to, ordered) DESC NULLS LAST
        LIMIT 40""", [entity, entity])
    return {"entity_id": entity, "since": since, "suppliers": partners("recipient", "supplier"),
            "buyers": partners("supplier", "recipient"), "deals": deals}
