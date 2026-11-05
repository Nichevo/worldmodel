"""City endpoints and the Numbeo prices button, against a copy of the sample warehouse
with a few cities added (the sample itself has none)."""

import shutil

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, numbeo
from worldmodel_api.warehouse import SAMPLE, Warehouse

NUMBEO_PAGE = """<html><body>
<div>Summary of cost of living in Auckland: A single person estimated monthly costs are <span class="emp_number">1,234.5$</span>
(without rent). Family of four estimated monthly costs are <span>4,321.0$</span> (without rent).</div>
<table class="data_wide_table new_bar_table">
<tr><th class="highlighted_th prices">Restaurants <span>Edit</span></th><th>Avg.</th></tr>
<tr><td>Meal, Inexpensive Restaurant </td><td style="text-align: right" class="priceValue ">17.50&nbsp;$</td></tr>
<tr><td>Cappuccino (regular)</td><td class="priceValue">3.40&nbsp;$</td></tr>
<tr><th class="highlighted_th prices">Rent Per Month</th></tr>
<tr><td>Apartment (1 bedroom) in City Centre</td><td class="priceValue">1,450.00&nbsp;$</td></tr>
</table></body></html>"""


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
    con.execute("""INSERT INTO cities VALUES
        ('gn2193733', 'Auckland', 'Auckland', 'tamakimakaurau', 'NZL', 'Auckland', -36.85, 174.76, 417910, '', 'PPLA', 'Pacific/Auckland', 26, 'geonames', 'v1'),
        ('gn2179537', 'Wellington', 'Wellington', '', 'NZL', 'Wellington', -41.29, 174.78, 215400, 'national', 'PPLC', 'Pacific/Auckland', 10, 'geonames', 'v1'),
        ('gn5746545', 'Portland', 'Portland', '', 'USA', 'Oregon', 45.52, -122.68, 652503, '', 'PPL', 'America/Los_Angeles', 15, 'geonames', 'v1')""")
    con.execute("""CREATE TABLE city_series (city_id VARCHAR, indicator_id VARCHAR, period_start DATE, source_id VARCHAR,
        vintage VARCHAR, value DOUBLE, status VARCHAR, source_name VARCHAR)""")
    con.execute("""INSERT INTO city_series VALUES
        ('gn2193733', 'city_population', '2015-01-01', 'un_wup', 'v1', 1500000, 'E', 'Auckland'),
        ('gn2193733', 'city_population', '2025-01-01', 'un_wup', 'v1', 1700000, 'P', 'Auckland'),
        ('gn2193733', 'city_population', '2035-01-01', 'un_wup', 'v1', 1900000, 'P', 'Auckland'),
        ('gn2193733', 'wn_city_cost_index', '2026-01-01', 'wherenext', 'v1', 72, 'E', 'Auckland')""")
    con.execute("""CREATE OR REPLACE TABLE places (place_id VARCHAR, kind VARCHAR, subkind VARCHAR, name VARCHAR, country_id VARCHAR,
        city_id VARCHAR, city_name VARCHAR, lat DOUBLE, lon DOUBLE, founded DATE, url VARCHAR, facts VARCHAR, size DOUBLE,
        source_id VARCHAR, vintage VARCHAR)""")
    con.execute("""INSERT INTO places VALUES
        ('w:university:Q1', 'university', 'public', 'University of Auckland', 'NZL', 'gn2193733', 'Auckland', -36.85, 174.77,
         '1883-01-01', 'https://en.wikipedia.org/wiki/University_of_Auckland', '{"students": 40000}', 40000, 'wikidata_places', 'v1'),
        ('w:company:Q2', 'company', NULL, 'Fletcher Building', 'NZL', 'gn2193733', 'Auckland', -36.85, 174.76,
         NULL, NULL, '{"revenue_usd": 4600000000}', 4600000000, 'wikidata_places', 'v1'),
        ('w:transit:Q3', 'transit', 'metro', 'Portland Streetcar', 'USA', NULL, 'Portland', NULL, NULL,
         NULL, NULL, '{}', NULL, 'wikidata_places', 'v1')""")
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_city_list_and_page(client):
    rows = client.get("/api/v1/cities", params={"country": "NZL"}).json()["rows"]
    assert [r["name"] for r in rows] == ["Auckland", "Wellington"]
    assert rows[0]["population"] == 1700000 and rows[0]["population_2035"] == 1900000
    assert rows[1]["population"] is None and rows[1]["geonames_population"] == 215400
    assert client.get("/api/v1/cities", params={"q": "tamaki"}).json()["rows"][0]["city_id"] == "gn2193733"
    page = client.get("/api/v1/cities/gn2193733").json()
    pop = next(s for s in page["series"] if s["indicator_id"] == "city_population")
    assert len(pop["points"]) == 3 and pop["unit"] == "persons"
    assert [o["name"] for o in page["others"]] == ["Wellington"]
    assert client.get("/api/v1/cities/gn0").status_code == 404
    assert [p["name"] for p in page["places"]] == ["Fletcher Building", "University of Auckland"]


