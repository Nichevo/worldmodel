"""Plane types, registrations and flags from the aircraft database; airline logos kept on disk;
the ship sweep log; aisstream retry back-off (aircraftdb.py, aircraft_types.py, live.py)."""

import gzip
import time

import httpx

from worldmodel_api import aircraftdb, live
from worldmodel_api.planestore import PlaneStore
from worldmodel_api.shipstore import ShipStore

ROWS = "\n".join([
    "C80005;ZK-TIE;C152;00;;;Tie-Upp Aviation;",
    "C8000D;ZK-IGA;EC45;00;AIRBUS HELICOPTERS EC-145;;;",
    "7C6B2D;VH-VGF;A320;00;;;;",
    "AE1234;03-3123;C17;10;;;;",
    "000001;;;10;;;Miscode - VARIOUS;",
])


def _db(tmp_path):
    folder = tmp_path / "planes"
    folder.mkdir()
    (folder / "aircraft.csv.gz").write_bytes(gzip.compress(ROWS.encode()))
    return folder


def test_types_registration_flag_and_group(tmp_path):
    db = aircraftdb.AircraftDb(_db(tmp_path))
    assert db.load()
    c152 = db.find("c80005")
    assert c152["model"].startswith("Cessna") and {k: v for k, v in c152.items() if k != "model"} == {"flag": "NZ", "military": False, "reg": "ZK-TIE", "type": "C152", "group": "light"}
    assert db.find("C8000D")["group"] == "helicopter"
    a = db.find("7c6b2d")
    assert a["flag"] == "AU" and a["group"] == "airliner" and a["model"].startswith("Airbus")
    assert db.find("ae1234")["military"] is True and db.find("ae1234")["flag"] == "US"
    assert db.find("c87f01") == {"flag": "NZ", "military": True}   # not in the file: still the country and its military block
    assert db.find("not-hex") == {}


def test_planes_get_type_when_no_category_is_sent(tmp_path):
    planes = live.Planes(store=PlaneStore(_db(tmp_path)), settings=lambda: {"planes_collect": False})
    planes.aircraft.load()
    heli = planes.describe({"id": "c8000d", "callsign": "ZKIGA", "group": "unknown"})
    assert heli["group"] == "helicopter" and heli["reg"] == "ZK-IGA" and heli["flag"] == "NZ"
    unknown_airliner = planes.describe({"id": "c8ffff", "callsign": "ANZ123", "group": "unknown"})
    assert unknown_airliner["group"] == "airliner" and unknown_airliner["airline_code"] == "ANZ"   # by its airline callsign
    sent = planes.describe({"id": "c80005", "callsign": "ZKTIE", "group": "glider"})
    assert sent["group"] == "glider"   # what the plane sends wins
    off = live.Planes(store=PlaneStore(tmp_path / "planes"), settings=lambda: {"planes_types": False})
    assert off.describe({"id": "c8000d", "callsign": None, "group": "unknown"})["group"] == "unknown"


