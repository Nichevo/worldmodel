"""How a country ranks among a group: its neighbours, the countries most like it, a bloc it
belongs to, or countries picked by hand. For each measure: the best, this country with its
rank ("#14 of 38"), the group's middle and the worst, each with its value and year.

Neighbours are worked out from the map's country shapes: the countries touching it, then the
nearest others (across the sea) until there are eight, none further than 3,000 km.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from statistics import median

import numpy as np

Rows = Callable[..., list[dict]]
SHAPES = Path(__file__).resolve().parents[2] / "web" / "public" / "geo" / "countries.json"
TOUCH_KM, NEAR_KM, NEIGHBOURS = 30, 3000, 8
MIN_PEOPLE = 100_000  # countries smaller than this are left out of made-up groups

# Default rows: (indicator, which way is better). Quality of life first, then money and the state.
MEASURES: list[tuple[str, str]] = [
    ("life_expectancy", "higher"), ("infant_mortality", "lower"), ("homicide_rate", "lower"),
    ("gdp_ppp_per_capita", "higher"), ("unemployment", "lower"), ("ilo_min_wage_ppp", "higher"),
    ("pm25_exposure", "lower"), ("hdi", "higher"), ("gini", "lower"), ("govt_debt_gdp", "lower"),
]
BETTER = dict(MEASURES)
GROUP_TYPES = ("bloc", "alliance", "group", "subregion", "continent", "income_group", "intermediate_region")


# ----------------------------------------------------------------------------- neighbours
@lru_cache(maxsize=1)
def _outlines() -> dict[str, np.ndarray]:
    """Each country's outline as up to 300 points (radians, lat/lon), for distances."""
    try:
        d = json.loads(SHAPES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out, sizes = {}, {}
    for ft in d.get("features") or []:
        iso = (ft.get("properties") or {}).get("iso3")
        g = ft.get("geometry") or {}
        polys = g.get("coordinates") or []
        if g.get("type") == "Polygon":
            polys = [polys]
        # The main land only (the biggest outline): New Zealand's neighbours are measured from its
        # two main islands, not from Tokelau; France's from France, not French Guiana.
        main = max(polys, key=lambda poly: _area(poly[0]) if poly else 0, default=None)
        pts = [pt[:2] for pt in main[0]] if main else []
        if not iso or not pts:
            continue
        size = _area(main[0])
        if iso in sizes and sizes[iso] >= size:  # a country's islands can come as features of their own
            continue
        sizes[iso] = size
        a = np.radians(np.asarray(pts, dtype=float))
        step = max(1, len(a) // 300)
        out[iso] = a[::step][:, ::-1]  # lat, lon
    return out


def _area(ring) -> float:
    a = np.asarray(ring, dtype=float)
    if len(a) < 3:
        return 0.0
    x, y = a[:, 0], a[:, 1]
    return abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))) / 2


def _min_km(a: np.ndarray, b: np.ndarray) -> float:
    la1, lo1 = a[:, 0][:, None], a[:, 1][:, None]
    la2, lo2 = b[:, 0][None, :], b[:, 1][None, :]
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return float(2 * 6371.0 * np.arcsin(np.sqrt(np.clip(h.min(), 0, 1))))


@lru_cache(maxsize=256)
def neighbours(iso: str, countries: frozenset[str]) -> list[tuple[str, float]]:
    """(country, km apart) for the countries touching iso, then the nearest others to make eight."""
    shapes = _outlines()
    me = shapes.get(iso)
    if me is None:
        return []
    lat0, lon0 = float(me[:, 0].mean()), float(me[:, 1].mean())
    near = []
    for other, pts in shapes.items():
        if other == iso or other not in countries:
            continue
        # A cheap first cut on the outlines' middles (5,000 km plus the shapes' size) before the full check.
        c = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        rough = 2 * 6371 * math.asin(min(1, math.sqrt(math.sin((c[0] - lat0) / 2) ** 2
                                                       + math.cos(lat0) * math.cos(c[0]) * math.sin((c[1] - lon0) / 2) ** 2)))
        if rough > 9000:
            continue
        near.append((other, round(_min_km(me, pts))))
    near.sort(key=lambda x: x[1])
    touching = [n for n in near if n[1] <= TOUCH_KM]
    rest = [n for n in near if TOUCH_KM < n[1] <= NEAR_KM]
    return touching + rest[: max(0, NEIGHBOURS - len(touching))]


