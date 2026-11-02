"""Cities and the cost of living: GeoNames, UN WUP, WhereNext, ILOSTAT and Numbeo, and the city matching."""

from pathlib import Path

import duckdb
import pytest

from worldmodel_contract.cities import norm_name
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "geonames", "un_wup", "wherenext", "ilostat_earnings", "numbeo")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def city(con, cid, ind, year, source=None):
    r = con.execute("SELECT value, status FROM city_series WHERE city_id = ? AND indicator_id = ? AND year(period_start) = ?"
                    + (" AND source_id = ?" if source else ""), [cid, ind, year] + ([source] if source else [])).fetchone()
    return r


def value(con, entity, indicator, year):
    r = con.execute("SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND year(period_start) = ?",
                    [entity, indicator, year]).fetchone()
    return r and r[0]


def test_norm_name():
    assert norm_name("Ōtautahi") == "otautahi"
    assert norm_name("Mexico City") == norm_name("Ciudad de Mexico".replace("Ciudad de ", "")) == "mexico"
    assert norm_name("Saint Louis") == norm_name("St. Louis")


def test_geonames_city_list(built):
    _, con = built
    row = con.execute("SELECT name, country_id, admin1, capital, population FROM cities WHERE city_id = 'gn2179537'").fetchone()
    assert row == ("Wellington", "NZL", "Wellington", "national", 215400)
    assert con.execute("SELECT count(*) FROM cities WHERE name = 'Nowhere'").fetchone()[0] == 0  # unknown country
    layer = con.execute("SELECT feature_count FROM layers WHERE layer_id = 'major_cities'").fetchone()
    assert layer and layer[0] >= 6  # cities of a million or more, plus capitals (Wellington)


def test_wup_matched_by_location_and_marks_projections(built):
    _, con = built
    v, status = city(con, "gn2193733", "city_population", 1950)
    assert v == pytest.approx(329_100) and status == "E"
    assert city(con, "gn2193733", "city_population", 2030)[1] == "P"
    # "New York-Newark" matches New York City (largest named city nearby), not Manhattan.
    assert city(con, "gn5128581", "city_population", 2015)
    assert not con.execute("SELECT count(*) FROM city_series WHERE city_id = 'gn5125771'").fetchone()[0]


def test_wherenext_cities_and_countries(built):
    _, con = built
    assert city(con, "gn2179537", "wn_city_monthly_cost_usd", 2026)[0] == 2250
    assert city(con, "gn5128581", "wn_city_cost_index", 2026)[0] == 95  # "New York" is one of NYC's other names
    assert value(con, "NZL", "wn_cost_index", 2026) == 71
    assert value(con, "GBR", "wn_median_net_usd", 2024) == 38570
    assert value(con, "NZL", "wn_take_home_share", 2024) == pytest.approx(100 * 55400 / 69000)


def test_ilostat_earnings(built):
    _, con = built
    assert value(con, "NZL", "ilo_earnings_ppp", 2023) == 4200
    assert value(con, "NZL", "ilo_earnings_ppp_women", 2023) == pytest.approx(3780)
    assert value(con, "NZL", "ilo_min_wage_lcu", 2023) == 3700


def test_numbeo_by_city_and_country(built):
    result, con = built
    # Hamilton, New Zealand is the NZ one, not the larger Hamilton in Canada; "Londres" is one of London's names.
    assert city(con, "gn2190324", "numbeo_cost_of_living", 2025)[0] == pytest.approx(60.1)
    assert city(con, "gn2643743", "numbeo_rent", 2025)[0] == 65
    assert not con.execute("SELECT count(*) FROM city_series WHERE city_id = 'gn5969785'").fetchone()[0]
    assert value(con, "NZL", "numbeo_rent", 2025) == pytest.approx(27.4)
    check = next(c for c in result.checks if c.check_id == "cities:matched")
    assert "matched no city" in check.detail and any("Lyonville" in e for e in check.examples)
