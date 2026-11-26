"""Land, cities and trees (connectors/land.py and FAOSTAT's land use), on small synthetic
fixtures shaped like the real files."""

import json
from pathlib import Path

import duckdb
import pytest
from worldmodel_contract.land import LCDB_CLASSES, lcdb_level, nz_region
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.land import (
    hyde_txt,
    mollweide_to_lonlat,
    nzf_figures,
    nztm_to_lonlat,
)
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "geonames", "faostat", "hyde_land", "ghsl_ucdb", "gfw_treecover", "council_trees", "nz_lcdb", "nz_forestry")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def val(con, ent, ind, year, breakdown=""):
    r = con.execute("SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND year(period_start) = ? AND breakdown = ?",
                    [ent, ind, year, breakdown]).fetchone()
    return r and r[0]


def test_projections_and_helpers():
    lon, lat = nztm_to_lonlat(1756000, 5920000)
    assert lon == pytest.approx(174.75, abs=0.01) and lat == pytest.approx(-36.853, abs=0.01)  # central Auckland
    assert mollweide_to_lonlat(0, 0) == (0.0, 0.0)
    lon, lat = mollweide_to_lonlat(13889000, -4362000)
    assert -40 < lat < -30 and 150 < lon < 180
    assert hyde_txt("region 1700AD 10000BC\n554 1.5 0\n") == [("554", 1700, 1.5), ("554", -10000, 0.0)]
    assert nz_region("Manawatū-Whanganui Region") == "NZ-MWT" and nz_region("Auckland Region") == "NZ-AUK"
    assert lcdb_level(71, 1) == "Forest" and lcdb_level(71, 2) == "Exotic forest" and len(LCDB_CLASSES) >= 33
    got = nzf_figures([["Year", "New planting (ha)", "Net stocked area (ha)"], ["2022", "40000", "1760000"]], "nefd_harvest")
    assert sorted(got) == [("nz_new_planting_ha", None, 2022, 40000.0), ("nz_plantation_ha", None, 2022, 1760000.0)]


def test_faostat_land_use_and_animals(built):
    _, con = built
    assert val(con, "NZL", "land_forest_ha", 2020) == 9_900_000
    assert val(con, "NZL", "land_forest_pct", 2020) == pytest.approx(9900 / 26300 * 100)
    assert val(con, "NZL", "land_pasture_ha", 2000) == 12_500_000
    assert val(con, "NZL", "livestock_sheep_head", 2023) == 24_000_000
    assert val(con, "NZL", "livestock_dairy_cows", 2023) == 4_800_000
    assert val(con, "NZL", "sa_kiwifruit", 2023) == 13_500
    assert val(con, "NZL", "fert_n_per_ha", 2022) == pytest.approx(666.7)
    assert val(con, "NZL", "sp_milk", 2023) == 21_500_000  # production still read as before


def test_faostat_land_cover_shares(built):
    _, con = built
    total = 9000 + 30 + 14000 + 400 + 100 + 800 + 100 + 370  # coastal water left out; MODIS rows ignored
    assert val(con, "NZL", "lc_trees_pct", 1992) == pytest.approx(9030 / total * 100)
    assert val(con, "NZL", "lc_built_pct", 2022) == pytest.approx(140 / (9200 + 30 + 13600 + 450 + 140 + 810 + 90 + 380) * 100)
    assert con.execute("SELECT count(*) FROM indicators WHERE indicator_id LIKE 'lc_%_pct'").fetchone()[0] == 7


def test_hyde(built):
    _, con = built
    assert val(con, "NZL", "hyde_cropland_ha", 1700) == 1000
    assert val(con, "NZL", "hyde_cropland_ha", 1600) is None  # kept from 1700
    assert val(con, "NZL", "hyde_grazing_ha", 1800) == 200 * 100  # km² to ha


def test_ghsl_cities_and_outlines(built):
    _, con = built
    rows = {r[0]: (r[1], json.loads(r[2])) for r in con.execute(
        "SELECT feature_id, name, props FROM geo_features WHERE layer_id = 'urban_centres'").fetchall()}
    assert set(rows) == {"1", "2"}  # the centre in no known country is left out
    name, props = rows["1"]
    assert name == "Auckland" and props["pop"]["1975"] == 700000 and props["growth"] == pytest.approx(128.6, abs=0.1)
    w, s, e, n = con.execute("SELECT west, south, east, north FROM geo_features WHERE feature_id = '1'").fetchone()
    assert 174.5 < w < 174.7 and 174.8 < e < 175.0 and -37.1 < s < -36.9  # Mollweide turned back into degrees
    auckland = con.execute("SELECT city_id FROM cities WHERE name = 'Auckland'").fetchone()[0]
    got = dict(con.execute("SELECT year(period_start), value FROM city_series WHERE city_id = ? AND indicator_id = 'ghsl_population'",
                           [auckland]).fetchall())
    assert got[2025] == 1_600_000 and got[2030] == 1_700_000
    assert con.execute("SELECT status FROM city_series WHERE city_id = ? AND indicator_id = 'ghsl_population' "
                       "AND year(period_start) = 2030", [auckland]).fetchone()[0] == "P"
    dens = con.execute("SELECT value FROM city_series WHERE city_id = ? AND indicator_id = 'ghsl_density' AND year(period_start) = 2025",
                       [auckland]).fetchone()[0]
    assert dens == pytest.approx(1_600_000 / 330)


