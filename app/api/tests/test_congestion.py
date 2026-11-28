"""Congestion: airport busy hours, limits, gates and delays; road counts; trains now. Answers are
shaped like the live services' (OpenSky, Overpass, EUROCONTROL, FAA, NZTA ArcGIS, WebTRIS,
Transport for NSW, GTFS Realtime in JSON and protocol buffers)."""

import io
import json
import struct
import zipfile
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from worldmodel_api import airbusy, main, roads, trains
from worldmodel_contract import catalogue


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setattr(airbusy, "_list_cache", None)
    monkeypatch.setattr(airbusy, "ASK_GAP", 0)
    return tmp_path


def _airport(icao, country, size="large", lon=174.79, lat=-37.01, iata=None):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"icao": icao, "iata": iata, "name": icao, "country": country, "size": size}}


# ----------------------------------------------------------------------------- airports
def test_pick_airports_home_large_and_busiest():
    cfg = {"home_countries": {"all_scheduled": ["NZL"], "large": ["AUS"]}, "busiest_airports": ["KATL", "EGLL"]}
    feats = [_airport("NZWN", "NZL", "medium"), _airport("YSSY", "AUS"), _airport("YBTL", "AUS", "medium"),
             _airport("KATL", "USA"), _airport("EGLL", "GBR"), _airport("KXYZ", "USA")]
    got = [a["icao"] for a in airbusy.pick_airports(feats, cfg)]
    assert got[0] == "NZWN" and set(got) == {"NZWN", "YSSY", "KATL", "EGLL"}
    assert {a["icao"] for a in airbusy.pick_airports(feats, cfg, world=False)} == {"NZWN", "YSSY"}


def test_counting_by_local_hour_whole_days_only():
    nz = ZoneInfo("Pacific/Auckland")
    t = lambda y, m, d, h: int(datetime(y, m, d, h, 10, tzinfo=nz).timestamp())
    arr = [{"lastSeen": t(2026, 11, 20, 7)}, {"lastSeen": t(2026, 11, 20, 7)}, {"lastSeen": t(2026, 11, 20, 18)}]
    dep = [{"firstSeen": t(2026, 11, 20, 6)}]
    counts = airbusy.count_flights(arr, dep, nz)
    assert counts["2026-11-20"]["arr"][7] == 2 and counts["2026-11-20"]["dep"][6] == 1
    store: dict = {}
    # NZ 20 Nov runs from 19 Nov 11:00 UTC to 20 Nov 11:00 UTC: both UTC days are needed
    airbusy.merge_counts(store, "2026-11-20", counts)
    assert airbusy.local_days(store, nz) == {}
    airbusy.merge_counts(store, "2026-11-19", {})
    days = airbusy.local_days(store, nz)
    assert list(days) == ["2026-11-20"]
    pr = airbusy.profile(days)
    assert pr["peak_hour"] == 7 and pr["peak_flights"] == 2 and pr["per_day"] == 4


def test_limits_curfews_and_own_files(home):
    lim = airbusy.limits()
    assert lim["YSSY"]["hourly_limit"] == 80 and lim["YSSY"]["slot_level"] == 3
    assert airbusy.curfew_hours("23:00-06:00") == [23, 0, 1, 2, 3, 4, 5]
    folder = home / "manual" / "airport_limits"
    folder.mkdir(parents=True)
    (folder / "mine.csv").write_text("icao,hourly_limit,note\nNZAA,45,From the airport's plan\n", encoding="utf-8")
    assert airbusy.limits()["NZAA"]["hourly_limit"] == 45
    assert airbusy.limits()["NZAA"]["source"] == "Your file mine.csv"


def test_gates_from_overpass_counts():
    batch = [{"icao": "NZAA", "lat": -37, "lon": 174.8, "size": "large"}, {"icao": "NZWN", "lat": -41.3, "lon": 174.8}]
    q = airbusy.gates_query(batch)
    assert q.count("out count;") == 4 and "around:4000" in q and "around:2500" in q
    body = {"elements": [{"type": "count", "tags": {"total": "32"}}, {"type": "count", "tags": {"total": "74"}},
                         {"type": "count", "tags": {"total": "14"}}, {"type": "count", "tags": {"total": "30"}}]}
    assert airbusy.gates_counts(body, batch) == {"NZAA": {"gates": 32, "stands": 74}, "NZWN": {"gates": 14, "stands": 30}}


