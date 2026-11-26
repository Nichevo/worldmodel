"""Then and now: LINZ's survey list, Esri's versions of a place, the before/after pair for AI,
Landsat timelapses, the aerial photo background and New Zealand aerial scans, all against stand-ins
for the picture sites and the local model."""

import io
import json
from datetime import date

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from worldmodel_api import spotting, thennow, tiles
from worldmodel_contract import thennow as tn


def jpeg(colour, size=256):
    buf = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buf, "JPEG")
    return buf.getvalue()


def png(colour, size=256):
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), colour).save(buf, "PNG")
    return buf.getvalue()


class Resp:
    def __init__(self, status=200, body=None, content=b"", kind="application/json"):
        self.status_code, self._body, self.content = status, body, content
        self.headers = {"content-type": kind}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("bad", request=None, response=None)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    thennow._idx.update(rows=None, shapes=None, state="idle", error=None, built=None)
    return tmp_path


def square(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def test_titles_and_layer_names():
    assert tn.linz_layer("christchurch_2023_0.075m") == "christchurch-2023-0.075m"
    t = thennow.parse_title("Christchurch 0.075m Urban Aerial Photos (2015-2016)")
    assert t == {"year_from": 2015, "year_to": 2016, "gsd": 0.075, "kind": "urban"}
    assert thennow.parse_title("Auckland 0.4m SN139 (1939-1940)")["kind"] == "historical"
    assert thennow.parse_title("New Zealand 10m Satellite Imagery (2025-2026)")["kind"] == "satellite"
    assert tn.layer_ok("aerial") and tn.layer_ok("christchurch-2023-0.075m")
    assert not tn.layer_ok("../etc") and not tn.layer_ok("a b") and not tn.layer_ok("")
    assert tn.in_nz(172.6, -43.5) and tn.in_nz(-176.5, -44.0) and not tn.in_nz(151.2, -33.9)
    assert tn.ai_ok("linz:aerial") and tn.ai_ok("eox:2018") and not tn.ai_ok("esri:now") and not tn.ai_ok("wayback:123")


def test_build_index_and_surveys_at(home):
    catalog = {"links": [
        {"rel": "child", "href": "./canterbury/christchurch_2023_0.075m/rgb/2193/collection.json", "title": "Christchurch 0.075m Urban Aerial Photos (2023)"},
        {"rel": "child", "href": "./canterbury/christchurch_1940_0.4m/rgb/2193/collection.json", "title": "Christchurch 0.4m SN100 (1940)"},
        {"rel": "child", "href": "./canterbury/christchurch_2023_0.075m/rgbnir/2193/collection.json", "title": "Christchurch 0.075m Near-Infrared Aerial Photos (2023)"},
        {"rel": "child", "href": "./auckland/auckland_2024_0.075m/rgb/2193/collection.json", "title": "Auckland 0.075m Urban Aerial Photos (2024) - Draft"},
        {"rel": "self", "href": "./catalog.json"}]}
    areas = {"christchurch_2023_0.075m": {"type": "Feature", "geometry": square(172.4, -43.7, 172.8, -43.4)},
             "christchurch_1940_0.4m": {"type": "FeatureCollection", "features": [{"geometry": square(172.6, -43.6, 172.7, -43.5)}]},
             "auckland_2024_0.075m": {"type": "Feature", "geometry": square(174.6, -37.0, 174.9, -36.7)}}
    asked = []

    def get(url):
        asked.append(url)
        if url == tn.LINZ_CATALOG:
            return Resp(body=catalog)
        slug = url.split("/")[-4]
        return Resp(body=areas[slug]) if slug in areas else Resp(404)

    rows = thennow.build_index(get, workers=1)
    assert [r["layer"] for r in rows] == ["auckland-2024-0.075m", "christchurch-2023-0.075m", "christchurch-1940-0.4m"]
    assert not any("rgbnir" in u for u in asked)  # near-infrared surveys are not read
    assert rows[0]["title"] == "Auckland 0.075m Urban Aerial Photos (2024)" and rows[0]["draft"]
    shapes = thennow._load_shapes(rows)
    here = thennow.surveys_at(172.65, -43.55, rows, shapes)
    assert [h["layer"] for h in here] == ["christchurch-2023-0.075m", "christchurch-1940-0.4m"]
    assert [h["layer"] for h in thennow.surveys_at(172.45, -43.65, rows, shapes)] == ["christchurch-2023-0.075m"]
    assert thennow.surveys_at(151.2, -33.9, rows, shapes) == []


def test_saved_index_is_used(home, monkeypatch):
    rows = [{"slug": "x_2020_0.1m", "layer": "x-2020-0.1m", "title": "X (2020)", "region": "x", "year_from": 2020, "year_to": 2020,
             "gsd": 0.1, "kind": "urban", "draft": False, "bbox": [172, -44, 173, -43], "area": square(172, -44, 173, -43)}]
    thennow._write(thennow._index_file(), {"built": date.today().isoformat(), "surveys": rows})
    monkeypatch.setattr(thennow, "_index_work", lambda: pytest.fail("should not read LINZ again"))
    got = thennow.dates(172.5, -43.5)
    assert got["nz"] and [r["layer"] for r in got["linz"]] == ["x-2020-0.1m"]
    assert got["eox"][0] == "2024" and "Christchurch" in got["places"]
    assert thennow.dates(151.2, -33.9)["linz"] == []


def test_wayback_changes():
    config = {"10": {"itemTitle": "World Imagery (Wayback 2014-02-20)"}, "30": {"itemTitle": "World Imagery (Wayback 2020-05-01)"},
              "20": {"itemTitle": "World Imagery (Wayback 2018-01-10)"}, "40": {"itemTitle": "World Imagery (Wayback 2026-11-18)"},
              "50": {"itemTitle": "World Imagery (Wayback 2026-10-29)"}}
    # The newest two versions hold the 2020 picture; 2018 is its own; 2014 is the oldest.
    holds = {40: 30, 50: 30, 30: 30, 20: 20, 10: 10}
    asked = []

    def get(url):
        if url == tn.WAYBACK_CONFIG:
            return Resp(body=config)
        rel = int(url.split("/tilemap/")[1].split("/")[0])
        asked.append(rel)
        return Resp(body={"data": [1], "select": [holds[rel]]} if holds[rel] != rel else {"data": [1]})

    got = thennow.wayback_changes(172.6, -43.5, get)
    assert [g["date"] for g in got] == ["2020-05-01", "2018-01-10", "2014-02-20"]
    assert asked == [40, 20, 10]  # 50 and 30 were skipped: the answer said where the picture came from


def test_resolve_swaps_esri():
    linz = [{"layer": "chch-2023", "title": "Christchurch 2023", "year_to": 2023, "gsd": 0.075},
            {"layer": "chch-2015", "title": "Christchurch 2015", "year_to": 2015, "gsd": 0.075}]
    assert thennow.resolve("linz:chch-2015", 172.6, -43.5, linz)[:3] == ("aerial", "chch-2015", "Christchurch 2015")
    set_id, t, _, note = thennow.resolve("wayback:2016-03-01", 172.6, -43.5, linz)
    assert (set_id, t) == ("aerial", "chch-2015") and "for looking only" in note
    set_id, t, _, note = thennow.resolve("esri:now", 151.2, -33.9, [])
    assert (set_id, t) == ("satyears", "2024") and note
    assert thennow.resolve("wayback:2017-01-01", 151.2, -33.9, [])[1] == "2018"
    assert thennow.resolve("eox:2019", 0, 0)[:2] == ("satyears", "2019")
    with pytest.raises(ValueError):
        thennow.resolve("google:2020", 0, 0)


def test_pair_picture(home, monkeypatch):
    monkeypatch.setattr(thennow, "surveys_at", lambda lon, lat: [{"layer": "chch-2015", "title": "Christchurch 2015", "year_to": 2015, "gsd": 0.1}])

    def fetch(set_id, z, x, y, t):
        return jpeg((200, 30, 30) if set_id == "aerial" else (30, 30, 200)), "image/jpeg"

    got = thennow.pair(172.6, -43.5, 16, "linz:chch-2015", "eox:2024", fetch=fetch)
    im = np.asarray(Image.open(io.BytesIO(got["jpeg"])))
    assert im.shape == (512 + 30, 512 * 2 + 8, 3)
    assert im[300, 100, 0] > 150 and im[300, 900, 2] > 150  # before on the left, after on the right
    assert got["before"]["label"] == "Christchurch 2015" and got["after"]["set"] == "satyears" and not got["notes"]
    with pytest.raises(RuntimeError, match="LINZ_BASEMAPS_API_KEY"):
        thennow.pair(172.6, -43.5, 16, "linz:chch-2015", "eox:2024", fetch=lambda *a: None)


def test_aerial_tiles_need_key(home, monkeypatch):
    monkeypatch.delenv(tn.LINZ_KEY_ENV, raising=False)
    assert tiles.tile("aerial", 16, 64000, 40000) is None
    with pytest.raises(ValueError, match="LINZ_BASEMAPS_API_KEY"):
        tiles.save({"set": "aerial", "bbox": [172.5, -43.6, 172.6, -43.5], "minzoom": 0, "maxzoom": 15})
    urls = []

    class C:
        def get(self, url):
            urls.append(url)
            return Resp(content=b"RIFFxxxxWEBP", kind="image/webp")
    monkeypatch.setenv(tn.LINZ_KEY_ENV, "k123")
    monkeypatch.setattr(tiles, "_http", lambda: C())
    got = tiles.tile("aerial", 16, 64000, 40000, "christchurch-2023-0.075m")
    assert got == (b"RIFFxxxxWEBP", "image/webp")
    assert urls[-1] == "https://basemaps.linz.govt.nz/v1/tiles/christchurch-2023-0.075m/WebMercatorQuad/16/64000/40000.webp?api=k123"
    tiles.tile("aerial", 16, 64000, 40000, "../../etc")
    assert "/v1/tiles/aerial/" in urls[-1]  # a bad name falls back to the best picture
    # saved copies stop at the setting (15 by default)
    assert tiles.check({"set": "aerial", "bbox": [172.5, -43.6, 172.6, -43.5], "minzoom": 0, "maxzoom": 20})["maxzoom"] == 15


def test_season_and_scene_pick():
    assert thennow.season(2001, -43, True) == "2000-12-01T00:00:00Z/2001-03-31T23:59:59Z"
    assert thennow.season(2001, 45, True) == "2001-06-01T00:00:00Z/2001-09-30T23:59:59Z"
    assert thennow.season(2001, 45, False).startswith("2001-01-01")
    assert tn.landsat_platforms(1990) == ["landsat-5"] and tn.landsat_platforms(2012) == ["landsat-7"]
    assert "landsat-9" in tn.landsat_platforms(2024)
    box = [170.0, -44.1, 170.2, -43.9]
    edge = {"id": "edge", "bbox": [170.1, -45, 171, -43], "properties": {"eo:cloud_cover": 1}}
    whole = {"id": "whole", "bbox": [169, -45, 171, -43], "properties": {"eo:cloud_cover": 8}}
    assert thennow.pick_scene([edge, whole], box)["id"] == "whole"
    assert thennow.pick_scene([edge], box)["id"] == "edge" and thennow.pick_scene([], box) is None
    assert tn.classify_index(200, 100, 100) == "water" and tn.classify_index(100, 200, 100) == "green"
    assert tn.classify_index(100, 120, 160) == "built" and tn.classify_index(100, 140, 100) == "other"


def test_timelapse_runs(home, monkeypatch):
    monkeypatch.setattr(thennow, "_tl_kick", lambda: None)
    m = thennow.timelapse_create({"bbox": [170.10, -44.05, 170.16, -44.00], "name": "Lake test"})
    assert m["state"] == "queued" and m["zoom"] == 12 and m["total"] == date.today().year - 1983
    with pytest.raises(ValueError):
        thennow.timelapse_create({"bbox": [160, -50, 179, -30]})
    meta = thennow._read(thennow._tl_meta_path(m["id"]), {})
    meta["state"] = "running"
    thennow._write(thennow._tl_meta_path(m["id"]), meta)

    def post(url, body):
        y = int(body["datetime"].split("/")[1][:4])  # the season ends in this year
        if y == 1990:
            return Resp(body={"features": []})
        return Resp(body={"features": [{"id": f"LC-{y}", "bbox": [169, -45, 171, -43],
                                        "properties": {"eo:cloud_cover": 3, "datetime": f"{y}-01-15T22:00:00Z", "platform": "landsat-8"}}]})

    def get(url):
        if "expression=" in url:  # the index picture: left half water, right half green
            im = Image.new("RGBA", (256, 256), (100, 200, 100, 255))
            im.paste(Image.new("RGBA", (128, 256), (220, 100, 100, 255)), (0, 0))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return Resp(content=buf.getvalue(), kind="image/png")
        return Resp(content=png((90, 120, 160, 255)), kind="image/png")

    done = thennow.run_timelapse(m["id"], get=get, post=post)
    assert done["state"] == "done" and done["done"] == done["total"]
    years = {y["year"]: y for y in done["years"]}
    assert years[1990]["missing"] and "scene" not in years[1990]
    y = years[2000]
    assert y["scene"] == "LC-2000" and y["water"] > 0 and y["green"] > 0 and y["built"] == 0 and y["seen"] == 1.0
    assert thennow.frame_path(m["id"], 2000) is not None and thennow.frame_path(m["id"], 1990) is None
    assert thennow.timelapse_delete(m["id"]) and thennow.timelapses() == []


def test_aerial_scan(home, monkeypatch):
    monkeypatch.setenv(tn.LINZ_KEY_ENV, "k")
    monkeypatch.setattr(spotting, "vision_models", lambda s=None: {"scan": "fake-vl", "ask": "fake-vl", "models": []})
    monkeypatch.setattr(spotting, "_kick", lambda: None)
    q = lambda *a: []  # noqa: E731
    with pytest.raises(ValueError, match="older survey"):
        spotting.scan_create(q, {"mode": "scan", "picture": "aerial", "bbox": [172.60, -43.54, 172.62, -43.52], "tags": ["new_house"]})
    with pytest.raises(ValueError, match="New Zealand only"):
        spotting.scan_create(q, {"mode": "scan", "picture": "aerial", "bbox": [151.20, -33.90, 151.22, -33.88], "tags": ["pool"]})
    m = spotting.scan_create(q, {"mode": "scan", "picture": "aerial", "bbox": [172.60, -43.54, 172.62, -43.52],
                                 "tags": ["solar_roof", "pool", "new_house"], "layer": "chch-2023", "before": "chch-2015",
                                 "layer_title": "Christchurch 2023", "before_title": "Christchurch 2015"})
    assert m["picture"] == "aerial" and m["total"] >= 4 and all(t[0] == tn.AERIAL_SCAN_ZOOM for t in spotting._meta(m["id"])["todo"])
    meta = spotting._meta(m["id"])
    meta["state"] = "running"
    spotting._write(spotting._meta_path(m["id"]), meta)
    seen = []

    def fetch(set_id, z, x, y, t):
        seen.append((set_id, z, t))
        return jpeg((120, 140, 90)), "image/jpeg"

    calls = []

    def looker(model, pic, prompt, schema, settings):
        calls.append((Image.open(io.BytesIO(pic)).size, prompt, schema))
        return {"counts": {"solar_roof": 3, "pool": 0, "new_house": 2}, "sure": 0.8, "note": "rows of panels"}

    done = spotting.run_scan(m["id"], fetch=fetch, settings={}, looker=looker)
    assert done["state"] == "done"
    assert {s[0] for s in seen} == {"aerial"} and {s[1] for s in seen} == {tn.AERIAL_PICTURE_ZOOM} and {s[2] for s in seen} == {"chch-2023", "chch-2015"}
    size, prompt, schema = calls[0]
    assert size == (512 * 2 + 8, 512)  # older and newer photo side by side
    assert "LEFT is the older one (Christchurch 2015)" in prompt and set(schema["properties"]["counts"]["required"]) == {"solar_roof", "pool", "new_house"}
    items = spotting.found(m["id"])
    assert {i["tag"] for i in items} == {"solar_roof", "new_house"} and items[0]["count"] in (3, 2)
    lay = spotting.layer(0.5)
    assert any(p["label"] == "Rooftop solar: 3" for p in lay)
    towns = spotting.towns(lambda sql, p: [{"name": "Christchurch", "lat": -43.53, "lon": 172.63, "population": 380000}], m["id"])
    assert towns[0]["town"] == "Christchurch" and towns[0]["counts"]["solar_roof"] == 3 * m["total"]
    rates = {r["tag"]: r for r in spotting.hit_rates()}
    assert rates["solar_roof"]["found"] == m["total"]


def test_routes(home, monkeypatch):
    from worldmodel_api.main import app

    rows = [{"slug": "x_2020_0.1m", "layer": "x-2020-0.1m", "title": "X (2020)", "region": "x", "year_from": 2020, "year_to": 2020,
             "gsd": 0.1, "kind": "urban", "draft": False, "bbox": [172, -44, 173, -43], "area": square(172, -44, 173, -43)}]
    thennow._write(thennow._index_file(), {"built": date.today().isoformat(), "surveys": rows})
    c = TestClient(app)
    d = c.get("/api/v1/thennow/dates", params={"lon": 172.5, "lat": -43.5}).json()
    assert d["linz"][0]["layer"] == "x-2020-0.1m" and d["linz_key"] in (True, False)
    monkeypatch.setattr(spotting, "_fetch", lambda *a: (jpeg((10, 200, 10)), "image/jpeg"))
    r = c.get("/api/v1/thennow/pair", params={"lon": 172.5, "lat": -43.5, "a": "linz:x-2020-0.1m", "b": "esri:now"})
    assert r.status_code == 200 and r.json()["picture"].startswith("data:image/jpeg") and r.json()["after"]["t"] == "x-2020-0.1m"
    assert c.get("/api/v1/thennow/pair.jpg", params={"lon": 172.5, "lat": -43.5, "a": "eox:2018", "b": "eox:2024"}).headers["content-type"] == "image/jpeg"
    assert c.get("/api/v1/thennow/pair", params={"lon": 172.5, "lat": -43.5, "a": "nope:1", "b": "eox:2024"}).status_code == 422
    assert c.get("/api/v1/thennow/wayback", params={"lon": 1, "lat": 1}).status_code == 200
    assert c.get("/api/v1/thennow/timelapse").json()["timelapses"] == []
    assert c.post("/api/v1/thennow/timelapse", json={"bbox": [1, 2]}).status_code == 422
    assert c.delete("/api/v1/thennow/timelapse/nothing-here").status_code == 404
    terms = c.get("/api/v1/spot/terms").json()
    assert any(t["id"] == "solar_roof" for t in terms["aerial_tags"])
