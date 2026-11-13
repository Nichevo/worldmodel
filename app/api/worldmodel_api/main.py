"""Worldmodel API, on localhost. Serves the web app and any other local tool.

All endpoints are under /api/v1 and read the warehouse only. The only things
written are the user's own files (layouts, settings, indicator switches, history)
in a user folder beside the data (see layouts.py and userdata.py), Wikipedia pages
fetched on demand within the daily limits in Settings (media/wikipedia, see
wiki.py), and, when asked on the Data status page, old raw downloads deleted to
free space.
Interactive docs are at /api/docs when the server runs (also through the web app, port 3030).
The public API for scripts, the Python client and MCP is in public.py, under /api/public/v1.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from worldmodel_contract import SCHEMA_VERSION, catalogue
from worldmodel_contract.schema import EVENT_KINDS
from worldmodel_contract.queries import SeriesQuery, divergence_sql, forecast_pairs_sql, series_sql, stream_query
from worldmodel_contract import cohort, local
from worldmodel_contract import crowd as crowd_terms
from worldmodel_contract import energy_flow
from worldmodel_contract import discover
from worldmodel_contract import quality as qual
from worldmodel_contract import relations as relterms
from worldmodel_contract import forecast as statforecast
from worldmodel_contract.cities import CITY_INDICATORS
from worldmodel_api import __version__, ai, basemap, briefing, climate, crises, hazards, crowd, predictions, highlights, land, layouts, longhistory, look, markets, nature, news, numbeo, people, relationships, sectors, space, tiles, transport, userdata, wiki
from worldmodel_api import upkeep as upkeep_jobs
from worldmodel_api import public as public_api
from worldmodel_api.warehouse import Warehouse, WarehouseError

load_dotenv()
API_VERSION = "1"
HEADLINE = ["pop_total", "pop_growth_rate", "tfr", "median_age", "life_expectancy", "pop_share_65_plus",
            "net_migration", "gdp_growth", "gdp_usd", "gdp_per_capita_usd", "inflation"]



def _tiles_starter() -> None:
    try:
        s = local.load_settings()
        if s["map_tiles_starter"] and not tiles.status()["starter_done"]:
            tiles.start_starter()
    except Exception:  # noqa: BLE001 - shown on Settings > Maps when it runs
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    background = wiki.Background(wiki_targets)
    background.start()
    starter = threading.Timer(30, _tiles_starter)  # the starter map copies, once, after the app is up
    starter.daemon = True
    starter.start()
    yield
    background.close()


app = FastAPI(title="Worldmodel API", version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json",
              description="The worldmodel app's API. **Public API** (/api/public/v1) is the stable part for scripts, "
                          "the Python client and AI assistants: switch it on in Settings > API access. The rest (/api/v1) "
                          "serves the app's own pages and may change.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3030", "http://127.0.0.1:3030"],
                   allow_methods=["GET", "PUT", "POST", "PATCH", "DELETE"], allow_headers=["*"])
api = APIRouter(prefix="/api/v1")
warehouse = Warehouse()


@app.exception_handler(WarehouseError)
def _warehouse_error(_, exc: WarehouseError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def cursor():
    """A cursor on the warehouse that also sees your ratios as indicators (see _ratio_views)."""
    cur = warehouse.cursor()
    found = userdata.ratios()
    if found:
        _ratio_views(cur, found)
    return cur


def _ratio_views(cur, found: list[dict]) -> None:
    """Your ratios as indicators: temporary views, for this cursor only, that put each
    ratio beside the warehouse's own rows in series, indicators and indicator_sources
    (the warehouse itself is never written). A ratio's value is numerator / denominator
    x multiplier for each country, year and variant where both have a value from their
    first-ranked source; a projection on either side makes it a projection."""
    db = cur.execute("SELECT current_database()").fetchone()[0].replace('"', '""')
    main = lambda t: f'"{db}".main.{t}'  # noqa: E731
    known = {r[0] for r in cur.execute(f"SELECT indicator_id FROM {main('indicators')}").fetchall()}
    found = [r for r in found if r["numerator"] in known and r["denominator"] in known
             and re.fullmatch(r"my_[a-z0-9_]{1,60}", str(r.get("id", "")))]
    if not found:
        return
    best = lambda i: (f"(SELECT * FROM {main('series')} WHERE indicator_id = '{i}' AND breakdown = '' AND source_id = "  # noqa: E731
                      f"(SELECT source_id FROM {main('indicator_sources')} WHERE indicator_id = '{i}' ORDER BY rank LIMIT 1))")
    parts = [f"""
        SELECT a.entity_id, '{r["id"]}' AS indicator_id, a.period_start, a.freq, '' AS breakdown, a.variant,
            'user' AS source_id, 'ratio' AS vintage, a.value / b.value * {float(r["multiplier"])!r} AS value,
            CASE WHEN a.status = 'P' OR b.status = 'P' THEN 'P' ELSE 'E' END AS status,
            a.is_aggregate OR b.is_aggregate AS is_aggregate, least(a.coverage, b.coverage) AS coverage
        FROM {best(r["numerator"])} a
        JOIN {best(r["denominator"])} b
            ON b.entity_id = a.entity_id AND b.period_start = a.period_start AND b.freq = a.freq AND b.variant = a.variant
        WHERE b.value <> 0""" for r in found]
    cur.execute(f"CREATE OR REPLACE TEMP VIEW series AS SELECT * FROM {main('series')} UNION ALL BY NAME "
                + " UNION ALL ".join(parts))
    cur.execute(f"CREATE OR REPLACE TEMP TABLE ratio_indicators AS SELECT * FROM {main('indicators')} LIMIT 0")
    names = dict(cur.execute(f"SELECT indicator_id, name FROM {main('indicators')}").fetchall())
    for r in found:
        mult = r["multiplier"]
        times = "" if mult == 1 else f" × {mult:g}"
        cur.execute("INSERT INTO ratio_indicators BY NAME SELECT ? AS indicator_id, ? AS name, ? AS description, '' AS synonyms, "
                    "'Your ratios' AS domain, ? AS unit, ? AS decimals, 'A' AS frequency, '' AS breakdowns, 'none' AS agg_method, "
                    "-1e300 AS bound_min, 1e300 AS bound_max, true AS default_on",
                    [r["id"], r["name"], r.get("description") or f"Your ratio: {names[r['numerator']]} ÷ {names[r['denominator']]}{times}.",
                     r.get("unit") or "", int(r.get("decimals", 2))])
    cur.execute(f"CREATE OR REPLACE TEMP VIEW indicators AS SELECT * FROM {main('indicators')} UNION ALL BY NAME "
                "SELECT * FROM ratio_indicators")
    values = ", ".join(f"('{r['id']}', 'user', '{r['id']}', 1.0, 1, 'Worked out from your ratio')" for r in found)
    cur.execute(f"CREATE OR REPLACE TEMP VIEW indicator_sources AS SELECT * FROM {main('indicator_sources')} UNION ALL BY NAME "
                f"SELECT * FROM (VALUES {values}) v(indicator_id, source_id, series, scale, rank, notes)")


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = cursor()
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
                    "row_count": sum(c["row_count"] for c in inds),
                    "on_demand": wiki.status() if src["source_id"] == "wikipedia" else None})
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
    return rows(f"SELECT entity_id, name, short_name, type, iso3, iso2, valid_from, valid_to FROM entities "
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


# ----------------------------------------------------------------------------- texts: Factbook, Wikidata
@api.get("/entities/{entity_id}/texts")
def texts(entity_id: str, source: str = "cia_factbook", edition: int | None = None):
    """One edition of a text source for an entity (the latest unless `edition` is given),
    as sections of fields in the source's order, with the editions there are."""
    editions = [r["edition"] for r in rows("SELECT DISTINCT edition FROM texts WHERE entity_id = ? AND source_id = ? "
                                            "ORDER BY edition DESC NULLS LAST", [entity_id, source])]
    out = {"entity_id": entity_id, "source_id": source, "editions": editions, "edition": None, "vintage": None,
           "sections": []}
    if not editions:
        return out
    ed = edition if edition in editions else editions[0]
    fields = rows("SELECT section, field, field_key, content, vintage FROM texts WHERE entity_id = ? AND source_id = ? "
                  "AND edition IS NOT DISTINCT FROM ? ORDER BY position", [entity_id, source, ed])
    sections: dict[str, list] = {}
    for f in fields:
        sections.setdefault(f["section"], []).append({k: f[k] for k in ("field", "field_key", "content")})
    return {**out, "edition": ed, "vintage": fields[0]["vintage"] if fields else None,
            "sections": [{"section": k, "fields": v} for k, v in sections.items()]}


@api.get("/entities/{entity_id}/texts/history")
def text_history(entity_id: str, key: str, source: str = "cia_factbook"):
    """One field across every edition, oldest first: how the Factbook's text changed."""
    return rows("SELECT edition, field, content FROM texts WHERE entity_id = ? AND source_id = ? AND field_key = ? "
                "ORDER BY edition, position", [entity_id, source, key])


# ----------------------------------------------------------------------------- Wikipedia
WIKI_FACTS = {"article": "article", "item": "item", "P18": "photo", "P41": "flag", "P242": "map"}


def _wiki_facts(entity_ids: list[str] | None = None) -> dict[str, dict]:
    """Article title, Wikidata item and picture file names per entity, from the Wikidata facts."""
    where, params = "", list(WIKI_FACTS)
    if entity_ids is not None:
        where = f" AND entity_id IN ({', '.join('?' * len(entity_ids))})"
        params += entity_ids
    out: dict[str, dict] = {}
    for r in rows(f"SELECT entity_id, field_key, content FROM texts WHERE source_id = 'wikidata' "
                  f"AND field_key IN ({', '.join('?' * len(WIKI_FACTS))}){where}", params):
        out.setdefault(r["entity_id"], {})[WIKI_FACTS[r["field_key"]]] = r["content"].split("; ")[0]
    return out


def wiki_target(entity_id: str) -> dict | None:
    found = rows("SELECT entity_id, name, type FROM entities WHERE entity_id = ?", [entity_id])
    if not found:
        return None
    return {**found[0], **_wiki_facts([entity_id]).get(entity_id, {})}


def wiki_targets() -> list[tuple[str, dict]]:
    """Countries in the order the background fetches them: most opened first, then by population."""
    countries = rows("""
        SELECT e.entity_id, e.name, e.type FROM entities e
        LEFT JOIN (SELECT entity_id, max_by(value, period_start) AS pop FROM series
                   WHERE indicator_id = 'pop_total' AND breakdown = '' AND variant = 'central' AND status = 'E'
                   GROUP BY entity_id) p USING (entity_id)
        WHERE e.type = 'country' AND e.valid_to IS NULL
        ORDER BY p.pop DESC NULLS LAST, e.entity_id""")
    by_id = {c["entity_id"]: c for c in countries}
    opened = [i["entity_id"] for i in userdata.entity_interest(500) if i["entity_id"] in by_id]
    facts = _wiki_facts()
    order = list(dict.fromkeys([*opened, *by_id]))
    return [(e, {**by_id[e], **facts.get(e, {})}) for e in order]


def _with_image_urls(page: dict | None) -> dict | None:
    if not page:
        return page
    images = [{**i, "src": f"/api/v1/media/wikipedia/{i['local']}" if i.get("local") else None}
              for i in page.get("images", [])]
    return {**page, "images": images}


@api.get("/entities/{entity_id}/wikipedia")
def wikipedia(entity_id: str, fetch: bool = True):
    """The Wikipedia introduction and pictures for an entity, from the local copy. With
    fetch (the default), a missing or month-old copy is fetched first if today's limit allows."""
    target = wiki_target(entity_id)
    if target is None:
        raise HTTPException(404, f"no entity {entity_id}")
    if target["type"] not in wiki.TYPES and "article" not in target:
        return {"status": "none", "page": None, "budget": wiki.budget(), "message": None}  # no article for this kind of group
    res = wiki.page(entity_id, target, fetch)
    return {**res, "page": _with_image_urls(res["page"])}


@api.get("/wikipedia/status")
def wikipedia_status():
    """Pages stored, pages due for a refresh, and today's fetches against the limit."""
    return wiki.status()


@api.get("/media/wikipedia/{name}")
def wikipedia_image(name: str):
    path = wiki.image_path(name)
    if path is None:
        raise HTTPException(404, f"no picture {name}")
    return FileResponse(path, headers={"Cache-Control": "max-age=604800"})


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
    found = sorted(found, key=lambda r: order[r["indicator_id"]])
    if not found:
        return found
    # For headline tiles: the last ten years (a sparkline and the change since the year before),
    # the rank among countries in the same year and source, and which way is better.
    from worldmodel_contract.discover import better_when
    marks = ", ".join("(?, ?, ?)" for _ in found)
    args = [x for r in found for x in (r["indicator_id"], r["source_id"], int(r["period"]))]
    trend = rows(f"""
        WITH want(indicator_id, source_id, y) AS (VALUES {marks})
        SELECT s.indicator_id, year(s.period_start) AS y, s.value FROM series s JOIN want w
            ON w.indicator_id = s.indicator_id AND w.source_id = s.source_id
        WHERE s.entity_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E'
            AND year(s.period_start) BETWEEN w.y - 10 AND w.y ORDER BY 1, 2""", [*args, entity_id])
    ranks = rows(f"""
        WITH want(indicator_id, source_id, y) AS (VALUES {marks}),
        r AS (SELECT s.indicator_id, s.entity_id, rank() OVER (PARTITION BY s.indicator_id ORDER BY s.value DESC) AS rank,
                count(*) OVER (PARTITION BY s.indicator_id) AS n
            FROM series s JOIN want w ON w.indicator_id = s.indicator_id AND w.source_id = s.source_id AND year(s.period_start) = w.y
            JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
            WHERE s.breakdown = '' AND s.variant = 'central' AND s.status = 'E')
        SELECT indicator_id, rank, n FROM r WHERE entity_id = ?""", [*args, entity_id])
    by_rank = {r["indicator_id"]: r for r in ranks}
    for r in found:
        r["trend"] = [[t["y"], t["value"]] for t in trend if t["indicator_id"] == r["indicator_id"]]
        k = by_rank.get(r["indicator_id"])
        r["rank"], r["of"] = (k["rank"], k["n"]) if k else (None, None)
        r["better"] = better_when(r["indicator_id"], r["name"])
    return found


# ----------------------------------------------------------------------------- indicators
_ind_cache: dict = {"key": None, "rows": []}


