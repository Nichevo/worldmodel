"""Indicators, their quality grades and your own ratios."""

from __future__ import annotations

import json

from fastapi import Body, HTTPException

from worldmodel_contract import families, local
from worldmodel_contract import quality as qual
from worldmodel_api import core, userdata
from worldmodel_api.core import _build_id, api, cursor, rows, split


# ----------------------------------------------------------------------------- indicators
_ind_cache: dict = {"key": None, "rows": []}


def _indicator_rows() -> list[dict]:
    """Every indicator with its years, country count and sources; cached per build."""
    build = core.warehouse.current().meta.get("build_id")
    mine = userdata.ratios()
    key = (build, json.dumps(mine, sort_keys=True))
    if _ind_cache["key"] != key or build is None:
        found = rows("""
            SELECT i.*, min(year(s.period_start)) AS first_year, max(year(s.period_start)) AS last_year,
                max(year(s.period_start)) FILTER (WHERE s.status = 'E') AS last_estimate_year,
                count(DISTINCT s.entity_id) FILTER (WHERE e.type = 'country') AS countries
            FROM indicators i LEFT JOIN series s USING (indicator_id) LEFT JOIN entities e USING (entity_id)
            GROUP BY ALL ORDER BY i.domain, i.name""")
        # The year a map opens on: the latest estimate year with at least half the countries
        # of the indicator's best-covered year (the very latest year often has only a few),
        # counted in the first-ranked source, which is the one maps and rankings show.
        main_year = {r["indicator_id"]: r["y"] for r in rows("""
            WITH first AS (SELECT indicator_id, arg_min(source_id, rank) AS source_id FROM indicator_sources GROUP BY 1),
            n AS (
                SELECT s.indicator_id, year(s.period_start) AS y, count(DISTINCT s.entity_id) AS c
                FROM series s JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
                LEFT JOIN first f ON f.indicator_id = s.indicator_id
                WHERE s.status = 'E' AND s.variant = 'central' AND s.breakdown = ''
                    AND (f.source_id IS NULL OR s.source_id = f.source_id) GROUP BY 1, 2)
            SELECT indicator_id, max(y) AS y FROM n
            WHERE c >= (SELECT max(c) FROM n m WHERE m.indicator_id = n.indicator_id) / 2 GROUP BY 1""")}
        srcs = rows("SELECT r.*, s.short_name AS source_name, s.licence FROM indicator_sources r "
                    "LEFT JOIN sources s USING (source_id) ORDER BY r.indicator_id, r.rank")
        for f in found:
            f["synonyms"] = split((f["synonyms"] or "").replace("|", ","))
            f["sources"] = [s for s in srcs if s["indicator_id"] == f["indicator_id"]]
            f["available"] = f["first_year"] is not None
            f["default_on"] = bool(f.get("default_on", True))
            f["main_year"] = main_year.get(f["indicator_id"], f["last_estimate_year"])
        # A ratio is credited to the sources of its two indicators; ratio says what it is made of.
        by_id = {f["indicator_id"]: f for f in found}
        for r in mine:
            f = by_id.get(r["id"])
            if f is None:
                continue
            f["ratio"] = {k: r[k] for k in ("numerator", "denominator", "multiplier")}
            f["sources"] = [{**s, "rank": 1} for part in (r["numerator"], r["denominator"])
                            for s in by_id.get(part, {}).get("sources", [])[:1]]
        # Indicators that sit under another (Male population under Population...): the drop-downs nest them.
        under = families.parents(found)
        for f in found:
            f["part_of"] = under.get(f["indicator_id"])
        _ind_cache.update(key=key, rows=found)
    return _ind_cache["rows"]


@api.get("/indicators")
def indicators(domain: str | None = None):
    """Every indicator, with `enabled`: whether it is switched on (Indicators page)
    for the panel menus (switched-off indicators still serve data), and its quality:
    `grade` (A to D, yours when you set one), `type` (level, per person, rate...) and `starred`."""
    over = userdata.indicator_overrides()
    q = _quality()
    out = []
    for f in _indicator_rows():
        if domain is not None and f["domain"] != domain:
            continue
        g = q.get(f["indicator_id"], {})
        out.append({**f, "enabled": over.get(f["indicator_id"], f["default_on"]), "grade": g.get("grade"),
                    "type": g.get("type") or qual.measure_type(f["indicator_id"], f["name"], f["unit"]),
                    "starred": bool(g.get("starred"))})
    return out


