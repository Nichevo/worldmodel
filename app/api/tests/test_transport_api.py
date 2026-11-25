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
        ("rivers", "3:6:tiny:115_-26", "Tiny", 6, {"flow": 2, "order": 6}, "NZL", 175.0, -38.0, 176.0, -37.5, LINE),
        ("rivers", "4:3:wiggly", "Wiggly", 3, {"flow": 2000, "order": 3}, "NZL", 170.0, -40.0, 171.0, -39.99,
         {"type": "LineString", "coordinates": [[170 + i / 100, -40 + (i % 2) / 1000] for i in range(101)]}),
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
    assert {f["properties"]["id"] for f in far["features"]} == {"1:3", "4:3:wiggly"}
    # Zoomed out, lines come simplified to about a pixel; closer in, as stored
    wiggly = {f["properties"]["id"]: f for f in far["features"]}["4:3:wiggly"]
    assert 2 <= len(wiggly["geometry"]["coordinates"]) < 10 and wiggly["properties"]["name"] == "Wiggly"
    near = client.get("/api/v1/geo/rivers", params={"west": 170, "south": -45, "east": 180, "north": -30, "zoom": 7}).json()
    assert {f["properties"]["id"] for f in near["features"]} == {"1:3", "2:5", "3:6:tiny:115_-26", "4:3:wiggly"}
    assert len({f["properties"]["id"]: f for f in near["features"]}["4:3:wiggly"]["geometry"]["coordinates"]) == 101
    mid = client.get("/api/v1/geo/rivers", params={"west": 170, "south": -45, "east": 180, "north": -30, "zoom": 5.2}).json()
    assert "3:6:tiny:115_-26" not in {f["properties"]["id"] for f in mid["features"]}  # 1 to 10 m3/s from zoom 5.5
    # A Pacific-centred window across the date line still finds them
    wrap = client.get("/api/v1/geo/rivers", params={"west": 170, "south": -45, "east": 200, "north": -30, "zoom": 7}).json()
    assert len(wrap["features"]) == 4
    none = client.get("/api/v1/geo/rivers", params={"west": 0, "south": 0, "east": 10, "north": 10, "zoom": 7}).json()
    assert none["features"] == [] and "loaded" not in none  # loaded, just none here
    gas = client.get("/api/v1/geo/gas_pipelines").json()  # never loaded: says how to get it
    assert gas["features"] == [] and gas["loaded"] is False and "gem_infrastructure" in gas["note"]
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
    assert t["loaded"]["rivers"] == 4
    c = client.get("/api/v1/transport/country/NZL").json()
    assert c["networks"]["cables"][0]["name"] == "Southern Cross NEXT" and c["ports"][0]["port_id"] == "port1"
    assert client.get("/api/v1/transport/country/AUS").json()["networks"]["basins"][0]["id"] == "600"
    ck = client.get("/api/v1/transport/chokepoint/chokepoint1", params={"start": 2023}).json()
    assert ck["name"] == "Suez Canal" and ck["points"] and {c["id"] for c in ck["depends"]} == {"EGY"}
    assert len(client.get("/api/v1/transport/port/port1").json()["months"]) == 12


def test_heads_and_country_ports(client):
    h = {x["id"]: x for x in client.get("/api/v1/transport/heads", params={"home": "NZL"}).json()}
    assert h["chokepoints"]["value"] == "30 a day" and "▼" in h["chokepoints"]["note"]
    assert h["ports"]["value"] == "100 a month" and h["ports"]["note"].endswith("12 months to 2024-12")
    assert h["cuts"]["id"] == "cuts"
    p = client.get("/api/v1/transport/ports/NZL").json()
    assert p["ports"][0]["calls_12m"] == 1200 and len(p["ports"][0]["months"]) == 36 and p["ports"][0]["months"][-1] == ["2024-12", 100]
    assert p["finding"].startswith("port1 the busiest, 1,200 ship calls")
    t = client.get("/api/v1/transport").json()
    assert t["choke_finding"].startswith("Suez Canal traffic") and "below a year before" in t["choke_finding"]


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