def test_tree_cover(built):
    _, con = built
    assert val(con, "NZL", "gfw_tree_cover_loss_ha", 2023) == 52000  # the 30% canopy row
    assert val(con, "NZL", "gfw_tree_cover_ha", 2010) == 10_100_000
    assert val(con, "BRA", "gfw_tree_cover_pct", 2000) == pytest.approx(520 / 851 * 100)
    trees = con.execute("SELECT name, props FROM geo_features WHERE layer_id = 'street_trees' ORDER BY feature_id").fetchall()
    # three in Auckland, one in Wellington (NZTM; a row without a place left out), one living tree in
    # Christchurch (Esri JSON; a removed one left out), two in New York, one in Melbourne
    assert len(trees) == 8
    props = [json.loads(p) for _, p in trees]
    assert [p["council"] for p in props].count("auckland") == 3
    assert {p.get("planted") for p in props if p["council"] == "auckland"} == {2000, 2010, None}
    assert [p["council"] for p in props].count("newyork") == 2
    assert next(p for p in props if p["council"] == "christchurch")["species"] == "Platanus orientalis"
    m = next(p for p in props if p["council"] == "melbourne")
    assert m["planted"] == 2008 and m["common"] == "Peppercorn Tree"
    countries = dict(con.execute("""SELECT json_extract_string(props, '$.council'), any_value(countries) FROM geo_features
                                    WHERE layer_id = 'street_trees' GROUP BY 1""").fetchall())
    assert countries["newyork"] == "USA" and countries["melbourne"] == "AUS" and countries["auckland"] == "NZL"
    w = next(p for p in props if p["council"] == "wellington")
    assert w["planted"] == 1995 and w["species"] == "Sophora microphylla"


def test_nz_land_cover(built):
    _, con = built
    assert val(con, "NZL", "nz_lcdb_ha", 2018, "class=71") == pytest.approx(100)
    assert val(con, "NZL", "nz_lcdb_ha", 2012, "class=40") == pytest.approx(200)
    assert val(con, "NZ-AUK", "nz_lcdb_ha", 2018, "class=69") == pytest.approx(400)
    assert val(con, "NZ-AUK", "nz_lcdb_ha", 2018, "class=1") is None  # the Canterbury polygon is outside the Auckland boundary
    assert val(con, "NZL", "nz_lcdb_change_ha", 2018, "change=40>1") == pytest.approx(100)
    changes = con.execute("SELECT props FROM geo_features WHERE layer_id = 'nz_land_change'").fetchall()
    assert len(changes) == 2


def test_nz_forestry(built):
    _, con = built
    assert val(con, "NZL", "nz_new_planting_ha", 2022) == 40000
    assert val(con, "NZL", "nz_harvest_area_ha", 2021) == 47000
    assert val(con, "NZL", "nz_plantation_ha", 2022) == 1_760_000
    assert val(con, "NZL", "nz_ets_forest_ha", 2022) == 410000


