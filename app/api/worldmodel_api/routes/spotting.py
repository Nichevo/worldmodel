"""Spotting: pictures read by the app."""

from __future__ import annotations

from typing import Literal

from fastapi import Body, HTTPException, Query
from fastapi.responses import FileResponse, Response

from worldmodel_api import spotting
from worldmodel_api.core import api, rows
from worldmodel_api.routes.events import _BLANK_PNG


# ----------------------------------------------------------------------------- spotting (pictures read by the app)
def _spot_png(data: bytes | None) -> Response:
    if data is None:
        return Response(_BLANK_PNG, media_type="image/png", headers={"Cache-Control": "max-age=300", "X-Tile-Missing": "1"})
    return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@api.get("/spot/terms")
def spot_terms():
    """What the Spotting layers draw: kinds of land change, water classes, things scans look for, places checks can check."""
    from worldmodel_contract import spotting as sp
    return {"changes": [vars(c) for c in sp.CHANGES], "water": [vars(w) for w in sp.WATER_CLASSES],
            "tags": [vars(t) for t in sp.SCAN_TAGS], "checkable": sp.CHECKABLE, "sources": sp.CHANGE_SOURCES,
            "water_attribution": sp.WATER_ATTRIBUTION}


@api.get("/spot/change/{src}/{z}/{x}/{y}")
def spot_change_tile(src: str, z: int, x: int, y: int, y0: int = Query(2017, alias="from"), y1: int = Query(2025, alias="to"),
                     kinds: str | None = None):
    """Map layer 8: land whose cover changed between two years, coloured by kind of change."""
    try:
        return _spot_png(spotting.change_tile(src, z, x, y, y0, y1, kinds))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/spot/water/{z}/{x}/{y}")
def spot_water_tile(z: int, x: int, y: int, show: Literal["changes", "all"] = "changes"):
    """Map layer 9: water gained (blue) and lost (red) since the 1980s (JRC Global Surface Water)."""
    return _spot_png(spotting.water_tile(z, x, y, show))


@api.get("/spot/summary")
def spot_summaries():
    """Area summaries worked out so far, and the one being worked out now."""
    return spotting.summaries()


@api.post("/spot/summary")
def spot_summary_start(body: dict = Body(...)):
    """Work out how much land changed (or water came and went) in a country or box, in the background."""
    try:
        return spotting.summary_start(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@api.get("/spot/here")
def spot_here(lon: float, lat: float, zoom: int = 15):
    """For Ask the picture: the satellite picture round a point, the land cover there and the map's items nearby."""
    try:
        return spotting.here(rows, lon, lat, zoom)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@api.get("/spot/models")
def spot_models():
    """Your Ollama models that can see pictures, and the ones used for asking and for scans."""
    return spotting.vision_models()


@api.get("/spot/scans")
def spot_scans():
    return {**spotting.status(), "hit_rates": spotting.hit_rates()}


@api.post("/spot/scans/estimate")
def spot_scan_estimate(body: dict = Body(...)):
    try:
        return spotting.estimate(rows, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.post("/spot/scans")
def spot_scan_create(body: dict = Body(...)):
    """Start a scan (squares of an area) or a check (the map's own places) with a local model."""
    try:
        return spotting.scan_create(rows, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.post("/spot/scans/{scan_id}/{action}")
def spot_scan_action(scan_id: str, action: str):
    try:
        return spotting.scan_action(scan_id, action)
    except (ValueError, KeyError) as exc:
        raise HTTPException(404 if isinstance(exc, KeyError) else 422, str(exc))


@api.delete("/spot/scans/{scan_id}")
def spot_scan_delete(scan_id: str):
    try:
        if not spotting.scan_delete(scan_id):
            raise HTTPException(404, f"no scan {scan_id}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True}


@api.get("/spot/scans/{scan_id}/found")
def spot_scan_found(scan_id: str):
    try:
        return spotting.found(scan_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.post("/spot/scans/{scan_id}/found/{item_id}/mark")
def spot_scan_mark(scan_id: str, item_id: str, body: dict = Body(...)):
    """Your yes / no on something a scan reported (mark: "yes", "no" or null)."""
    try:
        return spotting.mark(scan_id, item_id, body.get("mark"))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc}")


@api.get("/spot/scans/{scan_id}/pictures/{key}.jpg")
def spot_scan_picture(scan_id: str, key: str):
    try:
        p = spotting.picture_path(scan_id, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not p:
        raise HTTPException(404, "no picture kept for that")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@api.get("/spot/layer")
def spot_layer(min_sure: float | None = None):
    """Map layer 0, Spotted by AI: what scans reported, and places a check said do not look right."""
    return spotting.layer(min_sure)
