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


# ----------------------------------------------------------------------------- plant grounds (OpenStreetMap)
def _sq(lon, lat, d):
    return [{"lon": lon, "lat": lat}, {"lon": lon + d, "lat": lat}, {"lon": lon + d, "lat": lat + d}, {"lon": lon, "lat": lat + d},
            {"lon": lon, "lat": lat}]


OVERPASS = {"elements": [
    # Huntly-like coal and gas station: about 600 m square
    {"type": "way", "id": 11, "tags": {"power": "plant", "name": "Big Station", "plant:source": "coal;gas",
                                       "plant:output:electricity": "1,000 MW", "operator": "Genesis"},
     "geometry": _sq(175.15, -37.55, 0.006)},
    # a solar farm drawn as a relation of two open ways, with a hole
    {"type": "relation", "id": 22, "tags": {"power": "plant", "plant:source": "solar", "plant:output:electricity": "52 MWp"},
     "members": [
         {"type": "way", "role": "outer", "geometry": [{"lon": 172.0, "lat": -43.0}, {"lon": 172.01, "lat": -43.0}, {"lon": 172.01, "lat": -42.99}]},
         {"type": "way", "role": "outer", "geometry": [{"lon": 172.0, "lat": -43.0}, {"lon": 172.0, "lat": -42.99}, {"lon": 172.01, "lat": -42.99}]},
         {"type": "way", "role": "inner", "geometry": _sq(172.004, -42.996, 0.001)}]},
    # a plant that is one small building: left out
    {"type": "way", "id": 33, "tags": {"power": "plant", "plant:source": "hydro"}, "geometry": _sq(170.0, -45.0, 0.0002)},
    {"type": "node", "id": 44, "tags": {"power": "plant"}},
]}


def test_site_rows():
    from worldmodel_data.connectors.power import osm_mw, site_boxes, site_rows

    assert osm_mw({"plant:output:electricity": "1.2 GW"}) == 1200 and osm_mw({"plant:output:electricity": "500 kW"}) == 0.5
    assert osm_mw({"plant:output:electricity": "yes"}) is None
    assert site_boxes()[0] == (160, -60) and len(set(site_boxes())) == 126  # New Zealand first, each square once
    rows = {r[1]: r for r in site_rows(OVERPASS)}
    assert set(rows) == {"w11", "r22"}
    big = rows["w11"]
    assert big[2] == "Big Station" and big[4]["fuel"] == "Coal" and big[4]["mw"] == 1000 and big[4]["operator"] == "Genesis"
    assert big[3] == 2 and 30 < big[4]["ha"] < 40 and big[6]["type"] == "Polygon"
    solar = rows["r22"]
    assert solar[2] == "Solar power plant" and solar[4]["fuel"] == "Solar" and solar[4]["mw"] == 52
    assert len(solar[6]["coordinates"]) == 2  # the outer ring joined from two ways, and the hole
    assert solar[3] == 1 or solar[4]["ha"] > 70


def test_sites_built(tmp_path):
    tmp = tmp_path
    (tmp / "osm").mkdir()
    (tmp / "osm" / "osm_power_160_-60_20.json").write_text(json.dumps(OVERPASS), encoding="utf-8")
    home = Paths(tmp / "var")
    CONNECTORS["osm_power_sites"]().ingest(VintageStore(home), tmp / "osm")
    con = duckdb.connect(str(build(home).path), read_only=True)
    got = con.execute("SELECT feature_id, rank FROM geo_features WHERE layer_id = 'power_sites' ORDER BY 1").fetchall()
    assert [g[0] for g in got] == ["r22", "w11"]


def test_sites_download(tmp_path, monkeypatch):
    """Squares read in turn, one too big read as four, and a refusal stops the run."""
    from worldmodel_data.connectors import power

    class R:
        def __init__(self, code, body=b'{"elements": []}'):
            self.status_code, self.content = code, body

    asked = []
    late = b'{"elements": [], "remark": "runtime error: Query timed out in \\"query\\" at line 1 after 600 seconds."}'

    def post(url, data, timeout):
        asked.append(data["data"])
        n = len(asked)
        return R(200, late) if n == 2 else R(429) if n == 8 else R(200)

    c = CONNECTORS["osm_power_sites"]()
    c.gap = 0
    c._client = type("C", (), {"post": staticmethod(post)})()
    c.download(tmp_path, "2026-11-28")
    files = sorted(p.name for p in tmp_path.glob("osm_power_*.json"))
    assert len(asked) == 8 and len(files) == 6  # 1 whole square, 4 quarters, 1 more square, then refused
    assert "osm_power_160_-60_20.json" in files and any(f.endswith("_10.json") for f in files)
    done = json.loads((tmp_path / "fetched.json").read_text())
    assert len(done) == 3
