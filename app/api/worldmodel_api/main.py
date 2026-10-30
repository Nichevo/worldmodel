"""Worldmodel API, on localhost. Serves the web app and any other local tool.

All endpoints are under /api/v1 and read the warehouse only. The only things
written are the user's own files (layouts, settings, indicator switches, history)
in a user folder beside the data (see layouts.py and userdata.py), and, when asked
on the Data status page, old raw downloads deleted to free space.
Interactive docs are at /docs when the server runs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from worldmodel_contract import SCHEMA_VERSION, catalogue
from worldmodel_contract.queries import SeriesQuery, forecast_pairs_sql, series_sql, stream_query
from worldmodel_contract import cohort, local
from worldmodel_api import __version__, layouts, userdata
from worldmodel_api.warehouse import Warehouse, WarehouseError

load_dotenv()
API_VERSION = "1"
HEADLINE = ["pop_total", "pop_growth_rate", "tfr", "median_age", "life_expectancy", "pop_share_65_plus",
            "net_migration", "gdp_growth", "gdp_usd", "gdp_per_capita_usd", "inflation"]

app = FastAPI(title="Worldmodel API", version=__version__,
              description="Local read-only API over the worldmodel warehouse.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3030", "http://127.0.0.1:3030"],
                   allow_methods=["GET", "PUT", "POST", "PATCH", "DELETE"], allow_headers=["*"])
api = APIRouter(prefix="/api/v1")
warehouse = Warehouse()


@app.exception_handler(WarehouseError)
def _warehouse_error(_, exc: WarehouseError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = warehouse.cursor()
    rel = cur.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def split(s: str | None) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


# ----------------------------------------------------------------------------- meta
@api.get("/meta")
def meta():
    o = warehouse.current()
    vintages = rows("SELECT source_id, vintage, release, retrieved_at, origin, is_latest FROM vintages "
                    "ORDER BY source_id, retrieved_at")
    return {"api_version": API_VERSION, "app_schema_version": SCHEMA_VERSION, "warehouse": o.path.name,
            "is_sample": warehouse.is_sample, **o.meta, "vintages": vintages}


@api.get("/sources")
def sources():
    return rows("SELECT * FROM sources ORDER BY default_rank, source_id")


@api.get("/build-checks")
def build_checks():
    return rows("SELECT * FROM build_checks ORDER BY kind, check_id")


@api.get("/datasets")
def datasets():
    """One row per source: its latest vintage and what it covers, indicator by indicator."""
    coverage = rows("""
        SELECT s.source_id, s.indicator_id, i.name, i.domain,
            min(year(s.period_start)) AS first_year, max(year(s.period_start)) AS last_year,
            max(year(s.period_start)) FILTER (WHERE s.status = 'E') AS last_estimate_year,
            count(DISTINCT s.entity_id) FILTER (WHERE e.type = 'country') AS countries,
            count(*) AS row_count
        FROM series s JOIN indicators i USING (indicator_id) JOIN entities e USING (entity_id)
        GROUP BY ALL ORDER BY s.source_id, i.domain, i.name""")
    latest = {v["source_id"]: v for v in rows(
        "SELECT source_id, vintage, release, retrieved_at, origin FROM vintages WHERE is_latest")}
    out = []
    for src in sources():
        inds = [c for c in coverage if c["source_id"] == src["source_id"]]
        out.append({**src, "latest_vintage": latest.get(src["source_id"]), "indicators": inds,
                    "row_count": sum(c["row_count"] for c in inds)})
    return out


# ----------------------------------------------------------------------------- entities
@api.get("/entities")
def entities(type: str | None = None, q: str | None = None):
    where, params = ["1 = 1"], []
    if type:
        where.append(f"type IN ({', '.join('?' * len(split(type)))})")
        params += split(type)
    if q:
        where.append("(name ILIKE ? OR short_name ILIKE ? OR synonyms ILIKE ? OR entity_id ILIKE ?)")
        params += [f"%{q}%"] * 3 + [q]
    return rows(f"SELECT entity_id, name, short_name, type, iso3, valid_from, valid_to FROM entities "
                f"WHERE {' AND '.join(where)} ORDER BY type <> 'country', short_name", params)


@api.get("/entities/{entity_id}")
def entity(entity_id: str, on: date | None = None):
    found = rows("SELECT * FROM entities WHERE entity_id = ?", [entity_id])
    if not found:
        raise HTTPException(404, f"no entity {entity_id}")
    on = on or date.today()
    active = "(m.valid_from IS NULL OR m.valid_from <= ?) AND (m.valid_to IS NULL OR m.valid_to >= ?)"
    groups = rows(f"SELECT e.entity_id, e.short_name, e.type, m.valid_from, m.valid_to FROM memberships m "
                  f"JOIN entities e ON e.entity_id = m.group_id WHERE m.member_id = ? AND {active} "
                  f"ORDER BY e.type, e.short_name", [entity_id, on, on])
    members = rows(f"SELECT e.entity_id, e.short_name, e.type, m.valid_from, m.valid_to FROM memberships m "
                   f"JOIN entities e ON e.entity_id = m.member_id WHERE m.group_id = ? AND {active} "
                   f"ORDER BY e.short_name", [entity_id, on, on])
    history = rows("SELECT m.member_id, e.short_name, m.valid_from, m.valid_to FROM memberships m "
                   "JOIN entities e ON e.entity_id = m.member_id WHERE m.group_id = ? AND "
                   "(m.valid_from IS NOT NULL OR m.valid_to IS NOT NULL) ORDER BY m.valid_from, e.short_name",
                   [entity_id])
    succession = rows("SELECT * FROM successions WHERE predecessor_id = ? OR successor_id = ? ORDER BY date",
                      [entity_id, entity_id])
    codes = rows("SELECT scheme, code, valid_from, valid_to FROM entity_codes WHERE entity_id = ? ORDER BY scheme",
                 [entity_id])
    return {**found[0], "groups": groups, "members": members, "membership_history": history,
            "successions": succession, "codes": codes, "as_of": on}


@api.get("/memberships")
def memberships(type: str | None = None, group: str | None = None, on: date | None = None):
    """Who belongs to which group today (or on `on`): every group of a type, or one group.
    Used to colour countries by continent, subregion or bloc."""
    if not type and not group:
        raise HTTPException(400, "give type or group")
    on = on or date.today()
    where, params = ["(m.valid_from IS NULL OR m.valid_from <= ?) AND (m.valid_to IS NULL OR m.valid_to >= ?)"], [on, on]
    if type:
        where.append(f"g.type IN ({', '.join('?' * len(split(type)))})")
        params += split(type)
    if group:
        where.append("g.entity_id = ?")
        params.append(group)
    return rows(f"SELECT g.entity_id AS group_id, g.short_name AS group_name, m.member_id FROM memberships m "
                f"JOIN entities g ON g.entity_id = m.group_id WHERE {' AND '.join(where)} "
                f"ORDER BY g.short_name, m.member_id", params)


@api.get("/entities/{entity_id}/profile")
def profile(entity_id: str):
    """Latest estimate (not projection) of the headline indicators, with the year and source."""
    if not rows("SELECT 1 FROM entities WHERE entity_id = ?", [entity_id]):
        raise HTTPException(404, f"no entity {entity_id}")
    found = rows(f"""
        SELECT s.indicator_id, i.name, i.unit, i.decimals, strftime(s.period_start, '%Y') AS period,
            s.value, s.source_id, s.vintage, s.is_aggregate, s.coverage
        FROM series s
        JOIN indicators i USING (indicator_id)
        JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id AND r.rank = 1
        WHERE s.entity_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E'
            AND s.indicator_id IN ({', '.join('?' * len(HEADLINE))})
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id ORDER BY s.period_start DESC) = 1""",
                 [entity_id, *HEADLINE])
    order = {k: i for i, k in enumerate(HEADLINE)}
    return sorted(found, key=lambda r: order[r["indicator_id"]])


# ----------------------------------------------------------------------------- indicators
_ind_cache: dict = {"key": None, "rows": []}


def _indicator_rows() -> list[dict]:
    """Every indicator with its years, country count and sources; cached per build."""
    key = warehouse.current().meta.get("build_id")
    if _ind_cache["key"] != key or key is None:
        found = rows("""
            SELECT i.*, min(year(s.period_start)) AS first_year, max(year(s.period_start)) AS last_year,
                max(year(s.period_start)) FILTER (WHERE s.status = 'E') AS last_estimate_year,
                count(DISTINCT s.entity_id) FILTER (WHERE e.type = 'country') AS countries
            FROM indicators i LEFT JOIN series s USING (indicator_id) LEFT JOIN entities e USING (entity_id)
            GROUP BY ALL ORDER BY i.domain, i.name""")
        srcs = rows("SELECT r.*, s.short_name AS source_name, s.licence FROM indicator_sources r "
                    "LEFT JOIN sources s USING (source_id) ORDER BY r.indicator_id, r.rank")
        for f in found:
            f["synonyms"] = split((f["synonyms"] or "").replace("|", ","))
            f["sources"] = [s for s in srcs if s["indicator_id"] == f["indicator_id"]]
            f["available"] = f["first_year"] is not None
            f["default_on"] = bool(f.get("default_on", True))
        _ind_cache.update(key=key, rows=found)
    return _ind_cache["rows"]


@api.get("/indicators")
def indicators(domain: str | None = None):
    """Every indicator, with `enabled`: whether it is switched on (Indicators page)
    for the panel menus. Switched-off indicators still serve data."""
    over = userdata.indicator_overrides()
    return [{**f, "enabled": over.get(f["indicator_id"], f["default_on"])}
            for f in _indicator_rows() if domain is None or f["domain"] == domain]


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


# ----------------------------------------------------------------------------- search
@api.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 20):
    """Entities and indicators whose names or synonyms match. Used by the search box and,
    later, by the assistant to turn words into ids."""
    like = f"%{q}%"
    ents = rows("""
        SELECT 'entity' AS kind, entity_id AS id, short_name AS name, type AS detail,
            CASE WHEN lower(short_name) = lower(?) OR lower(entity_id) = lower(?)
                      OR '|' || lower(synonyms) || '|' LIKE '%|' || lower(?) || '|%' THEN 0
                 WHEN short_name ILIKE ? THEN 1 ELSE 2 END AS score
        FROM entities WHERE short_name ILIKE ? OR name ILIKE ? OR synonyms ILIKE ? OR lower(entity_id) = lower(?)""",
                [q, q, q, f"{q}%", like, like, like, q])
    inds = rows("""
        SELECT 'indicator' AS kind, indicator_id AS id, name, domain AS detail,
            CASE WHEN lower(name) = lower(?) THEN 0 WHEN name ILIKE ? THEN 1 ELSE 2 END AS score
        FROM indicators WHERE name ILIKE ? OR synonyms ILIKE ? OR description ILIKE ?""",
                [q, f"{q}%", like, like, like])
    return sorted(ents + inds, key=lambda r: (r["score"], r["kind"], r["name"]))[:limit]


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


@api.get("/map")
def map_values(indicator: str, year: int, source: str | None = None):
    """One value per country for a year, to colour the map."""
    data = _series(indicator, None, None, year, year, source, "", "central", True, None)
    countries = {r["entity_id"] for r in rows("SELECT entity_id FROM entities WHERE type = 'country'")}
    return {"indicator": indicator, "year": year,
            "rows": [{"entity_id": r["entity_id"], "value": r["value"], "status": r["status"]}
                     for r in data if r["entity_id"] in countries]}


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


# ----------------------------------------------------------------------------- population what-if
_whatif_inputs: dict[tuple, cohort.Inputs | None] = {}
SUMMARY_YEARS = (2030, 2050, 2075, 2100)


def _inputs(entity: str) -> cohort.Inputs | None:
    key = (warehouse.current().meta.get("build_id"), entity)
    if key not in _whatif_inputs:
        if len(_whatif_inputs) > 64:
            _whatif_inputs.clear()
        _whatif_inputs[key] = cohort.prepare(warehouse.cursor().execute(cohort.inputs_sql(), [entity]).fetchall())
    return _whatif_inputs[key]


@api.get("/whatif")
def whatif(entity: str,
           tfr: float = Query(0, ge=-3, le=3, description="change in children per woman, in full after `phase` years"),
           e0: float = Query(0, ge=-20, le=20, description="change in life expectancy at birth, years"),
           mig: float = Query(1, ge=0, le=3, description="multiplier on net migration"),
           extra: float = Query(0, ge=-5_000_000, le=5_000_000, description="extra net migrants a year"),
           phase: int = Query(10, ge=0, le=50, description="years until the changes are in full"),
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
    levers = cohort.Levers(tfr=tfr, e0=e0, migration=mig, extra_migrants=extra, phase=phase)
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
        WHERE entity_id = ? AND indicator_id = 'pop_total' AND variant <> 'central' AND freq = 'A'""", [entity])
    by: dict[str, dict[int, float]] = {}
    for r in ranges:
        by.setdefault(r["variant"], {})[r["y"]] = r["value"]
    out["ranges"] = {k: [v.get(y) for y in years] for k, v in by.items()}
    out.update(entity=entity, name=found[0]["short_name"], type=found[0]["type"],
               levers={"tfr": tfr, "e0": e0, "mig": mig, "extra": extra, "phase": phase})
    return out


