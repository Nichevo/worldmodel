"""Power plants and power lines for the map's Energy layers (Settings > Transport and
networks, "Power plants and power lines").

wri_gppd
    WRI's Global Power Plant Database (version 1.3, CC BY 4.0): about 35,000 plants with
    their fuel, capacity (MW), owner and year built, from the CSV on WRI's GitHub. Stored as
    the map layer power_plants. The database stopped being updated in 2021.
gridfinder
    gridfinder (Arderne et al. 2020, CC BY 4.0, Zenodo): high and medium voltage lines,
    those mapped in OpenStreetMap and those predicted from night lights and roads, as one
    GeoPackage of about 700 MB. Read once and kept as lines simplified to about 1 km and
    gathered by 1° square (geo_features layer power_lines), mapped lines rank 1, predicted 2.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
import struct
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.networks import dp_line, lines_of, multiline
from worldmodel_data.connectors.tabular import num
from worldmodel_data.connectors.transport import stage_geo

log = logging.getLogger(__name__)

GPPD_URL = "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv"
GRIDFINDER_URL = "https://zenodo.org/records/3628142/files/grid.gpkg?download=1"
LINE_TOL = 0.01  # degrees (about 1 km) when simplifying power lines
FUELS = {"Hydro", "Geothermal", "Wind", "Solar", "Nuclear", "Coal", "Gas", "Oil", "Biomass", "Waste", "Storage", "Wave and Tidal",
         "Cogeneration", "Petcoke", "Other"}


def plant_features(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lat, lon = num(r.get("latitude")), num(r.get("longitude"))
            if lat is None or lon is None:
                continue
            fuel = (r.get("primary_fuel") or "Other").strip()
            year = num(r.get("commissioning_year"))
            out.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                "name": r.get("name"), "fuel": fuel if fuel in FUELS else "Other", "mw": round(num(r.get("capacity_mw")) or 0, 1) or None,
                "year": int(year) if year else None, "owner": (r.get("owner") or "").strip()[:80] or None, "country": r.get("country"),
            }))
    out.sort(key=lambda f: -(f["properties"].get("mw") or 0))
    return out


class WRIPowerPlants(Connector):
    source_id = "wri_gppd"
    switch = "power_fetch"
    fetch_every_days = 180

    def default_release(self, fetched_at: datetime) -> str:
        return "1.3.0"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "1.3.0"

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(GPPD_URL, raw_dir / "global_power_plant_database.csv")
        return GPPD_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv"))
        feats = plant_features(files[0]) if files else []
        if not feats:
            raise ConnectorError(f"wri_gppd: no power plants read in {raw_dir}")
        self.layers = [{"layer_id": "power_plants", "name": "Power plants", "kind": "point", "feature_count": len(feats),
                        "description": "Power plants sized by capacity and coloured by fuel (WRI Global Power Plant Database 1.3, 2021).",
                        "geojson": collection(feats)}]
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- GeoPackage lines
def _gpkg_wkb(blob: bytes) -> bytes:
    """The WKB inside a GeoPackage geometry blob (after its header and envelope)."""
    if blob[:2] != b"GP":
        return blob
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((flags >> 1) & 0x07, 0)
    return blob[8 + env:]


def _wkb_lines(b: bytes) -> list[list[list[float]]]:
    """Lines from a WKB LineString or MultiLineString (2D, or with Z/M dropped)."""
    out: list = []

    def read(i: int) -> int:
        order = "<" if b[i] == 1 else ">"
        (t,) = struct.unpack_from(order + "I", b, i + 1)
        dims = 3 if (t // 1000) in (1, 2) or t & 0x80000000 or t & 0x40000000 else 4 if t // 1000 == 3 else 2
        base = (t & 0xFFFF) % 1000
        i += 5
        if base == 2:
            (n,) = struct.unpack_from(order + "I", b, i)
            i += 4
            pts = struct.unpack_from(order + "d" * (n * dims), b, i)
            out.append([[pts[k], pts[k + 1]] for k in range(0, len(pts), dims)])
            return i + 8 * n * dims
        if base in (5, 7):  # MultiLineString, GeometryCollection
            (n,) = struct.unpack_from(order + "I", b, i)
            i += 4
            for _ in range(n):
                i = read(i)
            return i
        raise ValueError(f"geometry type {t}")
    read(0)
    return out


def grid_rows(path: Path, tol: float = LINE_TOL) -> list[tuple]:
    """geo_features rows: power lines simplified and gathered by 1° square and by mapped or predicted."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchall()
        if not tables:
            raise ConnectorError(f"gridfinder: no geometry table in {path.name}")
        table, gcol = tables[0]
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
        src = "source" if "source" in cols else None
        squares: dict[tuple[int, int, int], list] = defaultdict(list)
        for g, s in con.execute(f'SELECT "{gcol}", {f"{src}" if src else "NULL"} FROM "{table}"'):
            if not g:
                continue
            rank = 1 if s and "osm" in str(s).lower() else 2
            try:
                lines = _wkb_lines(_gpkg_wkb(bytes(g)))
            except (ValueError, struct.error):
                continue
            for ln in lines:
                if len(ln) < 2:
                    continue
                d = dp_line(ln, tol, 3)
                if not d:
                    continue
                squares[(int(d[0][0] // 1), int(d[0][1] // 1), rank)].append(d)
    finally:
        con.close()
    rows = []
    for (x, y, rank), lines in squares.items():
        rows.append(("power_lines", f"{x}_{y}_{rank}", "Power lines (mapped)" if rank == 1 else "Power lines (predicted)", rank,
                     {"rank": rank}, [], multiline(lines)))
    return rows


class Gridfinder(Connector):
    source_id = "gridfinder"
    switch = "power_fetch"
    fetch_every_days = 3650  # a 2020 release that is not updated: read once
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return "1.1.1"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "1.1.1"

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(GRIDFINDER_URL, raw_dir / "grid.gpkg")
        return GRIDFINDER_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.gpkg"))
        if not files:
            raise ConnectorError(f"gridfinder: grid.gpkg missing from {raw_dir}")
        rows = grid_rows(files[0])
        if not rows:
            raise ConnectorError(f"gridfinder: no power lines read in {files[0].name}")
        self.history_queries = {"geo_features": stage_geo(con, rows)}
        log.info("gridfinder: %s squares of power lines", len(rows))
        return EMPTY_OBSERVATIONS
