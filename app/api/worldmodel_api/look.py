"""Small summaries the pages lead with: where a country stands on a figure (rank among
countries, the world, a guideline or target), a country's recovery against a base year,
and how its land is used. Each function takes `q`, the API's rows(sql, params) helper."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

Q = Callable[[str, list], list[dict]]

# Guidelines and targets drawn on rankings: (value, label, higher is better?)
GUIDES: dict[str, tuple[float, str, bool]] = {
    "pm25_exposure": (5.0, "WHO guideline 5 µg/m³ (2021)", False),
    "protected_land_share": (30.0, "30% by 2030 (Kunming-Montreal goal)", True),
    "protected_sea_share": (30.0, "30% by 2030 (Kunming-Montreal goal)", True),
    "protected_total_share": (30.0, "30% by 2030 (Kunming-Montreal goal)", True),
    "kba_land_protected": (100.0, "all key nature areas", True),
    "kba_sea_protected": (100.0, "all key nature areas", True),
    "safe_drinking_water": (100.0, "everyone by 2030 (SDG 6)", True),
    "wastewater_treated_share": (100.0, "", True),
}
# Which way is better when no guideline says so (None = neither)
LOWER_BETTER = {"pm25_exposure", "pm25_above_who_share", "air_pollution_death_rate", "air_pollution_death_share", "water_stress",
                "freshwater_withdrawal_share", "ocean_plastic", "ocean_plastic_per_capita", "ocean_plastic_share", "road_deaths_rate",
                "red_list_index_owid", "threatened_mammals", "threatened_birds", "threatened_fish_wdi", "threatened_plants_wdi",
                "iucn_threatened", "iucn_cr", "iucn_ex", "tree_cover_loss", "introduced_species", "watched_pests_present"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def ranked(q: Q, indicator: str, keys: list[str]) -> dict | None:
    """Every country's latest value (in the indicator's main year, the best-ranked source), the
    world's, the key countries' with their rank, and the home country's line ("4th lowest of 190")."""
    meta = q("SELECT name, unit, decimals FROM indicators WHERE indicator_id = ?", [indicator])
    if not meta:
        return None
    got = q("""
        SELECT s.entity_id AS e, coalesce(n.short_name, n.name) AS name, n.type AS t, year(s.period_start) AS y, s.value AS v
        FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        JOIN entities n ON n.entity_id = s.entity_id
        WHERE s.indicator_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E' AND s.value IS NOT NULL
          AND (n.type = 'country' OR s.entity_id = 'world')
        QUALIFY row_number() OVER (PARTITION BY s.entity_id ORDER BY s.period_start DESC, r.rank) = 1""", [indicator])
    countries = [g for g in got if g["t"] == "country"]
    if not countries:
        return None
    # the year most countries report in, or newer
    years = defaultdict(int)
    for g in countries:
        years[g["y"]] += 1
    top = max(years.values())
    main = max(y for y, n in years.items() if n >= top / 2)
    countries = [g for g in countries if g["y"] >= main - 3]
    lower = indicator in LOWER_BETTER or (indicator in GUIDES and not GUIDES[indicator][2])
    order = sorted(countries, key=lambda g: g["v"], reverse=not lower)  # best first
    rank = {g["e"]: i + 1 for i, g in enumerate(order)}
    world = next((g for g in got if g["e"] == "world"), None)
    guide = GUIDES.get(indicator)
    meeting = None
    if guide:
        meeting = sum(1 for g in countries if (g["v"] >= guide[0] if guide[2] else g["v"] <= guide[0]))
    word = "lowest" if lower else "highest"
    rows = []
    for e in keys:
        g = next((c for c in countries if c["e"] == e), None)
        if g:
            rows.append({"entity_id": e, "name": g["name"], "value": g["v"], "year": g["y"], "rank": rank[e], "key": True})
    if world:
        rows.append({"entity_id": "world", "name": "World", "value": world["v"], "year": world["y"], "rank": None, "key": True})
    for g in order[:2] + order[-2:]:  # the best and worst, for range
        if g["e"] not in keys:
            rows.append({"entity_id": g["e"], "name": g["name"], "value": g["v"], "year": g["y"], "rank": rank[g["e"]], "key": False})
    rows.sort(key=lambda r: r["value"], reverse=not lower)
    home = next((r for r in rows if r["entity_id"] == (keys[0] if keys else "")), None)
    line = (f"{home['name']}: {home['value']:,.{meta[0]['decimals']}f} {meta[0]['unit']}, {_ordinal(home['rank'])} {word} of {len(countries)}"
            f"{' (' + str(home['year']) + ')' if home['year'] != main else ''}") if home else ""
    return {"indicator": indicator, "name": meta[0]["name"], "unit": meta[0]["unit"], "decimals": meta[0]["decimals"], "year": main,
            "of": len(countries), "lower_better": lower, "rows": rows, "line": line,
            "min": min(g["v"] for g in countries), "max": max(g["v"] for g in countries),
            "guide": {"value": guide[0], "label": guide[1], "meeting": meeting} if guide else None}


