"""The Details page behind every map layer: by country, by group, sizes and categories, items
and a country's own counts, against a copy of the sample warehouse with a few hospitals and a
cable added. The live layers are tested with their fetch replaced."""

import json
import shutil

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import layer_details, main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    hospitals = [("Q1", "Auckland City Hospital", "NZL", 1100), ("Q2", "Christchurch Hospital", "NZL", 650),
                 ("Q3", "Small Clinic", "NZL", None), ("Q4", "Royal Brisbane", "AUS", 929)]
    con.executemany("INSERT INTO layer_items VALUES ('hospitals', ?, ?, ?, -37, 175, ?, NULL, NULL, '{}', false, 'wikidata_places', 'v1')",
                    hospitals)
    con.execute("""INSERT INTO geo_features VALUES ('cables', 'scn', 'Southern Cross NEXT', 1, ?, 'AUS,NZL,USA',
                   151.2, -33.9, 178.4, -18.1, '{"type":"LineString","coordinates":[[151.2,-33.9],[178.4,-18.1]]}', 'x', 'v1')""",
                [json.dumps({"length": "15,840 km", "owners": ["Spark", "Telstra"], "rfs": 2022})])
    con.close()
    layer_details._cache.clear()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))
    layer_details._cache.clear()


def test_by_country_with_sizes_and_coverage(client):
    got = client.get("/api/v1/layer-details/hospitals").json()
    assert got["totals"]["count"] == 4 and got["totals"]["with_size"] == 3
    assert got["layer"]["size"]["label"] == "Beds"
    nz = next(r for r in got["countries"] if r["entity_id"] == "NZL")
    assert nz["count"] == 3 and nz["size_total"] == 1750 and nz["with_size"] == 2
    assert nz["largest"] == {"name": "Auckland City Hospital", "size": 1100}
    assert nz["per_m"] is None or nz["per_m"] > 0
    assert len(nz["official"]) == 3  # national count, WHO density, World Bank beds (where the sample has them)
    bands = {b["label"]: b["count"] for b in got["sizes"]}
    assert bands["500 to 1,000"] == 2 and bands["no beds given"] == 1


def test_groups_add_up_their_members(client):
    got = client.get("/api/v1/layer-details/hospitals").json()
    oceania = [g for g in got["groups"] if {"NZL", "AUS"} <= set(_members(g["entity_id"]))]
    if oceania:
        assert oceania[0]["count"] >= 4


def _members(group):
    con = main.warehouse.cursor()
    return [r[0] for r in con.execute("SELECT member_id FROM memberships WHERE group_id = ?", [group]).fetchall()]


def test_items_biggest_first_and_by_country(client):
    got = client.get("/api/v1/layer-details/hospitals/items", params={"country": "NZL"}).json()
    assert got["total"] == 3
    assert [r["name"] for r in got["rows"]] == ["Auckland City Hospital", "Christchurch Hospital", "Small Clinic"]
    named = client.get("/api/v1/layer-details/hospitals/items", params={"q": "royal"}).json()
    assert named["rows"][0]["country_names"] == ["Australia"]


def test_lines_count_for_every_country_they_touch(client):
    got = client.get("/api/v1/layer-details/cables").json()
    assert {r["entity_id"] for r in got["countries"]} == {"AUS", "NZL", "USA"}
    assert got["totals"]["count"] == 1 and got["totals"]["size_total"] == 15840
    rows = client.get("/api/v1/layer-details/cables/items").json()["rows"]
    assert rows[0]["countries"] == ["AUS", "NZL", "USA"] and rows[0]["fields"]["owners"] == "Spark, Telstra"


def test_sample_layers_and_the_country_card(client):
    over = {r["id"]: r for r in client.get("/api/v1/layer-details").json()}
    assert over["airports"]["count"] > 1000 and over["hospitals"]["count"] == 4
    card = {r["layer_id"]: r for r in client.get("/api/v1/layer-details/country/NZL").json()}
    assert card["hospitals"]["count"] == 3 and card["hospitals"]["rank"] == 1
    assert card["hospitals"]["size"]["value"] == 1750
    cats = client.get("/api/v1/layer-details/airports").json()["categories"]
    assert {c["label"] for c in cats} >= {"large", "medium"}


def test_live_layers_are_counted_when_opened(client, monkeypatch):
    fires = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [150, -33]}, "properties": {"frp": 40, "country": "AUS"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [151, -33]}, "properties": {"frp": 10, "country": "AUS"}},
    ]}
    monkeypatch.setattr(main, "_live_layer", lambda layer_id: fires)
    got = client.get("/api/v1/layer-details/fires_now").json()
    assert got["countries"][0]["entity_id"] == "AUS" and got["countries"][0]["count"] == 2
    assert got["totals"]["size_total"] == 50


def test_layers_that_cannot_be_counted_say_why(client):
    r = client.get("/api/v1/layer-details/live_planes")
    assert r.status_code == 404 and "area in view" in r.json()["detail"]


def test_coverage_grades_every_country(client):
    got = client.get("/api/v1/layer-details/hospitals/coverage").json()
    assert {r["entity_id"] for r in got["countries"]} >= {"NZL", "AUS"}
    for r in got["countries"]:
        assert r["grade"] in ("good", "part", "thin", "unknown")
        if r["coverage"] is not None:
            assert r["official"] and r["basis"]
    assert sum(got["grades"].values()) == len(got["countries"])


def test_blank_spots_are_big_towns_with_nothing_near(client):
    got = client.get("/api/v1/layer-details/hospitals/gaps", params={"country": "NZL"}).json()
    assert got["km"] == 25 and got["people"] == 100_000
    for t in got["towns"]:
        assert t["entity_id"] == "NZL" and t["population"] >= 100_000
        assert t["nearest_km"] is None or t["nearest_km"] > 25
    assert client.get("/api/v1/layer-details/nope/gaps").status_code == 404



def test_hospitals_by_list_and_kind(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    for n, (found, tier) in enumerate([("Wikidata + OpenStreetMap", "hospital"), ("OpenStreetMap", "unsure"), ("Overture", "clinic")]):
        con.execute("INSERT INTO layer_items VALUES ('hospitals', ?, ?, 'NZL', -37, 175, NULL, ?, NULL, ?, false, 'wikidata_places', 'v1')",
                    [f"h{n}", f"H{n}", found, json.dumps({"tier": tier})])
    con.close()
    layer_details._cache.clear()
    main.warehouse = Warehouse(str(db))
    try:
        rows = {r["list"]: r for r in TestClient(main.app).get("/api/v1/layer-details/hospitals").json()["by_list"]}
    finally:
        main.warehouse = Warehouse(str(SAMPLE))
        layer_details._cache.clear()
    assert rows["OpenStreetMap"] == {"list": "OpenStreetMap", "count": 2, "only": 1, "hospital": 1, "unsure": 1, "clinic": 0}
    assert rows["All lists"]["count"] == 3 and rows["All lists"]["clinic"] == 1
