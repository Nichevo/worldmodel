"""Top crops endpoints, against a copy of the sample warehouse with crop areas added for three
countries, two US counties in one state, and New Zealand regions' horticulture."""

import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import core, main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.execute("INSERT INTO vintages VALUES ('croptest', 'v1', 'v1', now(), 'x', 0, 'test', true)")
    for i in ("crop_area_ha", "usreg_crop_area_ha", "nzreg_hort_apples_ha", "nzreg_hort_wine_grapes_ha"):
        con.execute("DELETE FROM indicators WHERE indicator_id = ?", [i])
        con.execute("INSERT INTO indicators (indicator_id, name, domain, unit, decimals, frequency) VALUES (?, ?, 'land', 'ha', 0, 'A')",
                    [i, i])
        con.execute("DELETE FROM indicator_sources WHERE indicator_id = ?", [i])
        con.execute("INSERT INTO indicator_sources VALUES (?, 'croptest', ?, 1, 0, '')", [i, i])
    cols = [r[0] for r in con.execute("DESCRIBE entities").fetchall()]
    for eid, nm in (("US-IA", "Iowa"), ("US-19169", "Story County, IA"), ("US-19153", "Polk County, IA")):
        con.execute("DELETE FROM entities WHERE entity_id = ?", [eid])
        vals = {"entity_id": eid, "short_name": nm, "name": nm, "type": "subnational"}
        con.execute(f"INSERT INTO entities ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    assert "short_name" in cols
    con.execute("INSERT INTO subdivisions VALUES ('US-IA', 'USA', 'state', '19'), ('US-19169', 'US-IA', 'county', '169'), "
                "('US-19153', 'US-IA', 'county', '153')")
    obs = []
    for ent, crops in (("NZL", {"kiwifruit": 13_500, "wheat": 40_000, "barley": 50_000}),
                       ("AUS", {"wheat": 12e6, "barley": 4e6}), ("USA", {"maize": 35e6, "soybeans": 33e6})):
        obs += [(ent, "crop_area_ha", 2023, f"crop={c}", v) for c, v in crops.items()]
    obs += [("AUS", "crop_area_ha", 1990, "crop=wheat", 9e6)]
    obs += [("US-19169", "usreg_crop_area_ha", 2022, "crop=maize", 65_000), ("US-19169", "usreg_crop_area_ha", 2022, "crop=soybeans", 48_000),
            ("US-19153", "usreg_crop_area_ha", 2022, "crop=soybeans", 30_000), ("US-19153", "usreg_crop_area_ha", 2022, "crop=hay", 2_000),
            ("US-IA", "usreg_crop_area_ha", 2022, "crop=maize", 5e6)]
    obs += [("NZ-MBH", "nzreg_hort_wine_grapes_ha", 2024, "", 28_000), ("NZ-MBH", "nzreg_hort_apples_ha", 2024, "", 100),
            ("NZ-HKB", "nzreg_hort_apples_ha", 2024, "", 5_000), ("NZ-HKB", "nzreg_hort_wine_grapes_ha", 2024, "", 5_000 - 1)]
    con.executemany("INSERT INTO observations (entity_id, indicator_id, period_start, freq, breakdown, variant, source_id, vintage, value, status) "
                    "VALUES (?, ?, ?, 'A', ?, 'central', 'croptest', 'v1', ?, 'E')",
                    [(e, i, date(y, 1, 1), b, v) for e, i, y, b, v in obs])
    con.close()
    core.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    core.warehouse = Warehouse(str(SAMPLE))


def test_levels(client):
    got = {r["level"]: r for r in client.get("/api/v1/crops/levels").json()}
    assert set(got) == {"world", "us_state", "us_county", "nz_region"}
    assert got["world"]["years"] == [1990, 2023] and got["us_county"]["places"] == 2


def test_top_world(client):
    t = client.get("/api/v1/crops/top").json()
    assert t["year"] == 2023 and t["years"] == [1990, 2023]
    by = {p["id"]: p for p in t["places"]}
    assert by["NZL"]["top"][0]["crop"] == "barley" and by["NZL"]["total_ha"] == 103_500
    assert by["USA"]["top"][1] == {"crop": "soybeans", "ha": 33e6, "share": pytest.approx(33 / 68 * 100)}
    legend = {c["id"]: c for c in t["crops"]}
    assert legend["wheat"]["top_in"] == 1 and legend["wheat"]["name"] == "Wheat" and legend["kiwifruit"]["top_in"] == 0
    assert legend["maize"]["color"] == "#e8478b"
    old = client.get("/api/v1/crops/top", params={"year": 1990}).json()
    assert [p["id"] for p in old["places"]] == ["AUS"]


def test_top_us_and_nz(client):
    c = client.get("/api/v1/crops/top", params={"level": "us_county"}).json()
    assert {p["id"]: p["top"][0]["crop"] for p in c["places"]} == {"US-19169": "maize", "US-19153": "soybeans"}
    s = client.get("/api/v1/crops/top", params={"level": "us_state"}).json()
    assert [p["id"] for p in s["places"]] == ["US-IA"]
    nz = client.get("/api/v1/crops/top", params={"level": "nz_region"}).json()
    assert {p["id"]: p["top"][0]["crop"] for p in nz["places"]} == {"NZ-MBH": "grapes", "NZ-HKB": "apples"}
    assert "horticultural" in nz["note"]
    assert client.get("/api/v1/crops/top", params={"level": "mars"}).status_code == 422


def test_where_and_place(client):
    w = client.get("/api/v1/crops/where/soybeans", params={"level": "us_county"}).json()
    assert w["values"]["US-19153"] == {"ha": 30_000, "share": pytest.approx(30 / 32 * 100), "rank": 1}
    assert w["values"]["US-19169"]["rank"] == 2 and w["name"] == "Soybeans"
    p = client.get("/api/v1/crops/place/AUS").json()
    assert p["years"] == [1990, 2023] and p["crops"][0]["id"] == "wheat" and p["crops"][0]["ha"] == {"1990": 9e6, "2023": 12e6}
    nz = client.get("/api/v1/crops/place/NZ-MBH").json()
    assert nz["level"] == "nz_region" and nz["crops"][0]["id"] == "grapes"
