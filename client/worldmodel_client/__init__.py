"""Use the worldmodel app's data from Python.

    import worldmodel_client as wm
    wm.data("gdp_growth", ["NZL", "AUS"], start=2000)       # rows (a pandas DataFrame if pandas is installed)
    wm.forecast("inflation", "NZL")                           # p10 / p50 / p90 by year
    wm.chart("gdp_growth", ["NZL", "AUS"], path="growth.svg")  # a chart picture

The app must be running with the public API switched on (Settings > API access). On this PC
no key is needed. From another PC, point at it and give a key made in Settings > API access:

    wm.connect("http://my-pc:3030", key="wm_...")      # or set WORLDMODEL_URL and WORLDMODEL_KEY
"""

from __future__ import annotations

from worldmodel_client.client import ApiOff, Client, WorldmodelError

_default: Client | None = None


def connect(url: str | None = None, key: str | None = None) -> Client:
    """Set where the module-level calls go (default: WORLDMODEL_URL or http://localhost:3030)."""
    global _default
    _default = Client(url, key)
    return _default


def _c() -> Client:
    return _default or connect()


def countries(type: str | None = None):
    return _c().countries(type)


def indicators(q: str | None = None):
    return _c().indicators(q)


def search(q: str, limit: int = 20):
    return _c().search(q, limit)


def data(indicator: str, entities=None, start: int | None = None, end: int | None = None, source: str | None = None,
         as_of: str | None = None, projections: bool = True, frame: bool | None = None):
    return _c().data(indicator, entities, start, end, source, as_of, projections, frame)


def forecast(indicator: str, entity: str, horizon: int = 10):
    return _c().forecast(indicator, entity, horizon)


def chart(indicator: str, entities=None, start: int | None = None, end: int | None = None, path: str | None = None):
    return _c().chart(indicator, entities, start, end, path)


def events(entities=None, kinds=None, start=None, end=None, q: str | None = None, limit: int = 500):
    return _c().events(entities, kinds, start, end, q, limit)


def crowd(country: str | None = None, q: str | None = None, status: str = "open", limit: int = 50):
    return _c().crowd(country, q, status, limit)


def predictions(entity: str | None = None, indicator: str | None = None, state: str | None = None):
    return _c().predictions(entity, indicator, state)


def predict(**fields):
    return _c().predict(**fields)


def alike(entity: str, preset: str = "everything", year: int | None = None, n: int = 10):
    return _c().alike(entity, preset, year, n)


def synthetic(entity: str, indicator: str, year: int, start: int | None = None, pool=None):
    return _c().synthetic(entity, indicator, year, start, pool)


__all__ = ["ApiOff", "Client", "WorldmodelError", "connect", "countries", "indicators", "search", "data", "forecast", "chart",
           "events", "crowd", "predictions", "predict", "alike", "synthetic"]
