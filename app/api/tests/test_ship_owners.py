"""Airlines from callsigns and ship owners from Global Fishing Watch and Wikidata (airlines.py, shipowners.py)."""

import httpx

from worldmodel_api import shipowners
from worldmodel_api.airlines import airline

GFW = {"entries": [
    {"registryInfo": [{"ssvid": "999", "imo": "1111111", "shipname": "OTHER"}]},
    {"registryInfo": [{"ssvid": "512000001", "imo": "9300001", "shipname": "AOTEAROA", "flag": "NZL", "callsign": "ZMA1",
                       "lengthM": 180, "tonnageGt": 20000, "extraFields": [{"builtYear": 2004}]}],
     "registryOwners": [{"name": "OLD OWNER LTD", "flag": "PAN", "dateFrom": "2004-01-01T00:00:00Z", "dateTo": "2015-06-01T00:00:00Z", "sourceCode": ["IMO"]},
                        {"name": "KIWI SHIPPING LTD", "flag": "NZL", "dateFrom": "2015-06-02T00:00:00Z", "dateTo": None, "sourceCode": ["IMO", "ICCAT"]}],
     "registryPublicAuthorizations": [{"sourceCode": ["SPRFMO"], "dateFrom": "2020-01-01T00:00:00Z", "dateTo": "2026-01-01T00:00:00Z"}],
     "selfReportedInfo": [{"id": "abc-123", "ssvid": "512000001", "flag": "PAN", "transmissionDateFrom": "2012-01-01T00:00:00Z", "transmissionDateTo": "2015-06-01T00:00:00Z"},
                          {"id": "abc-124", "ssvid": "512000001", "flag": "NZL", "transmissionDateFrom": "2015-06-02T00:00:00Z", "transmissionDateTo": "2026-11-01T00:00:00Z"}],
     "combinedSourcesInfo": [{"geartypes": [{"name": "TRAWLERS"}]}]}]}

WD = {"results": {"bindings": [
    {"ship": {"value": "http://www.wikidata.org/entity/Q1"}, "shipLabel": {"value": "Aotearoa"}, "builderLabel": {"value": "Hyundai Heavy Industries"},
     "operatorLabel": {"value": "Kiwi Lines"}, "launched": {"value": "2003-05-01T00:00:00Z"}, "image": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/A.jpg"}},
    {"ship": {"value": "http://www.wikidata.org/entity/Q1"}, "shipLabel": {"value": "Aotearoa"}, "builderLabel": {"value": "Hyundai Heavy Industries"},
     "operatorLabel": {"value": "Pacific Ops"}}]}}


def test_airline_from_callsign():
    assert airline("ANZ123 ")["name"] == "Air New Zealand"
    assert airline("qfa1")["country"] == "Australia"
    assert airline("ZKABC") is None and airline(None) is None and airline("N123AB") is None


def test_parse_gfw_picks_the_same_ship():
    g = shipowners.parse_gfw(GFW, "9300001", "512000001")
    assert g["name"] == "AOTEAROA" and g["built"] == 2004 and g["gear"] == "TRAWLERS"
    assert [o["name"] for o in g["owners"]] == ["KIWI SHIPPING LTD", "OLD OWNER LTD"]  # current first
    assert g["owners"][0]["source"] == "IMO, ICCAT" and g["owners"][1]["to"] == "2015-06-01"
    assert [f["flag"] for f in g["flags"]] == ["PAN", "NZL"] and g["authorisations"][0]["by"] == "SPRFMO"
    assert shipowners.parse_gfw(GFW, None, "512000001")["imo"] == "9300001"  # by MMSI when no IMO
    assert shipowners.parse_gfw(GFW, "5555555", "1") is None


def test_parse_wikidata_merges_rows():
    w = shipowners.parse_wikidata(WD)
    assert w["builder"] == ["Hyundai Heavy Industries"] and w["operator"] == ["Kiwi Lines", "Pacific Ops"] and w["launched"] == "2003"
    assert shipowners.parse_wikidata({"results": {"bindings": []}}) is None
    assert '"9300001"' in shipowners.wikidata_query("9300001")


def test_owner_uses_settings_keeps_answers_and_retries_failures(tmp_path, monkeypatch):
    calls = {"gfw": 0, "wd": 0}

    def fake_gfw(imo, mmsi, token):
        calls["gfw"] += 1
        return shipowners.parse_gfw(GFW, imo, mmsi)

    def fake_wd(imo):
        calls["wd"] += 1
        if calls["wd"] == 1:
            raise httpx.ConnectError("down")
        return shipowners.parse_wikidata(WD)

    monkeypatch.setattr(shipowners, "gfw", fake_gfw)
    monkeypatch.setattr(shipowners, "wikidata", fake_wd)
    store = shipowners.Owners(tmp_path)
    detail = {"imo": 9300001}
    monkeypatch.delenv("GFW_API_TOKEN", raising=False)
    out = shipowners.owner(store, 512000001, detail, {})
    assert out["gfw"] is None and any("GFW_API_TOKEN" in n for n in out["notes"])
    assert out["wikidata"]["error"] and out["equasis"]["imo"] == "9300001"
    monkeypatch.setenv("GFW_API_TOKEN", "t")
    out = shipowners.owner(store, 512000001, detail, {})
    assert out["gfw"]["owners"][0]["name"] == "KIWI SHIPPING LTD" and out["wikidata"]["builder"] == ["Hyundai Heavy Industries"]
    out = shipowners.owner(shipowners.Owners(tmp_path), 512000001, detail, {})  # from the file
    assert calls == {"gfw": 1, "wd": 2} and out["wikidata"]["operator"]
    off = shipowners.owner(store, 512000001, detail, {"ship_owners_gfw": False, "ship_owners_wikidata": False, "ship_owners_equasis": False})
    assert off["gfw"] is None and off["wikidata"] is None and off["equasis"] is None
    no_imo = shipowners.owner(store, 512000002, {}, {"ship_owners_gfw": False})
    assert no_imo["wikidata"] is None and any("IMO" in n for n in no_imo["notes"])


def test_plane_journey_is_kept(monkeypatch):
    from worldmodel_api import journeys

    asked = {"track": 0, "aircraft": 0}

    def fake_track(q, auth, icao24):
        asked["track"] += 1
        return {"track": {"type": "FeatureCollection", "features": [], "from": 1, "points": 2}, "route": None, "from_airport": None, "note": None}

    def fake_aircraft(icao24):
        asked["aircraft"] += 1
        return {"registration": "ZK-NZE"}

    monkeypatch.setattr(journeys, "_track", fake_track)
    monkeypatch.setattr(journeys, "_aircraft", fake_aircraft)
    monkeypatch.setattr(journeys, "_route", lambda cs, lat, lon: None)
    journeys._tracks.clear()
    journeys._aircraft_kept.clear()
    first = journeys.plane_journey(lambda s, p: [], lambda c: {}, "C81D90", "ANZ1", None, None)
    again = journeys.plane_journey(lambda s, p: [], lambda c: {}, "c81d90", "ANZ1", None, None)
    assert asked == {"track": 1, "aircraft": 1} and "kept_at" in again and "kept_at" not in first
    assert again["airline"]["name"] == "Air New Zealand" and again["aircraft"]["registration"] == "ZK-NZE"
