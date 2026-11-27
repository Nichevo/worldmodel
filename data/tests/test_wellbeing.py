"""The Scorecard's own sources (ILOSTAT hours, Global Slavery Index, WID female labour share),
staged from small hand-made fixtures, and the WDI and OWID series it adds."""

from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.owid import CHARTS
from worldmodel_data.connectors.wellbeing import gsi_rows, wid_values
from worldmodel_data.connectors.world_bank_wdi import MAIN
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("ilostat_hours", "walkfree_gsi", "wid_gender")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", *SOURCES):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return duckdb.connect(str(result.path), read_only=True)


def _v(con, ind, ent, year):
    got = con.execute("SELECT value FROM series WHERE indicator_id = ? AND entity_id = ? AND year(period_start) = ?",
                      [ind, ent, year]).fetchall()
    return got[0][0] if got else None


def test_hours(con):
    assert _v(con, "weekly_hours_worked", "NZL", 2023) == pytest.approx(33.1)
    assert _v(con, "weekly_hours_worked_women", "NZL", 2023) == pytest.approx(29.6)
    assert _v(con, "weekly_hours_worked", "USA", 2023) == pytest.approx(36.4)


def test_slavery_year_is_the_estimate_year(con):
    assert _v(con, "modern_slavery_per_1000", "NZL", 2021) == pytest.approx(1.6)
    assert _v(con, "modern_slavery_per_1000", "IND", 2021) == pytest.approx(8.0)
    assert _v(con, "slavery_government_response", "AUS", 2021) == pytest.approx(67)


def test_wid_wide_download_as_percent(con):
    assert _v(con, "female_labour_income_share", "NZL", 2022) == pytest.approx(38.4)
    assert _v(con, "female_labour_income_share", "USA", 2021) == pytest.approx(39.8)


def test_readers_on_other_shapes():
    long = [["Country", "Variable", "Percentile", "Year", "Value"], ["New Zealand", "x", "p0p100", "2020", "0.37"]]
    assert wid_values(long) == [("NZL", 2020, 0.37)]
    assert gsi_rows([["Country", "Prevalence per 1000"], ["New Zealand", 1.6]]) == {"NZL": {"modern_slavery_per_1000": 1.6}}
    assert gsi_rows([["Nothing", "here"]]) == {}


def test_scorecard_series_are_fetched():
    for ind in ("basic_drinking_water", "basic_sanitation", "safe_sanitation", "clean_cooking_access", "nurses_per_1000",
                "air_pollution_death_rate_who"):
        assert ind in MAIN
    ids = {c[2] for c in CHARTS}
    assert {"cardio_death_rate_ghe", "diabetes_death_rate_ghe", "communicable_ncd_death_rate", "whr_happiness"} <= ids
