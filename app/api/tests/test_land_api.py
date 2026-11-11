"""Land, cities and trees endpoints, against a copy of the sample warehouse with a few land
figures, two urban centres, LCDB classes and changes, and council trees added. City land
cover is worked out from a made-up WorldCover picture."""

import io
import json
import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from worldmodel_api import land, main, tiles
from worldmodel_api.warehouse import SAMPLE, Warehouse

SQUARE = {"type": "Polygon", "coordinates": [[[174.6, -37.0], [174.9, -37.0], [174.9, -36.7], [174.6, -36.7], [174.6, -37.0]]]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.execute("INSERT INTO vintages VALUES ('landtest', 'v1', 'v1', now(), 'x', 0, 'test', true)")
    inds = {"land_forest_ha": "ha", "land_pasture_ha": "ha", "land_area_ha": "ha", "land_agri_ha": "ha", "land_cropland_ha": "ha",
            "hyde_cropland_ha": "ha", "livestock_sheep_head": "head", "sp_sheep_meat": "t", "nz_lcdb_ha": "ha",
            "nz_lcdb_change_ha": "ha", "nzreg_sheep": "head"}
    for i, u in inds.items():
        con.execute("DELETE FROM indicators WHERE indicator_id = ?", [i])
        con.execute("INSERT INTO indicators (indicator_id, name, domain, unit, decimals, frequency) VALUES (?, ?, 'land', ?, 0, 'A')",
                    [i, i.replace("_", " "), u])
        con.execute("DELETE FROM indicator_sources WHERE indicator_id = ?", [i])
        con.execute("INSERT INTO indicator_sources VALUES (?, 'landtest', ?, 1, 0, '')", [i, i])
    obs = []
    for ent, f90, f20 in (("NZL", 7.7e6, 9.9e6), ("AUS", 140e6, 134e6), ("BRA", 590e6, 497e6)):
        obs += [(ent, "land_forest_ha", 1990, f90), (ent, "land_forest_ha", 2020, f20)]
    obs += [("NZL", "land_pasture_ha", 2020, 9.5e6), ("NZL", "livestock_sheep_head", 2020, 26e6), ("NZL", "sp_sheep_meat", 2020, 460000),
            ("NZL", "hyde_cropland_ha", 1700, 1000), ("NZL", "hyde_cropland_ha", 1961, 400000), ("NZ-CAN", "nzreg_sheep", 2020, 5.5e6),
            ("NZ-OTA", "nzreg_sheep", 2020, 5.0e6)]
    for i, v in (("land_area_ha", 13e9), ("land_agri_ha", 4.8e9), ("land_cropland_ha", 1.6e9), ("land_pasture_ha", 3.2e9),
                 ("land_forest_ha", 4.1e9)):
        obs.append(("world", i, 2020, v))
    rows = [(e, i, date(y, 1, 1), "A", "", "central", "landtest", "v1", v, "E") for e, i, y, v in obs]
    rows += [("NZL", "nz_lcdb_ha", date(y, 1, 1), "A", f"class={c}", "central", "landtest", "v1", v, "E")
             for y, c, v in ((2012, 40, 200), (2012, 69, 400), (2018, 71, 100), (2018, 69, 400), (2018, 1, 100))]
    rows += [("NZ-AUK", "nz_lcdb_ha", date(2018, 1, 1), "A", "class=69", "central", "landtest", "v1", 400, "E"),
             ("NZL", "nz_lcdb_change_ha", date(2018, 1, 1), "A", "change=40>71", "central", "landtest", "v1", 100, "E"),
             ("NZL", "nz_lcdb_change_ha", date(2018, 1, 1), "A", "change=40>1", "central", "landtest", "v1", 100, "E")]
    con.executemany("INSERT INTO observations (entity_id, indicator_id, period_start, freq, breakdown, variant, source_id, vintage, value, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    geo = [("urban_centres", "1", "Auckland", 2, {"country": "NZL", "pop": {"1975": 700000, "2025": 1600000}, "built": {"1975": 120, "2025": 330},
                                                    "now": 2025, "first": 1975, "people": 1600000, "growth": 128.6, "lat": -36.85, "lon": 174.75},
            "NZL", SQUARE),
           ("urban_centres", "2", "Sydney", 1, {"country": "AUS", "pop": {"1975": 2.8e6, "2025": 4.9e6}, "built": {"1975": 500, "2025": 1200},
                                                 "now": 2025, "first": 1975, "people": 4.9e6, "growth": 75.0, "lat": -33.85, "lon": 151.0},
            "AUS", {"type": "Polygon", "coordinates": [[[150.8, -34.0], [151.3, -34.0], [151.3, -33.6], [150.8, -33.6], [150.8, -34.0]]]}),
           ("street_trees", "auckland-1", "English oak", 1, {"council": "auckland", "species": "Quercus robur", "common": "English oak", "planted": 2000, "height": 12},
            "NZL", {"type": "Point", "coordinates": [174.76, -36.85]}),
           ("street_trees", "auckland-2", "Pōhutukawa", 1, {"council": "auckland", "species": "Metrosideros excelsa", "common": "Pōhutukawa"},
            "NZL", {"type": "Point", "coordinates": [174.77, -36.86]})]
    for layer, fid, name, rank, props, ctry, g in geo:
        xs = [p[0] for p in (g["coordinates"][0] if g["type"] == "Polygon" else [g["coordinates"]])]
        ys = [p[1] for p in (g["coordinates"][0] if g["type"] == "Polygon" else [g["coordinates"]])]
        con.execute("INSERT INTO geo_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'landtest', 'v1')",
                    [layer, fid, name, rank, json.dumps(props), ctry, min(xs), min(ys), max(xs), max(ys), json.dumps(g)])
    con.close()
    main.warehouse = Warehouse(str(db))
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))


