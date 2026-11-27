"""The Details page behind every map layer: how many items each country (or bloc) has, per
million people and per 10,000 km², their size total where the source gives one, how that
compares with an official total, the spread of sizes or categories, and every item.

Items come from the warehouse's layer_items table (dot layers), geo_features (cables, pipelines
and street trees), the live hazard layers as the map gets them, or conflict_events. Which layers
there are and what their size and category are: worldmodel_contract.layer_details."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

from worldmodel_contract import layer_details as spec

Q = Callable[..., list[dict]]
_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()
LIVE_SECONDS = 900


def _has(q: Q, table: str) -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'", [table]))


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip().split(" ")[0]
    try:
        return float(s)
    except ValueError:
        return None


# ----------------------------------------------------------------------------- items
def items(q: Q, key: str, d: spec.LayerDetail, live: Callable[[str], dict] | None = None,
          country_of: Callable[[float, float], str | None] | None = None) -> list[dict]:
    """Every item of a layer as {item_id, name, entity_id, lat, lon, size, category, url, props};
    one per item and country. Kept per warehouse (live layers for 15 minutes)."""
    ck = (key, d.id)
    with _lock:
        hit = _cache.get(ck)
    if hit and (d.kind != "live" or time.time() - hit[0] < LIVE_SECONDS):
        return hit[1]  # type: ignore[return-value]
    got = _load(q, d, live, country_of)
    with _lock:
        _cache[ck] = (time.time(), got)
        if len(_cache) > 80:
            _cache.pop(next(iter(_cache)))
    return got


def _load(q: Q, d: spec.LayerDetail, live, country_of) -> list[dict]:
    if d.kind == "stored":
        if not _has(q, "layer_items"):
            return []
        out = q("""SELECT item_id, name, entity_id, lat, lon, size, category, url, props, placed
                   FROM layer_items WHERE layer_id = ?""", [d.id])
        for r in out:
            r["props"] = json.loads(r["props"] or "{}")
        return out
    if d.kind in ("lines", "trees"):
        if not _has(q, "geo_features"):
            return []
        out = []
        for r in q("SELECT feature_id, name, props, countries, south, north, west, east FROM geo_features WHERE layer_id = ?", [d.id]):
            p = json.loads(r["props"] or "{}")
            if d.id == "cables" and p.get("length") is not None:
                p["length_km"] = _num(p.get("length"))
            for k in ("owners", "landings"):
                if isinstance(p.get(k), list):
                    p[k] = ", ".join(str(x) for x in p[k][:8])
            ents = [c for c in str(r["countries"] or "").split(",") if c] or [None]
            base = {"item_id": r["feature_id"], "name": r["name"] or d.one, "lat": (r["south"] + r["north"]) / 2,
                    "lon": (r["west"] + r["east"]) / 2, "size": _num(p.get(d.size.prop)) if d.size else None,
                    "category": (str(p.get(d.category[0])) if d.category and p.get(d.category[0]) not in (None, "") else None),
                    "url": p.get("url"), "props": p, "placed": False}
            if d.kind == "trees":  # by council: the council stands where a country would
                base["group"] = p.get("council") or "Other"
            out += [{**base, "entity_id": e} for e in ents]
        return out
    if d.kind == "events":
        if not _has(q, "conflict_events"):
            return []
        since = (date.today() - timedelta(days=365)).isoformat()
        rows = q("""SELECT event_id AS item_id, coalesce(place, kind) AS name, entity_id, lat, lon, deaths AS size, kind AS category,
                           day, place, source_id FROM conflict_events WHERE day >= ?""", [since])
        for r in rows:
            r["props"] = {"day": str(r.pop("day")), "place": r.pop("place"), "source": r.pop("source_id")}
            r["url"], r["placed"] = None, False
        return rows
    if d.kind == "live" and live is not None:
        fc = live(d.id) or {}
        out = []
        for n, f in enumerate(fc.get("features") or []):
            c = (f.get("geometry") or {}).get("coordinates") or []
            if len(c) < 2:
                continue
            p = dict(f.get("properties") or {})
            ent = p.get("country") or (country_of(c[0], c[1]) if country_of else None)
            out.append({"item_id": str(p.get("city") or p.get("id") or n), "name": p.get("name") or d.one, "entity_id": ent,
                        "lat": c[1], "lon": c[0], "size": _num(p.get(d.size.prop)) if d.size else None,
                        "category": None, "url": None, "props": p, "placed": not p.get("country")})
        return out
    return []


# ----------------------------------------------------------------------------- figures
def _latest(q: Q, indicator: str) -> dict[str, float]:
    """Each country's latest value (up to this year) of an indicator."""
    return {r["e"]: r["v"] for r in q("""SELECT entity_id AS e, max_by(value, period_start) AS v FROM series
        WHERE indicator_id = ? AND variant = 'central' AND breakdown = '' AND year(period_start) <= year(current_date)
        GROUP BY 1""", [indicator])}


