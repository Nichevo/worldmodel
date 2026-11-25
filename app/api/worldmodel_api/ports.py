"""Port pressure: ports and chokepoints each week against normal (traffic_weekly), what events
did to them (traffic_impacts), the typical shape of a hit by kind of event, how fast each
port gets back, the connections between ports (port_links) and the map layer of ports
against normal. Each function takes `q`, the API's rows(sql, params) helper. Tables are
absent before schema 1.16.0; every function then answers empty."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

Q = Callable[[str, list], list[dict]]

TYPES = ("container", "dry_bulk", "general_cargo", "roro", "tanker")
TYPE_NAMES = {"container": "Container", "dry_bulk": "Dry bulk", "general_cargo": "General cargo", "roro": "Ro-ro (vehicles)",
              "tanker": "Tanker"}
HAZARD_NAMES = {"cyclone": "Cyclones", "earthquake": "Earthquakes", "flood": "Floods", "drought": "Droughts",
                "volcano": "Volcanoes", "wildfire": "Wildfires", "tsunami": "Tsunamis", "other": "Other disasters"}
BEFORE = 4  # the curve starts 4 weeks before an event


def _has(q: Q, table: str) -> bool:
    try:
        q(f"SELECT 1 FROM {table} LIMIT 1", [])
        return True
    except Exception:  # noqa: BLE001 - warehouses before 1.16.0
        return False


def _layer_props(q: Q, layer: str) -> dict[str, dict]:
    try:
        row = q("SELECT geojson FROM layers WHERE layer_id = ?", [layer])
    except Exception:  # noqa: BLE001
        return {}
    if not row:
        return {}
    out = {}
    for f in json.loads(row[0]["geojson"]).get("features") or []:
        p = dict(f.get("properties") or {})
        c = (f.get("geometry") or {}).get("coordinates") or [None, None]
        p["lon"], p["lat"] = c[0], c[1]
        out[p.get("id")] = p
    return out


def _r(v, n=1):
    return None if v is None else round(v, n)


def places(q: Q, entity: str | None = None, end: date | None = None, weeks: int = 4) -> list[dict]:
    """Every port and chokepoint with a weekly series: its name, country, ships a week over
    `weeks` full weeks against normal, and its usual ships a week (the year before). The weeks
    end with the last one stored, or with the week holding `end` for a look back in time."""
    if not _has(q, "traffic_weekly"):
        return []
    last = q("SELECT max(week) AS w FROM traffic_weekly", [])[0]["w"]
    if not last:
        return []
    if end is not None:
        first = q("SELECT min(week) AS w FROM traffic_weekly", [])[0]["w"]
        want = end - timedelta(days=end.weekday())  # weeks start on Monday
        last = max(first, min(last, want))
    weeks = max(1, min(int(weeks), 26))
    a, b = last - timedelta(days=7 * (weeks - 1)), last - timedelta(days=364)
    where, params = "WHERE week <= ?", [a, a, b, last]
    if entity:
        where, params = where + " AND entity_id = ?", [*params, entity]
    got = q(f"""SELECT place_kind, place_id, any_value(entity_id) AS entity_id,
                       sum(value) FILTER (WHERE week >= ? AND normal IS NOT NULL) AS now,
                       sum(normal) FILTER (WHERE week >= ? AND normal IS NOT NULL) AS normal_now,
                       avg(value) FILTER (WHERE week >= ?) AS weekly
                FROM traffic_weekly {where} GROUP BY 1, 2""", params)
    ports, chokes = _layer_props(q, "ports"), _layer_props(q, "chokepoints")
    out = []
    for g in got:
        p = (ports if g["place_kind"] == "port" else chokes).get(g["place_id"], {})
        vs = round(100 * (g["now"] / g["normal_now"] - 1), 1) if g["now"] is not None and g["normal_now"] else None
        out.append({"kind": g["place_kind"], "id": g["place_id"], "name": p.get("name") or g["place_id"],
                    "entity_id": g["entity_id"] or p.get("country"), "weekly": _r(g["weekly"]), "vs_normal": vs,
                    "lat": p.get("lat"), "lon": p.get("lon")})
    out.sort(key=lambda r: -(r["weekly"] or 0))
    return [{**r, "as_of": (last + timedelta(days=6)).isoformat(), "from": a.isoformat()} for r in out]


def weeks_span(q: Q) -> dict:
    """The first and last weeks stored, for the map's week picker."""
    if not _has(q, "traffic_weekly"):
        return {"first": None, "last": None}
    r = q("SELECT min(week) AS a, max(week) AS b FROM traffic_weekly WHERE place_kind = 'port'", [])[0]
    return {"first": r["a"].isoformat() if r["a"] else None, "last": r["b"].isoformat() if r["b"] else None}


