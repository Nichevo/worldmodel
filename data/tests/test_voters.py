"""Who votes: US Census table A-1 and the NZ Electoral Commission's turnout spreadsheets."""

import time
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.voters import read_nz_turnout, read_us_table
from worldmodel_data.vintage_store import VintageStore

FIX = Path(__file__).parent / "fixtures"


def test_us_table_a1():
    v = read_us_table(FIX / "us_census_voting" / "hst_vote01.xlsx")
    assert v[("us_voted", 2024)] == 59.3 and v[("us_voted_citizens", 2024)] == 65.3
    assert v[("us_voted_age_18_24", 1964)] == 50.9 and v[("us_voted_age_65_plus_female", 2024)] == 71.2
    assert v[("us_registered_hispanic", 2024)] == 42.8 and v[("us_voting_age_population", 1964)] == 110_604_000
    assert ("us_voted_citizens", 1976) not in v  # "N": not available
    assert ("us_voted_asian", 1988) not in v


def test_nz_turnout_file():
    year, v = read_nz_turnout(FIX / "nz_election_turnout" / "2023-General_Election_Turnout_by_Age_Descent.xlsx")
    assert year == 2023 and len(v) == 36
    assert 100 * v["nz_turnout"][0] / v["nz_turnout"][1] == pytest.approx(77.51, abs=0.01)
    assert v["nz_turnout_maori"] == (398770, 567012) and v["nz_turnout_age_70_plus_non_maori"][0] == 469909


def test_voters_build(tmp_path):
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, FIX / "imf_weo")
    CONNECTORS["us_census_voting"]().ingest(store, FIX / "us_census_voting")
    nz = FIX / "nz_election_turnout"
    CONNECTORS["nz_election_turnout"]().ingest(store, nz)
    # A second election's file loaded on its own adds to the first (files are kept).
    other = tmp_path / "2020"
    other.mkdir()
    import shutil
    shutil.copy(nz / "2023-General_Election_Turnout_by_Age_Descent.xlsx", other / "2020-General_Election_Turnout_by_Age.xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(other / "2020-General_Election_Turnout_by_Age.xlsx")
    for ws in wb.worksheets:
        ws["A1"] = ws["A1"].value.replace("2023", "2020")
    wb.save(other / "2020-General_Election_Turnout_by_Age.xlsx")
    time.sleep(1.1)
    CONNECTORS["nz_election_turnout"]().ingest(store, other)
    con = duckdb.connect(str(build(home).path), read_only=True)
    nzv = dict(con.execute("SELECT year(period_start), value FROM series WHERE entity_id = 'NZL' AND indicator_id = 'nz_turnout'").fetchall())
    assert set(nzv) == {2020, 2023} and nzv[2023] == pytest.approx(77.51, abs=0.01)
    us = con.execute("SELECT count(*) FROM series WHERE entity_id = 'USA' AND indicator_id = 'us_voted_age_18_24'").fetchone()[0]
    assert us == 31  # every November election 1964-2024
    on = dict(con.execute("SELECT indicator_id, default_on FROM indicators WHERE indicator_id IN "
                          "('nz_turnout_age_18_24', 'nz_turnout_age_18_24_maori', 'us_voted', 'us_voted_age_18_24_male')").fetchall())
    assert on == {"nz_turnout_age_18_24": True, "nz_turnout_age_18_24_maori": False, "us_voted": True, "us_voted_age_18_24_male": False}