def _indicator_rows() -> list[dict]:
    """Every indicator with its years, country count and sources; cached per build."""
    build = warehouse.current().meta.get("build_id")
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
def energy_flow_chart(entity: str, year: int | None = None):
    """Where a country's energy comes from and goes (a Sankey chart), from its energy
    balance (energy_balance_pj, breakdown flow=<row>|fuel=<fuel>). Without a year, or for
    a year without a balance, the latest year before it; `years` lists them all."""
    base = ("FROM series WHERE indicator_id = 'energy_balance_pj' AND entity_id = ? AND variant = 'central' "
            "AND breakdown LIKE 'flow=%'")
    years = [r["y"] for r in rows(f"SELECT DISTINCT year(period_start) AS y {base} ORDER BY 1", [entity])]
    if not years:
        return {"entity": entity, "year": None, "years": [], "nodes": [], "links": [], "totals": None}
    if year not in years:
        year = max((y for y in years if y <= (year or years[-1])), default=years[-1])
    data = rows(f"""SELECT split_part(split_part(breakdown, '|', 1), '=', 2) AS flow,
            split_part(split_part(breakdown, '|', 2), '=', 2) AS fuel, value, source_id, vintage
        {base} AND year(period_start) = ?""", [entity, year])
    out = energy_flow.flow([(r["flow"], r["fuel"], r["value"]) for r in data])
    return {"entity": entity, "year": year, "years": years, "unit": "PJ",
            "source_id": data[0]["source_id"] if data else None, "vintage": data[0]["vintage"] if data else None, **out}


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
    key = (warehouse.current().meta.get("build_id"), entity)
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
    key = (warehouse.current().meta.get("build_id"), indicator, entity, source, horizon, model,
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
    key = warehouse.current().meta.get("build_id")
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


# ----------------------------------------------------------------------------- local AI
@api.get("/ai/status")
def ai_status():
    """Is Ollama reachable, which models it has, the default model, and the web search engine with its usage."""
    return ai.status()


@api.post("/ai/search")
def ai_search(question: str = Body(..., max_length=20_000), model: str | None = Body(None),
              query: str | None = Body(None, max_length=300)):
    """One web search for a question: the model writes the query (unless one is given), the engine in
    Settings answers. Brave searches count against the limits in Settings."""
    s = userdata.settings()
    ready, why = ai.search_ready(s)
    if not ready:
        raise HTTPException(409, why)
    q = query
    if not q:
        try:
            q = ai.write_query(question, model or ai.default_model(s, ai.models(s)) or "", s)
        except (httpx.HTTPError, ValueError):  # the model could not write a query: search the question itself
            q = question[:200]
    try:
        results = ai.web_search(q, s)
    except ai.SearchLimit as e:
        raise HTTPException(409, str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{s['ai_search_engine']} search failed: HTTP {e.response.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{s['ai_search_engine']} search failed: {e}")
    return {"query": q, "results": results, "engine": s["ai_search_engine"], "usage": ai.search_usage(s)}


@api.post("/ai/ask")
def ai_ask(req: dict = Body(...)):
    """Ask a model in Ollama; streams one JSON object a line: start, token {text}, done {answer} or error {message}.
    Body: question, context [{label, text}], model?, web? {query, results}, title?, page?, entity?, indicator?, group?"""
    if not userdata.settings()["ai_enabled"]:
        raise HTTPException(409, "Local AI is switched off (Settings: Local AI).")

    def lines():
        for event in ai.ask(req):
            yield json.dumps(event, ensure_ascii=False) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@api.get("/ai/answers")
def ai_answers(q: str | None = None, entity: str | None = None, indicator: str | None = None, model: str | None = None,
               limit: int = Query(200, le=5000)):
    """Saved answers, newest first."""
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for a in reversed(ai.answers()):
        if entity and a.get("entity") != entity or indicator and a.get("indicator") != indicator or model and a["model"] != model:
            continue
        hay = f"{a['question']} {a['answer']} {a.get('title', '')} {a.get('note', '')} {' '.join(a.get('tags', []))}".lower()
        if all(w in hay for w in words):
            out.append(a)
        if len(out) >= limit:
            break
    return out


@api.patch("/ai/answers/{answer_id}")
def ai_patch_answer(answer_id: str, patch: dict = Body(...)):
    """Rate an answer (rating 1, -1 or 0), or set its tags or note."""
    try:
        return ai.update_answer(answer_id, patch)
    except KeyError:
        raise HTTPException(404, f"no answer {answer_id}")


@api.delete("/ai/answers/{answer_id}")
def ai_delete_answer(answer_id: str):
    if not ai.delete_answer(answer_id):
        raise HTTPException(404, f"no answer {answer_id}")
    return {"deleted": answer_id}


@api.get("/ai/stats")
def ai_stats():
    """Your own AI use: per model questions, tokens, speed, time to first word and ratings; web searches."""
    return ai.stats()


# ----------------------------------------------------------------------------- highlights
@api.get("/highlights")
def get_highlights(q: str | None = None, kind: str | None = None, tag: str | None = None, entity: str | None = None):
    """Everything kept, newest first, with the tags in use."""
    return {"items": highlights.search(q, kind, tag, entity), "tags": highlights.tags()}


@api.post("/highlights")
def post_highlight(item: dict = Body(...)):
    """Keep something: {kind: text|chart|table|answer, title?, text?, page_url?, page_title?, entities?, indicator?,
    query? (chart settings), table? {columns, rows, unit?}, picture? (PNG data URL), answer_id?, question?, model?,
    sources?, tags?, note?}."""
    try:
        return highlights.add(item)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.patch("/highlights/{item_id}")
def patch_highlight(item_id: str, patch: dict = Body(...)):
    try:
        return highlights.update(item_id, patch)
    except KeyError:
        raise HTTPException(404, f"no highlight {item_id}")


@api.delete("/highlights/{item_id}")
def delete_highlight(item_id: str):
    if not highlights.delete(item_id):
        raise HTTPException(404, f"no highlight {item_id}")
    return {"deleted": item_id}


@api.get("/highlights/{item_id}/picture")
def highlight_picture(item_id: str):
    p = highlights.picture_path(item_id)
    if not p:
        raise HTTPException(404, "no picture")
    return FileResponse(p, media_type="image/png")


@api.get("/highlights-export.md")
def export_highlights(q: str | None = None, kind: str | None = None, tag: str | None = None, entity: str | None = None,
                      base: str = Query("", max_length=200)):
    """The highlights shown (same filters) as one Markdown file."""
    text = highlights.markdown(highlights.search(q, kind, tag, entity), base.rstrip("/"))
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="highlights.md"'})


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


@api.get("/manual-files")
def manual_files():
    """Files you save by hand: each source that needs one always (by_hand) or when its site
    refuses a refresh, with where to get it, what is in its var/manual folder, when it was
    last loaded, and whether anything needs doing now."""
    from datetime import datetime, timezone
    folder_root = local.home() / "manual"
    loaded = {r["source_id"]: r["retrieved_at"] for r in rows(
        "SELECT source_id, max(retrieved_at) AS retrieved_at FROM vintages GROUP BY source_id")}
    failing = {p["source_id"]: p for p in local.problems() if p.get("kind") == "fetch" and p.get("open")}
    out = []
    for s in catalogue.sources().values():
        if not s.manual:
            continue
        folder = folder_root / s.id
        files = sorted((f for f in folder.iterdir() if f.is_file() and not f.name.startswith(("_", ".", "~$"))),
                       key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
        last = loaded.get(s.id)
        last_dt = datetime.fromisoformat(str(last)) if last else None
        if last_dt and last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        newest = datetime.fromtimestamp(files[0].stat().st_mtime, timezone.utc) if files else None
        if newest and (last_dt is None or newest > last_dt):
            todo, why = "load", f"{files[0].name} is in the folder but not loaded yet"
        elif s.manual.by_hand and last is None and not s.manual.optional:
            todo, why = "download", "Not loaded yet"
        elif s.id in failing:
            todo, why = "download", f"The last refresh could not download it ({failing[s.id].get('summary') or 'refused'})"
        else:
            todo, why = None, ""
        out.append({"source_id": s.id, "name": s.name, "by_hand": s.manual.by_hand, "optional": s.manual.optional, "get": s.manual.get,
                    "what": s.manual.what, "cadence": s.cadence, "folder": f"var\\manual\\{s.id}",
                    "files": [f.name for f in files[:5]], "last_loaded": str(last) if last else None,
                    "todo": todo, "why": why, "command": f".\\load.bat {s.id}"})
    out.sort(key=lambda r: (r["todo"] is None, not r["by_hand"], r["name"]))
    return out


@api.get("/scrapers")
def scrapers():
    """Sources read from web pages (the scraping tools): how each runs, what it reads, the
    setting that governs it, when it last ran, how far it got and why it stopped, if it did."""
    settings = local.load_settings()
    runs = local.read_scrape_log()
    loaded = {r["source_id"]: r["retrieved_at"] for r in rows(
        "SELECT source_id, max(retrieved_at) AS retrieved_at FROM vintages GROUP BY source_id")}
    failing = {p["source_id"]: p for p in local.problems() if p.get("kind") == "fetch" and p.get("open")}
    out = []
    for s in catalogue.sources().values():
        if not s.scraper:
            continue
        today = None
        if s.id == "numbeo":
            b = numbeo.budget()
            today = f"{b['used']} of {b['limit']} pages today"
        elif s.id == "wikipedia":
            c, t, e = wiki.budget("countries"), wiki.budget("cities"), wiki.budget("empires")
            today = (f"{c['used']} of {c['limit']} countries, {t['used']} of {t['limit']} cities and "
                     f"{e['used']} of {e['limit']} empires today")
        last = loaded.get(s.id)
        prob = failing.get(s.id)
        out.append({"source_id": s.id, "name": s.name, "run": s.scraper.run, "reads": s.scraper.reads,
                    "setting": s.scraper.setting or None,
                    "setting_value": settings.get(s.scraper.setting) if s.scraper.setting else None,
                    "last_run": runs.get(s.id), "last_loaded": str(last) if last else None, "today": today,
                    "problem": (prob.get("summary") or "the last refresh failed") if prob else None})
    out.sort(key=lambda r: (r["problem"] is None and not (r["last_run"] or {}).get("stopped"), r["name"]))
    return {"gap_seconds": settings.get("scrape_gap_seconds"), "sources": out}


@api.get("/fetch-methods")
def fetch_methods_list():
    """How each source is fetched: what it can do (refresh from the site, verify.bat in your
    browser, your own file), what you chose, what Automatic chose and why, and how its last
    refresh went. Written by the data side on every refresh and update.bat."""
    from worldmodel_contract import fetch_methods as fm
    state = fm.read_state()
    choices = fm.read_choices()
    meta = catalogue.sources()
    last: dict[str, dict] = {}
    for run in local.read_refresh_log():
        for s in run.get("sources") or []:
            if s.get("source_id"):
                last[s["source_id"]] = {"at": run.get("started_at"), "status": s.get("status"),
                                        "note": s.get("error") or s.get("note") or ""}
    out = []
    for sid, e in sorted((state.get("sources") or {}).items()):
        can = [m for m in e.get("can") or [] if m in fm.METHODS]
        choice = choices.get(sid) if choices.get(sid) in can else None
        auto = e.get("auto") if e.get("auto") in can else None
        m = meta.get(sid)
        out.append({"source_id": sid, "name": m.name if m else sid, "can": can, "kind": e.get("kind"),
                    "kind_label": fm.SITE_KINDS.get(e.get("kind") or "", ""), "choice": choice or "auto",
                    "auto": auto or fm.effective(None, None, can), "method": fm.effective(choice, auto, can),
                    "since": e.get("since"), "why": e.get("why") if auto and auto != "site" else None,
                    "retry_from": e.get("retry_from") if not choice else None,
                    "last_kind": e.get("last_kind"), "last_error": e.get("last_error"), "last": last.get(sid)})
    return {"written_at": state.get("written_at"), "labels": fm.LABELS, "kinds": fm.SITE_KINDS,
            "blocked_in_a_row": fm.BLOCKED_IN_A_ROW, "sources": out}


@api.put("/fetch-methods/{source_id}")
def fetch_methods_set(source_id: str, change: dict = Body(...)):
    """Choose how one source is fetched: {"method": "auto" | "site" | "verify" | "file"}."""
    from worldmodel_contract import fetch_methods as fm
    e = (fm.read_state().get("sources") or {}).get(source_id)
    if e is None:
        raise HTTPException(404, f"no source {source_id} (run update.bat if it is new)")
    method = change.get("method")
    if method != "auto" and method not in (e.get("can") or []):
        raise HTTPException(422, f"{source_id} can be fetched by: auto, {', '.join(e.get('can') or [])}")
    fm.set_choice(source_id, method)
    return next(r for r in fetch_methods_list()["sources"] if r["source_id"] == source_id)


@api.get("/problems")
def problems():
    """Each distinct failure in the refresh log, with how often it happened and whether it is still open."""
    return local.problems()


# ----------------------------------------------------------------------------- looking after the sources
def _todo_state() -> dict:
    try:
        data = json.loads((local.user_dir() / "todo.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _source_uses() -> dict[str, list[str]]:
    """source -> names of the indicators that read it."""
    out: dict[str, list[str]] = {}
    for i in catalogue.indicators().values():
        for s in i.sources:
            out.setdefault(s.source_id, []).append(i.name)
    return out


def _todo_items() -> list[dict]:
    """Everything that needs you, each once: files waiting for a source, files to save or
    load, sources failing, keys missing and forms to fill in. Things being handled by
    themselves (retrying, not due yet) stay out."""
    from worldmodel_contract import inbox as inbox_mod

    s = userdata.settings()
    off = set(filter(None, (s.get("sources_off") or "").split(",")))
    uses = _source_uses()
    names = {x.id: x.name for x in catalogue.sources().values()}
    items: list[dict] = []

    def add(key: str, kind: str, title: str, why: str, *, source_id: str | None = None, link: str | None = None,
            command: str | None = None, button: str | None = None, what: str | None = None, folder: str | None = None,
            order: int = 5, **extra) -> None:
        n = len(uses.get(source_id or "", []))
        items.append({"key": key, "kind": kind, "title": title, "why": why, "source_id": source_id, "link": link,
                      "command": command, "button": button, "what": what, "folder": folder, "uses": n,
                      "uses_names": uses.get(source_id or "", [])[:6], "order": order, **extra})

    box = inbox_mod.state(local.home(), s)
    for w in box["waiting"]:
        add(f"inbox:{w['name']}", "inbox", f"Which source is {w['name']}?",
            "It is in the inbox, but the app could not tell which source it belongs to." if not w["candidates"]
            else f"It could be {', '.join(w['candidate_names'].values())}.", button="assign", order=0,
            name=w["name"], candidates=w["candidates"])
    handled = set()
    for m in manual_files():
        if not m["todo"] or m["source_id"] in off:
            continue
        handled.add(m["source_id"])
        if m["todo"] == "load":
            add(f"load:{m['source_id']}", "load", f"Load {m['name']}", m["why"], source_id=m["source_id"],
                command=m["command"], button="load", folder=m["folder"], order=1)
        else:
            add(f"file:{m['source_id']}", "download", f"Save the file for {m['name']}", m["why"], source_id=m["source_id"],
                link=m["get"], what=m["what"], folder=m["folder"], button="get", order=3)
    try:
        ways = {r["source_id"]: r["method"] for r in fetch_methods_list()["sources"]}
    except Exception:  # noqa: BLE001 - written by the data side; may be missing
        ways = {}
    for p in local.problems():
        if not p.get("open"):
            continue
        sid = p.get("source_id")
        if sid in handled or sid in off:
            continue
        if p.get("kind") == "fetch" and sid:
            verify = ways.get(sid) == "verify"
            add(f"problem:{p['key']}", "failing", f"{names.get(sid, sid)} did not download",
                (p.get("summary") or "The last refresh could not fetch it.")[:400], source_id=sid,
                command=f".\\verify.bat {sid}" if verify else None, button="refresh", order=2, times=p.get("times"))
        else:
            add(f"problem:{p['key']}", "check", p.get("title") or "A check failed",
                (p.get("summary") or p.get("explain") or "")[:400], source_id=sid, order=2, times=p.get("times"),
                todo_text=p.get("todo"))
    for k in relationships.keys():
        if not k["active"] or k["source"] in off:
            continue
        missing = [e["name"] for e in k["env"] if not e["set"]]
        if missing:
            add(f"key:{k['source']}", "key", f"Add the key for {k['name']}", k.get("unlocks") or "", source_id=k["source"],
                link=k.get("signup"), button="key", order=4, env=missing)
    for sid, info in inbox_mod.source_info(local.home()).items():
        if sid in off:
            continue
        blank = [v for v in info.get("needs_settings") or [] if not s.get(v)]
        if blank:
            add(f"form:{sid}", "form", f"Fill in the form for {names.get(sid, sid)}",
                "Its site asks who is downloading; the refresh fetches it once the form in Settings is filled in.",
                source_id=sid, link="/settings", order=4)
    items.sort(key=lambda r: (r["order"], -r["uses"], r["title"]))
    return items


def _sig(item: dict) -> str:
    return f"{item['kind']}|{item['why'][:200]}"


@api.get("/todo")
def todo():
    """The To do list: items that need you, without those you marked done (until they change)
    or snoozed (until the date passes)."""
    st = _todo_state()
    today = date.today().isoformat()
    shown, hidden = [], []
    for it in _todo_items():
        mark = st.get(it["key"]) or {}
        if mark.get("done") == _sig(it) or (mark.get("snooze_until") or "") > today:
            hidden.append({**it, "mark": mark})
        else:
            shown.append(it)
    return {"items": shown, "count": len(shown), "hidden": hidden}


@api.put("/todo/{key:path}")
def todo_mark(key: str, change: dict = Body(...)):
    """Mark an item: {"action": "done"} (hidden until it changes), {"action": "snooze", "days": 7},
    or {"action": "clear"} (shown again)."""
    st = _todo_state()
    item = next((i for i in _todo_items() if i["key"] == key), None)
    action = change.get("action")
    if action == "clear":
        st.pop(key, None)
    elif item is None:
        raise HTTPException(404, "no such item (it may have been dealt with already)")
    elif action == "done":
        st[key] = {"done": _sig(item), "at": date.today().isoformat()}
    elif action == "snooze":
        days = max(1, min(365, int(change.get("days") or 7)))
        st[key] = {"snooze_until": (date.today() + timedelta(days=days)).isoformat()}
    else:
        raise HTTPException(422, "action is done, snooze or clear")
    path = local.user_dir() / "todo.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return todo()


@api.get("/inbox")
def inbox_state():
    """Files waiting in the inbox (with the app's guess), files filed lately, and the folders the app looks in."""
    from worldmodel_contract import inbox as inbox_mod
    return inbox_mod.state(local.home(), userdata.settings())


@api.post("/inbox/assign")
def inbox_assign(change: dict = Body(...)):
    """File one waiting file into the source you chose ({"name", "source_id"}) and load it; the
    app remembers files named like it."""
    from worldmodel_contract import inbox as inbox_mod
    sid = str(change.get("source_id") or "")
    if sid not in catalogue.sources():
        raise HTTPException(422, f"unknown source {sid}")
    try:
        e = inbox_mod.assign(str(change.get("name") or ""), sid, local.home())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except OSError as exc:
        raise HTTPException(409, f"could not move it: {exc}")
    try:
        job = upkeep_jobs.start("load", [sid])
    except RuntimeError as exc:
        job = {"note": f"{exc} It loads at the next refresh."}
    return {"filed": e, "job": job}


@api.get("/jobs")
def jobs_status():
    """The refresh, inbox, download or backup job running now (or the last one), with its console lines and progress."""
    return upkeep_jobs.status()


@api.post("/jobs")
def jobs_start(change: dict = Body(...)):
    """Start a job: {"kind": "refresh" | "inbox" | "get" | "backup" | "load", "sources": [...] (optional)}."""
    kind = str(change.get("kind") or "")
    known = set(catalogue.sources())
    sources = [x for x in (change.get("sources") or []) if x in known]
    try:
        return upkeep_jobs.start(kind, sources)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except OSError as exc:
        raise HTTPException(500, f"could not start it: {exc}")


_HEALTH_SIZES: dict = {"at": 0.0, "sizes": {}}


def _source_sizes() -> dict[str, int]:
    """Bytes on disk per source (downloads and stored vintages), worked out at most every 10 minutes."""
    import time as _t
    if _t.monotonic() - _HEALTH_SIZES["at"] < 600 and _HEALTH_SIZES["sizes"]:
        return _HEALTH_SIZES["sizes"]
    out: dict[str, int] = {}
    for part in ("raw", "vintages", "manual"):
        base = local.home() / part
        if not base.is_dir():
            continue
        for d in base.iterdir():
            if d.is_dir():
                total = 0
                for dirpath, _, files in os.walk(d):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, f))
                        except OSError:
                            pass
                out[d.name] = out.get(d.name, 0) + total
    _HEALTH_SIZES.update(at=_t.monotonic(), sizes=out)
    return out


@api.get("/source-health")
def source_health():
    """Every source in one table: how it is doing, when it last worked, when it is next due,
    how it is fetched, its size on disk, rows loaded, what reads it, and whether it is switched off."""
    from datetime import datetime as _dt
    from worldmodel_contract import inbox as inbox_mod
    s = userdata.settings()
    off = set(filter(None, (s.get("sources_off") or "").split(",")))
    info = inbox_mod.source_info(local.home())
    vint = {r["source_id"]: r for r in rows(
        "SELECT source_id, max(retrieved_at) AS loaded, arg_max(row_count, retrieved_at) AS rows_n, "
        "arg_max(release, retrieved_at) AS release FROM vintages GROUP BY source_id")}
    last_ok: dict[str, str] = {}
    last_note: dict[str, str] = {}
    for run in local.read_refresh_log():
        for e in run.get("sources") or []:
            sid = e.get("source_id")
            if e.get("status") in ("new", "unchanged"):
                last_ok[sid] = run.get("started_at") or ""
            if sid:
                last_note[sid] = e.get("error") or e.get("note") or ""
    failing = {p["source_id"]: p for p in local.problems() if p.get("kind") == "fetch" and p.get("open")}
    try:
        ways = {r["source_id"]: r for r in fetch_methods_list()["sources"]}
    except Exception:  # noqa: BLE001
        ways = {}
    sizes = _source_sizes()
    uses = _source_uses()
    domains: dict[str, dict[str, int]] = {}
    for i in catalogue.indicators().values():
        for src in i.sources:
            domains.setdefault(src.source_id, {}).setdefault(i.domain, 0)
            domains[src.source_id][i.domain] += 1
    now = _dt.now()
    out = []
    for m in catalogue.sources().values():
        if m.status != "active":
            continue
        sid = m.id
        inf = info.get(sid) or {}
        v = vint.get(sid) or {}
        loaded = str(v["loaded"]) if v.get("loaded") else None
        every = inf.get("every_days")
        due = None
        if inf.get("manual"):
            due = "when you save a newer file"
        elif inf.get("frozen"):
            due = "never (an archive)"
        elif loaded and every:
            d = _dt.fromisoformat(loaded[:19]) + timedelta(days=every)
            due = "next refresh" if d <= now else d.date().isoformat()
        elif loaded or sid in info:
            due = "every refresh"
        if sid in off:
            state = "off"
        elif sid in failing:
            state = "failing"
        elif not loaded:
            state = "never"
        elif due == "next refresh":
            state = "due"
        else:
            state = "ok"
        dom = domains.get(sid) or {}
        out.append({"source_id": sid, "name": m.name, "publisher": m.publisher, "cadence": m.cadence, "url": m.url,
                    "state": state, "off": sid in off, "by_hand": bool(m.manual and m.manual.by_hand),
                    "method": (ways.get(sid) or {}).get("method"), "last_ok": last_ok.get(sid), "loaded": loaded,
                    "release": v.get("release"), "rows": v.get("rows_n"), "due": due, "bytes": sizes.get(sid, 0),
                    "failing": (failing[sid].get("summary") or "")[:300] if sid in failing else None,
                    "note": last_note.get(sid, "")[:300], "uses": len(uses.get(sid, [])), "uses_names": uses.get(sid, [])[:8],
                    "group": max(dom, key=dom.get) if dom else "other", "fetched": sid in info,
                    "scraper": bool(m.scraper), "on_demand": sid in ("wikipedia", "numbeo")})
    order = {"failing": 0, "never": 1, "due": 2, "ok": 3, "off": 4}
    out.sort(key=lambda r: (order[r["state"]], r["name"]))
    return {"sources": out, "off": sorted(off)}


@api.put("/keys/{env}")
def keys_set(env: str, change: dict = Body(...)):
    """Save one key into the .env file on this computer ({"value": "..."}; empty removes it).
    Only names the app knows are accepted; the key is never sent back."""
    from worldmodel_contract import upkeep as upkeep_mod
    known = {v for e in catalogue.api_keys() for v in (e.get("env") or [])}
    if env not in known:
        raise HTTPException(404, f"unknown key {env}")
    value = str(change.get("value") or "").strip()
    if any(c in value for c in "\r\n\"'") or len(value) > 500:
        raise HTTPException(422, "a key is one line, without quotes")
    path = upkeep_mod.env_file()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if not re.match(rf"\s*{re.escape(env)}\s*=", ln)]
    if value:
        lines.append(f"{env}={value}")
        os.environ[env] = value
    else:
        os.environ.pop(env, None)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"env": env, "set": bool(value), "file": str(path)}


@api.get("/upkeep")
def upkeep_state():
    """The scheduled refresh (as Windows has it) and the backups made so far."""
    from worldmodel_contract import upkeep as upkeep_mod
    s = userdata.settings()
    return {"schedule": upkeep_mod.schedule_state(), "backup_folder": str(upkeep_mod.backup_dir(s)),
            "backups": upkeep_mod.backups(s)[:20], "env_file": str(upkeep_mod.env_file())}


@api.put("/upkeep/schedule")
def upkeep_schedule(change: dict = Body(...)):
    """Turn the scheduled refresh on or off ({"on", "often", "day", "time"}); saves the settings and tells Windows."""
    from worldmodel_contract import upkeep as upkeep_mod
    s = userdata.settings()
    new = local.clean_settings({"schedule_on": bool(change.get("on")), "schedule_often": change.get("often", s["schedule_often"]),
                                "schedule_day": change.get("day", s["schedule_day"]), "schedule_time": change.get("time", s["schedule_time"])}, s)
    res = upkeep_mod.schedule(new["schedule_on"], new["schedule_often"], new["schedule_day"], new["schedule_time"])
    if res["ok"]:
        userdata.save_settings(new)
    return {**res, "schedule": upkeep_mod.schedule_state()}


# ----------------------------------------------------------------------------- events and milestones
EVENT_COLUMNS = ("event_id", "entity_id", "source_id", "kind", "subkind", "title", "start_date", "end_date",
                 "precision", "size", "size_unit", "deaths", "affected", "damage_usd", "place", "url", "detail", "color")


def _year_or_date(v: str | None, end: bool = False) -> str | None:
    """'1990' -> 1990-01-01 (or 1990-12-31 for an end), a full date as it is."""
    if not v:
        return None
    v = v.strip()
    if len(v) == 4 and v.isdigit():
        return f"{v}-12-31" if end else f"{v}-01-01"
    try:
        return date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        raise HTTPException(422, f"not a year or date: {v}")


def _milestone_rows() -> list[dict]:
    return [{"event_id": f"user:{m['id']}", "entity_id": m["entity_id"], "source_id": "user", "kind": "user",
             "subkind": m.get("subkind"), "title": m["title"], "start_date": m["start_date"], "end_date": m.get("end_date"),
             "precision": "day", "size": None, "size_unit": None, "deaths": None, "affected": None, "damage_usd": None,
             "place": None, "url": m.get("url"), "detail": m.get("note") or None, "color": None, "milestone_id": m["id"]}
            for m in userdata.milestones()]


@api.get("/basemap")
def basemap_status():
    """The local map files, whether the tool and fonts are in, and what a refresh is doing."""
    return basemap.status()


@api.post("/basemap/estimate")
def basemap_estimate():
    """How big the map files for the current Settings would be (nothing is downloaded but the tool)."""
    try:
        return basemap.estimate()
    except Exception as exc:  # the site, the tool or the network: say which
        raise HTTPException(502, basemap._explain(exc))


@api.post("/basemap/make")
def basemap_make():
    """Make (or remake) the map files in the background; GET /basemap shows how it is going."""
    return basemap.start()


@api.delete("/basemap/files/{name}")
def basemap_delete(name: str):
    if not basemap.remove(name):
        raise HTTPException(404, f"no map file {name}")
    return {"ok": True}


@api.get("/basemap/files/{name}")
def basemap_file(name: str):
    """One map file, read by the map in pieces (HTTP range requests)."""
    p = basemap.root() / name
    if not name.endswith(".pmtiles") or p.parent != basemap.root() or not p.is_file():
        raise HTTPException(404, f"no map file {name}: make the map files in Settings > Map")
    return FileResponse(p, media_type="application/vnd.pmtiles")


@api.get("/basemap/fonts/{stack}/{part}")
def basemap_font(stack: str, part: str):
    p = basemap.root() / "fonts" / stack / part
    if not re.fullmatch(r"\d+-\d+\.pbf", part) or p.parent.parent != basemap.root() / "fonts" or not p.is_file():
        raise HTTPException(404, "no such font range")
    return FileResponse(p, media_type="application/x-protobuf", headers={"Cache-Control": "max-age=604800"})


@api.get("/space")
def space_status():
    """The Solar system page's downloads: what is kept, how old, and what a fetch is doing."""
    st = space.status()
    if st["due"] and st["job"].get("state") != "running":
        st["job"] = space.start()  # first visit, or older than 90 days: fetch in the background
    return st


@api.post("/space/fetch")
def space_fetch():
    return space.start(force=True)


@api.get("/space/{name}")
def space_data(name: Literal["asteroids", "missions", "values"]):
    d = space.data(name)
    if d is None:
        raise HTTPException(404, f"no {name} yet: they download when the Solar system page first opens")
    return JSONResponse(d, headers={"Cache-Control": "max-age=3600"})


@api.get("/tiles")
def tiles_status():
    """Relief, satellite and night light pictures: the saved areas, their size, and what a save is doing."""
    return tiles.status()


def _area(body: dict) -> dict:
    area = dict(body)
    if area.get("country"):
        box = tiles.country_box(str(area["country"]))
        if not box:
            raise HTTPException(404, f"no shape for {area['country']}")
        area["bbox"] = box
        area.setdefault("name", str(area["country"]).upper())
    if not area.get("bbox") or len(area["bbox"]) != 4:
        raise HTTPException(422, "give a country or a box (west, south, east, north)")
    area.setdefault("t", "-")
    return area


@api.post("/tiles/check")
def tiles_check(body: dict = Body(...)):
    """How many tiles an area holds and roughly how big it would be, before saving."""
    try:
        return tiles.check(_area(body))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc))


