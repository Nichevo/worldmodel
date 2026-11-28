"""Land, cities and trees, city pages and live streams."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Literal

from fastapi import Body, HTTPException, Query

from worldmodel_contract import catalogue
from worldmodel_contract.cities import CITY_INDICATORS
from worldmodel_contract.queries import series_sql, stream_query
from worldmodel_api import cityscore, core, crops, land, numbeo, userdata, wiki
from worldmodel_api.core import _has_cities, _lh, api, rows, split
from worldmodel_api.routes.basics import _with_image_urls
from worldmodel_api.routes.data import _respond


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


@api.get("/crops/levels")
def crops_levels():
    """Which Top crops maps have figures: countries, US states, US counties, New Zealand regions."""
    return _lh(("crops", "levels"), lambda: crops.levels(rows))


@api.get("/crops/top")
def crops_top(level: str = "world", year: int | None = None):
    """The crop on the most land in each place at a level, with each place's top five and the map's legend."""
    try:
        return _lh(("crops", "top", level, year), lambda: crops.top(rows, level, year))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/crops/where/{crop}")
def crops_where(crop: str, level: str = "world", year: int | None = None):
    """Where one crop is grown: its hectares and share of crop land in each place at a level."""
    try:
        return _lh(("crops", "where", crop, level, year), lambda: crops.crop_where(rows, crop, level, year))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/crops/place/{entity}")
def crops_place(entity: str):
    """One country's, state's, county's or region's crops by land over the years held."""
    return crops.entity_crops(rows, entity)


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


@api.get("/land/cover-change")
def land_cover_change(entity: str = "NZL", y0: str = "1992", y1: str = "2020"):
    """Land that changed from each kind of cover to another between two years in a country (ESA's
    yearly 300 m maps, read from the land cover pictures), with each kind's total both years."""
    try:
        return land.cover_change(entity.upper(), y0, y1)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@api.get("/land/trees")
def land_trees(council: str | None = None):
    """A council's street tree list: how many, the commonest species, planting by year."""
    return land.street_trees(rows, council)


# ----------------------------------------------------------------------------- cities


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


def _city_score(score_id: str, year: int | None) -> dict:
    if not _has_cities():
        return {"rows": [], "parts": [], "note": NO_CITIES}
    return _lh(("city_score", score_id, year), lambda: cityscore.compute(rows, score_id, year))


@api.get("/cities/scores")
def city_scores(score: str = "stress", year: int | None = Query(None, description="Score on figures up to this year")):
    """A score made from several city figures (contract city_scores.yaml), such as City stress:
    every city with enough parts, most stressful first, each part's figure and its 0-10 place,
    the years with figures, and published scores to compare with."""
    if not cityscore.config(score):
        raise HTTPException(404, f"no city score {score}; there are {', '.join(catalogue.city_scores())}")
    got = dict(_city_score(score, year))
    got["years"] = cityscore.years(rows, score) if _has_cities() else []
    got["scores"] = [{"id": k, "name": v["name"]} for k, v in catalogue.city_scores().items()]
    return got


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
            "scores": cityscore.for_city(rows, _city_score, city_id),
            "others": [o for o in others if o["city_id"] != city_id][:10],
            "places": places(kind=None, country=None, city=city_id, q=None, limit=60)["rows"]}


DIST_KM = """2 * 6371.0088 * asin(least(1, sqrt(pow(sin(radians(c.lat - ?) / 2), 2)
    + cos(radians(?)) * cos(radians(c.lat)) * pow(sin(radians(c.lon - ?) / 2), 2))))"""
DIST_COLS = "c.city_id, c.name, c.country_id, e.short_name AS country, c.lat, c.lon, c.timezone, coalesce(c.population, 0) AS population"


def _key_city(name: str) -> dict | None:
    """A city named in Settings > Cities > Key cities: "London" (the biggest London) or
    "London GBR" / "London, GBR" (that country's)."""
    name = name.strip()
    m = re.match(r"^(.*?)[,\s]+([A-Za-z]{3})$", name)
    where, params = "(lower(c.name) = lower(?) OR lower(c.ascii_name) = lower(?))", [name, name]
    if m and not rows(f"SELECT 1 FROM cities c WHERE {where} LIMIT 1", params):
        where += " AND c.country_id = ?"
        params = [m.group(1), m.group(1), m.group(2).upper()]
    found = rows(f"""SELECT {DIST_COLS} FROM cities c LEFT JOIN entities e ON e.entity_id = c.country_id
                     WHERE {where} ORDER BY population DESC LIMIT 1""", params)
    return found[0] if found else None


@api.get("/cities/{city_id}/distances")
def city_distances(city_id: str, add: str | None = Query(None, description="Comma-separated city ids to add"),
                   near: int = Query(8, ge=0, le=30), near_min_population: float = 100_000):
    """How far this city is from the key cities (Settings > Cities), from any cities added, and
    which big cities are nearest: great-circle km, the bearing to set off on, and each city's
    time zone (the page works out today's time difference)."""
    c = _city(city_id)
    lat, lon = c["lat"], c["lon"]
    names = [n for n in str(userdata.settings().get("distance_key_cities") or "").split(",") if n.strip()]
    keys, seen = [], {city_id}
    for n in names:
        k = _key_city(n)
        if k and k["city_id"] not in seen:
            seen.add(k["city_id"])
            keys.append(k)
    extra = [x for x in split(add) if x not in seen][:20]
    added = rows(f"""SELECT {DIST_COLS} FROM cities c LEFT JOIN entities e ON e.entity_id = c.country_id
                     WHERE c.city_id IN ({', '.join('?' * len(extra))})""", extra) if extra else []
    seen |= {a["city_id"] for a in added}
    nearest = rows(f"""SELECT * FROM (SELECT {DIST_COLS}, {DIST_KM} AS km FROM cities c LEFT JOIN entities e ON e.entity_id = c.country_id
                       WHERE coalesce(c.population, 0) >= ? AND c.city_id <> ? AND c.lat IS NOT NULL)
                       ORDER BY km LIMIT ?""", [lat, lat, lon, near_min_population, city_id, near + len(seen)]) if near else []
    nearest = [r for r in nearest if r["city_id"] not in seen][:near]

    def leg(r: dict, kind: str) -> dict:
        la1, la2, dl = map(math.radians, (lat, r["lat"], r["lon"] - lon))
        km = 2 * 6371.0088 * math.asin(min(1, math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2)))
        brg = (math.degrees(math.atan2(math.sin(dl) * math.cos(la2),
                                       math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl))) + 360) % 360
        out = {k: r[k] for k in ("city_id", "name", "country_id", "country", "lat", "lon", "timezone", "population")}
        return {**out, "kind": kind, "km": round(km, 1), "bearing": round(brg) % 360}

    return {"city": {k: c[k] for k in ("city_id", "name", "country_id", "lat", "lon", "timezone")},
            "key": [leg(k, "key") for k in keys], "added": [leg(a, "added") for a in added],
            "nearest": [leg(n, "nearest") for n in nearest], "key_names": names,
            "missing": [n.strip() for n in names if not _key_city(n)]}


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
    meta_ = core.warehouse.current().meta
    return _respond(rows(sql, params), format, name,
                    {"stream": st, "as_of": as_of, "build_id": meta_.get("build_id")})
