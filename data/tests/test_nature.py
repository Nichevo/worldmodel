"""Climate zones, pollution and nature sources (connectors/nature.py), on fixtures."""

import json
import zlib
from pathlib import Path

import duckdb
import numpy as np
import pytest

from worldmodel_contract import catalogue
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.nature import berkeley_years, pest_present, sdg_rows, trend, wahis_rows, zone_shares
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "koppen_beck", "berkeley_earth", "psmsl", "un_sdg", "nd_gain", "griis", "iucn_redlist",
           "eppo_pests", "wahis_outbreaks", "wdpa")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    CONNECTORS["nature_curated"]().ingest(store)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def _vals(con, ind, ent, variant="central", breakdown=""):
    return {r[0]: r[1] for r in con.execute(
        "SELECT year(period_start), value FROM series WHERE indicator_id = ? AND entity_id = ? AND variant = ? AND breakdown = ?",
        [ind, ent, variant, breakdown]).fetchall()}


def test_zone_shares_weight_cells_by_area():
    zones = np.array([[1, 2], [1, 1]], dtype=np.uint8)
    countries = np.array([[1, 1], [1, 0]], dtype=np.uint16)
    s = zone_shares(zones, countries, 1)
    assert s[1, 1] == pytest.approx(200 / 3, rel=1e-6) and s[1, 2] == pytest.approx(100 / 3, rel=1e-6)


def test_climate_zones_by_country_and_path(built):
    _, con = built
    temperate = _vals(con, "climzone_c", "NZL")
    assert temperate[2006] == pytest.approx(100, abs=0.01) and temperate[2085] == pytest.approx(100, abs=0.01)
    tropical = _vals(con, "climzone_a", "NZL", "high")
    assert tropical[2085] > 20  # SSP5-8.5 in the fixture turns northern New Zealand tropical
    assert _vals(con, "climzone_b", "AUS")[2006] == pytest.approx(100, abs=0.01)
    cfa = _vals(con, "climate_zone_share", "NZL", "central", "zone=Cfa")
    assert 2085 in cfa and 2006 not in cfa
    st = con.execute("SELECT DISTINCT status FROM series WHERE indicator_id = 'climzone_c' AND year(period_start) = 2085").fetchall()
    assert st == [("P",)]
    grids = con.execute("SELECT period, scenario, width, height, grid FROM zone_grids ORDER BY 1, 2").fetchall()
    assert ("1991-2020", "historical") in [(g[0], g[1]) for g in grids] and len(grids) == 5
    g = grids[0]
    arr = np.frombuffer(zlib.decompress(g[4]), dtype=np.uint8).reshape(g[3], g[2])
    assert arr[0, 0] == 29 and arr[90 + 37, 180 + 172] in (15, 14)


def test_berkeley_earth_years():
    years, base = berkeley_years((FIXTURES / "berkeley_earth" / "NZL-TAVG-Trend.txt").read_text())
    assert base == 10.59 and years[2022] == pytest.approx(0.5) and 2024 not in years


def test_berkeley_and_sdg_and_gain(built):
    _, con = built
    assert _vals(con, "be_temp_mean", "NZL")[2023] == pytest.approx(11.69, abs=0.001)
    assert _vals(con, "wastewater_treated_share", "NZL")[2020] == 60.5
    assert _vals(con, "red_list_index", "NZL")[2000] == pytest.approx(0.6)
    assert _vals(con, "nd_gain", "NZL")[2022] == pytest.approx(70.2) and 2022 not in _vals(con, "nd_gain", "AUS")
    assert _vals(con, "nd_gain_readiness", "NZL")[2022] == pytest.approx(0.72)


def test_sdg_prefers_totals():
    got = sdg_rows("X", [{"geoAreaCode": "554", "timePeriodStart": 2020, "value": "5", "dimensions": {"Sex": "FEMALE"}},
                         {"geoAreaCode": "554", "timePeriodStart": 2020, "value": "7", "dimensions": {"Sex": "BOTHSEX"}}])
    assert got == [("554", 2020, 7.0)]


def test_tide_gauges_layer(built):
    _, con = built
    gj = json.loads(con.execute("SELECT geojson FROM layers WHERE layer_id = 'tide_gauges'").fetchone()[0])
    assert len(gj["features"]) == 1  # Wellington has only ten years in the fixture
    p = gj["features"][0]["properties"]
    assert p["name"] == "Auckland Ii" and p["trend"] == pytest.approx(2.0) and p["years"] == 40
    assert trend([(2000, 1.0), (2001, 3.0)]) == pytest.approx(2.0)


def test_species_pests_and_outbreaks(built):
    _, con = built
    assert _vals(con, "introduced_species", "NZL")[2023] == 3260
    y = con.execute("SELECT max(year(period_start)) FROM series WHERE indicator_id = 'iucn_threatened'").fetchone()[0]
    assert _vals(con, "iucn_threatened", "NZL")[y] == 3  # the kiwi's older assessment is not counted again
    assert _vals(con, "iucn_ex", "NZL")[y] == 1
    names = {r[0]: r[1] for r in con.execute("SELECT scientific_name, category FROM species_status WHERE entity_id = 'NZL'").fetchall()}
    assert names == {"Strigops habroptila": "CR", "Heteralocha acutirostris": "EX"}
    pests = con.execute("SELECT pest_code, entity_id, present FROM pest_presence ORDER BY 1, 2").fetchall()
    assert ("HALYHA", "NZL", False) in pests and ("DACUTR", "NZL", True) in pests
    assert _vals(con, "watched_pests_present", "USA")[y] == 1 and _vals(con, "watched_pests_present", "NZL")[y] == 1
    assert pest_present("Transient, actionable") and not pest_present("Absent, pest eradicated")
    assert _vals(con, "animal_disease_outbreaks", "USA")[2024] == 15


def test_wahis_needs_country_and_disease():
    rows = wahis_rows([["Report"], ["Country", "Disease", "Year"], ["New Zealand", "Mycoplasma bovis", "2018"]])
    assert rows == [("NZL", 2018, "Mycoplasma bovis", 1.0)]


def test_protected_areas(built):
    _, con = built
    got = {r[0]: r for r in con.execute("SELECT name, entity_id, marine, area_km2, year, geojson FROM protected_areas").fetchall()}
    assert set(got) == {"Abel Tasman National Park", "Small Reserve", "Great Barrier Reef"}  # all of New Zealand's, big ones elsewhere
    assert got["Great Barrier Reef"][1] == "AUS" and got["Great Barrier Reef"][2] == "2"
    assert json.loads(got["Abel Tasman National Park"][5])["type"] == "Polygon"


def test_curated_nature_events(built):
    _, con = built
    kinds = dict(con.execute("SELECT kind, count(*) FROM events WHERE source_id = 'nature_curated' GROUP BY 1").fetchall())
    assert set(kinds) == {"animal_disease", "pest", "pollution"}
    smoke = con.execute("SELECT entity_id FROM events WHERE title LIKE 'Australian bushfire smoke%' ORDER BY 1").fetchall()
    assert smoke == [("AUS",), ("NZL",)]
    assert all(p["code"].isupper() for p in catalogue.nature()["pests"])
