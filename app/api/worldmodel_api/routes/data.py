"""Figures, Learn, the Data console, the population what-if, forecasts and source comparison."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Body, HTTPException, Query, Request
from fastapi.responses import Response

from worldmodel_contract import catalogue, cohort, energy_flow
from worldmodel_contract import forecast as statforecast
from worldmodel_contract.queries import SeriesQuery, divergence_sql, forecast_pairs_sql, series_sql
from worldmodel_api import core, grid, learn, userdata
from worldmodel_api import public as public_api
from worldmodel_api.core import api, cursor, rows, split


# ----------------------------------------------------------------------------- data
def _series(indicator: str, entities: str | None, members_of: str | None, start: int | None, end: int | None,
            source: str | None, breakdown: str | None, variant: str, projections: bool, as_of: date | None):
    q = SeriesQuery(indicator_id=indicator, entity_ids=split(entities), members_of=members_of, start=start,
                    end=end, source_id=source, breakdown=breakdown, variant=variant, projections=projections,
                    as_of=as_of)
    sql, params = series_sql(q)
    return rows(sql, params)


def _respond(data: list[dict], fmt: str, name: str, extra: dict | None = None):
    if fmt == "csv":
        buf = io.StringIO()
        if data:
            w = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if fmt == "parquet":
        import duckdb
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.parquet"
            con = duckdb.connect()
            con.execute("CREATE TABLE t AS SELECT * FROM read_json_auto(?)",
                        [_write_json(Path(d) / "rows.json", data)])
            con.execute(f"COPY t TO '{path.as_posix()}' (FORMAT parquet)")
            con.close()
            return Response(path.read_bytes(), media_type="application/vnd.apache.parquet",
                            headers={"Content-Disposition": f'attachment; filename="{name}.parquet"'})
    return {**(extra or {}), "rows": data}


def _write_json(path: Path, data: list[dict]) -> str:
    path.write_text(json.dumps(data, default=str))
    return str(path)


@api.get("/series")
def series(
    indicator: str,
    entities: str | None = Query(None, description="Comma-separated entity ids"),
    members_of: str | None = Query(None, description="A group id: every country that has been a member"),
    start: int | None = None,
    end: int | None = None,
    source: str | None = Query(None, description="Default: the indicator's first-ranked source"),
    breakdown: str | None = Query("", description="'' for totals; for example age=0-4|sex=male"),
    variant: str = "central",
    projections: bool = True,
    as_of: date | None = Query(None, description="Values as known on this date, from stored vintages"),
    format: Literal["json", "csv", "parquet"] = "json",
):
    if not rows("SELECT 1 FROM indicators WHERE indicator_id = ?", [indicator]):
        raise HTTPException(404, f"no indicator {indicator}")
    data = _series(indicator, entities, members_of, start, end, source, breakdown, variant, projections, as_of)
    return _respond(data, format, f"{indicator}", {"indicator": indicator, "as_of": as_of})


@api.get("/series-many")
def series_many(indicators: str = Query(..., description="Comma-separated indicator ids, at most 60"),
                entities: str | None = Query(None, description="Comma-separated entity ids"),
                start: int | None = None, end: int | None = None):
    """Several indicators for the same entities in one call ({indicator: rows}), so a page of
    charts makes one request instead of dozens. Unknown indicators come back empty."""
    ids = split(indicators)[:60]
    known = {r["indicator_id"] for r in rows("SELECT indicator_id FROM indicators WHERE indicator_id IN (SELECT unnest(?))", [ids])}
    return {i: (_series(i, entities, None, start, end, None, "", "central", True, None) if i in known else []) for i in ids}


@api.get("/map")
def map_values(indicator: str, year: int, source: str | None = None,
               back: int = Query(0, ge=0, le=50, description="Fill a missing year with the country's latest figure up to this many years before")):
    """One value per country for a year, to colour the map. With `back`, a country with no figure
    that year gets its latest one from the years before, and each row says which year it is from."""
    data = _series(indicator, None, None, year - back, year, source, "", "central", True, None)
    countries = {r["entity_id"] for r in rows("SELECT entity_id FROM entities WHERE type = 'country'")}
    if not back:
        return {"indicator": indicator, "year": year,
                "rows": [{"entity_id": r["entity_id"], "value": r["value"], "status": r["status"]}
                         for r in data if r["entity_id"] in countries]}
    best: dict[str, dict] = {}
    for r in data:
        if r["entity_id"] not in countries or r["value"] is None:
            continue
        y = int(r["period"][:4])
        if r["entity_id"] not in best or y > best[r["entity_id"]]["year"]:
            best[r["entity_id"]] = {"entity_id": r["entity_id"], "value": r["value"], "status": r["status"], "year": y}
    return {"indicator": indicator, "year": year, "back": back, "rows": list(best.values())}


@api.get("/map/range")
def map_range(indicator: str, start: int | None = None, end: int | None = None):
    """Every country's values over a span of years, for sparklines: rows[entity] lines up with years."""
    data = _series(indicator, None, None, start, end, None, "", "central", True, None)
    countries = {r["entity_id"] for r in rows("SELECT entity_id FROM entities WHERE type = 'country'")}
    years = sorted({int(r["period"][:4]) for r in data})
    at = {y: i for i, y in enumerate(years)}
    out: dict[str, list] = {}
    for r in data:
        if r["entity_id"] in countries:
            out.setdefault(r["entity_id"], [None] * len(years))[at[int(r["period"][:4])]] = r["value"]
    last_e = max((int(r["period"][:4]) for r in data if r["status"] == "E"), default=None)
    return {"indicator": indicator, "years": years, "last_estimate_year": last_e, "rows": out}


