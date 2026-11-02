"""Places from Wikidata: metro and rail systems and stations, universities and companies,
each matched to a city, with company revenue in US dollars."""

import json
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "geonames", "bis", "wikidata_places")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def place(con, name):
    cols = ["kind", "subkind", "country_id", "city_id", "founded", "facts", "size"]
    r = con.execute(f"SELECT {', '.join(cols)} FROM places WHERE name = ?", [name]).fetchone()
    if r is None:
        return None
    d = dict(zip(cols, r))
    d["facts"] = json.loads(d["facts"])
    return d


def city_name(con, city_id):
    return con.execute("SELECT name FROM cities WHERE city_id = ?", [city_id]).fetchone()[0]


def test_transit_systems_with_stations_and_latest_riders(built):
    _, con = built
    m = place(con, "Sydney Metro")
    assert m["kind"] == "transit" and m["subkind"] == "metro" and city_name(con, m["city_id"]) == "Sydney"
    assert m["facts"]["stations"] == 2 and m["facts"]["riders"] == 30_000_000 and m["facts"]["riders_year"] == 2024
    assert m["facts"]["length_km"] == 66.0 and str(m["founded"]) == "2019-05-26" and m["size"] == 30_000_000
    a = place(con, "Auckland rail network")
    assert a["subkind"] == "commuter rail" and a["facts"]["stations"] == 1 and city_name(con, a["city_id"]) == "Auckland"
    assert a["size"] == 113 * 1e6  # no riders: sized by length
    assert con.execute("SELECT count(*) FROM places WHERE name = 'Q3'").fetchone()[0] == 0  # no English name


def test_universities_matched_to_the_bigger_city(built):
    _, con = built
    u = place(con, "University of Auckland")
    assert u["subkind"] == "public" and u["facts"]["students"] == 40_000 and u["size"] == 40_000
    c = place(con, "Columbia University")
    assert city_name(con, c["city_id"]) == "New York City"  # not Manhattan: NYC is bigger and almost as close


def test_company_revenue_in_us_dollars(built):
    _, con = built
    f = place(con, "Fletcher Building")
    assert f["facts"]["revenue"] == 7.7e9 and f["facts"]["revenue_year"] == 2024 and f["facts"]["currency"] == "NZD"
    assert f["facts"]["industry"] == "construction; building materials"
    assert f["facts"]["revenue_usd"] == pytest.approx(7.7e9 / 1.65, rel=0.05)
    assert place(con, "Pfizer")["facts"]["revenue_usd"] == 58_500_000_000
    assert place(con, "No Money Ltd") is None


def test_stations_map_layer(built):
    _, con = built
    r = con.execute("SELECT feature_count FROM layers WHERE layer_id = 'transit_stations'").fetchone()
    assert r and r[0] == 3
    got = dict(con.execute("SELECT layer_id, feature_count FROM layers WHERE layer_id IN ('universities', 'companies')").fetchall())
    assert got == {"universities": 2, "companies": 2}