def place(q: Q, kind: str, ident: str, start: int = 2019, event: str | None = None) -> dict:
    """One port or chokepoint: weekly ships, tonnes and normal; its events and their impacts;
    its ship types, connections, a line about it; and, when an event is picked, how the
    ports it connects to fared over the same weeks."""
    empty = {"kind": kind, "id": ident, "weeks": [], "impacts": [], "links": [], "mix": [], "disruptions": []}
    if not _has(q, "traffic_weekly"):
        return empty
    weeks = q("""SELECT week, value, tonnes, normal, ratio FROM traffic_weekly
                 WHERE place_kind = ? AND place_id = ? AND year(week) >= ? ORDER BY week""", [kind, ident, start])
    props = (_layer_props(q, "ports") if kind == "port" else _layer_props(q, "chokepoints")).get(ident, {})
    out = {**empty, "name": props.get("name") or ident, "entity_id": props.get("country"), "fact": props.get("fact"),
           "top": props.get("top"), "lat": props.get("lat"), "lon": props.get("lon"),
           "weeks": [{"week": w["week"].isoformat(), "value": w["value"], "tonnes": w["tonnes"], "normal": _r(w["normal"]),
                      "ratio": _r(w["ratio"], 3)} for w in weeks]}
    if _has(q, "traffic_impacts"):
        out["impacts"] = [{**i, "start_date": i["start_date"].isoformat(), "end_date": i["end_date"].isoformat() if i["end_date"] else None,
                           "worst_week": i["worst_week"].isoformat() if i["worst_week"] else None,
                           "curve": json.loads(i["curve"] or "[]")}
                          for i in q("""SELECT impact_id, event_key, origin, title, hazard, start_date, end_date, base_weekly,
                                               worst_pct, worst_week, lost_calls, lost_tonnes, recover_days, catchup_pct, clear, curve
                                        FROM traffic_impacts WHERE place_kind = ? AND place_id = ? ORDER BY start_date""",
                                     [kind, ident])]
    if kind == "port" and _has(q, "port_daily"):
        last = q("SELECT max(day) AS d FROM port_daily WHERE port_id = ?", [ident])[0]["d"]
        if last:
            mix = q(f"""SELECT {', '.join(f'sum({t}) AS {t}' for t in TYPES)}, sum(calls) AS calls,
                               sum(import_t) AS import_t, sum(export_t) AS export_t
                        FROM port_daily WHERE port_id = ? AND day > ?""", [ident, last - timedelta(days=365)])[0]
            total = sum(mix[t] or 0 for t in TYPES) or 1
            out["mix"] = [{"type": t, "name": TYPE_NAMES[t], "calls": mix[t] or 0, "share": round(100 * (mix[t] or 0) / total, 1)}
                          for t in TYPES if mix[t]]
            out["year_calls"], out["year_import_t"], out["year_export_t"] = mix["calls"], mix["import_t"], mix["export_t"]
            out["monthly_types"] = q(f"""SELECT strftime(date_trunc('month', day), '%Y-%m') AS month,
                                                {', '.join(f'sum({t}) AS {t}' for t in TYPES)}
                                         FROM port_daily WHERE port_id = ? AND year(day) >= ? GROUP BY 1 ORDER BY 1""",
                                      [ident, start])
    if kind == "port" and _has(q, "port_links"):
        out["links"] = links(q, ident)
    if kind == "port" and _has(q, "port_disruptions"):
        out["disruptions"] = [{**d, "start_date": d["start_date"].isoformat(), "end_date": d["end_date"].isoformat() if d["end_date"] else None}
                              for d in q("""SELECT event_id, name, hazard, alert, severity, start_date, end_date, distance_km
                                            FROM port_disruptions WHERE port_id = ? ORDER BY start_date""", [ident])]
    if event:
        out["knock_on"] = knock_on(q, kind, ident, event)
    out["expect"] = expect_now(q, out)
    return out


