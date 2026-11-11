"""Sectors: trade by product and country pair (BACI), production (USGS, World Mining Data,
FAOSTAT), commodity prices (Pink Sheet) and electric cars (IEA). All from small sample files."""

from pathlib import Path

import duckdb
import pytest

from worldmodel_contract import catalogue
from worldmodel_contract import sectors as sec
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.sectors import to_tonnes
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("baci", "usgs_mcs", "wmd", "faostat", "wb_pinksheet", "iea_ev")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("sectors") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi") + SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, period, breakdown="", source=None):
    sql = ("SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ? "
           "AND breakdown = ? AND variant = 'central'")
    params = [entity, indicator, period, breakdown]
    if source:
        sql += " AND source_id = ?"
        params.append(source)
    r = con.execute(sql, params).fetchone()
    return r[0] if r else None


def test_sector_file_is_valid_and_codes_map_to_stages():
    assert catalogue.validate() == []
    assert len(sec.sectors()) >= 39
    assert sec.hs_stage("260600") == "bauxite"
    assert sec.hs_stage("854231") == "chips"  # four-digit prefix
    assert sec.hs_stage("760110") == "aluminium"
    assert sec.hs_stage("010121") is None
    assert sec.sector("semiconductors")["stages"][1]["id"] == "chips"


def test_concentration():
    c = sec.concentration([50, 30, 20])
    assert c == {"top3": 100.0, "hhi": 3800, "n": 3}
    assert sec.concentration([0, None])["hhi"] is None


def test_baci_totals_routes_and_taiwan(con):
    assert value(con, "AUS", "sx_bauxite", "2021-01-01") == 600_000_000  # thousand US$ to US$
    assert value(con, "AUS", "sx_bauxite", "2021-01-01", "partner=CHN") == 500_000_000
    assert value(con, "AUS", "sxq_bauxite", "2021-01-01") == 12_000_000
    assert value(con, "CHN", "sm_bauxite", "2022-01-01") == 600_000_000
    assert value(con, "TWN", "sx_chips", "2022-01-01") == 2_500_000_000  # "Other Asia, nes" is Taiwan
    # a route under US$ 1 million counts in the total but is not kept on its own
    assert value(con, "NZL", "sx_aluminium", "2021-01-01") == 800_500_000
    assert value(con, "NZL", "sx_aluminium", "2021-01-01", "partner=AUS") is None
    # years before Settings > Sectors "trade kept from" (2005) are left out
    assert value(con, "AUS", "sx_bauxite", "2004-01-01") is None


def test_baci_chapters_for_the_by_country_view(con):
    assert value(con, "NZL", "tgx_04", "2021-01-01") == 3_000_000_000
    assert value(con, "NZL", "tgx_04", "2022-01-01", "partner=CHN") == 3_500_000_000
    assert value(con, "NZL", "tgx_01", "2021-01-01") == 2_000_000  # not in any sector, still in its chapter
    assert value(con, "CHN", "tgm_85", "2022-01-01") == 3_400_000_000
    names = {r[0]: r[1] for r in con.execute("SELECT indicator_id, name FROM indicators WHERE indicator_id IN ('tgx_04', 'sx_chips')").fetchall()}
    assert "Dairy" in names["tgx_04"] and "chips" in names["sx_chips"]


def test_usgs_production_reserves_and_units(con):
    assert value(con, "AUS", "sp_bauxite", "2024-01-01", source="usgs_mcs") == 100_000_000
    assert value(con, "AUS", "sr_bauxite", "2024-01-01") == 3_500_000_000
    assert value(con, "AUS", "sp_alumina", "2023-01-01", source="usgs_mcs") == 18_000_000
    assert value(con, "NZL", "sp_aluminium", "2023-01-01", source="usgs_mcs") == 330_000
    assert value(con, "AUS", "sp_gold", "2023-01-01", source="usgs_mcs") == 310_000  # kilograms stay kilograms
    assert to_tonnes("thousand metric dry tons") == 1000 and to_tonnes("kilograms") == 0.001


def test_world_mining_data(con):
    assert value(con, "AUS", "sp_bauxite", "2019-01-01", source="wmd") == 105_000_000
    assert value(con, "NZL", "sp_gold", "2023-01-01", source="wmd") == 10_100
    assert value(con, "GIN", "sp_bauxite", "2023-01-01", source="wmd") == 97_000_000


def test_faostat_production_only(con):
    assert value(con, "NZL", "sp_milk", "2023-01-01") == 21_500_000
    assert value(con, "AUS", "sp_wheat", "2023-01-01") == 26_000_000
    assert value(con, "NZL", "sp_urea", "2022-01-01") == 120_000  # production, not agricultural use
    assert value(con, "world", "sp_milk", "2023-01-01") is None  # countries only
    assert value(con, "NZL", "sp_logs", "2023-01-01", source="faostat") == 35_000_000  # forestry in cubic metres
    assert value(con, "NZL", "sp_sawnwood", "2023-01-01", source="faostat") == 4_200_000


def test_pink_sheet_prices(con):
    assert value(con, "world", "price_crude_oil", "2024-02-01") == pytest.approx(80.1)
    assert value(con, "world", "price_aluminium", "1960-01-01") == pytest.approx(511.47)
    assert value(con, "world", "price_urea", "2024-01-01") == 333
    assert value(con, "world", "price_urea", "2024-02-01") is None
    unit, freq = con.execute("SELECT unit, frequency FROM indicators WHERE indicator_id = 'price_gold'").fetchone()
    assert unit == "US$ per troy oz" and freq == "M"


def test_iea_electric_cars(con):
    assert value(con, "NZL", "ev_sales_share", "2023-01-01") == 21
    assert value(con, "NZL", "ev_sales_bev", "2023-01-01") == 19_000  # cars only, not buses
    assert value(con, "world", "ev_sales_share", "2024-01-01") == 22
    assert value(con, "eu", "ev_stock_share", "2024-01-01") == 4.6
    assert value(con, "CHN", "ev_sales_share", "2030-01-01") is None  # projections left out
    assert value(con, "CHN", "ev_stock_phev", "2024-01-01") == 10_000_000


def test_iea_ev_reads_the_yearly_excel_file(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Notes"
    ws = wb.create_sheet("GEVO_EV_2026")
    ws.append(["region_country", "category", "parameter", "mode", "powertrain", "year", "unit", "value", "Aggregate group"])
    ws.append(["New Zealand", "Historical", "EV sales share", "Cars", "EV", 2025, "percent", 17, "Other"])
    ws.append(["New Zealand", "Historical", "EV sales", "Cars", "BEV", 2025, "Vehicles", 15000, "Other"])
    ws.append(["New Zealand", "Projection-STEPS", "EV sales share", "Cars", "EV", 2030, "percent", 40, "Other"])
    ws.append(["Chile", "Historical", "EV charging points", "EVSE", "Publicly available fast", 2011, "charging points", 1, "Other"])
    folder = tmp_path / "in"
    folder.mkdir()
    wb.save(folder / "EV data by country 2026.xlsx")
    home = Paths(tmp_path / "var")
    manifest, _ = CONNECTORS["iea_ev"]().ingest(VintageStore(home), folder)
    assert manifest.row_count == 2  # the two historical car rows; projections and chargers left out


def test_wdi_main_maps_each_code_once():
    """A code under two names in MAIN goes to the later name only, and the earlier one's rows vanish."""
    from collections import Counter
    from worldmodel_data.connectors.world_bank_wdi import MAIN
    twice = [c for c, n in Counter(c for codes in MAIN.values() for c in codes).items() if n > 1]
    assert twice == []
