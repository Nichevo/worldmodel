"""The long view: Cliopatria borders, long-run series, events far back (Wikidata, NOAA)."""

import json
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.history import simplify, wd_year
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "cliopatria", "owid_longrun", "wikidata_history", "noaa_hazel")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def test_wikidata_years_bc_have_no_year_zero():
    assert wd_year("-0215-08-02T00:00:00Z") == (-216, 8, 2)  # Cannae, 216 BC
    assert wd_year("+1346-00-00T00:00:00Z") == (1346, None, None)
    assert wd_year("0000-01-01T00:00:00Z")[0] == -1
    assert wd_year(None) == (None, None, None)


def test_simplify_keeps_shape_and_drops_specks():
    square = [[0, 0], [0.001, 5], [0, 10], [10, 10], [10, 0], [0, 0]]
    speck = [[50, 50], [50.001, 50], [50.001, 50.001], [50, 50]]
    out = simplify({"type": "MultiPolygon", "coordinates": [[square], [speck]]})
    assert out["type"] == "Polygon" and out["coordinates"][0] == [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
    assert simplify({"type": "Polygon", "coordinates": [speck]}) is None


def test_polities_with_regions_and_composites(built):
    _, con = built
    rows = con.execute("SELECT name, from_year, to_year, composite, member_of, region, geojson FROM polities").fetchall()
    by = {(r[0], r[1]): r for r in rows}
    ming = next(r for r in rows if r[0] == "Ming Dynasty")
    assert ming[5] == "east_asia" and json.loads(ming[6])["type"] in ("Polygon", "MultiPolygon")
    rome = next(r for r in rows if r[0] == "Roman Empire" and r[1] <= 117 <= r[2])
    assert rome[5] in ("europe", "mena")
    sumer = next(r for r in rows if r[0] == "Sumerian City-States")
    assert sumer[1] == -3400 and sumer[5] == "mena"
    brit = next(r for r in rows if r[0] == "(British Empire)")
    assert brit[3] is True
    raj = next(r for r in rows if r[0] == "British Raj")
    assert raj[4] == "(British Empire)" and raj[5] == "south_asia" and raj[3] is False
    assert len(by) == len(rows)


def test_long_series_by_entity_with_bc_years(built):
    _, con = built
    got = dict(((e, y), v) for e, y, v in con.execute(
        "SELECT entity_id, year, value FROM long_series WHERE series_id = 'population'").fetchall())
    assert got[("world", -10000)] == 4432180 and got[("CHN", 1)] == 59600000
    assert ("world", 2050) not in got  # projections left out
    assert not any(e is None for e, _ in got)  # OWID's own regions are not kept
    gdp = con.execute("SELECT value FROM long_series WHERE series_id = 'gdp_per_capita' AND entity_id = 'GBR' AND year = 1820").fetchone()
    assert gdp[0] == 3306


def test_history_events(built):
    _, con = built
    ev = {r[0]: r for r in con.execute(
        "SELECT title, kind, year, end_year, deaths, lat, entity_id, region, links, size, size_unit FROM history_events").fetchall()}
    cannae = ev["Battle of Cannae"]
    assert cannae[1] == "battle" and cannae[2] == -216 and cannae[4] == 70000 and cannae[7] == "europe" and cannae[8] == 60
    assert ev["Battle of Waterloo"][6] == "BEL" and ev["Battle of Waterloo"][5] == pytest.approx(50.68)
    assert ev["Black Death"][2:4] == (1346, 1353) and ev["Black Death"][1] == "epidemic"
    assert "Q999" not in ev  # no English name
    quake = ev["Earthquake: New Zealand: Wairarapa"]
    assert quake[9] == 8.2 and quake[10] == "magnitude" and quake[4] == 5 and quake[7] == "pacific"
    assert ev["Eruption of Vesuvius"][2] == 79 and ev["Eruption of Vesuvius"][9] == 5
    assert any(t.startswith("Earthquake: Jordan") and r[2] == -2150 for t, r in ev.items())


def test_build_check_mentions_long_history(built):
    _, con = built
    detail = con.execute("SELECT detail FROM build_checks WHERE check_id = 'history:loaded'").fetchone()[0]
    assert "border shapes" in detail


def test_things_begun_take_the_earliest_date(built):
    _, con = built
    ev = {r[0]: r for r in con.execute(
        "SELECT title, kind, year, lat, entity_id, links, url FROM history_events WHERE kind IN ('built', 'city', 'religion', 'writing')").fetchall()}
    assert ev["Great Pyramid of Giza"][1:3] == ("built", -2560) and ev["Great Pyramid of Giza"][4] == "EGY"
    assert ev["Stonehenge"][2] == -3001  # two dates in Wikidata (3000 BC and a rebuilding): the earliest
    assert ev["Angkor Wat"][2] == 802 and ev["Kyoto"][1:3] == ("city", 794)
    assert ev["Islam"][1] == "religion" and ev["Islam"][3] == pytest.approx(23.5036)  # placed where it began
    assert ev["Cuneiform"][1] == "writing" and ev["Cuneiform"][3] is None  # no place: listed, not on the map
    assert ev["Hagia Sophia"][6] == "https://en.wikipedia.org/wiki/Hagia_Sophia"


def test_rulers_with_reigns_and_no_consorts(built):
    _, con = built
    got = {(r[0], r[1]): r for r in con.execute(
        "SELECT name, over_qid, over_name, post, from_year, to_year, links FROM history_rulers").fetchall()}
    aug = got[("Augustus", "Q1747689")]
    assert aug[2:6] == ("Ancient Rome", "Roman emperor", -27, 14)
    assert ("Theodosius I", "Q1747689") in got and ("Theodosius I", "Q12544") in got  # one row per post
    assert ("Hürrem Sultan", "Q12560") not in got and not any("consort" in (r[3] or "") for r in got.values())
    assert got[("Open-ended ruler", "Q1747689")][5] is None


def test_a_cut_off_query_result_is_skipped(built):
    _, con = built
    # begun_heritage.json in the fixtures ends in a Java error, as when the service runs out of time
    assert con.execute("SELECT count(*) FROM history_events WHERE kind = 'built'").fetchone()[0] == 7


def test_charts_for_the_inventions_page(built):
    _, con = built
    got = {(e, s, y): v for e, s, y, v in con.execute(
        "SELECT entity_id, series_id, year, value FROM long_series WHERE series_id NOT IN ('population', 'gdp_per_capita')").fetchall()}
    assert got[("USA", "us_electric_power", 1950)] == 94 and got[("USA", "us_household_refrigerator", 1931)] == 8
    assert got[("world", "energy_coal", 1800)] == 97 and got[("world", "energy_traditional_biomass", 2020)] == 11000
    assert got[("NZL", "vaccine_mcv1", 1990)] == 90 and ("NZL", "vaccine_dtpcv3", 1990) not in got
    assert got[("GBR", "child_mortality", 1841)] == 25.11 and got[("world", "child_mortality", 1800)] == 42.8
    assert not any(k[1].startswith("energy_") and k[0] != "world" for k in got)  # OWID's regions left out


def test_inventions_from_wikidata(built):
    _, con = built
    ev = {r[0]: r for r in con.execute("SELECT title, year, entity_id, links, url FROM history_events WHERE kind = 'invention'").fetchall()}
    assert ev["zipper"][1] == 1851  # two dates: the earliest
    assert ev["emoji"][2] == "JPN" and ev["zipper"][4] == "https://en.wikipedia.org/wiki/Zipper"
