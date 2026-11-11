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
