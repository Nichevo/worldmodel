from worldmodel_data.connectors.sectors import usgs_rows
from worldmodel_data.connectors.tabular import Rows


def test_usgs_one_value_per_country_year_and_stage():
    """USGS lists iron ore twice per country (usable ore, iron content): only the first row counts."""
    table = [["COMMODITY", "COUNTRY", "TYPE", "UNIT_MEAS", "PROD_2023", "RESERVES_2024"],
             ["Iron ore", "Australia", "Mine production, usable ore", "thousand metric tons", "960000", "58000000"],
             ["Iron ore", "Australia", "Mine production, iron content", "thousand metric tons", "590000", "27000000"]]
    rows, found = Rows(), set()
    usgs_rows(table, rows, found)
    keys = [(r[1], r[2], r[3]) for r in rows.rows]
    assert len(keys) == len(set(keys))
    assert next(r[5] for r in rows.rows if r[2] == "sp_iron_ore") == 960000 * 1000
