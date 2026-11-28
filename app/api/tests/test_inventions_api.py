"""Inventions over time: the typed-in list, one card, a measure with inventions along it, and
the chart events, on made-up figures."""

from datetime import date

import duckdb
import pytest

from worldmodel_contract import catalogue
from worldmodel_api import inventions


def test_catalogue_is_consistent():
    cat = catalogue.inventions()
    cats = {c["id"] for c in cat["categories"]}
    ids = [i["id"] for i in cat["inventions"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 100
    years = [i["year"] for i in cat["inventions"]]
    assert years == sorted(years)
    for i in cat["inventions"]:
        assert i["category"] in cats and i["what"] and i["wiki"] and i["related"] is not None
        for s in (*i["spread"], *i["related"]):
            if s.startswith("long:"):
                sid = s[5:]
                assert sid in cat["measures"] or sid in catalogue.history()["series"], f"{i['id']}: {s} has no name"
    # every category gives defaults for inventions with no related series of their own
    assert all(c in cats for c in ("energy", "medicine", "food", "computing"))


@pytest.fixture
def q():
    con = duckdb.connect()
    con.execute("""CREATE TABLE series (entity_id VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, breakdown VARCHAR,
                   variant VARCHAR, status VARCHAR, value DOUBLE, source_id VARCHAR, is_aggregate BOOLEAN)""")
    con.execute("CREATE TABLE indicator_sources (indicator_id VARCHAR, source_id VARCHAR, rank INTEGER)")
    con.execute("CREATE TABLE indicators (indicator_id VARCHAR, name VARCHAR, unit VARCHAR, decimals INTEGER)")
    con.execute("CREATE TABLE entities (entity_id VARCHAR, name VARCHAR, short_name VARCHAR)")
    con.execute("CREATE TABLE long_series (entity_id VARCHAR, series_id VARCHAR, year INTEGER, value DOUBLE, source_id VARCHAR, vintage VARCHAR)")
    con.execute("""CREATE TABLE history_events (event_id VARCHAR, kind VARCHAR, title VARCHAR, year INTEGER, entity_id VARCHAR,
                   links INTEGER, url VARCHAR)""")
    con.execute("INSERT INTO entities VALUES ('NZL', 'New Zealand', 'New Zealand'), ('world', 'World', 'World'), ('USA', 'United States', 'US')")
    con.execute("INSERT INTO indicators VALUES ('cereal_yield', 'Cereal yield', 'kg per hectare', 0)")
    for y in range(1961, 2021):
        con.execute("INSERT INTO series VALUES ('NZL', 'cereal_yield', ?, 'A', '', 'central', 'A', ?, 'world_bank_wdi', false)",
                    [date(y, 1, 1), 4000 + 50 * (y - 1961)])
    for y in range(1850, 2021, 10):
        con.execute("INSERT INTO long_series VALUES ('world', 'life_expectancy', ?, ?, 'owid_longrun', 'v')", [y, 30 + (y - 1850) / 4])
        con.execute("INSERT INTO long_series VALUES ('NZL', 'child_mortality', ?, ?, 'owid_longrun', 'v')", [y, 30 - (y - 1850) / 6])
    con.execute("INSERT INTO long_series VALUES ('USA', 'us_electric_power', 1930, 70, 'owid_longrun', 'v')")
    con.execute("""INSERT INTO history_events VALUES ('wd:Q1', 'invention', 'zipper', 1893, NULL, 84, 'https://en.wikipedia.org/wiki/Zipper'),
                   ('wd:Q2', 'invention', 'penicillin', 1928, NULL, 118, 'https://en.wikipedia.org/wiki/Penicillin'),
                   ('wd:Q3', 'invention', 'obscure thing', 1900, NULL, 5, 'https://en.wikipedia.org/wiki/Obscure')""")

    def run(sql, params):
        cur = con.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return run


def test_listing_keeps_wikidata_extras_not_typed_in(q):
    got = inventions.listing(q)
    assert len(got["inventions"]) == len(catalogue.inventions()["inventions"])
    assert [x["name"] for x in got["extras"]] == ["Zipper"]  # penicillin is typed in; the obscure one has too few Wikipedias
    assert "caused" in got["caution"]
    assert any(m["series"] == "cereal_yield" and m["name"] == "Cereal yield" for m in got["measures"])


def test_card_has_spread_and_related_charts(q):
    got = inventions.card(q, "smallpox-vaccine")
    assert got["invention"]["year"] == 1796 and got["invention"]["wiki"].endswith("Smallpox_vaccine")
    assert got["entities"][:5] == list(inventions.KEY) and "GBR" in got["entities"]
    kinds = {c["series"]: c["kind"] for c in got["charts"]}
    assert kinds["long:smallpox_cases"] == "spread" and kinds["long:life_expectancy"] == "related"
    life = next(c for c in got["charts"] if c["series"] == "long:life_expectancy")
    assert [l["entity"] for l in life["lines"]] == ["world"] and life["lines"][0]["points"][0] == [1850, 30.0]
    assert life["name"] == "Life expectancy at birth"
    assert any(o["id"] == "penicillin" for o in life["others"])
    assert got["after"] is not None and got["before"] is not None


def test_us_household_series_show_the_us_only(q):
    got = inventions.card(q, "power-station", ["NZL"])
    us = next(c for c in got["charts"] if c["series"] == "long:us_electric_power")
    assert [l["entity"] for l in us["lines"]] == ["USA"] and us["name"] == "US homes with electricity"


def test_along_marks_linked_inventions(q):
    got = inventions.along(q, "cereal_yield", ["NZL"], ["food"])
    assert got["lines"][0]["points"][0] == [1961, 4000]
    assert all(i["category"] == "food" for i in got["inventions"])
    assert next(i for i in got["inventions"] if i["id"] == "haber-bosch")["linked"]
    assert inventions.card(q, "no-such-thing") is None


def test_inventions_as_chart_events():
    rows = inventions.as_events(["NZL", "AUS"])
    pen = [r for r in rows if r["title"] == "Penicillin"]
    assert {r["entity_id"] for r in pen} == {"NZL", "AUS"}
    assert pen[0]["start_date"] == "1928-01-01" and pen[0]["kind"] == "invention" and pen[0]["url"] == "/inventions?id=penicillin"
    assert all(int(r["start_date"][:4]) >= 1700 for r in rows)