def _names(q: Q) -> dict[str, dict]:
    return {r["entity_id"]: r for r in q("SELECT entity_id, short_name AS name, type, iso2 FROM entities")}


def _total(vals: list[float], how: str) -> float | None:
    if not vals:
        return None
    return sum(vals) if how == "sum" else max(vals) if how == "max" else sum(vals) / len(vals)


def _official(o: spec.Official, raw: float | None, pop: float | None) -> float | None:
    if raw is None:
        return None
    if o.as_total == "per1000":
        return raw * pop / 1000 if pop else None
    if o.as_total == "per100k":
        return raw * pop / 100_000 if pop else None
    if o.as_total == "kw_to_mw":
        return raw / 1000
    return raw


def _summary(d: spec.LayerDetail, key: str, name: str, its: list[dict], pop: float | None, area: float | None,
             offs: list[tuple[spec.Official, float | None]]) -> dict:
    uniq = {i["item_id"]: i for i in its}.values()
    n = len(uniq)
    sizes = [i["size"] for i in uniq if i["size"] is not None]
    total = _total(sizes, d.size.total) if d.size else None
    big = max(uniq, key=lambda i: i["size"] if i["size"] is not None else float("-inf")) if sizes else None
    row = {"key": key, "name": name, "count": n, "per_m": n / pop * 1e6 if pop else None,
           "per_10k_km2": n / area * 1e4 if area else None, "with_size": len(sizes), "size_total": total,
           "size_per_1000": total / pop * 1000 if total is not None and pop and d.size and d.size.total == "sum" else None,
           "largest": {"name": big["name"], "size": big["size"]} if big else None, "official": []}
    for o, val in offs:
        mine = total if o.of == "size" else n
        row["official"].append({"value": val, "coverage": mine / val if o.coverage and val and mine is not None else None})
    return row


def detail(q: Q, key: str, layer_id: str, live=None, country_of=None) -> dict:
    """By country, by group, totals and the spread of sizes and categories for one layer."""
    d = spec.BY_ID.get(layer_id)
    if d is None:
        return {"error": spec.NOT_COUNTED.get(layer_id, f"No details for the map layer {layer_id}.")}
    its = items(q, key, d, live, country_of)
    info = _info(q, d)
    if not its:
        return {"layer": info, "totals": {"count": 0}, "countries": [], "groups": [], "sizes": [], "categories": [], "by_list": []}
    names = _names(q)
    pop, area = _latest(q, "pop_total"), _latest(q, "land_area")
    offs = {o.indicator: _latest(q, o.indicator) for o in d.official}
    by: dict[str, list[dict]] = defaultdict(list)
    for i in its:
        by[i.get("group") or i["entity_id"] or ""].append(i)
    countries = []
    for k, rows in by.items():
        if d.kind == "trees":
            countries.append(_summary(d, k, k, rows, None, None, []) | {"entity_id": rows[0]["entity_id"]})
            continue
        e = names.get(k) or {}
        countries.append(_summary(d, k, e.get("name") or ("At sea or not placed" if not k else k), rows, pop.get(k), area.get(k),
                                  [(o, _official(o, offs[o.indicator].get(k), pop.get(k))) for o in d.official])
                         | {"entity_id": k or None})
    countries.sort(key=lambda r: -r["count"])
    groups = [] if d.kind == "trees" else _groups(q, d, by, names, pop, area, offs)
    uniq = list({i["item_id"]: i for i in its}.values())
    sizes = [i["size"] for i in uniq if i["size"] is not None]
    totals = {"count": len(uniq), "countries": len([k for k in by if k]), "with_size": len(sizes),
              "size_total": _total(sizes, d.size.total) if d.size else None,
              "placed": sum(1 for i in uniq if i.get("placed")),
              "largest": (lambda b: {"name": b["name"], "size": b["size"], "entity_id": b["entity_id"]})(
                  max((i for i in uniq if i["size"] is not None), key=lambda i: i["size"])) if sizes else None}
    return {"layer": info, "totals": totals, "countries": countries, "groups": groups,
            "sizes": _bands(d, uniq), "categories": _categories(d, uniq), "by_list": _by_list(uniq)}


