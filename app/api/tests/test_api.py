"""API against the sample warehouse that ships in app/sample/."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture(scope="module")
def client():
    main.warehouse = Warehouse(str(SAMPLE))
    return TestClient(main.app)


def test_meta_says_sample(client):
    m = client.get("/api/v1/meta").json()
    assert m["is_sample"] and m["schema_version"].startswith("1.")


def test_profile_and_series(client):
    prof = {r["indicator_id"]: r for r in client.get("/api/v1/entities/NZL/profile").json()}
    assert prof["pop_total"]["value"] > 4e6
    rows = client.get("/api/v1/series", params={"indicator": "tfr", "entities": "JPN,eu", "start": 2000, "end": 2030}).json()["rows"]
    assert {r["entity_id"] for r in rows} == {"JPN", "eu"}
    assert any(r["status"] == "P" for r in rows)
    assert all(r["is_aggregate"] for r in rows if r["entity_id"] == "eu")


def test_search_uses_synonyms(client):
    hits = client.get("/api/v1/search", params={"q": "UK"}).json()
    assert hits[0]["id"] == "GBR"
    assert client.get("/api/v1/search", params={"q": "fertility"}).json()[0]["id"] == "tfr"


def test_map_and_pyramid(client):
    rows = client.get("/api/v1/map", params={"indicator": "pop_total", "year": 2023}).json()["rows"]
    assert len(rows) >= 200
    pyr = client.get("/api/v1/pyramid", params={"entity": "JPN", "year": 2020}).json()
    assert len(pyr["groups"]) == 21 and pyr["groups"][0]["age"] == "0-4"


def test_streams_formats(client):
    js = client.get("/api/v1/streams/nz-population").json()
    assert js["rows"] and js["stream"]["indicator"] == "pop_total"
    csv = client.get("/api/v1/streams/nz-population", params={"format": "csv"})
    assert csv.text.startswith("entity_id,")
    assert client.get("/api/v1/streams/nope").status_code == 404


def test_bad_warehouse_is_refused(tmp_path):
    import duckdb
    bad = tmp_path / "old.duckdb"
    con = duckdb.connect(str(bad))
    con.execute("CREATE TABLE meta AS SELECT 'schema_version' AS key, '0.1.0' AS value")
    con.close()
    from worldmodel_api.warehouse import WarehouseError
    with pytest.raises(WarehouseError):
        Warehouse(str(bad)).current()


def test_datasets_summarise_each_source(client):
    found = {d["source_id"]: d for d in client.get("/api/v1/datasets").json()}
    wpp = found["un_wpp"]
    assert wpp["latest_vintage"]["vintage"] == "2024"
    tfr = next(i for i in wpp["indicators"] if i["indicator_id"] == "tfr")
    assert tfr["countries"] >= 200 and tfr["first_year"] <= 1950 and tfr["last_year"] >= 2100
    assert found["world_bank_wdi"]["latest_vintage"] is None and found["world_bank_wdi"]["indicators"] == []


def test_pyramid_falls_back_to_the_latest_earlier_year(client):
    pyr = client.get("/api/v1/pyramid", params={"entity": "JPN", "year": 2022}).json()
    assert pyr["year"] == 2020 and len(pyr["groups"]) == 21
    early = client.get("/api/v1/pyramid", params={"entity": "JPN", "year": 1900}).json()
    assert early["year"] == early["years_available"][0]


def test_layouts_save_list_delete(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path))
    assert client.get("/api/v1/layouts").json() == []
    saved = client.put("/api/v1/layouts/Fertility across time", json={"query": "?l=4&p=map.tfr.1970"}).json()
    assert saved["query"] == "l=4&p=map.tfr.1970"
    client.put("/api/v1/layouts/Fertility across time", json={"query": "l=2h&p=map.tfr"})
    listed = client.get("/api/v1/layouts").json()
    assert [r["name"] for r in listed] == ["Fertility across time"] and listed[0]["query"] == "l=2h&p=map.tfr"
    assert (tmp_path / "layouts.json").exists()
    assert client.delete("/api/v1/layouts/Fertility across time").status_code == 200
    assert client.delete("/api/v1/layouts/Fertility across time").status_code == 404
    assert client.put("/api/v1/layouts/%20", json={"query": "l=1"}).status_code == 422


def test_memberships_by_type_and_group(client):
    continents = client.get("/api/v1/memberships", params={"type": "continent"}).json()
    by_member = {r["member_id"]: r["group_id"] for r in continents}
    assert by_member["NZL"] == "oceania" and by_member["FRA"] == "europe"
    eu = {r["member_id"] for r in client.get("/api/v1/memberships", params={"group": "eu"}).json()}
    assert "FRA" in eu and "GBR" not in eu
    assert client.get("/api/v1/memberships").status_code == 400