def test_eurocontrol_and_faa():
    traffic = airbusy.eurocontrol_rows("YEAR,MONTH_NUM,FLT_DATE,APT_ICAO,FLT_TOT_1\n2026,01,2026-01-01,EGLL,1200\n2026,01,2026-01-02,EGLL,1300\n")
    dly = airbusy.eurocontrol_rows("FLT_DATE,APT_ICAO,FLT_ARR_1,DLY_APT_ARR_1\n2026-01-01,EGLL,600,1200\n2026-01-02,EGLL,650,0\n")
    taxi = airbusy.eurocontrol_rows("YEAR,MONTH_NUM,APT_ICAO,TOTAL_REF_NB_FL,TOTAL_ADD_TIME_MIN\n2026,01,EGLL,1000,4500\n")
    got = airbusy.eurocontrol_months(traffic, dly, taxi, [])["EGLL"]["2026-01"]
    assert got == {"flights_a_day": 1250.0, "arr_delay_min": 0.96, "taxi_add_min": 4.5}
    xml = """<AIRPORT_STATUS_INFORMATION><Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List>
      <Program><ARPT>SFO</ARPT><Reason>low ceilings</Reason><End_Time>3:15 pm PST</End_Time></Program></Ground_Stop_List></Delay_type>
      <Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List><Delay><ARPT>LAS</ARPT>
      <Reason>STAFF:Staffing</Reason><Arrival_Departure Type="Departure"><Min>16 minutes</Min><Max>30 minutes</Max>
      <Trend>Increasing</Trend></Arrival_Departure></Delay></Arrival_Departure_Delay_List></Delay_type></AIRPORT_STATUS_INFORMATION>"""
    st = airbusy.faa_status(xml)
    assert st["SFO"][0]["kind"] == "Ground Stop Programs" and "End Time: 3:15 pm PST" in st["SFO"][0]["detail"]
    assert "Departure 16 minutes-30 minutes (Increasing)" in st["LAS"][0]["detail"]


def test_collector_round_and_api(home, monkeypatch):
    nz = ZoneInfo("Pacific/Auckland")
    monkeypatch.setattr(airbusy, "airports", lambda q, s=None: [{"icao": "NZWN", "iata": "WLG", "name": "Wellington", "country": "NZL",
                                                                 "size": "medium", "lon": 174.8, "lat": -41.33, "tz": "Pacific/Auckland",
                                                                 "why": "home", "rank": None, "city": "Wellington"}])
    now = datetime(2026, 11, 24, 12, tzinfo=UTC).timestamp()

    def handler(req: httpx.Request):
        if "opensky" in req.url.host:
            begin = int(req.url.params["begin"])
            hour = datetime.fromtimestamp(begin + 20 * 3600, UTC).astimezone(nz)  # 8 or 9 am NZ
            key = "lastSeen" if "arrival" in req.url.path else "firstSeen"
            return httpx.Response(200, json=[{key: begin + 20 * 3600}] * (3 if hour.weekday() < 5 else 1))
        return httpx.Response(404)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    st = airbusy.COLLECTOR.round(None, {"airport_gates_fetch": False, "airport_delays_fetch": False}, client=c, now=now)
    assert st["days_fetched"] == airbusy.BACKFILL_DAYS and not st["error"]
    got = airbusy.airport_detail(None, "WLG", {})
    assert got["profile"]["peak_flights"] == 6 and got["curfew_hours"][:1] == [0]
    assert got["use"] == 100 and got["against"] == "record"
    with TestClient(main.app) as tc:
        r = tc.get("/api/v1/congestion/airports/map").json()
    assert r["features"][0]["properties"]["peak_flights"] == 6


def test_opensky_refusal_stops_the_round(home, monkeypatch):
    monkeypatch.setattr(airbusy, "airports", lambda q, s=None: [{"icao": i, "tz": "UTC", "lon": 0, "lat": 0} for i in ("EGLL", "EGKK")])
    asked = []

    def handler(req):
        asked.append(req.url.params["airport"])
        return httpx.Response(429)

    st = airbusy.COLLECTOR.round(None, {"airport_gates_fetch": False, "airport_delays_fetch": False},
                                 client=httpx.Client(transport=httpx.MockTransport(handler)), now=1_795_000_000)
    assert "429" in st["error"] and set(asked) == {"EGLL"}


# ----------------------------------------------------------------------------- roads
def test_nzta_sites_and_counts():
    sites = roads.nzta_sites([{"attributes": {"siteref": "01000007", "sh": "10", "description": "Sth of Puketona Rd", "region": "01 - Northland",
                                              "aadt1yearago": 6145, "aadt5yearsago": 4954}, "geometry": {"x": 173.96, "y": -35.30}}])
    assert sites["01000007"]["name"] == "SH10 Sth of Puketona Rd" and sites["01000007"]["aadt"][-1] == 6145
    into: dict = {}
    roads.nzta_counts([{"attributes": {"SiteRef": "01000007", "startDate": 1793491200000, "vehicles": 11777}}], into)
    assert into == {"01000007": {"2026-11-01": 11777.0}}


