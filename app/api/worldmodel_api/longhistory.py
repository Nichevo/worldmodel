"""The Long history page: empires' sizes and borders over time, who ruled where, figures
over centuries, events far back, voyages, the eight factors and the big cycle.

Reads the warehouse tables polities, long_series and history_events (schema 1.8.0; a
warehouse without them gives empty answers) and the set-up in the contract's history.yaml.
Years are whole numbers, negative for BC, with no year 0.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Callable

from worldmodel_contract import catalogue

Q = Callable[[str, list], list[dict]]

FIRST_YEAR, LAST_YEAR = -3400, 2024
EVENT_KINDS = {"war": "Wars", "battle": "Battles", "siege": "Sieges", "revolution": "Revolutions", "treaty": "Treaties",
               "epidemic": "Epidemics", "famine": "Famines", "earthquake": "Earthquakes", "volcano": "Volcanic eruptions",
               "tsunami": "Tsunamis"}


def year_label(y: int | None) -> str:
    if y is None:
        return ""
    return f"{-y:,} BC" if y < 0 else (f"AD {y}" if y < 1000 else str(y))


def strip(name: str | None) -> str:
    return (name or "").strip().strip("()").strip()


# ----------------------------------------------------------------------------- what is loaded
def counts(q: Q, has: Callable[[str], bool]) -> dict:
    out = {}
    for t in ("polities", "long_series", "history_events"):
        out[t] = q(f"SELECT count(*) AS n FROM {t}", [])[0]["n"] if has(t) else 0
    return out


def overview(q: Q, has: Callable[[str], bool]) -> dict:
    """The page's set-up with each power's span and peak from the borders."""
    h = catalogue.history()
    powers = catalogue.history_powers()
    spans: dict[str, dict] = {}
    if has("polities"):
        for pid, p in powers.items():
            names = p.get("polities") or []
            if not names:
                continue
            r = q(f"""SELECT min(from_year) AS f, max(to_year) AS t, max(area_km2) AS peak,
                         arg_max(from_year, area_km2) AS peak_year FROM polities
                      WHERE name IN ({', '.join('?' * len(names))})""", names)[0]
            if r["f"] is not None:
                spans[pid] = {"from": r["f"], "to": r["t"], "peak_km2": r["peak"], "peak_year": r["peak_year"]}
    out_powers = []
    for pid, p in powers.items():
        out_powers.append({"id": pid, "name": p["name"], "era": p["era"], "group": p.get("group"), "entity": p.get("entity"),
                           "colour": p.get("colour"), "wikipedia": p.get("wikipedia"), "has_borders": pid in spans,
                           **spans.get(pid, {})})
    return {
        "counts": counts(q, has),
        "powers": out_powers,
        "dynasties": [d["id"] for d in h["china_dynasties"]],
        "regions": [{"id": r["id"], "name": r["name"]} for r in h["regions"]],
        "pacific": {"id": h["pacific"]["id"], "name": h["pacific"]["name"], "note": h["pacific"]["note"]},
        "series": h["series"],
        "factors": h["factors"],
        "stages": h["cycle"]["stages"],
        "event_kinds": EVENT_KINDS,
        "voyages": [{"id": v["id"], "name": v["name"], "who": v["who"], "power": v.get("power"),
                     "from": v["stops"][0][0], "to": v["stops"][-1][0]} for v in h["voyages"]],
    }


# ----------------------------------------------------------------------------- sizes and shapes
def _power(pid: str) -> dict:
    p = catalogue.history_powers().get(pid)
    if p is None:
        raise KeyError(pid)
    return p


def _rows_of(q: Q, names: list[str], geo: bool = False) -> list[dict]:
    if not names:
        return []
    cols = "polity_key, name, from_year, to_year, area_km2, composite, member_of, wikipedia, lat, lon, west, south, east, north"
    return q(f"SELECT {cols}{', geojson' if geo else ''} FROM polities WHERE name IN ({', '.join('?' * len(names))}) "
             "ORDER BY from_year, area_km2 DESC", names)


def frames(rows: list[dict]) -> list[dict]:
    """The power's shape over time: for each stretch of years, the largest of its rows alive
    then (a composite where there is one). Neighbouring years with the same row are joined."""
    if not rows:
        return []
    lo, hi = min(r["from_year"] for r in rows), max(r["to_year"] for r in rows)
    out: list[dict] = []
    # Walk the years where something starts or ends; between two such years nothing changes.
    edges = sorted({r["from_year"] for r in rows} | {r["to_year"] + 1 for r in rows})
    for a, b in zip(edges, edges[1:]):
        alive = [r for r in rows if r["from_year"] <= a <= r["to_year"]]
        if not alive:
            continue
        best = max(alive, key=lambda r: r["area_km2"] or 0)
        if out and out[-1]["key"] == best["polity_key"] and out[-1]["to"] == a - 1:
            out[-1]["to"] = b - 1
        else:
            out.append({"key": best["polity_key"], "name": best["name"], "from": a, "to": b - 1,
                        "area_km2": round(best["area_km2"] or 0)})
    return [f for f in out if lo <= f["from"] <= hi]


def sizes(q: Q, ids: list[str]) -> list[dict]:
    """Land area over time for each power: points where it changes (draw as steps)."""
    out = []
    for pid in ids:
        try:
            p = _power(pid)
        except KeyError:
            continue
        fr = frames(_rows_of(q, p.get("polities") or []))
        pts: list[list[float]] = []
        for f in fr:
            if pts and pts[-1][0] < f["from"] - 1:
                pts.append([pts[-1][0] + 1, None])  # a gap: the power did not exist for a while
            pts.append([f["from"], f["area_km2"]])
            pts.append([f["to"], f["area_km2"]])
        out.append({"id": pid, "name": p["name"], "colour": p.get("colour"), "group": p.get("group"), "points": pts})
    return out


def shape(q: Q, key: str) -> dict | None:
    r = q("SELECT polity_key, name, from_year, to_year, area_km2, member_of, wikipedia, geojson FROM polities "
          "WHERE polity_key = ?", [key])
    if not r:
        return None
    r = r[0]
    return {"type": "Feature", "geometry": json.loads(r["geojson"]),
            "properties": {"key": r["polity_key"], "name": strip(r["name"]), "from": r["from_year"], "to": r["to_year"],
                           "area_km2": round(r["area_km2"] or 0),
                           "label": f"<b>{strip(r['name'])}</b><br/>{year_label(r['from_year'])} to {year_label(r['to_year'])}"
                                    f"<br/>{(r['area_km2'] or 0) / 1e6:.2f} million km²"}}


def expansion(q: Q, pid: str, most: int = 24) -> dict:
    """Up to `most` of the power's shapes, evenly spread over its life (its peak always in),
    oldest on top, each coloured on the map by its first year: the land it gained, when."""
    p = _power(pid)
    fr = frames(_rows_of(q, p.get("polities") or []))
    if not fr:
        return {"type": "FeatureCollection", "features": []}
    peak = max(fr, key=lambda f: f["area_km2"])
    if len(fr) > most:
        step = (len(fr) - 1) / (most - 1)
        keep = {fr[round(i * step)]["key"] for i in range(most)} | {peak["key"]}
        fr = [f for f in fr if f["key"] in keep]
    feats = []
    for f in sorted(fr, key=lambda f: -f["from"]):  # newest first, so the oldest is drawn last, on top
        s = shape(q, f["key"])
        if s:
            s["properties"].update({"from": f["from"], "to": f["to"], "sort": -f["from"]})
            feats.append(s)
    return {"type": "FeatureCollection", "features": feats}


def world(q: Q, year: int, geometry: bool = True) -> dict:
    """Every state alive in a year (the parts, not the composites), named by the empire
    they belong to, for the World-in-year map. Without geometry, only the properties (the
    map asks for the shapes it does not have yet with shapes())."""
    found = q(f"""SELECT polity_key, name, member_of, from_year, to_year, area_km2{', geojson' if geometry else ''} FROM polities
                 WHERE NOT composite AND from_year <= ? AND to_year >= ? ORDER BY area_km2 DESC""", [year, year])
    feats = []
    for r in found:
        whole = strip(r["member_of"]) or strip(r["name"])
        feats.append({"type": "Feature", "geometry": json.loads(r["geojson"]) if geometry else None, "properties": {
            "key": r["polity_key"], "name": strip(r["name"]), "whole": whole, "hue": _hue(whole),
            "label": f"<b>{strip(r['name'])}</b>" + (f"<br/>part of {whole}" if whole != strip(r["name"]) else "")
                     + f"<br/>{year_label(r['from_year'])} to {year_label(r['to_year'])} with these borders"
                     + f"<br/>{(r['area_km2'] or 0) / 1e6:.2f} million km²"}})
    return {"type": "FeatureCollection", "features": feats, "year": year}


def shapes(q: Q, keys: list[str]) -> dict[str, dict]:
    """Geometries by polity key."""
    if not keys:
        return {}
    return {r["polity_key"]: json.loads(r["geojson"]) for r in q(
        "SELECT polity_key, geojson FROM polities WHERE polity_key IN (SELECT unnest(?))", [keys])}


def _hue(name: str) -> int:
    """A steady colour (0-359) per empire name, so one empire keeps its colour from year to year."""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) % 360
    return h


# ----------------------------------------------------------------------------- who ruled where
def ruled(q: Q, step: int = 10) -> dict:
    """For each region (and the Pacific), who held the most land there, period by period."""
    h = catalogue.history()
    regions = [*h["regions"], {**h["pacific"]}]
    found = q(f"""
        WITH years AS (SELECT range AS y FROM range({FIRST_YEAR}, {LAST_YEAR + 1}, ?))
        SELECT region, y, coalesce(nullif(trim(BOTH '()' FROM member_of), ''), name) AS who, sum(area_km2) AS area
        FROM years JOIN polities ON from_year <= y AND to_year >= y
        WHERE NOT composite AND region IS NOT NULL
        GROUP BY ALL""", [step])
    best: dict[tuple[str, int], tuple[str, float]] = {}
    for r in found:
        k = (r["region"], r["y"])
        if k not in best or (r["area"] or 0) > best[k][1]:
            best[k] = (r["who"], r["area"] or 0)
    china = {strip(n) for d in catalogue.history_powers().values() if d.get("group") == "china" for n in d.get("polities") or []}
    out = []
    for reg in regions:
        segs: list[dict] = []
        for y in range(FIRST_YEAR, LAST_YEAR + 1, step):
            b = best.get((reg["id"], y))
            if b is None:
                continue
            if segs and segs[-1]["name"] == b[0] and segs[-1]["to"] >= y - step:
                segs[-1]["to"] = min(y + step - 1, LAST_YEAR)
                segs[-1]["area_km2"] = max(segs[-1]["area_km2"], round(b[1]))
            else:
                segs.append({"name": b[0], "from": y, "to": min(y + step - 1, LAST_YEAR), "area_km2": round(b[1]),
                             "hue": _hue(b[0]), "china": b[0] in china})
        out.append({"id": reg["id"], "name": reg["name"], "note": reg.get("note"), "segments": segs})
    return {"step": step, "regions": out}


# ----------------------------------------------------------------------------- long-run figures
def region_members() -> dict[str, set[str]]:
    """Countries in each region (and the Pacific), from UN M49 groups plus the adds and drops."""
    h = catalogue.history()
    by_group: dict[str, set[str]] = defaultdict(set)
    for m in catalogue.memberships():
        by_group[m["group_id"]].add(m["member_id"])
    out = {}
    for r in [*h["regions"], h["pacific"]]:
        s: set[str] = set()
        for g in r.get("groups", []):
            s |= by_group.get(g, set())
        s |= set(r.get("add", []))
        s -= set(r.get("drop", []))
        out[r["id"]] = s
    return out


def series(q: Q, entities: list[str], series_ids: list[str], start: int | None = None, end: int | None = None) -> list[dict]:
    if not entities or not series_ids:
        return []
    meta = catalogue.history()["series"]
    where, params = ["entity_id IN (SELECT unnest(?))", "series_id IN (SELECT unnest(?))"], [entities, series_ids]
    if start is not None:
        where.append("year >= ?")
        params.append(start)
    if end is not None:
        where.append("year <= ?")
        params.append(end)
    found = q(f"SELECT entity_id, series_id, year, value, source_id FROM long_series WHERE {' AND '.join(where)} "
              "ORDER BY entity_id, series_id, year", params)
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for r in found:
        grouped[(r["entity_id"], r["series_id"])].append([r["year"], r["value"]])
    names = {e.entity_id: e.short_name or e.name for e in catalogue.entities().values()}
    return [{"entity": e, "entity_name": names.get(e, e), "series": s, "name": meta.get(s, {}).get("name", s),
             "unit": meta.get(s, {}).get("unit", ""), "source": meta.get(s, {}).get("source", ""),
             "note": meta.get(s, {}).get("note"), "points": pts} for (e, s), pts in grouped.items()]


def regional_population(q: Q) -> list[dict]:
    """People in each region over time: the sum of its countries in the years where nearly all
    of them have a figure (HYDE gives every country the same years)."""
    members = region_members()
    names = {r["id"]: r["name"] for r in [*catalogue.history()["regions"], catalogue.history()["pacific"]]}
    found = q("SELECT entity_id, year, value FROM long_series WHERE series_id = 'population'", [])
    by: dict[str, dict[int, list[float]]] = {rid: defaultdict(list) for rid in members}
    of = {e: rid for rid, s in members.items() for e in s}
    for r in found:
        rid = of.get(r["entity_id"])
        if rid:
            by[rid][r["year"]].append(r["value"])
    out = []
    for rid, years in by.items():
        if not years:
            continue
        most = max(len(v) for v in years.values())
        pts = [[y, sum(v)] for y, v in sorted(years.items()) if len(v) >= 0.8 * most]
        out.append({"id": rid, "name": names[rid], "points": pts, "countries": most})
    return out


def events(q: Q, start: int | None = None, end: int | None = None, kinds: list[str] | None = None, min_links: int = 5,
           bbox: tuple[float, float, float, float] | None = None, region: str | None = None, entity: str | None = None,
           limit: int = 400) -> list[dict]:
    where, params = ["(links IS NULL OR links >= ?)"], [min_links]
    if start is not None:
        where.append("coalesce(end_year, year) >= ?")
        params.append(start)
    if end is not None:
        where.append("year <= ?")
        params.append(end)
    if kinds:
        where.append("kind IN (SELECT unnest(?))")
        params.append(kinds)
    if bbox:
        w, s, e, n = bbox
        where.append("lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?")
        params += [w, e, s, n]
    if region:
        where.append("region = ?")
        params.append(region)
    if entity:
        where.append("entity_id = ?")
        params.append(entity)
    # The most notable first: Wikipedias with an article, then deaths (NOAA's have no article count).
    found = q(f"""SELECT event_id, kind, title, year, end_year, month, day, lat, lon, place, entity_id, region, deaths,
                         size, size_unit, links, url, source_id FROM history_events WHERE {' AND '.join(where)}
                  ORDER BY coalesce(links, 0) + coalesce(ln(1 + deaths), 0) * 2 DESC, year LIMIT ?""", [*params, limit])
    for r in found:
        r["when"] = year_label(r["year"]) + (f" to {year_label(r['end_year'])}" if r["end_year"] and r["end_year"] != r["year"] else "")
    return sorted(found, key=lambda r: r["year"])


def voyages(power: str | None = None) -> list[dict]:
    out = []
    for v in catalogue.history()["voyages"]:
        if power and v.get("power") != power:
            continue
        out.append({**v, "stops": [{"year": s[0], "place": s[1], "lat": s[2], "lon": s[3]} for s in v["stops"]]})
    return out


def power_card(q: Q, pid: str, has: Callable[[str], bool], min_links: int = 5) -> dict:
    p = _power(pid)
    rows = _rows_of(q, p.get("polities") or []) if has("polities") else []
    fr = frames(rows)
    box = None
    if rows:
        box = [min(r["west"] for r in rows), min(r["south"] for r in rows), max(r["east"] for r in rows),
               max(r["north"] for r in rows)]
    span = (fr[0]["from"], fr[-1]["to"]) if fr else (None, None)
    ev = []
    if box and has("history_events"):
        ev = events(q, span[0], span[1], None, min_links, tuple(box), limit=60)  # type: ignore[arg-type]
    peak = max(fr, key=lambda f: f["area_km2"]) if fr else None
    return {"id": pid, "name": p["name"], "era": p["era"], "group": p.get("group"), "entity": p.get("entity"),
            "colour": p.get("colour"), "wikipedia": p.get("wikipedia"), "frames": fr, "bbox": box,
            "from": span[0], "to": span[1], "peak": peak, "events": ev, "voyages": voyages(pid),
            "sizes": sizes(q, [pid])[0]["points"] if fr else []}


def ruled_here(q: Q, lat: float, lon: float) -> list[dict]:
    """The states whose borders held a point (a capital), in time order: one line per state
    and stretch of years."""
    cands = q("""SELECT polity_key, name, member_of, from_year, to_year, geojson FROM polities
                 WHERE NOT composite AND west <= ? AND east >= ? AND south <= ? AND north >= ? ORDER BY from_year""",
              [lon, lon, lat, lat])
    spans: list[dict] = []
    for r in cands:
        if not _inside(json.loads(r["geojson"]), lon, lat):
            continue
        who = strip(r["member_of"]) or strip(r["name"])
        if spans and spans[-1]["name"] == who and spans[-1]["to"] >= r["from_year"] - 1:
            spans[-1]["to"] = max(spans[-1]["to"], r["to_year"])
        else:
            spans.append({"name": who, "part": strip(r["name"]), "from": r["from_year"], "to": r["to_year"], "hue": _hue(who)})
    return spans


def _inside(geometry: dict, x: float, y: float) -> bool:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    for poly in polys:
        if _in_ring(poly[0], x, y) and not any(_in_ring(h, x, y) for h in poly[1:]):
            return True
    return False


def _in_ring(ring: list, x: float, y: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


# ----------------------------------------------------------------------------- then and now
WORLD_LAND_KM2 = 134_000_000  # the world's land without Antarctica
MEASURES = {"output": "Share of world output", "people": "Share of world people", "land": "Share of the world's land"}


def then_and_now(q: Q, measure: str, ids: list[str]) -> dict:
    """Each power's share of the world (%) over time, with its peak: output and people from
    its core country's long-run figures (Maddison, HYDE), land from its borders."""
    powers = catalogue.history_powers()
    ids = [i for i in ids if i in powers]
    out = []
    if measure == "land":
        for s in sizes(q, ids):
            pts = [[y, round(100 * v / WORLD_LAND_KM2, 2) if v is not None else None] for y, v in s["points"]]
            out.append({"id": s["id"], "points": pts})
    else:
        ents = sorted({powers[i]["entity"] for i in ids if powers[i].get("entity")} | {"world"})
        need = ["population"] if measure == "people" else ["population", "gdp_per_capita"]
        found = q("SELECT entity_id, series_id, year, value FROM long_series WHERE entity_id IN (SELECT unnest(?)) "
                  "AND series_id IN (SELECT unnest(?)) ORDER BY year", [ents, need])
        pts: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
        for r in found:
            pts[(r["entity_id"], r["series_id"])].append((r["year"], r["value"]))

        def amount(e: str, y: int) -> float | None:
            vals = [_interp(pts.get((e, s), []), y) for s in need]
            return math.prod(vals) if all(v is not None for v in vals) else None  # type: ignore[arg-type]

        for i in ids:
            e = powers[i].get("entity")
            if not e:
                continue
            own = pts.get((e, need[-1]), [])
            line = []
            for y, _ in own:
                a, w = amount(e, y), amount("world", y)
                if a is not None and w:
                    line.append([y, round(100 * a / w, 2)])
            out.append({"id": i, "points": line})
    for line in out:
        good = [p for p in line["points"] if p[1] is not None]
        line["peak"] = max(good, key=lambda p: p[1]) if good else None
        line["name"] = powers[line["id"]]["name"]
        line["colour"] = powers[line["id"]].get("colour")
    return {"measure": measure, "name": MEASURES.get(measure, measure), "lines": out,
            "note": ("Output and people are the core country's figures (Britain for the British Empire, Italy for Rome), "
                     "so an empire's colonies are not in them; land ruled is from the borders and includes them.")}


