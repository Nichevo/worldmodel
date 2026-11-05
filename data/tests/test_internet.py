"""Internet speeds from Ookla's open tiles: tiles summed by country (land, the coast,
islands smaller than a cell, Natural Earth units without an ISO code), quarters carried
as small CSVs, and years as the test-weighted mean of their quarters."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.internet import country_grid, parquet_quarter, sum_tiles
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
HERE = FIXTURES / "ookla_speedtest"


def test_tiles_summed_by_country():
    grid, codes = country_grid(HERE / "ne_50m_admin_0_countries.geojson")
    by = {r["iso3"]: r for r in sum_tiles(HERE / "2024-04-01_performance_fixed_tiles.parquet", grid, codes)}
    assert set(by) == {"NZL", "AUS", "XKX"}  # the mid-Pacific tile belongs to no one
    assert by["NZL"]["tests"] == 45  # Auckland, Christchurch and the tile just off the coast
    assert by["NZL"]["down_mbps"] == pytest.approx(3.5e6 / 45 / 1000)
    assert by["AUS"]["tests"] == 42  # Sydney and the island smaller than a cell
    assert parquet_quarter("2024-04-01_performance_fixed_tiles.parquet") == ("fixed", 2024, 2)


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("internet") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi", "ookla_speedtest"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, period, freq="A"):
    r = con.execute("SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ? AND freq = ? "
                    "AND breakdown = '' AND variant = 'central'", [entity, indicator, period, freq]).fetchone()
    return r[0] if r else None


def test_quarters_and_years(con):
    assert value(con, "NZL", "internet_fixed_down_mbps_q", date(2024, 4, 1), "Q") == pytest.approx(77.778, abs=0.01)
    assert value(con, "NZL", "internet_fixed_down_mbps_q", date(2024, 1, 1), "Q") == pytest.approx(50.0)
    # 2024: Q1 with 100 tests at 50, Q2 with 45 at 77.8
    assert value(con, "NZL", "internet_fixed_down_mbps", date(2024, 1, 1)) == pytest.approx((100 * 50 + 3500) / 145, abs=0.01)
    assert value(con, "NZL", "internet_fixed_tests", date(2024, 1, 1)) == 145
    assert value(con, "NZL", "internet_mobile_down_mbps", date(2023, 1, 1)) == pytest.approx(90.0)
    assert value(con, "XKX", "internet_fixed_latency_ms", date(2024, 1, 1)) == pytest.approx(25.0)
    unit, freq = con.execute("SELECT unit, frequency FROM indicators WHERE indicator_id = 'internet_fixed_down_mbps_q'").fetchone()
    assert unit == "Mbps" and freq == "Q"
