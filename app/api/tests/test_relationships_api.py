"""Relationships endpoints on the sample warehouse with a small made-up scan beside it:
the ranked list and its filters, one pair with its scatter points, links to events,
keeping a pair as a what-if driver, and the key register."""

import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_contract import relations as rel

LAGS = "[0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.4, 0.1, 0.0, 0.0, 0.0]"


def _scan(home, build_id):
    d = rel.results_dir(home)
    d.mkdir(parents=True)
    con = duckdb.connect()
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('gdp_growth', 'inflation', ['together', 'first', 'holds'], 3.4, 9000, 150, 1980, 2023, -0.4, -0.35, 1e-6, 1e-5,
         -0.3, -0.25, 1e-4, 1e-3, true, 'x', 1, 1e-4, 1e-3, 0.5, 0.6, 40, NULL, 150, {LAGS}::DOUBLE[],
         '{{"income-high": [-0.5, 40, 0.001]}}', true, false, false, 'Both follow the economy.'),
        ('pop_total', 'pop_male', ['together'], -1.0, 9000, 200, 1960, 2023, 0.99, 0.99, 1e-9, 1e-8,
         NULL, NULL, NULL, NULL, false, NULL, NULL, 0.5, 0.6, 0.5, 0.6, NULL, NULL, NULL, {LAGS}::DOUBLE[],
         '{{}}', false, true, true, 'Nearly the same figure.'))
        t(x, y, labels, score, n_obs, n_countries, year_from, year_to, r, r_two_way, p_together, q_together,
          beta, slope, p_holds, q_holds, control_used, "first", best_lag, p_x_first, q_x_first, p_y_first, q_y_first,
          countries_x_first, countries_y_first, countries_tested, lags, groups, in_drivers, near_same, same_source, note))
        TO '{(d / f"{build_id}.pairs.parquet").as_posix()}' (FORMAT parquet)""")
    con.execute(f"""COPY (SELECT 'recession' AS kind, 'inflation' AS indicator_id, 30 AS n_events, [-3, -2, -1, 0, 1, 2, 3] AS h,
        [0.1, 0.0, 0.0, -1.0, -2.0, -2.5, -3.0]::DOUBLE[] AS effect, [0.2, 0.2, 0.0, 0.3, 0.4, 0.5, 0.6]::DOUBLE[] AS se,
        [30, 30, 30, 30, 30, 30, 30] AS n, -3.0 AS effect_3, 1e-4 AS p, 1e-3 AS q, true AS significant, false AS built_in, false AS diverging_before,
        0.1 AS pre_trend, 'change in points' AS unit)
        TO '{(d / f"{build_id}.events.parquet").as_posix()}' (FORMAT parquet)""")
    names = {i: {"name": i.replace("_", " ").title(), "domain": dom, "unit": u, "kind": k, "source": "s"}
             for i, dom, u, k in (("gdp_growth", "economy", "percent", "diff"), ("inflation", "economy", "percent", "diff"),
                                  ("pop_total", "population", "persons", "pct"), ("pop_male", "population", "persons", "pct"))}
    (d / f"{build_id}.json").write_text(json.dumps({
        "build_id": build_id, "finished_at": "2026-11-05T00:00:00+00:00", "seconds": 90, "partial": False, "indicators": 4,
        "pairs_possible": 6, "pairs_tested": 6, "pairs_thin": 0, "pairs_kept": 2,
        "label_counts": {"together": 2, "first": 1, "holds": 1}, "events_tested": 4, "events_kept": 1,
        "settings": {"relations_fdr": 0.05}, "names": names}))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    _scan(tmp_path, SAMPLE.stem)
    yield TestClient(main.app)


def test_no_scan_yet(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    r = TestClient(main.app).get("/api/v1/relationships").json()
    assert r == {"scan": None, "total": 0, "rows": []}


def test_list_and_filters(client):
    r = client.get("/api/v1/relationships").json()
    assert r["scan"]["stale"] is False and r["scan"]["domains"] == ["economy", "population"]
    assert [(p["x"], p["y"]) for p in r["rows"]] == [("gdp_growth", "inflation")]  # nearly-the-same pair hidden
    assert r["rows"][0]["x_name"] == "Gdp Growth" and r["rows"][0]["x_unit"] == "change in percentage points"
    assert client.get("/api/v1/relationships?hide_same=false").json()["total"] == 2
    assert client.get("/api/v1/relationships?hide_same=false&hide_same_source=true").json()["total"] == 1
    assert client.get("/api/v1/relationships?label=holds&domain=population&hide_same=false").json()["total"] == 0
    assert client.get("/api/v1/relationships?group=income-high").json()["total"] == 1
    assert client.get("/api/v1/relationships?q=inflat").json()["total"] == 1
    assert client.get("/api/v1/relationships?label=nonsense").status_code == 422
    assert r["rows"][0]["built_from"] is None and r["scan"]["built_from_label"] == "Built from each other"
    assert client.get("/api/v1/relationships?built=only&hide_same=false").json()["total"] == 0
    assert client.get("/api/v1/relationships?built=hide").json()["total"] == 1
    assert client.get("/api/v1/relationships?built=nonsense").status_code == 422


def test_pairs_built_from_each_other_are_tagged_and_listed_last(client, monkeypatch):
    from worldmodel_api import relationships
    monkeypatch.setattr(relationships, "_ratios", lambda: {"pop_male": ("pop_male", "pop_total")})
    monkeypatch.setitem(relationships._cache, "key", None)  # read again, and again after the test
    r = client.get("/api/v1/relationships?hide_same=false").json()
    assert [(p["x"], p["built_from"]) for p in r["rows"]] == [("gdp_growth", None), ("pop_total", "a ratio and what it is made from")]
    assert [p["x"] for p in client.get("/api/v1/relationships?hide_same=false&built=only").json()["rows"]] == ["pop_total"]
    assert client.get("/api/v1/relationships?hide_same=false&built=hide").json()["total"] == 1


def test_pair_with_points(client):
    r = client.get("/api/v1/relationships/pair", params={"x": "inflation", "y": "gdp_growth"}).json()
    assert r["pair"]["flipped"] is True and r["pair"]["first"] == "x"
    assert len(r["points"]) > 1000 and r["names"]["NZL"] == "New Zealand"
    nz = [p for p in r["points"] if p[0] == "NZL"]
    assert all(isinstance(p[1], int) for p in nz)


def test_event_links(client):
    r = client.get("/api/v1/relationships/events?kind=recession").json()
    assert r["total"] == 1 and r["rows"][0]["name"] == "Inflation" and r["rows"][0]["effect_3"] == -3.0
    assert client.get("/api/v1/relationships/events?kind=coup").json()["total"] == 0


def test_drivers(client):
    bad = client.post("/api/v1/drivers", json={"driver": "pop_total", "target": "pop_male"})
    assert bad.status_code == 422
    d = client.post("/api/v1/drivers", json={"driver": "gdp_growth", "target": "inflation"}).json()
    assert d["slope"] == -0.25 and d["lag"] == 1 and d["target_kind"] == "diff"
    other = client.post("/api/v1/drivers", json={"driver": "inflation", "target": "gdp_growth"}).json()
    assert other["slope"] == pytest.approx(-4.0) and other["lag"] == 0
    assert len(client.get("/api/v1/drivers").json()) == 2
    assert client.get("/api/v1/relationships").json()["rows"][0]["saved_driver"] is True
    assert client.delete(f"/api/v1/drivers/{d['id']}").status_code == 200
    assert client.delete("/api/v1/drivers/nope").status_code == 404


def test_keys(client, monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "x")
    keys = {k["source"]: k for k in client.get("/api/v1/keys").json()}
    assert {"statsnz", "gie_agsi", "eia"} <= set(keys) and "un_wpp" not in keys
    assert keys["eia"]["env"] == [{"name": "EIA_API_KEY", "set": True}] and keys["statsnz"]["unlocks"]
    assert "x" not in json.dumps(keys["eia"]["env"]).replace("EIA_API_KEY", "")