def test_logo_fetched_once_and_missing_remembered(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 20
    asked = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(200, content=png) if "ANZ" in str(request.url) else httpx.Response(404)

    real = httpx.Client
    monkeypatch.setattr(aircraftdb.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    folder = tmp_path / "logos"
    assert aircraftdb.logo(folder, "anz") == png and aircraftdb.logo(folder, "ANZ") == png
    assert len(asked) == 1
    assert aircraftdb.logo(folder, "ZZZ") is None and aircraftdb.logo(folder, "ZZZ") is None
    assert len(asked) == 3   # two sources tried once, then the miss is remembered
    assert aircraftdb.logo(folder, "../x") is None


def test_sweep_log_and_retry_back_off(tmp_path):
    s = {"live_ships": True, "ships_collect": True, "ships_area": "pacific", "ships_world_every_hours": 2}
    ships = live.Ships(store=ShipStore(tmp_path / "ships"), settings=lambda: s)
    now = time.time()
    ships.log_sweep("sweep", now - 600, "finished", 41000, 3200, "")
    ships.log_sweep("connection", now - 900, "dropped", 500, None, "aisstream.io closed the connection")
    ships.log_sweep("sweep", now - 200, "cut short", 9000, 700, "aisstream.io closed the connection")
    got = ships.sweeps(7)
    assert got["totals"] == {"sweeps": 2, "finished": 1, "cut_short": 1, "reports": 50000, "new_ships": 3900, "drops": 1}
    assert got["rows"][0]["outcome"] == "cut short" and got["rows"][1]["new_ships"] is None
    assert [ships.retry_wait() for ships.fails in (0, 1, 2, 3, 10)] == [30, 30, 60, 120, 600]
    assert "10 minutes" in live._ship_error(OSError("blocked"), 600)


def test_flights_split_at_landings_and_callsign_changes(tmp_path):
    from tests.test_planes_saved import _plane

    st = PlaneStore(tmp_path / "planes")
    t0 = time.time() - 86400

    def at(minutes, cs, alt):
        f = _plane("c81d90", 174.8 + minutes / 100, -36.9, cs)
        f["properties"]["altitude_m"] = alt
        st.add_many([f], now=t0 + minutes * 60)

    for m, alt in ((0, 1000), (5, 9000), (60, 9000), (170, 900)):   # AKL to SYD
        at(m, "ANZ101", alt)
    for m, alt in ((230, 800), (300, 10000), (400, 600)):            # an hour on the ground, back as ANZ102
        at(m, "ANZ102", alt)
    for m, alt in ((1000, 700), (1100, 10000)):                     # the next day, same callsign again
        at(m, "ANZ102", alt)
    planes = live.Planes(store=st, settings=lambda: {"planes_collect": True})
    got = planes.flights("C81D90", None, days=3)["flights"]
    assert [(f["callsign"], f["points"]) for f in got] == [("ANZ102", 2), ("ANZ102", 3), ("ANZ101", 4)]
    assert got[2]["minutes"] == 170 and got[2]["top_m"] == 9000 and got[0]["airline"] == "Air New Zealand"
    by_cs = planes.flights(None, "anz102", days=3)["flights"]
    assert len(by_cs) == 2 and all(f["icao"] == "c81d90" for f in by_cs)


def test_live_counts():
    from worldmodel_api import livestats

    ships = [{"group": "cargo", "type": "Cargo", "flag_code": "NZ", "flag": "New Zealand", "last_port": {"name": "Auckland", "country": "NZ"},
              "to_port": {"name": "Sydney", "country": "AU"}, "length_m": 180, "speed_kn": 12, "last_seen": time.time(), "first_seen": time.time()},
             {"group": "fishing", "type": "Fishing", "flag_code": None, "destination": "nelson", "length_m": None, "speed_kn": 0}]
    s = livestats.ships(ships, {"cargo": "Cargo"})
    parts = {p["id"]: p for p in s["parts"]}
    assert s["total"] == 2 and s["moving"] == 1 and s["first_seen_last_day"] == 1
    assert parts["group"]["rows"][0]["label"] in ("Cargo", "fishing") and parts["flag"]["distinct"] == 2
    assert parts["came_from"]["rows"] == [{"key": "Auckland, NZ", "label": "Auckland, NZ", "count": 1, "share": 1.0}]
    assert {r["key"] for r in parts["going_to"]["rows"]} == {"Sydney, AU", "NELSON"}
    assert {r["key"] for r in parts["length"]["rows"]} == {"100 to 200 m", "Not said"}
    planes = [{"group": "airliner", "airline": "Air New Zealand", "flag": "NZ", "country": "New Zealand", "model": "Airbus A-320",
               "from": {"city": "Auckland", "country": "NZ"}, "to": {"city": "Sydney", "country": "AU"}, "altitude_m": 10500},
              {"group": "light", "flag": None, "altitude_m": None, "military": True}]
    p = livestats.planes(planes, {})
    parts = {x["id"]: x for x in p["parts"]}
    assert p["total"] == 2 and p["military"] == 1 and p["airline"] == 1
    assert parts["route"]["rows"][0]["key"] == "Auckland, NZ to Sydney, AU"
    assert parts["height"]["rows"][0]["count"] == 1 and parts["flag"]["rows"][0]["label"] in ("New Zealand", "Not known")
