"""Laws endpoints: the rules stored, one rule for every country with the year its value began,
and one country's rules, on a copy of the sample warehouse with a rule added."""

import shutil

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    src, vin = con.execute("SELECT source_id, vintage FROM vintages WHERE is_latest LIMIT 1").fetchone()
    cols = [r[0] for r in con.execute("DESCRIBE indicators").fetchall()]
    base = dict(zip(cols, con.execute("SELECT * FROM indicators LIMIT 1").fetchone()))
    base.update(indicator_id="law_same_sex_marriage", name="Same-sex marriage is legal", unit="yes/no", decimals=0, domain="laws",
                description="Whether same-sex couples can marry.")
    con.execute(f"INSERT INTO indicators VALUES ({', '.join('?' * len(cols))})", [base[c] for c in cols])
    rows = [(e, "law_same_sex_marriage", f"{y}-01-01", "A", "", "central", src, vin, float(e == "NZL" and y >= 2013), "E")
            for e in ("NZL", "AUS") for y in range(2010, 2016)]
    con.executemany("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_rules_listed(client):
    r = client.get("/api/v1/laws").json()
    assert [(x["indicator_id"], x["countries"], x["first"], x["last"]) for x in r] == [("law_same_sex_marriage", 2, 2010, 2015)]


def test_one_rule_with_the_year_it_began(client):
    r = client.get("/api/v1/laws/law_same_sex_marriage").json()
    assert r["year"] == 2015
    assert {x["entity_id"]: (x["value"], x["since"]) for x in r["rows"]} == {"NZL": (1, 2013), "AUS": (0, 2010)}
    assert client.get("/api/v1/laws/law_same_sex_marriage", params={"year": 2012}).json()["rows"][1]["value"] == 0


def test_a_countrys_rules(client):
    r = client.get("/api/v1/entities/NZL/laws").json()
    rule = r["rules"][0]
    assert (rule["value"], rule["since"], rule["changed"]) == (1, 2013, True)