@api.get("/size-in-countries")
def size_in_countries(indicator: str, entity: str = "world", step: int = Query(2, ge=1, le=20), what: Literal["change", "level"] = "change",
                      unit: str = "NZL", start: int | None = None):
    """A total (GDP, people, emissions...) told in countries: each step's change (or level) of the
    entity, next to the country whose own level that year is closest, and how many of the unit country it is."""
    if not rows("SELECT 1 FROM indicators WHERE indicator_id = ?", [indicator]):
        raise HTTPException(404, f"no indicator {indicator}")
    data = _series(indicator, None, None, start, None, None, "", "central", False, None)
    names = {r["entity_id"]: r["short_name"] or r["name"] for r in rows("SELECT entity_id, name, short_name FROM entities WHERE type = 'country'")}
    by: dict[str, dict[int, float]] = {}
    for r in data:
        if r["value"] is not None:
            by.setdefault(r["entity_id"], {})[int(r["period"][:4])] = r["value"]
    base = by.get(entity, {})
    if not base:
        raise HTTPException(404, f"no {indicator} figures for {entity}")
    years = sorted(base)
    out = []
    y = years[0] + (step if what == "change" else 0)
    while y <= years[-1]:
        if y in base and (what == "level" or (y - step) in base):
            v = base[y] - base[y - step] if what == "change" else base[y]
            pool = [(c, vals[y]) for c, vals in by.items() if c in names and c != entity and y in vals and vals[y] > 0]
            match = min(pool, key=lambda cv: abs(cv[1] - abs(v))) if pool and v else None
            u = by.get(unit, {}).get(y)
            out.append({"year": y, "from": y - step if what == "change" else None, "value": v,
                        "match": {"id": match[0], "name": names[match[0]], "value": match[1]} if match else None,
                        "in_unit": v / u if u else None})
        y += step
    return {"indicator": indicator, "entity": entity, "step": step, "what": what, "unit": unit,
            "unit_name": names.get(unit, unit), "rows": out}


@api.get("/popup")
def popup(entity: str, indicator: str, year: int):
    """What a country popup shows: the value and its rank among countries, the change over
    ten years, and the series for the country, its region (subregion, else continent) and the world."""
    found = rows("SELECT entity_id, short_name, type FROM entities WHERE entity_id = ?", [entity])
    if not found:
        raise HTTPException(404, f"no entity {entity}")
    if not rows("SELECT 1 FROM indicators WHERE indicator_id = ?", [indicator]):
        raise HTTPException(404, f"no indicator {indicator}")
    groups = rows("""SELECT g.entity_id, g.short_name, g.type FROM memberships m JOIN entities g ON g.entity_id = m.group_id
        WHERE m.member_id = ? AND g.type IN ('subregion', 'continent') AND m.valid_to IS NULL
        ORDER BY g.type = 'continent'""", [entity])
    ids = [entity, *[g["entity_id"] for g in groups], "world"]
    data = _series(indicator, ",".join(dict.fromkeys(ids)), None, None, None, None, "", "central", True, None)
    by: dict[str, list] = {}
    for r in data:
        by.setdefault(r["entity_id"], []).append([int(r["period"][:4]), r["value"], r["status"]])
    region = next((g for g in groups if by.get(g["entity_id"])), None)
    now_ = next((p for p in by.get(entity, []) if p[0] == year), None)
    before = next((p for p in by.get(entity, []) if p[0] == year - 10), None)
    ranked = sorted((r["value"] for r in map_values(indicator, year)["rows"]), reverse=True)
    rank = ranked.index(now_[1]) + 1 if now_ and found[0]["type"] == "country" and now_[1] in ranked else None
    return {"entity": entity, "name": found[0]["short_name"], "type": found[0]["type"], "indicator": indicator,
            "year": year, "value": now_[1] if now_ else None, "status": now_[2] if now_ else None,
            "rank": rank, "of": len(ranked),
            "change10": {"from_year": year - 10, "value": now_[1] - before[1]} if now_ and before else None,
            "region": {"entity_id": region["entity_id"], "name": region["short_name"]} if region else None,
            "series": {"entity": by.get(entity, []), "region": by.get(region["entity_id"], []) if region else [],
                       "world": by.get("world", []) if entity != "world" else []}}


