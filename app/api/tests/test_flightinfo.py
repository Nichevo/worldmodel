"""A plane card's schedule (AeroDataBox) and seat prices (Travelpayouts), with made-up answers."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx

from worldmodel_api import flightinfo


class Store:
    """The lookup/keep part of the planes store, in memory."""

    def __init__(self):
        self.d: dict = {}

    def lookup(self, kind, key, max_age):
        hit = self.d.get(kind, {}).get(key)
        return (hit[1], hit[0]) if hit and time.time() - hit[0] < max_age else None

    def keep(self, kind, key, value, drop_after):
        self.d.setdefault(kind, {})[key] = (time.time(), value)


def _utc(dt):
    return dt.strftime("%Y-%m-%d %H:%MZ")


def _flight(dep, arr, number="NZ 103", hex_code="c8222e", status="EnRoute"):
    return {"number": number, "callSign": "ANZ103", "status": status, "isCargo": False,
            "airline": {"name": "Air New Zealand", "iata": "NZ", "icao": "ANZ"},
            "aircraft": {"reg": "ZK-NZE", "modeS": hex_code.upper(), "model": "Boeing 787-9"},
            "departure": {"airport": {"iata": "AKL", "icao": "NZAA", "name": "Auckland", "municipalityName": "Auckland"},
                          "scheduledTime": {"utc": _utc(dep), "local": "2026-11-28 09:00+13:00"},
                          "revisedTime": {"utc": _utc(dep + timedelta(minutes=25))},
                          "runwayTime": {"utc": _utc(dep + timedelta(minutes=35))}, "terminal": "I", "gate": "7"},
            "arrival": {"airport": {"iata": "SYD", "icao": "YSSY", "name": "Sydney"},
                        "scheduledTime": {"utc": _utc(arr), "local": "2026-11-28 10:40+11:00"},
                        "predictedTime": {"utc": _utc(arr + timedelta(minutes=20))}, "baggageBelt": "3"}}


def test_schedule_needs_key(monkeypatch):
    monkeypatch.delenv("AERODATABOX_API_KEY", raising=False)
    out = flightinfo.schedule(Store(), "c8222e", "ANZ103", {})
    assert out["needs_key"] == "AERODATABOX_API_KEY" and out["flight"] is None


def test_schedule_picks_flight_in_air_and_keeps_it(monkeypatch):
    monkeypatch.setenv("AERODATABOX_API_KEY", "k")
    now = datetime.now(timezone.utc)
    flown = _flight(now - timedelta(hours=1), now + timedelta(hours=2))
    yesterday = _flight(now - timedelta(days=1, hours=1), now - timedelta(days=1) + timedelta(hours=2), status="Arrived")
    asked = []

    def answer(req: httpx.Request):
        asked.append(req)
        assert req.headers["X-RapidAPI-Key"] == "k"
        assert req.url.path == "/flights/callsign/ANZ103"
        return httpx.Response(200, json=[yesterday, flown])

    store = Store()
    with httpx.Client(transport=httpx.MockTransport(answer)) as c:
        out = flightinfo.schedule(store, "c8222e", "anz103", {}, client=c)
        again = flightinfo.schedule(store, "c8222e", "ANZ103", {}, client=c)
    f = out["flight"]
    assert out["found"] == 2 and f["status"] == "EnRoute"
    assert f["departure"]["airport"]["iata"] == "AKL" and f["departure"]["gate"] == "7"
    assert f["departure"]["late_min"] == 35  # took off 35 minutes after the scheduled time
    assert f["arrival"]["late_min"] == 20 and f["arrival"]["baggage"] == "3"
    assert len(asked) == 1 and again["kept_at"] and flightinfo.used_this_month(store) == 1


def test_schedule_monthly_cap_and_no_flight(monkeypatch):
    monkeypatch.setenv("AERODATABOX_API_KEY", "k")
    store = Store()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(204))) as c:
        out = flightinfo.schedule(store, "abcdef", None, {"flight_lookups_month": 5}, client=c)
        assert out["flight"] is None and "no published flight" in out["note"]
        store.keep("adb_month", flightinfo._month(), 5, 1e9)
        capped = flightinfo.schedule(store, "123456", "QFA1", {"flight_lookups_month": 5}, client=c)
    assert "used up" in capped["note"]
    assert "off" in flightinfo.schedule(store, "123456", "QFA1", {"flight_lookups_month": 0})["note"]


def test_schedule_refused_key(monkeypatch):
    monkeypatch.setenv("AERODATABOX_API_KEY", "bad")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as c:
        out = flightinfo.schedule(Store(), "abcdef", "ANZ1", {}, client=c)
    assert "refused" in out["error"]


def test_fares_links_without_token(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    out = flightinfo.fares(Store(), "akl", "syd", "2026-12-05", "NZ", "103", {})
    assert out["needs_key"] == "TRAVELPAYOUTS_TOKEN"
    hrefs = {l["label"]: l["href"] for l in out["links"]}
    assert hrefs["Skyscanner"].endswith("/akl/syd/261205/") and "AKL05" in hrefs["Aviasales"]
    assert "google.com/travel/flights" in hrefs["Google Flights"]


def test_fares_cheapest_and_this_flight(monkeypatch):
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "t")
    data = [
        {"origin": "AKL", "destination": "SYD", "price": 420, "airline": "NZ", "flight_number": "103", "departure_at": "2026-12-05T09:00:00+13:00", "transfers": 0, "link": "/search/AKL0512SYD1?t=x"},
        {"origin": "AKL", "destination": "SYD", "price": 300, "airline": "JQ", "flight_number": "202", "departure_at": "2026-12-05T13:00:00+13:00", "transfers": 0},
        {"origin": "AKL", "destination": "SYD", "price": 250, "airline": "QF", "flight_number": "144", "departure_at": "2026-12-19T07:00:00+13:00", "transfers": 0},
    ]
    asked = []

    def answer(req: httpx.Request):
        asked.append(req)
        assert req.headers["X-Access-Token"] == "t" and req.url.params["departure_at"] == "2026-12"
        return httpx.Response(200, json={"success": True, "data": data, "currency": "nzd"})

    store = Store()
    with httpx.Client(transport=httpx.MockTransport(answer)) as c:
        out = flightinfo.fares(store, "AKL", "SYD", "2026-12-05", "NZ", "103", {}, client=c)
        flightinfo.fares(store, "AKL", "SYD", "2026-12-05", "NZ", "103", {}, client=c)
    assert len(asked) == 1  # kept for the route and month
    assert out["cheapest_month"]["price"] == 250 and out["cheapest_day"]["price"] == 300
    assert out["this_flight"]["price"] == 420 and out["this_flight"]["link"].startswith("https://www.aviasales.com/search/")
    assert flightinfo.fares(store, "AKL", "SYD", "2026-12-05", settings={"flight_fares": False})["cheapest_month"] is None


def test_answers_saved_to_history(monkeypatch, tmp_path):
    monkeypatch.setenv("AERODATABOX_API_KEY", "k")
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "t")
    store = Store()
    store.folder = tmp_path
    now = datetime.now(timezone.utc)
    sched = httpx.MockTransport(lambda r: httpx.Response(200, json=[_flight(now - timedelta(hours=1), now + timedelta(hours=2))]))
    fares_ = httpx.MockTransport(lambda r: httpx.Response(200, json={"success": True, "data": [
        {"price": 300, "airline": "NZ", "flight_number": "103", "departure_at": "2026-12-05T09:00:00+13:00"}]}))
    with httpx.Client(transport=sched) as c:
        flightinfo.schedule(store, "c8222e", "ANZ103", {}, client=c)
        flightinfo.schedule(store, "c8222e", "ANZ103", {}, client=c)  # kept: not saved twice
    with httpx.Client(transport=fares_) as c:
        flightinfo.fares(store, "AKL", "SYD", "2026-12-05", settings={}, client=c)
    files = sorted(p.name for p in (tmp_path / "flight_history").iterdir())
    assert files[0].startswith("fares-") and files[1].startswith("schedules-")
    h = flightinfo.history(store, "NZ103", "AKL", "SYD")
    assert len(h["flights"]) == 1 and h["flights"][0]["late_leave_min"] == 35 and h["flights"][0]["from"] == "AKL"
    assert h["fares"][0]["cheapest"] == 300
    assert flightinfo.history(store, "anz103")["flights"]  # by callsign too
