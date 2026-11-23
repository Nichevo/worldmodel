"""Energy flows from two sources, power links between countries and the Grid now readers, on a
copy of the sample warehouse with a few rows added and answers shaped like the live services'."""

import shutil
from datetime import date, datetime, timezone

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import grid, main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    for src in ("mbie_energy", "unsd_energy", "eurostat_power_trade"):
        con.execute("INSERT INTO vintages VALUES (?, 'v1', 'v1', now(), 'x', 0, 'test', true)", [src])
    bal = [("mbie_energy", "Indigenous production", "Hydro", 90.0), ("mbie_energy", "Electricity generation", "Hydro", -90.0),
           ("mbie_energy", "Electricity generation", "Electricity", 150.0), ("mbie_energy", "Residential", "Electricity", 45.0),
           ("unsd_energy", "Indigenous production", "Hydro", 94.6), ("unsd_energy", "Electricity generation", "Hydro", -94.6),
           ("unsd_energy", "Electricity generation", "Electricity", 160.8), ("unsd_energy", "Residential", "Electricity", 46.8)]
    rows = [("NZL", "energy_balance_pj", f"flow={f}|fuel={g}", s, v) for s, f, g, v in bal]
    rows += [("ITA", "elec_imports_gwh", "origin=FRA", "eurostat_power_trade", 18000.0),
             ("FRA", "elec_imports_gwh", "origin=ITA", "eurostat_power_trade", 1500.0),
             ("FRA", "elec_exports_gwh", "origin=ITA", "eurostat_power_trade", 18500.0)]
    con.executemany("INSERT INTO observations (entity_id, indicator_id, period_start, freq, breakdown, variant, source_id, vintage, value, status) "
                    "VALUES (?, ?, ?, 'A', ?, 'central', ?, 'v1', ?, 'E')",
                    [(e, i, date(2022 if i.startswith("energy") else 2023, 1, 1), b, s, v) for e, i, b, s, v in rows])
    have = {r[0] for r in con.execute("SELECT country_id FROM cities WHERE capital = 'national'").fetchall()} \
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'cities'").fetchone()[0] else None
    if have is not None:
        for cid, cc, lon, lat in (("t-rome", "ITA", 12.5, 41.9), ("t-paris", "FRA", 2.35, 48.85)):
            if cc not in have:
                cols = [r[0] for r in con.execute("DESCRIBE cities").fetchall()]
                vals = {"city_id": cid, "name": cid, "country_id": cc, "lat": lat, "lon": lon, "capital": "national"}
                con.execute(f"INSERT INTO cities ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_energy_flow_sources(client):
    f = client.get("/api/v1/energy-flow", params={"entity": "NZL"}).json()
    assert f["source_id"] == "mbie_energy" and {s["source_id"] for s in f["sources"]} == {"mbie_energy", "unsd_energy"}
    assert f["totals"]["electricity_generated"] == 150.0
    u = client.get("/api/v1/energy-flow", params={"entity": "NZL", "source": "unsd_energy"}).json()
    assert u["source_id"] == "unsd_energy" and u["totals"]["electricity_generated"] == pytest.approx(160.8)
    assert client.get("/api/v1/energy-flow", params={"entity": "XYZ"}).json()["sources"] == []


def test_power_links(client):
    got = client.get("/api/v1/power-links").json()
    if not got["features"]:
        pytest.skip("the sample warehouse has no cities table")
    f = got["features"][0]["properties"]
    assert (f["from"], f["to"], f["sent"], f["back"], f["net"]) == ("FRA", "ITA", 18500, 1500, 17000)
    assert client.get("/api/v1/layers/power_links").json()["features"][0]["properties"]["from"] == "FRA"


def mock(routes: dict) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        for part, body in routes.items():
            if part in str(req.url):
                return httpx.Response(200, json=body)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_grid_nz():
    grid._kept.clear()
    t = lambda h, m: {"day": 23, "month": 10, "year": 2026, "hour": h, "minute": m}  # noqa: E731 (month counts from 0)
    c = mock({
        "current_generation": {"data": {"New Zealand": {"Hydro": {"generation": 3310, "capacity": 5415}, "Wind": {"generation": 711, "capacity": 1470},
                                                        "Gas": {"generation": 61, "capacity": 1280}, "Co-Gen": {"generation": 44, "capacity": 168},
                                                        "total": 4126}}, "timestamp": 1795404600},
        "load_data_graph": {"data": {"nzPoints": [[t(17, 0), 4600], [t(17, 5), 4650]]}},
        "hvdc": {"data": {"dcn_flow": [[t(16, 30), 873]], "dcs_flow": [[t(16, 30), 0]]}},
        "renewables_generation": {"data": [98.02]},
    })
    g = grid.grid_now("NZL", client=c)
    assert g["mix"][0] == {"fuel": "Hydro", "mw": 3310.0, "capacity": 5415.0} and g["renewable_share"] == 98.02
    assert g["demand_mw"] == 4650 and g["lines"][0]["points"][0][0] == "2026-11-23T04:00:00Z"  # 5 pm NZDT
    assert g["links"][0]["mw"] == 873 and "error" not in g


def test_grid_gb_and_keys(monkeypatch):
    grid._kept.clear()
    rows = [{"startTime": f"2026-11-22T{h:02d}:{m:02d}:00Z", "data": [{"fuelType": "CCGT", "generation": 4000}, {"fuelType": "WIND", "generation": 8000},
                                                                     {"fuelType": "INTFR", "generation": 1000}, {"fuelType": "INTNSL", "generation": -300}]}
            for h in (0, 1) for m in (0, 5, 30)]
    c = mock({"generation/outturn": rows, "carbonintensity": {"data": [{"intensity": {"forecast": 168, "actual": 163}}]}})
    g = grid.gb(c, datetime(2026, 11, 22, 2, tzinfo=timezone.utc))
    assert [s["fuel"] for s in g["series"]] == ["Wind", "Natural gas", "Imports"]
    assert len(g["series"][0]["points"]) == 4  # half-hours only
    assert g["carbon_g_kwh"] == 163 and g["links"][0] == {"name": "France (IFA)", "mw": 1000.0}
    assert g["renewable_share"] == pytest.approx(100 * 8000 / 12000, abs=0.1)
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENELECTRICITY_API_KEY", raising=False)
    assert "EIA_API_KEY" in grid.grid_now("USA", client=c)["error"]
    assert "OPENELECTRICITY_API_KEY" in grid.grid_now("AUS", client=c)["error"]
    assert "switched off" in grid.grid_now("GBR", on=False)["error"]


def test_grid_us(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "test")
    c = mock({"fuel-type-data": {"response": {"data": [
        {"period": "2026-11-22T05", "fueltype": "NG", "value": 200000}, {"period": "2026-11-22T05", "fueltype": "SUN", "value": 0},
        {"period": "2026-11-22T05", "fueltype": "WND", "value": 60000}, {"period": "2026-11-22T06", "fueltype": "NG", "value": 210000},
        {"period": "2026-11-22T06", "fueltype": "WND", "value": 65000}]}},
        "region-data": {"response": {"data": [{"period": "2026-11-22T06", "type": "D", "value": 450000}]}}})
    g = grid.us(c, datetime(2026, 11, 22, 8, tzinfo=timezone.utc))
    assert [s["fuel"] for s in g["series"]] == ["Natural gas", "Wind"] and g["demand_mw"] == 450000
    assert g["at"] == "2026-11-22T06:00:00Z"
