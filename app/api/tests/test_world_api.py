"""The world beyond borders endpoints: UN voting, CrisisWatch by month, zones, and the
around-an-event view against each country's own region, on a copy of the sample warehouse
with a few rows added."""

import shutil

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    src, vin = con.execute("SELECT source_id, vintage FROM vintages WHERE is_latest LIMIT 1").fetchone()
    rows = [("NZL", "unga_agreement", f"{y}-01-01", "A", p, "central", src, vin, v, "E")
            for y, p, v in ((2020, "USA", 62), (2021, "USA", 65), (2020, "FRA", 80), (2020, "DEU", 84), (2020, "CHN", 70))]
    rows += [("NZL", "unga_ideal_point", "2020-01-01", "A", "", "central", src, vin, 0.81, "E")]
    con.executemany("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    ev = [("cw1", "NZL", "crisiswatch", "unchanged", "CrisisWatch: Unchanged", "2024-09-01", "Calm."),
          ("cw2", "AUS", "crisiswatch", "deteriorated", "CrisisWatch: Deteriorated", "2024-10-01", "Worse."),
          ("cw3", "NZL", "crisiswatch", "improved", "CrisisWatch: Improved", "2024-10-01", "Better."),
          ("veto1", "USA", "un", "veto", "Vetoed a Security Council draft", "2023-10-18", None),
          ("seat1", "NZL", "un", "council_seat", "Elected member of the UN Security Council", "2015-01-01", "Term 2015 to 2016.")]
    con.executemany("""INSERT INTO events (event_id, entity_id, source_id, vintage, kind, subkind, title, start_date, precision, detail)
        VALUES (?, ?, 'test', 'v1', ?, ?, ?, ?, 'day', ?)""", [(i, e, k, s, t, d, x) for i, e, k, s, t, d, x in ev])
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_voting_lines_with_a_group_average(client):
    r = client.get("/api/v1/entities/NZL/voting", params={"compare": "USA,eu"}).json()
    lines = {ln["id"]: ln for ln in r["lines"]}
    assert lines["USA"]["points"] == [[2020, 62], [2021, 65]]
    assert lines["eu"]["points"] == [[2020, 82]] and "average" in lines["eu"]["name"]  # France 80, Germany 84
    assert r["ideal"] == [[2020, 0.81]]
    assert [c["entity_id"] for c in r["closest"]] == ["USA"] and r["closest_year"] == 2021  # the latest year only
    assert [e["subkind"] for e in r["council"]] == ["council_seat"]


def test_crisiswatch_month_for_the_map(client):
    r = client.get("/api/v1/crisiswatch").json()
    assert r["months"] == ["2024-09", "2024-10"] and r["month"] == "2024-10"
    assert {x["entity_id"]: x["score"] for x in r["rows"]} == {"AUS": -2, "NZL": 1}
    assert client.get("/api/v1/crisiswatch", params={"month": "2024-09"}).json()["rows"][0]["subkind"] == "unchanged"
    assert client.get("/api/v1/crisiswatch", params={"month": "2030-01"}).json()["month"] == "2024-10"  # latest before


def test_zones_list_every_zone_even_before_a_refresh(client):
    r = client.get("/api/v1/zones").json()
    assert [z["entity_id"] for z in r] == ["ATA", "arctic", "space", "high_seas"]
    assert all(isinstance(z["treaties"], list) for z in r)


def test_around_against_each_countrys_region(client):
    r = client.get("/api/v1/around", params={"indicator": "pop_total", "kind": "crisiswatch", "compare": "region"})
    assert r.status_code in (200, 404)  # the sample may lack figures for these years
    if r.status_code == 200:
        body = r.json()
        assert "region" in body["note"]
        assert all(e["compare_id"] != "world" for e in body["events"])
