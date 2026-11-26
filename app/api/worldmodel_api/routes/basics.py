"""Build facts, entities, Factbook and Wikidata texts, Wikipedia pages and search."""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse

from worldmodel_contract import SCHEMA_VERSION
from worldmodel_api import core, userdata, wiki
from worldmodel_api import regions as region_tools
from worldmodel_api.core import API_VERSION, HEADLINE, api, rows, split


# ----------------------------------------------------------------------------- meta
@api.get("/meta")
def meta():
    o = core.warehouse.current()
    vintages = rows("SELECT source_id, vintage, release, retrieved_at, origin, is_latest FROM vintages "
                    "ORDER BY source_id, retrieved_at")
    return {"api_version": API_VERSION, "app_schema_version": SCHEMA_VERSION, "warehouse": o.path.name,
            "is_sample": core.warehouse.is_sample, **o.meta, "vintages": vintages}


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
            "successions": succession, "codes": codes, "as_of": on,
            "subdivision": region_tools.place(rows, entity_id) if found[0]["type"] == "subnational" else None}


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