def _by_list(uniq: list[dict]) -> list[dict]:
    """Layers merged from several lists (hospitals): for each list, how many items it has, how many
    only it has, and how many are likely hospitals, unsure or likely clinics."""
    if not any((i.get("props") or {}).get("tier") for i in uniq[:200]):
        return []
    lists: dict[str, dict] = {}
    for i in uniq:
        p = i.get("props") or {}
        found = [x.strip() for x in str(i.get("category") or p.get("found") or "").split("+") if x.strip()]
        for name in found:
            r = lists.setdefault(name, {"list": name, "count": 0, "only": 0, "hospital": 0, "unsure": 0, "clinic": 0})
            r["count"] += 1
            r["only"] += len(found) == 1
            t = p.get("tier") or "unsure"
            r[t if t in ("hospital", "unsure", "clinic") else "unsure"] += 1
    total = {"list": "All lists", "count": len(uniq), "only": None,
             **{t: sum(1 for i in uniq if ((i.get("props") or {}).get("tier") or "unsure") == t) for t in ("hospital", "unsure", "clinic")}}
    return sorted(lists.values(), key=lambda r: -r["count"]) + [total]


def _groups(q: Q, d, by, names, pop, area, offs) -> list[dict]:
    """Blocs, continents and the other groups: their members' items together."""
    mem = defaultdict(set)
    for r in q("""SELECT group_id, member_id FROM memberships WHERE (valid_to IS NULL OR valid_to >= current_date)
                  AND (valid_from IS NULL OR valid_from <= current_date)"""):
        mem[r["group_id"]].add(r["member_id"])
    out = []
    for g, members in mem.items():
        e = names.get(g) or {}
        if e.get("type") in (None, "custom", "subnational"):
            continue
        rows = [i for m in members for i in by.get(m, [])]
        if not rows:
            continue
        p = sum(pop.get(m) or 0 for m in members) or None
        a = sum(area.get(m) or 0 for m in members) or None
        offv = []
        for o in d.official:
            vals = [_official(o, offs[o.indicator].get(m), pop.get(m)) for m in members if by.get(m)]
            vals = [v for v in vals if v is not None]
            offv.append((o, sum(vals) if vals else None))
        out.append(_summary(d, g, e.get("name") or g, rows, p, a, offv) | {"entity_id": g, "type": e.get("type")})
    out.sort(key=lambda r: -r["count"])
    return out


def _bands(d: spec.LayerDetail, uniq: list[dict]) -> list[dict]:
    if not d.size or not d.size.bands:
        return []
    edges = list(d.size.bands)
    out = [{"label": f"under {_fmt(edges[0])}", "count": 0}]
    out += [{"label": f"{_fmt(a)} to {_fmt(b)}", "count": 0} for a, b in zip(edges, edges[1:])]
    out.append({"label": f"{_fmt(edges[-1])} or more", "count": 0})
    none = 0
    for i in uniq:
        s = i["size"]
        if s is None:
            none += 1
            continue
        out[sum(1 for e in edges if s >= e)]["count"] += 1
    if none:
        out.append({"label": f"no {d.size.label.lower()} given", "count": none, "missing": True})
    return out


def _fmt(v: float) -> str:
    for div, suf in ((1e9, " bn"), (1e6, " m")):
        if abs(v) >= div:
            return f"{v / div:g}{suf}"
    return f"{v:,.0f}" if v == int(v) else f"{v:g}"


def _categories(d: spec.LayerDetail, uniq: list[dict]) -> list[dict]:
    if not d.category:
        return []
    got: dict[str, dict] = {}
    for i in uniq:
        k = i["category"] or "Not given"
        g = got.setdefault(k, {"label": k, "count": 0, "size_total": None})
        g["count"] += 1
        if i["size"] is not None and d.size and d.size.total == "sum":
            g["size_total"] = (g["size_total"] or 0) + i["size"]
    return sorted(got.values(), key=lambda g: -g["count"])


