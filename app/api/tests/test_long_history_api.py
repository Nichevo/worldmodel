"""Long history endpoints, against a copy of the sample warehouse (which has the powers'
borders) with a few long-run figures and events added."""

import shutil

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import longhistory, main
from worldmodel_api.warehouse import SAMPLE, Warehouse


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    db = tmp_path / "w.duckdb"
    shutil.copy(SAMPLE, db)
    con = duckdb.connect(str(db))
    con.executemany("INSERT INTO long_series VALUES (?, ?, ?, ?, 'owid_longrun', 'v1')", [
        ("world", "population", -10000, 4.4e6), ("world", "population", 1, 2.3e8), ("world", "population", 2023, 8.09e9),
        *[(c, "population", y, v) for c, vs in {"CHN": (6e7, 1.4e9), "IND": (7e7, 1.43e9), "GBR": (1e6, 6.8e7),
                                                  "USA": (1e6, 3.3e8), "NLD": (2e5, 1.8e7), "FRA": (5e6, 6.8e7)}.items()
          for y, v in ((1, vs[0]), (2020, vs[1]))],
        *[(c, "gdp_per_capita", y, v) for c, vs in {"CHN": (1000, 17000), "IND": (900, 7000), "GBR": (1500, 45000),
                                                      "USA": (1000, 62000), "NLD": (1200, 55000), "FRA": (1100, 44000)}.items()
          for y, v in ((1820, vs[0]), (2020, vs[1]))],
    ])
    con.executemany("INSERT INTO history_events VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL, ?, ?, ?, NULL, NULL, ?, ?, ?, 'v1')", [
        ("wd:Q1", "battle", "Battle of Cannae", -216, 41.3, 16.1, "ITA", "europe", 70000, 60, "https://en.wikipedia.org/wiki/Battle_of_Cannae", "wikidata_history"),
        ("wd:Q2", "epidemic", "Black Death", 1346, 45.0, 30.0, None, "europe", 5e7, 120, "u", "wikidata_history"),
        ("wd:Q3", "battle", "Obscure skirmish", 1400, 45.0, 10.0, None, "europe", None, 3, "u", "wikidata_history"),
        ("wd:Q4", "war", "Imjin War", 1592, 37.5, 127.0, "KOR", "east_asia", None, 40, "u", "wikidata_history"),
    ])
    con.close()
    main.warehouse = Warehouse(str(db))
    main._lh_cache.clear()
    yield TestClient(main.app)
    main.warehouse = Warehouse(str(SAMPLE))
    main._lh_cache.clear()


def test_overview_has_powers_with_peaks(client):
    r = client.get("/api/v1/long").json()
    rome = next(p for p in r["powers"] if p["id"] == "rome")
    assert rome["has_borders"] and rome["peak_year"] >= 100 and rome["peak_km2"] > 4e6
    assert next(p for p in r["powers"] if p["id"] == "eu")["has_borders"] is False
    assert r["dynasties"][0] == "shang" and "ming" in r["dynasties"]
    assert len(r["regions"]) == 8 and r["pacific"]["note"]
    assert r["counts"]["polities"] > 500 and r["counts"]["history_events"] == 4


def test_sizes_and_frames(client):
    s = client.get("/api/v1/long/sizes?powers=ming,britain").json()
    ming = next(x for x in s if x["id"] == "ming")
    assert ming["points"][0][0] == 1375 and max(p[1] for p in ming["points"] if p[1]) > 5e6
    card = client.get("/api/v1/long/power/britain").json()
    assert card["frames"] and card["peak"]["area_km2"] > 2e7  # the composite British Empire wins
    assert card["peak"]["name"] == "(British Empire)" and card["voyages"][0]["id"] == "cook"
    shape = client.get(f"/api/v1/long/shape/{card['peak']['key']}")
    assert shape.status_code == 200 and shape.json()["geometry"]["type"] in ("Polygon", "MultiPolygon")
    exp = client.get("/api/v1/long/power/rome/expansion?most=5").json()
    years = [f["properties"]["from"] for f in exp["features"]]
    assert years == sorted(years, reverse=True) and len(years) <= 6  # oldest last, drawn on top