def recovery(q: Q, indicator: str, keys: list[str], base: int = 2019, since: int = 2000) -> dict:
    """Each key country's figure since `since`, and its latest as a share of `base` (visitors back
    to the level before COVID)."""
    if not keys:
        return {"indicator": indicator, "lines": [], "finding": ""}
    got = q(f"""
        SELECT s.entity_id AS e, coalesce(n.short_name, n.name) AS name, year(s.period_start) AS y, s.value AS v
        FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        JOIN entities n ON n.entity_id = s.entity_id
        WHERE s.indicator_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E'
          AND year(s.period_start) >= ? AND s.entity_id IN ({', '.join('?' * len(keys))})
        QUALIFY row_number() OVER (PARTITION BY s.entity_id, s.period_start ORDER BY r.rank) = 1
        ORDER BY s.period_start""", [indicator, since] + keys)
    by: dict = defaultdict(list)
    names = {}
    for g in got:
        by[g["e"]].append([g["y"], g["v"]])
        names[g["e"]] = g["name"]
    lines = []
    for e in keys:
        pts = by.get(e)
        if not pts:
            continue
        b = dict(pts).get(base)
        last = pts[-1]
        lines.append({"id": e, "name": names[e], "points": pts, "latest": last[1], "year": last[0],
                      "of_base": round(100 * last[1] / b) if b else None})
    back = [l for l in lines if l["of_base"] is not None and l["year"] > base][:2]
    parts = [f"{l['name']} at {l['of_base']}%" + (f" of its {base} level" if i == 0 else "") for i, l in enumerate(back)]
    finding = "; ".join(parts) + (f" ({back[0]['year']})" if back else "")
    return {"indicator": indicator, "base": base, "lines": lines, "finding": finding}


LAND_PARTS = [("pasture", "Pasture and grazing", "land_pasture_ha"), ("natural", "Native forest", "land_natural_forest_ha"),
              ("planted", "Planted forest", "land_planted_forest_ha"), ("forest", "Forest", "land_forest_ha"),
              ("crops", "Cropland", "land_cropland_ha")]


