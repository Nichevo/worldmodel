"""Dated events: coups, conflicts, disasters, Wikidata elections, leaders and sporting
events, the curated notable episodes, and episodes worked out from the data."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("e") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi", "wikidata", "powell_thyne", "ucdp_acd", "emdat"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return home, duckdb.connect(str(result.path), read_only=True)


def events(con, where: str, params=()):
    cols = ("event_id", "entity_id", "source_id", "kind", "subkind", "title", "start_date", "end_date", "precision",
            "size", "size_unit", "deaths", "affected", "damage_usd", "place", "detail", "color")
    rows = con.execute(f"SELECT {', '.join(cols)} FROM events WHERE {where} ORDER BY start_date, entity_id", params).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def test_coups_are_dated_and_matched_by_name(built):
    _, con = built
    got = events(con, "source_id = 'powell_thyne'")
    assert [(e["entity_id"], e["start_date"], e["subkind"]) for e in got] == [
        ("CIV", date(1999, 12, 24), "successful"), ("THA", date(2006, 9, 19), "successful"),
        ("THA", date(2014, 5, 22), "successful"), ("TUR", date(2016, 7, 15), "failed")]


def test_conflicts_are_episodes_for_each_country_involved(built):
    _, con = built
    got = events(con, "source_id = 'ucdp_acd'")
    ukraine = [e for e in got if e["start_date"] == date(2022, 2, 24)]
    assert {e["entity_id"] for e in ukraine} == {"RUS", "UKR"}
    assert all(e["end_date"] is None and e["size"] == 2 and e["subkind"] == "interstate" for e in ukraine)
    afg = next(e for e in got if e["entity_id"] == "AFG")
    assert afg["end_date"] == date(2002, 12, 31) and afg["subkind"] == "internationalised intrastate"


def test_disasters_carry_deaths_affected_and_damage(built):
    _, con = built
    got = {e["title"]: e for e in events(con, "source_id = 'emdat'")}
    assert got["Tohoku"]["deaths"] == 19846 and got["Tohoku"]["damage_usd"] == 290e9  # the inflation-adjusted figure
    assert got["Riverine flood (flood)"]["size_unit"] == "deaths" and got["Riverine flood (flood)"]["precision"] == "day"
    assert got["COVID-19"]["kind"] == "epidemic" and got["COVID-19"]["precision"] == "month"
    assert "Atlantis" not in str(got)


def test_wikidata_events(built):
    _, con = built
    elections = events(con, "source_id = 'wikidata' AND kind = 'election'")
    assert {(e["entity_id"], e["subkind"]) for e in elections} == {("NZL", "general"), ("GBR", "referendum")}
    leaders = {(e["entity_id"], e["title"], e["start_date"].year): e
               for e in events(con, "source_id = 'wikidata' AND kind = 'leader'")}
    assert ("NZL", "Jacinda Ardern (head of government)", 2017) in leaders
    assert not any("Q57196" in t for _, t, _ in leaders)  # no English label: left out
    ardern = leaders[("NZL", "Jacinda Ardern (head of government)", 2017)]
    assert ardern["detail"] == "New Zealand Labour Party" and ardern["color"] == "#D82A20"
    # A party membership whose dates cover the term wins over one that ended long before.
    bolger = leaders[("NZL", "Jim Bolger (head of government)", 1990)]
    assert bolger["detail"] == "New Zealand National Party" and bolger["color"] == "#00529F"
    assert len([k for k in leaders if k[0] == "GBR"]) == 16
    sport = events(con, "source_id = 'wikidata' AND kind = 'sport'")
    cup = [e for e in sport if e["title"] == "2002 FIFA World Cup"]
    assert {e["entity_id"] for e in cup} == {"KOR", "JPN"}  # co-hosts each get the event
    brazil = next(e for e in sport if e["entity_id"] == "BRA")
    assert brazil["end_date"] == date(2014, 7, 13) and set(brazil["place"].split("; ")) == {"Rio de Janeiro", "São Paulo"}
    quake = events(con, "source_id = 'wikidata' AND kind = 'disaster'")
    assert len(quake) == 1 and quake[0]["deaths"] == 19759 and quake[0]["damage_usd"] == 360e9


def test_notable_episodes_and_computed_ones(built):
    _, con = built
    notable = events(con, "source_id = 'notable'")
    assert any(e["title"] == "Interstate Highway System" and e["entity_id"] == "USA" for e in notable)
    recessions = events(con, "source_id = 'worldmodel' AND kind = 'recession'")
    assert recessions, "the IMF fixture has years of falling GDP"
    r = recessions[0]
    assert r["precision"] == "year" and r["start_date"].month == 1 and r["end_date"].month == 12 and r["size"] < 0
    assert dict(con.execute("SELECT check_id, status FROM build_checks").fetchall())["episodes:computed"] == "info"


def test_events_keys_are_unique(built):
    _, con = built
    assert not con.execute("SELECT event_id, entity_id FROM events GROUP BY ALL HAVING count(*) > 1").fetchall()


def test_refresh_skips_hand_loaded_sources_and_refetches_after_new_queries():
    from worldmodel_data.cli import _not_due
    from worldmodel_data.vintage_store import Manifest, now_utc

    assert "fetch emdat --from" in _not_due(CONNECTORS["emdat"], None)
    last = Manifest(source_id="wikidata", vintage="2026-10", release="2026-10", retrieved_at=now_utc().isoformat(),
                    origin="", sha256="", raw_dir="")
    assert _not_due(CONNECTORS["wikidata"], last) is None  # fetched today, but before the event queries existed
    last.fetch_version = CONNECTORS["wikidata"].fetch_version
    assert "days ago" in _not_due(CONNECTORS["wikidata"], last)