def test_places_by_kind_and_country(client):
    got = client.get("/api/v1/places", params={"kind": "university"}).json()["rows"]
    assert len(got) == 1 and got[0]["facts"]["students"] == 40000 and got[0]["founded"] == "1883" and got[0]["city"] == "Auckland"
    usa = client.get("/api/v1/places", params={"country": "USA"}).json()["rows"]
    assert usa[0]["city"] == "Portland" and usa[0]["city_id"] is None


def test_no_cities_table_is_not_an_error(monkeypatch):
    main.warehouse = Warehouse(str(SAMPLE))
    res = TestClient(main.app).get("/api/v1/cities").json()
    assert res["rows"] == [] and "refresh" in res["note"]


def test_numbeo_button_fetches_once_within_the_limit(client, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=NUMBEO_PAGE)

    real = httpx.Client
    monkeypatch.setattr(numbeo.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    assert client.get("/api/v1/cities/gn2193733/numbeo").json()["prices"] is None
    got = client.post("/api/v1/cities/gn2193733/numbeo", json={}).json()
    assert got["prices"]["summary"] == {"single_without_rent": 1234.5, "family_without_rent": 4321.0}
    assert {"section": "Restaurants", "item": "Meal, Inexpensive Restaurant", "value": 17.5} in got["prices"]["items"]
    assert got["prices"]["items"][-1]["section"] == "Rent Per Month"
    assert got["budget"]["used"] == 1
    assert dict(seen[0].url.params)["city"] == "Auckland"
    client.post("/api/v1/cities/gn5746545/numbeo", json={})
    assert dict(seen[1].url.params)["city"] == "Portland, OR"
    both = client.get("/api/v1/numbeo/compare").json()
    assert {p["id"] for p in both["places"]} == {"gn2193733", "gn5746545"}
    assert both["places"][0]["values"]["Meal, Inexpensive Restaurant"] == 17.5
    assert {"item": "Meal, Inexpensive Restaurant", "section": "Restaurants"} in both["items"]
    # each fetch is also kept under its year; an older year's page compares against it
    this_year = int(both["places"][0]["fetched_at"][:4])
    assert both["years"] == [this_year]
    old = numbeo.cached("cities", "gn2193733") | {"fetched_at": "2024-06-01T00:00:00+00:00",
                                                 "items": [{"section": "Restaurants", "item": "Meal, Inexpensive Restaurant", "value": 15.0}]}
    numbeo._write(numbeo._year_file("cities", "gn2193733", 2024), old)
    then = client.get("/api/v1/numbeo/compare", params={"year": 2024}).json()
    assert [p["id"] for p in then["places"]] == ["gn2193733"] and then["years"] == [this_year, 2024]
    change = client.get("/api/v1/numbeo/compare", params={"since": 2024}).json()
    auck = next(p for p in change["places"] if p["id"] == "gn2193733")
    assert auck["before"] == {"Meal, Inexpensive Restaurant": 15.0} and auck["before_fetched_at"].startswith("2024")
    assert next(p for p in change["places"] if p["id"] == "gn5746545")["before"] is None
    client.put("/api/v1/settings", json={"numbeo_daily": 2})
    res = client.post("/api/v1/entities/NZL/numbeo", json={})
    assert res.status_code == 409 and "used up" in res.json()["detail"]


def test_manual_files_say_what_to_do(client, tmp_path):
    rows = {r["source_id"]: r for r in client.get("/api/v1/manual-files").json()}
    assert rows["emdat"]["get"].startswith("https://") and rows["emdat"]["command"] == ".\\load.bat emdat"
    assert all(r["todo"] == "download" for r in rows.values()
               if r["by_hand"] and r["last_loaded"] is None and not r["optional"])
    assert rows["gunpolicy"]["optional"] and rows["gunpolicy"]["todo"] is None  # needs a sign-in: never nags
    assert all(r["todo"] is None for r in rows.values() if not r["by_hand"] and not r["files"])
    (tmp_path / "manual" / "rbnz").mkdir(parents=True)
    (tmp_path / "manual" / "rbnz" / "hb2-daily.xlsx").write_bytes(b"x")
    rows = {r["source_id"]: r for r in client.get("/api/v1/manual-files").json()}
    assert rows["rbnz"]["todo"] == "load" and rows["rbnz"]["files"] == ["hb2-daily.xlsx"]


def test_scrapers_listed_with_their_last_run(client, tmp_path):
    import json

    (tmp_path / "warehouse").mkdir(exist_ok=True)
    (tmp_path / "warehouse" / "scrape_log.json").write_text(json.dumps({"crisiswatch": {
        "at": "2026-11-05T20:00:00+00:00", "planned": 13, "read": 4, "stopped": "crisiswatch: stopped after 4 of 13",
        "url": "x", "gap_seconds": 6}}))
    data = client.get("/api/v1/scrapers").json()
    rows = {r["source_id"]: r for r in data["sources"]}
    assert {"world_prison_brief", "crisiswatch", "numbeo", "wikipedia", "nz_election_turnout"} <= set(rows)
    assert data["sources"][0]["source_id"] == "crisiswatch"  # stopped runs first
    assert rows["crisiswatch"]["last_run"]["read"] == 4 and rows["crisiswatch"]["setting_value"] == 12
    assert "of 20 pages today" in rows["numbeo"]["today"] and data["gap_seconds"] == 6