def land_mix(q: Q, entity: str, since: int = 1990) -> dict | None:
    """A country's land by use in its latest year (FAOSTAT), as shares of its land area, and
    the change in each since `since`."""
    ids = ["land_area_ha"] + [p[2] for p in LAND_PARTS]
    got = q(f"""
        SELECT s.indicator_id AS i, year(s.period_start) AS y, s.value AS v
        FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        WHERE s.entity_id = ? AND s.indicator_id IN ({', '.join('?' * len(ids))}) AND s.breakdown = '' AND s.variant = 'central'
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.period_start ORDER BY r.rank) = 1""", [entity] + ids)
    by: dict = defaultdict(dict)
    for g in got:
        by[g["i"]][g["y"]] = g["v"]
    area = by.get("land_area_ha")
    if not area:
        return None
    year = max(area)
    use = [p for p in LAND_PARTS if by.get(p[2])]
    split_forest = any(p[0] in ("natural", "planted") for p in use)
    use = [p for p in use if not (split_forest and p[0] == "forest")]
    parts = []
    for key, label, ind in use:
        ys = by[ind]
        y = max(y for y in ys if y <= year) if any(y <= year for y in ys) else max(ys)
        then = ys.get(since) or ys.get(min(ys, key=lambda x: abs(x - since)))
        parts.append({"id": key, "label": label, "indicator": ind, "ha": ys[y], "share": round(100 * ys[y] / area[year], 1), "year": y,
                      "change": round(100 * (ys[y] / then - 1), 1) if then else None})
    other = 100 - sum(p["share"] for p in parts)
    parts.append({"id": "other", "label": "Other (scrub, tussock, bare, built, water)", "indicator": None, "ha": None,
                  "share": round(max(0.0, other), 1), "year": year, "change": None})
    moves = sorted([p for p in parts if p["change"] is not None and abs(p["change"]) >= 5], key=lambda p: -abs(p["change"]))[:2]
    word = lambda c: f"{'up' if c > 0 else 'down'} {abs(c):.0f}%"  # noqa: E731
    finding = "; ".join(f"{p['label'] if i == 0 else p['label'].lower()} {word(p['change'])}" for i, p in enumerate(moves))
    finding += f" since {since}" if moves else ""
    nm = q("SELECT coalesce(short_name, name) AS n FROM entities WHERE entity_id = ?", [entity])
    return {"entity": entity, "name": nm[0]["n"] if nm else entity, "year": year, "since": since, "parts": parts, "finding": finding[:1].upper() + finding[1:]}


COVER = [("trees", "Tree cover"), ("shrub", "Shrubs and sparse plants"), ("grass", "Grassland"), ("crops", "Cropland"),
         ("built", "Built-up land"), ("bare", "Bare land"), ("snow", "Snow and ice"), ("water", "Inland water")]


def land_cover(q: Q, entity: str) -> dict | None:
    """A country's land cover by year from ESA's satellite maps (FAOSTAT shares, 1992 on), and the
    biggest moves since the first year (built-up land growing fastest, for most countries)."""
    ids = [f"lc_{c}_pct" for c, _ in COVER]
    got = q(f"""SELECT s.indicator_id AS i, year(s.period_start) AS y, s.value AS v FROM series s
        WHERE s.entity_id = ? AND s.indicator_id IN ({', '.join('?' * len(ids))}) AND s.breakdown = '' AND s.variant = 'central'
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.period_start ORDER BY s.source_id) = 1
        ORDER BY s.period_start""", [entity] + ids)
    if not got:
        return None
    by: dict = defaultdict(dict)
    for g in got:
        by[g["i"][3:-4]][g["y"]] = g["v"]
    years = sorted({g["y"] for g in got})
    first, last = years[0], years[-1]
    parts = []
    for c, label in COVER:
        ys = by.get(c)
        if not ys:
            continue
        a, b = ys.get(first), ys.get(last)
        parts.append({"id": c, "label": label, "points": [[y, round(ys[y], 2)] for y in years if y in ys], "latest": b,
                      "change": round(100 * (b / a - 1)) if a and b and a >= 0.2 else None})
    moves = sorted([p for p in parts if p["change"] is not None and abs(p["change"]) >= 3], key=lambda p: -abs(p["change"]))[:2]
    finding = "; ".join(f"{p['label'].lower()} {'up' if p['change'] > 0 else 'down'} {abs(p['change'])}%" for p in moves)
    nm = q("SELECT coalesce(short_name, name) AS n FROM entities WHERE entity_id = ?", [entity])
    name = nm[0]["n"] if nm else entity
    return {"entity": entity, "name": name, "first": first, "last": last, "parts": parts,
            "finding": f"{name}: {finding} since {first}" if finding else f"{name}'s land cover, {first} to {last}"}
