"""Long history: empires, rulers, the world in a year, big cycles."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Literal
from urllib.parse import unquote

from fastapi import Body, HTTPException, Query
from fastapi.responses import Response

from worldmodel_contract import catalogue
from worldmodel_api import cycles, episodes, inventions, longhistory, userdata, wiki
from worldmodel_api.core import _has_cities, _has_table, _lh, api, rows, split
from worldmodel_api.routes.basics import _with_image_urls


# ----------------------------------------------------------------------------- Long history




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
    lifetime, voyages it sponsored and its best-known rulers."""
    _lh_power(power_id)
    min_links = int(userdata.settings().get("history_event_min_links", 5))
    idx = _lh_rulers() if _lh_has("history_rulers") else None
    return _lh(("power", power_id, min_links), lambda: longhistory.power_card(rows, power_id, _lh_has, min_links, idx))


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
    idx = _lh_rulers() if _lh_has("history_rulers") else None
    data = json.dumps(longhistory.world(rows, year, geometry, idx), separators=(",", ":"))
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
    tsunamis, and things begun: famous buildings, cities founded, religions, writing and
    languages. min_links defaults to the setting (Wikipedias with an article)."""
    links = min_links if min_links is not None else int(userdata.settings().get("history_event_min_links", 5))
    box = None
    if bbox:
        try:
            w, s_, e, n = (float(x) for x in bbox.split(","))
            box = (w, s_, e, n)
        except ValueError:
            raise HTTPException(422, "bbox is west,south,east,north")
    return longhistory.events(rows, start, end, split(kind), links, box, region, entity, limit,
                              has_table=_lh_has("history_events"))


def _lh_rulers() -> dict:
    return _lh(("ruler_index",), lambda: longhistory.ruler_index(rows, _lh_has))


@api.get("/long/rulers")
def long_rulers(year: int = Query(..., ge=longhistory.FIRST_YEAR, le=longhistory.LAST_YEAR), most: int = Query(6, ge=1, le=30),
                states: str | None = None):
    """The rulers of the biggest states alive in a year (and of any states named), from
    Wikidata, for the strip under the World-in-year map."""
    if not _lh_has("polities") or not _lh_has("history_rulers"):
        return []
    return longhistory.rulers_in(rows, _lh_rulers(), year, most, split(states))


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


@api.get("/long/arcs")
def long_arcs(start: int = Query(1500, ge=1000, le=1900)):
    """Big cycles: each power's eight-factor index split into rise, top and decline, with crises and big wars."""
    if not _lh_has("long_series"):
        return {"lines": [], "note": None, "how": None}
    return _lh(("arcs", start), lambda: cycles.arcs(rows, start))


@api.get("/long/stages")
def long_stages(entities: str | None = None, start: int = Query(1950, ge=1900, le=2020)):
    """Big cycles: the cycle's stage decade by decade, by the same rules as today's placing."""
    ids = split(entities) or catalogue.history()["cycle"]["countries"]
    return _lh(("stages", tuple(ids), start), lambda: cycles.stages_over_time(rows, ids, start, date.today().year))


@api.get("/cycles/debt/{entity_id}")
def cycles_debt(entity_id: str):
    """The long-term debt cycle for one country: government debt since 1800, crises, wars, real rates."""
    return cycles.debt_cycle(rows, entity_id, date.today().year)


@api.get("/cycles/clock")
def cycles_clock(entities: str | None = None):
    """The short-term debt cycle clock: each country's phase from its latest figures, with the reasons."""
    ids = split(entities) or list(episodes.KEY)
    return cycles.clock(rows, ids, date.today().year)


@api.get("/cycles/short/{entity_id}")
def cycles_short(entity_id: str, start: int = Query(1960, ge=1900, le=2020)):
    """The short-term debt cycle over time: growth, private credit, the central bank rate and recessions."""
    return cycles.short_cycle(rows, entity_id, start, date.today().year)


@api.get("/episodes")
def episodes_list():
    """The typed-in big episodes, newest first, with how far output fell in the worst-hit country."""
    return _lh(("episodes",), lambda: episodes.listing(rows, date.today().year))


@api.get("/inventions")
def inventions_list():
    """Inventions over time: the typed-in list with categories, the series their cards chart, and
    extra inventions from Wikidata."""
    return _lh(("inventions",), lambda: inventions.listing(rows))


@api.get("/inventions/along")
def inventions_along(series: str, entities: str | None = None, categories: str | None = None):
    """One series (an indicator id or long:<id>) with the typed-in inventions along it."""
    return inventions.along(rows, series, split(entities) or None, split(categories) or None)


@api.get("/inventions/future")
def inventions_future():
    """Expected inventions: year ranges from named sources, what might follow, and matching
    crowd forecasts where they are loaded."""
    return inventions.future_listing(rows, date.today().year)


@api.get("/inventions/future/{future_id}")
def invention_future_card(future_id: str, entities: str | None = None):
    """One expected invention: its range and sources, what it might lead to, the crowd's view
    and today's figures for the things it might change."""
    got = inventions.future_card(rows, future_id, date.today().year, split(entities) or None)
    if got is None:
        raise HTTPException(404, f"no expected invention {future_id}")
    return got


@api.get("/inventions/{invention_id}")
def invention_card(invention_id: str, entities: str | None = None):
    """One invention: what, when and where, how it spread and the changes seen around it."""
    got = inventions.card(rows, invention_id, split(entities) or None)
    if got is None:
        raise HTTPException(404, f"no invention {invention_id}")
    return got


@api.get("/episodes/found")
def episodes_found(entity: str | None = None, kinds: str | None = None, limit: int = Query(600, ge=1, le=5000)):
    """Recessions, booms, inflation spikes, debt surges and crises the app finds in the data, and the years
    when many countries were hit together."""
    if not _has_table("events"):
        return {"events": [], "waves": [], "note": "No events loaded yet (run .\\refresh.bat)."}
    return episodes.found(rows, entity, split(kinds), limit)


@api.get("/episodes/{episode_id}")
def episode_page(episode_id: str):
    """One episode: timeline, charts, who was hit, before/during/after, and does today look like it."""
    got = _lh(("episode", episode_id), lambda: episodes.page(rows, episode_id, date.today().year))
    if got is None:
        raise HTTPException(404, f"no episode {episode_id}")
    return got


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


@api.get("/long/event-wikipedia")
def long_event_wikipedia(url: str, fetch: bool = True):
    """The Wikipedia introduction for an event or beginning on the World-in-year map, from its
    English article's address (shares the empires' daily limit in Settings)."""
    m = re.match(r"^https://en\.wikipedia\.org/wiki/([^?#]+)$", url)
    if not m:
        raise HTTPException(422, "url must be an English Wikipedia article")
    title = unquote(m.group(1)).replace("_", " ")
    key = "ev_" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
    res = wiki.page(key, {"name": title, "type": "event", "article": title}, fetch, kind="empires")
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
