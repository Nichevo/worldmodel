"""House prices and household debt, migration in and out, education and turnout sources, and map layers."""

from pathlib import Path

import json

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "bis", "oecd", "dallas_fed_ihpd", "imf_gdd", "un_ims", "unhcr", "wittgenstein", "undp_hdr",
           "idea_turnout", "plates_bird", "gem_faults", "gvp_volcanoes", "usgs_earthquakes")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, year, breakdown=""):
    r = con.execute("""SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ?
        AND breakdown = ? AND variant = 'central'""", [entity, indicator, f"{year}-01-01", breakdown]).fetchone()
    return r and r[0]


def test_house_prices_from_each_source(con):
    # BIS: yearly mean of the quarters, from the GitHub copy and from the API's CSV (Switzerland).
    assert 150 < value(con, "NZL", "bis_house_price_nominal", 2021) < 250
    assert value(con, "CHE", "bis_house_price_nominal", 2010) == pytest.approx(100, abs=3)
    assert value(con, "NZL", "bis_house_price_real", 2021) > 100
    assert value(con, "AUS", "bis_household_credit_gdp", 2010) == pytest.approx(55 + 60 * 15.625 / 30, abs=1)
    # OECD: yearly rows only; every measure; household debt to income.
    assert value(con, "NZL", "oecd_house_price_nominal", 2015) == pytest.approx(100)
    assert value(con, "GBR", "oecd_price_to_income_vs_avg", 2015) == pytest.approx(100 / 0.9, rel=1e-3)
    assert value(con, "DEU", "oecd_household_debt_income", 2000) > 50
    # Dallas Fed: four sheets, country names mapped (UK, US), aggregates left out, ratio worked out.
    hpi, pdi = value(con, "USA", "dfed_house_price_nominal", 2020), value(con, "USA", "dfed_income_nominal", 2020)
    assert value(con, "USA", "dfed_price_to_income", 2020) == pytest.approx(100 * hpi / pdi)
    assert value(con, "GBR", "dfed_house_price_real", 2010) > 0
    assert value(con, "NZL", "dfed_house_price_nominal", 2024)  # the latest year's quarters so far
    assert not con.execute("SELECT count(*) FROM series WHERE source_id = 'dallas_fed_ihpd' AND entity_id NOT IN "
                           "('NZL', 'AUS', 'GBR', 'USA', 'DEU') AND NOT is_aggregate").fetchone()[0]
    assert value(con, "NZL", "imf_household_debt_gdp", 2020) > 60


def test_shared_names_name_their_source(con):
    names = dict(con.execute("SELECT indicator_id, name FROM indicators WHERE indicator_id IN "
                             "('bis_house_price_nominal', 'oecd_house_price_nominal', 'dfed_house_price_nominal', "
                             "'bis_household_credit_gdp', 'imf_household_debt_gdp')").fetchall())
    assert names["bis_house_price_nominal"] == "House prices (nominal) (BIS)"
    assert names["dfed_house_price_nominal"] == "House prices (nominal) (Dallas Fed IHPD)"
    assert names["imf_household_debt_gdp"].endswith("(IMF GDD)")


def test_migrants_in_and_out(con):
    # Immigrants in New Zealand, emigrants from it, and who came from where (the UN's 2020 edition).
    into = value(con, "NZL", "migrant_stock", 2020)
    out = value(con, "NZL", "emigrant_stock", 2020)
    assert 1_000_000 < into < 1_500_000 and 600_000 < out < 1_000_000
    gbr_in_nzl = value(con, "NZL", "migrant_stock_by_origin", 2020, "origin=GBR")
    assert gbr_in_nzl > 150_000
    nzl_in_aus = value(con, "AUS", "migrant_stock_by_origin", 2020, "origin=NZL")
    assert nzl_in_aus > 400_000
    # By-origin values are not added up for regions.
    assert not con.execute("SELECT count(*) FROM series WHERE indicator_id = 'migrant_stock_by_origin' "
                           "AND is_aggregate").fetchone()[0]


def test_refugees(con):
    assert value(con, "SYR", "refugees_from", 2020) > 5_000_000
    assert value(con, "DEU", "refugees_hosted", 2020) > 1_000_000
    assert value(con, "DEU", "refugees_by_origin", 2020, "origin=SYR") > 400_000
    assert value(con, "SYR", "idps", 2020) > 5_000_000


def test_education(con):
    # Wittgenstein: history and projections, women and men; shares of each level.
    assert 12 < value(con, "NZL", "wic_mys", 2020) < 14
    status = con.execute("""SELECT status FROM series WHERE entity_id = 'NZL' AND indicator_id = 'wic_mys'
        AND period_start = DATE '2050-01-01'""").fetchone()[0]
    assert status == "P"
    assert value(con, "NZL", "wic_mys_female", 1950) and value(con, "IND", "wic_mys", 1950) < 3
    levels = [value(con, "NZL", f"wic_edu_{x}", 2030) for x in ("none", "incomplete_primary", "primary",
              "lower_secondary", "upper_secondary", "short_post_secondary", "bachelor", "master")]
    assert sum(levels) == pytest.approx(100, abs=1.5)
    # UNDP: countries only, years from the column names, a file that is not UTF-8.
    assert value(con, "NZL", "hdi", 2023) == pytest.approx(0.939, abs=0.001)
    assert value(con, "NZL", "hdr_mean_years_schooling_female", 2000)
    assert "gnipc" not in {r[0] for r in con.execute("SELECT indicator_id FROM indicators").fetchall()}


def test_turnout(con):
    assert value(con, "NZL", "turnout_parliamentary", 2023) == pytest.approx(78.2)
    assert value(con, "GBR", "vap_turnout_parliamentary", 2024) == pytest.approx(54.12)
    assert value(con, "USA", "turnout_presidential", 2020) == pytest.approx(66.59)
    assert value(con, "NZL", "registered_voters", 2020) == 3_549_580
    # EU Parliament elections are left out; a blank turnout gives no value.
    assert value(con, "GBR", "turnout_parliamentary", 2019) == pytest.approx(67.55)
    assert value(con, "USA", "turnout_parliamentary", 2022) is None


def test_map_layers(con):
    layers = {r[0]: r for r in con.execute(
        "SELECT layer_id, kind, feature_count, geojson, source_id FROM layers").fetchall()}
    assert set(layers) == {"plate_boundaries", "active_faults", "volcanoes", "earthquakes"}
    plates = json.loads(layers["plate_boundaries"][3])
    assert plates["type"] == "FeatureCollection" and len(plates["features"]) == layers["plate_boundaries"][2] == 12
    assert plates["features"][0]["properties"]["name"].startswith("Plate boundary")
    faults = json.loads(layers["active_faults"][3])["features"]
    assert all(len(p) == 2 and p[0] == round(p[0], 3) for f in faults for p in f["geometry"]["coordinates"])
    assert any(f["properties"].get("slip") for f in faults)
    volcano = {f["properties"]["name"]: f for f in json.loads(layers["volcanoes"][3])["features"]}
    assert volcano["Ruapehu"]["properties"]["last"] == 2007 and volcano["Ruapehu"]["geometry"]["type"] == "Point"
    assert volcano["Etna"]["properties"]["url"].endswith("vn=211060")
    quakes = {f["properties"]["mag"]: f["properties"] for f in json.loads(layers["earthquakes"][3])["features"]}
    assert quakes[7.8]["date"] == "2016-11-13" and quakes[7.8]["depth"] == 15 and quakes[7.8]["tsunami"] == 1
    assert layers["earthquakes"][1] == "point" and layers["earthquakes"][4] == "usgs_earthquakes"
