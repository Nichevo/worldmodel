"""Planes saved from OpenSky answers, look-ups kept on disk, and the tables' from/to filters (planestore.py, live.py, journeys.py)."""

import time

from worldmodel_api import journeys, live
from worldmodel_api.planestore import PlaneStore


def _plane(icao, lon, lat, cs="ANZ123", group="airliner"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"id": icao, "callsign": cs, "country": "New Zealand", "altitude_m": 10000, "speed_kmh": 800,
                           "heading": 90, "group": group, "seen": int(time.time())}}


def test_store_saves_thins_and_reads_back(tmp_path):
    st = PlaneStore(tmp_path / "planes")
    t0 = time.time() - 3 * 86400
    assert st.add_many([_plane("c81d90", 174.8, -36.9), _plane("7c6b2d", 151.2, -33.9, "QFA1")], now=t0) == 2
    assert st.add_many([_plane("c81d90", 175.0, -37.0)], now=t0 + 60) == 0          # too soon
    assert st.add_many([_plane("c81d90", 175.5, -37.5)], now=t0 + 300) == 1
    got = {p["id"]: p for p in st.at(t0 + 400, [(170, -45, 180, -30)])}
    assert list(got) == ["c81d90"] and got["c81d90"]["lon"] == 175.5 and got["c81d90"]["callsign"] == "ANZ123"
    assert [p[1] for p in st.track("c81d90", t0 - 1, t0 + 1000)] == [174.8, 175.5]
    st.tidy(30, now=t0 + 2 * 86400)
    assert list((tmp_path / "planes").glob("*.parquet")) and len(st.track("c81d90", t0 - 1, t0 + 1000)) == 2
    assert st.status()["planes"] == 2


def test_lookups_kept_on_disk(tmp_path):
    st = PlaneStore(tmp_path / "planes")
    st.keep_many("route", {"ANZ1": {"codes": "NZAA-NZWN"}, "QFA1": None}, 86400)
    again = PlaneStore(tmp_path / "planes")
    assert again.lookup("route", "ANZ1", 3600)[0] == {"codes": "NZAA-NZWN"}
    assert again.lookup("route", "QFA1", 3600)[0] is None and again.lookup("route", "QFA1", 3600) is not None
    assert again.lookup("route", "ZZZ9", 3600) is None


def test_planes_saved_table_routes_and_journey(tmp_path, monkeypatch):
    planes = live.Planes(store=PlaneStore(tmp_path / "planes"), settings=lambda: {"planes_collect": True})
    old = _plane("c81d91", 172.0, -43.5, "ANZ500")
    planes.store.add_many([old], now=time.time() - 1800)           # landed half an hour ago: still in the table
    planes.last = {"type": "FeatureCollection", "features": [_plane("c81d90", 174.8, -36.9)], "at": int(time.time())}
    asked = []

    def fake_routes(batch):
        asked.append([b[0] for b in batch])
        return {"ANZ123": {"codes": "NZAA-NZWN", "plausible": True, "airports": [
            {"name": "Auckland", "iata": "AKL", "icao": "NZAA", "city": "Auckland", "country": "NZ"},
            {"name": "Wellington", "iata": "WLG", "icao": "NZWN", "city": "Wellington", "country": "NZ"}]}}

    monkeypatch.setattr(journeys, "routes", fake_routes)
    t = planes.table(hours=1)
    assert {r["id"] for r in t["planes"]} == {"c81d90", "c81d91"}
    planes.route_thread.join(5)
    assert sorted(asked[0]) == ["ANZ123", "ANZ500"]
    t = planes.table(hours=1)
    row = next(r for r in t["planes"] if r["id"] == "c81d90")
    assert row["from"]["iata"] == "AKL" and row["to"]["city"] == "Wellington" and row["airline"] == "Air New Zealand"
    # the saved positions draw the path when OpenSky has none, and the route comes from disk
    planes.store.add_many([_plane("c81d90", 174.9, -37.0)], now=time.time() - 600)
    planes.store.add_many([_plane("c81d90", 175.0, -37.2)], now=time.time() - 60)
    monkeypatch.setattr(journeys, "_track", lambda q, auth, icao: {"track": None, "route": None, "from_airport": None, "note": "OpenSky has no path"})
    monkeypatch.setattr(journeys, "_aircraft", lambda icao: None)
    monkeypatch.setattr(journeys, "_route", lambda *a: (_ for _ in ()).throw(AssertionError("asked again")))
    j = journeys.plane_journey(lambda s, p: [], lambda c: {}, "c81d90", "ANZ123", None, None, store=planes.store)
    assert j["route"]["codes"] == "NZAA-NZWN" and j["track"]["points"] == 2 and "saved here" in j["note"]
    saved = planes.saved_at(time.time(), 170, -45, 180, -30)
    assert {f["properties"]["id"] for f in saved["features"]} >= {"c81d90"}


def test_ships_table_going_to_filter(tmp_path, monkeypatch):
    from worldmodel_api.shipstore import ShipStore

    monkeypatch.setenv("AISSTREAM_API_KEY", "k")
    ships = live.Ships(store=ShipStore(tmp_path / "ships"), settings=lambda: {"live_ships": True, "ships_collect": True})
    for mmsi, dest in ((512000001, "NZ TRG"), (512000002, "AUSYD"), (512000003, "")):
        ships.store.note(mmsi, name=f"S{mmsi}", destination=dest, lat=-37.0, lon=175.0)
    idx = {"code": {"NZTRG": {"name": "Tauranga", "country": "New Zealand", "locode": "NZ TRG", "lon": 176.2, "lat": -37.6},
                    "AUSYD": {"name": "Sydney", "country": "Australia", "locode": "AU SYD", "lon": 151.2, "lat": -33.9}}, "name": {}}
    t = ships.table(ports=idx, to="new zealand")
    assert [r["id"] for r in t["rows"]] == [512000001] and t["rows"][0]["to_port"]["name"] == "Tauranga"
    assert [r["id"] for r in ships.table(ports=idx, to="syd")["rows"]] == [512000002]
