"""Relationships, climate, page summaries, nature, transport, markets, sectors, religion, laws, topics and countries like this one."""

from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Literal

from fastapi import Body, HTTPException, Query
from fastapi.responses import Response

from worldmodel_contract import catalogue, local
from worldmodel_contract import relations as relterms
from worldmodel_api import climate, crises, look, markets, nature, osint, people, port_goods, ports, relationships, sectors, transport, userdata
from worldmodel_api import regions as region_tools
from worldmodel_api.core import _build_id, _has_cities, _has_table, api, rows, split
from worldmodel_api.routes.indicators import _indicator_rows
from worldmodel_api.routes.disease import events


# ----------------------------------------------------------------------------- relationship scan


@api.get("/relationships")
def relationships_list(label: str | None = None, domain: str | None = None, group: str | None = None,
                       q: str | None = None, indicator: str | None = None, drivers: bool = False,
                       hide_same: bool = True, first: bool = False, hide_same_source: bool = False,
                       built: str = Query("last", pattern="^(last|hide|only|mixed)$"),
                       lag: int | None = Query(None, ge=1, le=relterms.MAX_LAG),
                       limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Pairs of indicators the relationship scan found worth a look, best first. Each
    carries its evidence labels (move together, one tends to come first, holds after
    allowing for income and time); nothing is called cause and effect. Filters: label,
    topic (domain), country group (pairs whose link also shows within that group),
    words, one indicator, pairs in the forecast model's driver list, pairs where one
    comes first by a given number of years (`lag`, 1-5). Pairs where one
    figure is made from the other (a total and the same per person, a level and its
    growth, a ratio and its parts) carry `built_from` with the reason; `built` lists
    them last (default), hides them, shows only them, or mixes them in. `scan` is null
    until the first scan has run (after a refresh)."""
    if label and label not in relterms.LABELS:
        raise HTTPException(422, f"label must be one of {', '.join(relterms.LABELS)}")
    out = relationships.pairs(_build_id(), label, domain, group, q, indicator, drivers, hide_same, first,
                              hide_same_source, limit, offset, built, lag)
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


@api.get("/transport/pressure/map")
def transport_pressure_map(end: date | None = Query(None, description="look back: the weeks ending with the week holding this day"),
                           weeks: int = Query(4, ge=1, le=26)):
    """The 'Ports against normal' map layer at any week since 2019 (GeoJSON), and the weeks stored."""
    data = {**ports.layer(rows, end, weeks), **{"span": ports.weeks_span(rows)}}
    return Response(json.dumps(data, separators=(",", ":"), default=str), media_type="application/geo+json")


@api.get("/transport/pressure/places")
def transport_pressure_places(entity: str | None = None):
    """Every port and chokepoint with weekly figures: ships a week and the last four weeks against normal."""
    return ports.places(rows, entity)


@api.get("/transport/pressure/{kind}/{ident}")
def transport_pressure(kind: Literal["port", "chokepoint"], ident: str, start: int = Query(2019, ge=2019, le=2100),
                       event: str | None = Query(None, description="an impact_id: adds how the connected ports fared")):
    """One port or chokepoint each week against normal, its events and their impacts, ship types and connections."""
    return ports.place(rows, kind, ident, start, event)


@api.get("/transport/impacts")
def transport_impacts(entity: str | None = None, hazard: str | None = None, since: int | None = None,
                      kind: Literal["port", "chokepoint"] | None = None, clear: bool = True,
                      limit: int = Query(200, ge=1, le=2000)):
    """The biggest hits: what events did to ports and chokepoints, most ship calls lost first."""
    return ports.impacts(rows, entity, hazard, since, kind, clear, limit)


@api.get("/transport/patterns")
def transport_patterns():
    """What usually happens to ships after each kind of event, and how fast each port gets back."""
    return ports.patterns(rows)


@api.get("/transport/pressure-country/{entity}")
def transport_pressure_country(entity: str):
    """A country's busiest ports over the last 26 weeks against normal, and the events that hit them."""
    return ports.country(rows, entity)


@api.get("/transport/goods/countries")
def transport_goods_countries():
    """Countries with goods by port: how many ports, from which sources, up to when."""
    return port_goods.countries(rows)


@api.get("/transport/goods/ports/{entity}")
def transport_goods_ports(entity: str):
    """A country's ports with the last year of goods in and out, busiest first."""
    return port_goods.ports_of(rows, entity)


@api.get("/transport/goods/for/{port_id}")
def transport_goods_for(port_id: str):
    """The goods-by-port keys tied to an IMF PortWatch port."""
    return port_goods.for_port_id(rows, port_id)


@api.get("/transport/goods/port/{key}")
def transport_goods_port(key: str):
    """One port: totals year by year, last year's goods and partners in and out, biggest goods by year."""
    d = port_goods.port(rows, key)
    if d is None:
        raise HTTPException(404, f"No goods stored for port {key}")
    return d


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
def live_planes(west: float, south: float, east: float, north: float, at: float | None = None):
    """Planes in the air in a map window now (OpenSky Network; at most one request a minute), or
    with `at` (seconds since 1970) where the saved planes were then."""
    from worldmodel_api import live

    if at is not None:
        return live.PLANES.saved_at(at, west, south, east, north)
    if not local.load_settings().get("live_planes", True):
        return {"type": "FeatureCollection", "features": [], "error": "Planes now is switched off in Settings > Transport."}
    return live.PLANES.get(west, south, east, north)


@api.get("/live/ships")
def live_ships(west: float, south: float, east: float, north: float, at: float | None = None):
    """Ships' latest positions in a map window (aisstream.io, needs AISSTREAM_API_KEY), or with `at`
    (seconds since 1970) where they were then, from the positions saved while collecting."""
    from worldmodel_api import live

    if not local.load_settings().get("live_ships", True):
        return {"type": "FeatureCollection", "features": [], "error": "Ships now is switched off in Settings > Transport."}
    out = live.SHIPS.get(west, south, east, north, at)
    banned = osint.sanctioned_ship_ids(rows)
    if banned:
        for f in out.get("features") or []:
            p = f.get("properties") or {}
            if str(p.get("id")) in banned or (p.get("imo") and str(p["imo"]) in banned):
                p["sanctioned"] = True
    return out


@api.get("/live/ships/status")
def live_ships_status():
    """The ship collector: on or off, its area, and the days, size and time span of the saved positions."""
    from worldmodel_api import live

    return live.SHIPS.status()


@api.get("/live/ships/table")
def live_ships_table(q: str = "", group: str = "", flag: str = "", sort: str = "last_seen",
                     limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0), hours: float = Query(0, ge=0),
                     to: str = "", came: str = "", ontime: str = ""):
    """Every ship seen: name, MMSI, IMO, call sign, flag, type, size, destination (matched to a port)
    and where it was last; `to` keeps ships going to a port, code or country containing it. Cargo
    ships also get on_time (on_time, early, slipping, late, none) and late_h; `ontime` keeps one state
    (any: every cargo ship with one)."""
    from worldmodel_api import journeys, live

    ix = journeys.ports(rows)
    now = time.time()
    fn = (lambda m: _schedule_of(m, ix, now)) if live.SHIPS.settings().get("ship_schedules", True) else None
    out = live.SHIPS.table(q, group, flag, sort, limit, offset, hours, to=to, ports=ix, came=came, schedule_fn=fn, ontime=ontime)
    banned = osint.sanctioned_ship_ids(rows)
    for r in out["rows"]:
        r["sanctioned"] = bool(banned and (str(r["id"]) in banned or (r.get("imo") and str(r["imo"]) in banned)))
    return out


