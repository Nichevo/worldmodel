"""Spotting: land change and water tiles read from the pictures, area summaries, the picture of a
place, and area scans run against a stand-in for the local model."""

import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from worldmodel_api import spotting, tiles
from worldmodel_contract import spotting as sp

LC = {name: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (255,) for name, (c, _) in sp.LC10_COLOURS.items()}


def png(colour, size=256, box=None, base=(0, 0, 0, 0)):
    im = Image.new("RGBA", (size, size), base)
    if box is not None:
        im.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), colour), box[:2])
    else:
        im = Image.new("RGBA", (size, size), colour)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def jpeg(colour, size=256):
    buf = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    return tmp_path


def decode(data):
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    return np.asarray(im)


def test_change_kinds():
    assert sp.change_kind("grass", "built") == "built"
    assert sp.change_kind("trees", "crops") == "cleared"
    assert sp.change_kind("trees", "bare") == "bare"
    assert sp.change_kind("grass", "crops") == "crops"
    assert sp.change_kind("crops", "trees") == "trees"
    assert sp.change_kind("grass", "water") == "water_gain" and sp.change_kind("water", "grass") == "water_loss"
    assert sp.change_kind("trees", "trees") is None and sp.change_kind("snow", "water") is None


def test_change_tile_needs_change_to_hold(home):
    # 2017 all rangeland; 2025 the left half built on; 2024 only the top-left quarter built on
    def fetch(set_id, z, x, y, t):
        if t == "2017":
            return png(LC["Rangeland"]), "image/png"
        if t == "2025":
            return png(LC["Built area"], box=(0, 0, 128, 256), base=LC["Rangeland"]), "image/png"
        if t == "2024":
            return png(LC["Built area"], box=(0, 0, 128, 128), base=LC["Rangeland"]), "image/png"
        raise AssertionError(t)

    a = decode(spotting.change_tile("lc10", 10, 5, 5, 2017, 2025, fetch=fetch))
    built = tuple(int(sp.CHANGES[0].colour[i:i + 2], 16) for i in (1, 3, 5))
    assert tuple(a[10, 10][:3]) == built and a[10, 10][3] > 200      # built by 2024 and 2025
    assert a[200, 10][3] == 0                                          # only built in 2025: not yet counted
    assert a[10, 200][3] == 0                                          # never built
    # asking for other kinds only hides it
    a2 = decode(spotting.change_tile("lc10", 10, 5, 5, 2017, 2025, kinds="trees", fetch=fetch))
    assert a2[10, 10][3] == 0


def test_change_tile_drops_specks():
    k0 = np.zeros((20, 20), dtype=np.int32) + sp.KINDS.index("grass")
    k1 = k0.copy()
    k1[5, 5] = sp.KINDS.index("built")            # one pixel alone
    k1[10:14, 10:14] = sp.KINDS.index("built")    # a block
    c = spotting.change_classes(k0, k1)
    assert c[5, 5] == -1 and c[11, 11] == sp.CHANGE_IDS.index("built")


def test_change_tile_saved_and_missing(home, monkeypatch):
    calls = []

    def fetch(set_id, z, x, y, t):
        calls.append(t)
        return (png(LC["Trees"]) if t == "2017" else png(LC["Crops"])), "image/png"

    monkeypatch.setattr(spotting, "_fetch", fetch)
    one = spotting.change_tile("lc10", 9, 1, 1, 2017, 2020)
    assert one and len(calls) == 3
    two = spotting.change_tile("lc10", 9, 1, 1, 2017, 2020)
    assert len(calls) == 3 and decode(two)[0, 0][3] > 200  # read back from the saved copy
    assert spotting.change_tile("lc10", 9, 1, 2, 2017, 2020, fetch=lambda *a: None) is None
    assert spotting.change_tile("lc10", 15, 1, 1, 2017, 2020) is None  # past Esri's closest zoom
    with pytest.raises(ValueError):
        spotting.change_tile("lc10", 9, 1, 1, 2020, 2017)