def _info(q: Q, d: spec.LayerDetail) -> dict:
    src = q("""SELECT l.name, l.description, s.short_name AS source, l.vintage FROM layers l LEFT JOIN sources s USING (source_id)
               WHERE l.layer_id = ?""", [d.id]) if d.kind == "stored" and _has(q, "layers") else []
    s = src[0] if src else {}
    return {"id": d.id, "one": d.one, "many": d.many, "kind": d.kind, "note": d.note, "name": s.get("name"),
            "description": s.get("description"), "source": s.get("source"), "vintage": s.get("vintage"),
            "by_country": d.by_country, "country_from": d.country_from,
            "size": {"label": d.size.label, "unit": d.size.unit, "decimals": d.size.decimals, "total": d.size.total}
            if d.size else None,
            "category": d.category[1] if d.category else None,
            "fields": [{"key": k, "label": label} for k, label in d.fields],
            "official": [{"indicator": o.indicator, "label": o.label, "of": o.of, "coverage": o.coverage} for o in d.official],
            "indicators": spec.indicator_ids(d), "group_label": "Council" if d.kind == "trees" else "Country"}


def list_items(q: Q, key: str, layer_id: str, country: str | None, text: str | None, sort: str, limit: int, offset: int,
               live=None, country_of=None, min_size: float | None = None, date_from: str | None = None,
               date_to: str | None = None, box: str | None = None, category: str | None = None) -> dict:
    """The items themselves, biggest (or by name, or newest) first, for one country, council or group, or all.
    min_size keeps items at least that big; date_from/date_to (YYYY-MM-DD) keep those dated within, for a
    layer with a "date" field (earthquakes). box ("west,south,east,north", west past east across the date
    line) keeps those in a map's view; category keeps those of these categories (comma-separated)."""
    d = spec.BY_ID.get(layer_id)
    if d is None:
        return {"rows": [], "total": 0}
    its = items(q, key, d, live, country_of)
    if country:
        want = set(country.split(","))
        if d.kind != "trees" and len(want) == 1:
            members = {r["member_id"] for r in q("""SELECT member_id FROM memberships WHERE group_id = ?
                       AND (valid_to IS NULL OR valid_to >= current_date)""", [country])}
            want |= members
        its = [i for i in its if (i.get("group") or i["entity_id"] or "") in want
               or (country == "-" and not i["entity_id"])]
    if text:
        t = text.lower()
        its = [i for i in its if t in str(i["name"]).lower() or t in str(i.get("category") or "").lower()]
    if min_size is not None:
        its = [i for i in its if i["size"] is not None and i["size"] >= min_size]
    inside = in_box(box)
    if inside:
        its = [i for i in its if i["lat"] is not None and i["lon"] is not None and inside(i["lon"], i["lat"])]
    categories: dict[str, list] = {}  # how many of each category, and their size together, before picking some (the key)
    counted: set = set()
    for i in its:
        if i["item_id"] not in counted:
            counted.add(i["item_id"])
            c = categories.setdefault(i.get("category") or "", [0, 0.0])
            c[0] += 1
            c[1] += i["size"] or 0
    if category:
        cats = set(category.split(","))
        its = [i for i in its if (i.get("category") or "") in cats]
    dated = any(k == "date" for k, _ in d.fields)
    day = (lambda i: str((i["props"] or {}).get("date") or ""))
    if dated and (date_from or date_to):
        its = [i for i in its if (not date_from or day(i) >= date_from) and (not date_to or day(i)[:len(date_to)] <= date_to)]
    seen: dict[str, dict] = {}
    for i in its:  # one row per item, its countries together
        r = seen.get(i["item_id"])
        if r is None:
            seen[i["item_id"]] = {**i, "countries": [i["entity_id"]] if i["entity_id"] else []}
        elif i["entity_id"] and i["entity_id"] not in r["countries"]:
            r["countries"].append(i["entity_id"])
    rows = list(seen.values())
    if sort == "name":
        rows.sort(key=lambda r: str(r["name"]).lower())
    elif sort == "date" and dated:
        rows.sort(key=lambda r: (day(r), r["size"] or 0), reverse=True)
    else:
        rows.sort(key=lambda r: (r["size"] is None, -(r["size"] or 0), str(r["name"]).lower()))
    names = _names(q)
    out = []
    for r in rows[offset:offset + limit]:
        p = r["props"] or {}
        out.append({"item_id": r["item_id"], "name": r["name"], "countries": r["countries"],
                    "country_names": [(names.get(c) or {}).get("name") or c for c in r["countries"]],
                    "lat": r["lat"], "lon": r["lon"], "size": r["size"], "category": r["category"], "url": r["url"],
                    "placed": r.get("placed"), "fields": {k: p.get(k) for k, _ in d.fields}, "group": r.get("group")})
    return {"rows": out, "total": len(rows),
            "categories": [{"category": k or None, "count": v[0], "size": round(v[1], 1)}
                           for k, v in sorted(categories.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))]}