def test_live_planes_keep_last_after_limit(monkeypatch):
    class Resp:
        status_code = 429
        headers = {"X-Rate-Limit-Retry-After-Seconds": "7200"}

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            calls.append(1)
            return Resp()

    calls = []
    monkeypatch.setattr(live.httpx, "Client", Client)
    planes = live.Planes()
    planes.last = {"type": "FeatureCollection", "at": 0, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [174.8, -37.0]}, "properties": {"id": "abc"}}]}
    got = planes.get(170, -45, 180, -30)
    assert len(got["features"]) == 1 and "about 2 hours" in got["error"] and "min ago" in got["error"]
    planes.last_at = 0  # long past the refresh gap, but OpenSky said wait: no new request
    planes.get(170, -45, 180, -30)
    assert len(calls) == 1


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


def test_live_ships_keep_the_reason_they_stopped(monkeypatch):
    monkeypatch.setenv("AISSTREAM_API_KEY", "bad")
    ships = live.Ships()
    started = []

    def run(key):
        started.append(key)
        ships.take({"error": "Api Key Is Not Valid"})  # what aisstream sends before closing
        ships.failed_at = live.time.time()  # as the real _run records when the socket closes

    monkeypatch.setattr(ships, "_run", run)
    ships.get(170, -45, 180, -30)
    ships.thread.join(2)
    again = ships.get(170, -45, 180, -30)  # within the retry gap: not started again, the reason still shown
    assert len(started) == 1 and "Api Key Is Not Valid" in again["error"] and "Settings > Keys" in again["error"]
    assert "Connecting" in again["note"]


def test_ship_error_words():
    class ConnectionClosedError(Exception):
        pass

    assert "wrong or expired key" in live._ship_error(ConnectionClosedError("received 1008"))
    assert "Could not reach" in live._ship_error(OSError("blocked"))


