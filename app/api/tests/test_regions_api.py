"""Regions inside a country: the US states and a state's counties, their outlines and one region's
figures ranked against the others, on a copy of the sample warehouse with three states and two
counties added."""

import json
import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_api import core


def square(x, y):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.execute("INSERT INTO vintages VALUES ('ustest', 'v1', 'v1', now(), 'x', 0, 'test', true)")
    places = [("US-CA", "California", "USA", "state"), ("US-TX", "Texas", "USA", "state"), ("US-VT", "Vermont", "USA", "state"),
              ("US-06037", "Los Angeles County, CA", "US-CA", "county"), ("US-06001", "Alameda County, CA", "US-CA", "county")]
    for eid, nm, parent, level in places:
        con.execute("INSERT INTO entities (entity_id, name, short_name, type) VALUES (?, ?, ?, 'subnational')", [eid, nm, nm])
        con.execute("INSERT INTO subdivisions VALUES (?, ?, ?, ?)", [eid, parent, level, eid[3:]])
    for i, u in (("usreg_population", "people"), ("usreg_median_household_income", "US$")):
        con.execute("INSERT INTO indicators (indicator_id, name, domain, unit, decimals, frequency) VALUES (?, ?, 'population', ?, 0, 'A')",
                    [i, i.replace("_", " "), u])
        con.execute("INSERT INTO indicator_sources VALUES (?, 'ustest', ?, 1, 1, '')", [i, i])
    obs = [("US-CA", "usreg_population", 2023, 39.0e6), ("US-TX", "usreg_population", 2023, 30.5e6),
           ("US-VT", "usreg_population", 2023, 0.65e6), ("US-CA", "usreg_population", 2022, 39.1e6),
           ("US-CA", "usreg_median_household_income", 2023, 91905), ("US-TX", "usreg_median_household_income", 2023, 73035),
           ("US-06037", "usreg_population", 2023, 9.7e6), ("US-06001", "usreg_population", 2023, 1.6e6)]
    con.executemany("INSERT INTO observations (entity_id, indicator_id, period_start, freq, breakdown, variant, source_id, vintage, value, status) "
                    "VALUES (?, ?, ?, 'A', '', 'central', 'ustest', 'v1', ?, 'E')", [(e, i, date(y, 1, 1), v) for e, i, y, v in obs])
    for (eid, nm, parent, level), (x, y) in zip(places, ((-120, 36), (-100, 31), (-73, 44), (-118, 34), (-122, 37.6))):
        con.execute("INSERT INTO geo_features VALUES ('regions', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'us_shapes', 'v1')",
                    [eid, nm, 1 if level == "state" else 2, json.dumps({"level": level, "parent": parent}), "USA", x, y, x + 1, y + 1,
                     json.dumps(square(x, y))])
    con.close()
    core.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    core.warehouse = Warehouse(str(SAMPLE))


def test_states_and_counties(client):
    us = client.get("/api/v1/regions/USA").json()
    assert [r["entity_id"] for r in us["regions"]] == ["US-CA", "US-TX", "US-VT"] and us["regions"][0]["level"] == "state"
    pop = next(m for m in us["measures"] if m["indicator_id"] == "usreg_population")
    assert pop["values"]["US-TX"] == {"2023": 30.5e6} and pop["source_id"] == "ustest"
    ca = client.get("/api/v1/regions/US-CA").json()
    assert {r["entity_id"] for r in ca["regions"]} == {"US-06037", "US-06001"}


def test_shapes(client):
    states = client.get("/api/v1/region-shapes/USA").json()
    assert sorted(f["id"] for f in states["features"]) == ["US-CA", "US-TX", "US-VT"]
    counties = client.get("/api/v1/region-shapes/USA", params={"level": "county"}).json()
    assert sorted(f["properties"]["id"] for f in counties["features"]) == ["US-06001", "US-06037"]
    assert client.get("/api/v1/region-shapes/US-CA").json()["features"][0]["properties"]["level"] == "county"


def test_facts_and_entity(client):
    f = client.get("/api/v1/region-facts/US-TX").json()
    assert f["place"]["parent_id"] == "USA" and f["place"]["children"] == 0
    pop = next(x for x in f["facts"] if x["indicator_id"] == "usreg_population")
    assert (pop["rank"], pop["of"], pop["middle"], pop["year"]) == (2, 3, 30.5e6, 2023)
    la = next(x for x in client.get("/api/v1/region-facts/US-06037").json()["facts"] if x["indicator_id"] == "usreg_population")
    assert (la["rank"], la["of"], la["parent_value"]) == (1, 2, 39.0e6)  # the state's own figure beside the county's
    e = client.get("/api/v1/entities/US-CA").json()
    assert e["subdivision"]["level"] == "state" and e["subdivision"]["children"] == 2
    assert client.get("/api/v1/entities/NZL").json()["subdivision"] is None


def test_all_counties_one_figure(client):
    c = client.get("/api/v1/regions/USA", params={"level": "county", "indicator": "usreg_population"}).json()
    assert c["level"] == "county" and len(c["regions"]) == 2 and c["regions"][0]["parent_id"] == "US-CA"
    pop = next(m for m in c["measures"] if m["indicator_id"] == "usreg_population")
    assert pop["values"]["US-06037"] == {"2023": 9.7e6} and pop["years"] == [2023]


def test_region_countries(client):
    got = {r["entity_id"]: r for r in client.get("/api/v1/region-countries").json()}
    assert got["USA"]["regions"] == 3 and got["USA"]["below"] == 2 and got["NZL"]["regions"] == 16
