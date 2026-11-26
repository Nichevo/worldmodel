"""The map's Cameras layer: each road agency's list read into dots (shapes copied from the real
feeds in November 2026), only the agencies whose region is in view asked, lists kept, and Windy
asked only with a key. Network calls are replaced."""

import httpx
import pytest

from worldmodel_api import cameras

NZTA = {"type": "FeatureCollection", "lastUpdated": 1795638212, "features": [
    {"type": "Feature", "properties": {"ClassName": "TrafficCamera", "ExternalId": 709, "Name": "SH1 Memorial Ave North",
                                       "Description": "North along the Russley Overbridge", "Offline": 0, "UnderMaintenance": 0,
                                       "ImageUrl": "https://www.trafficnz.info/camera/709.jpg", "Latitude": "-43.492518",
                                       "Longitude": "172.550329", "Direction": "Northbound", "id": 1433},
     "geometry": {"type": "Point", "coordinates": [172.550329, -43.492518]}},
    {"type": "Feature", "properties": {"ClassName": "TrafficCamera", "ExternalId": 710, "Name": "SH1 Memorial Ave South",
                                       "Offline": 1, "UnderMaintenance": 0, "ImageUrl": "https://www.trafficnz.info/camera/710.jpg",
                                       "Latitude": "-43.492761", "Longitude": "172.550215", "Direction": "Southbound"},
     "geometry": {"type": "Point", "coordinates": [172.550215, -43.492761]}}]}
TFL = [{"id": "JamCams_00002.00865", "commonName": "A406 Billet Upass E", "placeType": "JamCam", "lat": 51.60067, "lon": -0.01594,
        "additionalProperties": [
            {"category": "payload", "key": "available", "value": "true"},
            {"category": "payload", "key": "imageUrl", "value": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00002.00865.jpg"},
            {"category": "payload", "key": "videoUrl", "value": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00002.00865.mp4"},
            {"category": "cameraView", "key": "view", "value": "West"}]}]
CALTRANS = {"data": [{"cctv": {"index": "1", "location": {
    "district": "7", "locationName": "I-110 : (196) Avenue 26 Off Ramp", "nearbyPlace": "Cypress Park", "longitude": "-118.2215",
    "latitude": "34.0837", "direction": "South", "county": "Los Angeles", "route": "I-110"}, "inService": "true",
    "imageData": {"streamingVideoURL": "https://wzmedia.dot.ca.gov/D7/CCTV-196.stream/playlist.m3u8",
                  "static": {"currentImageURL": "https://cwwp2.dot.ca.gov/data/d7/cctv/image/i110196avenue26offramp/i110196avenue26offramp.jpg"}}}}]}
FINLAND = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "id": "C01503", "geometry": {"type": "Point", "coordinates": [23.99616, 60.05374, 0]},
     "properties": {"id": "C01503", "name": "kt51_Inkoo", "collectionStatus": "GATHERING",
                    "presets": [{"id": "C0150301", "inCollection": True}, {"id": "C0150302", "inCollection": True},
                                {"id": "C0150309", "inCollection": False}]}}]}
WINDY = {"total": 2, "webcams": [
    {"webcamId": 1600000001, "title": "Piha: Lion Rock", "status": "active", "lastUpdatedOn": "2026-11-25T20:00:00.000Z",
     "categories": [{"id": "beach", "name": "Beach"}], "images": {"current": {"preview": "https://imgproxy.windy.com/x/preview.jpg?token=t"}},
     "location": {"latitude": -36.95, "longitude": 174.47, "city": "Piha", "region": "Auckland", "country": "New Zealand"},
     "player": {"live": "https://webcams.windy.com/webcams/public/player?webcamId=1600000001&playerType=live"},
     "urls": {"detail": "https://webcams.windy.com/webcams/1600000001"}},
    {"webcamId": 1600000002, "title": "Old", "status": "inactive", "location": {"latitude": -36.9, "longitude": 174.5}}]}