def in_box(box: str | None) -> Callable[[float, float], bool] | None:
    """A test for "inside this map view" from "west,south,east,north" (west above east: across the date line)."""
    if not box:
        return None
    try:
        w, s, e, n = (float(x) for x in box.split(","))
    except ValueError:
        return None
    if e - w >= 360:
        return lambda x, y: s <= y <= n
    w, e = ((w + 180) % 360) - 180, ((e + 180) % 360) - 180
    if w <= e:
        return lambda x, y: s <= y <= n and w <= x <= e
    return lambda x, y: s <= y <= n and (x >= w or x <= e)


def country(q: Q, key: str, entity: str) -> list[dict]:
    """For one country: each counted layer's items there, size total, and its rank among countries."""
    if not _has(q, "layer_items"):
        return []
    got = q("""WITH c AS (SELECT layer_id, entity_id, count(DISTINCT item_id) AS n, sum(size) AS total, max(size) AS top
                          FROM layer_items WHERE entity_id IS NOT NULL GROUP BY 1, 2)
               SELECT layer_id, n, total, top, rank, of FROM (
                   SELECT *, rank() OVER (PARTITION BY layer_id ORDER BY n DESC) AS rank, count(*) OVER (PARTITION BY layer_id) AS of
                   FROM c) WHERE entity_id = ?""", [entity])
    out = []
    for r in got:
        d = spec.BY_ID.get(r["layer_id"])
        if d is None:
            continue
        size = None
        if d.size:
            size = {"label": d.size.label, "unit": d.size.unit,
                    "value": r["total"] if d.size.total == "sum" else r["top"] if d.size.total == "max" else None}
        out.append({"layer_id": d.id, "many": d.many, "one": d.one, "count": r["n"], "rank": r["rank"], "of": r["of"],
                    "size": size})
    order = {d.id: n for n, d in enumerate(spec.LAYERS)}
    return sorted(out, key=lambda r: order.get(r["layer_id"], 99))


def overview(q: Q) -> list[dict]:
    """Every layer the Details page can count, with how many items and countries it has now."""
    stored = {r["layer_id"]: r for r in q("""SELECT layer_id, count(DISTINCT item_id) AS n, count(DISTINCT entity_id) AS c
        FROM layer_items GROUP BY 1""")} if _has(q, "layer_items") else {}
    geo = {r["layer_id"]: r for r in q("SELECT layer_id, count(*) AS n FROM geo_features GROUP BY 1")} if _has(q, "geo_features") else {}
    out = []
    for d in spec.LAYERS:
        n = c = None
        if d.kind == "stored" and d.id in stored:
            n, c = stored[d.id]["n"], stored[d.id]["c"]
        elif d.kind in ("lines", "trees") and d.id in geo:
            n = geo[d.id]["n"]
        out.append({"id": d.id, "many": d.many, "kind": d.kind, "count": n, "countries": c,
                    "size": d.size.label if d.size else None, "category": d.category[1] if d.category else None,
                    "available": d.kind in ("live", "events") or n is not None})
    return out


# ----------------------------------------------------------------------------- coverage
PEERS = 15  # countries nearest in income a missing official figure is estimated from


