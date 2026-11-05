"""Indicator quality endpoints on the sample warehouse: grades on every indicator, stars and
your own grade that stick, and the summary for the Quality tab on Data status."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_contract import quality as qual


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    main._q_cache["key"] = None
    yield TestClient(main.app)
    main._q_cache["key"] = None


def test_every_indicator_has_a_grade_and_a_type(client):
    inds = client.get("/api/v1/indicators").json()
    assert inds and all(i["grade"] in "ABCD" and i["type"] for i in inds)
    pop = next(i for i in inds if i["indicator_id"] == "pop_total")
    assert pop["grade"] == "A" and pop["type"] == "count" and pop["starred"] is False
    q = client.get("/api/v1/quality").json()
    assert set(q["scores"]) == {"history", "up_to_date", "coverage", "standing", "health", "definition"}
    p = q["indicators"]["pop_total"]
    assert set(p["scores"]) == set(q["scores"]) and all(1 <= v <= 5 for v in p["scores"].values())
    assert "un_wpp" in p["notes"]["standing"] or "world_bank_wdi" in p["notes"]["standing"]


def test_stars_and_your_grade_stick(client, tmp_path):
    r = client.put("/api/v1/quality/pop_total", json={"starred": True, "grade": "C"}).json()
    assert r["starred"] and r["grade"] == "C" and r["overridden"] and r["worked_grade"] == "A"
    assert qual.stars() == ["pop_total"] and qual.overrides() == {"pop_total": "C"}
    pop = next(i for i in client.get("/api/v1/indicators").json() if i["indicator_id"] == "pop_total")
    assert pop["grade"] == "C" and pop["starred"]
    back = client.put("/api/v1/quality/pop_total", json={"grade": None}).json()
    assert back["grade"] == "A" and not back.get("overridden")
    assert client.put("/api/v1/quality/pop_total", json={"grade": "E"}).status_code == 422
    assert client.put("/api/v1/quality/nonsense", json={"starred": True}).status_code == 404


def test_summary_counts_and_changes_since_the_build_before(client, tmp_path):
    first = client.get("/api/v1/quality/summary").json()
    assert sum(first["totals"].values()) == len(client.get("/api/v1/quality").json()["indicators"])
    assert first["changes"] is None and first["by_domain"] and first["by_source"]
    # The build before had population at D: it has gained a grade since.
    build = main._build_id()
    earlier = {k: dict(v) for k, v in qual.load(tmp_path, build).items()}
    earlier["pop_total"]["grade"] = "D"
    qual.save(tmp_path, "00000000T000000Z", earlier)
    s = client.get("/api/v1/quality/summary").json()
    assert s["since"] == "00000000T000000Z"
    assert {"indicator_id": "pop_total", "name": "Population", "from": "D", "to": "A"} in s["changes"]["gained"]
