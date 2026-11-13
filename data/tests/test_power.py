"""Power plants (WRI) and power lines (gridfinder GeoPackage) on small fixtures made in the test."""

import json
import sqlite3
import struct

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.power import _gpkg_wkb, _wkb_lines, grid_rows
from worldmodel_data.vintage_store import VintageStore

GPPD = """country,country_long,name,gppd_idnr,capacity_mw,latitude,longitude,primary_fuel,other_fuel1,commissioning_year,owner
NZL,New Zealand,Manapouri,NZL0001,850,-45.52,167.28,Hydro,,1971,Meridian Energy
NZL,New Zealand,Wairakei,NZL0002,161,-38.62,176.10,Geothermal,,1958,Contact Energy
NZL,New Zealand,Nowhere,NZL0003,10,,,Wind,,,
AUS,Australia,Odd plant,AUS0001,5,-30.0,150.0,Hamster wheel,,2001,
"""


def line_wkb(points, order="<"):
    b = struct.pack(order + "bII", 1 if order == "<" else 0, 2, len(points))
    for x, y in points:
        b += struct.pack(order + "dd", x, y)
    return b


def gpkg_blob(wkb: bytes) -> bytes:
    # magic, version 0, flags: little-endian with a 2D envelope (code 1: 32 bytes), srs 4326
    return b"GP" + bytes([0, 0b00000011]) + struct.pack("<i", 4326) + struct.pack("<4d", 0, 1, 0, 1) + wkb


def make_gpkg(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT)")
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('grid', 'geom')")
    con.execute("CREATE TABLE grid (fid INTEGER PRIMARY KEY, geom BLOB, source TEXT)")
    con.execute("INSERT INTO grid (geom, source) VALUES (?, 'osm')", [gpkg_blob(line_wkb([(174.70, -36.90), (174.75, -36.85), (174.80, -36.80)]))])
    con.execute("INSERT INTO grid (geom, source) VALUES (?, 'gridfinder')", [gpkg_blob(line_wkb([(174.2, -36.5), (174.4, -36.3)], ">"))])
    con.execute("INSERT INTO grid (geom, source) VALUES (?, 'osm')", [gpkg_blob(line_wkb([(174.71, -36.91), (174.72, -36.92)]))])
    con.commit()
    con.close()


def test_geopackage_lines(tmp_path):
    assert _wkb_lines(_gpkg_wkb(gpkg_blob(line_wkb([(1, 2), (3, 4)])))) == [[[1.0, 2.0], [3.0, 4.0]]]
    path = tmp_path / "grid.gpkg"
    make_gpkg(path)
    rows = grid_rows(path)
    by = {r[1]: r for r in rows}
    assert set(by) == {"174_-37_1", "174_-37_2"}  # mapped and predicted kept apart, one row a 1° square
    assert by["174_-37_1"][3] == 1 and by["174_-37_1"][6]["type"] == "MultiLineString"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("power")
    (tmp / "wri").mkdir()
    (tmp / "wri" / "global_power_plant_database.csv").write_text(GPPD, encoding="utf-8")
    (tmp / "grid").mkdir()
    make_gpkg(tmp / "grid" / "grid.gpkg")
    home = Paths(tmp / "var")
    store = VintageStore(home)
    CONNECTORS["wri_gppd"]().ingest(store, tmp / "wri")
    CONNECTORS["gridfinder"]().ingest(store, tmp / "grid")
    result = build(home)
    return duckdb.connect(str(result.path), read_only=True)


def test_power_layers_built(built):
    fc = json.loads(built.execute("SELECT geojson FROM layers WHERE layer_id = 'power_plants'").fetchone()[0])
    props = [f["properties"] for f in fc["features"]]
    assert [p["name"] for p in props] == ["Manapouri", "Wairakei", "Odd plant"]  # biggest first; no place, no dot
    assert props[0] == {"name": "Manapouri", "fuel": "Hydro", "mw": 850.0, "year": 1971, "owner": "Meridian Energy", "country": "NZL"}
    assert props[2]["fuel"] == "Other"
    n = built.execute("SELECT count(*) FROM geo_features WHERE layer_id = 'power_lines'").fetchone()[0]
    assert n == 2
