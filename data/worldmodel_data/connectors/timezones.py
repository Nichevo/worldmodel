"""Time zones for the map.

tz_boundaries
    Evan Siroky's timezone-boundary-builder (data under the Open Database License, built
    from OpenStreetMap): the outline of every IANA time zone, out at sea too (the nautical
    zones Etc/GMT+12 to Etc/GMT-12 cover open water). The "now" release merges zones that
    keep the same clocks from today on, so there are about 300 shapes rather than 450.
    Simplified to about 1 km and kept as the map layer timezones; each zone's offset,
    daylight saving and local time are worked out in the browser from its IANA name, so
    they are right on the day you look. If the download fails, save
    timezones-with-oceans-now.geojson.zip (or the plain .geojson) from the project's
    releases page into var\\manual\\tz_boundaries.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.transport import stage_geo

log = logging.getLogger(__name__)

TZB = "https://github.com/evansiroky/timezone-boundary-builder/releases/latest/download/"
# Tried in turn: the merged "now" zones, then every zone (older releases have no "now" file).
TZB_FILES = ("timezones-with-oceans-now.geojson.zip", "timezones-with-oceans.geojson.zip")
TZ_TOL = 0.01  # degrees, about 1 km


def _rings(geom) -> list[list[list[float]]]:
    out = []
    for ring in [geom.exterior, *geom.interiors]:
        r = [[round(x, 3), round(y, 3)] for x, y, *_ in ring.coords]
        if len(r) >= 4:
            if r[0] != r[-1]:
                r.append(r[0])
            out.append(r)
    return out


def zone_geometry(geometry: dict, tol: float = TZ_TOL) -> dict | None:
    """A zone's (multi)polygon simplified (shared edges kept as close as shapely can), or None."""
    from shapely.geometry import shape

    try:
        g = shape(geometry)
    except Exception:  # noqa: BLE001 - a broken outline is skipped
        return None
    if g.is_empty:
        return None
    if not g.is_valid:
        g = g.buffer(0)
    g = g.simplify(tol, preserve_topology=True)
    polys = [_rings(p) for p in getattr(g, "geoms", [g]) if hasattr(p, "exterior") and not p.is_empty]
    polys = [p for p in polys if p]
    if not polys:
        return None
    return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}


def zone_rows(features: list[dict]) -> list[tuple]:
    """geo_features rows (layer timezones): one per zone, named by its IANA id."""
    rows = []
    for ft in features:
        p = ft.get("properties") or {}
        tz = str(p.get("tzid") or p.get("TZID") or "").strip()
        if not tz:
            continue
        geom = zone_geometry(ft.get("geometry") or {})
        if geom:
            rows.append(("timezones", tz, tz, 1, {"tz": tz, "sea": tz.startswith("Etc/")}, [], geom))
    return rows


def read_features(path: Path) -> list[dict]:
    """The features of a timezone-boundary-builder file: a .zip holding one .geojson, or the .geojson itself."""
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if n.lower().endswith((".geojson", ".json"))), None)
                if not name:
                    return []
                with z.open(name) as f:
                    d = json.load(f)
        else:
            d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        log.warning("tz_boundaries: could not read %s (%s)", path.name, e)
        return []
    return (d.get("features") or []) if isinstance(d, dict) else []


class TimezoneBoundaries(Connector):
    source_id = "tz_boundaries"
    switch = "timezones_fetch"
    fetch_every_days = 180  # a new release follows each IANA time zone database release, a few a year

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        last: Exception | None = None
        for name in TZB_FILES:
            try:
                self.get(TZB + name, raw_dir / name)
                return TZB + name
            except Exception as e:  # noqa: BLE001 - the next file is tried
                last = e
        raise ConnectorError(f"tz_boundaries: could not download the time zone outlines ({last})")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted((f for f in raw_dir.iterdir() if f.suffix.lower() in (".zip", ".geojson", ".json")),
                       key=lambda f: ("now" not in f.name, f.name))  # the merged "now" file first
        rows: list[tuple] = []
        for f in files:
            rows = zone_rows(read_features(f))
            if rows:
                break
        if not rows:
            raise ConnectorError(f"tz_boundaries: no time zone outlines read from {raw_dir}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("tz_boundaries: %s time zones", len(rows))
        return EMPTY_OBSERVATIONS
