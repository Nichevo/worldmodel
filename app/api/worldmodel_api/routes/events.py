"""Events and milestones."""

from __future__ import annotations

import base64
import re
from datetime import date
from typing import Literal

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from worldmodel_api import basemap, space, tiles, userdata
from worldmodel_api.core import api


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
    # MapLibre asks for a whole font stack ("Open Sans Regular,Arial Unicode MS Regular" is its
    # default when a layer names none). Serve the first font in the stack that is here, else
    # Noto Sans Regular, so a label never fails just because its font was not downloaded.
    if not re.fullmatch(r"\d+-\d+\.pbf", part):
        raise HTTPException(404, "no such font range")
    base = basemap.root() / "fonts"
    names = [n.strip() for n in stack.split(",") if n.strip()] + [basemap.FONTS[0]]
    for name in names:
        p = base / name / part
        if p.parent.parent == base and p.is_file():
            return FileResponse(p, media_type="application/x-protobuf", headers={"Cache-Control": "max-age=604800"})
    raise HTTPException(404, "no such font range")


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
def space_data(name: Literal["asteroids", "missions", "moons", "values"]):
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


_BLANK_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=")  # 1x1, fully see-through


@api.get("/tiles/{set_id}/{z}/{x}/{y}")
def tile(set_id: str, z: int, x: int, y: int, t: str | None = None):
    """One picture tile: the saved copy, or fetched online for this view (not saved)."""
    got = tiles.tile(set_id, z, x, y, t)
    if not got:
        # A see-through picture rather than an empty answer: maps try to decode whatever comes
        # back, and an empty body shows up in the browser as "The image could not be decoded".
        return Response(_BLANK_PNG, media_type="image/png", headers={"Cache-Control": "max-age=300", "X-Tile-Missing": "1"})
    data, media = got
    return Response(data, media_type=media, headers={"Cache-Control": "max-age=86400"})