# ----------------------------------------------------------------------------- groups
def groups_of(q: Rows, entity: str) -> list[dict]:
    """The groups a country can be ranked in: neighbours, countries like it, and its blocs and regions."""
    # Counted as the card shows them: countries of at least MIN_PEOPLE (and this one).
    got = q(f"""WITH big AS (SELECT entity_id FROM series WHERE indicator_id = 'pop_total' AND variant = 'central'
                             AND breakdown = '' GROUP BY 1 HAVING max(value) >= {MIN_PEOPLE})
                SELECT g.entity_id AS id, coalesce(g.short_name, g.name) AS name, g.type,
                       (SELECT count(*) FROM memberships o JOIN entities e ON e.entity_id = o.member_id AND e.type = 'country'
                        WHERE o.group_id = g.entity_id AND o.valid_to IS NULL
                          AND (o.member_id = ? OR o.member_id IN (SELECT entity_id FROM big))) AS n
                FROM memberships m JOIN entities g ON g.entity_id = m.group_id
                WHERE m.member_id = ? AND m.valid_to IS NULL AND g.type IN ({', '.join('?' * len(GROUP_TYPES))})""",
            [entity, entity, *GROUP_TYPES])
    order = {t: i for i, t in enumerate(GROUP_TYPES)}
    got = [g for g in got if g["n"] and g["n"] >= 3]
    got.sort(key=lambda g: (order.get(g["type"], 9), -g["n"]))
    return ([{"id": "neighbours", "name": "Neighbours", "type": "made"}, {"id": "like", "name": "Like this country", "type": "made"}]
            + [{"id": g["id"], "name": f"{g['name']} ({g['n']})", "type": g["type"], "n": g["n"]} for g in got]
            + [{"id": "world", "name": "Every country", "type": "world"}])


def members(q: Rows, entity: str, group: str, like: Callable[[], list[str]], custom: list[str]) -> list[str]:
    countries = {r["entity_id"] for r in q("SELECT entity_id FROM entities WHERE type = 'country'")}
    if group == "custom":
        ids = [c for c in custom if c in countries]
    elif group == "neighbours":
        big = {r["e"] for r in q("""SELECT entity_id AS e FROM series WHERE indicator_id = 'pop_total' AND variant = 'central'
                   AND breakdown = '' GROUP BY 1 HAVING max(value) >= ?""", [MIN_PEOPLE])}
        ids = [c for c, _ in neighbours(entity, frozenset(c for c in countries if not big or c in big))]
    elif group == "like":
        ids = like()
    elif group == "world":
        ids = sorted(countries)
    else:
        ids = [r["m"] for r in q("""SELECT m.member_id AS m FROM memberships m JOIN entities e ON e.entity_id = m.member_id
                                    WHERE m.group_id = ? AND m.valid_to IS NULL AND e.type = 'country'""", [group])]
    return list(dict.fromkeys([entity, *ids]))


# ----------------------------------------------------------------------------- ranking
def rank(q: Rows, entity: str, ids: list[str], measures: list[tuple[str, str]]) -> list[dict]:
    """Each measure ranked over the group: the latest value each country has (best-ranked source),
    kept to within three years of the year most of them report."""
    inds = [m for m, _ in measures]
    got = q("""
        WITH first AS (SELECT indicator_id, arg_min(source_id, rank) AS src FROM indicator_sources GROUP BY 1)
        SELECT s.indicator_id AS i, s.entity_id AS e, coalesce(n.short_name, n.name) AS name, year(s.period_start) AS y, s.value AS v
        FROM series s JOIN first f ON f.indicator_id = s.indicator_id AND f.src = s.source_id
        JOIN entities n ON n.entity_id = s.entity_id
        WHERE s.indicator_id IN (SELECT unnest(?)) AND s.entity_id IN (SELECT unnest(?)) AND s.breakdown = ''
          AND s.variant = 'central' AND s.status = 'E' AND s.value IS NOT NULL
          AND year(s.period_start) >= year(current_date) - 12
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.entity_id ORDER BY s.period_start DESC) = 1""", [inds, ids])
    meta = {r["indicator_id"]: r for r in q("SELECT indicator_id, name, unit, decimals FROM indicators WHERE indicator_id IN (SELECT unnest(?))", [inds])}
    by: dict[str, list[dict]] = {}
    for r in got:
        by.setdefault(r["i"], []).append(r)
    out = []
    for ind, better in measures:
        vals = by.get(ind) or []
        if len(vals) < 2 or ind not in meta:
            continue
        years: dict[int, int] = {}
        for v in vals:
            years[v["y"]] = years.get(v["y"], 0) + 1
        top = max(years.values())
        main = max(y for y, n in years.items() if n >= top / 2)
        vals = [v for v in vals if v["y"] >= main - 3]
        if len(vals) < 2:
            continue
        order = sorted(vals, key=lambda v: v["v"], reverse=better != "lower")  # best first
        me = next((i for i, v in enumerate(order) if v["e"] == entity), None)
        n = len(order)
        pick = lambda v: {"entity_id": v["e"], "name": v["name"], "value": v["v"], "year": v["y"]}
        tied = lambda v, order=order: [w["name"] for w in order if w["v"] == v["v"]]
        m = meta[ind]
        out.append({
            "indicator_id": ind, "name": m["name"], "unit": m["unit"], "decimals": m["decimals"], "better": better, "year": main, "of": n,
            "best": {**pick(order[0]), "tied": len(tied(order[0]))}, "worst": {**pick(order[-1]), "tied": len(tied(order[-1]))},
            "middle": median(v["v"] for v in order),
            "me": ({**pick(order[me]), "rank": (r := _rank_of(order, me, better)), "position": round(1 - (r - 1) / (n - 1), 3) if n > 1 else 1.0}
                   if me is not None else None),
            "ranked": [{**pick(v), "rank": i + 1} for i, v in enumerate(order)],
        })
    return out


def _rank_of(order: list[dict], i: int, better: str) -> int:
    """1 + the countries strictly better (ties share a rank)."""
    v = order[i]["v"]
    return 1 + sum(1 for w in order if (w["v"] < v if better == "lower" else w["v"] > v))