# ----------------------------------------------------------------------------- forecast track record
def _errors(pairs: list[dict]) -> dict:
    d = [p["forecast"] - p["actual"] for p in pairs]
    n = len(d)
    return {"n": n, "bias": sum(d) / n, "mae": sum(abs(x) for x in d) / n, "rmse": (sum(x * x for x in d) / n) ** 0.5} \
        if n else {"n": 0, "bias": None, "mae": None, "rmse": None}


@api.get("/track-record")
def track_record(indicator: str = "gdp_growth", entity: str | None = None, since: int = Query(1990, ge=1980)):
    """How past IMF WEO forecasts compared with what happened: errors (forecast minus
    outcome) by how far ahead the forecast was made, for the April and October
    releases. With an entity: its own record plus every release's forecast path.
    Without: all countries pooled, and each country's record a year ahead."""
    if indicator not in ("gdp_growth", "inflation"):
        raise HTTPException(422, "track records exist for gdp_growth and inflation")
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
    if entity and entity not in names:
        raise HTTPException(404, f"no entity {entity}")
    sql, params = forecast_pairs_sql(indicator, [entity] if entity else None, countries_only=entity is None)
    pairs = [p for p in rows(sql, params) if int(p["release"][:4]) >= since]
    # Outcomes come from the latest release, so that release's own figures say nothing.
    latest = (rows("SELECT max(left(vintage, 7)) AS r FROM vintages WHERE source_id = 'imf_weo' AND is_latest")
              or [{"r": None}])[0]["r"] or "9999"
    known = [p for p in pairs if p["actual"] is not None and p["release"] < latest]
    stats = []
    for month, season in (("04", "April"), ("10", "October")):
        for h in range(-1, 6):
            sel = [p for p in known if p["horizon"] == h and p["release"].endswith(month)]
            if sel:
                stats.append({"season": season, "horizon": h, **_errors(sel)})
    releases = sorted({p["release"] for p in pairs})
    out = {"indicator": indicator, "entity": entity, "name": names.get(entity) if entity else None,
           "releases": releases, "outcomes_from": latest if latest != "9999" else None, "stats": stats,
           "sources": sorted({r["source_id"] for r in rows(
               "SELECT DISTINCT source_id FROM series WHERE indicator_id = ? AND source_id LIKE 'imf_weo%'", [indicator])})}
    if entity:
        by: dict[str, list] = {}
        for p in pairs:
            by.setdefault(p["release"], []).append([p["year"], p["forecast"]])
        out["paths"] = [{"release": r, "points": by[r]} for r in releases]
        out["actual"] = [[r["y"], r["value"]] for r in rows("""SELECT year(period_start) AS y, value FROM series
            WHERE source_id = 'imf_weo' AND indicator_id = ? AND entity_id = ? AND breakdown = '' AND variant = 'central'
                AND status = 'E' ORDER BY 1""", [indicator, entity])]
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


