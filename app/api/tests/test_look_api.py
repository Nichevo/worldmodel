"""Page summaries: where a country sits among countries (with a guideline), recovery against
2019, and land by use, on a copy of the sample warehouse with made-up rows added."""

import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import look, main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    countries = [r[0] for r in con.execute("SELECT entity_id FROM entities WHERE type = 'country' ORDER BY 1").fetchall()]
    rows = []

    def put(e, ind, y, v, src):
        rows.append((e, ind, date(y, 1, 1), "A", "", "central", src, "t", float(v), "E"))

    for i, e in enumerate(countries):
        put(e, "pm25_exposure", 2020, 10 + i, "who_air")
    put("NZL", "pm25_exposure", 2020, 4.0, "who_air")
    put("world", "pm25_exposure", 2020, 31.7, "who_air")
    for y, nz, au in ((2018, 3.8e6, 9.2e6), (2019, 3.9e6, 9.5e6), (2020, 1e6, 1.8e6), (2023, 3.3e6, 7.6e6)):
        put("NZL", "tourist_arrivals", y, nz, "wdi")
        put("AUS", "tourist_arrivals", y, au, "wdi")
    for y, past, plant in ((1990, 14e6, 1.2e6), (2021, 9.8e6, 1.8e6)):
        put("NZL", "land_pasture_ha", y, past, "faostat_land")
        put("NZL", "land_planted_forest_ha", y, plant, "faostat_land")
        put("NZL", "land_natural_forest_ha", y, 8e6, "faostat_land")
        put("NZL", "land_area_ha", y, 26.3e6, "faostat_land")
    con.executemany("INSERT INTO observations VALUES (" + ", ".join("?" * 10) + ")", rows)
    for s in sorted({r[6] for r in rows}):
        con.execute("INSERT INTO vintages BY NAME SELECT ? AS source_id, 't' AS vintage, 't' AS release, true AS is_latest", [s])
    have = {r[0] for r in con.execute("SELECT indicator_id FROM indicators").fetchall()}
    for i, src, u in (("pm25_exposure", "who_air", "µg/m³"), ("tourist_arrivals", "wdi", "people"), ("land_pasture_ha", "faostat_land", "ha"),
                      ("land_planted_forest_ha", "faostat_land", "ha"), ("land_natural_forest_ha", "faostat_land", "ha"), ("land_area_ha", "faostat_land", "ha")):
        if i not in have:
            con.execute("INSERT INTO indicators BY NAME SELECT ? AS indicator_id, ? AS name, '' AS description, 'x' AS domain, ? AS unit, "
                        "1 AS decimals, 'A' AS frequency, '' AS breakdowns, 'none' AS agg_method, true AS default_on", [i, i, u])
        con.execute("DELETE FROM indicator_sources WHERE indicator_id = ?", [i])
        con.execute("INSERT INTO indicator_sources BY NAME SELECT ? AS indicator_id, ? AS source_id, ? AS series, 1.0 AS scale, 1 AS rank", [i, src, i])
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_ranked_with_guideline(client):
    r = client.get("/api/v1/look/ranked/pm25_exposure", params={"keys": "NZL,AUS"}).json()
    assert r["lower_better"] and r["guide"]["value"] == 5.0 and r["guide"]["meeting"] == 1
    assert r["line"].startswith("NZL") or "1st lowest" in r["line"]
    assert "1st lowest of" in r["line"]
    ids = [x["entity_id"] for x in r["rows"]]
    assert ids[0] == "NZL" and "world" in ids and "AUS" in ids
    assert client.get("/api/v1/look/ranked/nothing_here").status_code == 404


def test_recovery_and_land_mix(client):
    r = client.get("/api/v1/look/recovery/tourist_arrivals", params={"keys": "NZL,AUS"}).json()
    nz = r["lines"][0]
    assert nz["of_base"] == 85 and nz["year"] == 2023
    assert r["finding"].split(" at 85% of its 2019 level; ")[1].endswith("at 80% (2023)")
    m = client.get("/api/v1/look/land-mix/NZL").json()
    parts = {p["id"]: p for p in m["parts"]}
    assert parts["pasture"]["share"] == 37.3 and parts["pasture"]["change"] == -30.0 and parts["planted"]["change"] == 50.0
    assert "forest" not in parts and parts["other"]["share"] == round(100 - 37.3 - 30.4 - 6.8, 1)
    assert m["finding"] == "Planted forest up 50%; pasture and grazing down 30% since 1990"


def test_ordinal():
    assert look._ordinal(1) == "1st" and look._ordinal(12) == "12th" and look._ordinal(23) == "23rd"
