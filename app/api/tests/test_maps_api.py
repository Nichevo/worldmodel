"""Maps: picture tiles saved on this PC, the Solar system downloads, and totals told in
countries. Network calls are replaced."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, space, tiles


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    return TestClient(main.app)


class FakeHttp:
    def __init__(self):
        self.urls = []

    def get(self, url, params=None):
        self.urls.append(url)
        return httpx.Response(200, content=b"PNG" + url.encode()[-12:], headers={"content-type": "image/png"},
                              request=httpx.Request("GET", url))


def test_tile_maths():
    assert tiles.tile_of(0, 0, 1) == (1, 1)
    assert tiles.tile_of(-180, 85, 2) == (0, 0)
    assert tiles.count(tiles.WORLD, 0, 2) == 1 + 4 + 16
    # A box across the date line counts both sides
    nz_chathams = (172.0, -45.0, -176.0, -43.0)
    assert {x for x, _ in tiles.tiles_in(nz_chathams, 3)} == {7, 0}
    assert tiles.country_box("NZL")[0] > 160


def test_save_serve_and_delete(client, monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(tiles, "_http", lambda: fake)
    monkeypatch.setattr(tiles, "_queue", lambda items: [tiles._save_one(a) for a in items] and {"state": "done"})
    chk = client.post("/api/v1/tiles/check", json={"set": "relief", "bbox": [170, -45, 175, -40], "maxzoom": 4}).json()
    assert chk["fits"] and chk["tiles"] == tiles.count((170, -45, 175, -40), 0, 4) == 7
    assert client.post("/api/v1/tiles/save", json={"set": "relief", "country": "NZL", "maxzoom": 4}).status_code == 200
    st = client.get("/api/v1/tiles").json()
    assert st["areas"][0]["name"] == "NZL" and st["areas"][0]["bytes"] > 0
    n = len(fake.urls)
    x, y = tiles.tile_of(172, -42, 4)
    r = client.get(f"/api/v1/tiles/relief/4/{x}/{y}")
    assert r.status_code == 200 and r.content.startswith(b"PNG") and len(fake.urls) == n  # served from disk
    client.get("/api/v1/tiles/relief/9/1/1")
    assert len(fake.urls) == n + 1  # not saved: fetched online
    assert client.post("/api/v1/tiles/check", json={"set": "nonsense", "bbox": [0, 0, 1, 1], "maxzoom": 2}).status_code == 422
    area = st["areas"][0]["id"]
    assert client.delete(f"/api/v1/tiles/areas/{area}").status_code == 200
    assert not tiles.path_of("relief", "-", 4, x, y).exists()
    assert client.get("/api/v1/tiles").json()["areas"] == []


def test_night_lights_urls():
    assert "VIIRS_Black_Marble/default/2012-01-01" in tiles.upstream("night", 3, 1, 2, "2012")
    assert "DayNightBand" in tiles.upstream("night", 3, 1, 2, "latest")
    assert tiles._time("night", "latest")[0].startswith("latest-")


def test_space_readers():
    answer = {"fields": space.FIELDS.split(","), "data": [
        ["1 Ceres", "2.77", "0.0786", "10.6", "80.3", "73.6", "60.1", "2460600.5", None, "G", "N", "MBA", "939.4", "0.09", "3.3"],
        ["433 Eros", "1.458", "0.223", "10.8", "304.3", "178.9", "310.5", "2460600.5", "S", "S", "Y", "AMO", "16.8", "0.25", "10.4"],
        ["X", "3.0", "0.1", "1", "1", "1", "1", "2460600.5", None, None, "N", "MBA", None, "0.05", "12"],
        ["bad", None, "0.1", "1", "1", "1", "1", "2460600.5", None, None, "N", "MBA", None, None, "12"],
    ]}
    rows = space.asteroid_rows(answer, "main belt")
    assert [(r[0], r[8], r[9], r[10]) for r in rows] == [("1 Ceres", "C", True, False), ("433 Eros", "S", True, True), ("X", "C", False, False)]
    text = "head\n$$SOE\n2443400.5, A.D. 1977-Sep-06, 0.98, 0.15, 0.0,\n2443415.5, A.D. 1977-Sep-21, 0.97, 0.25, 0.001,\n$$EOE\nfoot"
    assert space.horizons_rows({"result": text}) == [[2443400.5, 0.98, 0.15, 0.0], [2443415.5, 0.97, 0.25, 0.001]]
    with pytest.raises(ValueError):
        space.horizons_rows({"result": "No ephemeris for target \"x\" prior to A.D. 2000"})
    assert space.spec_kind("Xc") == "X" and space.spec_kind("V") == "V" and space.spec_kind("") is None


def test_space_endpoints(client, monkeypatch):
    started = []
    monkeypatch.setattr(space, "start", lambda force=False: started.append(force) or {"state": "running"})
    st = client.get("/api/v1/space").json()
    assert st["due"] and started == [False] and len(st["missions"]) >= 20  # first visit starts the download
    assert client.get("/api/v1/space/asteroids").status_code == 404
    space._write("asteroids.json", {"fetched": "2099-01-01T00:00:00+00:00", "rows": [["1 Ceres", 2.77]]})
    assert client.get("/api/v1/space/asteroids").json()["rows"][0][0] == "1 Ceres"


def test_size_in_countries(client):
    r = client.get("/api/v1/size-in-countries", params={"indicator": "pop_total", "step": 5, "start": 2000}).json()
    row = r["rows"][0]
    assert row["from"] == 2000 and row["year"] == 2005 and row["value"] > 0
    assert row["match"]["id"] != "world" and row["in_unit"] > 10  # world growth is many New Zealands
    lv = client.get("/api/v1/size-in-countries", params={"indicator": "pop_total", "what": "level", "entity": "NZL", "start": 2020}).json()
    assert lv["rows"][0]["in_unit"] == pytest.approx(1.0)
    assert client.get("/api/v1/size-in-countries", params={"indicator": "nonsense"}).status_code == 404
