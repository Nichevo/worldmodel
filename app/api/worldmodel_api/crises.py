"""Financial crises over two centuries (Reinhart and Rogoff's crisis years, source crisis_history).

The page shows, for each year, how many of the countries with data were in each kind of
crisis (the waves), and a strip per country with its crisis spells, so countries can be
lined up against each other and against the world's waves.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

Q = Callable[[str, list], list[dict]]

KINDS = ("banking", "systemic", "default_external", "default_domestic", "currency", "inflation", "stock_crash")
NAMES = {"banking": "Banking crisis", "systemic": "Systemic banking crisis", "default_external": "Default on foreign debt",
         "default_domestic": "Default on domestic debt", "currency": "Currency crisis", "inflation": "Inflation crisis",
         "stock_crash": "Stock market crash"}


def crises(q: Q, kinds: list[str] | None = None, start: int = 1800, end: int | None = None,
           entities: list[str] | None = None) -> dict:
    kinds = [k for k in (kinds or KINDS) if k in KINDS]
    ids = [f"crisis_{k}" for k in KINDS]
    ph = ", ".join("?" for _ in ids)
    obs = q(f"""SELECT entity_id AS e, substr(indicator_id, 8) AS k, year(period_start) AS y, value AS v
                FROM series WHERE source_id = 'crisis_history' AND indicator_id IN ({ph})
                  AND variant = 'central' AND NOT is_aggregate AND year(period_start) >= ?""", [*ids, start])
    if end is not None:
        obs = [r for r in obs if r["y"] <= end]
    # The waves: share of the countries with data that year that were in each kind of crisis.
    have: dict[tuple[str, int], int] = defaultdict(int)
    hit: dict[tuple[str, int], int] = defaultdict(int)
    any_hit: dict[int, set[str]] = defaultdict(set)
    any_have: dict[int, set[str]] = defaultdict(set)
    for r in obs:
        have[(r["k"], r["y"])] += 1
        any_have[r["y"]].add(r["e"])
        if r["v"]:
            hit[(r["k"], r["y"])] += 1
            if r["k"] in kinds:
                any_hit[r["y"]].add(r["e"])
    years = sorted({y for _, y in have})
    waves = {k: [{"year": y, "share": round(hit[(k, y)] / have[(k, y)] * 100, 1), "count": hit[(k, y)],
                  "of": have[(k, y)]} for y in years if have[(k, y)]] for k in KINDS}
    waves["any"] = [{"year": y, "share": round(len(any_hit[y]) / len(any_have[y]) * 100, 1), "count": len(any_hit[y]),
                     "of": len(any_have[y])} for y in years if any_have[y]]
    # The strips: each country's spells from the events, and how many crisis years it had.
    ev = q("""SELECT entity_id AS e, subkind AS k, year(start_date) AS a, year(end_date) AS b FROM events
              WHERE source_id = 'crisis_history' AND kind = 'crisis' ORDER BY entity_id, start_date""", [])
    strips: dict[str, dict] = {}
    for r in ev:
        if r["k"] not in kinds or (end is not None and r["a"] > end) or (r["b"] or r["a"]) < start:
            continue
        s = strips.setdefault(r["e"], {"entity_id": r["e"], "spells": [], "years": 0})
        a, b = max(r["a"], start), min(r["b"] or r["a"], end or 9999)
        s["spells"].append({"kind": r["k"], "from": a, "to": b})
        s["years"] += b - a + 1
    countries = sorted({r["e"] for r in obs})
    for e in countries:
        strips.setdefault(e, {"entity_id": e, "spells": [], "years": 0})
    order = sorted(strips.values(), key=lambda s: (-s["years"], s["entity_id"]))
    if entities:
        keep = set(entities)
        order = [s for s in order if s["entity_id"] in keep] + [s for s in order if s["entity_id"] not in keep]
    return {"kinds": [{"id": k, "name": NAMES[k]} for k in KINDS], "selected": kinds,
            "years": [years[0], years[-1]] if years else None, "waves": waves, "strips": order,
            "countries": len(countries)}