@api.get("/live/ships/stats")
def live_ships_stats(hours: float = Query(24, ge=0, le=24 * 400), top: int = Query(25, ge=0, le=100_000),
                     group: str = "", flag: str = "", q: str = "", to: str = "", came: str = ""):
    """Counts of the ships heard in the last `hours` (0: every ship kept): by kind, flag, where from, where to and more.
    The same filters as the ships table narrow what is counted."""
    from worldmodel_api import journeys, live, livestats

    found = live.SHIPS.table(q=q, group=group, flag_code=flag, limit=10**9, hours=hours, to=to, ports=journeys.ports(rows), came=came)["rows"]
    return {**livestats.ships(found, {}, top), "hours": hours, "top": top}


@api.get("/live/planes/stats")
def live_planes_stats(hours: float = Query(24, ge=0.1, le=24 * 7), top: int = Query(25, ge=0, le=100_000),
                      group: str = "", airline: str = "", flag: str = "", q: str = "", frm: str = Query("", alias="from"), to: str = ""):
    """Counts of the planes heard in the last `hours`: by kind, airline, country, from, to, route, aircraft and height.
    group, airline (name, or - for none), flag (two letters), from, to and q (any text) narrow what is counted."""
    from worldmodel_api import live, livestats

    found = livestats.filter_planes(live.PLANES.table(hours)["planes"], group=group, airline=airline, flag=flag, q=q, frm=frm, to=to)
    return {**livestats.planes(found, {}, top), "hours": hours, "top": top}