# ----------------------------------------------------------------------------- saved layouts
def _layout_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 60 or any(c in name for c in "\r\n\t"):
        raise HTTPException(422, "a layout name is 1 to 60 characters on one line")
    return name


@api.get("/layouts")
def list_layouts():
    return layouts.all_layouts()


@api.put("/layouts/{name}")
def save_layout(name: str, query: str = Body(..., embed=True, max_length=4000)):
    """Save (or overwrite) a named layout: the map page's URL query."""
    try:
        return layouts.save(_layout_name(name), query.lstrip("?"))
    except ValueError as e:
        raise HTTPException(409, str(e))


@api.delete("/layouts/{name}")
def delete_layout(name: str):
    if not layouts.delete(_layout_name(name)):
        raise HTTPException(404, f"no layout {name}")
    return {"deleted": name}


# ----------------------------------------------------------------------------- settings, history
@api.get("/settings")
def get_settings():
    return {"settings": userdata.settings(), "defaults": local.SETTINGS}


@api.put("/settings")
def put_settings(patch: dict = Body(...)):
    """Change some settings; unknown keys are ignored and numbers held to their ranges."""
    return {"settings": userdata.save_settings(patch), "defaults": local.SETTINGS}


@api.get("/history")
def get_history(q: str | None = None, kind: str | None = None, starred: bool = False,
                since: str | None = Query(None, description="YYYY-MM-DD"), until: str | None = None,
                limit: int = Query(500, le=5000)):
    """What was opened and looked at, newest first."""
    return userdata.history(q, kind, starred, since, until, limit)