@api.get("/pyramid")
def pyramid(entity: str, year: int):
    """Population by age and sex. Age data comes every few years, so a year without it
    falls back to the latest year before it (or the first year); `year` says which was used."""
    years = [r["y"] for r in rows("SELECT DISTINCT year(period_start) AS y FROM series WHERE "
                                  "indicator_id = 'pop_by_age_sex' AND entity_id = ? ORDER BY 1", [entity])]
    if years and year not in years:
        year = max((y for y in years if y <= year), default=years[0])
    data = rows("""
        SELECT split_part(split_part(breakdown, '|', 1), '=', 2) AS age,
            split_part(split_part(breakdown, '|', 2), '=', 2) AS sex, value, status, source_id, vintage, is_aggregate
        FROM series WHERE indicator_id = 'pop_by_age_sex' AND entity_id = ? AND period_start = make_date(?, 1, 1)
            AND variant = 'central'""", [entity, year])
    groups: dict[str, dict] = {}
    for r in data:
        g = groups.setdefault(r["age"], {"age": r["age"]})
        g[r["sex"]] = r["value"]
    ordered = sorted(groups.values(), key=lambda g: int(g["age"].rstrip("+").split("-")[0]))
    first = data[0] if data else {}
    return {"entity": entity, "year": year, "groups": ordered, "years_available": years,
            "status": first.get("status"), "source_id": first.get("source_id"), "vintage": first.get("vintage")}


@api.get("/energy-flow")
def energy_flow_chart(entity: str, year: int | None = None, source: str | None = None):
    """Where a country's or group's energy comes from and goes (a Sankey chart), from its energy
    balance (energy_balance_pj, breakdown flow=<row>|fuel=<fuel>). A country's own balance
    (MBIE for New Zealand) is drawn first where held, else the UN's; `sources` lists the
    others to switch to. Without a year, or for a year without a balance, the latest year
    before it; `years` lists them all. `population` lets the chart show energy per person."""
    base = ("FROM series WHERE indicator_id = 'energy_balance_pj' AND entity_id = ? AND variant = 'central' "
            "AND breakdown LIKE 'flow=%'")
    held = rows(f"""SELECT s.source_id, coalesce(src.short_name, s.source_id) AS name, min(year(s.period_start)) AS first,
            max(year(s.period_start)) AS last, bool_or(s.is_aggregate) AS summed, max(s.coverage) AS coverage
        FROM ({base.replace('FROM series', 'SELECT * FROM series')}) s LEFT JOIN sources src ON src.source_id = s.source_id
        GROUP BY 1, 2""", [entity])
    if not held:
        return {"entity": entity, "year": None, "years": [], "nodes": [], "links": [], "totals": None, "sources": []}
    # the country's own balance first; for a group the source summed over the most members
    held.sort(key=lambda r: (r["source_id"] != "mbie_energy", -(r["coverage"] or 0), r["source_id"] != "unsd_energy"))
    src = source if any(r["source_id"] == source for r in held) else held[0]["source_id"]
    years = [r["y"] for r in rows(f"SELECT DISTINCT year(period_start) AS y {base} AND source_id = ? ORDER BY 1", [entity, src])]
    if year not in years:
        year = max((y for y in years if y <= (year or years[-1])), default=years[-1])
    data = rows(f"""SELECT split_part(split_part(breakdown, '|', 1), '=', 2) AS flow,
            split_part(split_part(breakdown, '|', 2), '=', 2) AS fuel, value, source_id, vintage, coverage
        {base} AND source_id = ? AND year(period_start) = ?""", [entity, src, year])
    out = energy_flow.flow([(r["flow"], r["fuel"], r["value"]) for r in data])
    pop = rows("""SELECT value FROM series WHERE entity_id = ? AND indicator_id = 'pop_total' AND variant = 'central'
        AND breakdown = '' AND year(period_start) = ? ORDER BY source_id = 'un_wpp' DESC LIMIT 1""", [entity, year])
    return {"entity": entity, "year": year, "years": years, "unit": "PJ", "source_id": src,
            "vintage": data[0]["vintage"] if data else None, "coverage": data[0]["coverage"] if data else None,
            "population": pop[0]["value"] if pop else None,
            "sources": [{"source_id": r["source_id"], "name": r["name"], "first": r["first"], "last": r["last"]} for r in held],
            **out}


@api.get("/grid-now/{country}")
def grid_now(country: str):
    """A country's electricity grid as it runs: generation by fuel for the last two days, demand,
    links to neighbours (New Zealand, Australia, Great Britain, the US). Read live while the
    card is open, kept five minutes, never saved."""
    return grid.grid_now(country.upper(), bool(userdata.settings().get("grid_now", True)))


@api.get("/power-links")
def power_links_layer(year: int | None = None):
    """Electricity traded between European countries in a year, as lines between capitals."""
    return grid.power_links(rows, year)