@api.post("/tiles/save")
def tiles_save(body: dict = Body(...)):
    """Save an area's pictures on this PC (in the background; GET /tiles shows how it is going)."""
    try:
        return tiles.save(_area(body))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc))


@api.post("/tiles/starter")
def tiles_starter():
    """Download the starter copies now (world relief, New Zealand relief and satellite, night lights)."""
    return tiles.start_starter()


@api.delete("/tiles/areas/{area_id}")
def tiles_delete(area_id: str):
    if not tiles.remove(area_id):
        raise HTTPException(404, f"no saved area {area_id}")
    return {"ok": True}


@api.get("/tiles/{set_id}/{z}/{x}/{y}")
def tile(set_id: str, z: int, x: int, y: int, t: str | None = None):
    """One picture tile: the saved copy, or fetched online for this view (not saved)."""
    got = tiles.tile(set_id, z, x, y, t)
    if not got:
        return Response(status_code=204)
    data, media = got
    return Response(data, media_type=media, headers={"Cache-Control": "max-age=86400"})


# ----------------------------------------------------------------------------- land, cities and trees
@api.get("/land")
def land_overview(entity: str = "world"):
    """Land use for the world or a country: FAOSTAT since 1961, HYDE back to 1700 (modelled
    before 1961), tree cover and loss, and people."""
    return land.overview(rows, entity)


@api.get("/land/ranking")
def land_ranking(indicator: str = "land_forest_ha", start: int = 1990, end: int | None = None, per: str = "change"):
    """Countries by change in a land figure between two years."""
    try:
        return land.ranking(rows, indicator, start, end, per)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/land/where")
def land_where(year: int | None = None):
    """Where the land goes: Earth's surface down to farmland for crops and for grazing."""
    return land.where(rows, year)


@api.get("/land/climate/{entity}")
def land_climate(entity: str):
    """Land beside temperature, fires and emissions for one country."""
    return land.against_climate(rows, entity)


@api.get("/land/card/{sector}")
def land_card(sector: str, entities: str | None = None):
    """A land-based sector's Land card: land against output, intensity, comparisons, NZ regions."""
    got = land.card(rows, sector, entities.split(",") if entities else None)
    if got is None:
        raise HTTPException(404, f"no Land card for {sector}")
    return got


@api.get("/land/cities")
def land_cities(sort: str = "people", country: str | None = None, limit: int = 100, search: str | None = None):
    """GHSL urban centres ranked by people, built-up area, growth or density."""
    return land.cities(rows, sort, country, min(limit, 2000), search)


@api.get("/land/outlines")
def land_outlines(ids: str):
    """Outlines of urban centres with their figures (Compare cities)."""
    return land.outlines(rows, [i for i in ids.split(",") if i][:12])


@api.get("/land/city/{city_id}")
def land_city(city_id: str):
    """The GHSL urban centre a city sits in, with its figures, outline and land cover if worked out."""
    if not _has_cities():
        raise HTTPException(404, "no city list loaded yet")
    got = land.centre_for_city(rows, city_id)
    if got is None:
        raise HTTPException(404, "no urban centre for this city")
    return got


@api.get("/land/cover")
def land_cover():
    """Cities whose land cover (trees, crops, built-up) has been worked out from the WorldCover pictures."""
    return land.city_cover(rows)


@api.post("/land/cover")
def land_cover_start(body: dict = Body(...)):
    """Work out land cover for urban centres (ids), in the background; or the biggest `top` not done yet."""
    ids = [str(i) for i in body.get("ids") or []]
    if body.get("top"):
        ids += [r["id"] for r in land.cities(rows, "people", body.get("country"), int(body["top"]))["rows"]]
    try:
        return land.city_cover_start(rows, ids[:500])
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/land/nz")
def land_nz(level: int = 2, region: str = "NZL", y0: int | None = None, y1: int | None = None):
    """New Zealand's land cover (LCDB) by class and survey year, the changes between two surveys, and regions."""
    return land.nz(rows, level, region, y0, y1)


@api.get("/land/trees")
def land_trees(council: str | None = None):
    """A council's street tree list: how many, the commonest species, planting by year."""
    return land.street_trees(rows, council)


# ----------------------------------------------------------------------------- Predictions (your log, scorecard, base rates, watchlist)
def _pred_check() -> None:
    """Settle what the app can see, at most once per build (cheap, but every page asks)."""
    b = _build_id()
    if _pred_state.get("build") != b:
        _pred_state["build"] = b
        try:
            predictions.check(rows)
        except Exception:  # noqa: BLE001 - a bad entry never breaks the page
            pass


_pred_state: dict = {}


@api.get("/predictions")
def predictions_list(who: str | None = None, category: str | None = None, entity: str | None = None,
                     indicator: str | None = None, state: str | None = None):
    """Your log: every prediction with its state (open, due, settled) and score. Outcomes the app can
    see (an indicator's figure for the year, a crowd question's resolution) are filled in first."""
    _pred_check()
    items = predictions.listing({"who": who, "category": category, "entity": entity, "indicator": indicator, "state": state})
    everyone = predictions.items()
    return {"items": items, "who": sorted({p["who"] for p in everyone}), "categories": sorted({p["category"] for p in everyone if p.get("category")})}


@api.post("/predictions")
def predictions_add(p: dict = Body(..., examples=[{"question": "NZ inflation in 2026", "kind": "number", "value": 2.4, "low": 2,
                                                   "high": 3, "due": "2027-04-30", "indicator": "inflation", "entity": "NZL", "year": 2026}])):
    """Add a prediction: {question, kind (binary, number or date), who_kind (you, expert, app, crowd), who, link, made, due,
    chance | value, low, high, unit | date_call, window_days, category, tags, why, indicator, entity, year, crowd_key}."""
    try:
        return predictions.save(p)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.put("/predictions/{pred_id}")
def predictions_edit(pred_id: str, p: dict = Body(...)):
    try:
        return predictions.save(p, pred_id)
    except KeyError:
        raise HTTPException(404, f"no prediction {pred_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.delete("/predictions/{pred_id}")
def predictions_delete(pred_id: str):
    if not predictions.delete(pred_id):
        raise HTTPException(404, f"no prediction {pred_id}")
    return {"deleted": pred_id}


@api.post("/predictions/{pred_id}/outcome")
def predictions_outcome(pred_id: str, body: dict = Body(..., examples=[{"actual": True}])):
    """How it turned out: {actual: true/false, a number or a date; null clears it}."""
    try:
        p = predictions.set_outcome(pred_id, body.get("actual"))
        return {**p, "score": predictions.score(p)}
    except KeyError:
        raise HTTPException(404, f"no prediction {pred_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.get("/predictions/export.csv")
def predictions_csv():
    buf = io.StringIO()
    cols = ["id", "question", "kind", "who_kind", "who", "made", "due", "chance", "value", "low", "high", "unit", "date_call",
            "category", "indicator", "entity", "year", "crowd_key", "link", "why", "state", "outcome", "hit", "brier", "miss"]
    w = csv.writer(buf)
    w.writerow(cols)
    for p in predictions.listing():
        sc = p.get("score") or {}
        w.writerow([p.get(c) if c not in ("outcome", "hit", "brier", "miss") else
                    ((p.get("outcome") or {}).get("actual") if c == "outcome" else sc.get(c)) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=predictions.csv"})


@api.get("/predictions/scorecard")
def predictions_scorecard(category: str | None = None, entity: str | None = None, since: str | None = None):
    """One row per forecaster (you, experts, the app, each crowd site, your Metaculus accounts): hit rate,
    Brier score, typical miss, and calibration in tenths."""
    _pred_check()
    days = int(userdata.settings().get("crowd_score_days", 7))
    return {"score_days": days, "rows": predictions.scorecard(rows, category=category, entity=entity, since=since, score_days=days)}


@api.get("/predictions/due")
def predictions_due(days: int = Query(30, ge=1, le=365)):
    _pred_check()
    return predictions.due_soon(days)


@api.post("/predictions/draft")
def predictions_draft(body: dict = Body(..., examples=[{"url": "https://example.org/article"}])):
    """Draft an expert's prediction from a web page (or pasted text) with your local AI, for you to check."""
    s = userdata.settings()
    if not s.get("ai_enabled", True):
        raise HTTPException(422, "Local AI is off (Settings: Local AI)")
    text, url = (body.get("text") or "").strip(), (body.get("url") or "").strip()
    if url and not text:
        if not re.match(r"https?://", url):
            raise HTTPException(422, "Paste a link starting with http:// or https://")
        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "worldmodel (personal research)"}) as c:
                r = c.get(url)
                r.raise_for_status()
                text = predictions.page_text(r.text)
        except httpx.HTTPError as e:
            raise HTTPException(422, f"Could not read that page ({e.__class__.__name__}); paste its text instead")
    if len(text) < 80:
        raise HTTPException(422, "Not enough text to find a prediction in")
    model = ai.default_model(s, ai.models(s))
    if not model:
        raise HTTPException(422, "No local AI model is installed (Settings: Local AI)")
    try:
        with httpx.Client(timeout=300) as c:
            r = c.post(f"{ai.ollama_url(s)}/api/chat", json={"model": model, "stream": False, "format": "json",
                       "messages": [{"role": "user", "content": predictions.DRAFT_PROMPT.format(url=url or "pasted text", text=text[:12000])}],
                       "options": {"temperature": 0, "num_ctx": s["ai_context_tokens"]}})
            r.raise_for_status()
            answer = (r.json().get("message") or {}).get("content") or ""
    except httpx.HTTPError as e:
        raise HTTPException(502, f"The local AI did not answer ({e.__class__.__name__})")
    try:
        d = predictions.parse_draft(answer)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if url:
        d["link"] = url
    d["model"] = model
    return d


@api.get("/predictions/base-rates")
def base_rates_presets():
    return {"presets": predictions.PRESETS,
            "event_kinds": [{"kind": k, "label": v} for k, v in EVENT_KINDS.items() if k not in ("holiday", "user", "crisiswatch")]}


@api.get("/predictions/base-rate")
def base_rate(preset: str | None = None, event: str | None = None, indicator: str | None = None, if_op: str | None = None,
              if_value: float | None = None, then_op: str | None = None, then_value: float | None = None,
              within: int | None = Query(None, ge=1, le=50), entity: str | None = None, group: str | None = None,
              start: int = Query(1960, ge=1800, le=2030)):
    """How often something has happened before: a preset, or your own: an event kind per country-year
    (event=coup), or an indicator rule (indicator, if_op/if_value, then_op/then_value, within years)."""
    kind = "event" if event else "rule" if indicator else None
    try:
        return predictions.base_rate(rows, preset, kind=kind, event=event, indicator=indicator, if_op=if_op, if_value=if_value,
                                     then_op=then_op, then_value=then_value, within=within, entity=entity, group=group, start=start)
    except KeyError:
        raise HTTPException(404, f"no preset {preset}")
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"Not enough to work out a base rate: {e}")


@api.get("/watchlist")
def watchlist_get():
    s = userdata.settings()
    return {"on": bool(s.get("watchlist_on", True)), "items": predictions.check_watch(rows, s.get("crowd_move_points", 10))}


@api.post("/watchlist")
def watchlist_add(w: dict = Body(..., examples=[{"kind": "indicator", "indicator": "inflation", "entity": "NZL", "op": "above", "threshold": 3}])):
    """Watch an indicator crossing a line, a crowd question moving, or an IMF forecast being revised."""
    try:
        return predictions.add_watch(w)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.delete("/watchlist/{watch_id}")
def watchlist_delete(watch_id: str):
    if not predictions.delete_watch(watch_id):
        raise HTTPException(404, f"no watch {watch_id}")
    return {"deleted": watch_id}


# ----------------------------------------------------------------------------- Crowd forecasts
@api.get("/crowd")
def crowd_list(site: str | None = None, category: str | None = None, country: str | None = None,
               status: str | None = "open", q: str | None = None, indicator: str | None = None, followed: bool = False,
               hidden: bool = False, sort: Literal["busy", "closing", "newest", "moved", "resolved"] = "busy",
               days: int = Query(7, ge=1, le=90), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Crowd questions matched to countries, indicators and categories, each with its chance now and how far
    it moved over `days` days. status: open, closed, resolved (or empty for all)."""
    f = crowd_terms.load_follow()
    out = crowd.questions(rows, site=site, category=category, country=country, status=status or None, q=q, indicator=indicator,
                          follow=f["follow"], hide=f["hide"], only_followed=followed, show_hidden=hidden, sort=sort, days=days,
                          limit=limit, offset=offset)
    out["categories"] = crowd_terms.CATEGORIES
    out["sites"] = crowd_terms.SITES
    out["loaded"] = crowd.has_data(rows)
    return out


@api.get("/crowd/question")
def crowd_question(key: str):
    """One question: its record, chance over time (the site's own history and the app's saves), your
    Metaculus forecasts, comments, the same question on other sites, and events in its countries."""
    rec = crowd.question(rows, key)
    if rec is None:
        raise HTTPException(404, f"no question {key}")
    f = crowd_terms.load_follow()
    rec["followed"], rec["hidden"] = key in f["follow"], key in f["hide"]
    rec["predictions"] = [p for p in predictions.listing() if p.get("crowd_key") == key]
    return rec


@api.post("/crowd/follow")
def crowd_follow(body: dict = Body(..., examples=[{"key": "metaculus:123", "follow": True}])):
    """Follow or hide a question: {key, follow: bool} or {key, hide: bool}. Followed questions get their full
    history and comments read at the next refresh."""
    key = str(body.get("key") or "")
    if not re.fullmatch(r"(polymarket|metaculus|manifold):[\w-]{1,80}", key):
        raise HTTPException(422, "key is <site>:<id>")
    f = crowd_terms.load_follow()
    for name in ("follow", "hide"):
        if name in body:
            lst = [k for k in f[name] if k != key]
            if body[name]:
                lst.append(key)
            f[name] = lst
    crowd_terms.save_follow(f)
    return f


@api.get("/crowd/moves")
def crowd_moves(days: int = Query(7, ge=1, le=90), points: float | None = Query(None, ge=1, le=100), country: str | None = None):
    s = userdata.settings()
    f = crowd_terms.load_follow()
    return crowd.moves(rows, days=days, min_points=points or s.get("crowd_move_points", 10), countries=split(country) or None,
                       hide=f["hide"], limit=60)


@api.get("/crowd/events")
def crowd_events():
    """Events against predictions: did the crowd see resolved questions coming, and how early."""
    return crowd.events_vs(rows, int(userdata.settings().get("crowd_score_days", 7)))


@api.get("/crowd/country/{entity_id}")
def crowd_country(entity_id: str):
    """A country page's "What the crowd expects" card: its busiest open questions and ViEWS conflict forecasts."""
    return crowd.country(rows, entity_id, hide=crowd_terms.load_follow()["hide"])


@api.get("/crowd/conflict")
def crowd_conflict():
    """ViEWS conflict forecasts by country for the next 12 months."""
    return crowd.conflict_map(rows)


@api.get("/layers")
def layers():
    """The map overlays the warehouse holds (plate boundaries, faults, volcanoes, earthquakes), without their features."""
    return rows("""SELECT l.layer_id, l.name, l.description, l.kind, l.feature_count, l.source_id, s.short_name AS source_name
        FROM layers l LEFT JOIN sources s USING (source_id) ORDER BY l.layer_id""")


@api.get("/layers/{layer_id}")
def layer(layer_id: str):
    """One overlay's features, as GeoJSON. storms_active is read live from NOAA (kept an hour)."""
    if layer_id in ("fires_now", "fires_week", "heat_now", "coral_alerts"):
        on = bool(userdata.settings().get("hazards_live", True))
        data = (hazards.fires("7d" if layer_id == "fires_week" else "24h", on) if layer_id.startswith("fires")
                else hazards.heat(_hazard_cities(), on) if layer_id == "heat_now" else hazards.coral(on))
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json",
                        headers={"Cache-Control": "max-age=900"})
    if layer_id == "storms_active":
        data = climate.active_storms(bool(userdata.settings().get("climate_live_map", True)))
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json",
                        headers={"Cache-Control": "max-age=900"})
    found = rows("SELECT geojson FROM layers WHERE layer_id = ?", [layer_id])
    if not found:
        raise HTTPException(404, f"no map layer {layer_id}; a refresh loads the map layers")
    return Response(found[0]["geojson"], media_type="application/geo+json",
                    headers={"Cache-Control": "max-age=3600"})