def mock(calls: list, *, windy=WINDY, nzta_status=200):
    def handle(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        host = req.url.host
        if host == "www.journeys.nzta.govt.nz":
            return httpx.Response(nzta_status, json=NZTA)
        if host == "api.tfl.gov.uk":
            return httpx.Response(200, json=TFL)
        if host == "cwwp2.dot.ca.gov":
            return httpx.Response(200, json=CALTRANS) if "/d7/" in req.url.path else httpx.Response(404)
        if host == "tie.digitraffic.fi":
            return httpx.Response(200, json=FINLAND)
        if host == "api.windy.com":
            assert req.headers.get("x-windy-api-key") == "wk"
            if req.url.path.endswith("/webcams"):
                return httpx.Response(200, json=windy)
            return httpx.Response(200, json=windy["webcams"][0])
        if host == "api.qldtraffic.qld.gov.au":
            return httpx.Response(429, json={"message": "Too Many Requests"})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture(autouse=True)
def no_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))  # saved camera lists go to a scratch folder
    for k in ("WINDY_WEBCAMS_API_KEY", "TFNSW_API_KEY", "QLDTRAFFIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_parsers_read_each_feed():
    nz = cameras.parse_nzta(NZTA)
    assert [c["properties"]["id"] for c in nz] == ["nzta:709", "nzta:710"]
    assert nz[0]["properties"]["image"].endswith("709.jpg") and "offline" not in nz[0]["properties"] and nz[1]["properties"]["offline"]
    tfl = cameras.parse_tfl(TFL)[0]["properties"]
    assert tfl["video"].endswith(".mp4") and tfl["direction"] == "West" and tfl["id"] == "tfl:00002.00865"
    ca = cameras.parse_caltrans(CALTRANS)[0]
    assert ca["geometry"]["coordinates"] == [-118.2215, 34.0837] and ca["properties"]["stream"].endswith(".m3u8")
    fi = cameras.parse_finland(FINLAND)[0]["properties"]
    assert fi["name"] == "Inkoo (road 51)" and fi["kind"] == "weather" and len(fi["images"]) == 2
    assert fi["image"] == "https://weathercam.digitraffic.fi/C0150301.jpg"
    w = cameras.parse_windy(WINDY)
    assert len(w) == 1 and w[0]["properties"]["kind"] == "beach" and w[0]["properties"]["player"].endswith("playerType=live")


def test_only_agencies_in_view_are_asked_and_lists_are_kept():
    calls: list = []
    cams = cameras.Cameras()
    got = cams.get(165, -48, 180, -34, client=mock(calls))  # New Zealand
    assert {c["properties"]["source"] for c in got["features"]} == {"nzta"}
    assert all("nzta" in u for u in calls)
    assert "WINDY_WEBCAMS_API_KEY" in got["note"]
    cams.get(170, -46, 175, -40, client=mock(calls))
    assert len(calls) == 1  # kept: not read again
    got = cams.get(-1, 51, 1, 52, client=mock(calls))  # London
    assert [c["properties"]["name"] for c in got["features"]] == ["A406 Billet Upass E"]


def test_pacific_view_across_the_date_line_and_failures(monkeypatch):
    calls: list = []
    cams = cameras.Cameras()
    got = cams.get(140, -50, 200, -10, client=mock(calls, nzta_status=503))  # NZ, Queensland and NSW, across 180
    note = got["note"]
    assert "did not answer" in note and "QLDTRAFFIC_API_KEY" in note and "TFNSW_API_KEY" in note
    n = len(calls)
    cams.get(140, -50, 200, -10, client=mock(calls))
    assert len(calls) == n  # a failed agency is not asked again straight away


def test_california_reads_every_district_and_skips_missing_ones():
    calls: list = []
    got = cameras.Cameras().get(-125, 32, -114, 42.5, client=mock(calls))
    assert len([u for u in calls if "dot.ca.gov" in u]) == 12 and got["count"] == 1


def test_windy_with_a_key(monkeypatch):
    monkeypatch.setenv("WINDY_WEBCAMS_API_KEY", "wk")
    calls: list = []
    cams = cameras.Cameras()
    got = cams.get(174, -37.5, 175.5, -36, client=mock(calls))
    windy = [c for c in got["features"] if c["properties"]["source"] == "windy"]
    assert len(windy) == 1 and windy[0]["properties"]["name"] == "Piha: Lion Rock"
    assert len([u for u in calls if "windy" in u]) == 2  # most watched, then beaches and coasts
    assert "note" not in got or "WINDY" not in got["note"]
    cams.get(174, -37.5, 175.5, -36, client=mock(calls))
    assert len([u for u in calls if "windy" in u]) == 2  # kept nine minutes
    one = cams.windy_one(1600000001, client=mock(calls))
    assert one["image"].startswith("https://imgproxy.windy.com") and one["player"]


def test_endpoint_respects_the_setting(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from worldmodel_api import main
    from worldmodel_contract import local

    monkeypatch.setattr(local, "load_settings", lambda *a, **k: {"live_cameras": False})
    r = TestClient(main.app).get("/api/v1/live/cameras", params={"west": 170, "south": -45, "east": 180, "north": -30}).json()
    assert "switched off" in r["error"]


def test_a_slow_agency_list_is_read_in_the_background(monkeypatch):
    import threading
    import time

    release = threading.Event()

    def slow(source, client, old=None):
        release.wait(5)
        return [cameras._cam(source, 1, "Slow cam", -36.9, 174.8)]

    monkeypatch.setattr(cameras, "read_list", slow)
    monkeypatch.setattr(cameras, "WAIT", 0.2)
    monkeypatch.delenv("WINDY_WEBCAMS_API_KEY", raising=False)
    cams = cameras.Cameras()
    started = time.monotonic()
    got = cams.get(165, -48, 180, -34)  # no client: lists read in the background
    assert time.monotonic() - started < 2 and got["features"] == [] and got["retry_in"] == cameras.RETRY_SOON
    assert "Still reading" in got["note"]
    release.set()
    cams.loading["nzta"].join(5)
    got = cams.get(165, -48, 180, -34)
    assert [c["properties"]["name"] for c in got["features"]] == ["Slow cam"] and "retry_in" not in got


def test_lists_are_saved_and_shown_at_once_after_a_restart(monkeypatch, tmp_path):
    import threading
    import time

    calls: list = []
    cameras.Cameras().get(165, -48, 180, -34, client=mock(calls))  # New Zealand, read and saved
    assert (tmp_path / "live" / "cameras" / "nzta.json").is_file()

    release = threading.Event()

    def slow(source, client, old=None):
        release.wait(5)
        return [cameras._cam(source, 1, "New cam", -36.9, 174.8)]

    monkeypatch.setattr(cameras, "read_list", slow)
    monkeypatch.setattr(cameras, "LIST_KEEP", 0)  # the saved list is old: ask the agency again
    cams = cameras.Cameras()  # a restart
    started = time.monotonic()
    got = cams.get(165, -48, 180, -34)
    assert time.monotonic() - started < 1  # no waiting: the saved cameras show straight away
    assert {c["properties"]["name"] for c in got["features"]} == {"SH1 Memorial Ave North", "SH1 Memorial Ave South"}
    assert got["checking"] == ["NZ Transport Agency Waka Kotahi"] and got["retry_in"] == cameras.RETRY_SOON
    release.set()
    cams.loading["nzta"].join(5)
    monkeypatch.setattr(cameras, "LIST_KEEP", 3600)
    got = cams.get(165, -48, 180, -34)
    assert [c["properties"]["name"] for c in got["features"]] == ["New cam"] and "checking" not in got


def test_an_agency_that_stops_answering_keeps_its_saved_list():
    calls: list = []
    cameras.Cameras().get(165, -48, 180, -34, client=mock(calls))
    cams = cameras.Cameras()  # a restart, with the saved list old and the agency down
    cameras.LIST_KEEP, keep = 0, cameras.LIST_KEEP
    try:
        got = cams.get(165, -48, 180, -34, client=mock(calls, nzta_status=503))
    finally:
        cameras.LIST_KEEP = keep
    assert got["count"] == 2 and "did not answer" in got["note"] and "Showing its cameras as saved" in got["note"]


def test_a_california_district_that_times_out_keeps_its_last_cameras():
    old = cameras.parse_caltrans(CALTRANS)  # district 7's camera from the last read

    def handle(req: httpx.Request) -> httpx.Response:
        if "/d7/" in req.url.path:
            raise httpx.ReadTimeout("slow", request=req)
        if "/d4/" in req.url.path:
            body = {"data": [dict(CALTRANS["data"][0], cctv=dict(CALTRANS["data"][0]["cctv"], index="9",
                                                                  location=dict(CALTRANS["data"][0]["cctv"]["location"], district="4")))]}
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    got = cameras.read_list("caltrans", httpx.Client(transport=httpx.MockTransport(handle)), old=old)
    assert sorted(c["properties"]["id"] for c in got) == ["caltrans:4-9", "caltrans:7-1"]
