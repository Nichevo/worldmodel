"""Cargo ships on schedule: ETA history, port lists, line schedules, lateness and learned routes."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from worldmodel_api import schedules
from worldmodel_api.schedules import Schedules

FIX = Path(__file__).parent / "fixtures" / "ports"
NOW = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc).timestamp()


def test_eta_text_gets_the_nearest_year():
    assert schedules.eta_ts("27/11 22:00 UTC", NOW) == datetime(2026, 11, 27, 22, tzinfo=timezone.utc).timestamp()
    assert schedules.eta_ts("03/01 06:00 UTC", NOW) == datetime(2027, 1, 3, 6, tzinfo=timezone.utc).timestamp()
    assert schedules.eta_ts("00/00 24:60 UTC", NOW) is None


def test_port_lists_parse():
    akl = schedules.parse_poal((FIX / "poal_arrivals.html").read_text())
    assert [r["name"] for r in akl] == ["MACHIAVELLI", "SPINNAKER SW", "JPO AQUARIUS", "CMA CGM DUTCH HARBOR"]
    jpo = akl[2]
    assert jpo["imo"] == 9220316 and jpo["voyage"] == "644S" and jpo["prev"] == "BRISBANE" and jpo["next"] == "NELSON"
    assert jpo["arrival"] == datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc).timestamp()
    assert akl[0]["imo"] is None and akl[1]["next"] is None
    trg = schedules.parse_tauranga((FIX / "tauranga.html").read_text())
    assert [(r["name"], r["state"]) for r in trg] == [("KIRIBATI CHIEF", "in_port"), ("CAPE SERRAT", "expected"),
                                                      ("ANL TASMAN TRADER", "expected"), ("CMA CGM SEATTLE", "departed")]
    assert trg[0]["cargo"] == "General Cargo" and trg[1]["cargo"] is None
    assert trg[2]["arrival"] == datetime(2026, 11, 27, 2, 30, tzinfo=timezone.utc).timestamp()  # 15:30 NZDT


def test_eta_history_voyages_and_slipping(tmp_path):
    s = Schedules(tmp_path)
    t = NOW - 5 * 86400
    s.note_eta(1, "SHANGHAI", "12/12 14:00 UTC", now=t)
    s.note_eta(1, "SHANGHAI", "12/12 14:00 UTC", now=t + 600)  # no change: not kept again
    s.note_eta(1, "SHANGHAI", "13/12 20:00 UTC", now=t + 3 * 86400)
    v = s.voyages(1)
    assert len(v) == 1 and len(v[0]["history"]) == 2 and v[0]["moved_h"] == 30
    st = s.status(1, {"imo": 9950143, "name": "CAPE SERRAT"}, {"lat": -30, "lon": 170, "speed_kn": 14}, None, now=NOW)
    assert st["measured_by"] == "ship" and st["late_h"] == 30 and st["state"] == "late"
    s.note_eta(1, "BUSAN", "20/12 00:00 UTC", now=NOW)
    assert len(s.voyages(1)) == 2


def test_port_booking_moves_and_actual_arrival(tmp_path):
    s = Schedules(tmp_path)
    arr = NOW + 3600
    row = {"name": "SPINNAKER SW", "imo": 9580003, "arrival": arr, "departs": arr + 86400, "state": "expected", "prev": "TOWNSVILLE"}
    s.record_bookings("auckland", [row], now=NOW - 86400)
    s.record_bookings("auckland", [{**row, "arrival": arr + 10 * 3600}], now=NOW - 3600)
    b = s.booking_for(9580003, "SPINNAKER SW", NOW)
    assert b and len(b["versions"]) == 2 and b["arrival"] == int(arr + 10 * 3600)
    st = s.status(7, {"imo": 9580003, "name": "SPINNAKER SW"}, {}, None, now=NOW)
    assert st["measured_by"] == "port" and st["late_h"] == 10 and st["state"] == "on_time"
    # it arrives 30 h after its first booking: seen stopping in Auckland
    s.note_stop(7, {"name": "Auckland", "country": "New Zealand", "locode": "NZAKL"}, now=arr + 30 * 3600)
    st = s.status(7, {"imo": 9580003, "name": "SPINNAKER SW"}, {}, None, now=arr + 31 * 3600)
    assert st["late_h"] == 30 and st["state"] == "late" and st["arrived_at"] == int(arr + 30 * 3600)
    s.save(now=NOW)
    again = Schedules(tmp_path)
    assert again.booking_for(9580003, None, NOW)["arrival"] == int(arr + 10 * 3600)


def test_line_schedule_wins(tmp_path):
    s = Schedules(tmp_path)
    body = [{"carrierServiceName": "Southern Star", "vesselSchedules": [{"vesselIMONumber": "9251638", "transportCalls": [
        {"location": {"UNLocationCode": "NZLYT", "locationName": "Lyttelton"}, "carrierExportVoyageNumber": "647S",
         "timestamps": [{"eventTypeCode": "ARRI", "eventClassifierCode": "PLN", "eventDateTime": "2026-11-27T22:00:00Z"},
                        {"eventTypeCode": "ARRI", "eventClassifierCode": "EST", "eventDateTime": "2026-11-29T00:00:00Z"}]}]}]}]
    got = schedules.parse_dcsa(body)
    assert got["service"] == "Southern Star" and got["calls"][0]["locode"] == "NZLYT"
    s.carrier["9251638"] = {**got, "at": NOW, "carrier": "maersk"}
    st = s.status(3, {"imo": 9251638, "name": "OLIVIA MAERSK"}, {}, None, now=NOW)
    assert st["measured_by"] == "line" and st["late_h"] == 26 and st["state"] == "late"
    assert schedules.line_of("OLIVIA MAERSK") is None and schedules.line_of("MAERSK OLIVIA")[1] == "maersk"
    assert schedules.line_of("ANL TASMAN TRADER") == ("CMA CGM (ANL)", "cmacgm")


def test_route_learned_after_two_loops(tmp_path):
    s = Schedules(tmp_path)
    t = NOW - 80 * 86400
    loop = ["Tauranga", "Auckland", "Brisbane", "Sydney", "Melbourne"]
    for i, p in enumerate(loop + loop + loop[:1]):
        s.note_stop(9, {"name": p, "locode": p[:5].upper()}, now=t + i * 7 * 86400)
        s.note_move(9, now=t + i * 7 * 86400 + 86400)
    r = s.route(9)
    assert r["loop"] == loop + ["Tauranga"] and r["times"] == 2 and r["round_days"] == 35
    s2 = Schedules(tmp_path / "b")
    for i, p in enumerate(["Napier", "Tauranga", "Shanghai"]):
        s2.note_stop(5, {"name": p}, now=t + i * 86400 * 4)
        s2.note_move(5, now=t + i * 86400 * 4 + 3600)
    assert s2.route(5)["loop"] is None and s2.route(5)["ports"] == ["Napier", "Tauranga", "Shanghai"]


def test_stop_and_move_make_one_call(tmp_path):
    s = Schedules(tmp_path)
    port = {"name": "Tauranga", "locode": "NZTRG"}
    s.note_stop(4, port, now=NOW)
    s.note_stop(4, port, now=NOW + 3600)
    s.note_move(4, now=NOW + 7200)
    s.note_stop(4, port, now=NOW + 3 * 3600)  # shifting berth: the same call
    assert len(s.calls[4]) == 1 and s.calls[4][0]["left"] is None
    s.note_move(4, now=NOW + 5 * 3600)
    s.note_stop(4, port, now=NOW + 20 * 86400)  # back a few weeks later: a new call
    assert len(s.calls[4]) == 2


def test_ships_table_gets_on_time(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from worldmodel_api import live, main
    from worldmodel_api.shipstore import ShipStore

    ships = live.Ships(store=ShipStore(tmp_path / "ships"), settings=lambda: {"ship_schedules": True})
    ships.store.note(111, name="CAPE SERRAT", imo=9950143, kind=70, destination="SHANGHAI", now=time.time())
    ships.store.note(222, name="KORIMAKO", kind=52, now=time.time())
    ships.schedules.note_eta(111, "SHANGHAI", "12/12 14:00 UTC", now=time.time() - 86400)
    ships.schedules.note_eta(111, "SHANGHAI", "14/12 14:00 UTC", now=time.time())
    monkeypatch.setattr(live, "SHIPS", ships)
    c = TestClient(main.app)
    got = c.get("/api/v1/live/ships/table").json()["rows"]
    by = {r["id"]: r for r in got}
    assert by[111]["on_time"] == "late" and by[111]["late_h"] == 48 and "on_time" not in by[222]
    assert [r["id"] for r in c.get("/api/v1/live/ships/table?ontime=late").json()["rows"]] == [111]
    sch = c.get("/api/v1/live/ships/schedule/111").json()
    assert sch["voyages"][-1]["moved_h"] == 48 and sch["route"]["loop"] is None
    assert c.get("/api/v1/live/ships/schedule/222").status_code == 404
    ships.schedules.record_bookings("tauranga", [{"name": "CAPE SERRAT", "imo": 9950143, "arrival": time.time() + 3600,
                                                  "departs": None, "state": "expected"}])
    board = c.get("/api/v1/live/schedules").json()
    assert board["rows"][0]["name"] == "CAPE SERRAT" and board["rows"][0]["id"] == 111 and board["rows"][0]["port"] == "Tauranga"
    assert c.get("/api/v1/live/schedules/reliability").json()["lines"] == []


def test_australian_port_lists_parse():
    syd = schedules.parse_nsw((FIX / "nsw_botany.html").read_text(), NOW)
    assert [r["name"] for r in syd] == ["Morning Ibis", "OOCL Chicago"]  # in port with no arrival row, and shifts: left out
    chi = syd[1]
    assert chi["arrival"] == datetime(2026, 11, 27, 13, 1, tzinfo=timezone.utc).timestamp()  # 00:01 AEDT on the 28th
    assert chi["prev"] == "Fremantle" and chi["next"] == "Auckland" and chi["state"] == "expected" and chi["imo"] is None
    vic = {r["name"]: r for r in schedules.parse_vic((FIX / "vic.html").read_text())}
    assert set(vic) == {"MSC New Haven VIII", "Maea", "Adria Ace", "Green Wave", "Star Japan"}  # pilot codes dropped
    assert vic["Green Wave"]["state"] == "in_port" and vic["Green Wave"]["next"] == "Auckland"
    assert vic["Adria Ace"]["state"] == "departed" and vic["MSC New Haven VIII"]["prev"] == "Sydney"
    assert vic["Star Japan"]["departs"] == datetime(2026, 12, 4, 8, 0, tzinfo=timezone.utc).timestamp()
    assert set(schedules.PARSERS) == {k for k, p in schedules.PORT_LISTS.items() if p["url"]}


def test_singapore_api_rows_merge():
    due = {"data": [{"vesselParticulars": {"vesselName": "MAERSK KOWLOON", "imoNumber": "9784270", "callSign": "9V1", "flag": "SG"},
                     "duetoArriveTime": "2026-11-27 14:30:00", "locationFrom": "PORT KLANG", "locationTo": "PASIR PANJANG"},
                    {"vesselParticulars": [{"vesselName": "EVER GIVEN", "imoNumber": "9811000"}],
                     "dueToArriveTime": "2026-11-28T06:00:00+08:00", "locationFrom": "COLOMBO"}]}
    arrived = [{"vesselParticulars": {"vesselName": "MAERSK KOWLOON", "imoNumber": "9784270"}, "arrivedTime": "2026-11-27 15:10:00",
                "locationFrom": "PORT KLANG", "locationTo": "PEBGA"}]
    leaving = [{"vesselParticulars": {"vesselName": "MAERSK KOWLOON", "imoNumber": "9784270"}, "duetoDepartTime": "2026-11-28 09:00:00",
                "nextPort": "JAKARTA"},
               {"vesselParticulars": {"vesselName": "NO ARRIVAL KNOWN", "imoNumber": "9000001"}, "duetoDepartTime": "2026-11-28 09:00:00"}]
    rows = schedules.merge_sg([schedules.parse_sg(due, "expected"), schedules.parse_sg(arrived, "in_port"),
                               schedules.parse_sg(leaving, "leaving")])
    by = {r["name"]: r for r in rows}
    assert set(by) == {"MAERSK KOWLOON", "EVER GIVEN"}
    k = by["MAERSK KOWLOON"]
    assert k["imo"] == 9784270 and k["state"] == "in_port" and k["prev"] == "PORT KLANG" and k["next"] == "JAKARTA"
    assert k["arrival"] == datetime(2026, 11, 27, 7, 10, tzinfo=timezone.utc).timestamp()  # 15:10 Singapore time
    assert k["departs"] == datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc).timestamp()
    assert by["EVER GIVEN"]["arrival"] == datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc).timestamp()


def test_singapore_needs_its_key(tmp_path, monkeypatch):
    monkeypatch.delenv("SG_OCEANSX_API_KEY", raising=False)
    monkeypatch.setattr(schedules, "PORT_LISTS", {"singapore": schedules.PORT_LISTS["singapore"]})
    s = Schedules(tmp_path)
    s.fetch_ports(None)  # no key: nothing asked
    assert "needs a free key" in s.notes["singapore"]
