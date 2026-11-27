"""The Scorecard: measures resolved from the contract, ranks among the countries picked, wins."""

import pytest
from fastapi.testclient import TestClient
from worldmodel_api import core, main, scorecard
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_contract import catalogue


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    core.warehouse = Warehouse(str(SAMPLE))
    core._lh_cache.clear()
    return TestClient(main.app)


def test_contract_has_29_measures_with_a_direction():
    card = catalogue.scorecard()
    ms = [m for g in card["groups"] for m in g["measures"]]
    assert len(ms) == 29 and len({m["id"] for m in ms}) == 29
    assert all(m["better"] in ("higher", "lower") and m["use"] for m in ms)
    assert card["default_countries"] == ["USA", "CHN", "DEU", "JPN", "GBR", "IND"]


def test_candidates_plain_then_patterns():
    known = ["a_rate", "cause_death_rate_cardiovascular", "cause_death_rate_diabetes", "communicable_ncd_death_rate_communicable",
             "communicable_ncd_death_rate_non_communicable"]
    assert scorecard.candidates(["missing", "a_rate"], known) == ["a_rate"]
    assert scorecard.candidates(["~^cause_death_rate_.*cardio"], known) == ["cause_death_rate_cardiovascular"]
    assert scorecard.candidates(["~^communicable_ncd_death_rate_(?!.*non).*communicable"], known) == \
        ["communicable_ncd_death_rate_communicable"]


def test_ranks_share_ties_both_ways():
    assert scorecard.ranks({"A": 1, "B": 2, "C": 2, "D": 5}, "lower") == {"A": 1, "B": 2, "C": 2, "D": 4}
    assert scorecard.ranks({"A": 1, "B": 2, "C": 2, "D": 5}, "higher") == {"A": 4, "B": 2, "C": 2, "D": 1}


def test_scorecard_view(client):
    r = client.get("/api/v1/scorecard", params={"countries": "NZL,AUS,usa,GBR,XXX"}).json()
    assert [c["entity_id"] for c in r["countries"]] == ["NZL", "AUS", "USA", "GBR"]
    assert r["measures"] == 29 and len(r["groups"]) == 6
    shown = [row for g in r["groups"] for row in g["rows"] if row["indicator_id"]]
    assert shown, "the sample warehouse should fill some rows"
    for row in shown:
        cells = row["cells"]
        best = [e for e, c in cells.items() if c["best"]]
        assert best
        vals = {e: c["value"] for e, c in cells.items()}
        top = min(vals.values()) if row["better"] == "lower" else max(vals.values())
        assert all(vals[e] == top for e in best)
    assert sum(c["wins"] for c in r["countries"]) >= len(shown)
    missing = {m["id"] for m in r["missing"]}
    assert missing == {row["id"] for g in r["groups"] for row in g["rows"] if not row["indicator_id"]}


def test_scorecard_default_countries(client):
    r = client.get("/api/v1/scorecard").json()
    assert {c["entity_id"] for c in r["countries"]} <= {"USA", "CHN", "DEU", "JPN", "GBR", "IND"}
