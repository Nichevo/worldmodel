"""Live hazard layers: fires gathered into cells and counted by country, hot cities, reef alerts."""

import json

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import hazards, main
from worldmodel_api.warehouse import SAMPLE, Warehouse

FIRMS_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
-33.861,151.101,330.1,0.4,0.4,2026-11-12,0312,N20,VIIRS,n,2.0NRT,290.1,12.5,D
-33.862,151.102,331.0,0.4,0.4,2026-11-13,0312,N20,VIIRS,h,2.0NRT,291.0,7.5,D
-33.9,151.12,300.0,0.4,0.4,2026-11-13,0312,N20,VIIRS,l,2.0NRT,280.0,1.0,D
-10.0,-60.0,340.0,0.4,0.4,2026-11-13,0312,N20,VIIRS,n,2.0NRT,295.0,30.0,D
"""


def setup_function():
    hazards._cache.clear()


def test_fire_cells_drop_low_confidence_and_gather():
    cells = hazards.fire_cells(FIRMS_CSV)
    assert len(cells) == 2
    syd = next(c for c in cells if c["lat"] < -30)
    assert syd["n"] == 2 and syd["frp"] == 20 and syd["date"] == "2026-11-13"


def test_fires_layer_counts_by_country():
    got = hazards.fires("24h", True, fetch=lambda url: FIRMS_CSV)
    assert got["fires"] == 3 and len(got["features"]) == 2
    assert got["countries"].get("AUS") == 2 and got["countries"].get("BRA") == 1
    assert hazards.country("AUS", True, [])["fires"] == 2


def test_fires_failure_says_why_and_is_not_kept():
    def boom(url):
        raise OSError("down")
    got = hazards.fires("7d", True, fetch=boom)
    assert got["features"] == [] and "FIRMS" in got["note"]
    assert "fires:7d" not in hazards._cache
    assert "off" in hazards.fires("24h", False)["note"]


def test_heat_cities_need_two_hot_days():
    cities = [{"name": "Perth", "country": "AUS", "lon": 115.86, "lat": -31.95}, {"name": "Auckland", "country": "NZL", "lon": 174.76, "lat": -36.85}]
    reply = [{"daily": {"time": ["2026-11-13", "2026-11-14", "2026-11-15"], "temperature_2m_max": [36.2, 38.9, 30.0]}},
             {"daily": {"time": ["2026-11-13", "2026-11-14", "2026-11-15"], "temperature_2m_max": [19.0, 35.5, 20.0]}}]
    got = hazards.heat(cities, True, fetch=lambda url, params: json.dumps(reply))
    assert [f["properties"]["name"] for f in got["features"]] == ["Perth"]
    p = got["features"][0]["properties"]
    assert p["peak"] == 38.9 and p["day"] == "2026-11-14" and p["days"] == 2
    assert hazards.heat([], True)["note"]


def test_coral_takes_the_highest_level_in_each_region():
    csv_text = ("time,latitude,longitude,CRW_BAA_7D_MAX\nUTC,degrees_north,degrees_east,1\n"
                "2026-11-12T12:00:00Z,-12.0,143.0,NaN\n2026-11-12T12:00:00Z,-12.25,143.0,1\n2026-11-12T12:00:00Z,-12.5,143.0,3\n")
    assert hazards.reef_level(csv_text) == (3, "2026-11-12")
    got = hazards.coral(True, fetch=lambda q: csv_text)
    assert len(got["features"]) == len(hazards.REEFS)
    assert got["features"][0]["properties"]["label"] == "Alert level 1" and got["date"] == "2026-11-12"
    nzl = hazards.country("FJI", True, [])
    assert nzl["reefs"][0]["name"] == "Fiji"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    return TestClient(main.app)


def test_layer_route_reads_live(client, monkeypatch):
    monkeypatch.setattr(hazards, "_get", lambda url, params=None, timeout=60: FIRMS_CSV)
    got = client.get("/api/v1/layers/fires_now").json()
    assert got["fires"] == 3
    assert client.get("/api/v1/hazards/AUS").json()["fires"] == 2


def test_land_cover_summary():
    from worldmodel_api import look
    rows = [{"i": "lc_built_pct", "y": 1992, "v": 0.4}, {"i": "lc_built_pct", "y": 2022, "v": 0.56},
            {"i": "lc_trees_pct", "y": 1992, "v": 37.0}, {"i": "lc_trees_pct", "y": 2022, "v": 37.5},
            {"i": "lc_grass_pct", "y": 1992, "v": 56.0}, {"i": "lc_grass_pct", "y": 2022, "v": 53.0}]

    def q(sql, params):
        return [{"n": "New Zealand"}] if "entities" in sql else rows
    got = look.land_cover(q, "NZL")
    assert [p["id"] for p in got["parts"]] == ["trees", "grass", "built"]
    assert got["finding"] == "New Zealand: built-up land up 40%; grassland down 5% since 1992"