_years_cache: dict = {"key": None, "out": {}}


@api.get("/indicators/years")
def indicator_years():
    """What years each indicator has, for the year strips in the indicator drop-downs:
    `from` (first year), `e` (countries with figures in each year from then on: the source's
    estimates) and `p` (countries with the source's own projections or forecasts in each
    year, after the estimates), plus `by` (the sources that project). Counts are countries,
    or any place when an indicator has no country figures (world-only series)."""
    build = _build_id()
    if _years_cache["key"] == build:
        return _years_cache["out"]
    found = rows("""
        SELECT s.indicator_id, year(s.period_start) AS y,
            count(DISTINCT s.entity_id) FILTER (WHERE s.status <> 'P' AND e.type = 'country') AS ec,
            count(DISTINCT s.entity_id) FILTER (WHERE s.status <> 'P') AS ea,
            count(DISTINCT s.entity_id) FILTER (WHERE s.status = 'P' AND e.type = 'country') AS pc,
            count(DISTINCT s.entity_id) FILTER (WHERE s.status = 'P') AS pa
        FROM series s JOIN entities e USING (entity_id)
        WHERE s.variant = 'central' AND s.breakdown = ''
        GROUP BY 1, 2 ORDER BY 1, 2""")
    projectors = rows("""
        SELECT DISTINCT s.indicator_id, coalesce(src.short_name, s.source_id) AS name
        FROM series s LEFT JOIN sources src USING (source_id) WHERE s.status = 'P' ORDER BY 1, 2""")
    by_ind: dict[str, list[dict]] = {}
    for r in found:
        by_ind.setdefault(r["indicator_id"], []).append(r)
    out: dict[str, dict] = {}
    for iid, rs in by_ind.items():
        countries = any(r["ec"] or r["pc"] for r in rs)
        ek, pk = ("ec", "pc") if countries else ("ea", "pa")
        first, last = rs[0]["y"], rs[-1]["y"]
        e = [0] * (last - first + 1)
        p = [0] * (last - first + 1)
        for r in rs:
            e[r["y"] - first] = r[ek]
            p[r["y"] - first] = r[pk]
        # Trim trailing zeros so short lists stay short.
        while e and not e[-1]:
            e.pop()
        while p and not p[-1]:
            p.pop()
        out[iid] = {"from": first, "e": e, "p": p, "countries": countries}
    for r in projectors:
        if r["indicator_id"] in out:
            out[r["indicator_id"]].setdefault("by", []).append(r["name"])
    _years_cache.update(key=build, out=out)
    return out


# ----------------------------------------------------------------------------- indicator quality
_q_cache: dict = {"key": None, "scores": {}}


def _quality_raw() -> dict[str, dict]:
    """The grades worked out for the live build: the pipeline's saved copy, else worked out here once."""
    build = _build_id()
    key = (build, json.dumps(userdata.ratios(), sort_keys=True))
    if _q_cache["key"] != key:
        found = qual.load(local.home(), build)
        if found is None or any(r["id"] not in found for r in userdata.ratios()):
            found = qual.compute(cursor())
            try:
                if not userdata.ratios():
                    qual.save(local.home(), build, found)
            except OSError:
                pass
        _q_cache.update(key=key, scores=found)
    return _q_cache["scores"]


def _quality() -> dict[str, dict]:
    return qual.with_choices(_quality_raw())


@api.get("/quality")
def quality_list():
    """Every indicator's six quality scores (1 to 5) with a note on each, its grade (A core,
    B good, C usable, D exploratory), the grade worked out before any override of yours,
    its measure type and whether you starred it."""
    return {"scores": qual.SCORES, "grades": qual.GRADES, "types": qual.MEASURE_TYPES, "weights": qual.WEIGHTS,
            "indicators": _quality()}