# ----------------------------------------------------------------------------- learn
@api.get("/learn/quiz")
def learn_quiz(topic: str | None = None, n: int = Query(10, ge=1, le=30), seed: int | None = None, familiar: bool = True):
    """Quiz questions made from the warehouse's figures (topics in learn.yaml): which of two is higher, which of
    four is highest, did a figure go up or down. Each carries the real values, unit and source."""
    try:
        return learn.quiz(rows, topic, n, seed, familiar)
    except KeyError:
        raise HTTPException(404, f"No quiz topic '{topic}'. Topics: {', '.join(t['id'] for t in learn.topics())}")


@api.get("/learn/guess")
def learn_guess(entity: str, indicator: str, hide_from: int):
    """A "draw your guess" chart: the line up to hide_from, and the axis range to draw on."""
    try:
        return learn.guess_chart(rows, entity, indicator, hide_from)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@api.post("/learn/guess")
def learn_guess_check(body: dict = Body(...)):
    """Score a drawn line against the real one, show the real one, and keep the score in your record."""
    try:
        g = learn.guess_chart(rows, str(body.get("entity", "")), str(body.get("indicator", "")), int(body.get("hide_from", 0)))
    except (LookupError, ValueError) as exc:
        raise HTTPException(404, str(exc))
    full = learn.figures(rows, [g["indicator_id"]], [g["entity_id"]], since=1900)[g["indicator_id"]][g["entity_id"]]
    hidden = [[y, v] for y, v in sorted(full.items()) if y > g["hide_from"]]
    drawn = [p for p in body.get("drawn") or [] if isinstance(p, (list, tuple)) and len(p) == 2][:400]
    got = learn.score_guess(hidden, drawn, g["y_max"] - g["y_min"])
    learn.remember("guesses", {"entity": g["entity_id"], "indicator": g["indicator_id"], "hide_from": g["hide_from"], "score": got["score"]})
    return {**got, "actual": hidden}


@api.post("/learn/quiz/score")
def learn_quiz_score(body: dict = Body(...)):
    """Keep a finished quiz round in your record."""
    topic = str(body.get("topic", "all"))[:40]
    right, asked = int(body.get("right", 0)), int(body.get("asked", 0))
    if not 0 <= right <= asked <= 30:
        raise HTTPException(422, "right must be between 0 and asked (at most 30)")
    return learn.remember("quiz", {"topic": topic, "right": right, "asked": asked})


@api.get("/learn")
def learn_page():
    """Everything the Learn page lists: quiz topics, ready-made guesses, tours and your record."""
    cat = catalogue.learn()
    return {"topics": [{"id": t["id"], "name": t["name"], "indicators": [i["id"] for i in t["indicators"]]} for t in cat.get("quiz", [])],
            "guesses": learn.presets(), "tours": cat.get("tours", []), "record": learn.record()}


# ----------------------------------------------------------------------------- data console
def _console(request: Request) -> None:
    if not userdata.settings().get("data_console"):
        raise HTTPException(403, "The Data console is switched off. Settings > Data console turns it on.")
    if not public_api.is_local(request):
        raise HTTPException(403, "The Data console works only on the PC running the app, not from other devices.")


@api.get("/console/tables")
def console_tables(request: Request):
    """The warehouse's tables and views with their columns, and your saved queries."""
    _console(request)
    return {"tables": learn.tables(cursor()), "saved": learn.saved_queries(), "max_rows": learn.MAX_ROWS}


@api.post("/console/query")
def console_query(request: Request, body: dict = Body(...)):
    """One read-only question in SQL (SELECT, WITH or FROM), with a row limit and a 20-second time limit."""
    _console(request)
    try:
        return learn.run_sql(cursor(), str(body.get("sql", "")), int(body.get("limit", 1000)))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.post("/console/saved")
def console_save(request: Request, body: dict = Body(...)):
    _console(request)
    try:
        learn.check_sql(str(body.get("sql", "")))
        return learn.save_query(str(body.get("name", "")), str(body.get("sql", "")))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.delete("/console/saved")
def console_drop(request: Request, name: str):
    _console(request)
    return learn.drop_query(name)


@api.get("/partners")
def partners(indicator: str, entity: str, direction: Literal["in", "out"] = "in", year: int | None = None,
             limit: int = Query(10, ge=1, le=300)):
    """The countries behind a by-country indicator (breakdown origin=<country>), largest first.
    in: where the people living in `entity` come from. out: where people from `entity` live.
    Without a year, the latest year with figures; `years` lists them all."""
    if direction == "in":
        where, params, partner = "s.entity_id = ? AND s.breakdown LIKE 'origin=%'", [indicator, entity], "substr(s.breakdown, 8)"
    else:
        where, params, partner = "s.breakdown = ?", [indicator, f"origin={entity}"], "s.entity_id"
    base = f"FROM series s WHERE s.indicator_id = ? AND s.variant = 'central' AND {where}"
    years = [r["y"] for r in rows(f"SELECT DISTINCT year(s.period_start) AS y {base} ORDER BY 1", params)]
    if not years:
        return {"indicator": indicator, "entity": entity, "direction": direction, "year": None, "years": [],
                "total": None, "rows": []}
    if year not in years:
        year = max((y for y in years if y <= (year or years[-1])), default=years[-1])
    data = rows(f"""SELECT p.partner AS entity_id, coalesce(e.short_name, p.partner) AS name, p.value, p.source_id
        FROM (SELECT {partner} AS partner, s.value, s.source_id {base} AND year(s.period_start) = ?) p
        LEFT JOIN entities e ON e.entity_id = p.partner ORDER BY p.value DESC""", [*params, year])
    return {"indicator": indicator, "entity": entity, "direction": direction, "year": year, "years": years,
            "total": sum(r["value"] for r in data), "rows": data[:limit]}