@api.get("/live/ships/detail/{mmsi}")
def live_ship_detail(mmsi: int):
    """One ship's details (the ships table's pop-up)."""
    from worldmodel_api import live

    got = live.SHIPS.detail(mmsi)
    if got is None:
        raise HTTPException(404, "no ship with that MMSI seen")
    banned = osint.sanctioned_ship_ids(rows)
    got["sanctioned"] = bool(banned and (str(mmsi) in banned or (got.get("imo") and str(got["imo"]) in banned)))
    return got


@api.get("/live/ships/owner/{mmsi}")
def live_ship_owner(mmsi: int):
    """Who owns, runs and built a ship: Global Fishing Watch (with a token), Wikidata by IMO, an Equasis link."""
    from worldmodel_api import live, shipowners

    got = live.SHIPS.detail(mmsi)
    if got is None:
        raise HTTPException(404, "no ship with that MMSI seen")
    global _SHIP_OWNERS
    if _SHIP_OWNERS is None or _SHIP_OWNERS.file.parent != live.SHIPS.store.folder:
        _SHIP_OWNERS = shipowners.Owners(live.SHIPS.store.folder)
    return shipowners.owner(_SHIP_OWNERS, mmsi, got, live.SHIPS.settings())


_SHIP_OWNERS = None


@api.get("/live/ships/journey/{mmsi}")
def live_ship_journey(mmsi: int, hours: float = Query(72, gt=0, le=24 * 400)):
    """Where a ship has been (its saved path) and where it says it is going (its destination, matched to a port)."""
    from worldmodel_api import journeys, live

    return journeys.ship_journey(rows, live.SHIPS, mmsi, hours)


def _schedule_of(mmsi: int, ports: dict, now: float | None = None) -> dict | None:
    """A cargo ship's on-time state (schedules.py), or None for other ships."""
    from worldmodel_api import journeys, live
    from worldmodel_api.schedules import is_cargo

    d = live.SHIPS.store.details.get(mmsi) or {}
    here = live.SHIPS.ships.get(mmsi) or {}
    if not is_cargo(d.get("kind") or here.get("kind")):
        return None
    return live.SHIPS.schedules.status(mmsi, {**d, "imo": d.get("imo") or here.get("imo"), "name": d.get("name") or here.get("name")},
                                       here, journeys.match_port(d.get("destination"), ports), now)


