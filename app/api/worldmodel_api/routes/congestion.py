"""Congestion: airport busy hours and limits, road traffic counts and live traffic tiles, trains now."""

from __future__ import annotations

import base64

from fastapi import HTTPException, Query
from fastapi.responses import Response
from worldmodel_contract import local

from worldmodel_api import airbusy, roads, trains
from worldmodel_api.core import api, rows


_BLANK_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=")  # 1x1, see-through


def _blank() -> Response:
    """A see-through tile (an empty answer makes the map complain it can't decode the picture)."""
    return Response(_BLANK_PNG, media_type="image/png", headers={"Cache-Control": "max-age=300", "X-Tile-Missing": "1"})


def _s() -> dict:
    return local.load_settings()


# ----------------------------------------------------------------------------- airports
@api.get("/congestion/airports")
def congestion_airports():
    """The airports whose flights are counted each day (OpenSky): flights a day, the busiest
    weekday hour, published limits (caps, curfews, slot levels), gates and stands
    (OpenStreetMap) and how the busiest hour compares with the limit, or with the airport's
    own busiest hour of the past year where no limit is published."""
    return airbusy.airport_list(rows, _s())


@api.get("/congestion/airports/map")
def congestion_airports_map():
    """The counted airports as map points, coloured by busiest hour against the limit or record."""
    return airbusy.map_features(rows, _s())


@api.get("/congestion/airport/{code}")
def congestion_airport(code: str):
    """One airport's flights by local hour (weekday and weekend averages over the last four weeks),
    flights each day, its limits, gates and stands, EUROCONTROL's monthly delays (Europe) and the
    FAA's status now (US)."""
    got = airbusy.airport_detail(rows, code, _s())
    if not got:
        raise HTTPException(404, f"{code} is not in the busy-hours list (Settings > Transport > Airport busy hours)")
    return got


@api.post("/congestion/airports/fetch")
def congestion_airports_fetch():
    """Count new days now instead of waiting for the next round (runs in the background)."""
    import threading

    if airbusy.COLLECTOR.busy:
        return {"started": False, "note": "Already counting"}
    threading.Thread(target=airbusy.COLLECTOR.round, args=(rows, _s()), daemon=True).start()
    return {"started": True}


# ----------------------------------------------------------------------------- roads
@api.get("/congestion/roads/sites")
def congestion_road_sites(west: float = -180, south: float = -90, east: float = 180, north: float = 90):
    """Road counting sites in a map window: vehicles a day over the last week and against the
    eight weeks before (NZTA, WebTRIS, Transport for NSW)."""
    return roads.sites_geojson(west, south, east, north)


@api.get("/congestion/roads/site/{site_id}")
def congestion_road_site(site_id: str):
    """One counting site: vehicles each day, by hour of the day (weekdays and weekends) where
    the source counts by hour, average speed (England) and average daily traffic by year (NZ)."""
    got = roads.site(site_id)
    if not got:
        raise HTTPException(404, "No such counting site")
    return got


@api.get("/congestion/roads/status")
def congestion_roads_status():
    import os

    return {**roads.COLLECTOR.status(), "tomtom_key": bool(os.environ.get("TOMTOM_API_KEY", "").strip()),
            "nsw_key": bool(os.environ.get("TFNSW_API_KEY", "").strip()), "sources": roads.SOURCES}


@api.post("/congestion/roads/fetch")
def congestion_roads_fetch():
    import threading

    if roads.COLLECTOR.busy:
        return {"started": False, "note": "Already reading"}
    threading.Thread(target=roads.COLLECTOR.run_once, daemon=True).start()
    return {"started": True}


@api.get("/congestion/traffic-tiles/{z}/{x}/{y}.png")
def congestion_traffic_tile(z: int, x: int, y: int):
    """TomTom's live traffic flow picture for one map tile, passed through with your key (not saved)."""
    if not _s().get("road_traffic_live", True):
        return _blank()
    code, body, kind = roads.tomtom_tile(z, x, y)
    if code != 200:
        return _blank()
    return Response(content=body, media_type=kind, headers={"Cache-Control": "max-age=60"})


# ----------------------------------------------------------------------------- trains
@api.get("/live/trains")
def live_trains(west: float, south: float, east: float, north: float):
    """Trains in a map window now (Auckland, Wellington, Sydney), coloured by minutes late."""
    return trains.TRAINS.geojson(west, south, east, north, on=bool(_s().get("trains_live", True)))


@api.get("/live/trains/{ident}")
def live_train(ident: str, day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """One train now and its path: the last two hours, or a whole saved day."""
    got = trains.TRAINS.trail(ident)
    if day:
        got["day"] = day
        got["day_path"] = trains.TRAINS.day_path(ident, day)
    return got


@api.get("/congestion/trains")
def congestion_trains(days: int = Query(7, ge=1, le=60)):
    """Each network's feed status, its lines from most to least often late, lateness by hour of
    the day and by day (from the saved readings), and monthly punctuality files saved by hand."""
    return {**trains.TRAINS.status(), **trains.TRAINS.lateness(days), "punctuality": trains.punctuality()}
