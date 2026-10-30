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
    assert found["owid_grapher"]["latest_vintage"] is None and found["owid_grapher"]["indicators"] == []
    assert found["world_bank_wdi"]["latest_vintage"] and len(found["world_bank_wdi"]["indicators"]) > 100


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
    assert client.get("/api/v1/problems").json() == []  # one passing build: nothing to report
    (reports / "20260302T000000Z.md").write_text(
        "# Build y\n\nResult: FAILED, not swapped in\n\n| dbt:unique_combination_observations_x | dbt_test | fail | 2 failing row(s) |\n")
    got = client.get("/api/v1/problems").json()
    assert [(p["title"], p["times"], p["open"]) for p in got] == [("Duplicate rows", 1, True)]


def test_whatif_defaults_match_un_and_levers_move_it(client):
    base = client.get("/api/v1/whatif", params={"entity": "NZL"}).json()
    assert base["base_year"] == 2023 and base["years"][-1] == 2100
    assert base["scenario"] == base["baseline"]  # defaults are the UN projection exactly
    assert base["baseline"][0] == pytest.approx(5_172_836, rel=1e-3)
    low = client.get("/api/v1/whatif", params={"entity": "NZL", "tfr": -0.5, "phase": 5}).json()
    assert low["scenario"][-1] < 0.85 * low["baseline"][-1]
    assert low["inputs"]["tfr"]["scenario"][10] == pytest.approx(low["inputs"]["tfr"]["baseline"][10] - 0.5)
    first, last = low["summary"][0], low["summary"][-1]
    assert first["year"] == 2023 and last["year"] == 2100
    assert last["scenario"]["share_65_plus"] > last["baseline"]["share_65_plus"]
    shut = client.get("/api/v1/whatif", params={"entity": "NZL", "mig": 0}).json()
    assert shut["scenario"][-1] < base["baseline"][-1]
    py = low["pyramids"]["2050"]
    assert len(py["scenario"]["male"]) == 21 and sum(py["scenario"]["male"][:4]) < sum(py["baseline"]["male"][:4])
    assert client.get("/api/v1/whatif", params={"entity": "NZL", "mig": 9}).status_code == 422
    assert client.get("/api/v1/whatif", params={"entity": "nowhere"}).status_code == 404


def test_track_record_and_variants(client):
    tr = client.get("/api/v1/track-record", params={"entity": "NZL"}).json()
    assert tr["releases"] == ["2015-04"] and tr["paths"][0]["points"][0][0] == 2014
    assert tr["stats"] == []  # the sample holds one release: nothing to score yet
    assert client.get("/api/v1/track-record", params={"indicator": "tfr"}).status_code == 422
    rows = client.get("/api/v1/series", params={"indicator": "tfr", "entities": "NZL", "variant": "central,low",
                                                "start": 2020, "end": 2021}).json()["rows"]
    assert {r["variant"] for r in rows} == {"central"}  # the sample has no ranges; the filter still works
    assert {s["name"] for s in client.get("/api/v1/streams").json()} >= {"world-population-forecast"}
    assert client.get("/api/v1/streams/world-population-forecast").json()["rows"]


def test_source_comparison(client):
    inds = {i["indicator_id"]: i for i in client.get("/api/v1/sources/indicators").json()}
    assert [s["source_id"] for s in inds["pop_total"]["sources"]] == ["un_wpp", "world_bank_wdi", "cia_factbook"]
    assert inds["gdp_growth"]["countries"] > 150 and inds["gdp_growth"]["differing"] > 0
    cmp = client.get("/api/v1/sources/compare", params={"indicator": "gdp_growth", "entity": "ARG"}).json()
    assert [s["source_id"] for s in cmp["sources"]] == ["imf_weo", "world_bank_wdi", "cia_factbook"]
    assert cmp["differences"] and {d["source_b"] for d in cmp["differences"]} == {"world_bank_wdi", "cia_factbook"}
    div = client.get("/api/v1/sources/divergence", params={"indicator": "gdp_growth", "flagged": True}).json()
    assert div and all(d["flagged"] for d in div) and div[0]["rel"] >= div[-1]["rel"]
    nzl = client.get("/api/v1/sources/divergence", params={"entity": "NZL"}).json()
    assert {d["indicator_id"] for d in nzl} >= {"pop_total", "gdp_growth"} and nzl[0]["entity_name"] == "New Zealand"


def test_world_bank_indicators_and_income_groups(client):
    inds = {i["indicator_id"]: i for i in client.get("/api/v1/indicators").json()}
    assert inds["military_spending_gdp"]["enabled"]
    assert not any(i["enabled"] for k, i in inds.items() if k.startswith("wdi_"))
    assert any(k.startswith("wdi_") for k in inds)
    assert inds["renewables_share_elec"]["enabled"]
    groups = {e["entity_id"] for e in client.get("/api/v1/entities", params={"type": "income_group"}).json()}
    assert groups == {"income-high", "income-upper-middle", "income-lower-middle", "income-low"}
    rows = client.get("/api/v1/series", params={"indicator": "pop_total", "entities": "income-low", "start": 2020,
                                                "end": 2020}).json()["rows"]
    assert rows and rows[0]["value"] > 1e8


