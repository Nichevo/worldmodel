"""The client: one method per call of the public API (/api/public/v1)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx


class WorldmodelError(RuntimeError):
    """The app answered with an error (its message says what to do)."""


class ApiOff(WorldmodelError):
    """The public API is switched off in the app (Settings > API access)."""


def _ids(x) -> str | None:
    if x is None:
        return None
    return x if isinstance(x, str) else ",".join(x)


class Client:
    def __init__(self, url: str | None = None, key: str | None = None, timeout: float = 120, http: httpx.Client | None = None):
        """url: the app (default WORLDMODEL_URL, else http://localhost:3030); key: from Settings > API access,
        needed from another PC (default WORLDMODEL_KEY). http: a ready httpx client (for tests)."""
        self.url = (url or os.environ.get("WORLDMODEL_URL") or "http://localhost:3030").rstrip("/")
        self.key = key or os.environ.get("WORLDMODEL_KEY")
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        self._http = http or httpx.Client(base_url=f"{self.url}/api/public/v1", headers=headers, timeout=timeout)

    def _get(self, path: str, raw: bool = False, **params):
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = self._http.get(path, params=params)
        except httpx.ConnectError as exc:
            raise WorldmodelError(f"Cannot reach the app at {self.url}: is it running (start.bat)?") from exc
        return self._check(r, raw)

    def _check(self, r: httpx.Response, raw: bool = False):
        if r.status_code >= 400:
            try:
                msg = r.json().get("detail", r.text)
            except ValueError:
                msg = r.text
            if r.status_code == 403 and "switched off" in str(msg):
                raise ApiOff(str(msg))
            raise WorldmodelError(f"{r.status_code}: {msg}")
        return r if raw else r.json()

    # ------------------------------------------------------------------ calls
    def countries(self, type: str | None = None) -> list[dict]:
        return self._get("/countries", type=type)

    def indicators(self, q: str | None = None) -> list[dict]:
        return self._get("/indicators", q=q)

    def search(self, q: str, limit: int = 20) -> list[dict]:
        return self._get("/search", q=q, limit=limit)

    def data(self, indicator: str, entities=None, start: int | None = None, end: int | None = None, source: str | None = None,
             as_of: str | None = None, projections: bool = True, frame: bool | None = None):
        """Figures for one indicator: entity, year, value, status (estimate or projection), source, vintage.
        A pandas DataFrame when pandas is installed (frame=False for plain rows)."""
        out = self._get("/data", indicator=indicator, entities=_ids(entities), **{"from": start, "to": end}, source=source,
                        as_of=as_of, projections=str(projections).lower())
        rows = out["rows"]
        if frame is not False:
            try:
                import pandas as pd
            except ImportError:
                if frame:
                    raise
                return rows
            df = pd.DataFrame(rows)
            df.attrs.update({"indicator": indicator, "name": out["name"], "unit": out["unit"]})
            return df
        return rows

    def forecast(self, indicator: str, entity: str, horizon: int = 10) -> dict:
        return self._get("/forecast", indicator=indicator, entity=entity, horizon=horizon)

    def chart(self, indicator: str, entities=None, start: int | None = None, end: int | None = None,
              path: str | None = None) -> str:
        """A line chart as SVG text; with path, saved there too."""
        svg = self._get("/chart.svg", raw=True, indicator=indicator, entities=_ids(entities) or "NZL",
                        **{"from": start, "to": end}).text
        if path:
            Path(path).write_text(svg, encoding="utf-8")
        return svg

    def events(self, entities=None, kinds=None, start=None, end=None, q: str | None = None, limit: int = 500) -> list[dict]:
        return self._get("/events", entities=_ids(entities), kinds=_ids(kinds), start=start, end=end, q=q, limit=limit)

    def crowd(self, country: str | None = None, q: str | None = None, status: str = "open", limit: int = 50) -> dict:
        return self._get("/crowd", country=country, q=q, status=status, limit=limit)

    def predictions(self, entity: str | None = None, indicator: str | None = None, state: str | None = None) -> list[dict]:
        return self._get("/predictions", entity=entity, indicator=indicator, state=state)

    def predict(self, **fields) -> dict:
        """Add a prediction to the app's log: question, kind (binary, number, date), due, chance or value, ..."""
        fields.setdefault("who_kind", "app")
        fields.setdefault("who", "Python client")
        return self._check(self._http.post("/predictions", json=fields))

    def alike(self, entity: str, preset: str = "everything", year: int | None = None, n: int = 10) -> dict:
        return self._get("/alike", entity=entity, preset=preset, year=year, n=n)

    def synthetic(self, entity: str, indicator: str, year: int, start: int | None = None, pool=None) -> dict:
        return self._get("/synthetic", entity=entity, indicator=indicator, year=year, start=start, pool=_ids(pool))