def test_webtris_and_nsw_rows():
    rows = [{"Report Date": "2026-06-01T00:00:00", "Time Period Ending": f"{h:02d}:{m:02d}:00", "Total Volume": "100", "Avg mph": "60"}
            for h in range(2) for m in (14, 29, 44, 59)]
    into: dict = {}
    roads.webtris_rows(rows, into)
    assert into["2026-06-01"]["v"][:2] == [400, 400] and into["2026-06-01"]["mph"][0] == 60.0
    nsw: dict = {}
    roads.nsw_hours([{"station_key": "7", "date": "2026-11-01", **{f"hour_{h:02d}": 10 for h in range(24)}},
                     {"station_key": "7", "date": "2026-11-01", "hour_08": 5}], nsw)
    assert nsw["7"]["2026-11-01"]["v"][8] == 15 and sum(nsw["7"]["2026-11-01"]["v"]) == 245


def test_webtris_pick_spreads_sites():
    sites = [{"Id": str(i), "Name": f"M{i}", "Status": "Active", "Longitude": -2 + i * 0.001, "Latitude": 52.0} for i in range(500)]
    sites += [{"Id": "9999", "Name": "M1", "Status": "Inactive", "Longitude": 0, "Latitude": 51}]
    got = roads.webtris_pick(sites, 300)
    assert 1 <= len(got) <= 300 and all(s["Status"] == "Active" for s in got)


def test_road_sites_and_card(home):
    roads._write("nzta_sites.json", {"1": {"name": "SH1 Harbour Bridge", "lon": 174.75, "lat": -36.83, "aadt": [150000, 160000]}})
    days = {f"2026-{m:02d}-{d:02d}": 160000.0 + (5000 if (m, d) >= (11, 21) else 0) for m in (9, 10, 11) for d in range(1, 29)}
    roads._write("nzta_counts.json", {"1": days})
    g = roads.sites_geojson()
    p = g["features"][0]["properties"]
    assert p["id"] == "nzta:1" and p["vs_normal"] == pytest.approx(3.1, abs=0.1)
    card = roads.site("nzta:1")
    assert card["weekdays"][0] and not card.get("hours")
    with TestClient(main.app) as tc:
        assert tc.get("/api/v1/congestion/roads/site/nzta:1").json()["name"] == "SH1 Harbour Bridge"
        tile = tc.get("/api/v1/congestion/traffic-tiles/3/7/4.png")  # no TomTom key: a see-through tile
        assert tile.status_code == 200 and tile.headers["X-Tile-Missing"] == "1"


