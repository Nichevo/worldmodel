"""Laws and society: public holidays, Women, Business and the Law, UNODC crime and
prisons, the hand-checked same-sex marriage list and tables loaded by hand."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.laws import YES_NO, _unodc_target, change_events
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("laws") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi", "nager_holidays", "wbl", "unodc_crime", "world_policy"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    CONNECTORS["rules_curated"]().ingest(store)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, year):
    r = con.execute("SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ? "
                    "AND breakdown = '' AND variant = 'central'", [entity, indicator, f"{year}-01-01"]).fetchone()
    return r[0] if r else None


def test_holidays_as_events_and_a_yearly_count(con):
    got = con.execute("SELECT entity_id, subkind, title, start_date, place FROM events WHERE kind = 'holiday' "
                      "ORDER BY start_date, entity_id").fetchall()
    assert ("NZL", "national", "Matariki", date(2026, 7, 10), None) in got
    auckland = next(g for g in got if g[2] == "Auckland Anniversary Day")
    assert auckland[1] == "regional" and auckland[4] == "AUK, NTL"
    assert value(con, "NZL", "public_holidays", 2026) == 3  # the regional day is not counted
    assert value(con, "AUS", "public_holidays", 2026) == 1


def test_women_business_and_the_law(con):
    assert value(con, "NZL", "leave_maternity_days", 2002) == 98  # report year 2003: the laws of October 2002
    assert value(con, "SAU", "law_women_job_same", 2018) == 0 and value(con, "SAU", "law_women_job_same", 2019) == 1
    changes = {r[0]: r[1] for r in con.execute("SELECT subkind, title FROM events WHERE kind = 'law' AND entity_id = 'SAU'").fetchall()}
    assert changes["law_women_job_same"] == "Women can get a job in the same way as men: now law"
    assert changes["retirement_age_women"] == "Retirement age with full pension: women: 55 to 60 years"
    unit = con.execute("SELECT unit FROM indicators WHERE indicator_id = 'law_women_job_same'").fetchone()[0]
    assert unit == YES_NO


def test_crime_grouped_into_broad_types_and_prisons(con):
    assert value(con, "NZL", "homicide", 2020) == 52
    assert value(con, "NZL", "homicide_rate", 2020) == pytest.approx(1.03)
    assert value(con, "NZL", "crime_property", 2020) == 140000  # burglary + theft, not the car-theft subtype again
    assert value(con, "NZL", "crime_sexual", 2020) == 5000
    assert value(con, "NZL", "prisoners", 2020) == 9500
    assert value(con, "NZL", "prisoners_unsentenced", 2020) == 3500
    assert value(con, "NZL", "prisoners_women", 2020) == 600


def test_unodc_targets():
    assert _unodc_target("Offences", "by type", "Robbery", "Total", "Total") == "crime_violent"
    assert _unodc_target("Offences", "by type", "Theft: of a Motorized Land Vehicle", "Total", "Total") is None
    assert _unodc_target("Offences", "by type", "Robbery", "Male", "Total") is None


def test_same_sex_marriage_year_by_year(con):
    assert value(con, "NZL", "law_same_sex_marriage", 2012) == 0
    assert value(con, "NZL", "law_same_sex_marriage", 2013) == 1
    assert value(con, "IND", "law_same_sex_marriage", 2025) == 0
    ev = con.execute("SELECT start_date FROM events WHERE kind = 'law' AND entity_id = 'NZL' "
                     "AND subkind = 'law_same_sex_marriage'").fetchall()
    assert ev == [(date(2013, 1, 1),)]


def test_tables_loaded_by_hand(con):
    assert value(con, "NZL", "world_paid_sick_leave_guaranteed", 2022) == 1
    assert value(con, "USA", "world_weeks_of_paid_annual_leave", 2022) == 0


def test_no_event_for_the_first_year():
    assert change_events("NZL", "x", "X", YES_NO, {2000: 1.0, 2001: 1.0}, "s", None) == []