# ----------------------------------------------------------------------------- the eight factors
def _interp(points: list[tuple[int, float]], year: int) -> float | None:
    """The value in a year, drawn straight between known years; none outside them."""
    if not points or year < points[0][0] or year > points[-1][0]:
        return None
    for (y0, v0), (y1, v1) in zip(points, points[1:]):
        if y0 <= year <= y1:
            return v0 if y1 == y0 else v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    return points[-1][1] if points[-1][0] == year else None


def factors(q: Q, start: int = 1500, step: int = 10) -> dict:
    """Each factor as each country's share of the group's total (0-1), and the index: the
    average of the factors a country has that year (at least three)."""
    h = catalogue.history()
    countries = h["factor_countries"]
    need = sorted({s for f in h["factors"] for s in f.get("series", [])})
    found = q("""SELECT entity_id, series_id, year, value FROM long_series
                 WHERE entity_id IN (SELECT unnest(?)) AND series_id IN (SELECT unnest(?)) AND year >= ? ORDER BY year""",
              [countries, need, start - 200])
    pts: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    last_year = start
    for r in found:
        pts[(r["entity_id"], r["series_id"])].append((r["year"], r["value"]))
        last_year = max(last_year, r["year"])
    years = list(range(start, last_year + 1, step))
    if years and years[-1] != last_year:
        years.append(last_year)
    shares: dict[str, dict[str, dict[int, float]]] = {}
    for f in h["factors"]:
        per: dict[str, dict[int, float]] = defaultdict(dict)
        if f.get("periods"):
            for y in years:
                got = {c: 0.0 for c in countries}
                for p in h[f["periods"]]:
                    if p["from"] <= y <= p["to"] and p["entity"] in got:
                        got[p["entity"]] += (1.0 if p["rank"] == 1 else 0.5) * p.get("weight", 1)
                total = sum(got.values())
                if total:
                    for c, v in got.items():
                        per[c][y] = v / total
        elif f.get("series"):
            for y in years:
                raw = {}
                for c in countries:
                    vals = [_interp(pts.get((c, s), []), y) for s in f["series"]]
                    if all(v is not None for v in vals):
                        raw[c] = math.prod(vals)  # type: ignore[arg-type]
                total = sum(raw.values())
                if len(raw) >= 3 and total > 0:
                    for c, v in raw.items():
                        per[c][y] = v / total
        shares[f["id"]] = per
    index: dict[str, dict[int, float]] = defaultdict(dict)
    for c in countries:
        for y in years:
            vals = [shares[f][c][y] for f in shares if y in shares[f].get(c, {})]
            if len(vals) >= 3:
                index[c][y] = sum(vals) / len(vals)
    names = {e.entity_id: e.short_name or e.name for e in catalogue.entities().values()}

    def lines(d: dict[str, dict[int, float]]) -> list[dict]:
        return [{"entity": c, "name": names.get(c, c), "points": [[y, round(v, 4)] for y, v in sorted(d[c].items())]}
                for c in countries if d.get(c)]

    return {"countries": countries, "years": years,
            "factors": [{**{k: f[k] for k in ("id", "name", "how")}, "lines": lines(shares[f["id"]])} for f in h["factors"]],
            "index": lines(index),
            "note": "Rebuilt from free data: a copy of Ray Dalio's eight measures of a country's strength, not his own figures."}