# ----------------------------------------------------------------------------- population what-if
_whatif_inputs: dict[tuple, cohort.Inputs | None] = {}
SUMMARY_YEARS = (2030, 2050, 2075, 2100)


def _inputs(entity: str) -> cohort.Inputs | None:
    key = (core.warehouse.current().meta.get("build_id"), entity)
    if key not in _whatif_inputs:
        if len(_whatif_inputs) > 64:
            _whatif_inputs.clear()
        _whatif_inputs[key] = cohort.prepare(cursor().execute(cohort.inputs_sql(), [entity]).fetchall())
    return _whatif_inputs[key]


@api.get("/whatif")
def whatif(entity: str,
           tfr: float = Query(0, ge=-3, le=3, description="change in children per woman, in full after `phase` years"),
           e0: float = Query(0, ge=-20, le=20, description="change in life expectancy at birth, years"),
           mig: float = Query(1, ge=0, le=3, description="multiplier on net migration"),
           extra: float = Query(0, ge=-5_000_000, le=5_000_000, description="extra net migrants a year"),
           phase: int = Query(10, ge=0, le=50, description="years until the changes are in full"),
           hold: bool = Query(False, description="fertility stays at its base-year level instead of the UN path"),
           end: int | None = None):
    """The population what-if for one country: the UN medium projection (baseline) and
    the same with the levers moved (scenario), by year, with pyramids, key shares, the
    inputs used, the UN's own ranges where loaded, and how far the model itself is from
    the UN at default settings (raw_error)."""
    found = rows("SELECT short_name, type FROM entities WHERE entity_id = ?", [entity])
    if not found:
        raise HTTPException(404, f"no entity {entity}")
    inp = _inputs(entity)
    if inp is None:
        raise HTTPException(404, f"{found[0]['short_name']} has no population by age and sex to start from")
    stop = min(inp.last_year, end) if end else inp.last_year
    if stop <= inp.base_year:
        raise HTTPException(422, f"nothing to project: the data ends in {inp.base_year}")
    levers = cohort.Levers(tfr=tfr, e0=e0, migration=mig, extra_migrants=extra, phase=phase, hold_fertility=hold)
    out = cohort.whatif(inp.base_year, inp.base, inp.raw, stop, levers, inp.un, inp.un_totals)
    years = out["years"]
    for side in ("baseline", "scenario"):
        out[side] = [round(v) for v in out[side]]
    for y, p in out["pyramids"].items():
        for side in p.values():
            side["male"] = [round(v) for v in side["male"]]
            side["female"] = [round(v) for v in side["female"]]
    keys = [y for y in (inp.base_year, *SUMMARY_YEARS) if y in out["pyramids"]] or [years[-1]]
    if years[-1] not in keys:
        keys.append(years[-1])
    out["summary"] = [{"year": y, **{side: cohort.summary(cohort.Pyramid(**out["pyramids"][y][side]))
                                     for side in ("baseline", "scenario")}} for y in keys]
    ranges = rows("""SELECT variant, year(period_start) AS y, value FROM series
        WHERE entity_id = ? AND indicator_id = 'pop_total' AND source_id = 'un_wpp' AND variant <> 'central'
            AND freq = 'A'""", [entity])
    by: dict[str, dict[int, float]] = {}
    for r in ranges:
        by.setdefault(r["variant"], {})[r["y"]] = r["value"]
    out["ranges"] = {k: [v.get(y) for y in years] for k, v in by.items()}
    out.update(entity=entity, name=found[0]["short_name"], type=found[0]["type"],
               levers={"tfr": tfr, "e0": e0, "mig": mig, "extra": extra, "phase": phase, "hold": int(hold)})
    return out


# ----------------------------------------------------------------------------- statistical forecasts
FORECASTERS = ("imf_weo", "oecd_eo", "wb_gep")
_fc_cache: dict[tuple, dict] = {}


def _indicator_meta(indicator: str) -> dict:
    found = rows("SELECT name, unit, decimals, bound_min, bound_max FROM indicators WHERE indicator_id = ?", [indicator])
    if not found:
        raise HTTPException(404, f"no indicator {indicator}")
    return found[0]


