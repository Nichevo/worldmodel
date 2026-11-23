"""The Learn page (quiz from the sample warehouse, draw your guess, tours) and the Data console's guards."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import learn, main, userdata


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    return TestClient(main.app)


def test_quiz_questions_carry_real_figures(client):
    got = client.get("/api/v1/learn/quiz", params={"seed": 7, "n": 12}).json()
    assert len(got["questions"]) == 12 and got["seed"] == 7
    for q in got["questions"]:
        assert q["answer"] in {c["id"] for c in q["choices"]} and q["source_id"]
        if q["kind"] in ("higher", "top"):
            vals = {c["id"]: c["value"] for c in q["choices"]}
            assert vals[q["answer"]] == max(vals.values())
            assert len(vals) == (2 if q["kind"] == "higher" else 4)
        else:
            (y0, a), (y1, b) = q["values"]
            assert y0 < y1 and q["answer"] == ("up" if b > a else "down")
    again = client.get("/api/v1/learn/quiz", params={"seed": 7, "n": 12}).json()
    assert [q["question"] for q in again["questions"]] == [q["question"] for q in got["questions"]]
    people = client.get("/api/v1/learn/quiz", params={"topic": "people", "n": 5}).json()["questions"]
    assert {q["indicator_id"] for q in people} <= {i["id"] for i in learn.topics()[0]["indicators"]}
    assert client.get("/api/v1/learn/quiz", params={"topic": "nope"}).status_code == 404


def test_most():
    assert learn.most("higher inflation") == "the highest inflation"
    assert learn.most("an older population (higher median age)") == "the oldest population (higher median age)"
    assert learn.most("more people") == "the most people"


def test_guess_and_record(client):
    g = client.get("/api/v1/learn/guess", params={"entity": "NZL", "indicator": "tfr", "hide_from": 1990}).json()
    assert g["shown"][-1][0] == 1990 and g["y_min"] < min(v for _, v in g["shown"]) and g["last"] > 1990
    full = learn.figures(main.rows, ["tfr"], ["NZL"])["tfr"]["NZL"]
    exact = [[y, v] for y, v in sorted(full.items()) if y > 1990]
    spot = client.post("/api/v1/learn/guess", json={"entity": "NZL", "indicator": "tfr", "hide_from": 1990, "drawn": exact}).json()
    assert spot["score"] == 100 and spot["actual"] == exact
    flat = client.post("/api/v1/learn/guess", json={"entity": "NZL", "indicator": "tfr", "hide_from": 1990,
                                                     "drawn": [[1991, g["y_max"]], [g["last"], g["y_max"]]]}).json()
    assert flat["score"] < 50
    client.post("/api/v1/learn/quiz/score", json={"topic": "people", "right": 7, "asked": 10})
    rec = client.get("/api/v1/learn").json()
    assert [x["score"] for x in rec["record"]["guesses"]] == [100, flat["score"]] and rec["record"]["quiz"][0]["right"] == 7
    assert rec["tours"][0]["stops"][0]["path"] == "/" and rec["guesses"]
    assert client.post("/api/v1/learn/quiz/score", json={"right": 5, "asked": 3}).status_code == 422


def test_score_guess_partial_line():
    real = [[y, 1.0] for y in range(2000, 2010)]
    assert learn.score_guess(real, [[2000, 1.0], [2009, 1.0]], 2)["score"] == 100
    assert learn.score_guess(real, [[2000, 1.0], [2002, 1.0]], 2)["score"] < 50  # only a third of the years drawn
    assert learn.score_guess(real, [], 2)["score"] == 0


@pytest.mark.parametrize("sql", ["drop table series", "select 1; select 2", "select * from read_parquet('x')",
                                 "from 'c:/x.csv'", "select 1 -- x", "with a as (select 1) insert into t select * from a",
                                 "select getenv('HOME')", "pragma version", "attach 'x' as y"])
def test_console_refuses(sql):
    with pytest.raises(ValueError):
        learn.check_sql(sql)


def test_console(client):
    assert client.post("/api/v1/console/query", json={"sql": "select 1"}).status_code == 403  # off by default
    userdata.save_settings({"data_console": True})
    r = client.post("/api/v1/console/query", json={"sql": "SELECT entity_id, name FROM entities WHERE name = 'Insert; drop' OR true", "limit": 3})
    got = r.json()
    assert got["columns"] == ["entity_id", "name"] and len(got["rows"]) == 3 and got["more"] is True
    assert client.post("/api/v1/console/query", json={"sql": "delete from entities"}).status_code == 422
    assert "series" in {t["table"] for t in client.get("/api/v1/console/tables").json()["tables"]}
    client.post("/api/v1/console/saved", json={"name": "Countries", "sql": "select * from entities"})
    assert [q["name"] for q in client.get("/api/v1/console/tables").json()["saved"]] == ["Countries"]
    assert client.request("DELETE", "/api/v1/console/saved", params={"name": "Countries"}).json() == []
    far = client.post("/api/v1/console/query", json={"sql": "select 1"}, headers={"x-forwarded-for": "192.168.1.20"})
    assert far.status_code == 403 and "PC running the app" in far.json()["detail"]
