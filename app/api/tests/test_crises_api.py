"""Financial crises endpoint on a copy of the sample warehouse with made-up crisis years."""

import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("crises_api")
    path = d / "crises.duckdb"
    shutil.copy(SAMPLE, path)
    con = duckdb.connect(str(path))
    obs, ev = [], []
    spells = {"ARG": [("banking", 2001, 2002), ("default_external", 2001, 2003)], "NZL": [("banking", 1987, 1987)],
              "USA": [("banking", 2007, 2008)]}
    for e, sp in spells.items():
        for y in range(1985, 2011):
            for k in ("banking", "default_external"):
                on = any(k == kk and a <= y <= b for kk, a, b in sp)
                obs.append((e, f"crisis_{k}", date(y, 1, 1), "A", "", "central", "crisis_history", "t", float(on), "E"))
        for i, (k, a, b) in enumerate(sp):
            ev.append((f"{e}{i}", e, "crisis_history", "t", "crisis", k, k, date(a, 1, 1), date(b, 12, 31), "year"))
    con.executemany("INSERT INTO observations VALUES (" + ", ".join("?" * 10) + ")", obs)
    con.execute("INSERT INTO vintages BY NAME SELECT 'crisis_history' AS source_id, 't' AS vintage, 't' AS release, "
                "true AS is_latest")
    con.executemany("INSERT INTO events BY NAME SELECT ? AS event_id, ? AS entity_id, ? AS source_id, ? AS vintage, "
                    "? AS kind, ? AS subkind, ? AS title, ? AS start_date, ? AS end_date, ? AS precision", ev)
    con.close()
    mp = pytest.MonkeyPatch()
    mp.setenv("WORLDMODEL_HOME", str(d))
    mp.setenv("WORLDMODEL_USER_DIR", str(d / "user"))
    old = main.warehouse
    main.warehouse = Warehouse(str(path))
    yield TestClient(main.app)
    main.warehouse = old
    mp.undo()


def test_waves_and_strips(client):
    r = client.get("/api/v1/crises", params={"start": 1985}).json()
    assert r["countries"] == 3 and r["years"] == [1985, 2010]
    bank = {p["year"]: p for p in r["waves"]["banking"]}
    assert bank[2001]["count"] == 1 and bank[2001]["of"] == 3 and bank[2001]["share"] == 33.3
    assert {p["year"]: p["count"] for p in r["waves"]["any"]}[2003] == 1
    assert r["strips"][0]["entity_id"] == "ARG" and r["strips"][0]["years"] == 5
    only = client.get("/api/v1/crises", params={"kind": "banking", "entity": "NZL", "start": 1985}).json()
    assert only["strips"][0]["entity_id"] == "NZL"
    assert all(s["kind"] == "banking" for st in only["strips"] for s in st["spells"])
    assert client.get("/api/v1/crises", params={"kind": "tulips"}).status_code == 422
