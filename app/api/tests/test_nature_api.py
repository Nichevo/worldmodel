"""Climate zones, pollution and nature endpoints, against a copy of the sample warehouse
with a small zone grid, cities, protected areas, species and pests added."""

import shutil
import struct
import zlib

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, nature
from worldmodel_api.warehouse import SAMPLE, Warehouse


def _grid(nz_north: int) -> bytes:
    """A 1° grid: New Zealand Cfb (15), its north nz_north; Sydney's cell Cfa (14); Brisbane Cwa (11)."""
    g = bytearray(180 * 360)

    def put(lat0, lat1, lon0, lon1, z):
        for r in range(180):
            lat = 90 - (r + 0.5)
            if lat0 <= lat <= lat1:
                for c in range(360):
                    lon = -180 + c + 0.5
                    if lon0 <= lon <= lon1:
                        g[r * 360 + c] = z
    put(-47, -34, 166, 179, 15)
    put(-40, -34, 166, 179, nz_north)
    put(-35, -33, 150, 152, 14)
    put(-28, -27, 152, 154, 11)
    return zlib.compress(bytes(g))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.executemany("INSERT INTO zone_grids VALUES (?, ?, 360, 180, ?, 'koppen_beck', 'v1')", [
        ("1991-2020", "historical", _grid(15)), ("2071-2099", "ssp245", _grid(14)), ("2071-2099", "ssp585", _grid(1))])
    con.execute("""CREATE TABLE cities (city_id VARCHAR, name VARCHAR, ascii_name VARCHAR, synonyms VARCHAR, country_id VARCHAR,
        admin1 VARCHAR, lat DOUBLE, lon DOUBLE, population DOUBLE, capital VARCHAR, feature_code VARCHAR, timezone VARCHAR,
        elevation DOUBLE, source_id VARCHAR, vintage VARCHAR)""")
    con.executemany("INSERT INTO cities VALUES (?, ?, ?, '', ?, '', ?, ?, ?, '', 'PPL', '', NULL, 'geonames', 'v1')", [
        ("2193733", "Auckland", "Auckland", "NZL", -36.85, 174.76, 1_600_000),
        ("2179537", "Wellington", "Wellington", "NZL", -41.29, 174.78, 420_000),
        ("2147714", "Sydney", "Sydney", "AUS", -33.87, 151.21, 5_000_000),
        ("2174003", "Brisbane", "Brisbane", "AUS", -27.47, 153.03, 2_400_000)])
    con.execute("""INSERT INTO protected_areas VALUES ('54', 'Abel Tasman National Park', 'National Park', 'II', 'NZL', '0', 225.3,
        1942, -40.8, 172.4, 172.0, -41.0, 172.8, -40.5, '{"type":"Polygon","coordinates":[[[172,-41],[172,-40.5],[172.8,-40.5],[172.8,-41],[172,-41]]]}',
        'wdpa', 'v1')""")
    con.execute("INSERT INTO species_status VALUES ('NZL', 'Strigops habroptila', 'CR', 2021, 'u', 'iucn_redlist', 'v1')")
    con.execute("INSERT INTO pest_presence VALUES ('DACUTR', 'Queensland fruit fly', 'NZL', NULL, 'Transient', true, 'eppo_pests', 'v1')")
    con.close()
    main.warehouse = Warehouse(str(db))
    nature._grids.clear()
    nature._tiles.clear()
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))
    nature._grids.clear()
    nature._tiles.clear()


def _png_pixels(png: bytes) -> tuple[int, int, bytes]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    i, w, h, idat = 8, 0, 0, b""
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        kind, body = png[i + 4:i + 8], png[i + 8:i + 8 + n]
        if kind == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        i += 12 + n
    return w, h, zlib.decompress(idat)


def test_zone_tiles(client):
    r = client.get("/api/v1/climatezones/tiles/1991-2020/ssp245/0/0/0.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    w, h, raw = _png_pixels(r.content)
    assert (w, h) == (256, 256) and len(raw) == 256 * 257
    assert set(raw[1::257]) <= set(range(31)) and 15 in raw  # palette indices are zone numbers; New Zealand shows
    g = client.get("/api/v1/climatezones/tiles/2071-2099/ssp585/0/0/0.png?groups=true")
    assert 1 in _png_pixels(g.content)[2]  # group A (tropical) under SSP5-8.5 in the fixture
    assert client.get("/api/v1/climatezones/tiles/2041-2070/ssp245/0/0/0.png").status_code == 404
    assert client.get("/api/v1/climatezones/tiles/bad/ssp245/0/0/0.png").status_code == 404
    over = client.get("/api/v1/climatezones").json()
    assert len(over["zones"]) == 30 and over["zones"][14]["code"] == "Cfb" and over["scenario"] == "ssp245"
    assert {"period": "2071-2099", "scenario": "ssp585"} in over["periods"]


def test_zones_country_twins(client):
    r = client.get("/api/v1/climatezones/country/NZL").json()
    auck = next(t for t in r["twins"] if t["name"] == "Auckland")
    assert auck["now"] == "Cfb" and auck["later"] == "Cfa" and auck["twin"]["name"] == "Sydney"
    well = next(t for t in r["twins"] if t["name"] == "Wellington")
    assert well["now"] == well["later"] == "Cfb" and well["twin"] is None
    assert r["people"] == {"Cfb": 100.0}
    city = client.get("/api/v1/climatezones/city/2193733?scenario=ssp585").json()
    assert city["periods"]["2071-2099"]["later"] == "Af" and city["periods"]["2041-2070"] is None


def test_pollution_nature_and_pledges(client):
    p = client.get("/api/v1/pollution").json()
    assert set(p["tabs"]) == {"air", "water", "ocean", "borders"}
    assert any(e["title"].startswith("Australian bushfire smoke") and e["entities"] == ["AUS", "NZL"] for e in p["events"])
    n = client.get("/api/v1/nature").json()
    fly = next(x for x in n["pests"] if x["code"] == "DACUTR")
    assert fly["countries"] == 1 and n["protected"]["n"] == 1 and n["comebacks"]
    c = client.get("/api/v1/nature/country/NZL").json()
    assert c["species"][0]["scientific_name"] == "Strigops habroptila"
    assert next(x for x in c["pests"] if x["code"] == "DACUTR")["here"]["present"] is True
    assert any(e["kind"] == "animal_disease" for e in c["events"]) and any(r["name"] == "Zealandia ecosanctuary" for r in c["restoration"])
    pl = client.get("/api/v1/climate/pledges/NZL").json()
    assert pl["pledges"][0]["year"] == 2030 and pl["pledges"][0]["cut"] == 50


def test_protected_areas_by_window_across_the_date_line(client):
    r = client.get("/api/v1/nature/protected?west=160&south=-50&east=200&north=-30").json()
    assert [f["properties"]["name"] for f in r["features"]] == ["Abel Tasman National Park"]
    r = client.get("/api/v1/nature/protected?west=-20&south=-50&east=20&north=-30").json()
    assert r["features"] == []