def test_land_overview_ranking_where(client):
    nz = client.get("/api/v1/land", params={"entity": "NZL"}).json()
    assert nz["series"]["land_forest_ha"] == [[1990, 7.7e6], [2020, 9.9e6]] and nz["modelled_before"] == 1961
    assert nz["hyde"] == ["hyde_cropland_ha"]
    r = client.get("/api/v1/land/ranking", params={"indicator": "land_forest_ha", "start": 1990}).json()
    assert [x["entity_id"] for x in r["rows"]][:1] == ["NZL"] and r["rows"][-1]["entity_id"] == "BRA"
    assert client.get("/api/v1/land/ranking", params={"indicator": "pop_total"}).status_code == 422
    w = client.get("/api/v1/land/where").json()
    assert w["year"] == 2020 and w["pasture_ha"] == 3.2e9 and w["habitable_ha"] == pytest.approx(5.1e10 * 0.29 * 0.71)


def test_sector_card(client):
    c = client.get("/api/v1/land/card/sheep").json()
    assert c["land"]["by"]["NZL"] == [[2020, 9.5e6]]
    sheep_per_ha = next(r for r in c["ratios"] if r["label"].startswith("Sheep per hectare"))
    assert sheep_per_ha["by"]["NZL"][0][1] == pytest.approx(26 / 9.5)
    assert [r["e"] for r in c["regions"]["rows"]] == ["NZ-CAN", "NZ-OTA"]
    assert client.get("/api/v1/land/card/semiconductors").status_code == 404


def test_cities_outlines_and_trees(client):
    c = client.get("/api/v1/land/cities", params={"sort": "growth"}).json()
    assert [r["name"] for r in c["rows"]] == ["Auckland", "Sydney"]
    assert c["rows"][0]["density"] == pytest.approx(1_600_000 / 330) and c["rows"][0]["built_growth"] == pytest.approx(175)
    assert client.get("/api/v1/land/cities", params={"country": "AUS"}).json()["total"] == 1
    o = client.get("/api/v1/land/outlines", params={"ids": "2,1"}).json()
    assert [f["properties"]["name"] for f in o["features"]] == ["Sydney", "Auckland"]
    g = client.get("/api/v1/geo/urban_centres", params={"west": 100, "south": -50, "east": 180, "north": 0, "zoom": 4}).json()
    assert {f["properties"]["name"] for f in g["features"]} == {"Auckland", "Sydney"}
    t = client.get("/api/v1/land/trees").json()
    assert t["council"] == "auckland" and t["total"] == 2 and t["planted"] == [{"y": 2000, "n": 1}]
    nz = client.get("/api/v1/land/nz", params={"level": 1}).json()
    assert nz["years"] == [2012, 2018] and nz["cover"]["2018"]["Forest"] == 500
    assert {(f["from"], f["to"]) for f in nz["flows"]} == {("Grassland, sedge and saltmarsh", "Forest"),
                                                            ("Grassland, sedge and saltmarsh", "Artificial surfaces")}
    assert [r["id"] for r in nz["regions"]] == ["NZ-AUK"]


def test_city_cover_from_pictures(client, monkeypatch):
    # Left half tree cover, right half built-up
    img = Image.new("RGB", (256, 256), (250, 0, 0))
    img.paste((0, 100, 0), (0, 0, 128, 256))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    fetched = []
    monkeypatch.setattr(land.tiles, "tile", lambda s, z, x, y, t=None: fetched.append((z, x, y)) or (buf.getvalue(), "image/png"))
    res = land.city_cover_compute(SQUARE, "2021")
    # The square cuts tiles at different places, so the halves are not exactly half
    assert 35 < res["shares"]["10"] < 65 and res["shares"]["10"] + res["shares"]["50"] == pytest.approx(100)
    assert len(fetched) == res["tiles"] == len(list(tiles.tiles_in((174.6, -37.0, 174.9, -36.7), 12)))
    est = land.trees_estimate({"10": 50.0}, 100, SQUARE, 1_000_000)
    assert est["tree_km2"] == 50 and est["trees_per_person"] == pytest.approx(0.75)
    # The background job keeps the result and the ranking shows it
    monkeypatch.setattr(land.threading, "Thread", lambda target, args, **k: type("T", (), {"start": lambda self: target(*args)})())
    client.post("/api/v1/land/cover", json={"ids": ["1"]})
    got = client.get("/api/v1/land/cover").json()
    assert got["rows"][0]["id"] == "1" and got["rows"][0]["trees_estimate"] > 0
    assert client.get("/api/v1/land/cities").json()["rows"][1]["tree_pct"] == res["shares"]["10"]