def links(q: Q, ident: str, n: int = 12) -> list[dict]:
    """The ports most tied to this one by ship: where its ships go next (out) and where the
    ships it gets come from (in), by capacity at risk, with sailing days."""
    names = _layer_props(q, "ports")
    out = []
    for direction, me, other in (("out", "from_port", "to_port"), ("in", "to_port", "from_port")):
        for r in q(f"""SELECT {other} AS port, transit_days, capacity_at_risk, share_at_risk FROM port_links
                       WHERE {me} = ? ORDER BY capacity_at_risk DESC NULLS LAST LIMIT {int(n)}""", [ident]):
            p = names.get(r["port"], {})
            out.append({"direction": direction, "port_id": r["port"], "name": p.get("name") or r["port"],
                        "entity_id": p.get("country"), "days": _r(r["transit_days"]), "capacity_t": _r(r["capacity_at_risk"], 0),
                        "share": _r(100 * r["share_at_risk"], 2) if r["share_at_risk"] is not None else None,
                        "lat": p.get("lat"), "lon": p.get("lon")})
    return out


def knock_on(q: Q, kind: str, ident: str, impact_id: str) -> list[dict]:
    """For one impact at this place: the ports it is most tied to, and their ships against normal
    over the event's weeks and the two after (re-routing shows as a rise, knock-on as a fall)."""
    if kind != "port" or not _has(q, "port_links"):
        return []
    imp = q("SELECT start_date, end_date FROM traffic_impacts WHERE impact_id = ?", [impact_id])
    if not imp:
        return []
    s = imp[0]["start_date"] - timedelta(days=imp[0]["start_date"].weekday())
    e = (imp[0]["end_date"] or imp[0]["start_date"]) + timedelta(days=14)
    got = []
    for r in links(q, ident, 10):
        w = q("""SELECT sum(value) AS v, sum(normal) AS n FROM traffic_weekly
                 WHERE place_kind = 'port' AND place_id = ? AND week BETWEEN ? AND ? AND normal IS NOT NULL""",
              [r["port_id"], s, e])[0]
        if w["v"] is not None and w["n"]:
            got.append({**r, "vs_normal": round(100 * (w["v"] / w["n"] - 1), 1)})
    return got


def expect_now(q: Q, p: dict) -> dict | None:
    """When an event at this place started in the last 8 weeks: the typical curve for that kind
    of event, scaled to the expected ships, to draw ahead of the real line."""
    recent = [i for i in p.get("impacts") or [] if i["start_date"] >= (date.today() - timedelta(days=56)).isoformat()]
    if not recent:
        return None
    last = recent[-1]
    pat = next((c for c in patterns(q)["curves"] if c["hazard"] == last["hazard"]), None)
    if not pat or pat["n"] < 3:
        return None
    start = date.fromisoformat(last["start_date"])
    start -= timedelta(days=start.weekday())
    return {"title": last["title"], "hazard": last["hazard"], "n": pat["n"],
            "weeks": [{"week": (start + timedelta(days=7 * (k - BEFORE))).isoformat(),
                       "value": _r(m * last["base_weekly"]) if m is not None else None}
                      for k, m in enumerate(pat["mean"]) if k >= BEFORE]}


def impacts(q: Q, entity: str | None = None, hazard: str | None = None, since: int | None = None, kind: str | None = None,
            clear: bool = True, limit: int = 200) -> list[dict]:
    """The biggest hits: event impacts by how many ship calls were lost, worst first."""
    if not _has(q, "traffic_impacts"):
        return []
    where, params = ["1=1"], []
    if clear:
        where.append("clear")
    if entity:
        where.append("entity_id = ?")
        params.append(entity)
    if hazard:
        where.append("hazard = ?")
        params.append(hazard)
    if since:
        where.append("year(start_date) >= ?")
        params.append(since)
    if kind:
        where.append("place_kind = ?")
        params.append(kind)
    got = q(f"""SELECT impact_id, event_key, origin, title, hazard, entity_id, start_date, end_date, place_kind, place_id, place_name,
                       base_weekly, worst_pct, worst_week, lost_calls, lost_tonnes, recover_days, catchup_pct, clear
                FROM traffic_impacts WHERE {' AND '.join(where)}
                ORDER BY lost_calls DESC NULLS LAST, worst_pct LIMIT {int(limit)}""", params)
    return [{**g, "start_date": g["start_date"].isoformat(), "end_date": g["end_date"].isoformat() if g["end_date"] else None,
             "worst_week": g["worst_week"].isoformat() if g["worst_week"] else None} for g in got]