def test_events_filter_by_links_and_area(client):
    ev = client.get("/api/v1/long/events?start=-500&end=1500").json()
    assert [e["title"] for e in ev] == ["Battle of Cannae", "Black Death"]  # the skirmish has too few articles
    assert ev[0]["when"] == "216 BC"
    card = client.get("/api/v1/long/power/rome").json()
    assert any(e["title"] == "Battle of Cannae" for e in card["events"])
    assert client.get("/api/v1/long/events?bbox=100,20,140,50").json()[0]["title"] == "Imjin War"


def test_world_ruled_and_regions(client):
    w = client.get("/api/v1/long/world?year=1600").json()
    names = {f["properties"]["name"] for f in w["features"]}
    assert "Ming Dynasty" in names and all(not n.startswith("(") for n in names)
    ruled = client.get("/api/v1/long/ruled?step=50").json()
    east = next(r for r in ruled["regions"] if r["id"] == "east_asia")
    assert any(s["name"] == "Ming Dynasty" and s["china"] for s in east["segments"])
    assert ruled["regions"][-1]["id"] == "pacific"


def test_series_factors_and_cycle(client):
    s = client.get("/api/v1/long/series?entities=world&series=population").json()
    assert s[0]["points"][0] == [-10000, 4.4e6] and s[0]["unit"] == "people" and "HYDE" in s[0]["source"]
    f = client.get("/api/v1/long/factors?start=1820&step=50").json()
    out = next(x for x in f["factors"] if x["id"] == "output")
    usa = next(l for l in out["lines"] if l["entity"] == "USA")
    assert 0 < usa["points"][-1][1] < 1
    rc = next(x for x in f["factors"] if x["id"] == "reserve_currency")
    assert next(l for l in rc["lines"] if l["entity"] == "USA")["points"][-1][1] > 0.5
    c = client.get("/api/v1/long/cycle?entities=USA,NZL").json()
    assert len(c["stages"]) == 6 and [x["entity"] for x in c["countries"]] == ["USA", "NZL"]


def test_point_in_shape_and_year_labels():
    sq = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]], [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]]]}
    assert longhistory._inside(sq, 2, 2) and not longhistory._inside(sq, 5, 5) and not longhistory._inside(sq, 12, 2)
    assert longhistory.year_label(-3400) == "3,400 BC" and longhistory.year_label(79) == "AD 79"
    assert longhistory.year_label(1600) == "1600"


def test_wikipedia_for_a_power_uses_its_own_limit(client, monkeypatch):
    calls = []
    monkeypatch.setattr(main.wiki, "fetch_page", lambda eid, target, reason="opened", kind="countries": calls.append((eid, target, kind)) or {
        "title": target["article"], "extract": "x", "images": [], "fetched_at": "2099-01-01T00:00:00+00:00"})
    r = client.get("/api/v1/long/wikipedia/ming").json()
    assert calls == [("long_ming", {"name": "Ming China", "type": "empire", "article": "Ming dynasty"}, "empires")]
    assert r["budget"]["limit"] == 20
    assert client.get("/api/v1/long/wikipedia/nope").status_code == 404


def test_then_and_now_shares(client):
    land = client.get("/api/v1/long/thenandnow?measure=land&powers=britain,rome").json()
    brit = next(l for l in land["lines"] if l["id"] == "britain")
    assert 15 < brit["peak"][1] < 25  # about 29 million km² of 134
    people = client.get("/api/v1/long/thenandnow?measure=people&powers=china,usa").json()
    china = next(l for l in people["lines"] if l["id"] == "china")
    assert china["points"][0] == [1, round(100 * 6e7 / 2.3e8, 2)]


def test_world_without_geometry_then_shapes(client):
    w = client.get("/api/v1/long/world?year=1600&geometry=false").json()
    keys = [f["properties"]["key"] for f in w["features"]]
    assert keys and all(f["geometry"] is None for f in w["features"])
    got = client.post("/api/v1/long/shapes", json={"keys": keys[:2]}).json()
    assert set(got) == set(keys[:2]) and got[keys[0]]["type"] in ("Polygon", "MultiPolygon")