def _stat_forecast(indicator: str, entity: str, source: str | None, horizon: int, model: str | None) -> dict:
    """The statistical forecast of one country's series, cached per build."""
    key = (core.warehouse.current().meta.get("build_id"), indicator, entity, source, horizon, model,
           json.dumps(userdata.ratios(), sort_keys=True) if indicator.startswith(userdata.RATIO_PREFIX) else "")
    if key in _fc_cache:
        return _fc_cache[key]
    meta = _indicator_meta(indicator)
    hist = [r for r in _series(indicator, entity, None, None, None, source, "", "central", False, None) if r["freq"] == "A"]
    if not hist:
        raise HTTPException(404, f"no yearly figures of {meta['name']} for {entity}")
    bounds = (meta["bound_min"] if meta["bound_min"] is not None else -1e18,
              meta["bound_max"] if meta["bound_max"] is not None else 1e18)
    try:
        out = statforecast.forecast([r["period_start"].year for r in hist], [r["value"] for r in hist], horizon,
                                    meta["unit"], bounds, model)
    except ValueError as exc:
        raise HTTPException(422, f"{meta['name']} for {entity}: {exc}")
    out.update(indicator=indicator, entity=entity, unit=meta["unit"], decimals=meta["decimals"],
               source=hist[0]["source_id"])
    if len(_fc_cache) > 256:
        _fc_cache.clear()
    _fc_cache[key] = out
    return out


def _official(indicator: str, entity: str) -> list[dict]:
    """Each forecaster's latest projections for a country (status P), with its last
    estimate first so the line joins the history."""
    srcs = rows("""SELECT r.source_id, coalesce(s.short_name, r.source_id) AS name FROM indicator_sources r
        LEFT JOIN sources s USING (source_id) WHERE r.indicator_id = ? AND r.source_id NOT LIKE '%_history'
        ORDER BY r.rank""", [indicator])
    out = []
    for src in srcs:
        data = rows("""SELECT year(period_start) AS y, value, status, vintage FROM series
            WHERE indicator_id = ? AND entity_id = ? AND source_id = ? AND breakdown = '' AND variant = 'central'
                AND freq = 'A' ORDER BY 1""", [indicator, entity, src["source_id"]])
        proj = [r for r in data if r["status"] == "P"]
        if not proj:
            continue
        before = [r for r in data if r["status"] == "E" and r["y"] < proj[0]["y"]]
        pts = ([before[-1]] if before else []) + proj
        out.append({"source_id": src["source_id"], "name": src["name"], "release": proj[0]["vintage"],
                    "points": [[r["y"], r["value"]] for r in pts]})
    return out


@api.get("/forecast")
def forecast_view(indicator: str, entity: str, source: str | None = None,
                  horizon: int = Query(10, ge=1, le=50), model: str | None = None, official: bool = True):
    """A statistical forecast of one country's yearly series past its last estimate:
    several simple models scored by a rolling back-test, the best (or a simpler one
    within 5%) used, with 80% and 95% ranges from its back-test misses. With
    `official`, each forecaster's own latest projections too (IMF, OECD, World Bank,
    UN and any other source with projections)."""
    if model and model not in statforecast.MODELS:
        raise HTTPException(422, f"model must be one of {', '.join(statforecast.MODELS)}")
    out = dict(_stat_forecast(indicator, entity, source, horizon, model))
    out["official"] = _official(indicator, entity) if official else []
    return out


@api.post("/forecast/values")
def forecast_values(body: dict = Body(..., examples=[{"years": [2000, 2001], "values": [1.0, 2.0], "unit": "",
                                                       "horizon": 10}])):
    """The same statistical forecast for figures sent in the request (your own ratios,
    or anything worked out in the browser)."""
    try:
        return statforecast.forecast([int(y) for y in body.get("years", [])], [float(v) for v in body.get("values", [])],
                                     max(1, min(50, int(body.get("horizon", 10)))), body.get("unit"), None,
                                     body.get("model"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc))


# ----------------------------------------------------------------------------- forecast track record
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _errors(pairs: list[dict]) -> dict:
    d = [p["forecast"] - p["actual"] for p in pairs]
    n = len(d)
    return {"n": n, "bias": sum(d) / n, "mae": sum(abs(x) for x in d) / n, "rmse": (sum(x * x for x in d) / n) ** 0.5} \
        if n else {"n": 0, "bias": None, "mae": None, "rmse": None}


def _known_pairs(indicator: str, entity: str | None, source: str, since: int) -> tuple[list[dict], list[dict], str]:
    sql, params = forecast_pairs_sql(indicator, [entity] if entity else None, countries_only=entity is None,
                                     source_id=source)
    pairs = [p for p in rows(sql, params) if int(p["release"][:4]) >= since]
    # Outcomes come from the latest release, so that release's own figures say nothing.
    latest = (rows("SELECT max(left(vintage, 7)) AS r FROM vintages WHERE source_id = ? AND is_latest", [source])
              or [{"r": None}])[0]["r"] or "9999"
    known = [p for p in pairs if p["actual"] is not None and p["release"] < latest]
    return pairs, known, latest