@api.put("/quality/{indicator_id}")
def quality_set(indicator_id: str, change: dict = Body(...)):
    """Star an indicator ({"starred": true}) or set its grade ({"grade": "B"}; null goes back to
    the worked-out grade). Both stay through refreshes."""
    if indicator_id not in _quality_raw():
        raise HTTPException(404, f"no indicator {indicator_id}")
    if "grade" in change and change["grade"] not in (None, *qual.GRADES):
        raise HTTPException(422, f"grade must be one of {', '.join(qual.GRADES)} or null")
    if "starred" in change:
        userdata.set_star(indicator_id, bool(change["starred"]))
    if "grade" in change:
        userdata.set_grade(indicator_id, change["grade"])
    return _quality()[indicator_id]


@api.get("/quality/summary")
def quality_summary():
    """For the Quality tab on Data status: how many indicators sit at each grade, by topic and by
    source, and what changed since the build before (grades lost and gained, figures gone stale,
    new problems found by the checks, starred indicators whose grade fell)."""
    q = _quality()
    rows_ = {f["indicator_id"]: f for f in _indicator_rows()}
    by_domain: dict[str, dict[str, int]] = {}
    by_source: dict[str, dict[str, int]] = {}
    totals = {g: 0 for g in qual.GRADES}
    for iid, v in q.items():
        g = v["grade"]
        totals[g] += 1
        dom = rows_.get(iid, {}).get("domain") or "other"
        by_domain.setdefault(dom, {k: 0 for k in qual.GRADES})[g] += 1
        by_source.setdefault(v.get("source_id") or "none", {k: 0 for k in qual.GRADES})[g] += 1
    build = _build_id()
    before = qual.previous(local.home(), build)
    ch = qual.changes(before[1], _quality_raw(), set(qual.stars())) if before else None
    names = {k: r["name"] for k, r in rows_.items()}
    if ch:
        for k in ch:
            for c in ch[k]:
                c["name"] = names.get(c["indicator_id"], c["indicator_id"])
    return {"totals": totals, "by_domain": by_domain, "by_source": by_source, "since": before[0] if before else None,
            "changes": ch, "starred": [{"indicator_id": i, "name": names.get(i, i), "grade": q.get(i, {}).get("grade")}
                                        for i in qual.stars()]}


@api.get("/indicators/{indicator_id}")
def indicator(indicator_id: str):
    for i in indicators():
        if i["indicator_id"] == indicator_id:
            return i
    raise HTTPException(404, f"no indicator {indicator_id}")


@api.put("/indicator-switches")
def switch_indicators(changes: dict[str, bool] = Body(...)):
    """Switch indicators on or off: {"tfr": true, "births": false}."""
    defaults = {f["indicator_id"]: f["default_on"] for f in _indicator_rows()}
    unknown = [k for k in changes if k not in defaults]
    if unknown:
        raise HTTPException(404, f"no indicator {', '.join(unknown[:5])}")
    userdata.set_indicators(changes, defaults)
    return {"changed": len(changes)}


@api.delete("/indicator-switches")
def reset_indicator_switches():
    """Back to the defaults."""
    userdata.reset_indicators()
    return {"reset": True}


# ----------------------------------------------------------------------------- your ratios
def _plain_indicator_ids() -> set[str]:
    return {f["indicator_id"] for f in _indicator_rows() if not f["indicator_id"].startswith(userdata.RATIO_PREFIX)}


@api.get("/ratios")
def get_ratios():
    """Your ratios: indicators made from two others, numerator / denominator x multiplier."""
    return userdata.ratios()


@api.post("/ratios")
def add_ratio(data: dict = Body(...)):
    """Make a ratio: {name, numerator, denominator, multiplier?, unit?, decimals?, description?}.
    It appears among the indicators (domain "Your ratios") at once."""
    try:
        return userdata.save_ratio(data, _plain_indicator_ids())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.put("/ratios/{ratio_id}")
def change_ratio(ratio_id: str, data: dict = Body(...)):
    try:
        return userdata.save_ratio(data, _plain_indicator_ids(), ratio_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError:
        raise HTTPException(404, f"no ratio {ratio_id}")


@api.delete("/ratios/{ratio_id}")
def remove_ratio(ratio_id: str):
    if not userdata.delete_ratio(ratio_id):
        raise HTTPException(404, f"no ratio {ratio_id}")
    return {"deleted": ratio_id}
