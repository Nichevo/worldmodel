"""City stress sources: Numbeo crime and health care pages, the WHO air quality file and
the TomTom ranking, matched to cities by the build."""

from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.cities import _tt_place, tomtom_minutes, who_aq_columns
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "geonames", "numbeo", "who_aqdb", "tomtom_traffic")
AUCKLAND, WELLINGTON, LONDON, NYC, TOKYO = "gn2193733", "gn2179537", "gn2643743", "gn5128581", "gn1850147"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def got(con, cid, ind, year):
    r = con.execute("SELECT value FROM city_series WHERE city_id = ? AND indicator_id = ? AND year(period_start) = ?",
                    [cid, ind, year]).fetchone()
    return r and r[0]


def test_numbeo_crime_and_health_care(con):
    assert got(con, AUCKLAND, "numbeo_crime", 2025) == pytest.approx(46.0)
    assert got(con, TOKYO, "numbeo_safety", 2025) == pytest.approx(77.0)
    assert got(con, LONDON, "numbeo_health_care", 2025) == pytest.approx(70.1)
    assert got(con, NYC, "numbeo_health_care_exp", 2025) == pytest.approx(108.0)
    assert got(con, AUCKLAND, "numbeo_cost_of_living", 2025) == pytest.approx(66.2)  # the older page still loads


def test_who_air_quality_from_the_data_sheet(con):
    # Two Auckland measurements in 2022 are averaged; "/NZL" is dropped from the name.
    assert got(con, AUCKLAND, "who_pm25_city", 2022) == pytest.approx(6.0)
    assert got(con, AUCKLAND, "who_pm25_city", 2021) == pytest.approx(6.0)
    assert got(con, WELLINGTON, "who_no2_city", 2022) == pytest.approx(12.0)
    assert got(con, NYC, "who_pm10_city", 2022) is None
    assert got(con, LONDON, "who_pm25_city", 2022) == pytest.approx(9.6)


def test_tomtom_page_and_pasted_table(con):
    assert got(con, LONDON, "tomtom_travel_10km", 2025) == pytest.approx(37.33)
    assert got(con, WELLINGTON, "tomtom_congestion", 2025) == 33
    assert got(con, AUCKLAND, "tomtom_travel_10km", 2024) == pytest.approx(22.5)
    assert got(con, TOKYO, "tomtom_congestion", 2024) == 40


def test_parsing_helpers():
    assert tomtom_minutes("27 min 40 s") == pytest.approx(27.67) and tomtom_minutes("15") == 15
    assert _tt_place("Mexico City Mexico", None) == ("Mexico City", "MEX")
    assert _tt_place("Port Moresby Papua New Guinea", None) == ("Port Moresby", "PNG")
    cols = who_aq_columns(["who_region", "iso3", "country_name", "city", "year", "pm10_concentration",
                           "pm25_concentration", "no2_concentration", "pm25_tempcov", "latitude", "longitude"])
    assert cols["pm25"] == 6 and cols["pm10"] == 5 and cols["lat"] == 9
    assert who_aq_columns(["a", "b"]) == {}
