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
    assert len(trees) == 4  # three in Auckland, one in Wellington (NZTM), one row without a place left out
    props = [json.loads(p) for _, p in trees]
    assert [p["council"] for p in props].count("auckland") == 3
    assert {p.get("planted") for p in props if p["council"] == "auckland"} == {2000, 2010, None}
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
