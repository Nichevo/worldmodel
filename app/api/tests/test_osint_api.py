"""OSINT detail endpoints on the sample warehouse (its OSINT tables come from the data side's test
files: scripts/sample/add_osint.py). Live military planes are tested with the network call replaced."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import live, main, osint
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_api import core


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    core.warehouse = Warehouse(str(SAMPLE))
    return TestClient(main.app)


def test_map_events(client):
    r = client.get("/api/v1/osint/events", params={"days": 3650, "end": "2025-12-31"}).json()
    assert r["loaded"] and r["count"] >= 6
    ids = {f["properties"]["id"] for f in r["features"]}
    assert "acled:NZL1" in ids and "ged:2" in ids
    deaths = [f["properties"]["deaths"] or 0 for f in r["features"]]
    assert deaths == sorted(deaths, reverse=True)  # biggest first
    # a Pacific-centred window across the date line still finds Wellington
    r = client.get("/api/v1/osint/events", params={"days": 3650, "end": "2025-12-31", "west": 160, "east": 200,
                                                   "south": -50, "north": -30}).json()
    assert [f["properties"]["id"] for f in r["features"]] == ["acled:NZL1"]
    r = client.get("/api/v1/osint/events", params={"days": 3650, "end": "2025-12-31", "kinds": "protest,riot"}).json()
    assert {f["properties"]["kind"] for f in r["features"]} == {"protest", "riot"}


def test_country_months_and_mismatch(client):
    r = client.get("/api/v1/osint/country/UKR", params={"months": 240}).json()
    months = {m["month"]: m for m in r["months"]}
    assert months["2024-02"]["ucdp_deaths"] == 120
    assert months["2025-01"]["ucdp_deaths"] == 25 and months["2025-01"]["acled_deaths"] == 7
    assert r["has"]["ucdp"] and r["has"]["acled"]
    items = [{"crisiswatch": cw, "ucdp_deaths": d, "acled_deaths": None, "violence": 0, "protests": 0, "riots": 0}
             for cw, d in [(None, 100), (None, 100), (None, 100), ("deteriorated", 20), ("improved", 400)]]
    osint._flag(items)
    assert items[3]["mismatch"] and "worse" in items[3]["mismatch"]
    assert items[4]["mismatch"] and "better" in items[4]["mismatch"]
    nz = client.get("/api/v1/osint/country/NZL", params={"months": 240}).json()
    assert any(m["protests"] for m in nz["months"])


def test_crisiswatch_month(client):
    r = client.get("/api/v1/osint/crisiswatch-month", params={"month": "2025-01"}).json()
    assert r["countries"]["UKR"]["ucdp_deaths"] == 25 and r["countries"]["UKR"]["acled_deaths"] == 7
    assert r["countries"]["IRN"]["outages"] >= 1


def test_wars_and_front(client):
    ws = client.get("/api/v1/osint/wars").json()["wars"]
    assert ws[0]["id"] == "russia_ukraine" and ws[0]["area"]["day"] == "2026-11-20"
    w = client.get("/api/v1/osint/wars/russia_ukraine").json()
    tanks = next(d for d in w["latest"] if d["category"] == "tanks")
    assert tanks["RUS_seen"] == 4085 and tanks["RUS_claimed"] == 12485 and tanks["UKR_seen"] == 1100
    assert w["statuses"]["RUS"]["captured"] == 3625
    assert [a[0] for a in w["areas"]] == ["2024-07-08", "2026-11-19", "2026-11-20"]
    f = client.get("/api/v1/osint/front/russia_ukraine", params={"day": "2025-01-01"}).json()
    assert f["features"][0]["properties"]["day"] == "2024-07-08" and "2026-11-20" in f["days"]
    assert client.get("/api/v1/osint/wars/nope").status_code == 404


def test_sanctions(client):
    r = client.get("/api/v1/osint/sanctions").json()
    assert r["loaded"] and [a["id"] for a in r["authorities"]][:4] == ["NZL", "AUS", "GBR", "USA"]
    rus = next(t for t in r["rows"] if t["target"] == "RUS")
    assert rus["cells"]["NZL"]["listed"] == 1 and rus["cells"]["eu"]["listed"] == 1
    assert r["recent"][0]["first_seen"] >= r["recent"][-1]["first_seen"]
    s = client.get("/api/v1/osint/sanctions/search", params={"q": "shadow"}).json()["items"]
    assert s[0]["schema"] == "Vessel" and s[0]["url"].startswith("https://www.opensanctions.org/")
    assert "9123456" in osint.sanctioned_ship_ids(main.rows)


def test_military_and_arms(client):
    r = client.get("/api/v1/osint/military", params={"entities": "NZL,USA"}).json()
    assert r["loaded"] and r["edition"] == 2026
    nz = r["countries"][0]
    assert nz["entity_id"] == "NZL" and nz["values"]["gfp_personnel_active"]["value"] == 8750
    pi = nz["values"]["gfp_power_index"]
    assert pi["rank"] == 3 and pi["of"] == 3  # lower is stronger: New Zealand last of the three
    us = r["countries"][1]["values"]["gfp_power_index"]
    assert us["rank"] == 1
    m = client.get("/api/v1/osint/military/map", params={"measure": "gfp_power_index"}).json()
    assert m["values"]["AUS"] == 0.3298
    a = client.get("/api/v1/osint/arms/NZL").json()
    assert a["suppliers"][0]["partner"] == "USA" and a["deals"][0]["weapon"] == "P-8A Poseidon"


def test_military_planes(monkeypatch):
    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ac": [{"hex": "ae1234", "flight": "RCH123 ", "t": "C17", "lat": -41.3, "lon": 174.8, "alt_baro": 30000, "gs": 450},
                           {"hex": "ae9999", "lat": 50.0, "lon": 10.0, "alt_baro": "ground"}]}

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return Resp()

    monkeypatch.setattr(live.httpx, "Client", Client)
    planes = live.MilitaryPlanes()
    r = planes.get(160, -50, 200, -30)
    assert r["count"] == 1 and r["features"][0]["properties"]["callsign"] == "RCH123"
    assert r["features"][0]["properties"]["altitude_m"] == 9144
