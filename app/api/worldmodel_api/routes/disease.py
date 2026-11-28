"""Disease outbreaks, flu and forecasts."""

from __future__ import annotations

from typing import Literal

from fastapi import Body, HTTPException, Query

from worldmodel_api import disease, disease_forecast, episodes, hazards, inventions, userdata
from worldmodel_api.core import api, rows, split
from worldmodel_api.routes.data import _series
from worldmodel_api.routes.events import EVENT_COLUMNS, _milestone_rows, _year_or_date


# ----------------------------------------------------------------------------- Disease
def _named(items: list[dict], key: str = "entity") -> list[dict]:
    ids = list({i[key] for i in items})
    if ids:
        names = {r["entity_id"]: r["name"] for r in rows(
            f"SELECT entity_id, coalesce(short_name, name) AS name FROM entities WHERE entity_id IN ({', '.join('?' * len(ids))})", ids)}
        for i in items:
            i["name"] = names.get(i[key], i[key])
    return items


@api.get("/disease/measures")
def disease_measures():
    """The diseases and weekly measures the Disease page offers, with how many places have each and its latest week."""
    return disease.measures(rows)


@api.get("/disease/seasons/{entity_id}")
def disease_seasons(entity_id: str, measure: str = "flu_pct_positive"):
    """A measure's weeks grouped into seasons, the normal range and how this season compares."""
    return disease.seasons_view(rows, entity_id, measure)


@api.get("/disease/heat/{entity_id}")
def disease_heat(entity_id: str, measure: str = "flu_pct_positive"):
    """Every season as a row of weeks, with the main flu strain each week."""
    return disease.heat_view(rows, entity_id, measure)


@api.get("/disease/now")
def disease_now(measure: str = "flu_pct_positive", entities: str | None = None):
    """The latest week of a measure for every country reporting, against its usual level for the week."""
    got = disease.now_view(rows, measure, split(entities) or None)
    _named(got["rows"])
    return got


@api.get("/disease/compare")
def disease_compare(measure: str = "flu_pct_positive", entities: str | None = None, years: int = 5):
    """A measure for several countries over the last few years, week by week."""
    got = disease.compare_view(rows, split(entities) or list(disease.D.KEY), measure, max(1, min(years, 30)))
    _named(got["series"])
    return got


@api.get("/disease/card/{entity_id}")
def disease_card(entity_id: str):
    """The country page's Disease now card."""
    return disease.card_view(rows, entity_id)


@api.get("/disease/long")
def disease_long(indicator: str = "measles_cases", entities: str | None = None):
    """Yearly case counts (per million people where that makes sense) for the long view, with pandemics."""
    got = disease.long_view(rows, split(entities) or list(disease.D.KEY), indicator)
    _named(got["series"])
    return got


@api.get("/disease/forecast/{entity_id}")
def disease_forecast_one(entity_id: str, measure: str = "flu_pct_positive"):
    """The forecast for a country's flu or RSV season under way (or the next one), the other hemisphere's
    signal it used, and how the same forecast did before each of the last five seasons."""
    return disease_forecast.forecast_view(rows, entity_id, measure)


@api.get("/disease/forecast-map")
def disease_forecast_map(measure: str = "flu_pct_positive"):
    """Every country's forecast peak for its season under way or next, against its usual peak."""
    return disease_forecast.forecast_map(rows, measure)


@api.get("/disease/notifiable")
def disease_notifiable():
    """New Zealand's notifiable diseases by year (PHF Science), latest year against the five before."""
    return disease.notifiable(rows)


@api.get("/disease/causes")
def disease_causes(entities: str | None = None):
    """Deaths per 100,000 by broad cause, age-standardised (WHO Mortality Database), for the countries given."""
    got = disease.causes(rows, (split(entities) or list(disease.D.KEY))[:8])
    _named(got["series"])
    return got


@api.get("/disease/outbreaks")
def disease_outbreaks(entities: str | None = None, limit: int = 60):
    """WHO Disease Outbreak News, newest first."""
    return disease.outbreaks(rows, split(entities) or None, max(1, min(limit, 500)))


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
    if (not kind_list or "episode" in kind_list) and (not src_list or "episodes" in src_list):
        enames = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
        for m in episodes.as_events(ents or None):
            if (lo and m["end_date"] < lo) or (hi and m["start_date"] > hi):
                continue
            if q and q.lower() not in f"{m['title']} {m['detail']}".lower():
                continue
            out.append({**m, "entity_name": enames.get(m["entity_id"], m["entity_id"])})
        out.sort(key=lambda r: (r["start_date"], r["entity_id"]))
    # Inventions only when asked for by kind: they are general, not news about a country.
    if kind_list and "invention" in kind_list and (not src_list or "inventions" in src_list):
        enames = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
        for m in inventions.as_events(ents or None):
            if (lo and m["start_date"] < lo) or (hi and m["start_date"] > hi):
                continue
            if q and q.lower() not in f"{m['title']} {m['detail']}".lower():
                continue
            out.append({**m, "entity_name": enames.get(m["entity_id"], m["entity_id"])})
        out.sort(key=lambda r: (r["start_date"], r["entity_id"]))
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