@api.post("/history")
def post_history(entry: dict = Body(...)):
    """Log one thing opened: {kind, title, url?, entity?, indicator?, detail?}. Ignored while paused."""
    try:
        return {"entry": userdata.add_history(entry)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.patch("/history/{entry_id}")
def patch_history(entry_id: str, star: bool | None = Body(None), note: str | None = Body(None, max_length=2000)):
    """Star an entry (a bookmark) or write a note on it."""
    try:
        return userdata.mark(entry_id, star, note)
    except KeyError:
        raise HTTPException(404, f"no history entry {entry_id}")


@api.delete("/history")
def delete_history(keep_starred: bool = True, before: str | None = Query(None, description="YYYY-MM-DD")):
    """Clear the history (or the part before a date), keeping starred entries unless told not to."""
    return {"deleted": userdata.clear_history(keep_starred, before)}


@api.get("/history/interest")
def history_interest(limit: int = 50):
    """Countries by how often and how recently they were opened; on-demand fetches go in this order."""
    return userdata.entity_interest(limit)


# ----------------------------------------------------------------------------- storage, refresh log
@api.get("/storage")
def storage():
    """Disk use of the data folder by category against the limits in Settings, with warning levels."""
    return local.storage()


@api.post("/storage/free-up")
def free_up(keep: int = Query(2, ge=1, le=10)):
    """Delete old raw downloads, keeping the newest `keep` per source. Never vintages or builds."""
    return local.free_raw(keep=keep)


@api.get("/refresh-log")
def refresh_log():
    """One record per refresh or build, oldest first (see worldmodel_data.monitor)."""
    return local.read_refresh_log()


# ----------------------------------------------------------------------------- streams
@api.get("/streams")
def streams():
    return catalogue.streams()


@api.get("/streams/{name}")
def stream(name: str, format: Literal["json", "csv", "parquet"] = "json", as_of: date | None = None):
    """A named stream from contract streams.yaml, for external tools such as a forecasting bot."""
    st = next((s for s in catalogue.streams() if s["name"] == name), None)
    if st is None:
        raise HTTPException(404, f"no stream {name}")
    q = stream_query(st)
    q.as_of = as_of
    sql, params = series_sql(q)
    meta_ = warehouse.current().meta
    return _respond(rows(sql, params), format, name,
                    {"stream": st, "as_of": as_of, "build_id": meta_.get("build_id")})


@app.get("/health")
def health():
    try:
        o = warehouse.current()
        return {"ok": True, "warehouse": o.path.name, "build_id": o.meta.get("build_id")}
    except WarehouseError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})


app.include_router(api)


def run() -> None:
    import uvicorn
    uvicorn.run("worldmodel_api.main:app", host=os.environ.get("WORLDMODEL_API_HOST", "127.0.0.1"),
                port=int(os.environ.get("WORLDMODEL_API_PORT", "8000")))