@api.get("/live/ships/schedule/{mmsi}")
def live_ship_schedule(mmsi: int):
    """A cargo ship's schedule: on time or late (against its line's schedule, the port's booking or its
    own first ETA), our estimate of its arrival, its ETA over time, its port calls and its learned route."""
    from worldmodel_api import journeys, live
    from worldmodel_api.schedules import line_of

    sch = live.SHIPS.schedules
    st = _schedule_of(mmsi, journeys.ports(rows))
    if st is None:
        raise HTTPException(404, "schedules are kept for cargo and container ships only")
    d = live.SHIPS.store.details.get(mmsi) or {}
    ln = line_of(d.get("name"))
    return {**st, "id": mmsi, "name": d.get("name"), "imo": d.get("imo"), "line": ln[0] if ln else None,
            "voyages": sch.voyages(mmsi)[-5:], "calls": sch.calls.get(mmsi, [])[-15:], "route": sch.route(mmsi),
            "on": live.SHIPS.schedules_on()}


@api.get("/live/schedules")
def live_schedules(port: str = "", days: float = Query(7, gt=0, le=60)):
    """The ports' arrival lists (Auckland, Tauranga, NSW ports, Melbourne) as a board: each ship's booked arrival, how often
    the booking moved, its own ETA, our estimate and whether it is on time. `port` keeps one port."""
    from worldmodel_api import journeys, live
    from worldmodel_api.schedules import PORT_LISTS, line_of

    sch, now = live.SHIPS.schedules, time.time()
    by_imo = {d.get("imo"): m for m, d in live.SHIPS.store.details.items() if d.get("imo")}
    ports_ix = journeys.ports(rows)
    out = []
    for calls in list(sch.bookings.values()):
        for b in calls:
            if port and port.lower() not in (b["port"].lower(), b["locode"].lower()):
                continue
            arr = b.get("arrival") or b["first"][1]
            if b.get("departed_at") or arr < now - 2 * 86400 or arr > now + days * 86400:
                continue
            mmsi = by_imo.get(b.get("imo"))
            st = _schedule_of(mmsi, ports_ix, now) if mmsi else None
            first = b["versions"][0][1] if b.get("versions") else b["first"][1]
            v = (st or {}).get("voyage") or {}
            ln = line_of(b["name"])
            out.append({"name": b["name"], "imo": b.get("imo"), "id": mmsi, "port": b["port"], "booked": arr, "first_booked": first,
                        "moved_h": round((arr - first) / 3600, 1), "changes": max(0, len(b.get("versions") or []) - 1),
                        "own_eta": v.get("eta"), "estimate": ((st or {}).get("estimate") or {}).get("at"),
                        "arrived_at": b.get("arrived_at") or (st or {}).get("arrived_at"), "in_port": b.get("state") == "in_port",
                        "state": (st or {}).get("state") or ("late" if (arr - first) / 3600 > 24 else "on_time"),
                        "late_h": (st or {}).get("late_h") if st and st.get("measured_by") else round((arr - first) / 3600, 1),
                        "measured_by": (st or {}).get("measured_by") or "port", "prev": b.get("prev"), "next": b.get("next"),
                        "cargo": b.get("cargo"), "voyage": b.get("voyage"), "line": ln[0] if ln else None})
    out.sort(key=lambda r: r["booked"])
    return {"rows": out, "ports": [p["name"] for p in PORT_LISTS.values()], "notes": dict(sch.notes),
            "on": live.SHIPS.schedules_on(), "lists_on": bool(live.SHIPS.settings().get("port_lists_fetch", True))}


