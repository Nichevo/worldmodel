"""Predictions log, scorecard, base rates, watchlist and crowd endpoints, against a copy of the
sample warehouse (which holds the small crowd test pages; scripts/sample/add_crowd.py)."""

import shutil

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, predictions
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.execute("""INSERT INTO events (event_id, source_id, vintage, entity_id, kind, title, start_date, precision) VALUES
        ('t:1', 'test', 'v1', 'NZL', 'coup', 'Made-up coup', '1990-05-01', 'day'),
        ('t:2', 'test', 'v1', 'AUS', 'coup', 'Another', '2001-05-01', 'day')""")
    # ViEWS months ahead of today, whenever the test runs
    con.execute("""INSERT INTO conflict_forecasts SELECT e, date_trunc('month', current_date) + INTERVAL (m) MONTH, d, c, 'sb', 'test', 'views', 'v1'
        FROM (VALUES ('SDN', 500.0, 0.9), ('UKR', 900.0, 0.95)) t(e, d, c), range(3) r(m)""")
    con.close()
    main.warehouse = Warehouse(str(db))
    main._pred_state.clear()
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))
    main._pred_state.clear()


def test_log_and_scores(client):
    a = client.post("/api/v1/predictions", json={"question": "Will NZ hold an election?", "kind": "binary", "chance": 0.8,
                                                 "made": "2026-01-05", "due": "2026-10-01", "category": "politics"}).json()
    b = client.post("/api/v1/predictions", json={"question": "NZ inflation", "kind": "number", "value": 2.4, "low": 2, "high": 3,
                                                 "due": "2027-04-30", "who_kind": "expert", "who": "A bank"}).json()
    assert client.post("/api/v1/predictions", json={"question": "", "kind": "binary"}).status_code == 422
    r = client.post(f"/api/v1/predictions/{a['id']}/outcome", json={"actual": True}).json()
    assert r["score"]["hit"] and r["score"]["brier"] == pytest.approx(0.04)
    r = client.post(f"/api/v1/predictions/{b['id']}/outcome", json={"actual": 3.4}).json()
    assert not r["score"]["hit"]
    log = client.get("/api/v1/predictions").json()
    assert len(log["items"]) == 2 and log["who"] == ["A bank", "You"]
    sc = client.get("/api/v1/predictions/scorecard").json()["rows"]
    you = next(x for x in sc if x["name"] == "You")
    assert you["settled"] == 1 and you["brier"] == pytest.approx(0.04)
    assert "NZ inflation" in client.get("/api/v1/predictions/export.csv").text
    assert client.delete(f"/api/v1/predictions/{a['id']}").status_code == 200
    assert client.delete(f"/api/v1/predictions/{a['id']}").status_code == 404


def test_base_rates(client):
    p = client.get("/api/v1/predictions/base-rates").json()
    assert p["presets"] and any(k["kind"] == "coup" for k in p["event_kinds"])
    r = client.get("/api/v1/predictions/base-rate", params={"event": "coup", "start": 1980, "within": 5}).json()
    assert r["cases"] >= 2 and 0 < r["rate"] < 1 and r["chance_within"] > r["rate"]
    nz = client.get("/api/v1/predictions/base-rate", params={"event": "coup", "entity": "NZL", "start": 1980}).json()
    assert nz["countries"] == 1 and nz["cases"] == 1
    rule = client.get("/api/v1/predictions/base-rate", params={"indicator": "inflation", "if_op": "above", "if_value": 10,
                                                               "then_op": "below", "then_value": 5, "within": 5}).json()
    assert rule["kind"] == "rule" and rule["cases"] >= 0
    assert client.get("/api/v1/predictions/base-rate", params={"preset": "nope"}).status_code == 404


def test_watchlist(client):
    w = client.post("/api/v1/watchlist", json={"kind": "indicator", "indicator": "inflation", "entity": "NZL", "op": "above",
                                               "threshold": -100}).json()
    items = client.get("/api/v1/watchlist").json()["items"]
    assert items[0]["id"] == w["id"] and "above" in items[0]["text"] and not items[0]["alert"]  # above both years: no crossing
    assert client.post("/api/v1/watchlist", json={"kind": "nothing"}).status_code == 422
    assert client.delete(f"/api/v1/watchlist/{w['id']}").status_code == 200


def test_crowd(client):
    lst = client.get("/api/v1/crowd", params={"status": ""}).json()
    keys = [q["question_key"] for q in lst["items"]]
    assert lst["loaded"] and "polymarket:501" in keys
    nz = client.get("/api/v1/crowd", params={"country": "NZL", "status": ""}).json()["items"]
    assert "polymarket:501" in [q["question_key"] for q in nz] and "polymarket:601" not in [q["question_key"] for q in nz]
    q = client.get("/api/v1/crowd/question", params={"key": "polymarket:501"}).json()
    assert len(q["points"]) >= 3 and q["followed"] is False
    assert client.get("/api/v1/crowd/question", params={"key": "polymarket:nope"}).status_code == 404
    f = client.post("/api/v1/crowd/follow", json={"key": "polymarket:501", "follow": True}).json()
    assert f["follow"] == ["polymarket:501"]
    assert client.get("/api/v1/crowd", params={"followed": True, "status": ""}).json()["items"][0]["question_key"] == "polymarket:501"
    client.post("/api/v1/crowd/follow", json={"key": "polymarket:501", "hide": True})
    assert "polymarket:501" not in [x["question_key"] for x in client.get("/api/v1/crowd", params={"status": ""}).json()["items"]]
    assert client.post("/api/v1/crowd/follow", json={"key": "bad key"}).status_code == 422
    assert isinstance(client.get("/api/v1/crowd/moves").json(), list)
    assert client.get("/api/v1/crowd/events").status_code == 200
    c = client.get("/api/v1/crowd/conflict").json()["rows"]
    assert c[0]["entity_id"] == "UKR" and {"SDN", "UKR"} <= {x["entity_id"] for x in c}
    ukr = client.get("/api/v1/crowd/country/UKR").json()
    assert ukr["views"]["deaths_12"] >= 2700 and any("Ukraine" in q["title"] for q in ukr["questions"])


def test_resolved_crowd_question_settles_a_prediction(client):
    p = client.post("/api/v1/predictions", json={"question": "Crowd call", "kind": "binary", "chance": 0.3, "made": "2025-12-01", "due": "2026-01-01",
                                                 "crowd_key": "polymarket:601"}).json()
    items = client.get("/api/v1/predictions").json()["items"]
    got = next(x for x in items if x["id"] == p["id"])
    assert got["outcome"]["actual"] is False and got["score"]["hit"]


def test_briefing_lanes(client):
    client.post("/api/v1/predictions", json={"question": "Soon", "kind": "binary", "chance": 0.5,
                                             "due": (predictions.date.today() + predictions.timedelta(days=5)).isoformat()})
    lanes = client.get("/api/v1/briefing").json()["lanes"]
    assert any(c["group"] == "prediction" and c["title"] == "Soon" for c in lanes["due"])