def test_port_pressure(client, tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    start = date(2023, 1, 2)
    weeks = []
    for i in range(80):
        w = start + timedelta(days=7 * i)
        v = 50.0 if i < 76 else 25.0  # the last four weeks at half
        weeks += [("port", "port1", "NZL", w, v, v * 1000, 50.0, v / 50), ("port", "port2", "NZL", w, 30.0, None, 30.0, 1.0)]
    con.executemany("INSERT INTO traffic_weekly VALUES (?, ?, ?, ?, ?, ?, ?, ?)", weeks)
    curve = json.dumps([1, 1, 1, 1, 0.5, 0.6, 0.9, 1.0] + [1.0] * 13)
    con.executemany(f"INSERT INTO traffic_impacts VALUES (?, ?, 'portwatch', ?, 'cyclone', 'NZL', ?, ?, 'port', ?, ?, 50, ?, ?, ?, ?, ?, 5, true, '{curve}')",
                    [("e1|port:port1", "portwatch:e1", "Cyclone A", date(2023, 6, 5), date(2023, 6, 8), "port1", "Auckland", -50.0, date(2023, 6, 5), 45.0, 45000, 14),
                     ("e2|port:port2", "portwatch:e2", "Cyclone B", date(2023, 9, 4), date(2023, 9, 4), "port2", "Tauranga", -30.0, date(2023, 9, 4), 12.0, None, None)])
    con.execute("INSERT INTO port_links VALUES ('port1', 'port2', 1.5, 12000, 0.12, 'portwatch', 'v1')")
    con.execute("INSERT INTO port_daily VALUES ('port1', 'NZL', DATE '2024-07-01', 10, 6, 2, 0, 2, 0, 1000, 2000, 'portwatch', 'v1')")
    con.close()
    pl = {p["id"]: p for p in client.get("/api/v1/transport/pressure/places").json()}
    assert pl["port1"]["vs_normal"] == -50.0 and pl["port2"]["vs_normal"] == 0.0 and pl["port1"]["weekly"] > 40
    one = client.get("/api/v1/transport/pressure/port/port1", params={"event": "e1|port:port1"}).json()
    assert len(one["weeks"]) == 80 and one["impacts"][0]["recover_days"] == 14 and one["impacts"][0]["curve"][4] == 0.5
    assert one["links"][0] == {**one["links"][0], "direction": "out", "port_id": "port2", "days": 1.5, "share": 12.0}
    assert one["mix"][0]["type"] == "container" and one["mix"][0]["share"] == 60.0
    assert one["knock_on"][0]["port_id"] == "port2" and one["knock_on"][0]["vs_normal"] == 0.0
    hits = client.get("/api/v1/transport/impacts").json()
    assert [h["impact_id"] for h in hits] == ["e1|port:port1", "e2|port:port2"]
    assert client.get("/api/v1/transport/impacts", params={"entity": "AUS"}).json() == []
    pat = client.get("/api/v1/transport/patterns").json()
    cy = pat["curves"][0]
    assert cy["hazard"] == "cyclone" and cy["n"] == 2 and cy["mean"][4] == 0.5 and cy["recover_median"] == 14
    assert {r["id"] for r in pat["resilience"]} == {"port1", "port2"}
    lay = client.get("/api/v1/layers/port_pressure").json()
    assert lay["type"] == "FeatureCollection"  # no ports layer in the sample: no coordinates, so no dots
    c = client.get("/api/v1/transport/pressure-country/NZL").json()
    assert [p["id"] for p in c["ports"]] == ["port1", "port2"] and len(c["ports"][0]["weeks"]) == 26


def test_port_goods(client, tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    rows = []
    for m in range(1, 13):
        p = date(2024, m, 1)
        rows += [("NZ:tauranga", "Port of Tauranga", "port2", "sea", "NZL", p, "M", "out", "04", "Dairy, eggs and honey", "",
                  800.0, 4e6, "NZD"),
                 ("NZ:tauranga", "Port of Tauranga", "port2", "sea", "NZL", p, "M", "out", "44", "Wood and logs", "",
                  5000.0, 2e6, "NZD"),
                 ("NZ:tauranga", "Port of Tauranga", "port2", "sea", "NZL", p, "M", "in", "27", "Oil, gas and coal", "",
                  2000.0, 1e6, "NZD"),
                 ("NZ:tauranga", "Port of Tauranga", "port2", "sea", "NZL", p, "M", "out", "TOTAL", "All goods", "CHN",
                  5800.0, 6e6, "NZD"),
                 ("NZ:akl-air", "Auckland Airport", None, "air", "NZL", p, "M", "in", "87", "Vehicles", "", 3.0, 5e5, "NZD")]
    rows.append(("AU:port-hedland", "Port Hedland", None, "sea", "AUS", date(2024, 6, 30), "FY", "out", "TOTAL", "All goods", "",
                 5.6e8, 8.4e10, "AUD"))
    con.executemany("INSERT INTO port_goods VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'x', 'v1')", rows)
    con.close()
    cs = {c["entity_id"]: c for c in client.get("/api/v1/transport/goods/countries").json()}
    assert cs["NZL"]["ports"] == 2 and cs["AUS"]["ports"] == 1
    ps = client.get("/api/v1/transport/goods/ports/NZL").json()
    assert [p["key"] for p in ps] == ["NZ:tauranga", "NZ:akl-air"]
    assert ps[0]["out_t"] == 5800 * 12 and ps[0]["in_v"] == 12e6 and ps[0]["from"] == "2024-01-01"
    assert client.get("/api/v1/transport/goods/for/port2").json() == ["NZ:tauranga"]
    one = client.get("/api/v1/transport/goods/port/NZ:tauranga").json()
    assert one["measure"] == "value" and one["goods"][0]["id"] == "04" and one["partners"][0]["id"] == "CHN"
    assert one["years"] == [{"year": 2024, "full": True, "in_t": 24000, "out_t": 69600, "in_v": 12e6, "out_v": 72e6}]
    assert {k["id"] for k in one["mix"]["keys"]} == {"04", "44", "27"}
    au = client.get("/api/v1/transport/goods/port/AU:port-hedland").json()
    assert au["years"][0]["out_t"] == 5.6e8 and au["goods"] == [] and au["freq"] == "FY"
    assert client.get("/api/v1/transport/goods/port/nope").status_code == 404
