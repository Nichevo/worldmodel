"""CIA World Factbook archive: numbers by estimate year, every field's text, and states that no longer exist."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.cia_factbook import estimate_year, number
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi", "cia_factbook"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return home, duckdb.connect(str(result.path), read_only=True)


def test_numbers_are_read_with_their_scale_and_year():
    assert number("production: 3.011 million metric tons (2023 est.)", 3.011) == 3.011e6
    assert number("$14,000", 14000.0) == 14000
    assert number("-$1.2 billion (2019 est.)", -1.2) == -1.2e9
    assert number("total: 92,200 km", 92200.0) == 92200
    assert estimate_year("value_2024", "x", None) == 2024
    assert estimate_year("value", "1,603,500 (June 1991)", "1987") == 1991
    assert estimate_year("value", "2% ", None, "2% of | GDP (FY90/91) | x") == 1991
    assert estimate_year("value", "41.8% ", None, "41.8% of GDP (2012 est.) | country") == 2012
    assert estimate_year("total", "4,035,461", None, "") is None


def test_series_from_every_edition(built):
    _, con = built
    pop = dict(con.execute("""SELECT year(period_start), value FROM series WHERE source_id = 'cia_factbook'
        AND entity_id = 'NZL' AND indicator_id = 'pop_total'""").fetchall())
    assert pop[2024] == 5161211 and pop[1990] == 3295866  # the 1990 edition: "3,295,866 (July 1990)"
    oil = con.execute("""SELECT value FROM series WHERE source_id = 'cia_factbook' AND entity_id = 'USA'
        AND indicator_id = 'fb_oil_reserves' AND period_start = DATE '2021-01-01'""").fetchone()[0]
    assert oil == pytest.approx(38.212e9)
    inds = {r[0]: r[1:] for r in con.execute("SELECT indicator_id, default_on, unit FROM indicators").fetchall()}
    assert inds["fb_oil_reserves"] == (True, "barrels") and inds["fb_gdp_ppp"][0] is False
    # The Factbook is one more source for indicators others have, ranked after them.
    ranks = dict(con.execute("SELECT source_id, rank FROM indicator_sources WHERE indicator_id = 'pop_total'").fetchall())
    assert ranks["un_wpp"] == 1 and ranks["cia_factbook"] > ranks["world_bank_wdi"]


def test_text_of_every_edition_with_old_states(built):
    _, con = built
    editions = dict(con.execute("""SELECT edition, count(*) FROM texts WHERE entity_id = 'NZL'
        AND source_id = 'cia_factbook' GROUP BY 1""").fetchall())
    assert set(editions) == {1990, 2020, 2025} and min(editions.values()) > 50
    bg = con.execute("""SELECT section, content FROM texts WHERE entity_id = 'NZL' AND edition = 2025
        AND field_key = 'Background'""").fetchone()
    assert bg[0] == "Introduction" and "Polynesians" in bg[1]
    who = {r[0] for r in con.execute("SELECT DISTINCT entity_id FROM texts").fetchall()}
    # The Soviet Union and both Yemens of 1990 by name; Somalia by its ISO code; the World.
    assert {"SUN", "YAR", "YMD", "YEM", "SOM", "world", "NZL", "USA"} <= who
    # Guernsey shares the UK's ISO code and the Gaza Strip is profiled apart: neither is put on a country.
    assert "GBR" not in who and "PSE" not in who
    assert not con.execute("SELECT count(*) FROM texts WHERE content LIKE '%Skip to content%'").fetchone()[0]


def test_refresh_leaves_frozen_and_recent_sources_alone(built):
    from worldmodel_data.cli import _not_due
    from worldmodel_data.vintage_store import Manifest

    home, _ = built
    last = VintageStore(home).latest("cia_factbook")
    assert "no longer changes" in _not_due(CONNECTORS["cia_factbook"], last)
    assert _not_due(CONNECTORS["un_wpp"], VintageStore(home).latest("un_wpp")) is None

    class Monthly:
        frozen, fetch_every_days = False, 28

    def fetched(days):
        at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return Manifest(**{**last.__dict__, "retrieved_at": at})

    assert "every 28 days" in _not_due(Monthly, fetched(3))
    assert _not_due(Monthly, fetched(40)) is None


def test_wikidata_facts_box(tmp_path):
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "wikidata"):
        manifest, _ = CONNECTORS[source]().ingest(store, FIXTURES / source)
    assert manifest.row_count == 0
    con = duckdb.connect(str(build(home).path), read_only=True)
    nz = {r[0]: r[1:] for r in con.execute("""SELECT field_key, field, content, section, edition FROM texts
        WHERE entity_id = 'NZL' AND source_id = 'wikidata' ORDER BY position""").fetchall()}
    assert nz["P36"][:2] == ("Capital", "Wellington") and nz["P36"][3] is None
    assert nz["P37"][1] == "English; Maori; New Zealand Sign Language"
    assert nz["P571"][1] == "1907-09-26" and nz["P474"][1] == "+64" and nz["P856"][1] == "https://www.govt.nz/"
    assert nz["P41"][1:3] == ("Flag of New Zealand.svg", "Pictures")
    assert nz["article"][1] == "New Zealand" and nz["item"][1] == "Q664"
    assert "P18" not in nz and "P610" not in nz
    # One item per code: the Netherlands, not the Kingdom; old states by their ISO 3166-3 code.
    nld = con.execute("SELECT content FROM texts WHERE entity_id = 'NLD' AND field_key = 'P36'").fetchone()[0]
    assert nld == "Amsterdam"
    assert con.execute("SELECT content FROM texts WHERE entity_id = 'SUN' AND field_key = 'P571'").fetchone()[0] == "1922-12-30"
