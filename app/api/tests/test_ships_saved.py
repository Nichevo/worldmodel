"""The ship collector's saved positions, details, tables and journeys (live.py, shipstore.py, journeys.py)."""

import time

from worldmodel_api import journeys, live
from worldmodel_api.shipflags import flag
from worldmodel_api.shipstore import ShipStore


def _ships(tmp_path, **settings):
    s = {"live_ships": True, "ships_collect": True, "ships_area": "pacific", "ships_world_every_hours": 6, **settings}
    return live.Ships(store=ShipStore(tmp_path / "ships"), settings=lambda: s)


def _pos(mmsi, lat, lon, sog=12.0, kind="PositionReport"):
    return {"MessageType": kind, "MetaData": {"MMSI": mmsi, "ShipName": "AOTEAROA", "latitude": lat, "longitude": lon},
            "Message": {kind: {"Sog": sog, "TrueHeading": 90, "NavigationalStatus": 0}}}


def test_store_thins_saves_and_reads_back(tmp_path):
    st = ShipStore(tmp_path / "ships")
    t0 = time.time() - 3 * 86400
    assert st.add(1, -36.8, 174.8, 12, 90, "A", now=t0)
    assert not st.add(1, -36.7, 174.9, 12, 90, "A", now=t0 + 60)  # within 10 minutes: not saved
    assert st.add(1, -36.6, 175.0, 12, 90, "A", now=t0 + 700, kind=70)
    assert not st.add(2, -41.3, 174.8, 0, 0, "B", now=t0 + 10) is False  # first one always saved
    assert not st.add(2, -41.3, 174.8, 0, 0, "B", now=t0 + 1000)  # still: once an hour
    got = {s["id"]: s for s in st.at(t0 + 800, [(170, -45, 180, -30)])}
    assert got[1]["lon"] == 175.0 and got[1]["kind"] == 70 and got[1]["name"] == "A" and 2 in got
    assert [p[1] for p in st.track(1, t0 - 10, t0 + 1000)] == [174.8, 175.0]
    st.tidy(30, now=t0 + 86400 * 2)  # the day is over: becomes Parquet, still readable
    assert list((tmp_path / "ships").glob("*.parquet")) and not list((tmp_path / "ships").glob("*.csv"))
    assert len(st.track(1, t0 - 10, t0 + 1000)) == 2
    st.tidy(1, now=t0 + 86400 * 5)  # past the kept days: deleted
    assert not list((tmp_path / "ships").glob("*.parquet"))


def test_collector_saves_details_and_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("AISSTREAM_API_KEY", "k")
    ships = _ships(tmp_path)
    ships.take({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 512000001, "ShipName": "AOTEAROA"},
                "Message": {"ShipStaticData": {"Name": "AOTEAROA", "ImoNumber": 9300001, "CallSign": "ZMA1", "Type": 71,
                                               "Dimension": {"A": 150, "B": 30, "C": 12, "D": 13}, "Destination": "NZ TRG",
                                               "Eta": {"Month": 11, "Day": 27, "Hour": 6, "Minute": 0}, "MaximumStaticDraught": 9.5}}})
    ships.take(_pos(512000001, -36.8, 174.8))
    ships.take(_pos(636000002, -33.9, 151.2, kind="StandardClassBPositionReport"))
    t = ships.table()
    assert t["total"] == 2 and t["groups"] == {"cargo": 1, "unknown": 1}
    row = next(r for r in t["rows"] if r["id"] == 512000001)
    assert (row["flag"], row["type"], row["length_m"], row["width_m"], row["destination"], row["status"]) == \
        ("New Zealand", "Cargo", 180, 25, "NZ TRG", "Under way (engine)")
    assert ships.table(q="zma1")["total"] == 1 and ships.table(group="cargo")["total"] == 1 and ships.table(flag_code="LR")["total"] == 1
    feats = ships.get(170, -45, 180, -30)["features"]
    assert feats[0]["properties"]["group"] == "cargo" and feats[0]["properties"]["heading"] == 90
    ships.store.save_details(30)
    again = _ships(tmp_path)  # details survive a restart
    assert again.store.details[512000001]["callsign"] == "ZMA1"
    saved = again.get(170, -45, 180, -30, at=time.time())
    assert [f["properties"]["id"] for f in saved["features"]] == [512000001]


def test_not_collecting_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("AISSTREAM_API_KEY", "k")
    ships = _ships(tmp_path, ships_collect=False)
    ships.take(_pos(512000001, -36.8, 174.8))
    assert not (tmp_path / "ships").exists() and ships.world_every() == 0


def test_class_b_static_and_flags():
    got = live._static("StaticDataReport", {"ReportA": {"Valid": True, "Name": "SEA BREEZE "},
                                              "ReportB": {"Valid": True, "ShipType": 37, "CallSign": "ZM1", "Dimension": {"A": 8, "B": 4, "C": 2, "D": 2}}})
    assert got == {"name": "SEA BREEZE", "callsign": "ZM1", "kind": 37, "length_m": 12, "width_m": 4}
    assert live.ship_group(37) == "leisure" and live.ship_type_name(84) == "Tanker" and live.ship_group(None) == "unknown"
    assert flag(512123456) == ("NZ", "New Zealand") and flag(970123456) is None


def test_destination_matches_a_port():
    index = {"code": {"NZTRG": {"name": "Tauranga"}, "AUSYD": {"name": "Sydney"}}, "name": {"AUCKLAND": {"name": "Auckland"}}}
    assert journeys.match_port("NZ TRG", index)["name"] == "Tauranga"
    assert journeys.match_port("NZAKL>AU SYD", index)["name"] == "Sydney"
    assert journeys.match_port("AUCKLAND NZ", index)["name"] == "Auckland"
    assert journeys.match_port("FOR ORDERS", index) is None and journeys.match_port("", index) is None


def test_saved_at_uses_long_look_back_outside_the_pacific(tmp_path):
    st = ShipStore(tmp_path / "ships")
    t = time.time() - 4 * 3600
    st.add(1, -36.8, 174.8, 12, 90, "PACIFIC", now=t)  # in the collected area: too old after 4 hours
    st.add(2, 51.0, 1.5, 12, 90, "CHANNEL", now=t)       # from a world snapshot: still shown
    area = live.SHIP_AREAS["pacific"][1]
    got = {s["name"] for s in st.at(time.time(), [(-180, -90, 180, 90)], area, 6 * 3600 + 600)}
    assert got == {"CHANNEL"}


def test_world_snapshot_uses_the_one_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("AISSTREAM_API_KEY", "k")
    ships = _ships(tmp_path)
    assert ships.wanted_boxes() == live.SHIP_AREAS["pacific"][1]
    ships.world_until = time.time() + 600  # a snapshot is on: the same connection widens to the world
    assert ships.wanted_boxes() == live.SHIP_AREAS["world"][1]
    ships.world_until = time.time() - 1
    assert ships.wanted_boxes() == live.SHIP_AREAS["pacific"][1]
    assert not hasattr(ships, "_listen_world")
