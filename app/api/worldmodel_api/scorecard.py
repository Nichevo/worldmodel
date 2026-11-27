"""The Scorecard: life in the countries picked, measure by measure (contract scorecard.yaml).

For each measure the first indicator that has figures for at least two of the countries is
used (one, when only one country is picked). Each country's latest figure from the indicator's
best-ranked source is taken; a figure more than `max_years_apart` years older than the row's
newest is left out, so a 2009 figure is not set against a 2022 one. Cells are ranked among the
countries picked (ties share a rank, and every tied best gets the star); "wins" counts the
rows where a country is best or tied best.
"""

from __future__ import annotations

import re
from collections.abc import Callable

Rows = Callable[..., list[dict]]


def candidates(use: list[str], known: list[str]) -> list[str]:
    """The indicator ids a measure may use, in order: plain ids that exist, and ids matching ~patterns."""
    have = set(known)
    out: list[str] = []
    for u in use:
        if u.startswith("~"):
            try:
                pat = re.compile(u[1:])
            except re.error:
                continue
            out += [k for k in sorted(known) if pat.search(k) and k not in out]
        elif u in have and u not in out:
            out.append(u)
    return out


def latest(q: Rows, inds: list[str], ids: list[str] | None) -> dict[str, list[dict]]:
    """{indicator: [{e, y, v}]}: each entity's latest estimate from the indicator's first-ranked source,
    from the last 15 years. ids None: every country."""
    if not inds:
        return {}
    where = "s.entity_id IN (SELECT unnest(?))" if ids is not None else \
        "s.entity_id IN (SELECT entity_id FROM entities WHERE type = 'country')"
    params: list = [inds] + ([ids] if ids is not None else [])
    got = q(f"""
        WITH first AS (SELECT indicator_id, arg_min(source_id, rank) AS src FROM indicator_sources GROUP BY 1)
        SELECT s.indicator_id AS i, s.entity_id AS e, year(s.period_start) AS y, s.value AS v
        FROM series s JOIN first f ON f.indicator_id = s.indicator_id AND f.src = s.source_id
        WHERE s.indicator_id IN (SELECT unnest(?)) AND {where} AND s.breakdown = ''
          AND s.variant = 'central' AND s.status = 'E' AND s.value IS NOT NULL
          AND year(s.period_start) >= year(current_date) - 15
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.entity_id ORDER BY s.period_start DESC) = 1""", params)
    by: dict[str, list[dict]] = {}
    for r in got:
        by.setdefault(r["i"], []).append(r)
    return by


def ranks(vals: dict[str, float], better: str) -> dict[str, int]:
    """1 + the number strictly better: ties share a rank."""
    lower = better == "lower"
    return {e: 1 + sum(1 for w in vals.values() if (w < v if lower else w > v)) for e, v in vals.items()}


def build(q: Rows, card: dict, ids: list[str], names: dict[str, str]) -> dict:
    known = [r["indicator_id"] for r in q("SELECT indicator_id FROM indicators")]
    meta = {r["indicator_id"]: r for r in q("SELECT indicator_id, name, unit, decimals FROM indicators")}
    apart = int(card.get("max_years_apart") or 6)
    need = 2 if len(ids) > 1 else 1
    wins = {e: 0 for e in ids}
    counted = {e: 0 for e in ids}
    groups, missing = [], []
    for g in card.get("groups") or []:
        rows_out = []
        for m in g.get("measures") or []:
            better = "lower" if m.get("better") == "lower" else "higher"
            pool = candidates(m.get("use") or [], known)
            got = latest(q, pool, ids)
            ind = next((i for i in pool if len(got.get(i) or []) >= need), None)
            if ind is None:
                missing.append({"id": m["id"], "label": m["label"], "get": m.get("get"), "source": m.get("source"),
                                "tried": pool or m.get("use") or []})
                rows_out.append(_row(m, better, None, meta, {}, {}, None))
                continue
            vals = got[ind]
            newest = max(v["y"] for v in vals)
            vals = [v for v in vals if v["y"] >= newest - apart]
            value = {v["e"]: v["v"] for v in vals}
            years = {v["e"]: v["y"] for v in vals}
            rk = ranks(value, better)
            world = None
            if m.get("world_rank"):
                every = [v for v in latest(q, [ind], None).get(ind, []) if v["y"] >= newest - apart]
                if every:
                    allv = {v["e"]: v["v"] for v in every}
                    wr = ranks(allv, better)
                    world = {"of": len(allv), "ranks": {e: wr.get(e) for e in value}}
            cells = {}
            n = len(value)
            for e in ids:
                if e not in value:
                    continue
                counted[e] += 1
                best = rk[e] == 1 and n >= need
                if best and n > 1:
                    wins[e] += 1
                cells[e] = {"value": value[e], "year": years[e], "rank": rk[e],
                            "position": round(1 - (rk[e] - 1) / (n - 1), 3) if n > 1 else 1.0, "best": best,
                            "world_rank": (world or {}).get("ranks", {}).get(e)}
            rows_out.append(_row(m, better, ind, meta, cells, years, world and world["of"]))
        groups.append({"name": g["name"], "rows": rows_out})
    return {
        "countries": [{"entity_id": e, "name": names.get(e, e), "wins": wins[e], "measures": counted[e]} for e in ids],
        "groups": groups, "missing": missing,
        "measures": sum(len(g["rows"]) for g in groups),
        "sets": card.get("sets") or [], "default_countries": card.get("default_countries") or [],
    }


def _row(m: dict, better: str, ind: str | None, meta: dict, cells: dict, years: dict, world_of: int | None) -> dict:
    im = meta.get(ind or "", {})
    return {
        "id": m["id"], "label": m["label"], "unit": m.get("unit") or im.get("unit") or "", "better": better,
        "decimals": m.get("decimals", im.get("decimals", 1)), "percent": bool(m.get("percent")),
        "indicator_id": ind, "indicator_name": im.get("name"), "source": m.get("source"), "get": m.get("get"),
        "year": max(years.values()) if years else None, "world_of": world_of, "cells": cells,
    }
