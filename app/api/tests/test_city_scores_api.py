"""City stress and other city scores (contract city_scores.yaml), on a copy of the sample
warehouse with a few cities and their figures added."""

import shutil

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import cityscore, main
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_api import core

CITIES = [("c1", "New York", "USA"), ("c2", "Auckland", "NZL"), ("c3", "Tokyo", "JPN"), ("c4", "Wellington", "NZL")]
# indicator -> figures for c1..c4 (None: no figure)
FIGURES = {
    "tomtom_travel_10km": [31.8, 23.2, 26.0, None],
    "numbeo_cost_of_living": [100, 66, 70, 60],
    "numbeo_health_care": [62, 60, 79, 66],
    "numbeo_crime": [50, 46, 23, 39],
    "who_pm25_city": [8.1, 6.0, 9.8, None],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.execute("""CREATE TABLE cities (city_id VARCHAR, name VARCHAR, ascii_name VARCHAR, synonyms VARCHAR, country_id VARCHAR,
        admin1 VARCHAR, lat DOUBLE, lon DOUBLE, population DOUBLE, capital VARCHAR, feature_code VARCHAR, timezone VARCHAR,
        elevation DOUBLE, source_id VARCHAR, vintage VARCHAR)""")
    for i, (cid, name, country) in enumerate(CITIES):
        con.execute("INSERT INTO cities VALUES (?, ?, ?, '', ?, '', ?, ?, 1000000, '', 'PPL', '', 0, 'geonames', 'v1')",
                    [cid, name, name, country, -40 + i, 170 + i])
    con.execute("""CREATE TABLE city_series (city_id VARCHAR, indicator_id VARCHAR, period_start DATE, source_id VARCHAR,
        vintage VARCHAR, value DOUBLE, status VARCHAR, source_name VARCHAR)""")
    for ind, vals in FIGURES.items():
        for (cid, name, _), v in zip(CITIES, vals):
            if v is not None:
                con.execute("INSERT INTO city_series VALUES (?, ?, '2025-01-01', 'x', 'v1', ?, 'E', ?)", [cid, ind, v, name])
    # An older year for Auckland's cost of living, so the score has a history.
    for cid, v in (("c1", 95), ("c2", 99), ("c3", 60)):
        con.execute("INSERT INTO city_series VALUES (?, 'numbeo_cost_of_living', '2018-01-01', 'x', 'v1', ?, 'E', '')", [cid, v])
    for cid, v in (("c1", 40), ("c2", 30), ("c3", 20)):
        con.execute("INSERT INTO city_series VALUES (?, 'numbeo_crime', '2018-01-01', 'x', 'v1', ?, 'E', '')", [cid, v])
        con.execute("INSERT INTO city_series VALUES (?, 'numbeo_health_care', '2018-01-01', 'x', 'v1', ?, 'E', '')", [cid, 60])
    con.close()
    core.warehouse = Warehouse(str(db))
    core._lh_cache.clear()  # answers kept per build; this copy has the sample's build id
    yield TestClient(main.app)
    core.warehouse = Warehouse(str(SAMPLE))


def test_scaled_places():
    assert cityscore.scaled({"a": 1, "b": 2, "c": 3}, "higher") == {"a": 0, "b": 5, "c": 10}
    assert cityscore.scaled({"a": 1, "b": 2, "c": 3}, "lower") == {"a": 10, "b": 5, "c": 0}
    assert cityscore.scaled({"a": 1, "b": 1, "c": 3}, "higher") == {"a": 2.5, "b": 2.5, "c": 10}
    assert cityscore.scaled({"a": 7}, "higher") == {"a": 5}


def test_stress_ranking(client):
    d = client.get("/api/v1/cities/scores", params={"score": "stress"}).json()
    names = [r["name"] for r in d["rows"]]
    assert names[0] == "New York" and set(names) == {"New York", "Auckland", "Tokyo", "Wellington"}
    ny = d["rows"][0]
    # New York: worst on traffic (10), cost (10), crime (10); health care 62 is third best of 4 (6.67); air 8.1 middle (5).
    assert ny["score"] == pytest.approx((10 + 10 + 6.67 + 10 + 5) / 5, abs=0.01)
    welly = next(r for r in d["rows"] if r["name"] == "Wellington")
    assert welly["n_parts"] == 3 and "tomtom_travel_10km" not in welly["parts"]
    assert [p["indicator"] for p in d["parts"]][0] == "tomtom_travel_10km" and d["parts"][0]["cities"] == 3
    assert d["years"] == [2018, 2025] and d["scores"][0]["id"] == "stress"
    pub = {c["name"]: c for c in d["published"]["cities"]}
    assert pub["New York"]["score"] == 7.56 and pub["New York"]["ours"] == ny["score"] and pub["Dublin"]["ours"] is None
    assert client.get("/api/v1/cities/scores", params={"score": "nope"}).status_code == 404


def test_score_for_a_year_and_on_the_city_page(client):
    old = client.get("/api/v1/cities/scores", params={"score": "stress", "year": 2019}).json()
    assert {r["name"] for r in old["rows"]} == {"New York", "Auckland", "Tokyo"}
    assert old["rows"][0]["name"] == "Auckland"  # dearest and most crime in 2018
    page = client.get("/api/v1/cities/c2").json()
    s = page["scores"][0]
    assert s["id"] == "stress" and s["of"] == 4 and len(s["parts"]) == 5
    assert [h["year"] for h in s["history"]] == [2018, 2025] and s["history"][0]["rank"] == 1