def test_events_filters_and_your_own_milestones(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path))
    jpn = client.get("/api/v1/events", params={"entities": "JPN", "kinds": "sport,disaster"}).json()
    assert {e["title"] for e in jpn} >= {"2002 FIFA World Cup", "Tohoku"}
    assert all(e["entity_id"] == "JPN" and e["kind"] in ("sport", "disaster") for e in jpn)
    assert all((e["end_date"] or e["start_date"]) >= "2000" for e in client.get("/api/v1/events", params={"start": "2000"}).json())
    kinds = {k["kind"]: k for k in client.get("/api/v1/events/kinds").json()}
    assert kinds["recession"]["sources"] == ["worldmodel"] and "user" not in kinds

    bad = client.post("/api/v1/milestones", json={"entity_id": "NZL", "title": "x", "start_date": "soon"})
    assert bad.status_code == 422
    m = client.post("/api/v1/milestones", json={"entity_id": "NZL", "title": "Reserve Bank Act", "start_date": "1989-12-20",
                                                "note": "inflation targeting starts"}).json()
    got = client.get("/api/v1/events", params={"entities": "NZL", "kinds": "user"}).json()
    assert [(e["title"], e["source_id"], e["detail"]) for e in got] == [("Reserve Bank Act", "user", "inflation targeting starts")]
    client.put(f"/api/v1/milestones/{m['id']}", json={**m, "title": "Reserve Bank of New Zealand Act"})
    assert client.get("/api/v1/milestones").json()[0]["title"] == "Reserve Bank of New Zealand Act"
    assert client.delete(f"/api/v1/milestones/{m['id']}").json() == {"deleted": m["id"]}
    assert client.get("/api/v1/milestones").json() == []


def test_around_the_event_lines_up_years(client):
    a = client.get("/api/v1/around", params={"indicator": "gdp_growth", "kind": "recession", "entity": "NZL",
                                              "before": 3, "after": 2}).json()
    assert a["offsets"] == [-3, -2, -1, 0, 1, 2] and a["mode"] == "value" and a["n"] >= 2
    first = a["events"][0]
    assert first["values"][3] < 0  # the recession year itself
    assert first["diff"][3] == pytest.approx(first["values"][3] - first["compare"][3], abs=1e-3)
    idx = client.get("/api/v1/around", params={"indicator": "gdp_usd", "kind": "sport", "q": "World Cup"}).json()
    assert idx["mode"] == "index" and all(e["values"][idx["offsets"].index(-1)] == 100 for e in idx["events"])
    assert client.get("/api/v1/around", params={"indicator": "gdp_growth", "kind": "nothing"}).status_code == 404


def test_your_ratios_work_like_indicators(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path))
    bad = client.post("/api/v1/ratios", json={"name": "x", "numerator": "nope", "denominator": "pop_total"})
    assert bad.status_code == 422 and "numerator" in bad.json()["detail"]
    r = client.post("/api/v1/ratios", json={"name": "Coal power per person", "numerator": "coal_electricity",
                                            "denominator": "pop_total", "multiplier": 1e9, "unit": "kWh", "decimals": 0}).json()
    assert r["id"] == "my_coal_power_per_person"
    ind = client.get(f"/api/v1/indicators/{r['id']}").json()
    assert ind["domain"] == "Your ratios" and ind["available"] and ind["ratio"]["denominator"] == "pop_total"
    assert {s["source_id"] for s in ind["sources"]} == {"owid_energy", "un_wpp"}
    # The series is numerator / denominator x multiplier, year by year.
    got = {x["period"][:4]: x["value"] for x in client.get("/api/v1/series", params={
        "indicator": r["id"], "entities": "NZL", "start": 2015, "end": 2020}).json()["rows"]}
    coal = {x["period"][:4]: x["value"] for x in client.get("/api/v1/series", params={
        "indicator": "coal_electricity", "entities": "NZL", "start": 2015, "end": 2020}).json()["rows"]}
    pop = {x["period"][:4]: x["value"] for x in client.get("/api/v1/series", params={
        "indicator": "pop_total", "entities": "NZL", "start": 2015, "end": 2020}).json()["rows"]}
    assert got and all(abs(got[y] - coal[y] / pop[y] * 1e9) < 1e-6 * got[y] for y in got)
    # It maps like any indicator, and goes away when deleted.
    assert len(client.get("/api/v1/map", params={"indicator": r["id"], "year": 2020}).json()["rows"]) > 100
    assert client.delete(f"/api/v1/ratios/{r['id']}").status_code == 200
    assert client.get(f"/api/v1/indicators/{r['id']}").status_code == 404