@api.get("/track-record")
def track_record(indicator: str = "gdp_growth", entity: str | None = None, since: int = Query(1990, ge=1980),
                 source: str = "imf_weo"):
    """How a forecaster's past forecasts compared with what happened: errors (forecast
    minus outcome) by how far ahead the forecast was made, for each month it publishes
    in (April and October for the IMF, June and December for the OECD, January and
    June for the World Bank). With an entity: its own record plus every release's
    forecast path. Without: all countries pooled, and each country's record a year
    ahead. Any indicator a forecaster covers works; the record grows with each stored
    release."""
    if not rows("SELECT 1 FROM indicator_sources WHERE indicator_id = ? AND source_id = ?", [indicator, source]):
        raise HTTPException(422, f"{source} has no forecasts of {indicator}")
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
    if entity and entity not in names:
        raise HTTPException(404, f"no entity {entity}")
    pairs, known, latest = _known_pairs(indicator, entity, source, since)
    stats = []
    for month in sorted({p["release"][5:7] for p in pairs}):
        season = MONTHS[int(month) - 1] if month.isdigit() and 1 <= int(month) <= 12 else month
        for h in range(-1, 6):
            sel = [p for p in known if p["horizon"] == h and p["release"][5:7] == month]
            if sel:
                stats.append({"season": season, "horizon": h, **_errors(sel)})
    releases = sorted({p["release"] for p in pairs})
    out = {"indicator": indicator, "entity": entity, "name": names.get(entity) if entity else None, "source": source,
           "source_name": (rows("SELECT short_name FROM sources WHERE source_id = ?", [source]) or [{"short_name": source}])[0]["short_name"],
           "releases": releases, "outcomes_from": latest if latest != "9999" else None, "stats": stats,
           "seasons": [MONTHS[int(m) - 1] if m.isdigit() and 1 <= int(m) <= 12 else m
                       for m in sorted({p["release"][5:7] for p in pairs})],
           "sources": sorted({r["source_id"] for r in rows(
               "SELECT DISTINCT source_id FROM series WHERE indicator_id = ? AND source_id LIKE ?", [indicator, f"{source}%"])})}
    if entity:
        by: dict[str, list] = {}
        for p in pairs:
            by.setdefault(p["release"], []).append([p["year"], p["forecast"]])
        out["paths"] = [{"release": r, "points": by[r]} for r in releases]
        out["actual"] = [[r["y"], r["value"]] for r in rows("""SELECT year(period_start) AS y, value FROM series
            WHERE source_id = ? AND indicator_id = ? AND entity_id = ? AND breakdown = '' AND variant = 'central'
                AND status = 'E' ORDER BY 1""", [source, indicator, entity])]
        out["years"] = [{"year": y, **_errors([p for p in known if p["year"] == y and p["horizon"] == 1])}
                        for y in sorted({p["year"] for p in known})]
    else:
        per: dict[str, list] = {}
        for p in known:
            if p["horizon"] == 1:
                per.setdefault(p["entity_id"], []).append(p)
        out["countries"] = sorted(({"entity_id": e, "name": names.get(e, e), **_errors(v)} for e, v in per.items()),
                                  key=lambda r: r["mae"])
    return out


@api.get("/track-record/compare")
def track_record_compare(indicator: str = "gdp_growth", entity: str | None = None, since: int = Query(1990, ge=1980)):
    """Who forecasts best: each forecaster's typical miss for the current year and for
    the next year, over all its scored forecasts and over the years every forecaster
    scored (the fair comparison). With an entity, the statistical model's own
    back-test joins in: its forecast one and two years past the last known figure,
    which is what a forecaster knows when forecasting the current and next year."""
    out = []
    for src in FORECASTERS:
        if not rows("SELECT 1 FROM indicator_sources WHERE indicator_id = ? AND source_id = ?", [indicator, src]):
            continue
        _, known, _ = _known_pairs(indicator, entity, src, since)
        name = (rows("SELECT short_name FROM sources WHERE source_id = ?", [src]) or [{"short_name": src}])[0]["short_name"]
        out.append({"source_id": src, "name": name, "releases": len({p["release"] for p in known}),
                    "_pairs": {h: [p for p in known if p["horizon"] == h] for h in (0, 1)}})
    if entity:
        try:
            fc = _stat_forecast(indicator, entity, None, 2, None)
            pairs = {0: [], 1: []}
            for b in fc["backtest"]:
                for ahead, h in ((1, 0), (2, 1)):
                    if b.get(f"forecast_{ahead}") is not None:
                        pairs[h].append({"entity_id": entity, "year": b["origin"] + ahead,
                                         "forecast": b[f"forecast_{ahead}"], "actual": b[f"actual_{ahead}"]})
            out.append({"source_id": "worldmodel", "name": f"Worldmodel ({fc['model_name'].lower()})",
                        "releases": None, "_pairs": pairs})
        except HTTPException:
            pass
    for h in (0, 1):
        sets = [{(p["entity_id"], p["year"]) for p in f["_pairs"][h]} for f in out if f["_pairs"][h]]
        common = set.intersection(*sets) if sets else set()
        for f in out:
            ps = f["_pairs"][h]
            label = "this_year" if h == 0 else "next_year"
            f[label] = _errors(ps)
            f[f"{label}_common"] = _errors([p for p in ps if (p["entity_id"], p["year"]) in common])
            f[f"{label}_common_years"] = len(common)
    for f in out:
        del f["_pairs"]
    return {"indicator": indicator, "entity": entity, "forecasters": out}


