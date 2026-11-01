"""Version 3 sources: other forecasters (OECD Economic Outlook, World Bank GEP) and
AI use by country (Eurostat, Anthropic Economic Index, Microsoft AI Diffusion)."""

import time
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from worldmodel_contract.queries import forecast_pairs_sql
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.forecasters import edition
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, FIXTURES / "imf_weo")  # gdp_growth needs its usual coverage
    CONNECTORS["oecd_eo"]().ingest(store, FIXTURES / "oecd_eo")
    time.sleep(1.1)  # fetch times are kept to the second; the later edition must be the latest
    CONNECTORS["oecd_eo"]().ingest(store, FIXTURES / "oecd_eo_2")
    for source in ("wb_gep", "eurostat_ai", "anthropic_aei", "ms_ai_diffusion"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, year, source):
    r = con.execute("""SELECT value, status FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ?
        AND source_id = ? AND breakdown = '' AND variant = 'central'""",
                    [entity, indicator, f"{year}-01-01", source]).fetchone()
    return r


def test_edition_names():
    assert edition(datetime(2026, 7, 1), (6, 12)) == "2026-06"
    assert edition(datetime(2026, 3, 1), (6, 12)) == "2025-12"
    assert edition(datetime(2026, 12, 9), (6, 12)) == "2026-12"
    assert edition(datetime(2026, 1, 20), (1, 6)) == "2026-01"


def test_oecd_outlook_is_a_further_source_of_growth_and_inflation(con):
    v, status = value(con, "NZL", "gdp_growth", 2027, "oecd_eo")
    assert status == "P" and v == pytest.approx(2 + 0.5 * (2027 % 3) + 0.3)
    assert value(con, "NZL", "gdp_growth", 2020, "oecd_eo")[1] == "E"
    assert value(con, "AUS", "inflation", 2024, "oecd_eo")[0] == pytest.approx(2.8)


def test_oecd_track_record_builds_from_stored_editions(con):
    sql, params = forecast_pairs_sql("gdp_growth", ["NZL"], source_id="oecd_eo")
    pairs = con.execute(sql, params).fetchall()
    assert {p[1] for p in pairs} == {"2025-12", "2026-06"}


def test_world_bank_gep(con):
    v, status = value(con, "GBR", "gdp_growth", 2027, "wb_gep")
    assert status == "P" and v == pytest.approx(2.4)
    assert value(con, "NZL", "gdp_growth", 2019, "wb_gep")[1] == "E"


def test_ai_use(con):
    assert value(con, "DEU", "ai_use_enterprises", 2024, "eurostat_ai")[0] == pytest.approx(11.6)
    assert value(con, "GRC", "ai_use_enterprises", 2024, "eurostat_ai")[0] == pytest.approx(4.2)  # EL is Greece
    assert value(con, "NZL", "ai_claude_use_per_capita_index", 2025, "anthropic_aei")[0] == pytest.approx(2.1)
    assert value(con, "USA", "ai_claude_use_share", 2025, "anthropic_aei")[0] == pytest.approx(21.6)
    assert value(con, "SGP", "ai_use_population", 2025, "ms_ai_diffusion")[0] == pytest.approx(60.9)
    assert value(con, "NZL", "ai_use_population", 2025, "ms_ai_diffusion")[0] == pytest.approx(38)  # a fraction
