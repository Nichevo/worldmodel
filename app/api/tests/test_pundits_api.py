"""Pundits endpoints on the sample warehouse (its tables come from the made-up Prediction Archive
pages in the data side's test files: scripts/sample/add_pundits.py)."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse

Z = "01a05faa-0000-7000-8000-000000000001"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    return TestClient(main.app)


def test_pundits_tab(client):
    r = client.get("/api/v1/crowd/pundits").json()
    assert r["loaded"] and r["key_countries"] == ["NZL", "AUS", "GBR", "USA"]
    names = [p["name"] for p in r["people"]]
    assert names == ["Kea Forecasting Ltd", "Wellington Economist", "Sample Pundit"]  # best hit rate first, 10+ graded
    assert {c["title"] for c in r["open"]} >= {"New Zealand will leave the Five Eyes within a decade",
                                               "Australia will build nuclear submarines at home by 2030"}
    assert all(c["outcome"] in (None, "pending") for c in r["open"])
    assert r["graded"][0]["outcome"] == "correct" and "NZL" in r["graded"][0]["countries"]
    one = client.get("/api/v1/crowd/pundits", params={"country": "AUS", "min_graded": 2000}).json()
    assert [p["name"] for p in one["people"]] == ["Sample Pundit"] and [c["countries"] for c in one["open"]] == [["AUS"]]


def test_one_pundit_and_the_country_card(client):
    p = client.get(f"/api/v1/crowd/pundits/{Z}").json()
    assert p["correct"] == 1003 and len(p["calls"]) == 3 and p["calls"][0]["made"] == "2022-05-10"
    assert client.get("/api/v1/crowd/pundits/nobody").status_code == 404
    card = client.get("/api/v1/crowd/country/NZL").json()
    assert {c["predictor"] for c in card["pundits"]} == {"Sample Pundit", "Kea Forecasting Ltd"}
    assert all(c["graded"] for c in card["pundits"])