@api.get("/live/schedules/reliability")
def live_schedules_reliability(days: float = Query(30, gt=0, le=400)):
    """Share of calls on time (within a day of the first booking) by line and by port, from the
    bookings whose arrival we saw in the last `days`. Our own small sample, not an industry table."""
    from worldmodel_api import live
    from worldmodel_api.schedules import ON_TIME_H, line_of

    sch, now = live.SHIPS.schedules, time.time()
    by_imo = {d.get("imo"): m for m, d in live.SHIPS.store.details.items() if d.get("imo")}
    tally: dict[tuple[str, str], list[int]] = {}
    for calls in list(sch.bookings.values()):
        for b in calls:
            first = b["versions"][0][1] if b.get("versions") else b["first"][1]
            mmsi = by_imo.get(b.get("imo"))
            got = b.get("arrived_at") or (sch._arrived(mmsi, b["locode"], first) if mmsi else None)
            if not got or got < now - days * 86400:
                continue
            ok = abs(got - first) / 3600 <= ON_TIME_H
            ln = line_of(b["name"])
            for key in (("line", ln[0] if ln else "Other or not told"), ("port", b["port"])):
                t = tally.setdefault(key, [0, 0, 0])
                t[0] += 1
                t[1] += ok
                t[2] += max(0, got - first)
    def part(kind):
        rows_ = [{"name": k[1], "calls": v[0], "on_time": v[1], "share": v[1] / v[0], "avg_late_h": round(v[2] / v[0] / 3600, 1)}
                 for k, v in tally.items() if k[0] == kind]
        return sorted(rows_, key=lambda r: -r["calls"])
    return {"days": days, "lines": part("line"), "ports": part("port")}


@api.get("/live/planes/journey/{icao24}")
def live_plane_journey(icao24: str, callsign: str | None = None, lat: float | None = None, lon: float | None = None):
    """A plane's path this flight (OpenSky), its route by callsign and its registration and type (adsb.lol)."""
    from worldmodel_api import journeys, live

    if not re.fullmatch(r"[0-9a-fA-F]{6}", icao24):
        raise HTTPException(400, "icao24 is six hex digits")
    return journeys.plane_journey(rows, live.PLANES._auth, icao24, callsign, lat, lon, store=live.PLANES.store)


PLANE_SORTS = {"callsign", "airline", "model", "reg", "country", "altitude_m", "speed_kmh", "climb_ms", "squawk", "seen"}


@api.get("/live/planes/table")
def live_planes_table(hours: float = Query(1, ge=0, le=24 * 7), q: str = "", group: str = "", airline: str = "",
                      frm: str = Query("", alias="from"), to: str = "", mins: float = Query(0, ge=0, le=24 * 60 * 7),
                      sort: str = "", limit: int = Query(0, ge=0, le=100_000)):
    """The planes from the last OpenSky request, and those saved in the last `hours` (the planes table).
    Filters as on the Live page (q any text, group, airline name or - for none, from, to, heard in the
    last `mins`), sorted by `sort` (numbers largest first); `limit` rows (0: all), with `total` matching
    and `airlines` (every airline in the table, most planes first) for the drop-down."""
    from worldmodel_api import live, livestats

    out = live.PLANES.table(hours)
    if not (q or group or airline or frm or to or mins or sort or limit):
        return out
    every = out["planes"]
    rows = livestats.filter_planes(every, group=group, airline=airline, q=q, frm=frm, to=to)
    if mins:
        since = time.time() - mins * 60
        rows = [p for p in rows if (p.get("seen") or 0) >= since]
    if sort in ("altitude_m", "speed_kmh", "climb_ms", "seen"):  # largest first, the unknown last
        rows = sorted(rows, key=lambda p: -p[sort] if isinstance(p.get(sort), (int, float)) else float("inf"))
    elif sort in PLANE_SORTS:
        rows = sorted(rows, key=lambda p: (p.get(sort) in (None, ""), str(p.get(sort) or "").lower()))
    counts: dict[str, int] = {}
    for p in every:
        if p.get("airline"):
            counts[p["airline"]] = counts.get(p["airline"], 0) + 1
    airlines = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {**out, "planes": rows[:limit] if limit else rows, "total": len(rows), "all": len(every), "airlines": airlines}


