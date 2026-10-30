"""Worldmodel API, on localhost. Serves the web app and any other local tool.

All endpoints are under /api/v1 and read the warehouse only. The only things
written are the user's own files (layouts, settings, indicator switches, history)
in a user folder beside the data (see layouts.py and userdata.py), Wikipedia pages
fetched on demand within the daily limits in Settings (media/wikipedia, see
wiki.py), and, when asked on the Data status page, old raw downloads deleted to
free space.
Interactive docs are at /docs when the server runs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from worldmodel_contract import SCHEMA_VERSION, catalogue
from worldmodel_contract.queries import SeriesQuery, divergence_sql, forecast_pairs_sql, series_sql, stream_query
from worldmodel_contract import cohort, local
from worldmodel_api import __version__, layouts, userdata, wiki
from worldmodel_api.warehouse import Warehouse, WarehouseError

load_dotenv()
API_VERSION = "1"
HEADLINE = ["pop_total", "pop_growth_rate", "tfr", "median_age", "life_expectancy", "pop_share_65_plus",
            "net_migration", "gdp_growth", "gdp_usd", "gdp_per_capita_usd", "inflation"]



@asynccontextmanager
async def lifespan(_app: FastAPI):
    background = wiki.Background(wiki_targets)
    background.start()
    yield
    background.close()


app = FastAPI(title="Worldmodel API", version=__version__, lifespan=lifespan,
              description="Local read-only API over the worldmodel warehouse.")
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
    return sorted(found, key=lambda r: order[r["indicator_id"]])


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
        # of the indicator's best-covered year (the very latest year often has only a few).
        main_year = {r["indicator_id"]: r["y"] for r in rows("""
            WITH n AS (
                SELECT s.indicator_id, year(s.period_start) AS y, count(DISTINCT s.entity_id) AS c
                FROM series s JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
                WHERE s.status = 'E' AND s.variant = 'central' AND s.breakdown = '' GROUP BY 1, 2)
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
        _whatif_inputs[key] = cohort.prepare(cursor().execute(cohort.inputs_sql(), [entity]).fetchall())
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
        WHERE entity_id = ? AND indicator_id = 'pop_total' AND source_id = 'un_wpp' AND variant <> 'central'
            AND freq = 'A'""", [entity])
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


@api.get("/problems")
def problems():
    """Each distinct failure in the refresh log, with how often it happened and whether it is still open."""
    return local.problems()


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
    compare: str = Query("world", description="An entity to compare with, or 'none'"),
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
    ents = sorted({e["entity_id"] for e in evs} | ({compare} if compare != "none" else set()))
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
        cmp = path(compare, y0) if compare != "none" else None
        diff = ([round(a - b, 4) if a is not None and b is not None else None for a, b in zip(own, cmp)]
                if cmp else None)
        out.append({"event_id": e["event_id"], "entity_id": e["entity_id"], "entity_name": e.get("entity_name"),
                    "title": e["title"], "kind": e["kind"], "subkind": e["subkind"], "year": y0,
                    "start_date": e["start_date"], "values": own, "compare": cmp, "diff": diff})

    def mean(key: str) -> list[float | None]:
        cols = [[r[key][i] for r in out if r[key] and r[key][i] is not None] for i in range(len(offsets))]
        return [round(sum(c) / len(c), 4) if c else None for c in cols]

    return {"indicator": ind[0], "mode": "index" if use_index else "value", "compare": compare, "offsets": offsets,
            "events": out, "mean": mean("values"), "mean_compare": mean("compare") if compare != "none" else None,
            "mean_diff": mean("diff") if compare != "none" else None, "n": len(out),
            "note": ("Index: the year before each event = 100." if use_index else f"Values in {unit}.")
            + (f" Compared with {compare} over the same years." if compare != "none" else "")}


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
    # The web app's proxy keeps connections open between requests; a server that closes
    # them first (uvicorn's default is after 5 idle seconds) makes the odd request fail
    # with a reset when the proxy reuses one just as it closes, so keep them open longer.
    uvicorn.run("worldmodel_api.main:app", host=os.environ.get("WORLDMODEL_API_HOST", "127.0.0.1"),
                port=int(os.environ.get("WORLDMODEL_API_PORT", "8000")), timeout_keep_alive=75)