# ----------------------------------------------------------------------------- trains
def _vint(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _ld(num, payload):
    return _vint(num << 3 | 2) + _vint(len(payload)) + payload


def _f32(num, v):
    return _vint(num << 3 | 5) + struct.pack("<f", v)


def _vi(num, v):
    return _vint(num << 3) + _vint(v & 0xFFFFFFFFFFFFFFFF)


def test_protocol_buffer_feed():
    trip = _ld(1, b"T1") + _ld(5, b"BMT")
    vp = _ld(1, trip) + _ld(2, _f32(1, -33.87) + _f32(2, 151.2) + _f32(3, 90.0)) + _vi(5, 1795000000) + _ld(8, _ld(1, b"V9") + _ld(2, b"Set A"))
    tu = _ld(1, trip) + _ld(2, _ld(2, _vi(1, 420)))
    feed = _ld(1, b"hdr") + _ld(2, _ld(1, b"e1") + _ld(4, vp)) + _ld(2, _ld(1, b"e2") + _ld(3, tu))
    ents = trains.entities(feed, "application/x-protobuf")
    got = trains.trains_from(ents, None, {"BMT": "Blue Mountains Line"}, 1795000000)
    assert got[0]["id"] == "V9" and got[0]["line"] == "Blue Mountains Line" and got[0]["delay_s"] == 420
    assert got[0]["lat"] == pytest.approx(-33.87, abs=1e-4) and got[0]["heading"] == 90
    late = trains._delay_of({"delay": None, "stop_time_update": [{"arrival": {"delay": -60}}]})
    assert late == -60


def test_json_feed_picks_trains_only():
    body = json.dumps({"status": "OK", "response": {"entity": [
        {"id": "1", "vehicle": {"trip": {"tripId": "t1", "routeId": "WEST-201"}, "position": {"latitude": -36.85, "longitude": 174.76},
                                "timestamp": 1795000000, "vehicle": {"id": "AMP 1", "label": "AMP 1"}}},
        {"id": "2", "vehicle": {"trip": {"tripId": "b1", "routeId": "NX1"}, "position": {"latitude": -36.8, "longitude": 174.7}}},
        {"id": "3", "tripUpdate": {"trip": {"tripId": "t1"}, "stopTimeUpdate": [{"departure": {"delay": 400}}]}}]}}).encode()
    got = trains.trains_from(trains.entities(body, "application/json"), {"WEST-201"}, {"WEST-201": "Western Line"}, 1795000000)
    assert [(t["id"], t["line"], t["delay_s"]) for t in got] == [("AMP 1", "Western Line", 400)]


def test_rail_routes_from_timetable_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("routes.txt", "route_id,route_short_name,route_long_name,route_type\nKPL,KPL,Kapiti Line,2\n1,1,Island Bay,3\n")
    assert trains.rail_routes_from_zip(buf.getvalue()) == {"KPL": "Kapiti Line"}


def test_poll_saves_paths_and_lateness(home, monkeypatch):
    monkeypatch.setenv("TFNSW_API_KEY", "k")
    monkeypatch.setattr(trains, "feeds", lambda: [{"id": "syd", "name": "Sydney Trains", "operator": "TfNSW", "tz": "Australia/Sydney",
                                                  "key": "TFNSW_API_KEY", "header": "Authorization", "header_prefix": "apikey ",
                                                  "positions": "https://x/pos", "updates": "https://x/upd", "rail_only": True}])
    t = trains.Trains()
    trip = _ld(1, b"T1") + _ld(5, b"T1R")
    pos = _ld(2, _ld(1, b"e") + _ld(4, _ld(1, trip) + _ld(2, _f32(1, -33.87) + _f32(2, 151.2)) + _ld(8, _ld(1, b"V1"))))
    upd = _ld(2, _ld(1, b"u") + _ld(3, _ld(1, trip) + _vi(5, 600)))
    seen = []

    def handler(req):
        seen.append(req.headers.get("Authorization"))
        return httpx.Response(200, content=pos if req.url.path == "/pos" else upd, headers={"content-type": "application/octet-stream"})

    now = datetime(2026, 11, 27, 8, tzinfo=ZoneInfo("Australia/Sydney")).timestamp()
    t.poll(httpx.Client(transport=httpx.MockTransport(handler)), {"trains_collect": True}, now=now)
    assert seen == ["apikey k", "apikey k"]
    g = t.geojson(150, -35, 152, -33)
    assert g["features"][0]["properties"]["delay_min"] == 10.0
    assert t.trail("syd:V1")["path"][0][1:] == [151.2, -33.87]
    assert t.day_path("syd:V1", "2026-11-27")[0][3] == 600
    late = t.lateness(7)["networks"][0]
    assert late["hours"][8]["late_pct"] == 100.0


def test_auckland_reads_one_combined_feed(home, monkeypatch):
    """Auckland's free product allows 35,000 calls a week: one call a read (positions and
    trip updates together) keeps 30-second reads around 20,000 a week."""
    akl = next(f for f in catalogue.congestion()["train_feeds"] if f["id"] == "akl")
    assert not akl.get("updates") and 7 * 24 * 3600 / 30 <= 35_000
    monkeypatch.setenv("AT_API_KEY", "k")
    monkeypatch.setattr(trains, "feeds", lambda: [{**akl, "rail_only": True}])
    trip = _ld(1, b"T1") + _ld(5, b"STH")
    both = (_ld(2, _ld(1, b"e") + _ld(4, _ld(1, trip) + _ld(2, _f32(1, -36.85) + _f32(2, 174.76)) + _ld(8, _ld(1, b"V1"))))
            + _ld(2, _ld(1, b"u") + _ld(3, _ld(1, trip) + _vi(5, 120))))
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=both, headers={"content-type": "application/x-protobuf"})

    t = trains.Trains()
    t.poll(httpx.Client(transport=httpx.MockTransport(handler)), {"trains_collect": True}, now=datetime(2026, 11, 27, 8, tzinfo=ZoneInfo("Pacific/Auckland")).timestamp())
    assert calls == ["https://api.at.govt.nz/realtime/legacy/"]
    assert t.geojson(174, -37, 175, -36)["features"][0]["properties"]["delay_min"] == 2.0


def test_trains_without_keys_say_so(home, monkeypatch):
    for k in ("AT_API_KEY", "METLINK_API_KEY", "TFNSW_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with TestClient(main.app) as tc:
        r = tc.get("/api/v1/live/trains", params={"west": 170, "south": -45, "east": 180, "north": -34}).json()
        assert "AT_API_KEY" in r["note"]
        assert tc.get("/api/v1/congestion/trains").json()["feeds"][0]["has_key"] is False


def test_punctuality_files(home):
    folder = home / "manual" / "rail_punctuality"
    folder.mkdir(parents=True)
    (folder / "orr.csv").write_text("Operator,Period end,On time %\nGreat Britain,2026-10-11,68.1\nGreat Britain,2026-09-13,70.2\n", encoding="utf-8")
    got = trains.punctuality()
    assert got[0]["network"] == "Great Britain" and got[0]["points"][0] == ["2026-09-13", 70.2]