@api.get("/live/planes/status")
def live_planes_status():
    """How many planes are saved, from when to when (the map's time slider)."""
    from worldmodel_api import live

    return live.PLANES.status()


@api.get("/live/ships/sweeps")
def live_ship_sweeps(days: float = Query(7, ge=0.1, le=400)):
    """Each whole-world snapshot (finished or cut short, reports, new ships) and each dropped connection."""
    from worldmodel_api import live

    return live.SHIPS.sweeps(days)


@api.get("/live/planes/flights")
def live_plane_flights(icao: str | None = None, callsign: str | None = None, days: float = Query(30, ge=0.1, le=400)):
    """Flights saved for one aircraft (icao) or every aircraft that flew a callsign, newest first."""
    from worldmodel_api import live

    if not (icao or callsign):
        raise HTTPException(400, "Give icao or callsign.")
    return live.PLANES.flights(icao, callsign, days)


@api.get("/live/planes/logo/{code}")
def live_plane_logo(code: str):
    """An airline's logo by its ICAO code (Settings > Transport: Airline logos), kept on disk once fetched."""
    from worldmodel_api import aircraftdb, live

    if not local.load_settings().get("planes_logos", True):
        raise HTTPException(404, "Airline logos are off (Settings > Transport).")
    png = aircraftdb.logo(live.PLANES.store.folder / "logos", code)
    if not png:
        raise HTTPException(404, f"No logo for {code}.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=604800"})


@api.get("/live/ships/track/{mmsi}")
def live_ship_track(mmsi: int, hours: float = Query(24, gt=0, le=24 * 400), end: float | None = None):
    """One ship's saved path over the hours before `end` (default now), as GeoJSON."""
    from worldmodel_api import live

    return live.SHIPS.track(mmsi, hours, end)


@api.get("/live/military-planes")
def live_military_planes(west: float, south: float, east: float, north: float):
    """Military planes in the air in a map window now, from adsb.lol's volunteer receivers (no key; one
    request a minute at most). Only planes that broadcast their position show: many military flights do not."""
    from worldmodel_api import live

    if not local.load_settings().get("live_military_planes", True):
        return {"type": "FeatureCollection", "features": [], "error": "Military planes are switched off in Settings > Transport."}
    return live.MIL_PLANES.get(west, south, east, north)


@api.get("/live/cameras")
def live_cameras(west: float, south: float, east: float, north: float):
    """Public cameras in a map window: road agencies' traffic cameras (NZ, Queensland, NSW, London,
    California, Finland) and, with a free Windy key, webcams worldwide (beaches, surf, harbours, cities).
    Each agency's list is read only when the view reaches it and kept six hours; nothing is saved."""
    from worldmodel_api import cameras

    if not local.load_settings().get("live_cameras", True):
        return {"type": "FeatureCollection", "features": [], "error": "Cameras are switched off in Settings > Transport."}
    return cameras.CAMERAS.get(west, south, east, north)


@api.get("/live/cameras/windy/{webcam_id}")
def live_camera_windy(webcam_id: int):
    """A fresh picture and live player link for one Windy webcam (its picture links last ten minutes)."""
    from worldmodel_api import cameras

    if not local.load_settings().get("live_cameras", True):
        return {"error": "Cameras are switched off in Settings > Transport."}
    return cameras.CAMERAS.windy_one(webcam_id)


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
def regions(country: str, level: str | None = None, indicator: str | None = None):
    """The regions inside a country or state (New Zealand's 16, the US states, a state's counties)
    with every figure held for them, by year; level=county under USA for every county, and
    indicator=... to send only that figure's values."""
    return markets.regions(rows, country, level, indicator)


@api.get("/region-countries")
def region_countries():
    """Countries whose regions the app holds (the US, New Zealand), with how many."""
    return region_tools.countries(rows)


