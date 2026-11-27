"""House prices by region: the New Zealand Ministry's sales workbook and the ABS dwelling tables, on small
fixtures made here in the same layouts, then one build."""

from datetime import date

import duckdb
import pytest
from worldmodel_contract import catalogue
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.house_prices import month_of
from worldmodel_data.vintage_store import VintageStore

SALES_HEAD = ["stat_type", "area_type", "area", "period", "residential_sales", "lower_quartile_sale_price",
              "median_sale_price", "upper_quartile_sale_price"]
HPI_HEAD = ["stat_type", "area_type", "area", "period", "residential_sales_used_for_HPI_all_quartiles",
            "residential_sales_used_for_HPI_quartile_1", "residential_sales_used_for_HPI_quartile_2",
            "residential_sales_used_for_HPI_quartile_3", "residential_sales_used_for_HPI_quartile_4",
            "house_price_index_all_quartiles"]


def serial(y, m):
    return (date(y, m, 1) - date(1899, 12, 30)).days


def nz_workbook(path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Instructions"
    wb.active["B2"] = "Property and Sales Statistics data extract"
    sales = wb.create_sheet("Sales")
    sales.append(SALES_HEAD)
    places = [("National", "New Zealand", 700000), ("Region", "Auckland", 950000),
              ("Region", "Manawatu-Wanganui", 480000), ("Territorial Authority", "Far North District", 500000),
              ("Region", "Area Outside Region", 300000)]
    for kind, area, price in places:
        for y in (2024, 2025):
            for m in range(1, 13):
                p = price + (y - 2024) * 12000 + m * 1000
                sales.append(["Monthly", kind, area, serial(y, m), 100, p - 100000, p, p + 200000])
                sales.append(["3-Month rolling", kind, area, serial(y, m), 300, p - 100000, p - 500, p + 200000])
                sales.append(["12-Month rolling", kind, area, serial(y, m), 1200, p - 100000, p - 6000, p + 200000])
    comp = wb.create_sheet("Sales composition")  # not read: its median would otherwise double up
    comp.append(["stat_type", "area_type", "area", "period", "median_sale_price"])
    comp.append(["Monthly", "National", "New Zealand", serial(2025, 12), 1])
    hpi = wb.create_sheet("House Price Index")
    hpi.append(HPI_HEAD)
    for kind, area, base in (("National", "New Zealand", 1300), ("Region", "Auckland", 1200)):
        for y in (2024, 2025):
            for m in range(1, 13):
                hpi.append(["Monthly", kind, area, serial(y, m), 5000, 1, 1, 1, 1, base + m])
                hpi.append(["3-Month rolling", kind, area, serial(y, m), 15000, 1, 1, 1, 1, base + m - 1])
    hpi.append(["Monthly", "Region", "Auckland", serial(2026, 1), 1, 1, None, None, None, 0])  # too few sales: 0
    wb.save(path)


ST = ("DATAFLOW,MEASURE: Measure,REGION: Region,FREQ: Frequency,TIME_PERIOD: Time Period,OBS_VALUE,"
      "UNIT_MEASURE: Unit of Measure,UNIT_MULT: Unit of Multiplier,OBS_STATUS: Observation Status,OBS_COMMENT: Observation Comment\r\n"
      + "".join(f"ABS:RES_DWELL_ST(1.0.0),5: Mean price of residential dwellings,{r},Q: Quarterly,2024-Q{q},{v + q},"
                f"AUD: Australian Dollars,3: Thousands,,\r\n"
                for r, v in (("1: New South Wales", 1200.0), ("AUS: Australia", 1000.0)) for q in range(1, 5))
      + "ABS:RES_DWELL_ST(1.0.0),5: Mean price of residential dwellings,1: New South Wales,Q: Quarterly,2025-Q1,1248.3,AUD: Australian Dollars,3: Thousands,,\r\n"
      + "ABS:RES_DWELL_ST(1.0.0),1: Value of dwelling stock: Owned by all sectors,8: Australian Capital Territory,Q: Quarterly,2025-Q1,201000.5,AUD: Australian Dollars,6: Millions,,\r\n"
      + "ABS:RES_DWELL_ST(1.0.0),4: Number of residential dwellings,6: Tasmania,Q: Quarterly,2025-Q1,267.1,NUM: Number,3: Thousands,,\r\n")
RD = ("DATAFLOW,MEASURE: Measure,REGION: Region,FREQ: Frequency,TIME_PERIOD: Time Period,OBS_VALUE,"
      "UNIT_MEASURE: Unit of Measure,UNIT_MULT: Unit of Multiplier,OBS_STATUS: Observation Status,OBS_COMMENT: Observation Comment\r\n"
      "ABS:RES_DWELL(1.0.0),3: Median Price of Established House Transfers,1GSYD: Greater Sydney,Q: Quarterly,2025-Q1,1650,AUD: Australian Dollars,3: Thousands,r: revised,\r\n"
      "ABS:RES_DWELL(1.0.0),3: Median Price of Established House Transfers,1RNSW: Rest of NSW,Q: Quarterly,2025-Q1,764.5,AUD: Australian Dollars,3: Thousands,r: revised,\r\n"
      "ABS:RES_DWELL(1.0.0),4: Median Price of Attached Dwelling Transfers,8ACTE: Australian Capital Territory,Q: Quarterly,2025-Q1,590,AUD: Australian Dollars,3: Thousands,,\r\n"
      "ABS:RES_DWELL(1.0.0),1: Number of Established House Transfers,3RQLD: Rest of Qld,Q: Quarterly,2025-Q1,11476,NUM: Number,0: Units,r: revised,\r\n")


def test_months():
    assert month_of(29221) == date(1980, 1, 1) and month_of(46235) == date(2026, 8, 1)
    assert month_of("2026-08") == date(2026, 8, 1) and month_of(None) is None


def test_australian_states_in_catalogue():
    ents, subs = catalogue.entities(), {s["entity_id"]: s for s in catalogue.subdivisions()}
    states = sorted(k for k, s in subs.items() if s["parent_id"] == "AUS")
    assert states == ["AU-ACT", "AU-NSW", "AU-NT", "AU-QLD", "AU-SA", "AU-TAS", "AU-VIC", "AU-WA"]
    assert ents["AU-NSW"].short_name == "New South Wales" and ents["AU-NSW"].type == "subnational"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("houses")
    home = Paths(tmp / "var")
    store = VintageStore(home)
    nz = tmp / "nz"
    nz.mkdir()
    nz_workbook(nz / "Property-and-Sales-data-download-August-2026.xlsx")
    CONNECTORS["nz_property_sales"]().ingest(store, nz)
    au = tmp / "au"
    au.mkdir()
    (au / "RES_DWELL_ST.csv").write_text(ST, encoding="utf-8")
    (au / "RES_DWELL.csv").write_text(RD, encoding="utf-8")
    CONNECTORS["abs_dwellings"]().ingest(store, au)
    return duckdb.connect(str(build(home).path), read_only=True)


def val(con, ind, ent, period, freq="A"):
    r = con.execute("SELECT value FROM series WHERE indicator_id = ? AND entity_id = ? AND period_start = ? AND freq = ?",
                    [ind, ent, period, freq]).fetchone()
    return r[0] if r else None


def test_nz_sales(con):
    # the calendar year is the 12-month rolling figure at December
    assert val(con, "nzhouse_median_price", "NZL", date(2025, 1, 1)) == 700000 + 12000 + 12000 - 6000
    assert val(con, "nzhouse_median_price", "NZ-AUK", date(2024, 1, 1)) == 950000 + 12000 - 6000
    assert val(con, "nzhouse_median_price", "NZ-MWT", date(2024, 1, 1)) == 480000 + 12000 - 6000  # "Manawatu-Wanganui"
    assert val(con, "nzhouse_uq_price", "NZL", date(2024, 1, 1)) == 700000 + 12000 + 200000
    assert val(con, "nzhouse_sales", "NZ-AUK", date(2025, 1, 1)) == 1200
    # months: 3-month rolling prices, monthly sales counts
    assert val(con, "nzhouse_median_price_m", "NZ-AUK", date(2025, 3, 1), "M") == 950000 + 12000 + 3000 - 500
    assert val(con, "nzhouse_sales_m", "NZL", date(2024, 7, 1), "M") == 100
    # district and outside-region rows have no entity and are left out; the composition sheet is not read
    assert con.execute("SELECT count(DISTINCT entity_id) FROM series WHERE source_id = 'nz_property_sales'").fetchone()[0] == 3
    assert val(con, "nzhouse_median_price_m", "NZL", date(2025, 12, 1), "M") == 700000 + 12000 + 12000 - 500


def test_nz_hpi(con):
    assert val(con, "nzhouse_hpi", "NZL", date(2024, 1, 1)) == pytest.approx(1300 + 6.5)
    assert val(con, "nzhouse_hpi_m", "NZ-AUK", date(2025, 6, 1), "M") == 1200 + 5
    assert val(con, "nzhouse_hpi", "NZ-AUK", date(2026, 1, 1)) is None  # one month of 0 is no year


def test_au_dwellings(con):
    assert val(con, "aureg_mean_dwelling_price", "AU-NSW", date(2024, 1, 1)) == pytest.approx(1000 * 1202.5)
    assert val(con, "aureg_mean_dwelling_price", "AU-NSW", date(2025, 1, 1)) is None  # one quarter is not a year
    assert val(con, "aureg_mean_dwelling_price_q", "AU-NSW", date(2025, 1, 1), "Q") == pytest.approx(1248300)
    assert val(con, "aureg_mean_dwelling_price_q", "AUS", date(2024, 10, 1), "Q") == pytest.approx(1004000)
    assert val(con, "aureg_dwelling_stock_value_q", "AU-ACT", date(2025, 1, 1), "Q") == pytest.approx(201.0005)
    assert val(con, "aureg_dwellings_q", "AU-TAS", date(2025, 1, 1), "Q") == pytest.approx(267100)
    assert val(con, "aureg_house_median_capital_q", "AU-NSW", date(2025, 1, 1), "Q") == pytest.approx(1650000)
    assert val(con, "aureg_house_median_rest_q", "AU-NSW", date(2025, 1, 1), "Q") == pytest.approx(764500)
    assert val(con, "aureg_unit_median_capital_q", "AU-ACT", date(2025, 1, 1), "Q") == pytest.approx(590000)
    assert con.execute("SELECT count(*) FROM series WHERE entity_id = 'AU-QLD'").fetchone()[0] == 0  # counts not kept


def test_region_figures_stay_off_menus(con):
    on = con.execute("SELECT count(*) FROM indicators WHERE (indicator_id LIKE 'nzhouse_%' OR indicator_id LIKE 'aureg_%') "
                     "AND default_on").fetchone()[0]
    assert on == 0