# ----------------------------------------------------------------------------- source comparison
_cmp_cache: dict = {"key": None, "rows": []}


def _source_names() -> dict[str, str]:
    return {r["source_id"]: r["short_name"] for r in rows("SELECT source_id, short_name FROM sources")}


@api.get("/sources/indicators")
def compared_indicators():
    """Indicators with more than one source holding data, with how many countries can be
    compared and how many of them differ in their latest common year."""
    key = core.warehouse.current().meta.get("build_id")
    if _cmp_cache["key"] != key or key is None:
        sql, params = divergence_sql()
        found = rows(f"""SELECT indicator_id, count(DISTINCT entity_id) AS countries,
                count(DISTINCT entity_id) FILTER (WHERE flagged) AS differing, list(DISTINCT source_b) AS others
            FROM ({sql}) GROUP BY 1""", params)
        meta = {r["indicator_id"]: r for r in rows("SELECT indicator_id, name, unit, domain FROM indicators")}
        rank = {(r["indicator_id"], r["source_id"]): r["rank"] for r in rows(
            "SELECT indicator_id, source_id, rank FROM indicator_sources")}
        first = {i: s for (i, s), k in rank.items() if k == 1}
        names = _source_names()
        _cmp_cache.update(key=key, rows=sorted((
            {**{k: meta[f["indicator_id"]][k] for k in ("indicator_id", "name", "unit", "domain")},
             "countries": f["countries"], "differing": f["differing"],
             "sources": [{"source_id": x, "name": names.get(x, x)} for x in [
                 first[f["indicator_id"]], *sorted(f["others"], key=lambda o: rank.get((f["indicator_id"], o), 99))]]}
            for f in found), key=lambda r: (r["domain"], r["name"])))
    return _cmp_cache["rows"]


@api.get("/sources/compare")
def compare_sources(indicator: str, entity: str):
    """One country's values for an indicator from every source that has them, default source
    first, with the years the sources differ (as on the source comparison page)."""
    if not rows("SELECT 1 FROM indicators WHERE indicator_id = ?", [indicator]):
        raise HTTPException(404, f"no indicator {indicator}")
    found = rows("SELECT short_name FROM entities WHERE entity_id = ?", [entity])
    if not found:
        raise HTTPException(404, f"no entity {entity}")
    names = _source_names()
    data = rows("""SELECT s.source_id, r.rank, year(s.period_start) AS year, s.value, s.status
        FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        WHERE s.indicator_id = ? AND s.entity_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A'
        ORDER BY r.rank, year""", [indicator, entity])
    by: dict[str, dict] = {}
    for r in data:
        by.setdefault(r["source_id"], {"source_id": r["source_id"], "name": names.get(r["source_id"], r["source_id"]),
                                       "rank": r["rank"], "points": []})["points"].append([r["year"], r["value"], r["status"]])
    sql, params = divergence_sql(indicator, [entity], latest_only=False)
    years = rows(f"SELECT year, source_b, value_a, value_b, diff, rel, flagged FROM ({sql}) ORDER BY year", params)
    return {"indicator": indicator, "entity": entity, "name": found[0]["short_name"],
            "sources": sorted(by.values(), key=lambda x: x["rank"]), "differences": years}


@api.get("/sources/divergence")
def source_divergence(indicator: str | None = None, entity: str | None = None, flagged: bool = False,
                      limit: int = Query(500, ge=1, le=5000)):
    """Countries where an indicator's sources disagree, in each pair's latest common year,
    largest gap first. With an entity: every indicator compared for that country."""
    sql, params = divergence_sql(indicator, [entity] if entity else None, flagged_only=flagged)
    found = rows(f"SELECT * FROM ({sql}) LIMIT {limit}", params)
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
    inds = {r["indicator_id"]: r for r in rows("SELECT indicator_id, name, unit, decimals FROM indicators")}
    src = _source_names()
    for f in found:
        f.update(entity_name=names.get(f["entity_id"], f["entity_id"]), indicator_name=inds[f["indicator_id"]]["name"],
                 unit=inds[f["indicator_id"]]["unit"], decimals=inds[f["indicator_id"]]["decimals"],
                 source_a_name=src.get(f["source_a"], f["source_a"]), source_b_name=src.get(f["source_b"], f["source_b"]))
    return found
