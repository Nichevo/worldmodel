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


def test_ms_ai_diffusion_github_file_one_column_per_period(tmp_path):
    """The repository's file has a column per half-year or quarter; each year takes its latest."""
    import httpx

    csv = ("Economy,H1 2025 AI Diffusion,H2 2025 AI Diffusion,Q1 2026 AI Diffusion,Q2 2026 AI Diffusion\n"
           "Singapore,58.60%,60.90%,63.40%,64.3%\nNew Zealand,37.60%,40.50%,43.00%,44.1%\n"
           # Bracketed names must not fold into the plain one: "Congo (DRC)" is not the Republic of the Congo.
           "Congo (DRC),5.0%,5.5%,6.0%,6.5%\nCongo,7.0%,7.5%,8.0%,8.5%\n"
           # Two spellings of one country: the first is kept rather than failing the build on duplicates.
           "Congo (Brazzaville),9.0%,9.5%,9.9%,9.9%\n")
    asked = []

    def handler(request):
        asked.append(str(request.url))
        if "api.github.com" in str(request.url):
            return httpx.Response(200, json=[{"type": "file", "name": "AI_Diffusion_Q12026_Update.csv"},
                                             {"type": "file", "name": "AI_Diffusion_Q22026_Update.csv"},
                                             {"type": "dir", "name": "US"}])
        return httpx.Response(200, text=csv)

    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, FIXTURES / "imf_weo")
    CONNECTORS["ms_ai_diffusion"](httpx.Client(transport=httpx.MockTransport(handler))).ingest(store)
    assert asked[1].endswith("/data/AI_Diffusion_Q22026_Update.csv")
    c = duckdb.connect(str(build(home).path), read_only=True)
    assert value(c, "NZL", "ai_use_population", 2025, "ms_ai_diffusion")[0] == pytest.approx(40.5)
    assert value(c, "NZL", "ai_use_population", 2026, "ms_ai_diffusion")[0] == pytest.approx(44.1)
    assert value(c, "COD", "ai_use_population", 2026, "ms_ai_diffusion")[0] == pytest.approx(6.5)
    assert value(c, "COG", "ai_use_population", 2026, "ms_ai_diffusion")[0] == pytest.approx(8.5)


def test_ms_ai_diffusion_file_in_windows_encoding(tmp_path):
    from worldmodel_data.connectors.ai_use import _table

    f = tmp_path / "AI_Diffusion.csv"
    f.write_bytes("Economy,Q2 2026 AI Diffusion\nCuraçao,30.1%\nCôte d’Ivoire,5%\n".encode("cp1252"))
    assert _table(f)[1][0] == "Curaçao" and _table(f)[2][0] == "Côte d’Ivoire"