def test_council_trees_download(tmp_path, monkeypatch):
    """Each council read its own way; one that fails is skipped, the rest are kept."""
    import httpx
    from worldmodel_contract import land as contract_land
    from worldmodel_data.connectors import land as land_mod

    monkeypatch.setattr(land_mod, "_settings", lambda: {"council_trees_overseas": True})
    monkeypatch.setattr(land_mod, "COUNCILS", {k: contract_land.COUNCILS[k] for k in ("auckland", "wellington", "christchurch", "newyork", "melbourne", "london")})
    seen = []

    def handler(request: httpx.Request):
        url = str(request.url)
        seen.append(url)
        if "aucklandcouncil" in url:
            return httpx.Response(200, json={"features": [
                {"properties": {"title": "Notable trees", "url": "https://x.arcgis.com/Notable/FeatureServer"}},
                {"properties": {"title": "Auckland Council Trees", "url": "https://x.arcgis.com/Trees/FeatureServer"}}]})
        if "x.arcgis.com/Trees/FeatureServer/0/query" in url:
            off = int(request.url.params["resultOffset"])
            feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [174.7, -36.8]}, "properties": {"OBJECTID": off + i}}
                     for i in range(3 if off == 0 else 0)]
            return httpx.Response(200, json={"type": "FeatureCollection", "features": feats, "properties": {"exceededTransferLimit": off == 0}})
        if "gis.wcc.govt.nz" in url:
            if request.url.params["f"] == "geojson":
                return httpx.Response(200, json={"error": {"code": 400, "message": "Invalid format"}})
            return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1}, "geometry": {"x": 174.78, "y": -41.29}}]})
        if "gis.ccc.govt.nz" in url:
            return httpx.Response(503)
        if "cityofnewyork" in url:
            assert request.url.params["$where"] == "status='Alive'"
            off = int(request.url.params["$offset"])
            return httpx.Response(200, json=[{"tree_id": "1", "spc_latin": "Acer", "latitude": "40.7", "longitude": "-73.9"}] if off == 0 else [])
        if "melbourne" in url:
            return httpx.Response(200, content=b"com_id,latitude,longitude\n1,-37.8,144.9\n2,-37.81,144.91\n")
        return httpx.Response(404)

    c = land_mod.CouncilTrees(client=httpx.Client(transport=httpx.MockTransport(handler)))
    c.pause_seconds = 0
    got = c.download(tmp_path, "2026-11")
    assert got == "auckland,melbourne,newyork,wellington"
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["auckland_000.geojson", "melbourne_000.csv", "newyork_000.csv", "wellington_000.json"]
    assert not any("Notable" in u for u in seen)
    assert len(land_mod.tree_records(tmp_path / "wellington_000.json")) == 1
    assert not any("london" in u for u in seen)  # saved by hand only


def test_ghsl_reads_2026_file_with_byte_order_marks(tmp_path):
    """The V1-1 file of late 2026 starts every column name and text value with a byte-order
    mark, and its exposure theme has POP/BUS columns that are not the city's totals."""
    import shutil
    import sqlite3

    from worldmodel_data.connectors.land import ghsl_centres

    p = tmp_path / "ucdb.gpkg"
    shutil.copy(FIXTURES / "ghsl_ucdb" / "GHS_UCDB_GLOBE_R2024A_V1_1.gpkg", p)
    con = sqlite3.connect(p)
    for (t,) in con.execute("SELECT table_name FROM gpkg_contents").fetchall():
        for (c,) in [(r[1],) for r in con.execute(f'PRAGMA table_info("{t}")').fetchall()]:
            if c not in ("fid", "geom"):
                con.execute(f'ALTER TABLE "{t}" RENAME COLUMN "{c}" TO "﻿{c}"')
        for c in ("GC_UCN_MAI_2025", "GC_CNT_GAD_2025", "GC_CNT_ISO_2025"):
            if c in [r[1].lstrip("﻿") for r in con.execute(f'PRAGMA table_info("{t}")')]:
                con.execute(f'UPDATE "{t}" SET "﻿{c}" = char(65279) || "﻿{c}"')
    con.execute('CREATE TABLE "GHS_UCDB_THEME_EXPOSURE_GLOBE_R2024A" (fid INTEGER, "﻿ID_UC_G0" REAL, "﻿EX_010_POP_1975" REAL)')
    con.execute('INSERT INTO "GHS_UCDB_THEME_EXPOSURE_GLOBE_R2024A" VALUES (1, 1, 5)')
    con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier) VALUES "
                "('GHS_UCDB_THEME_EXPOSURE_GLOBE_R2024A', 'attributes', 'x')")
    con.commit()
    con.close()
    auckland = next(c for c in ghsl_centres(p) if c["id"] == "1")
    assert auckland["name"] == "Auckland" and auckland["pop"][1975] == 700000


def test_gfw_download_tries_the_yearly_folder_first(tmp_path, monkeypatch):
    """The old file address answers 404; since 2026 the file is at .../download/<year>/global.xlsx."""
    from worldmodel_data.connectors.base import ConnectorError
    from worldmodel_data.connectors.land import GFWTreeCover

    c = GFWTreeCover()
    asked = []

    def get(url, dest, **kw):
        asked.append(url)
        if len(asked) < 2:  # this year's folder is not there yet
            raise ConnectorError(f"GET {url} returned HTTP 404")
        dest.write_bytes(b"x")

    monkeypatch.setattr(c, "get", get)
    assert c.download(tmp_path, "2026").endswith("/global.xlsx") and "/download/20" in asked[1]
    assert (tmp_path / "global_country_stats.xlsx").exists() and "/download/" in asked[0]
