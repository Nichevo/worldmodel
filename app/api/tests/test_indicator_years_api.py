"""Year strips in the indicator drop-downs: /indicators/years (countries per year, history
against the source's own forecasts) and part_of on /indicators (nesting in the drop-downs)."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setattr(main, "warehouse", Warehouse(SAMPLE))
    main._years_cache["key"] = None
    main._ind_cache["key"] = None
    return TestClient(main.app)


def test_years_split_history_from_forecasts(client):
    years = client.get("/api/v1/indicators/years").json()
    pop = years["pop_total"]
    assert pop["countries"] and "UN WPP" in pop["by"]
    assert max(pop["e"]) > 100 and any(pop["p"])
    last_hist = pop["from"] + max(k for k, n in enumerate(pop["e"]) if n)
    first_proj = pop["from"] + min(k for k, n in enumerate(pop["p"]) if n)
    assert first_proj > last_hist - 2
    assert not years.get("births", {}).get("p")


def test_parts_sit_under_their_parent(client):
    by_id = {i["indicator_id"]: i for i in client.get("/api/v1/indicators").json()}
    assert by_id["pop_female"]["part_of"] == {"parent": "pop_total", "kind": "part"}
    assert by_id["life_expectancy_male"]["part_of"]["kind"] == "sex"
    assert by_id["pop_total"]["part_of"] is None