def test_water_tile():
    gained = tuple(int(sp.WATER_CLASSES[1].colour[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    same = tuple(int(sp.WATER_CLASSES[0].colour[i:i + 2], 16) for i in (1, 3, 5)) + (255,)

    def fetch(set_id, z, x, y, t):
        assert set_id == "water"
        return png(gained, box=(0, 0, 128, 256), base=same), "image/png"

    a = decode(spotting.water_tile(8, 1, 1, "changes", fetch=fetch))
    assert a[10, 10][3] > 200 and a[10, 200][3] == 0
    b = decode(spotting.water_tile(8, 1, 1, "all", fetch=fetch))
    assert b[10, 200][3] > 200


def test_area_summary_box():
    # A box in New Zealand's Canterbury; every square: left half built on since 2017
    def fetch(set_id, z, x, y, t):
        if t == "2017":
            return png(LC["Crops"]), "image/png"
        return png(LC["Built area"], box=(0, 0, 128, 256), base=LC["Crops"]), "image/png"

    req = spotting._norm_summary({"kind": "land", "src": "lc10", "from": 2017, "to": 2025, "bbox": [172.0, -43.8, 172.5, -43.4]})
    res = spotting.area_summary(req, fetch=fetch)
    assert res["ha"]["built"] > 0 and res["ha"]["cleared"] == 0
    box_ha = 0.5 * 111.32 * np.cos(np.radians(43.6)) * 0.4 * 111.32 * 100
    assert 0.3 * box_ha < res["ha"]["built"] < 0.7 * box_ha
    assert res["hot_spots"] and res["hot_spots"][0]["main"] == "built"
    assert res["squares"] <= spotting.DETAIL_TILES["quick"]


def test_summary_country_and_errors(home):
    with pytest.raises(ValueError):
        spotting._norm_summary({"kind": "land", "entity": "XXX"})
    with pytest.raises(ValueError):
        spotting._norm_summary({"kind": "land", "bbox": [10, 0, 5, 1]})
    req = spotting._norm_summary({"kind": "water", "entity": "nzl"})
    assert req["entity"] == "NZL"
    with pytest.raises(RuntimeError):
        spotting.area_summary(req, fetch=lambda *a: None)


def test_picture_centred(monkeypatch):
    # Tiles coloured by their x so the crop's left and right show which tiles it used
    def fetch(set_id, z, x, y, t):
        return jpeg((x % 2 * 200, 50, 50)), "image/jpeg"

    data, info = spotting.picture(174.76, -36.85, 15, fetch=fetch)
    im = Image.open(io.BytesIO(data))
    assert im.size == (512, 512) and 1.5 < info["km"] < 2.5
    assert spotting.picture(174.76, -36.85, 15, fetch=lambda *a: None) is None


def test_country_at():
    assert spotting.country_at(174.76, -36.85)[0] == "NZL"
    assert spotting.country_at(-160.0, -30.0) is None


def test_land_squares_skip_sea():
    g, bounds, _ = spotting._area_shape(None, [174.0, -37.5, 176.0, -36.0])
    sq = spotting._land_tiles(g, bounds, 10)
    assert 0 < len(sq) < tiles.count(bounds, 10, 10)


class FakeModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, model, jpeg_bytes, prompt, schema, settings):
        self.calls.append(prompt)
        return self.answer(prompt) if callable(self.answer) else self.answer


def make_scan(monkeypatch, home, todo, mode="scan", tags=("solar_farm", "airport"), layers=()):
    monkeypatch.setattr(spotting, "vision_models", lambda s=None: {"scan": "fake-vl", "ask": "fake-vl", "models": []})
    monkeypatch.setattr(spotting, "_todo", lambda q, req: todo)
    monkeypatch.setattr(spotting, "_kick", lambda: None)
    return spotting.scan_create(lambda *a: [], {"bbox": [174, -37.5, 176, -36], "mode": mode, "tags": list(tags), "layers": list(layers)})


def land_fetch(set_id, z, x, y, t):
    return jpeg((120, 140, 90)), "image/jpeg"


def test_scan_runs_and_marks(home, monkeypatch):
    m = make_scan(monkeypatch, home, [[13, 8000, 5000], [13, 8001, 5000], [13, 8002, 5000]])
    assert m["state"] == "queued" and m["total"] == 3
    spotting.scan_action(m["id"], "resume")  # nothing to resume: stays queued
    meta = spotting._meta(m["id"])
    meta["state"] = "running"
    spotting._write(spotting._meta_path(m["id"]), meta)
    model = FakeModel({"seen": [{"tag": "solar_farm", "sure": 0.9, "where": "top left", "note": "dark rows"},
                                {"tag": "volcano", "sure": 1, "where": "centre"}]})
    done = spotting.run_scan(m["id"], fetch=land_fetch, settings={}, looker=model)
    assert done["state"] == "done" and done["done"] == 3 and done["found"] == 3
    assert "solar_farm: Solar farm" in model.calls[0] and "volcano" not in model.calls[0]
    items = spotting.found(m["id"])
    assert {i["tag"] for i in items} == {"solar_farm"}
    first = items[0]
    w, s, e, n = tiles.lonlat_box(13, 8000, 5000)
    assert w < first["lon"] < (w + e) / 2 and (s + n) / 2 < first["lat"] < n  # top left of the square
    assert spotting.picture_path(m["id"], "13-8000-5000") is not None
    spotting.mark(m["id"], first["id"], "no")
    spotting.mark(m["id"], items[1]["id"], "yes")
    rates = {r["tag"]: r for r in spotting.hit_rates()}
    assert rates["solar_farm"]["found"] == 3 and rates["solar_farm"]["right_pct"] == 50
    lay = spotting.layer(0.5)
    assert len(lay) == 2 and all(p["tag"] == "solar_farm" for p in lay)  # the one marked wrong is left off
    assert spotting.layer(0.95) and len(spotting.layer(0.95)) == 1     # only the one you marked right
    with pytest.raises(ValueError):
        spotting.mark(m["id"], first["id"], "maybe")


def test_scan_skips_sea_and_pauses(home, monkeypatch):
    m = make_scan(monkeypatch, home, [[13, 8000, 5000], [13, 8001, 5000]])
    meta = spotting._meta(m["id"])
    meta["state"] = "running"
    spotting._write(spotting._meta_path(m["id"]), meta)
    model = FakeModel({"seen": []})
    sea = lambda *a: (jpeg((10, 30, 60)), "image/jpeg")  # noqa: E731
    done = spotting.run_scan(m["id"], fetch=sea, settings={}, looker=model)
    assert done["skipped"] == 2 and not model.calls
    # paused before it starts: nothing is looked at
    m2 = make_scan(monkeypatch, home, [[13, 8000, 5000]])
    spotting.scan_action(m2["id"], "pause")
    out = spotting.run_scan(m2["id"], fetch=land_fetch, settings={}, looker=model)
    assert out["state"] == "paused" and out["done"] == 0
    spotting.recover()
    assert spotting.scan_action(m2["id"], "resume")["state"] == "queued"
    assert spotting.scan_delete(m2["id"]) and not spotting.scan_delete(m2["id"])


def test_scan_stops_after_errors(home, monkeypatch):
    m = make_scan(monkeypatch, home, [[13, 8000 + i, 5000] for i in range(8)])
    meta = spotting._meta(m["id"])
    meta["state"] = "running"
    spotting._write(spotting._meta_path(m["id"]), meta)

    def broken(*a):
        raise RuntimeError("Ollama answered 500: model failed to load")

    out = spotting.run_scan(m["id"], fetch=land_fetch, settings={}, looker=broken)
    assert out["state"] == "error" and out["done"] == 4 and "failed to load" in out["error"]


def test_check_mode(home, monkeypatch):
    todo = [["airports", "a1", "Somewhere Airport", "medium", 174.79, -37.0], ["airports", "a2", "Paddock Field", None, 175.0, -37.2]]
    m = make_scan(monkeypatch, home, todo, mode="check", tags=(), layers=("airports",))
    meta = spotting._meta(m["id"])
    meta["state"] = "running"
    spotting._write(spotting._meta_path(m["id"]), meta)
    model = FakeModel(lambda p: {"looks_like": "no" if "Paddock" in p else "yes", "sure": 0.8, "note": "fields"})
    spotting.run_scan(m["id"], fetch=land_fetch, settings={}, looker=model)
    items = spotting.found(m["id"])
    assert [i["verdict"] for i in items] == ["yes", "no"]
    assert "an airport with at least one runway" in model.calls[0]
    lay = spotting.layer(0.5)
    assert len(lay) == 1 and lay[0]["kind"] == "check" and lay[0]["name"] == "Paddock Field"


def test_json_answers():
    assert spotting._json_answer('<think>hmm</think>{"seen": []}') == {"seen": []}
    assert spotting._json_answer('Here: {"seen": [{"tag": "dam"}]} done')["seen"][0]["tag"] == "dam"
    with pytest.raises(ValueError):
        spotting._json_answer("no idea")


def test_vision_models(monkeypatch):
    from worldmodel_api import ai
    monkeypatch.setattr(ai, "models", lambda s: [{"name": "big-vl", "size": 20e9}, {"name": "text", "size": 5e9}, {"name": "small-vl", "size": 4e9}])
    monkeypatch.setattr(ai, "can_see", lambda name, s, timeout=5: name.endswith("-vl"))
    v = spotting.vision_models({})
    assert v["ask"] == "big-vl" and v["scan"] == "small-vl" and [m["name"] for m in v["models"]] == ["small-vl", "big-vl"]
    v = spotting.vision_models({"spot_scan_model": "big-vl", "spot_ask_model": "gone"})
    assert v["scan"] == "big-vl" and v["ask"] == "big-vl"


def test_routes(home, monkeypatch):
    from worldmodel_api.main import app

    c = TestClient(app)
    t = c.get("/api/v1/spot/terms").json()
    assert {x["id"] for x in t["changes"]} >= {"built", "cleared"} and len(t["water"]) == 10 and "airports" in t["checkable"]
    monkeypatch.setattr(spotting, "_fetch", lambda *a: None)
    r = c.get("/api/v1/spot/change/lc10/3/1/1?from=2017&to=2025")
    assert r.status_code == 200 and r.headers.get("x-tile-missing") == "1"
    assert c.get("/api/v1/spot/change/lc10/3/1/1?from=2025&to=2017").status_code == 422
    assert c.get("/api/v1/spot/scans").json()["scans"] == []
    assert c.post("/api/v1/spot/summary", json={"kind": "land", "entity": "XXX"}).status_code == 422
    assert c.get("/api/v1/spot/here?lon=174.7&lat=-36.8").status_code == 503
    assert c.get("/api/v1/spot/scans/bad id!/found").status_code in (404, 422)
    assert c.get("/api/v1/spot/layer").json() == []


def test_layer_letters_keep_digits():
    from worldmodel_contract import local
    assert local._letters("we8 9 0z8") == "we890z"
