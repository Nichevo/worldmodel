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