def coverage(q: Q, key: str, layer_id: str, live=None, country_of=None) -> dict:
    """How complete the layer is in each country: its count or size against the first official
    figure that country has, graded good / part / thin; where no official figure exists, against
    what countries of a similar income with good coverage have per person (an estimate)."""
    from worldmodel_contract import health

    got = detail(q, key, layer_id, live, country_of)
    if "error" in got:
        return got
    layer = got["layer"]
    offs = [(i, o) for i, o in enumerate(layer.get("official") or []) if o.get("coverage")]
    gdp, pop = _latest(q, "gdp_per_capita_usd"), _latest(q, "pop_total")
    rows = []
    for r in got["countries"]:
        e = r.get("entity_id")
        if not e:
            continue
        best = next(((o, r["official"][i]) for i, o in offs if r["official"][i].get("coverage") is not None), None)
        rows.append({"entity_id": e, "name": r["name"], "count": r["count"], "per_m": r["per_m"],
                     "official": best[1]["value"] if best else None, "basis": best[0]["label"] if best else None,
                     "coverage": best[1]["coverage"] if best else None, "estimated": False})
    good = [r for r in rows if r["coverage"] is not None and r["coverage"] >= health.GRADES[0][0] and r["per_m"] and gdp.get(r["entity_id"])]
    import math
    for r in rows:
        if r["coverage"] is None and good and gdp.get(r["entity_id"]) and pop.get(r["entity_id"]):
            lg = math.log(gdp[r["entity_id"]])
            near = sorted(good, key=lambda g: abs(math.log(gdp[g["entity_id"]]) - lg))[:PEERS]
            per_m = sorted(g["per_m"] for g in near)[len(near) // 2]
            expect = per_m * pop[r["entity_id"]] / 1e6
            if expect > 0:
                r.update(official=expect, basis="Expected from countries of a similar income", coverage=r["count"] / expect,
                         estimated=True)
        r["grade"] = health.grade(r["coverage"])
    order = {"thin": 0, "part": 1, "good": 2, "unknown": 3}
    rows.sort(key=lambda r: (order[r["grade"]], -(r["official"] or 0)))
    tally = defaultdict(int)
    for r in rows:
        tally[r["grade"]] += 1
    return {"layer": layer, "countries": rows, "grades": dict(tally), "cuts": {g: c for c, g in health.GRADES}}


def gaps(q: Q, key: str, layer_id: str, country: str | None, live=None, country_of=None, limit: int = 300) -> dict:
    """Blank spots: towns of GAP_TOWN_PEOPLE or more with no item of the layer within GAP_KM."""
    import math

    from worldmodel_contract import health

    d = spec.BY_ID.get(layer_id)
    if d is None:
        return {"error": spec.NOT_COUNTED.get(layer_id, f"No details for the map layer {layer_id}.")}
    if not _has(q, "cities"):
        return {"towns": [], "checked": 0, "km": health.GAP_KM, "people": health.GAP_TOWN_PEOPLE, "note": "No towns yet: a refresh loads them."}
    its = items(q, key, d, live, country_of)
    cell = 0.25
    grid: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for i in its:
        if i.get("lat") is not None and i.get("lon") is not None:
            grid[(int(i["lat"] // cell), int(i["lon"] // cell))].append((i["lat"], i["lon"]))
    sql = "SELECT city_id, name, country_id, lat, lon, population FROM cities WHERE population >= ? AND lat IS NOT NULL"
    params: list = [health.GAP_TOWN_PEOPLE]
    if country:
        sql += " AND country_id = ?"
        params.append(country)
    towns = q(sql + " ORDER BY population DESC", params)
    reach = health.GAP_KM
    out = []
    for t in towns:
        gy, gx = int(t["lat"] // cell), int(t["lon"] // cell)
        near = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for lat, lon in grid.get((gy + dy, gx + dx), ()):
                    x = math.radians(lon - t["lon"]) * math.cos(math.radians((lat + t["lat"]) / 2))
                    km = 6371 * math.hypot(x, math.radians(lat - t["lat"]))
                    near = km if near is None or km < near else near
        if near is None or near > reach:
            out.append({"city_id": t["city_id"], "name": t["name"], "entity_id": t["country_id"], "lat": t["lat"], "lon": t["lon"],
                        "population": t["population"], "nearest_km": round(near, 1) if near is not None else None})
    by = defaultdict(lambda: {"towns": 0, "people": 0.0})
    for t in out:
        by[t["entity_id"]]["towns"] += 1
        by[t["entity_id"]]["people"] += t["population"] or 0
    names = _names(q)
    return {"towns": out[:limit], "total": len(out), "checked": len(towns), "km": reach, "people": health.GAP_TOWN_PEOPLE,
            "by_country": sorted(({"entity_id": e, "name": (names.get(e) or {}).get("name") or e, **v} for e, v in by.items()),
                                 key=lambda r: -r["people"])[:60]}
