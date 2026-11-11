"""Transport, tourism and networks endpoints, against a copy of the sample warehouse with a
few rivers, a basin, a cable, chokepoint days and port months added. Live planes and ships
are tested with their network calls replaced."""

import json
import shutil
from datetime import date, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import live, main
from worldmodel_api.warehouse import SAMPLE, Warehouse

LINE = {"type": "LineString", "coordinates": [[175.0, -38.0], [176.0, -37.5]]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    geo = [
        ("rivers", "1:3", None, 3, {"flow": 340, "order": 3}, "NZL", 175.0, -38.0, 176.0, -37.5, LINE),
        ("rivers", "2:5", None, 5, {"flow": 12, "order": 5}, "NZL", 175.0, -38.0, 176.0, -37.5, LINE),
        ("basins", "600", "Murray basin", 1, {"area": 1050000, "shares": {"AUS": 1.0}, "of_country": {"AUS": 0.14},
                                                "flow": 420, "transboundary": False}, "AUS", 138.5, -37.0, 150.0, -26.0,
         {"type": "MultiPolygon", "coordinates": [[[[138.5, -37], [138.5, -26], [150, -26], [150, -37], [138.5, -37]]]]}),
        ("cables", "southern-cross-next", "Southern Cross NEXT", 1, {"rfs": 2022, "owners": "Spark"}, "AUS,FJI,NZL,USA",
         151.2, -33.9, 178.4, -18.1, {"type": "LineString", "coordinates": [[151.2, -33.9], [178.4, -18.1]]}),
    ]
    con.executemany("INSERT INTO geo_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'x', 'v1')",
                    [(*g[:4], json.dumps(g[4]), *g[5:10], json.dumps(g[10])) for g in geo])
    last = date(2024, 12, 31)
    days = [("chokepoint1", "Suez Canal", last - timedelta(days=i), 30.0 if i < 200 else 70.0) for i in range(800)]
    con.executemany("INSERT INTO chokepoint_traffic VALUES (?, ?, ?, ?, 10, 10, 5, 5, 1e6, 'portwatch', 'v1')", days)
    con.executemany("INSERT INTO port_traffic VALUES ('port1', 'NZL', 2024, ?, 100, 1000, 2000, 'portwatch', 'v1')",
                    [(m,) for m in range(1, 13)])
    con.execute("INSERT INTO airport_traffic VALUES ('NZAA', 'Auckland', 'NZL', 2024, 18500000, 140000, 'airport_traffic', 'v1')")
    con.execute("""INSERT INTO events (event_id, source_id, vintage, entity_id, kind, subkind, title, start_date, precision, deaths)
                   VALUES ('wikidata:a1', 'wikidata', 'v1', 'NZL', 'transport', 'air', 'Air New Zealand Flight 901', '1979-11-28', 'day', 257),
                          ('wikidata:a2', 'wikidata', 'v1', 'NZL', 'transport', 'sea', 'Small boat', '2001-01-01', 'day', 3)""")
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_geo_by_window_and_zoom(client):
    far = client.get("/api/v1/geo/rivers", params={"west": 170, "south": -45, "east": 180, "north": -30, "zoom": 3}).json()
    assert [f["properties"]["id"] for f in far["features"]] == ["1:3"]
    near = client.get("/api/v1/geo/rivers", params={"west": 170, "south": -45, "east": 180, "north": -30, "zoom": 7}).json()
    assert {f["properties"]["id"] for f in near["features"]} == {"1:3", "2:5"}
    # A Pacific-centred window across the date line still finds them
    wrap = client.get("/api/v1/geo/rivers", params={"west": 170, "south": -45, "east": 200, "north": -30, "zoom": 7}).json()
    assert len(wrap["features"]) == 2
    none = client.get("/api/v1/geo/rivers", params={"west": 0, "south": 0, "east": 10, "north": 10, "zoom": 7}).json()
    assert none["features"] == []
    assert client.get("/api/v1/geo/nonsense").status_code == 404


def test_basin_card_and_depends(client):
    b = client.get("/api/v1/geo/basins/600").json()
    assert b["name"] == "Murray basin" and b["split"][0]["id"] == "AUS" and b["split"][0]["share"] == 1.0
    assert b["people"] and b["people"] > 1_000_000  # 14% of Australia's people, roughly
    d = client.get("/api/v1/depends/cables/southern-cross-next").json()
    assert {c["id"] for c in d["countries"]} == {"AUS", "FJI", "NZL", "USA"}
    s = client.get("/api/v1/depends/chokepoints/Strait of Hormuz").json()
    assert {c["id"] for c in s["countries"]} == {"IRN", "OMN", "ARE"}


def test_transport_page_and_country(client):
    t = client.get("/api/v1/transport").json()
    suez = t["chokepoints"][0]
    assert suez["name"] == "Suez Canal" and suez["now"] == 30 and suez["change"] < -50
    assert t["ports"][0]["calls"] == 1200 and t["airports"][0]["airport"] == "NZAA"
    assert [a["title"] for a in t["accidents"]] == ["Air New Zealand Flight 901"]  # the 3-death one is under 10
    assert any(e["subkind"] == "pipeline" for e in t["infrastructure"]) or t["infrastructure"] == []
    assert t["loaded"]["rivers"] == 2
    c = client.get("/api/v1/transport/country/NZL").json()
    assert c["networks"]["cables"][0]["name"] == "Southern Cross NEXT" and c["ports"][0]["port_id"] == "port1"
    assert client.get("/api/v1/transport/country/AUS").json()["networks"]["basins"][0]["id"] == "600"
    ck = client.get("/api/v1/transport/chokepoint/chokepoint1", params={"start": 2023}).json()
    assert ck["name"] == "Suez Canal" and ck["points"] and {c["id"] for c in ck["depends"]} == {"EGY"}
    assert len(client.get("/api/v1/transport/port/port1").json()["months"]) == 12


def test_tourism(client):
    t = client.get("/api/v1/tourism").json()
    assert t["covid"]["start_date"] == "2020-03-01" and "visitors" in t["tabs"]
    c = client.get("/api/v1/tourism/country/NZL").json()
    assert c["entity"] == "NZL" and isinstance(c["sites"], list)


def test_live_planes(client, monkeypatch):
    calls = []

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"states": [["abc", "ANZ1 ", "New Zealand", 0, 0, 174.8, -37.0, 10000, False, 250, 90, 0, None, 0, None, False, 0],
                               ["def", "GRND", "New Zealand", 0, 0, 174.8, -37.0, 0, True, 0, 0, 0, None, 0, None, False, 0]]}

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            calls.append(params)
            return Resp()

    monkeypatch.setattr(live.httpx, "Client", Client)
    live.PLANES.__init__()
    p = client.get("/api/v1/live/planes", params={"west": 170, "south": -45, "east": 190, "north": -30}).json()
    assert [f["properties"]["callsign"] for f in p["features"]] == ["ANZ1"]  # the one on the ground left out
    assert len(calls) == 2  # across the date line: two boxes
    client.get("/api/v1/live/planes", params={"west": 172, "south": -40, "east": 176, "north": -35})
    assert len(calls) == 2  # inside the last box, within the minute: no new request


def test_live_ships_need_a_key_and_read_messages(client, monkeypatch):
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    r = client.get("/api/v1/live/ships", params={"west": 170, "south": -45, "east": 180, "north": -30}).json()
    assert "AISSTREAM_API_KEY" in r["error"]
    ships = live.Ships()
    ships.take({"MessageType": "PositionReport", "MetaData": {"MMSI": 512000001, "ShipName": "AOTEAROA ", "latitude": -36.8, "longitude": 174.8},
                "Message": {"PositionReport": {"Sog": 12.5, "TrueHeading": 511, "Cog": 80}}})
    ships.take({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 512000002, "ShipName": "NO POSITION"}, "Message": {}})
    monkeypatch.setenv("AISSTREAM_API_KEY", "k")
    monkeypatch.setattr(ships, "_run", lambda key: None)
    got = ships.get(170, -45, 180, -30)
    assert [(f["properties"]["name"], f["properties"]["heading"]) for f in got["features"]] == [("AOTEAROA", 80)]
