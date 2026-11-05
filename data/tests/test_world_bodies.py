"""The world beyond borders: UN votes and Security Council, sanctions, IMF programmes,
WTO disputes, treaties, CrisisWatch, Wikidata summits, court cases and resolutions,
Antarctica, sea ice and what is in orbit. All from small sample files."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.crisiswatch import entries, month_of, months_back
from worldmodel_data.connectors.world_bodies import cow_entity, parse_day
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("unga_votes", "un_vetoes", "gsdb", "imf_mona", "wto_disputes", "un_treaties", "crisiswatch",
           "nsidc_sea_ice", "celestrak_satcat", "wikidata")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("wb") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi") + SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def events(con, source, entity=None):
    sql = "SELECT entity_id, kind, subkind, title, start_date, end_date, size, detail FROM events WHERE source_id = ?"
    params = [source]
    if entity:
        sql += " AND entity_id = ?"
        params.append(entity)
    return con.execute(sql + " ORDER BY start_date, entity_id", params).fetchall()


def value(con, entity, indicator, period, breakdown=""):
    r = con.execute("SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ? "
                    "AND breakdown = ? AND variant = 'central'", [entity, indicator, period, breakdown]).fetchone()
    return r[0] if r else None


def test_un_agreement_both_ways_and_ideal_points(con):
    assert value(con, "NZL", "unga_agreement", "2020-01-01", "USA") == 62
    assert value(con, "USA", "unga_agreement", "2020-01-01", "NZL") == 62
    assert value(con, "AUS", "unga_agreement", "2021-01-01", "NZL") == 93
    assert value(con, "NZL", "unga_ideal_point", "2020-01-01") == pytest.approx(0.81)  # session 75 met in 2020
    assert value(con, "SUN", "unga_ideal_point", "1985-01-01") == pytest.approx(-1.6)  # by COW code, no ISO code


def test_cow_codes_follow_the_state():
    assert cow_entity(365, 1990) == "SUN" and cow_entity(365, 1992) == "RUS"
    assert cow_entity("920", 2000) == "NZL" and cow_entity("x", 2000) is None


def test_vetoes_and_council_seats(con):
    got = events(con, "un_vetoes")
    assert {r[0] for r in got if r[2] == "veto"} == {"RUS", "CHN", "USA"}
    syria = [r for r in got if r[4] == date(2012, 2, 4)]
    assert {r[0] for r in syria} == {"CHN", "RUS"}
    seats = [r for r in got if r[0] == "NZL" and r[2] == "council_seat"]
    assert [(r[4].year, r[5].year) for r in seats] == [(1954, 1955), (1993, 1994), (2015, 2016)]


def test_sanctions_events_and_counts(con):
    assert events(con, "gsdb", "CHL") == []  # the financial-sanctions file beside it (GSDB_V4_FS.csv) is not read
    got = events(con, "gsdb", "RUS")
    assert len(got) == 1 and got[0][3] == "Sanctions by New Zealand" and "financial" in got[0][2]
    assert value(con, "IRN", "sanctions_active", "2000-01-01") == 1
    assert value(con, "NZL", "sanctions_imposed", "2022-01-01") == 1
    zaf = events(con, "gsdb", "ZAF")[0]
    assert zaf[5] == date(1991, 12, 31)


def test_imf_programmes_once_each_with_size(con):
    got = events(con, "imf_mona")
    assert [r[0] for r in got] == ["GRC", "ARG", "LKA"]
    arg = got[1]
    assert arg[2] == "SBA" and arg[3] == "IMF programme: Stand-By Arrangement" and arg[6] == pytest.approx(40.714)
    assert arg[5] == date(2019, 12, 31)  # the revised end date


def test_wto_disputes_for_both_sides(con):
    got = events(con, "wto_disputes")
    ds543 = {(r[0], r[2]) for r in got if "DS543" in r[3]}
    assert ds543 == {("USA", "respondent"), ("CHN", "complainant")}
    assert ("eu", "respondent") in {(r[0], r[2]) for r in got if "DS600" in r[3]}


def test_treaties_joined_and_signed(con):
    got = {r[0]: r for r in events(con, "un_treaties")}
    assert got["NZL"][4] == date(2016, 10, 4) and got["NZL"][3] == "Joined the Paris Agreement"
    assert got["IRN"][3].startswith("Signed the Paris Agreement")
    assert got["AGO"][7].startswith("Acceded")
    assert value(con, "NZL", "treaties_joined", "2016-01-01") == 1
    assert value(con, "IRN", "treaties_joined", "2016-01-01") is None


def test_crisiswatch_ratings_split_entries(con):
    got = events(con, "crisiswatch")
    oct_ = {r[0]: r[2] for r in got if r[4] == date(2024, 10, 1)}
    assert oct_ == {"ISR": "deteriorated", "PSE": "deteriorated", "SOM": "unchanged", "LKA": "improved"}
    sep = {r[0]: r[2] for r in got if r[4] == date(2024, 9, 1)}
    assert sep == {"LBN": "risk_alert", "SOM": "unchanged"}
    assert next(r for r in got if r[0] == "LKA")[7] == "The new president took office peacefully."


def test_crisiswatch_months():
    assert month_of("october-2024.html") == date(2024, 10, 1)
    assert month_of("2003-08.htm") == date(2003, 8, 1)
    assert month_of("notes.html") is None
    assert months_back(date(2024, 1, 15), 2) == [date(2023, 12, 1), date(2023, 11, 1)]
    assert entries("<html><p>No entries</p></html>") == []


def test_wikidata_summits_courts_and_resolutions(con):
    got = events(con, "wikidata")
    assert ("NZL", "summit", "APEC") in {(r[0], r[1], r[2]) for r in got}
    court = {r[0]: r for r in got if r[1] == "court"}
    assert set(court) == {"AUS", "JPN"} and court["AUS"][2] == "ICJ" and "plaintiff" in court["AUS"][7]
    assert ("IRN", "un", "resolution") in {(r[0], r[1], r[2]) for r in got}


def test_antarctic_layers(con):
    layers = {r[0]: r[1:] for r in con.execute("SELECT layer_id, kind, feature_count FROM layers").fetchall()}
    assert layers["antarctic_stations"] == ("point", 2)
    assert layers["antarctic_claims"] == ("line", 9)


def test_sea_ice_monthly_and_yearly(con):
    assert value(con, "arctic", "sea_ice_extent", "2022-09-01") == pytest.approx(4.3)
    assert value(con, "arctic", "sea_ice_extent_min", "2023-01-01") == pytest.approx(4.1)
    assert value(con, "ATA", "sea_ice_extent_max", "2022-01-01") == pytest.approx(18.0)
    assert value(con, "arctic", "sea_ice_extent", "2024-01-01") is None  # -9999 is missing
    assert value(con, "arctic", "sea_ice_extent_mean", "2024-01-01") is None  # a part year has no mean


def test_satellites_by_owner_and_launch_site(con):
    assert value(con, "NZL", "sats_launched", "2018-01-01") == 1
    assert value(con, "NZL", "space_launches", "2018-01-01") == 1  # Mahia: two objects, one launch
    assert value(con, "SUN", "sats_launched", "1957-01-01") == 1
    assert value(con, "KAZ", "space_launches", "1957-01-01") == 1  # Baikonur
    assert value(con, "SUN", "sats_in_orbit", "1990-01-01") == 1  # Cosmos 2000
    assert value(con, "RUS", "sats_in_orbit", "2020-01-01") == 1  # ... which Russia then took over
    assert value(con, "space", "objects_in_orbit_debris", "2020-01-01") == 1
    assert value(con, "NZL", "sats_in_orbit", "2019-01-01") == 0


def test_dates_in_many_shapes():
    assert parse_day("16 Dec 1966")[0] == date(1966, 12, 16)
    assert parse_day("December 16, 1966")[0] == date(1966, 12, 16)
    assert parse_day("1966-12-16")[0] == date(1966, 12, 16)
    assert parse_day("")[0] is None


def test_sanctions_release_5_lists_several_countries_in_one_cell():
    from worldmodel_data.connectors.world_bodies import gsdb_names, sanction_rows
    assert gsdb_names("United States, United Kingdom, France", date(1956, 1, 1)) == ["United States", "United Kingdom", "France"]
    assert gsdb_names("Korea, North", date(2000, 1, 1)) == ["Korea, North"]
    assert gsdb_names("Gambia, The, Russia", date(2020, 1, 1)) == ["Gambia, The", "Russia"]
    table = [["case_id", "sanctioned_state", "sanctioning_state", "begin_year", "begin_month", "end_year", "end_month",
              "trade", "financial", "objective"],
             ["318", "New Zealand", "France", "1986", "February", "1986", "July", "1", "0", "other"],
             ["900", "Korea, North", "EU, Australia, New Zealand", "2006", "October", "2025", "NA", "1", "1", "policy_change"],
             ["901", "Ceylon, Malaya", "United Kingdom", "1960", "NA", "1961", "NA", "1", "0", ""],
             ["902", "ISIL/Al-Qaeda", "UN", "2015", "December", "2025", "NA", "0", "1", "fight_terror"],
             ["903", "Comecon", "CoCom", "1950", "NA", "1990", "NA", "1", "0", ""]]
    events, values, unmatched = sanction_rows(table, 2026)
    by = {e[1]: e for e in events}
    assert by["gsdb:318:NZL"][5:7] == (date(1986, 2, 1), date(1986, 7, 31))
    assert by["gsdb:900:PRK"][6] is None  # still in force when the database ends
    assert {"gsdb:901:LKA", "gsdb:901:MYS", "gsdb:902:isil", "gsdb:902:al-qaeda", "gsdb:903:comecon"} <= set(by)
    assert not unmatched
    imposed = {(r[1], r[3].year if hasattr(r[3], "year") else r[3]) for r in values.rows if r[2] == "sanctions_imposed"}
    assert {("eu", 2010), ("AUS", 2010), ("NZL", 2010), ("un", 2020), ("cocom", 1960)} <= imposed
