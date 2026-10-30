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


def test_settings_are_checked_and_saved(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path))
    s = client.get("/api/v1/settings").json()["settings"]
    assert s["click_mode"] == "popup" and s["disk_limit_gb"] == 100 and s["numbeo_daily"] == 20
    s = client.put("/api/v1/settings", json={"click_mode": "select", "numbeo_daily": 9999, "nonsense": 1,
                                             "disk_limit_gb": "250"}).json()["settings"]
    assert s["click_mode"] == "select" and s["numbeo_daily"] == 200 and s["disk_limit_gb"] == 250
    assert "nonsense" not in s
    assert client.put("/api/v1/settings", json={"click_mode": "wobble"}).json()["settings"]["click_mode"] == "select"


def test_indicator_switches(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path))
    inds = {i["indicator_id"]: i for i in client.get("/api/v1/indicators").json()}
    assert inds["tfr"]["enabled"] and inds["tfr"]["countries"] >= 200
    assert inds["tfr"]["sources"][0]["licence"]
    client.put("/api/v1/indicator-switches", json={"tfr": False})
    assert not client.get("/api/v1/indicators/tfr").json()["enabled"]
    assert client.put("/api/v1/indicator-switches", json={"nope": True}).status_code == 404
    client.delete("/api/v1/indicator-switches")
    assert client.get("/api/v1/indicators/tfr").json()["enabled"]


def test_history_log_star_note_clear(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path))
    a = client.post("/api/v1/history", json={"kind": "page", "title": "New Zealand", "url": "/entity/NZL",
                                             "entity": "NZL"}).json()["entry"]
    again = client.post("/api/v1/history", json={"kind": "page", "title": "New Zealand", "url": "/entity/NZL",
                                                 "entity": "NZL"}).json()["entry"]
    assert again["id"] == a["id"]  # the same page twice in a row is one entry
    client.post("/api/v1/history", json={"kind": "view", "title": "Map: fertility", "url": "/?p=map.tfr"})
    assert client.post("/api/v1/history", json={"kind": "bogus", "title": "x"}).status_code == 422
    listed = client.get("/api/v1/history").json()
    assert [e["kind"] for e in listed] == ["view", "page"]
    assert [e["title"] for e in client.get("/api/v1/history", params={"q": "zealand"}).json()] == ["New Zealand"]
    client.patch(f"/api/v1/history/{a['id']}", json={"star": True, "note": "check migration"})
    starred = client.get("/api/v1/history", params={"starred": True}).json()
    assert len(starred) == 1 and starred[0]["note"] == "check migration"
    assert client.get("/api/v1/history/interest").json()[0]["entity_id"] == "NZL"
    assert client.delete("/api/v1/history").json()["deleted"] == 1  # the starred entry stays
    assert len(client.get("/api/v1/history").json()) == 1
    client.put("/api/v1/settings", json={"history_paused": True})
    assert client.post("/api/v1/history", json={"kind": "page", "title": "Paused"}).json()["entry"] is None


def test_popup_and_map_range(client):
    p = client.get("/api/v1/popup", params={"entity": "NZL", "indicator": "tfr", "year": 2023}).json()
    assert p["value"] and 1 <= p["rank"] <= p["of"] and p["region"]["entity_id"] == "australia-and-new-zealand"
    assert p["change10"]["from_year"] == 2013 and p["series"]["world"] and p["series"]["region"]
    r = client.get("/api/v1/map/range", params={"indicator": "tfr", "start": 2000, "end": 2023}).json()
    assert r["years"][0] == 2000 and r["years"][-1] == 2023 and len(r["rows"]["NZL"]) == 24


def test_storage_free_up_and_refresh_log(client, tmp_path, monkeypatch):
    home = tmp_path / "var"
    monkeypatch.setenv("WORLDMODEL_HOME", str(home))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    for stamp in ("20260101T000000Z", "20260201T000000Z", "20260301T000000Z"):
        d = home / "raw" / "un_wpp" / "2024" / stamp
        d.mkdir(parents=True)
        (d / "file.csv").write_bytes(b"x" * 1000)
    (home / "user").mkdir()
    (home / "user" / "settings.json").write_text('{"disk_limit_gb": 1}')
    st = client.get("/api/v1/storage").json()
    raw = next(c for c in st["categories"] if c["key"] == "raw")
    assert raw["bytes"] == 3000 and st["freeable"] == 1000 and st["level"] == "ok"
    assert st["limits"][0]["limit"] == 1024 ** 3
    done = client.post("/api/v1/storage/free-up").json()
    assert done["removed"] == ["raw/un_wpp/2024/20260101T000000Z"] and done["freed_bytes"] == 1000
    reports = home / "warehouse" / "reports"
    reports.mkdir(parents=True)
    (reports / "20260301T000000Z.md").write_text("# Build x\n\nResult: passed, live\n\n| a | b | pass | d |\n")
    log = client.get("/api/v1/refresh-log").json()
    assert log[0]["build_id"] == "20260301T000000Z" and log[0]["checks"]["pass"] == 1 and log[0]["backfilled"]
