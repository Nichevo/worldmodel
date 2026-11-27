"""Worldmodel API, on localhost. Serves the web app and any other local tool.

All endpoints are under /api/v1 and read the warehouse only. The only things
written are the user's own files (layouts, settings, indicator switches, history)
in a user folder beside the data (see layouts.py and userdata.py), Wikipedia pages
fetched on demand within the daily limits in Settings (media/wikipedia, see
wiki.py), and, when asked on the Data status page, old raw downloads deleted to
free space.
Interactive docs are at /api/docs when the server runs (also through the web app, port 3030).
The public API for scripts, the Python client and MCP is in public.py, under /api/public/v1.

This file sets up the app; the calls themselves are in routes/, one module per area of the
app (routes/__init__.py lists them), and what they share is in core.py.
"""

from __future__ import annotations

import importlib
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from worldmodel_contract import local
from worldmodel_api import __version__, core, spotting, tiles, wiki
from worldmodel_api import public as public_api
from worldmodel_api.core import api, rows, split  # noqa: F401 - also used as main.rows by tools and tests
from worldmodel_api.routes import AREAS
from worldmodel_api.warehouse import WarehouseError

# Each area module adds its calls to core.api as it is imported; the order is the order
# FastAPI tries them in, so it follows the order they had when they were all in this file.
for _area in AREAS:
    importlib.import_module(f"worldmodel_api.routes.{_area}")

# Calls public.py reuses (it reaches them as main.<name>).
from worldmodel_api.routes.basics import search, wiki_targets  # noqa: E402,F401
from worldmodel_api.routes.data import _series, _stat_forecast  # noqa: E402,F401
from worldmodel_api.routes.disease import events  # noqa: E402,F401
from worldmodel_api.routes.forecasts import crowd_list, predictions_add, predictions_list  # noqa: E402,F401
from worldmodel_api.routes.world import alike, synthetic_view  # noqa: E402,F401


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
    try:  # ships saved in the background while the app runs (Settings > Transport: Collect ships)
        from worldmodel_api import journeys, live

        live.SHIPS.ports_fn = lambda: journeys.ports(rows)
        live.SHIPS.start()
        live.PLANES.start()
    except Exception:  # noqa: BLE001 - the map says what is wrong
        pass
    try:  # congestion: airport flights counted daily, road counts weekly, trains while on (Settings > Transport)
        from worldmodel_api import airbusy, roads, trains

        airbusy.COLLECTOR.start(rows, local.load_settings)
        roads.COLLECTOR.start(local.load_settings)
        trains.TRAINS.start(local.load_settings)
    except Exception:  # noqa: BLE001 - the Congestion tab says what is wrong
        pass
    starter = threading.Timer(30, _tiles_starter)  # the starter map copies, once, after the app is up
    starter.daemon = True
    starter.start()
    try:  # forecast accuracy: models' forecasts recorded every 6 hours (Settings > Climate > Weather)
        from worldmodel_api import forecast_skill, userdata

        forecast_skill.start(userdata.settings)
    except Exception:  # noqa: BLE001 - shown on the Forecast accuracy page
        pass
    try:  # forecast scores: back-tests and the running record, worked out after each new build (Forecasts > Scores)
        from worldmodel_api import forecast_scores, userdata
        from worldmodel_api.routes.forecasts import _wh_version

        forecast_scores.start(rows, core._build_id, _wh_version, userdata.settings)
    except Exception:  # noqa: BLE001 - the Scores tab says what is wrong
        pass
    try:
        spotting.recover()  # a scan left running when the app stopped waits, paused
    except Exception:  # noqa: BLE001 - shown on the Spotting page
        pass
    try:
        from worldmodel_api import thennow
        thennow.timelapse_recover()  # a timelapse being made when the app stopped carries on
    except Exception:  # noqa: BLE001 - shown on the Spotting page
        pass
    yield
    background.close()


app = FastAPI(title="Worldmodel API", version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json",
              description="The worldmodel app's API. **Public API** (/api/public/v1) is the stable part for scripts, "
                          "the Python client and AI assistants: switch it on in Settings > API access. The rest (/api/v1) "
                          "serves the app's own pages and may change.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3030", "http://127.0.0.1:3030"],
                   allow_methods=["GET", "PUT", "POST", "PATCH", "DELETE"], allow_headers=["*"])


@app.exception_handler(WarehouseError)
def _warehouse_error(_, exc: WarehouseError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health():
    try:
        o = core.warehouse.current()
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