@api.get("/region-shapes/{parent}")
def region_shapes(parent: str, level: str | None = None):
    """Outlines of the regions inside a country or state, for the "Regions inside a country" maps;
    level=county under USA gives every county."""
    return region_tools.shapes(rows, parent, level)


@api.get("/region-facts/{entity_id}")
def region_facts(entity_id: str):
    """A region's figures, each with its rank among the regions beside it (#n of N) and their middle value."""
    return region_tools.facts(rows, entity_id)


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
    where = _ranking_continents()
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        r["continent"] = where.get(r["entity_id"])
    return {"indicator": indicator_id, "year": y, "rows": ranked, "world": world}


def _ranking_continents() -> dict[str, str]:
    """Each country's continent for the value-band and share-of-world pictures, with the
    Americas split into North America (with Central America and the Caribbean) and South America."""
    out: dict[str, str] = {}
    for r in rows("""SELECT m.member_id, g.entity_id AS gid, g.short_name AS name FROM memberships m
            JOIN entities g ON g.entity_id = m.group_id
            WHERE m.valid_to IS NULL AND (g.type = 'continent' OR g.entity_id = 'south-america')"""):
        if r["gid"] == "south-america":
            out[r["member_id"]] = "South America"
        elif r["gid"] == "americas":
            out.setdefault(r["member_id"], "North America")
        else:
            out.setdefault(r["member_id"], r["name"])
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


@api.get("/peers/{entity_id}")
def peers_view(entity_id: str, group: str | None = None, measures: str | None = None, countries: str | None = None):
    """How a country ranks among a group (neighbours, like, a group's id, world, or custom with `countries`): for each
    measure the best, this country with its rank, the group's middle and the worst. `measures` is comma-separated
    indicator ids, each optionally :higher or :lower (which way is better); default a quality-of-life set."""
    from worldmodel_api import peers, similar
    groups = peers.groups_of(rows, entity_id)
    if group is None:  # a club it belongs to, else its part of the world if that has a few countries, else neighbours
        sizes = {g["id"]: g.get("n", 0) for g in groups}
        group = next((g for g in ("oecd", "eu", "asean") if g in sizes), None) or next(
            (g["id"] for g in groups if g["type"] == "subregion" and sizes[g["id"]] >= 5), "neighbours")
    wanted = []
    for m in split(measures) or [m for m, _ in peers.MEASURES]:
        ind, _, way = m.partition(":")
        way = way or peers.BETTER.get(ind) or (userdata.settings().get("discover_better") or {}).get(ind) or "higher"
        wanted.append((ind, "lower" if way == "lower" else "higher"))

    def like() -> list[str]:
        got = similar.like(rows, _country_names(), entity_id, similar.PRESETS["everything"][1], date.today().year - 2, 15)
        return [r["entity_id"] for r in got.get("nearest", [])]

    ids = peers.members(rows, entity_id, group, like, split(countries))
    if group != "custom":  # specks such as Christmas Island or Heard Island crowd out real neighbours
        big = {r["e"] for r in rows("""SELECT entity_id AS e FROM series WHERE indicator_id = 'pop_total' AND variant = 'central'
                   AND breakdown = '' GROUP BY 1 HAVING max(value) >= ?""", [peers.MIN_PEOPLE])}
        ids = [c for c in ids if c == entity_id or c in big] if big else ids
    names = {r["e"]: r["n"] for r in rows("SELECT entity_id AS e, coalesce(short_name, name) AS n FROM entities")}
    near = {}
    if group == "neighbours":
        all_c = frozenset(ids)
        near = dict(peers.neighbours(entity_id, all_c))
    return {"entity_id": entity_id, "name": names.get(entity_id, entity_id), "group": group, "groups": groups,
            "members": [{"entity_id": c, "name": names.get(c, c), "km": near.get(c)} for c in ids if c != entity_id],
            "rows": peers.rank(rows, entity_id, ids, wanted),
            "default_measures": [{"indicator_id": m, "better": b} for m, b in peers.MEASURES]}


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