# ----------------------------------------------------------------------------- the big cycle
CYCLE_INDICATORS = {"debt": "govt_debt_gdp", "growth": "gdp_growth", "inflation": "inflation", "top10": "wid_income_top10"}


def cycle(q: Q, entities: list[str], this_year: int) -> list[dict]:
    """A rough placing of each country in the six stages, by simple rules on its latest
    figures, with the reasons. Not Dalio's own placing."""
    h = catalogue.history()["cycle"]
    names = {e.entity_id: e.short_name or e.name for e in catalogue.entities().values()}
    out = []
    for ent in entities:
        figs: dict[str, dict] = {}
        for key, ind in CYCLE_INDICATORS.items():
            found = q("""SELECT year(period_start) AS y, value FROM series WHERE entity_id = ? AND indicator_id = ?
                         AND variant = 'central' AND freq = 'A' AND status = 'E' ORDER BY period_start""", [ent, ind])
            if found:
                figs[key] = {"latest": found[-1]["value"], "year": found[-1]["y"],
                             "avg5": sum(r["value"] for r in found[-5:]) / len(found[-5:]),
                             "ten_ago": next((r["value"] for r in found if r["y"] == found[-1]["y"] - 10), None)}
        began = h["order_began"].get(ent)
        stage, reasons = place(figs, (this_year - began) if began else None)
        out.append({"entity": ent, "name": names.get(ent, ent), "stage": stage, "reasons": reasons, "order_began": began,
                    "figures": {k: {"value": round(v["latest"], 1), "year": v["year"], "avg5": round(v["avg5"], 1)}
                                for k, v in figs.items()}})
    return out


