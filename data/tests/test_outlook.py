"""Leading indicators, quarterly GDP growth, the US yield gap and GDPNow, on small fixtures made in the test."""

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.outlook import period_start
from worldmodel_data.vintage_store import VintageStore

CLI = """STRUCTURE,STRUCTURE_ID,ACTION,REF_AREA,FREQ,MEASURE,UNIT_MEASURE,ACTIVITY,ADJUSTMENT,TRANSFORMATION,TIME_HORIZ,METHODOLOGY,TIME_PERIOD,OBS_VALUE
DATAFLOW,OECD.SDD.STES:DSD_STES@DF_CLI(4.1),I,NZL,M,LI,IX,_Z,AA,IX,_Z,H,2026-07,99.6
DATAFLOW,OECD.SDD.STES:DSD_STES@DF_CLI(4.1),I,NZL,M,LI,IX,_Z,AA,IX,_Z,H,2026-08,99.8
DATAFLOW,OECD.SDD.STES:DSD_STES@DF_CLI(4.1),I,USA,M,LI,IX,_Z,AA,IX,_Z,H,2026-08,100.4
DATAFLOW,OECD.SDD.STES:DSD_STES@DF_CLI(4.1),I,G20,M,LI,IX,_Z,AA,IX,_Z,H,2026-08,100.1
DATAFLOW,OECD.SDD.STES:DSD_STES@DF_CLI(4.1),I,USA,M,LI,IX,_Z,NOR,IX,_Z,H,2026-08,101.9
"""

QNA = """STRUCTURE,STRUCTURE_ID,ACTION,FREQ,ADJUSTMENT,REF_AREA,SECTOR,COUNTERPART_SECTOR,TRANSACTION,INSTR_ASSET,ACTIVITY,EXPENDITURE,UNIT_MEASURE,PRICE_BASE,TRANSFORMATION,TABLE_IDENTIFIER,TIME_PERIOD,OBS_VALUE
DATAFLOW,X,I,Q,Y,USA,S1,S1,B1GQ,_Z,_Z,_Z,PC,LR,G1,T0102,2026-Q1,0.3
DATAFLOW,X,I,Q,Y,USA,S1,S1,B1GQ,_Z,_Z,_Z,PC,LR,G1,T0102,2026-Q2,0.6
DATAFLOW,X,I,Q,Y,NZL,S1,S1,B1GQ,_Z,_Z,_Z,XDC,LR,N,T0102,2026-Q1,100.0
DATAFLOW,X,I,Q,Y,NZL,S1,S1,B1GQ,_Z,_Z,_Z,XDC,LR,N,T0102,2026-Q2,99.5
DATAFLOW,X,I,Q,Y,NZL,S1,S1,B1GQ,_Z,_Z,_Z,XDC,V,N,T0102,2026-Q2,140.0
"""


def test_periods():
    assert str(period_start("2026-Q3")) == "2026-07-01" and str(period_start("2026-05")) == "2026-05-01"
    assert period_start("2026") is None


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("outlook")
    (tmp / "oecd").mkdir()
    (tmp / "oecd" / "cli.csv").write_text(CLI, encoding="utf-8")
    (tmp / "oecd" / "gdp_q.csv").write_text(QNA, encoding="utf-8")
    (tmp / "fred").mkdir()
    (tmp / "fred" / "T10Y3M.csv").write_text("observation_date,T10Y3M\n2026-10-01,0.40\n2026-10-02,.\n2026-10-05,0.60\n2026-11-02,0.7\n")
    (tmp / "fred" / "GDPNOW.csv").write_text("observation_date,GDPNOW\n2026-07-01,2.1\n2026-10-01,1.4\n")
    home = Paths(tmp / "var")
    store = VintageStore(home)
    CONNECTORS["oecd_cli"]().ingest(store, tmp / "oecd")
    CONNECTORS["fred_cycle"]().ingest(store, tmp / "fred")
    return duckdb.connect(str(build(home).path), read_only=True)


def vals(con, ind, ent):
    return con.execute("SELECT strftime(period_start, '%Y-%m'), freq, value FROM series WHERE indicator_id = ? AND entity_id = ? "
                       "ORDER BY period_start", [ind, ent]).fetchall()


def test_cli_and_gdp(con):
    assert vals(con, "oecd_cli", "NZL") == [("2026-07", "M", 99.6), ("2026-08", "M", 99.8)]
    assert vals(con, "oecd_cli", "USA") == [("2026-08", "M", 100.4)]  # the not-adjusted copy is left out
    assert vals(con, "gdp_growth_q", "USA") == [("2026-01", "Q", 0.3), ("2026-04", "Q", 0.6)]
    assert vals(con, "gdp_growth_q", "NZL") == [("2026-04", "Q", -0.5)]  # worked out from volumes


def test_fred(con):
    assert vals(con, "us_term_spread", "USA") == [("2026-10", "M", 0.5), ("2026-11", "M", 0.7)]
    assert vals(con, "us_gdpnow", "USA")[-1] == ("2026-10", "Q", 1.4)
