"""How a country ranks among a group: neighbours from the map's shapes, groups, custom picks and
the ranking itself, on the sample warehouse."""

import pytest
from fastapi.testclient import TestClient
from worldmodel_api import main, peers
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_api import core


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    core.warehouse = Warehouse(str(SAMPLE))
    core._lh_cache.clear()
    return TestClient(main.app)


def test_rank_ties_and_direction():
    order = [{"v": 1.0}, {"v": 2.0}, {"v": 2.0}, {"v": 5.0}]
    assert [peers._rank_of(order, i, "lower") for i in range(4)] == [1, 2, 2, 4]
    order = order[::-1]
    assert [peers._rank_of(order, i, "higher") for i in range(4)] == [1, 2, 2, 4]


def test_neighbours_from_shapes():
    every = frozenset(peers._outlines())
    if not every:
        pytest.skip("map shapes not present")
    nz = [c for c, _ in peers.neighbours("NZL", every)]
    assert "AUS" in nz and len(nz) <= peers.NEIGHBOURS
    fr = dict(peers.neighbours("FRA", every))
    assert fr.get("DEU", 99) <= peers.TOUCH_KM and fr.get("ESP", 99) <= peers.TOUCH_KM


def test_peers_view(client):
    r = client.get("/api/v1/peers/NZL", params={"group": "neighbours"}).json()
    assert r["group"] == "neighbours" and r["name"]
    ids = {g["id"] for g in r["groups"]}
    assert {"neighbours", "like", "world"} <= ids
    for row in r["rows"]:
        vals = [c["value"] for c in row["ranked"]]
        assert vals == sorted(vals, reverse=row["better"] == "higher")
        assert row["best"]["value"] == vals[0] and row["worst"]["value"] == vals[-1]
        if row["me"]:
            assert 1 <= row["me"]["rank"] <= row["of"] and 0 <= row["me"]["position"] <= 1


def test_custom_group_and_measures(client):
    r = client.get("/api/v1/peers/NZL", params={"group": "custom", "countries": "AUS,USA,GBR",
                                                 "measures": "life_expectancy,pop_total:lower"}).json()
    assert {m["entity_id"] for m in r["members"]} <= {"AUS", "USA", "GBR"}
    got = {row["indicator_id"]: row for row in r["rows"]}
    assert set(got) <= {"life_expectancy", "pop_total"}
    if "pop_total" in got:
        assert got["pop_total"]["better"] == "lower"