def _hazard_cities() -> list[dict]:
    """The big cities the heat layer checks: a million people or more, biggest first (at most 600)."""
    if not _has_cities():
        return []
    return [{"name": r["name"], "country": r["country_id"], "lon": r["lon"], "lat": r["lat"]} for r in rows(
        "SELECT name, country_id, lat, lon FROM cities WHERE population >= 1000000 AND lat IS NOT NULL ORDER BY population DESC LIMIT 600")]


@api.get("/hazards/{entity_id}")
def hazards_country(entity_id: str):
    """A country card's line on fires, heatwaves and reefs: only what the map layers already read (no waiting)."""
    return hazards.country(entity_id, bool(userdata.settings().get("hazards_live", True)), [])


@api.get("/events")
def events(
    entities: str | None = Query(None, description="Comma-separated entity ids; none for every country"),
    members: bool = Query(False, description="For a group, its member countries' events (members at the time)"),
    kinds: str | None = Query(None, description="Comma-separated kinds (see /events/kinds); none for all"),
    sources: str | None = None,
    start: str | None = Query(None, description="A year or a date: events still going on or after it"),
    end: str | None = Query(None, description="A year or a date: events starting on or before it"),
    min_size: float | None = Query(None, description="Leave out sized events smaller than this (unsized ones stay)"),
    q: str | None = Query(None, description="Words in the title, place or detail"),
    limit: int = Query(2000, le=20000),
):
    """Dated events: elections, leaders, coups, conflicts, sporting events, disasters, worked-out episodes
    (recessions, booms...), notable episodes, and your own milestones (source 'user'). Oldest first."""
    ents, kind_list, src_list = split(entities), split(kinds), split(sources)
    lo, hi = _year_or_date(start), _year_or_date(end, end=True)
    where, params = [], []
    if ents:
        if members:
            where.append("""(e.entity_id IN (SELECT unnest(?)) OR EXISTS (SELECT 1 FROM memberships m
                WHERE m.member_id = e.entity_id AND m.group_id IN (SELECT unnest(?))
                AND (m.valid_from IS NULL OR m.valid_from <= coalesce(e.end_date, e.start_date))
                AND (m.valid_to IS NULL OR m.valid_to >= e.start_date)))""")
            params += [ents, ents]
        else:
            where.append("e.entity_id IN (SELECT unnest(?))")
            params.append(ents)
    if kind_list:
        where.append("e.kind IN (SELECT unnest(?))")
        params.append(kind_list)
    if src_list:
        where.append("e.source_id IN (SELECT unnest(?))")
        params.append(src_list)
    if lo:
        where.append("coalesce(e.end_date, e.start_date) >= CAST(? AS DATE)")
        params.append(lo)
    if hi:
        where.append("e.start_date <= CAST(? AS DATE)")
        params.append(hi)
    if min_size is not None:
        where.append("(e.size IS NULL OR abs(e.size) >= ?)")
        params.append(min_size)
    if q:
        where.append("(e.title ILIKE ? OR e.place ILIKE ? OR e.detail ILIKE ? OR e.subkind ILIKE ?)")
        params += [f"%{q}%"] * 4
    # The same disaster from Wikidata and EM-DAT: keep EM-DAT's, which has the fuller figures.
    where.append("""NOT (e.source_id = 'wikidata' AND e.kind IN ('disaster', 'epidemic') AND EXISTS (
        SELECT 1 FROM events x WHERE x.source_id = 'emdat' AND x.entity_id = e.entity_id
        AND abs(date_diff('day', x.start_date, e.start_date)) <= 3))""")
    sql = (f"SELECT {', '.join('e.' + c for c in EVENT_COLUMNS)}, n.short_name AS entity_name FROM events e "
           f"LEFT JOIN entities n USING (entity_id) {'WHERE ' + ' AND '.join(where) if where else ''} "
           f"ORDER BY e.start_date, e.entity_id LIMIT ?")
    out = rows(sql, params + [limit])
    for r in out:
        for k in ("start_date", "end_date"):
            r[k] = r[k].isoformat() if r[k] else None
    if (not kind_list or "user" in kind_list) and (not src_list or "user" in src_list):
        names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
        group_members = set()
        if ents and members:
            group_members = {r["member_id"] for r in rows(
                "SELECT member_id FROM memberships WHERE group_id IN (SELECT unnest(?))", [ents])}
        for m in _milestone_rows():
            if ents and m["entity_id"] not in ents and m["entity_id"] not in group_members:
                continue
            if (lo and (m["end_date"] or m["start_date"]) < lo) or (hi and m["start_date"] > hi):
                continue
            if q and q.lower() not in f"{m['title']} {m['detail'] or ''} {m['subkind'] or ''}".lower():
                continue
            out.append({**m, "entity_name": names.get(m["entity_id"], m["entity_id"])})
        out.sort(key=lambda r: (r["start_date"], r["entity_id"]))
    return out[:limit]


@api.get("/events/kinds")
def event_kinds():
    """What events there are: per kind, the count, sources and the most common subkinds."""
    found = rows("""SELECT kind, count(*) AS n, list(DISTINCT source_id ORDER BY source_id) AS sources,
            min(start_date) AS first, max(start_date) AS last FROM events GROUP BY kind ORDER BY n DESC""")
    subs = rows("""SELECT * FROM (SELECT kind, subkind, count(*) AS n FROM events WHERE subkind IS NOT NULL GROUP BY 1, 2)
            QUALIFY row_number() OVER (PARTITION BY kind ORDER BY n DESC) <= 12 ORDER BY kind, n DESC""")
    for k in found:
        k["first"], k["last"] = str(k["first"]), str(k["last"])
        k["subkinds"] = [{"subkind": s["subkind"], "n": s["n"]} for s in subs if s["kind"] == k["kind"]]
    mine = userdata.milestones()
    if mine:
        found.append({"kind": "user", "n": len(mine), "sources": ["user"], "first": mine[0]["start_date"],
                      "last": mine[-1]["start_date"], "subkinds": []})
    return found


@api.get("/milestones")
def get_milestones():
    """Your own events."""
    return userdata.milestones()


@api.post("/milestones")
def post_milestone(m: dict = Body(...)):
    """Add a milestone: {entity_id, title, start_date, end_date?, subkind?, note?, url?}."""
    try:
        return userdata.save_milestone(m)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.put("/milestones/{milestone_id}")