def _quantile(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def patterns(q: Q, min_events: int = 2) -> dict:
    """What usually happens: for each kind of event, the average ships against expected week by
    week (weeks -4 to +16) with the middle half of events, how many, the median worst week and
    days to recover; and each port's record of getting back (its median days to recover)."""
    if not _has(q, "traffic_impacts"):
        return {"curves": [], "resilience": []}
    got = q("""SELECT hazard, place_kind, place_id, place_name, entity_id, base_weekly, worst_pct, recover_days, curve
               FROM traffic_impacts WHERE clear""", [])
    by: dict[str, list[dict]] = defaultdict(list)
    for g in got:
        by[g["hazard"] or "other"].append(g)
    curves = []
    for hz, rows in by.items():
        if len(rows) < min_events:
            continue
        cs = [json.loads(r["curve"] or "[]") for r in rows]
        width = max((len(c) for c in cs), default=0)
        mean, p25, p75 = [], [], []
        for k in range(width):
            vals = [c[k] for c in cs if k < len(c) and c[k] is not None]
            mean.append(round(statistics.fmean(vals), 3) if vals else None)
            p25.append(_r(_quantile(vals, 0.25), 3))
            p75.append(_r(_quantile(vals, 0.75), 3))
        rec = [r["recover_days"] for r in rows if r["recover_days"] is not None]
        curves.append({"hazard": hz, "name": HAZARD_NAMES.get(hz, hz[:1].upper() + hz[1:]), "n": len(rows),
                       "worst_median": _r(statistics.median([r["worst_pct"] for r in rows])),
                       "recover_median": statistics.median(rec) if rec else None, "not_recovered": len(rows) - len(rec),
                       "mean": mean, "p25": p25, "p75": p75})
    curves.sort(key=lambda c: -c["n"])
    per: dict[tuple, list[dict]] = defaultdict(list)
    for g in got:
        per[(g["place_kind"], g["place_id"])].append(g)
    res = []
    for (kind, pid), rows in per.items():
        rec = [r["recover_days"] for r in rows if r["recover_days"] is not None]
        res.append({"kind": kind, "id": pid, "name": rows[0]["place_name"], "entity_id": rows[0]["entity_id"],
                    "events": len(rows), "recover_median": statistics.median(rec) if rec else None,
                    "not_recovered": len(rows) - len(rec), "weekly": _r(statistics.fmean(r["base_weekly"] for r in rows)),
                    "worst_median": _r(statistics.median([r["worst_pct"] for r in rows]))})
    # Ranked against ports of a like size: quarter by ships a week
    sized = sorted([r for r in res if r["weekly"]], key=lambda r: r["weekly"])
    for i, r in enumerate(sized):
        r["size_band"] = 1 + 4 * i // max(len(sized), 1)
    res.sort(key=lambda r: (r["recover_median"] is None, r["recover_median"] or 0, -r["events"]))
    return {"curves": curves, "resilience": res, "weeks_before": BEFORE}


def layer(q: Q, end: date | None = None, weeks: int = 4) -> dict:
    """The map layer 'Ports against normal': each port with a weekly series, its ships against
    normal (percent) over `weeks` weeks ending with the last stored or with `end`, and its usual
    ships a week."""
    feats = []
    for p in places(q, end=end, weeks=weeks):
        if p["kind"] != "port" or p["lat"] is None or p["lon"] is None:
            continue
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                      "properties": {"id": p["id"], "name": p["name"], "country": p["entity_id"], "weekly": p["weekly"],
                                     "vs_normal": p["vs_normal"], "as_of": p["as_of"], "from": p["from"]}})
    return {"type": "FeatureCollection", "features": feats}


def country(q: Q, entity: str, n: int = 4) -> dict:
    """A country's busiest ports: the last 26 weeks against normal, with the events that touched them."""
    ps = [p for p in places(q, entity) if p["kind"] == "port"][:n]
    out = []
    for p in ps:
        w = q("""SELECT week, value, normal, ratio FROM traffic_weekly WHERE place_kind = 'port' AND place_id = ?
                 ORDER BY week DESC LIMIT 26""", [p["id"]])
        out.append({**p, "weeks": [{"week": r["week"].isoformat(), "value": r["value"], "normal": _r(r["normal"]),
                                    "ratio": _r(r["ratio"], 3)} for r in reversed(w)]})
    hits = impacts(q, entity=entity, limit=8)
    return {"entity": entity, "ports": out, "impacts": hits}