def place(figs: dict[str, dict], age: int | None) -> tuple[int | None, list[str]]:
    """Points towards the later stages from debt, its rise, slow growth, high inflation and a
    wide income gap; the stage follows from the points and the age of the order."""
    if not figs:
        return None, ["No recent figures for debt, growth, inflation or the income gap."]
    reasons, pts = [], 0
    debt, growth, infl, top = (figs.get(k) for k in ("debt", "growth", "inflation", "top10"))
    if debt:
        d = debt["latest"]
        if d >= 100:
            pts += 2
            reasons.append(f"Government debt is {d:.0f}% of GDP ({debt['year']}): heavy.")
        elif d >= 70:
            pts += 1
            reasons.append(f"Government debt is {d:.0f}% of GDP ({debt['year']}): high.")
        else:
            reasons.append(f"Government debt is {d:.0f}% of GDP ({debt['year']}): moderate.")
        if debt["ten_ago"] is not None and d - debt["ten_ago"] >= 20:
            pts += 1
            reasons.append(f"Debt rose {d - debt['ten_ago']:.0f} points of GDP in ten years.")
    if growth:
        g = growth["avg5"]
        if g < 1.5:
            pts += 1
            reasons.append(f"Growth averaged {g:.1f}% a year over the last five years: slow.")
        elif g >= 5:
            pts -= 1
            reasons.append(f"Growth averaged {g:.1f}% a year over the last five years: fast.")
        else:
            reasons.append(f"Growth averaged {g:.1f}% a year over the last five years.")
    if infl and infl["avg5"] >= 10:
        pts += 1
        reasons.append(f"Inflation averaged {infl['avg5']:.0f}% a year over five years.")
    if top:
        t = top["latest"] * (100 if top["latest"] <= 1 else 1)
        if t >= 45:
            pts += 1
            reasons.append(f"The richest tenth get {t:.0f}% of income ({top['year']}): a wide gap.")
        else:
            reasons.append(f"The richest tenth get {t:.0f}% of income ({top['year']}).")
    if age is not None:
        reasons.append(f"The present order is {age} years old.")
    if age is not None and age < 10:
        stage = 1
    elif age is not None and age < 30 and pts <= 1:
        stage = 2
    elif pts <= 1:
        stage = 3
    elif pts <= 3:
        stage = 4
    else:
        stage = 5
    return stage, reasons