def put_milestone(milestone_id: str, m: dict = Body(...)):
    try:
        return userdata.save_milestone(m, milestone_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except KeyError:
        raise HTTPException(404, f"no milestone {milestone_id}")


@api.delete("/milestones/{milestone_id}")
def delete_milestone(milestone_id: str):
    if not userdata.delete_milestone(milestone_id):
        raise HTTPException(404, f"no milestone {milestone_id}")
    return {"deleted": milestone_id}


@api.get("/around")
def around(
    indicator: str,
    event_id: str | None = Query(None, description="One event (with entity), or else every event matching kind/subkind/q"),
    entity: str | None = None,
    kind: str | None = None,
    subkind: str | None = None,
    q: str | None = Query(None, description="Words in the title, e.g. Olympic"),
    before: int = Query(5, ge=1, le=20),
    after: int = Query(5, ge=1, le=20),
    compare: str = Query("world", description="An entity to compare with; 'region' or 'income' for each country's "
                                               "own UN sub-region or income group; or 'none'"),
    mode: Literal["auto", "value", "index"] = Query("auto", description="index: the year before the event = 100"),
    min_size: float | None = None,
    limit: int = Query(60, le=200),
):
    """An indicator in the years around events: each event's country from `before` years before to `after`
    years after the event's start year, beside a comparison (the world by default), and the average path.
    Use it to see what a World Cup, a coup or a disaster did to growth, inflation or anything else."""
    ind = rows("SELECT indicator_id, name, unit FROM indicators WHERE indicator_id = ?", [indicator])
    if not ind:
        raise HTTPException(404, f"no indicator {indicator}")
    if event_id:
        evs = [e for e in events(entities=entity, members=False, kinds=None, sources=None, start=None, end=None,
                                 min_size=None, q=None, limit=20000) if e["event_id"] == event_id]
    else:
        evs = events(entities=entity, members=False, kinds=kind, sources=None, start=None, end=None,
                     min_size=min_size, q=q, limit=20000)
        if subkind:
            evs = [e for e in evs if (e["subkind"] or "").lower() == subkind.lower()]
    if not evs:
        raise HTTPException(404, "no events match")
    evs = sorted(evs, key=lambda e: e["start_date"], reverse=True)[:limit]
    unit = ind[0]["unit"] or ""
    use_index = mode == "index" or (mode == "auto" and "%" not in unit and "per" not in unit.lower()
                                    and "rate" not in ind[0]["name"].lower())
    offsets = list(range(-before, after + 1))
    years = [int(e["start_date"][:4]) for e in evs]
    span_lo, span_hi = min(years) - before - 1, max(years) + after
    # Each country against its own region or income group, or everyone against one entity.
    peer_type = {"region": "subregion", "income": "income_group"}.get(compare)
    peers: dict[str, str] = {}
    if peer_type:
        for r in rows("""SELECT m.member_id, min(m.group_id) AS group_id FROM memberships m JOIN entities g ON g.entity_id = m.group_id
                WHERE g.type = ? AND m.member_id IN (SELECT unnest(?)) AND m.valid_to IS NULL GROUP BY 1""",
                      [peer_type, sorted({e["entity_id"] for e in evs})]):
            peers[r["member_id"]] = r["group_id"]
    compare_of = (lambda ent: peers.get(ent)) if peer_type else (lambda ent: None if compare == "none" else compare)
    ents = sorted({e["entity_id"] for e in evs} | {c for c in (compare_of(e["entity_id"]) for e in evs) if c})
    data = _series(indicator, ",".join(ents), None, span_lo, span_hi, None, "", "central", True, None)
    by = {(r["entity_id"], int(r["period"][:4])): r["value"] for r in data}

    def path(ent: str, y0: int) -> list[float | None]:
        vals = [by.get((ent, y0 + k)) for k in offsets]
        if not use_index:
            return vals
        base = by.get((ent, y0 - 1))
        return [round(v / base * 100, 3) if v is not None and base else None for v in vals]

    out = []
    for e, y0 in zip(evs, years):
        own = path(e["entity_id"], y0)
        if all(v is None for v in own):
            continue
        peer = compare_of(e["entity_id"])
        cmp = path(peer, y0) if peer else None
        diff = ([round(a - b, 4) if a is not None and b is not None else None for a, b in zip(own, cmp)]
                if cmp else None)
        out.append({"event_id": e["event_id"], "entity_id": e["entity_id"], "entity_name": e.get("entity_name"),
                    "title": e["title"], "kind": e["kind"], "subkind": e["subkind"], "year": y0,
                    "start_date": e["start_date"], "values": own, "compare": cmp, "compare_id": peer, "diff": diff})

    def mean(key: str) -> list[float | None]:
        cols = [[r[key][i] for r in out if r[key] and r[key][i] is not None] for i in range(len(offsets))]
        return [round(sum(c) / len(c), 4) if c else None for c in cols]

    return {"indicator": ind[0], "mode": "index" if use_index else "value", "compare": compare, "offsets": offsets,
            "events": out, "mean": mean("values"), "mean_compare": mean("compare") if compare != "none" else None,
            "mean_diff": mean("diff") if compare != "none" else None, "n": len(out),
            "note": ("Index: the year before each event = 100." if use_index else f"Values in {unit}.")
            + (" Each country compared with its own UN sub-region." if compare == "region"
               else " Each country compared with its own income group." if compare == "income"
               else f" Compared with {compare} over the same years." if compare != "none" else "")}


# ----------------------------------------------------------------------------- the world beyond borders
CW_SCORE = {"deteriorated": -2, "risk_alert": -1, "unchanged": 0, "improved": 1, "resolution_opportunity": 2}


@api.get("/entities/{entity_id}/voting")
def voting(entity_id: str,
           compare: str | None = Query(None, description="Partners, comma-separated; 'eu' is the average over the "
                                                         "EU's members of the year. Default: Settings voting_compare")):
    """How often a country voted with others in the UN General Assembly (percent, by year), its voting
    position (ideal point), and its Security Council seats and vetoes."""
    partners = [p for p in (split(compare) or split(userdata.settings().get("voting_compare") or "USA,CHN,RUS,eu"))
                if p != entity_id][:8]
    names = {r["entity_id"]: r["short_name"] for r in rows(
        "SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [partners + [entity_id]])}
    lines = []
    for p in partners:
        if p in ("eu", "nato", "oecd", "g7", "g20", "asean", "au") or p.islower():
            # a group: the average of the agreement with its members of each year
            data = rows("""SELECT year(s.period_start) AS year, round(avg(s.value), 2) AS value, count(*) AS n
                FROM series s JOIN memberships m ON m.member_id = s.breakdown AND m.group_id = ?
                  AND (m.valid_from IS NULL OR m.valid_from <= s.period_start)
                  AND (m.valid_to IS NULL OR m.valid_to >= s.period_start)
                WHERE s.indicator_id = 'unga_agreement' AND s.entity_id = ? AND s.variant = 'central' AND s.breakdown <> ?
                GROUP BY 1 ORDER BY 1""", [p, entity_id, entity_id])
            label = f"{names.get(p, p)} members (average)"
        else:
            data = rows("""SELECT year(period_start) AS year, value FROM series WHERE indicator_id = 'unga_agreement'
                AND entity_id = ? AND breakdown = ? AND variant = 'central' ORDER BY 1""", [entity_id, p])
            label = names.get(p, p)
        lines.append({"id": p, "name": label, "points": [[r["year"], r["value"]] for r in data]})
    ideal = rows("""SELECT year(period_start) AS year, value FROM series WHERE indicator_id = 'unga_ideal_point'
        AND entity_id = ? AND breakdown = '' AND variant = 'central' ORDER BY 1""", [entity_id])
    closest = rows("""SELECT s.breakdown AS entity_id, coalesce(e.short_name, s.breakdown) AS name, s.value
        FROM series s LEFT JOIN entities e ON e.entity_id = s.breakdown
        WHERE s.indicator_id = 'unga_agreement' AND s.entity_id = ? AND s.variant = 'central'
          AND s.period_start = (SELECT max(period_start) FROM series WHERE indicator_id = 'unga_agreement' AND entity_id = ?)
        ORDER BY s.value DESC""", [entity_id, entity_id])
    council = events(entities=entity_id, members=False, kinds="un", sources=None, start=None, end=None, min_size=None,
                     q=None, limit=2000)
    return {"entity": entity_id, "name": names.get(entity_id, entity_id), "lines": lines,
            "ideal": [[r["year"], r["value"]] for r in ideal],
            "closest": closest[:8], "furthest": closest[-8:][::-1] if len(closest) > 8 else [],
            "closest_year": rows("""SELECT max(year(period_start)) AS y FROM series WHERE indicator_id = 'unga_agreement'
                AND entity_id = ?""", [entity_id])[0]["y"],
            "council": council}


@api.get("/crisiswatch")
def crisiswatch(month: str | None = Query(None, description="YYYY-MM; default the latest month stored")):
    """CrisisWatch ratings for one month, for a map: each country's rating as a score
    (-2 deteriorated, -1 conflict risk alert, 0 unchanged, 1 improved, 2 resolution opportunity)."""
    months = [r["m"] for r in rows("""SELECT DISTINCT strftime(start_date, '%Y-%m') AS m FROM events
        WHERE kind = 'crisiswatch' ORDER BY 1""")]
    if not months:
        return {"months": [], "month": None, "rows": []}
    if month not in months:
        month = max((m for m in months if m <= (month or months[-1])), default=months[-1])
    data = rows("""SELECT e.entity_id, coalesce(n.short_name, e.entity_id) AS name, e.subkind, e.title, e.detail, e.place, e.url
        FROM events e LEFT JOIN entities n USING (entity_id)
        WHERE e.kind = 'crisiswatch' AND strftime(e.start_date, '%Y-%m') = ? ORDER BY e.subkind, name""", [month])
    for r in data:
        r["score"] = CW_SCORE.get(r["subkind"] or "", 0)
    return {"months": months, "month": month, "rows": data}


ZONES = {
    "ATA": {"indicators": ["sea_ice_extent_min", "sea_ice_extent_max", "sea_ice_extent_mean", "sea_ice_extent"],
            "layers": ["antarctic_claims", "antarctic_stations"], "treaties": []},
    "arctic": {"indicators": ["sea_ice_extent_min", "sea_ice_extent_max", "sea_ice_extent_mean", "sea_ice_extent"],
               "layers": [], "treaties": []},
    "space": {"indicators": ["objects_in_orbit_payload", "objects_in_orbit_rocket_body", "objects_in_orbit_debris"],
              "layers": [], "treaties": [], "by_country": ["sats_in_orbit", "sats_launched", "space_launches", "debris_in_orbit"]},
    "high_seas": {"indicators": [], "layers": [], "treaties": ["unclos", "bbnj"]},
}


@api.get("/zones")
def zones():
    """Places beyond any one country: Antarctica, the Arctic, space and the high seas, with what is
    stored for each (indicators, map layers, the treaties that govern them)."""
    have_inds = {r["indicator_id"] for r in rows("SELECT DISTINCT indicator_id FROM series WHERE indicator_id IN (SELECT unnest(?))",
                                                 [[i for z in ZONES.values() for i in z["indicators"] + z.get("by_country", [])]])}
    have_layers = {r["layer_id"] for r in rows("SELECT layer_id FROM layers")}
    ents = {r["entity_id"]: r for r in rows("SELECT entity_id, short_name, name, description FROM entities WHERE entity_id IN (SELECT unnest(?))",
                                             [list(ZONES)])}
    out = []
    for zid, z in ZONES.items():
        e = ents.get(zid, {"entity_id": zid, "short_name": zid, "name": zid, "description": None})
        treaties = []
        for t in z["treaties"]:
            n = rows("""SELECT count(DISTINCT entity_id) FILTER (WHERE title LIKE 'Joined%') AS joined,
                count(DISTINCT entity_id) FILTER (WHERE title LIKE 'Signed%') AS signed_only, min(title) AS title
                FROM events WHERE kind = 'treaty' AND subkind = ?""", [t])[0]
            treaties.append({"treaty": t, **n})
        out.append({**e, "indicators": [i for i in z["indicators"] if i in have_inds],
                    "by_country": [i for i in z.get("by_country", []) if i in have_inds],
                    "layers": [l for l in z["layers"] if l in have_layers], "treaties": treaties})
    return out


@api.get("/beyond/others")
def beyond_others():
    """International organisations (the UN, Comecon, the Arab League, and the blocs and alliances
    such as the EU and NATO) and armed groups (Al-Qaeda, ISIL), with how many sanctions are on
    each and the most each imposed in one year."""
    return rows("""
        SELECT e.entity_id, e.short_name, e.name, e.type, e.description, e.valid_from, e.valid_to,
               (SELECT count(*) FROM events v WHERE v.entity_id = e.entity_id AND v.kind = 'sanction') AS sanctions_on,
               (SELECT min(year(v.start_date)) FROM events v WHERE v.entity_id = e.entity_id) AS first_year,
               (SELECT max(s.value) FROM series s WHERE s.entity_id = e.entity_id AND s.indicator_id = 'sanctions_imposed'
                  AND s.status = 'E') AS most_imposed,
               (SELECT count(*) FROM events v WHERE v.entity_id = e.entity_id) AS events
        FROM entities e WHERE e.type IN ('organisation', 'bloc', 'alliance', 'armed_group')
        ORDER BY e.type = 'armed_group', sanctions_on DESC, most_imposed DESC NULLS LAST, e.short_name""")


# ----------------------------------------------------------------------------- relationship scan
def _build_id() -> str:
    return warehouse.current().path.stem


@api.get("/relationships")
def relationships_list(label: str | None = None, domain: str | None = None, group: str | None = None,
                       q: str | None = None, indicator: str | None = None, drivers: bool = False,
                       hide_same: bool = True, first: bool = False, hide_same_source: bool = False,
                       built: str = Query("last", pattern="^(last|hide|only|mixed)$"),
                       limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Pairs of indicators the relationship scan found worth a look, best first. Each
    carries its evidence labels (move together, one tends to come first, holds after
    allowing for income and time); nothing is called cause and effect. Filters: label,
    topic (domain), country group (pairs whose link also shows within that group),
    words, one indicator, pairs in the forecast model's driver list. Pairs where one
    figure is made from the other (a total and the same per person, a level and its
    growth, a ratio and its parts) carry `built_from` with the reason; `built` lists
    them last (default), hides them, shows only them, or mixes them in. `scan` is null
    until the first scan has run (after a refresh)."""
    if label and label not in relterms.LABELS:
        raise HTTPException(422, f"label must be one of {', '.join(relterms.LABELS)}")
    out = relationships.pairs(_build_id(), label, domain, group, q, indicator, drivers, hide_same, first,
                              hide_same_source, limit, offset, built)
    mine = {d["id"] for d in userdata.drivers()}
    for r in out["rows"]:
        r["saved_driver"] = f"{r['x']}__{r['y']}" in mine or f"{r['y']}__{r['x']}" in mine
    return out


@api.get("/relationships/pair")
def relationships_pair(x: str, y: str):
    """One pair: the scan's figures (lag chart, per-group correlations, note) and every
    country-year's changes of both, for the scatter chart."""
    bid = _build_id()
    found = relationships.one(bid, x, y)
    kx, ky = relationships.kind_of(bid, x), relationships.kind_of(bid, y)
    if kx is None or ky is None:
        raise HTTPException(404, "the last scan did not include both indicators")
    pts = rows(relationships.scatter_sql(kx, ky), [x, y, x, y])
    names = {r["entity_id"]: r["name"] for r in rows("SELECT entity_id, name FROM entities WHERE type = 'country'")}
    return {"pair": found, "x": x, "y": y, "kind_x": kx, "kind_y": ky,
            "points": [[p["entity_id"], p["y"], round(p["dx"], 4), round(p["dy"], 4)] for p in pts
                       if p["dx"] is not None and p["dy"] is not None],
            "names": names}


@api.get("/relationships/events")
def relationships_events(kind: str | None = None, indicator: str | None = None, significant: bool = True,
                         built_in: bool = False, diverging: bool = False):
    """Before and after events: how each indicator changed in countries after an event
    of a kind (from the year before to 3 years after, and the path from 3 years before
    to 5 after), less the change in countries of the same income group without one.
    `built_in` also lists links that hold by definition (a recession lowering GDP);
    `diverging` also lists those where the countries were already moving apart before."""
    return relationships.events(_build_id(), kind, indicator, significant, not built_in, not diverging)


@api.get("/drivers")
def drivers_list():
    """Pairs you kept from the Relationships page as what-if drivers for the Forecasts page."""
    return userdata.drivers()


@api.post("/drivers")
def drivers_add(body: dict = Body(..., examples=[{"driver": "urban_share", "target": "gdp_per_capita_growth"}])):
    """Keep a scanned pair as a what-if driver: the driver's extra change moves the
    target by the size the scan estimated (after income and time), after its lag."""
    driver, target = str(body.get("driver") or ""), str(body.get("target") or "")
    found = relationships.one(_build_id(), driver, target)
    if found is None:
        raise HTTPException(404, "the last scan has no such pair")
    if found["slope"] is None or "holds" not in found["labels"]:
        raise HTTPException(422, "only pairs that hold after allowing for income and time have a size to use")
    # the scan's slope is y on x; for the other way round, invert it (a rough reading)
    slope = found["slope"] if not found["flipped"] else (1 / found["slope"] if found["slope"] else None)
    lag = found["best_lag"] if found["first"] in ("x" if not found["flipped"] else "y", "both") else 0
    side_d, side_t = ("x", "y") if not found["flipped"] else ("y", "x")
    try:
        return userdata.add_driver({"driver": driver, "target": target, "slope": slope, "lag": lag,
                                    "driver_name": found[f"{side_d}_name"], "target_name": found[f"{side_t}_name"],
                                    "driver_unit": found[f"{side_d}_unit"], "target_unit": found[f"{side_t}_unit"],
                                    "target_kind": relationships.kind_of(_build_id(), target)})
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.delete("/drivers/{driver_id}")
def drivers_delete(driver_id: str):
    if not userdata.delete_driver(driver_id):
        raise HTTPException(404, "no such driver")
    return {"deleted": driver_id}


@api.get("/keys")
def keys_list():
    """The API keys the app can use: what each unlocks, where to get it, and whether it
    is set in the .env file (never the key itself)."""
    return relationships.keys()


# ----------------------------------------------------------------------------- climate
@api.get("/climate")
def climate_overview():
    """The world's vital signs: temperature against normal, CO2, methane and nitrous oxide in
    the air, sea level, ocean heat, glaciers, sea ice and ice sheets, world emissions, the
    current El Niño phase, and the indicators the emissions map can show."""
    return climate.overview(rows)


@api.get("/climate/headlines")
def climate_headlines(keys: str = Query("NZL,AUS,GBR,USA", description="Comma-separated key countries, the first is home; at most 4")):
    """The Climate page's headline strip (world temperature, CO2, Arctic sea ice, the home country,
    El Niño), records and firsts in the latest figures, and the key countries side by side."""
    return climate.headlines(rows, split(keys)[:4])


# ----------------------------------------------------------------------------- page summaries
@api.get("/look/ranked/{indicator}")
def look_ranked(indicator: str, keys: str = Query("NZL,AUS,GBR,USA", description="Key countries, the first is home")):
    """Where the key countries and the world sit on a figure among all countries, with the home
    country's line ("4th lowest of 190") and a guideline or target where there is one."""
    r = look.ranked(rows, indicator, split(keys)[:6])
    if r is None:
        raise HTTPException(404, f"no country figures for {indicator}")
    return r


@api.get("/look/recovery/{indicator}")
def look_recovery(indicator: str, keys: str = Query("NZL,AUS,GBR,USA"), base: int = 2019, since: int = 2000):
    """Each key country's figure since `since` and its latest as a share of `base`."""
    return look.recovery(rows, indicator, split(keys)[:6], base, since)


@api.get("/look/land-cover/{entity}")
def look_land_cover(entity: str):
    """A country's land cover by year (ESA satellite maps via FAOSTAT, 1992 on) and its biggest moves."""
    return look.land_cover(rows, entity) or {"entity": entity, "parts": []}


@api.get("/look/land-mix/{entity}")
def look_land_mix(entity: str, since: int = 1990):
    """A country's land by use in its latest year as shares of its land area, and the change in each since `since`."""
    return look.land_mix(rows, entity, since)


@api.get("/climate/country/{entity}")
def climate_country(entity: str):
    """One country's climate: temperature against normal, emissions by gas and by sector,
    emissions counted where goods are used, net zero target, carbon price, area burned,
    projections to 2100 (four scenarios, with ranges), its largest disasters, and how its
    temperature has moved with El Niño."""
    return climate.country(rows, entity)


@api.get("/climate/normals")
def climate_normals(entities: str = Query("NZL", description="Comma-separated country ids, at most 8")):
    """The year's weather for each country: the 1991-2020 average of each month (average, daytime high and
    night-time low temperature, and rainfall), with its year in a few figures."""
    return climate.normals(rows, split(entities)[:8])


@api.get("/climate/sea-ice")
def climate_sea_ice(pole: str = Query("arctic", description="arctic or ATA (Antarctic)")):
    """Sea ice through each year since 1978: every year's days, the 1981-2010 median and band, and each
    year's lowest and highest day (the yearly circle on Climate > Sea ice)."""
    return climate.sea_ice(rows, pole)


@api.get("/climate/enso")
def climate_enso():
    """El Niño and La Niña: the index, the Indian Ocean Dipole and the Southern Annular Mode
    by month, past episodes, the current phase, notes on what each phase means for some
    countries, and how strongly each country's temperature has moved with El Niño."""
    return climate.enso(rows)


@api.get("/climate/storms")
def climate_storms():
    """Tropical storms per year and basin, and the strong ones (category 3 or more), from the storm tracks layer."""
    return climate.storms(rows)


@api.get("/climate/live")
def climate_live():
    """Storms, floods, droughts, fires and earthquakes happening now (GDACS), asked for when the
    page opens and kept 15 minutes. Off with Settings: Climate, live map."""
    return climate.live(bool(userdata.settings().get("climate_live_map", True)))


@api.get("/climate/policy")
def climate_policy():
    """Each country's net zero target year and how firm it is, its carbon price, when it
    joined the Paris Agreement, and its share of world CO2 and emissions per person."""
    return climate.policy(rows)


# ----------------------------------------------------------------------------- climate zones, pollution, nature
def _zones_scenario(scenario: str | None) -> str:
    s = scenario or str(userdata.settings().get("zones_scenario", "ssp245"))
    return s if s in nature.SCENARIOS else "ssp245"


@api.get("/climatezones")
def zones_overview():
    """The Köppen-Geiger zones: legend (30 zones in five groups, with colours), the emissions
    paths, and which periods are loaded."""
    have = nature.periods(rows) if _has_table("zone_grids") else []
    return {**nature.legend(), "periods": have, "scenario": _zones_scenario(None)}


@api.get("/climatezones/tiles/{period}/{scenario}/{z}/{x}/{y}.png")
def zones_tile(period: str, scenario: str, z: int, x: int, y: int, groups: bool = False):
    """A 256-pixel map tile of the climate zones (Web Mercator), the six groups if groups=true.
    Periods up to 2020 use scenario historical whatever is asked."""
    if not re.fullmatch(r"\d{4}-\d{4}", period) or not (0 <= z <= 10) or not (0 <= y < 2 ** z) or not _has_table("zone_grids"):
        raise HTTPException(404, "no such tile")
    scen = "historical" if int(period[:4]) <= 2020 else _zones_scenario(scenario)
    png = nature.tile_png(rows, _build_id(), period, scen, z, x, y, groups)
    if png is None:
        raise HTTPException(404, f"no climate zone grid for {period} {scen}; a refresh loads them")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@api.get("/climatezones/country/{entity}")
def zones_country(entity: str, scenario: str | None = None):
    """A country's land in each zone and group per period (and each path ahead), the share of its
    city dwellers in each zone now, and its big cities' climate twins in 2071-2099."""
    if not _has_table("zone_grids"):
        return {"entity": entity, "zones": {}, "groups": {}, "people": {}, "twins": [], "legend": nature.legend()}
    return nature.country(rows, _build_id(), entity, _zones_scenario(scenario))


@api.get("/climatezones/city/{city_id}")
def zones_city(city_id: str, scenario: str | None = None):
    """One city's zone now and in 2041-2070 and 2071-2099, with its rough climate twin for each."""
    found = rows("SELECT city_id, name, country_id, lat, lon, population FROM cities WHERE city_id = ?", [city_id]) if _has_cities() else []
    if not found or not _has_table("zone_grids"):
        raise HTTPException(404, f"no city {city_id} or no climate zones loaded")
    scen = _zones_scenario(scenario)
    return {"scenario": scen, "periods": {p: (nature.twins(rows, _build_id(), found, scen, p) or [None])[0]
                                          for p in ("2041-2070", "2071-2099")}}


@api.get("/climate/pledges/{entity}")
def climate_pledges(entity: str, indicator: str = "ghg_total_gcp"):
    """A country's climate pledges (NDCs) as points for its emissions chart."""
    return nature.pledges(rows, entity, indicator)


@api.get("/pollution")
def pollution_overview():
    """The Pollution page: the indicators on each tab (air, water, ocean, across borders) and
    pollution disasters and smoke across borders as events."""
    return nature.pollution(rows)


@api.get("/pollution/country/{entity}")
def pollution_country(entity: str):
    """One country's latest pollution figures by tab and its pollution events."""
    return nature.pollution_country(rows, entity)


@api.get("/nature")
def nature_overview():
    """The Nature tab: indicators of nature being lost, invasive species and disease, and
    recovery; animal disease and pest events; the pest watch list with how many countries
    have each; species comebacks and restoration projects; protected areas loaded."""
    return nature.nature(rows)


@api.get("/nature/country/{entity}")
def nature_country(entity: str):
    """One country's nature figures, species by name (where loaded), pests, events, comebacks
    and restoration."""
    return nature.nature_country(rows, entity)


@api.get("/nature/protected")
def nature_protected(west: float = -180, south: float = -90, east: float = 180, north: float = 90,
                     limit: int = Query(1500, le=5000)):
    """Protected areas in a map window (WDPA), largest first, as GeoJSON."""
    data = nature.protected(rows, west, south, east, north, limit) if _has_table("protected_areas") else \
        {"type": "FeatureCollection", "features": []}
    return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json")


# ----------------------------------------------------------------------------- transport, tourism and networks
def _min_deaths() -> int:
    try:
        return int(local.load_settings().get("transport_min_deaths", 10))
    except (TypeError, ValueError):
        return 10


@api.get("/transport")
def transport_overview():
    """The Transport page: indicators by tab (sea, air, land, safety), chokepoints with ships a
    day now against a year before, the busiest ports and airports, cable, pipeline and canal
    events, air, sea and rail accidents (from Settings > Transport's deaths), and what is loaded."""
    return transport.transport(rows, _min_deaths())


@api.get("/transport/heads")
def transport_heads(home: str = "NZL"):
    """The Transport page's headline strip: ships through the chokepoints, world air passengers,
    the home country's ship calls and cables or pipelines cut in the last 12 months."""
    return transport.heads(rows, home)


@api.get("/transport/ports/{entity}")
def transport_country_ports(entity: str, n: int = Query(6, ge=1, le=20)):
    """A country's busiest ports: ship calls a month for three years, the last 12 months against the 12 before."""
    return transport.country_ports(rows, entity, n)


@api.get("/transport/country/{entity}")
def transport_country(entity: str):
    """A country's transport figures, ports, airports, accidents, cables, pipelines and river basins."""
    return transport.transport_country(rows, entity, _min_deaths())


@api.get("/transport/chokepoint/{ident}")
def transport_chokepoint(ident: str, start: int | None = None):
    """Ships through one chokepoint a day by type (weekly averages) and the countries on its shores."""
    return transport.chokepoint(rows, ident, start)


@api.get("/transport/port/{ident}")
def transport_port(ident: str):
    """One port's ship calls and estimated tonnes in and out a month (IMF PortWatch)."""
    return transport.port(rows, ident)


@api.get("/geo/{layer}")
def geo_layer(layer: str, west: float = -180, south: float = -90, east: float = 180, north: float = 90,
              zoom: float = 2, status: str | None = None):
    """Rivers, river_names, basins, waterways, cables, gas_pipelines or oil_pipelines in a map
    window as GeoJSON, with the detail that suits the zoom."""
    if layer not in transport.GEO_LAYERS:
        raise HTTPException(404, f"no geo layer {layer}; one of {', '.join(transport.GEO_LAYERS)}")
    data = transport.geo(rows, layer, west, south, east, north, zoom, status)
    return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json")


@api.get("/geo/{layer}/{feature_id}")
def geo_feature(layer: str, feature_id: str):
    """One feature's card: what it is, and the countries that depend on it (for a basin, its
    split by country with roughly how many people live in each part)."""
    found = transport.feature(rows, layer, feature_id)
    if not found:
        raise HTTPException(404, f"no {layer} {feature_id}")
    return found


@api.get("/depends/{kind}/{ident}")
def depends_on(kind: str, ident: str):
    """The countries that rely on a cable, pipeline, chokepoint (by name) or basin, to highlight on the map."""
    return transport.depends(rows, kind, ident)


@api.get("/tourism")
def tourism_overview():
    """The Tourism page: indicators by tab, the most visited countries, the COVID band, layers loaded."""
    return transport.tourism(rows)


@api.get("/tourism/country/{entity}")
def tourism_country(entity: str):
    """A country's tourism figures, where its visitors come from, and its World Heritage sites."""
    return transport.tourism_country(rows, entity)


@api.get("/live/planes")
def live_planes(west: float, south: float, east: float, north: float):
    """Planes in the air in a map window now (OpenSky Network; at most one request a minute)."""
    from worldmodel_api import live

    if not local.load_settings().get("live_planes", True):
        return {"type": "FeatureCollection", "features": [], "error": "Planes now is switched off in Settings > Transport."}
    return live.PLANES.get(west, south, east, north)


@api.get("/live/ships")
def live_ships(west: float, south: float, east: float, north: float):
    """Ships' latest positions in a map window (aisstream.io, needs AISSTREAM_API_KEY); the area
    fills in over a few minutes as ships report."""
    from worldmodel_api import live

    if not local.load_settings().get("live_ships", True):
        return {"type": "FeatureCollection", "features": [], "error": "Ships now is switched off in Settings > Transport."}
    return live.SHIPS.get(west, south, east, north)


# ----------------------------------------------------------------------------- markets and regions
@api.get("/fx/{entity}")
def fx(entity: str, partners: str | None = Query(None, description="Comma-separated entity ids; default: saved, else top trading partners"),
       start: int | None = None, end: int | None = None, mode: Literal["rate", "index"] = "rate"):
    """The country's currency against its partners' currencies, day by day (week or month over
    longer spans): units of the partner's currency one unit buys, or indexed to 100 at the start;
    with the BIS trade-weighted index each month."""
    saved = (local.load_settings().get("fx_partners") or {}).get(entity)
    return markets.fx(rows, entity, split(partners) or None, start, end, mode, split(saved) or None)


@api.get("/storage-levels")
def storage_list():
    """The storage series held: European gas and LNG (daily), US stocks (weekly), JODI stocks by country (monthly)."""
    return markets.storage_list(rows)


@api.get("/storage-levels/{indicator}/totals")
def storage_totals(indicator: str, by: str = Query("region", pattern="^(region|subregion|country)$"), group: str | None = None,
                   step: str = Query("year", pattern="^(year|month)$"), top: int = Query(10, ge=3, le=30)):
    """A stock added up over countries, year by year (or month by month): split by continent,
    subregion, or by country within a continent or subregion. Shares and days of cover are not added up."""
    out = markets.storage_totals(rows, indicator, by, group, step, top)
    if out is None:
        raise HTTPException(404, f"no totals for {indicator}")
    return out


@api.get("/storage-levels/{indicator}/{entity}")
def storage_series(indicator: str, entity: str, years: int | None = Query(None, ge=2, le=15)):
    """One storage series: this year against the band and average of the years before (Settings: storage_years)."""
    out = markets.storage(rows, indicator, entity, years or int(local.load_settings().get("storage_years", 5)))
    if out is None:
        raise HTTPException(404, f"no storage series {indicator} for {entity}")
    return out


@api.get("/regions/{country}")
def regions(country: str):
    """The country's regions (New Zealand's 16) with every figure held for them, by year."""
    return markets.regions(rows, country)


# ----------------------------------------------------------------------------- sectors
@api.get("/sectors")
def sectors_list():
    """Every sector (one industry followed stage by stage: ore, refined, metal, products),
    grouped, with each stage's latest world exports and production and who leads them.
    Sectors hidden in Settings carry hidden: true."""
    hidden = split(userdata.settings().get("sectors_hidden"))
    return sectors.listing(rows, hidden)


@api.get("/sectors/by-country")
def sectors_by_country(country: str = "NZL", year: int | None = None, since: int | None = None):
    """One country's goods trade by HS chapter (exports, imports, balance, change since a
    year, top five partners each way), its place in every sector stage, and its economy
    by broad sector (value added, % of GDP)."""
    return sectors.by_country(rows, country, year, since)


@api.get("/sectors/overview")
def sectors_overview():
    """The Sectors front page: headline figures, this month's price board (grouped, with
    changes, ten-year range and a five-year sparkline), world trade by sector group, where
    New Zealand counts, and for each sector its trade, price and three biggest makers."""
    return sectors.overview(rows)


@api.get("/sectors/prices")
def sectors_prices():
    """Every monthly commodity price and price index with its latest month, changes over a
    month, a year, five and ten years, ten-year range and (US consumer prices) against 1980."""
    return sectors.prices_table(rows)


@api.get("/sectors/prices/series")
def sectors_price_series(ids: str):
    """Monthly values of up to 12 price series (comma-separated ids), with US consumer prices
    as a yearly level (1980 = 1) for showing them after inflation."""
    return sectors.price_series(rows, split(ids))


@api.get("/sectors/prices/{price_id}/trade")
def sectors_price_trade(price_id: str):
    """Who gains and who pays when a price moves: the biggest sellers and buyers of the stage
    it prices, with their share of world trade and of their own goods trade."""
    out = sectors.price_trade(rows, price_id)
    if out is None:
        raise HTTPException(404, f"no traded stage for {price_id}")
    return out


@api.get("/sectors/{sector_id}")
def sector_page(sector_id: str, year: int | None = None, country: str = "NZL"):
    """One sector: for each stage, production and exports by country (ranking, world
    total and concentration each year), imports, reserves, import reliance, the biggest
    routes, and one country's figures; prices, key companies, and for cars the shift to
    electric, for EV batteries the materials and how concentrated their supply is."""
    out = sectors.page(rows, sector_id, year, country)
    if out is None:
        raise HTTPException(404, f"no sector {sector_id}")
    return out


# ----------------------------------------------------------------------------- religion and languages
@api.get("/religion")
def religion_page(year: int | None = None, group: str = "christian", since: int | None = None):
    """Each religion's share of the world over time by source (Correlates of War 1945-2010, Pew
    2010-2050 with projections), and a map year: each country's largest religion, the share of
    `group`, and its change since `since`."""
    if group not in people.GROUP_IDS:
        raise HTTPException(422, f"group must be one of {', '.join(people.GROUP_IDS)}")
    return people.religion(rows, year, group, since)


@api.get("/entities/{entity_id}/religion")
def entity_religion(entity_id: str):
    """One country's religious mix over time from each source, including the percentages read
    from each CIA Factbook edition's Religions line (exploratory)."""
    return people.religion_country(rows, entity_id)


@api.get("/languages")
def languages_page(lang: str | None = None, top: int = Query(25, ge=1, le=200)):
    """The most spoken languages in the world (first and second language together, CLDR), where
    `lang` is spoken and official, each country's main language, and how many languages are
    spoken and endangered in each (Glottolog)."""
    return people.languages(rows, lang, top)


@api.get("/crises")
def crises_page(kind: list[str] = Query(None), start: int = Query(1800, ge=1500, le=2100), end: int | None = None,
                entity: list[str] = Query(None)):
    """Two centuries of financial crises (Reinhart and Rogoff): for each year the share of
    countries with data in each kind of crisis, and each country's crisis spells as a strip,
    most crisis years first (countries in `entity` first)."""
    bad = [k for k in kind or [] if k not in crises.KINDS]
    if bad:
        raise HTTPException(422, f"kind must be among {', '.join(crises.KINDS)}")
    return crises.crises(rows, kind, start, end, entity)


@api.get("/entities/{entity_id}/languages")
def entity_languages(entity_id: str):
    """One country's languages: share speaking each and official status (CLDR), counts and the
    endangered ones by name (Glottolog), and the latest Factbook line."""
    return people.languages_country(rows, entity_id)


# ----------------------------------------------------------------------------- laws and society
LAW_DOMAINS = ("laws", "crime")


@api.get("/laws")
def laws():
    """The rules and crime figures stored: one row per indicator, with how many countries and which years."""
    return rows("""SELECT i.indicator_id, i.name, i.description, i.unit, i.decimals, i.domain,
            count(DISTINCT s.entity_id) AS countries, min(year(s.period_start)) AS first, max(year(s.period_start)) AS last
        FROM indicators i JOIN series s ON s.indicator_id = i.indicator_id AND s.breakdown = '' AND s.variant = 'central'
          AND NOT s.is_aggregate
        WHERE i.domain IN (SELECT unnest(?)) GROUP BY ALL ORDER BY i.domain DESC, i.name""", [list(LAW_DOMAINS)])


@api.get("/laws/{indicator_id}")
def law_map(indicator_id: str, year: int | None = Query(None, description="Default: the latest year")):
    """One rule in one year for every country, with the year its current value began (since)."""
    ind = rows("SELECT indicator_id, name, description, unit, decimals FROM indicators WHERE indicator_id = ?", [indicator_id])
    if not ind:
        raise HTTPException(404, f"no indicator {indicator_id}")
    years = [r["y"] for r in rows("""SELECT DISTINCT year(period_start) AS y FROM series WHERE indicator_id = ?
        AND breakdown = '' AND variant = 'central' AND NOT is_aggregate ORDER BY 1""", [indicator_id])]
    if not years:
        return {"indicator": ind[0], "years": [], "year": None, "rows": []}
    if year not in years:
        year = max((y for y in years if y <= (year or years[-1])), default=years[-1])
    data = rows("""WITH s AS (SELECT entity_id, year(period_start) AS y, value FROM series WHERE indicator_id = ?
            AND breakdown = '' AND variant = 'central' AND NOT is_aggregate AND year(period_start) <= ?
            QUALIFY row_number() OVER (PARTITION BY entity_id, period_start ORDER BY source_id) = 1),
        cur AS (SELECT entity_id, value FROM s WHERE y = ?),
        changed AS (SELECT s.entity_id, max(s.y) AS last_other FROM s JOIN cur USING (entity_id) WHERE s.value <> cur.value GROUP BY 1)
        SELECT cur.entity_id, coalesce(e.short_name, cur.entity_id) AS name, cur.value,
            (SELECT min(y) FROM s WHERE s.entity_id = cur.entity_id AND s.y > coalesce(c.last_other, -9999)) AS since
        FROM cur LEFT JOIN changed c USING (entity_id) LEFT JOIN entities e USING (entity_id)
        ORDER BY cur.value DESC, name""", [indicator_id, year, year])
    return {"indicator": ind[0], "years": years, "year": year, "rows": data}


@api.get("/entities/{entity_id}/laws")
def entity_laws(entity_id: str):
    """The country's rules: the latest value of each, the year it began, and the changes over time."""
    data = rows("""WITH s AS (SELECT i.indicator_id, i.name, i.unit, i.decimals, i.domain, year(s.period_start) AS y, s.value, s.source_id
            FROM series s JOIN indicators i USING (indicator_id)
            WHERE s.entity_id = ? AND i.domain = 'laws' AND s.breakdown = '' AND s.variant = 'central'),
        latest AS (SELECT * FROM s QUALIFY row_number() OVER (PARTITION BY indicator_id ORDER BY y DESC) = 1),
        other AS (SELECT s.indicator_id, max(s.y) AS last_other FROM s JOIN latest l USING (indicator_id)
            WHERE s.value <> l.value GROUP BY 1)
        SELECT l.indicator_id, l.name, l.unit, l.decimals, l.y AS year, l.value, l.source_id,
            (SELECT min(y) FROM s WHERE s.indicator_id = l.indicator_id AND s.y > coalesce(o.last_other, -9999)) AS since,
            o.last_other IS NOT NULL AS changed
        FROM latest l LEFT JOIN other o USING (indicator_id) ORDER BY l.name""", [entity_id])
    changes = events(entities=entity_id, members=False, kinds="law", sources=None, start=None, end=None, min_size=None,
                     q=None, limit=2000)
    return {"entity": entity_id, "rules": data, "changes": changes}


# ----------------------------------------------------------------------------- topics
@api.get("/topics")
def topics():
    """Topic pages: each with its introduction and the indicators that are loaded, in order."""
    have = {f["indicator_id"] for f in _indicator_rows() if f.get("countries")}
    return [{**t, "indicators": [i for i in t["indicators"] if i in have],
             "missing": [i for i in t["indicators"] if i not in have]} for t in catalogue.topics()]


@api.get("/topics/{topic_id}")
def topic(topic_id: str):
    for t in topics():
        if t["id"] == topic_id:
            return t
    raise HTTPException(404, f"no topic {topic_id}")


@api.get("/indicators/{indicator_id}/ranking")
def indicator_ranking(indicator_id: str, year: int | None = None):
    """Every country's value in one year (by default the indicator's main year: the latest
    with good coverage), highest first, with its rank, the change over ten years, and the
    world value. For the indicator page."""
    meta = next((f for f in _indicator_rows() if f["indicator_id"] == indicator_id), None)
    if meta is None:
        raise HTTPException(404, f"no indicator {indicator_id}")
    y = year or meta.get("main_year") or meta.get("last_estimate_year")
    if y is None:
        return {"indicator": indicator_id, "year": None, "rows": [], "world": None}
    data = rows("""SELECT s.entity_id, e.short_name AS name, s.value, s.status, s.source_id,
            (SELECT p.value FROM series p WHERE p.entity_id = s.entity_id AND p.indicator_id = s.indicator_id
                AND p.source_id = s.source_id AND p.breakdown = '' AND p.variant = 'central'
                AND year(p.period_start) = ? - 10) AS ten_years_before
        FROM series s JOIN entities e ON e.entity_id = s.entity_id
        WHERE s.indicator_id = ? AND year(s.period_start) = ? AND s.breakdown = '' AND s.variant = 'central'
            AND s.source_id = (SELECT source_id FROM indicator_sources WHERE indicator_id = ? ORDER BY rank LIMIT 1)
            AND e.type IN ('country', 'world')
        ORDER BY s.value DESC""", [y, indicator_id, y, indicator_id])
    world = next((r for r in data if r["entity_id"] == "world"), None)
    ranked = [r for r in data if r["entity_id"] != "world"]
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    return {"indicator": indicator_id, "year": y, "rows": ranked, "world": world}


# ----------------------------------------------------------------------------- electricity mix map
ELEC_MIX = {"coal": ["coal_electricity"], "gas": ["gas_electricity"], "oil": ["oil_electricity"],
            "nuclear": ["nuclear_electricity"], "hydro": ["hydro_electricity"], "wind": ["wind_electricity"],
            "solar": ["solar_electricity"], "bio": ["biofuel_electricity"], "other": ["other_renewable_exc_biofuel_electricity"]}


@api.get("/energy/electricity-mix")
def electricity_mix(back: int = Query(10, ge=1, le=40, description="Years before the latest to compare with")):
    """Each country's electricity generation by source in its latest year and `back` years before, as
    shares (%), with the total in TWh; also the world and each continent (countries added up). For the
    electricity map on the Energy topic page."""
    ids = [i for v in ELEC_MIX.values() for i in v]
    got = rows("""SELECT s.entity_id, s.indicator_id, year(s.period_start) AS y, s.value FROM series s
        JOIN entities e ON e.entity_id = s.entity_id
        WHERE s.indicator_id IN (SELECT unnest(?)) AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E'
          AND s.value IS NOT NULL AND e.type IN ('country', 'world')
        QUALIFY row_number() OVER (PARTITION BY s.entity_id, s.indicator_id, s.period_start ORDER BY s.source_id) = 1""", [ids])
    kind = {i: k for k, v in ELEC_MIX.items() for i in v}
    by: dict[str, dict[int, dict[str, float]]] = {}
    for r in got:
        d = by.setdefault(r["entity_id"], {}).setdefault(r["y"], {})
        d[kind[r["indicator_id"]]] = d.get(kind[r["indicator_id"]], 0.0) + max(0.0, float(r["value"]))
    cont = {r["member_id"]: (r["group_id"], r["name"]) for r in rows("""SELECT m.member_id, m.group_id, g.short_name AS name
        FROM memberships m JOIN entities g ON g.entity_id = m.group_id WHERE g.type = 'continent' AND m.valid_to IS NULL""")}
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities WHERE type IN ('country', 'world', 'continent')")}
    # a group's figures: its countries added up, in years when nearly all of its generation has reported
    groups: dict[str, dict[int, dict[str, float]]] = {}
    for e, years in by.items():
        if e in cont:
            for y, d in years.items():
                g = groups.setdefault(cont[e][0], {}).setdefault(y, {})
                for k, v in d.items():
                    g[k] = g.get(k, 0.0) + v
        if e != "world" and "world" not in by:
            for y, d in years.items():
                g = groups.setdefault("world", {}).setdefault(y, {})
                for k, v in d.items():
                    g[k] = g.get(k, 0.0) + v

    def one(e: str, years: dict[int, dict[str, float]], level: str) -> dict | None:
        full = {y: d for y, d in years.items() if sum(d.values()) > 0 and len(d) >= 5}
        if not full:
            return None
        if level != "country":  # a group's newest year is the newest most of its countries have reported
            tot = {y: sum(d.values()) for y, d in full.items()}
            best = max(tot.values())
            full = {y: d for y, d in full.items() if tot[y] >= 0.9 * best} or full
        y = max(full)
        d = full[y]
        t = sum(d.values())
        b = full.get(y - back) or years.get(y - back)
        tb = sum(b.values()) if b else 0
        share = {k: round(100 * d.get(k, 0) / t, 1) for k in ELEC_MIX}
        return {"id": e, "name": names.get(e, e), "level": level, "year": y, "twh": round(t, 1),
                "share": share, "before_year": y - back if tb else None,
                "before": {k: round(100 * b.get(k, 0) / tb, 1) for k in ELEC_MIX} if tb else None,
                "top": max(share, key=lambda k: share[k])}

    out = []
    for e, years in by.items():
        if e == "world":
            continue
        if (x := one(e, years, "country")):
            out.append(x)
    for g, years in groups.items():
        if g != "world" and (x := one(g, years, "continent")):
            out.append(x)
    w = one("world", by.get("world") or groups.get("world", {}), "world")
    return {"world": w, "rows": out, "kinds": list(ELEC_MIX), "back": back,
            "source": "Energy Institute and Ember, via Our World in Data"}


# ----------------------------------------------------------------------------- cities
def _has_cities() -> bool:
    return bool(rows("SELECT 1 FROM information_schema.tables WHERE table_name = 'cities' AND table_schema = 'main'"))


NO_CITIES = "No cities yet: run .\\refresh.bat (GeoNames gives the city list)."
CITY_COLS = """c.city_id, c.name, c.country_id, e.short_name AS country, c.admin1, c.lat, c.lon, c.capital,
    c.population AS geonames_population,
    (SELECT max_by(value, period_start) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'city_population' AND year(s.period_start) <= year(current_date)) AS population,
    (SELECT year(max(period_start)) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'city_population' AND year(s.period_start) <= year(current_date)) AS population_year,
    (SELECT max_by(value, period_start) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'city_population' AND year(s.period_start) = 2035) AS population_2035,
    (SELECT max_by(value, period_start) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'wn_city_cost_index') AS wn_cost_index,
    (SELECT max_by(value, period_start) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'wn_city_monthly_cost_usd') AS wn_monthly_cost_usd,
    (SELECT max_by(value, period_start) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'numbeo_cost_of_living') AS numbeo_cost_index,
    (SELECT max_by(value, period_start) FROM city_series s WHERE s.city_id = c.city_id
        AND s.indicator_id = 'numbeo_purchasing_power') AS numbeo_purchasing_power"""


@api.get("/cities")
def cities(country: str | None = Query(None, description="Comma-separated country ids"), q: str | None = None,
           min_population: float = 0, limit: int = Query(300, ge=1, le=5000),
           sort: Literal["population", "name", "cost", "growth"] = "population"):
    """Cities with their latest population (UN agglomeration where there is one, else GeoNames),
    growth to 2035 and cost of living figures. For the Cities page and the country page."""
    if not _has_cities():
        return {"rows": [], "note": NO_CITIES}
    where, params = ["1 = 1"], []
    if ids := split(country):
        where.append(f"c.country_id IN ({', '.join('?' * len(ids))})")
        params += ids
    if q:
        where.append("(c.name ILIKE ? OR c.ascii_name ILIKE ? OR c.synonyms ILIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q.lower()}%"]
    order = {"population": "coalesce(population, geonames_population) DESC NULLS LAST", "name": "name",
             "cost": "coalesce(wn_cost_index, numbeo_cost_index) DESC NULLS LAST",
             "growth": "population_2035 / population DESC NULLS LAST"}[sort]
    found = rows(f"""SELECT * FROM (SELECT {CITY_COLS} FROM cities c LEFT JOIN entities e ON e.entity_id = c.country_id
                     WHERE {' AND '.join(where)})
                     WHERE coalesce(population, geonames_population, 0) >= ?
                     ORDER BY {order} LIMIT ?""", [*params, min_population, limit])
    return {"rows": found, "note": None}


LARGEST_MEASURES = {"city_population": "UN World Urbanization Prospects (urban agglomerations)",
                    "ghsl_population": "GHSL Urban Centre Database (urban centres, satellite-based)"}


@api.get("/cities/largest")
def cities_largest(measure: Literal["auto", "city_population", "ghsl_population"] = "auto",
                   year: int = Query(2025, description="Rank the cities by their size this year"),
                   limit: int = Query(600, ge=10, le=3000)):
    """The world's largest cities with their population through the years (estimates and projections),
    their place and continent: for Cities > Largest cities (clusters by continent, or the map). measure
    auto takes the UN's agglomerations when loaded, else the GHSL urban centres."""
    if not _has_cities():
        return {"rows": [], "measure": None, "note": NO_CITIES}
    have = {r["indicator_id"]: r["n"] for r in rows("""SELECT indicator_id, count(DISTINCT city_id) AS n FROM city_series
        WHERE indicator_id IN ('city_population', 'ghsl_population') GROUP BY 1""")}
    if measure == "auto":
        measure = max(have, key=lambda k: (have[k] >= 100, k == "city_population", have[k]), default="ghsl_population")
    if not have.get(measure):
        return {"rows": [], "measure": measure, "measures": have,
                "note": "No city sizes through the years yet: .\\refresh.bat loads the GHSL urban centres (Settings > Land)."}
    got = rows("""
        WITH pts AS (SELECT city_id, year(period_start) AS y, value AS v, status FROM city_series WHERE indicator_id = ?),
        rank_on AS (SELECT city_id, arg_min(v, abs(y - ?)) AS v FROM pts GROUP BY 1),
        top AS (SELECT city_id FROM rank_on ORDER BY v DESC LIMIT ?),
        cont AS (SELECT m.member_id, any_value(g.short_name) AS continent FROM memberships m JOIN entities g ON g.entity_id = m.group_id
                 WHERE g.type = 'continent' AND m.valid_to IS NULL GROUP BY 1)
        SELECT c.city_id, c.name, c.country_id, e.short_name AS country, c.lat, c.lon, cont.continent,
               list(struct_pack(y := p.y, v := p.v, p := p.status = 'P') ORDER BY p.y) AS pts
        FROM top JOIN cities c USING (city_id) LEFT JOIN entities e ON e.entity_id = c.country_id
        LEFT JOIN cont ON cont.member_id = c.country_id JOIN pts p ON p.city_id = c.city_id
        GROUP BY ALL""", [measure, year, limit])
    for r in got:
        r["pts"] = [[p["y"], round(p["v"]), bool(p["p"])] for p in r["pts"]]
    years = sorted({p[0] for r in got for p in r["pts"]})
    first_proj = min((p[0] for r in got for p in r["pts"] if p[2]), default=None)
    return {"rows": got, "measure": measure, "source": LARGEST_MEASURES[measure], "measures": have,
            "years": years, "first_projection": first_proj, "note": None}


def _city(city_id: str) -> dict:
    if not _has_cities():
        raise HTTPException(404, NO_CITIES)
    found = rows(f"""SELECT {CITY_COLS}, c.ascii_name, c.timezone, c.elevation, c.feature_code
                     FROM cities c LEFT JOIN entities e ON e.entity_id = c.country_id WHERE c.city_id = ?""", [city_id])
    if not found:
        raise HTTPException(404, f"no city {city_id}")
    return found[0]


@api.get("/city-indicators")
def city_indicators():
    return [{"indicator_id": k, "name": v[0], "unit": v[1], "decimals": v[2], "description": v[3], "source_id": v[4]}
            for k, v in CITY_INDICATORS.items()]


@api.get("/cities/{city_id}")
def city(city_id: str):
    """One city: its facts, every figure kept about it by indicator, and the country's other big cities."""
    c = _city(city_id)
    data = rows("""SELECT s.indicator_id, year(s.period_start) AS year, s.value, s.status, s.source_id, s.source_name,
                          src.short_name AS source
                   FROM city_series s LEFT JOIN sources src USING (source_id)
                   WHERE s.city_id = ? ORDER BY s.indicator_id, s.period_start""", [city_id])
    series: dict[str, dict] = {}
    for r in data:
        meta = CITY_INDICATORS.get(r["indicator_id"], (r["indicator_id"], "", 1, "", r["source_id"]))
        one = series.setdefault(r["indicator_id"], {
            "indicator_id": r["indicator_id"], "name": meta[0], "unit": meta[1], "decimals": meta[2],
            "description": meta[3], "source": r["source"] or r["source_id"], "source_name": r["source_name"], "points": []})
        one["points"].append({"year": r["year"], "value": r["value"], "status": r["status"]})
    others = cities(country=c["country_id"], limit=12)["rows"]
    return {"city": c, "series": list(series.values()),
            "others": [o for o in others if o["city_id"] != city_id][:10],
            "places": places(kind=None, country=None, city=city_id, q=None, limit=60)["rows"]}


PLACE_KINDS = Literal["transit", "university", "company"]
NO_PLACES = "No metro, universities or companies yet: run .\\refresh.bat (Wikidata places, once every four weeks)."


def _has_places() -> bool:
    return bool(rows("SELECT 1 FROM information_schema.tables WHERE table_name = 'places' AND table_schema = 'main'"))


@api.get("/places")
def places(kind: PLACE_KINDS | None = None, country: str | None = Query(None, description="Comma-separated country ids"),
           city: str | None = None, q: str | None = None, limit: int = Query(200, ge=1, le=5000)):
    """Metro and rail systems, universities and big companies (Wikidata), biggest first: by
    riders (else length), students, or revenue in US dollars. Each with its city where matched."""
    if not _has_places():
        return {"rows": [], "note": NO_PLACES}
    where, params = ["1 = 1"], []
    if kind:
        where.append("p.kind = ?")
        params.append(kind)
    if ids := split(country):
        where.append(f"p.country_id IN ({', '.join('?' * len(ids))})")
        params += ids
    if city:
        where.append("p.city_id = ?")
        params.append(city)
    if q:
        where.append("p.name ILIKE ?")
        params.append(f"%{q}%")
    city_join = ("LEFT JOIN cities c ON c.city_id = p.city_id" if _has_cities()
                 else "LEFT JOIN (SELECT NULL::VARCHAR AS city_id, NULL::VARCHAR AS name) c ON false")
    found = rows(f"""SELECT p.place_id, p.kind, p.subkind, p.name, p.country_id, e.short_name AS country, p.city_id,
                            coalesce(c.name, p.city_name) AS city, p.lat, p.lon, p.founded, p.url, p.facts, p.size
                     FROM places p LEFT JOIN entities e ON e.entity_id = p.country_id {city_join}
                     WHERE {' AND '.join(where)} ORDER BY p.size DESC NULLS LAST, p.name LIMIT ?""", [*params, limit])
    for r in found:
        r["facts"] = json.loads(r["facts"] or "{}")
        r["founded"] = str(r["founded"])[:4] if r["founded"] else None
    return {"rows": found, "note": None}


@api.get("/cities/{city_id}/wikipedia")
def city_wikipedia(city_id: str, fetch: bool = True):
    """The Wikipedia introduction and pictures for a city (its own daily limit in Settings)."""
    c = _city(city_id)
    target = {"name": c["name"], "type": "city", "search": f"{c['name']} {c['country'] or ''}".strip()}
    res = wiki.page(city_id, target, fetch, kind="cities")
    return {**res, "page": _with_image_urls(res["page"])}


def _numbeo_answer(kind: str, item_id: str, name: str) -> dict:
    return {"name": name, "prices": numbeo.cached(kind, item_id), "budget": numbeo.budget()}


@api.get("/cities/{city_id}/numbeo")
def city_numbeo(city_id: str):
    """Numbeo prices fetched earlier for this city, and today's fetches against the limit."""
    c = _city(city_id)
    return _numbeo_answer("cities", city_id, numbeo.city_name(c["name"], c["country_id"], c["admin1"]))


@api.post("/cities/{city_id}/numbeo")
def fetch_city_numbeo(city_id: str, name: str | None = Body(None, embed=True, max_length=120)):
    """Fetch this city's Numbeo prices page now (one of today's Numbeo fetches). name is
    Numbeo's name for the city when it differs from ours."""
    c = _city(city_id)
    city_name = name or numbeo.city_name(c["name"], c["country_id"], c["admin1"])
    try:
        numbeo.fetch("cities", city_id, c["country"] or c["country_id"], city_name)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _numbeo_answer("cities", city_id, city_name)


def _country(entity_id: str) -> dict:
    found = rows("SELECT entity_id, short_name FROM entities WHERE entity_id = ? AND type = 'country'", [entity_id])
    if not found:
        raise HTTPException(404, f"no country {entity_id}")
    return found[0]


@api.get("/numbeo/compare")
def numbeo_compare(year: int | None = Query(None, description="The pages kept for this year (default: the latest of each)"),
                   since: int | None = Query(None, description="Also give each place's prices from this year, to show the change")):
    """Every Numbeo price page fetched so far, side by side: one column per city or country,
    one row per item (US dollars), with each page's name and date. Each fetch is kept under
    its year, so years can be compared."""
    pages = numbeo.all_cached(year)
    before = {(p["kind"], p["id"]): p for p in numbeo.all_cached(since)} if since else {}
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
    city_names = {}
    if _has_cities():
        ids = [p["id"] for p in pages if p.get("kind") == "cities"]
        if ids:
            city_names = {r["city_id"]: r for r in rows(
                "SELECT c.city_id, c.name, c.country_id FROM cities c WHERE c.city_id IN (SELECT unnest(?))", [ids])}
    places, order, sections = [], [], {}
    for p in pages:
        if p.get("kind") == "cities":
            c = city_names.get(p["id"])
            label = f"{c['name']}, {names.get(c['country_id'], c['country_id'])}" if c else (p.get("city") or p["id"])
            country = c["country_id"] if c else None
        else:
            label, country = names.get(p["id"], p.get("country") or p["id"]), p["id"]
        places.append({"kind": p["kind"], "id": p["id"], "name": label, "country_id": country, "url": p.get("url"),
                       "fetched_at": p.get("fetched_at"), "summary": p.get("summary") or {},
                       "values": {it["item"]: it["value"] for it in p["items"]},
                       "before": ({it["item"]: it["value"] for it in b["items"]} if (b := before.get((p["kind"], p["id"]))) else None),
                       "before_fetched_at": b.get("fetched_at") if b else None})
        for it in p["items"]:
            if it["item"] not in sections:
                sections[it["item"]] = it["section"]
                order.append(it["item"])
    return {"places": places, "items": [{"item": i, "section": sections[i]} for i in order], "years": numbeo.years(),
            "year": year, "since": since}


@api.get("/entities/{entity_id}/numbeo")
def country_numbeo(entity_id: str):
    return _numbeo_answer("countries", entity_id, _country(entity_id)["short_name"])


@api.post("/entities/{entity_id}/numbeo")
def fetch_country_numbeo(entity_id: str, name: str | None = Body(None, embed=True, max_length=120)):
    """Fetch the country's Numbeo prices page now (one of today's Numbeo fetches)."""
    country = name or _country(entity_id)["short_name"]
    try:
        numbeo.fetch("countries", entity_id, country, None)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _numbeo_answer("countries", entity_id, country)


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


# ----------------------------------------------------------------------------- Discover
_d_cache: dict = {"build": None, "finds": []}


def _finds() -> list[dict]:
    """The finds for the live build: the pipeline's saved copy, else worked out here once and saved."""
    build = _build_id()
    if _d_cache["build"] != build:
        saved = discover.load_saved(local.home(), build, exact=True)
        if saved is None:
            found = discover.compute(cursor(), local.home(), userdata.settings())
            try:
                discover.save(local.home(), build, found)
            except OSError:
                pass
        else:
            found = saved.get("finds", [])
        _d_cache.update(build=build, finds=found)
    return _d_cache["finds"]


def _news_names() -> "news.Names":
    return news.Names(cursor().execute("SELECT entity_id, short_name FROM entities WHERE type = 'country' AND short_name IS NOT NULL").fetchall())


def _stamp_first_seen(items: list[dict], st: dict) -> None:
    """The first time each find was listed, for "New since your last visit"."""
    now_ = userdata.now()
    fresh = {f["key"]: now_ for f in items if f["key"] not in st["first_seen"]}
    if fresh:
        st["first_seen"].update(fresh)
        if len(st["first_seen"]) > 50_000:  # keep the newest
            st["first_seen"] = dict(sorted(st["first_seen"].items(), key=lambda kv: kv[1])[-40_000:])
        discover.save_user_state(st)


def _when(f: dict) -> tuple[str, str]:
    """The days a find or news item covers, as ISO dates: a news item's day, a find's years."""
    if f.get("date"):
        return f["date"], f["date"]
    ys = [y for y in (f.get("years") or []) if y]
    return (f"{min(ys)}-01-01", f"{max(ys)}-12-31") if ys else ("", "")


@api.get("/discover")
def discover_list(tab: str = Query("finds", pattern="^(finds|interesting|hidden|news)$"), category: str | None = None,
                  kind: str | None = None, tone: str | None = None, entity: str | None = None, tag: str | None = None,
                  q: str | None = None, sort: str = Query("score", pattern="^(score|newest|key)$"), new: bool = False,
                  since: str | None = Query(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$"), until: str | None = Query(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$"),
                  limit: int = Query(60, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Interesting finds on the live build (and news), scored for you. Tabs: finds (all but the
    ones you hid), interesting (the ones you marked), hidden (marked Not interesting, or a kind
    you never want), news. Filters by category, kind, tone, country, tag, words and dates
    (since/until: a news item's day, or the years a find covers)."""
    s = userdata.settings()
    st = discover.user_state()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    finds = _finds() if tab != "news" else []
    pool = finds + (news.items() if tab in ("news", "interesting", "hidden") else [])
    _stamp_first_seen(pool, st)
    ranked = discover.ranked(pool, st, keys, float(s.get("discover_key_boost", 1.5)), bool(s.get("discover_tune", True)))
    if tab == "news":
        ranked = [f for f in ranked if f["kind"] == "news" and f["rating"] >= 0]
    elif tab == "interesting":
        ranked = [f for f in ranked if f["rating"] > 0]
    elif tab == "hidden":
        ranked = [f for f in ranked if f["rating"] < 0 or f["never"]]
    else:
        ranked = [f for f in ranked if f["rating"] >= 0 and not f["never"] and f["kind"] != "news"]
    last = st.get("last_visit")
    for f in ranked:
        f["new"] = bool(last and f.get("first_seen") and f["first_seen"] > last)
    facets = {"categories": {}, "kinds": {}, "tones": {}, "entities": {}, "tags": {}}
    words = [w for w in (q or "").lower().split() if w]

    def keep(f: dict) -> bool:
        if category and f["category"] != category or kind and f["kind"] != kind or tone and f["tone"] != tone:
            return False
        if entity and entity not in f.get("entities", []) or tag and tag not in f.get("tags", []) or new and not f["new"]:
            return False
        if since or until:
            first, last_ = _when(f)
            if not first or since and last_ < since[:10] or until and first[: len(until)] > until:
                return False
        hay = f"{f['headline']} {f.get('detail', '')} {' '.join(f.get('tags', []))}".lower()
        return all(w in hay for w in words)

    shown = [f for f in ranked if keep(f)]
    for f in ranked:  # counts across the tab, so a filter can be changed without losing the others
        for k, v in (("categories", f["category"]), ("kinds", f["kind"]), ("tones", f["tone"])):
            facets[k][v] = facets[k].get(v, 0) + 1
        for e in f.get("entities", []):
            facets["entities"][e] = facets["entities"].get(e, 0) + 1
        for t in f.get("tags", []):
            facets["tags"][t] = facets["tags"].get(t, 0) + 1
    facets["tags"] = dict(sorted(facets["tags"].items(), key=lambda kv: -kv[1])[:60])
    if sort == "newest":
        shown.sort(key=lambda f: (f.get("first_seen") or "", f.get("date") or str((f.get("years") or [0])[-1])), reverse=True)
    elif sort == "key":
        order = {k: i for i, k in enumerate(keys)}
        shown.sort(key=lambda f: (min((order.get(e, 99) for e in f.get("entities", [])), default=99), -f["rank_score"]))
    names = dict(cursor().execute("SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))",
                                  [list(facets["entities"])]).fetchall())
    st_news = news.state()
    return {"items": shown[offset: offset + limit], "total": len(shown), "facets": facets, "names": names,
            "build_id": _build_id(), "last_visit": last, "new_count": sum(1 for f in ranked if f["new"]),
            "kinds": {**discover.KINDS, "news": "News"}, "categories": discover.CATEGORIES, "never": st["never"],
            "news": {"on": bool(s.get("news_on", True)), "running": st_news["running"], "finished_at": st_news.get("finished_at"),
                     "errors": st_news["errors"], "last": st_news["last"], "due": news.is_due(s, st_news)}}


def _discover_find(key: str) -> dict | None:
    for f in _finds():
        if f["key"] == key:
            return f
    return next((i for i in news.items() if i["key"] == key), None)


@api.put("/discover/{key:path}")
def discover_mark(key: str, change: dict = Body(...)):
    """Your mark on one find: rating 1 (Interesting), -1 (Not interesting) or 0; tags (your own);
    tone ("good", "bad", "neutral", or null for the app's own)."""
    st = discover.user_state()
    f = _discover_find(key) or st["kept"].get(key)
    if f is None:
        raise HTTPException(404, f"no find {key}")
    if "rating" in change:
        r = int(change["rating"] or 0)
        if r not in (-1, 0, 1):
            raise HTTPException(422, "rating is 1, -1 or 0")
        if r:
            st["ratings"][key] = r
        else:
            st["ratings"].pop(key, None)
        if r > 0:
            st["kept"][key] = {k: v for k, v in f.items() if k not in ("stale", "rating", "rank_score", "new")}
        else:
            st["kept"].pop(key, None)
    if "tags" in change:
        tags = ai.clean_tags(change.get("tags"))
        if tags:
            st["tags"][key] = tags
        else:
            st["tags"].pop(key, None)
    if "tone" in change:
        t = change.get("tone")
        if t in discover.TONES:
            st["tones"][key] = t
        elif t is None:
            st["tones"].pop(key, None)
        else:
            raise HTTPException(422, "tone is good, bad, neutral or null")
    discover.save_user_state(st)
    return {"key": key, "rating": st["ratings"].get(key, 0), "my_tags": st["tags"].get(key, []), "tone": st["tones"].get(key, f["tone"])}


@api.put("/discover-never/{kind}")
def discover_never(kind: str, on: bool = Body(..., embed=True)):
    """Never show this kind of find (or show it again)."""
    if kind not in discover.KINDS and kind != "news":
        raise HTTPException(404, f"no kind {kind}")
    st = discover.user_state()
    st["never"] = sorted({*st["never"], kind} if on else set(st["never"]) - {kind})
    discover.save_user_state(st)
    return {"never": st["never"]}


@api.post("/discover-seen")
def discover_seen():
    """Mark the feed as seen now: later finds are "new since your last visit"."""
    st = discover.user_state()
    st["last_visit"] = userdata.now()
    discover.save_user_state(st)
    return {"last_visit": st["last_visit"]}


@api.get("/discover-entity/{entity_id}")
def discover_entity(entity_id: str, limit: int = Query(5, ge=1, le=50)):
    """A country's top finds, for the Discover card on its page."""
    s = userdata.settings()
    st = discover.user_state()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    mine = [f for f in _finds() if entity_id in f.get("entities", [])]
    ranked = [f for f in discover.ranked(mine, st, keys, float(s.get("discover_key_boost", 1.5)), bool(s.get("discover_tune", True)))
              if f["rating"] >= 0 and not f["never"] and entity_id in f.get("entities", [])]
    # One find per kind of change on one measure: a record in population, male population
    # and female population is one find on the card, not three.
    seen: set[tuple] = set()
    items = []
    for f in ranked:
        fam = (f.get("kind"), re.sub(r"_(total|male|female|men|women)$", "", f.get("indicator_id") or f.get("key", "")))
        if fam in seen:
            continue
        seen.add(fam)
        items.append(f)
    return {"items": items[:limit], "total": len(items)}


@api.post("/news/fetch")
def news_fetch(force: bool = False):
    """Fetch major news in the background (when due, or now with force); see GET /discover?tab=news."""
    s = userdata.settings()
    if not s.get("news_on", True):
        raise HTTPException(409, "News is switched off (Settings: Discover).")
    if not force and not news.is_due(s):
        return {"started": False, "why": "fetched recently", **news.state()}
    return {"started": news.start(s, _news_names()), **news.state()}


@api.post("/discover-rescan")
def discover_rescan():
    """Work the finds out again on the live build (after changing Discover's settings)."""
    found = discover.compute(cursor(), local.home(), userdata.settings())
    discover.save(local.home(), _build_id(), found)
    _d_cache.update(build=_build_id(), finds=found)
    return {"finds": len(found)}


# ----------------------------------------------------------------------------- Briefing, map events, watch words
def _has_table(name: str) -> bool:
    return bool(rows("SELECT 1 FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'", [name]))


def _city_index(entities: list[str]) -> dict[str, list[tuple[str, float, float]]]:
    """Cities of 100,000 people or more in these countries, biggest first, for placing news on the map."""
    if not entities or not _has_cities():
        return {}
    out: dict[str, list[tuple[str, float, float]]] = {}
    for r in rows("""SELECT country_id, name, lat, lon FROM cities WHERE population >= 100000
            AND country_id IN (SELECT unnest(?)) ORDER BY population DESC""", [sorted(set(entities))]):
        out.setdefault(r["country_id"], []).append((r["name"], r["lat"], r["lon"]))
    return out


def _starting(lo: str, hi: str, entity: str | None = None, quiet: bool = False) -> list[dict]:
    """Events that start between two days (not the long worked-out episodes, unless quiet)."""
    where = ["e.start_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"]
    params: list = [lo, hi]
    if not quiet:
        where.append("e.kind NOT IN (SELECT unnest(?))")
        params.append(sorted(briefing.QUIET_KINDS))
    if entity:
        where.append("e.entity_id = ?")
        params.append(entity)
    found = rows(f"""SELECT {', '.join('e.' + c for c in EVENT_COLUMNS)}, n.short_name AS entity_name FROM events e
        LEFT JOIN entities n USING (entity_id) WHERE {' AND '.join(where)} ORDER BY e.start_date DESC LIMIT 3000""", params)
    for r in found:
        for k in ("start_date", "end_date"):
            r[k] = r[k].isoformat() if r[k] else None
        r["group"] = briefing.KIND_GROUP.get(r["kind"], "other")
    return found


def _watch(lo: str, hi: str, entity: str | None = None) -> list[dict]:
    s = userdata.settings()
    ws = briefing.words(s.get("news_watch_words", ""))
    items = [i for i in news.items() if entity is None or entity in (i.get("entities") or [])]
    ents = sorted({e for i in items for e in (i.get("entities") or [])[:1]})
    confirm = rows("""SELECT entity_id, kind, start_date, title FROM events WHERE start_date BETWEEN
        CAST(? AS DATE) - INTERVAL 3 DAY AND CAST(? AS DATE) + INTERVAL 3 DAY""", [lo, hi])
    return briefing.watch_hits(items, ws, lo, until=hi, min_outlets=int(s.get("news_watch_outlets", 1)),
                               cities=_city_index(ents), confirm=confirm)


@api.get("/map-events")
def map_events(start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """What happened between two days, for the map's Events and News layers: dated events that start in the
    window (placed on their country), and news that names a watch word (placed on a city it names, else
    its country; confirmed once a dataset holds a matching event). Earthquakes and storm tracks are map
    layers of their own (GET /layers), filtered to the same window by the app."""
    if start > end:
        raise HTTPException(422, "start is after end")
    return {"start": start, "end": end, "events": _starting(start, end), "watch": _watch(start, end),
            "words": briefing.words(userdata.settings().get("news_watch_words", ""))}


def _cw_latest() -> tuple[str | None, list[dict]]:
    found = crisiswatch(None) if _has_table("events") else {"month": None, "rows": []}
    return found["month"], found["rows"]


def _briefing_predict(s: dict, keys: list[str], days: int) -> tuple[list[dict], list[dict]]:
    """The Briefing's prediction cards: big crowd moves and watchlist alerts for Happening; followed
    crowd questions closing and your predictions coming due for Due. Never breaks the page."""
    happening: list[dict] = []
    due: list[dict] = []
    try:
        f = crowd_terms.load_follow()
        h, d = crowd.briefing_cards(rows, briefing.card, key_countries=keys, follow=f["follow"], hide=f["hide"],
                                    min_points=float(s.get("crowd_move_points", 10)), days=min(days, 30))
        happening += h
        due += d
    except Exception:  # noqa: BLE001
        pass
    try:
        if s.get("watchlist_on", True):
            for w in predictions.check_watch(rows, s.get("crowd_move_points", 10)):
                if w.get("alert"):
                    happening.append(briefing.card("feed", f"watch:{w['id']}", w.get("title") or w.get("note") or
                                                   f"{w.get('indicator')} in {w.get('entity')}",
                                                   detail=w.get("text") or "", day=w.get("date"), group="alert",
                                                   entities=[w["entity"]] if w.get("entity") else [], source="Your watchlist",
                                                   href="/predictions?tab=watchlist", tone="neutral"))
        for p in predictions.due_soon(30):
            due.append(briefing.card("due", f"pred:{p['id']}", p["question"], detail=f"Your log: {p.get('who') or 'You'}",
                                     day=p["due"], entities=[p["entity"]] if p.get("entity") else [], source="Predictions",
                                     href="/predictions", group="prediction"))
    except Exception:  # noqa: BLE001
        pass
    return happening, due


@api.get("/briefing")
def briefing_page(days: int | None = Query(None, ge=1, le=90)):
    """Everything new in four lanes, each a list of the shared card: happening (CrisisWatch's month,
    news that names a watch word, events of the last days, top news), found (Discover's best finds),
    due (events coming up in the next 60 days) and yours (what you kept lately)."""
    s = userdata.settings()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    days = days or int(s.get("briefing_days", 7))
    lo, hi = briefing.window(days)
    month, cw = _cw_latest()
    feed = discover_list(tab="finds", category=None, kind=None, tone=None, entity=None, tag=None, q=None, sort="score",
                         new=False, since=None, until=None, limit=12, offset=0)
    finds = sorted(feed["items"], key=lambda f: (not f.get("new"), -f.get("rank_score", 0)))
    ahead = (date.today() + timedelta(days=60)).isoformat()
    due = [e for e in _starting((date.today() + timedelta(days=1)).isoformat(), ahead)
           if e["kind"] in ("election", "sport", "summit", "court", "un", "treaty") or e["entity_id"] in keys]
    hl = highlights.search()
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
    p_happening, p_due = _briefing_predict(s, keys, days)
    return {
        "days": days, "since": lo, "build_id": _build_id(), "crisiswatch_month": month, "key_countries": keys, "names": names,
        "news_due": bool(s.get("news_on", True)) and news.is_due(s),
        "lanes": {
            "happening": [*briefing.crisiswatch_cards(cw, month, keys), *briefing.watch_cards(_watch(lo, hi)),
                          *briefing.event_cards(_starting(lo, hi)), *briefing.news_cards(news.items(), lo, 8), *p_happening],
            "found": briefing.find_cards(finds, 8),
            "due": [*briefing.event_cards(due, due=True)[:20], *p_due],
            "yours": briefing.yours_cards(hl, 6),
        },
    }


@api.get("/entities/{entity_id}/latest")
def entity_latest(entity_id: str, days: int = Query(30, ge=1, le=365)):
    """The "Latest on" strip of a country page: its CrisisWatch rating this month (and last), news that names
    a watch word, events of the last days, top news and its best Discover finds, as shared cards."""
    lo, hi = briefing.window(days)
    cw = None
    if _has_table("events"):
        got = rows("""SELECT strftime(start_date, '%Y-%m') AS month, subkind, detail, place, url FROM events
            WHERE kind = 'crisiswatch' AND entity_id = ? ORDER BY start_date DESC LIMIT 2""", [entity_id])
        if got:
            cw = {**got[0], "label": briefing.CW_WORDS.get(got[0]["subkind"] or "", got[0]["subkind"]),
                  "previous": got[1]["subkind"] if len(got) > 1 else None}
    # Finds about this country itself, not ones where it is one of a hundred countries setting a record.
    finds = [f for f in discover_entity(entity_id, limit=30)["items"] if entity_id in (f.get("entities") or []) and len(f.get("entities") or []) <= 3]
    cards = [*briefing.watch_cards(_watch(lo, hi, entity_id)), *briefing.event_cards(_starting(lo, hi, entity_id)),
             *briefing.news_cards(news.items(), lo, 5, entity_id), *briefing.find_cards(finds, 3)]
    ids = sorted({e for c in cards for e in c["entities"][:3]} | {entity_id})
    names = {r["entity_id"]: r["short_name"] for r in rows(
        "SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [ids])}
    return {"entity_id": entity_id, "days": days, "crisiswatch": cw, "cards": cards, "names": names}

# ----------------------------------------------------------------------------- Long history
_lh_cache: dict[tuple, object] = {}


def _lh(key: tuple, make):
    """Answers that take a while (who ruled where, the factors), kept until the build changes."""
    k = (_build_id(), *key)
    if k not in _lh_cache:
        if len(_lh_cache) > 64:
            _lh_cache.clear()
        _lh_cache[k] = make()
    return _lh_cache[k]


def _lh_has(name: str) -> bool:
    return _has_table(name)


def _lh_power(power_id: str) -> None:
    if power_id not in catalogue.history_powers():
        raise HTTPException(404, f"no power {power_id}")


@api.get("/long")
def long_overview():
    """The Long history page's set-up: powers with their span and peak, China's dynasties, regions,
    series, the eight factors, the cycle's stages, voyages, and how much is loaded."""
    return _lh(("overview",), lambda: longhistory.overview(rows, _lh_has))


@api.get("/long/sizes")
def long_sizes(powers: str | None = None):
    """Land area over time for powers (comma-separated ids; default all), as steps."""
    ids = split(powers) or list(catalogue.history_powers())
    if not _lh_has("polities"):
        return []
    return _lh(("sizes", tuple(ids)), lambda: longhistory.sizes(rows, ids))


@api.get("/long/power/{power_id}")
def long_power(power_id: str):
    """One power's card: its shapes over time (frames), size, peak, events in its area and
    lifetime, and voyages it sponsored."""
    _lh_power(power_id)
    min_links = int(userdata.settings().get("history_event_min_links", 5))
    return _lh(("power", power_id, min_links), lambda: longhistory.power_card(rows, power_id, _lh_has, min_links))


@api.get("/long/shape/{key:path}")
def long_shape(key: str):
    """One state's borders for one stretch of years, as a GeoJSON feature."""
    f = longhistory.shape(rows, key) if _lh_has("polities") else None
    if f is None:
        raise HTTPException(404, f"no shape {key}")
    return Response(json.dumps(f, separators=(",", ":")), media_type="application/json",
                    headers={"Cache-Control": "max-age=86400"})


@api.get("/long/power/{power_id}/expansion")
def long_expansion(power_id: str, most: int = Query(24, ge=2, le=60)):
    """A power's shapes over its life, oldest on top, for the expansion view."""
    _lh_power(power_id)
    if not _lh_has("polities"):
        return {"type": "FeatureCollection", "features": []}
    return _lh(("expansion", power_id, most), lambda: longhistory.expansion(rows, power_id, most))


@api.get("/long/world")
def long_world(year: int = Query(..., ge=longhistory.FIRST_YEAR, le=longhistory.LAST_YEAR), geometry: bool = True):
    """Every state alive in a year, named by the empire it belonged to (the World in year map).
    geometry=false gives the properties only; get the shapes with POST /long/shapes."""
    if not _lh_has("polities"):
        return {"type": "FeatureCollection", "features": [], "year": year}
    data = json.dumps(longhistory.world(rows, year, geometry), separators=(",", ":"))
    return Response(data, media_type="application/json")


@api.post("/long/shapes")
def long_shapes(keys: list[str] = Body(..., embed=True)):
    """Borders for several states at once, by key (at most 2,000)."""
    if not _lh_has("polities"):
        return {}
    return Response(json.dumps(longhistory.shapes(rows, keys[:2000]), separators=(",", ":")), media_type="application/json")


@api.get("/long/ruled")
def long_ruled(step: int = Query(10, ge=5, le=100)):
    """For each region, who held the most land there, period by period."""
    if not _lh_has("polities"):
        return {"step": step, "regions": []}
    return _lh(("ruled", step), lambda: longhistory.ruled(rows, step))


@api.get("/long/series")
def long_series(entities: str = "world", series: str = "population", start: int | None = None, end: int | None = None):
    """Figures over centuries (history.yaml series) for entities, with source and unit."""
    if not _lh_has("long_series"):
        return []
    return longhistory.series(rows, split(entities), split(series), start, end)


@api.get("/long/regions")
def long_regions():
    """People in each of the eight regions (and the Pacific) over time."""
    if not _lh_has("long_series"):
        return []
    return _lh(("regions",), lambda: longhistory.regional_population(rows))


@api.get("/long/events")
def long_events(start: int | None = None, end: int | None = None, kind: str | None = None, min_links: int | None = None,
                region: str | None = None, entity: str | None = None, bbox: str | None = None,
                limit: int = Query(400, ge=1, le=5000)):
    """Events far back: wars, battles, epidemics, famines, treaties, earthquakes, eruptions,
    tsunamis. min_links defaults to the setting (Wikipedias with an article)."""
    if not _lh_has("history_events"):
        return []
    links = min_links if min_links is not None else int(userdata.settings().get("history_event_min_links", 5))
    box = None
    if bbox:
        try:
            w, s_, e, n = (float(x) for x in bbox.split(","))
            box = (w, s_, e, n)
        except ValueError:
            raise HTTPException(422, "bbox is west,south,east,north")
    return longhistory.events(rows, start, end, split(kind), links, box, region, entity, limit)


@api.get("/long/voyages")
def long_voyages(power: str | None = None):
    """Voyages of exploration as dated stops (rough: straight lines between them)."""
    return longhistory.voyages(power)


@api.get("/long/thenandnow")
def long_then_and_now(measure: Literal["output", "people", "land"] = "output", powers: str | None = None):
    """Each power's share of the world over time (output, people or land), with its peak."""
    ids = split(powers) or [p["id"] for p in catalogue.history()["powers"]]
    table = "polities" if measure == "land" else "long_series"
    if not _lh_has(table):
        return {"measure": measure, "name": longhistory.MEASURES[measure], "lines": [], "note": None}
    return _lh(("thenandnow", measure, tuple(ids)), lambda: longhistory.then_and_now(rows, measure, ids))


@api.get("/long/factors")
def long_factors(start: int = Query(1500, ge=-500, le=2000), step: int = Query(10, ge=1, le=50)):
    """The eight factors, rebuilt from free data, and their index."""
    if not _lh_has("long_series"):
        return {"countries": [], "years": [], "factors": [], "index": [], "note": None}
    return _lh(("factors", start, step), lambda: longhistory.factors(rows, start, step))


@api.get("/long/cycle")
def long_cycle(entities: str | None = None):
    """Where countries might be in the big cycle's six stages, with the reasons."""
    ids = split(entities) or catalogue.history()["cycle"]["countries"]
    return {"stages": catalogue.history()["cycle"]["stages"], "countries": longhistory.cycle(rows, ids, date.today().year)}


@api.get("/long/wikipedia/{power_id}")
def long_wikipedia(power_id: str, fetch: bool = True):
    """The Wikipedia introduction for an empire, dynasty or voyage (its own daily limit in Settings)."""
    p = catalogue.history_powers().get(power_id)
    v = next((v for v in catalogue.history()["voyages"] if v["id"] == power_id), None)
    if p is None and v is None:
        raise HTTPException(404, f"no power or voyage {power_id}")
    item = p or v
    target = {"name": item["name"], "type": "empire", "article": item.get("wikipedia") or item["name"]}
    res = wiki.page(f"long_{power_id}", target, fetch, kind="empires")
    return {**res, "page": _with_image_urls(res["page"])}


@api.get("/long/country/{entity_id}")
def long_country(entity_id: str):
    """A country's long view: its long-run figures, who ruled the place where its capital is,
    and the best-known events there."""
    names = rows("SELECT name FROM entities WHERE entity_id = ?", [entity_id])
    if not names:
        raise HTTPException(404, f"no entity {entity_id}")
    meta = catalogue.history()["series"]
    out = {"entity_id": entity_id, "name": names[0]["name"], "series": [], "capital": None, "ruled": [], "events": []}
    if _lh_has("long_series"):
        out["series"] = longhistory.series(rows, [entity_id], list(meta))
    if _lh_has("polities") and _has_cities():
        cap = rows("SELECT name, lat, lon FROM cities WHERE country_id = ? AND capital = 'national' "
                   "ORDER BY population DESC LIMIT 1", [entity_id])
        if cap:
            out["capital"] = cap[0]
            out["ruled"] = _lh(("ruled_here", entity_id), lambda: longhistory.ruled_here(rows, cap[0]["lat"], cap[0]["lon"]))
    if _lh_has("history_events"):
        links = int(userdata.settings().get("history_event_min_links", 5))
        out["events"] = longhistory.events(rows, None, None, None, links, None, None, entity_id, 30)
    return out


# ----------------------------------------------------------------------------- countries like this one, synthetic comparison
def _country_names() -> dict[str, str]:
    return {r["entity_id"]: r["name"] for r in rows("SELECT entity_id, name FROM entities")}


def _alike_indicators(preset: str | None, indicators: str | None) -> list[str]:
    from worldmodel_api import similar
    ids = split(indicators)
    if ids:
        return ids[:30]
    key = preset or "everything"
    if key not in similar.PRESETS:
        raise HTTPException(422, f"preset must be one of {', '.join(similar.PRESETS)}")
    return similar.PRESETS[key][1]


@api.get("/alike/presets")
def alike_presets():
    """The ready-made indicator sets for countries like this one."""
    from worldmodel_api import similar
    return [{"id": k, "name": n, "indicators": ids} for k, (n, ids) in similar.PRESETS.items()]


@api.get("/alike")
def alike(entity: str, preset: str | None = None, indicators: str | None = None, year: int | None = None,
          n: int = Query(10, ge=1, le=40), decades: bool = False):
    """The countries most like this one in a year, on the indicators of a preset (or the ones given):
    each indicator on one scale across countries (logged when it spans more than a hundredfold), then the
    average distance over the indicators both have. With `decades`, the five nearest every ten years."""
    from worldmodel_api import similar
    ids = _alike_indicators(preset, indicators)
    year = year or date.today().year - 2
    names = _country_names()
    out = similar.like(rows, names, entity, ids, year, n)
    out["indicator_names"] = {r["indicator_id"]: r["name"] for r in
                              rows("SELECT indicator_id, name FROM indicators WHERE indicator_id IN (SELECT unnest(?))", [ids])}
    if decades:
        out["decades"] = similar.like_by_decade(rows, names, entity, ids, list(range(1960, year + 1, 10)))
    return out


@api.get("/alike/move")
def alike_move(indicator: str = "gdp_growth", start: int = Query(1990, ge=1800), end: int | None = None,
               groups: int = Query(6, ge=2, le=12)):
    """Groups of countries whose yearly changes in one indicator go up and down together."""
    from worldmodel_api import similar
    end = end or date.today().year - 1
    if end - start < 12:
        raise HTTPException(422, "choose at least 12 years")
    return similar.move_alike(rows, _country_names(), indicator, start, end, groups)


@api.get("/synthetic")
def synthetic_view(entity: str, indicator: str, year: int, pool: str | None = None, start: int | None = None,
                   end: int | None = None, placebos: bool = True):
    """Synthetic comparison: the mix of other countries that tracked this one best before the event year,
    the gap after it, and placebo runs on the pool countries to say whether that gap is unusual."""
    from worldmodel_api import similar
    out = similar.synthetic(rows, _country_names(), entity, indicator, year, split(pool) or None, start, end, placebos)
    if "error" in out:
        raise HTTPException(422, out["error"])
    return out



# ----------------------------------------------------------------------------- weekly digest (Briefing > Week)
@api.get("/digest")
def digest_view(week: str | None = Query(None, pattern=r"^\d{4}-W\d{2}$", description="2026-W45; default the last whole week")):
    """One Monday-to-Sunday week: new figures, finds, crowd moves, predictions due and settled, CrisisWatch,
    events and news. Kept once the week is over (Settings: weekly digest); the week in progress is worked out each time."""
    from worldmodel_api import digest
    import sys
    try:
        return digest.get(sys.modules[__name__], week)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/digests")
def digests_list():
    """The weeks with a kept digest, newest first, and the last whole week and this one."""
    from worldmodel_api import digest
    return {"kept": digest.saved(), "last_complete": digest.last_complete(), "this_week": digest.week_id(date.today())}


# ----------------------------------------------------------------------------- Settings > API access
@api.get("/api-access")
def api_access(request: Request):
    """The public API's switch, keys (never the keys themselves) and recent calls."""
    s = userdata.settings()
    return {"on": bool(s.get("api_public_on")), "daily_limit": s.get("api_daily_limit"), "keys": public_api.key_list(),
            "recent": public_api.recent(40), "local": public_api.is_local(request), "mcp_command": public_api.mcp_command()}


@api.post("/api-access/keys")
def api_key_make(body: dict = Body(..., examples=[{"name": "Laptop"}])):
    """Make a key for another PC; the key is in this answer only, so copy it now."""
    return public_api.make_key(body.get("name", ""), body.get("daily_limit"))


@api.delete("/api-access/keys/{key_id}")
def api_key_revoke(key_id: str):
    if not public_api.revoke_key(key_id):
        raise HTTPException(404, "no such key")
    return {"ok": True}


@app.get("/health")
def health():
    try:
        o = warehouse.current()
        return {"ok": True, "warehouse": o.path.name, "build_id": o.meta.get("build_id")}
    except WarehouseError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})


app.include_router(api)
app.include_router(public_api.router)  # the public API (public.py), which reuses the calls above


def run() -> None:
    import uvicorn
    # The web app's proxy keeps connections open between requests; a server that closes
    # them first (uvicorn's default is after 5 idle seconds) makes the odd request fail
    # with a reset when the proxy reuses one just as it closes, so keep them open longer.
    uvicorn.run("worldmodel_api.main:app", host=os.environ.get("WORLDMODEL_API_HOST", "127.0.0.1"),
                port=int(os.environ.get("WORLDMODEL_API_PORT", "8000")), timeout_keep_alive=75)
