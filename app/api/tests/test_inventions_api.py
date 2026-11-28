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


def test_future_catalogue_is_consistent():
    cat = catalogue.inventions()
    cats = {c["id"] for c in cat["categories"]}
    typed = {i["id"] for i in cat["inventions"]}
    ids = [f["id"] for f in cat["future"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 25 and not set(ids) & typed
    for f in cat["future"]:
        early, mid, late = f["range"]
        assert early <= mid <= late, f["id"]
        assert f["category"] in cats and f["what"] and f["now"] and f["effects"] and f["sources"], f["id"]
        assert all(s["name"] and s["says"] for s in f["sources"]), f["id"]
        assert set(f["built_on"]) <= typed, f["id"]
        for s in f["measures"]:
            if s.startswith("long:"):
                assert s[5:] in cat["measures"] or s[5:] in catalogue.history()["series"], f"{f['id']}: {s}"


def _crowd(q_con):
    q_con("""CREATE TABLE crowd_questions (question_key VARCHAR, site VARCHAR, title VARCHAR, url VARCHAR, kind VARCHAR,
             status VARCHAR, chance DOUBLE, closes TIMESTAMP, forecasters INTEGER, volume DOUBLE)""", [])
    q_con("CREATE TABLE crowd_points (question_key VARCHAR, at_time TIMESTAMP, chance DOUBLE, lower DOUBLE, upper DOUBLE)", [])
    ts = lambda y: (y - 1970) * inventions.YEAR_SECONDS  # noqa: E731
    q_con("""INSERT INTO crowd_questions VALUES
             ('mc:1', 'metaculus', 'When will a fusion power plant first supply the grid?', 'u1', 'date', 'open', ?, NULL, 900, NULL),
             ('mc:2', 'metaculus', 'Will nuclear fusion reach net energy by 2030?', 'u2', 'binary', 'open', 0.31, NULL, 300, NULL),
             ('mc:3', 'metaculus', 'Will fusion be done by 2020?', 'u3', 'binary', 'resolved', 0.0, NULL, 50, NULL),
             ('pm:4', 'polymarket', 'Next prime minister of somewhere?', 'u4', 'binary', 'open', 0.5, NULL, NULL, 10)""", [ts(2045.5)])
    q_con("INSERT INTO crowd_points VALUES ('mc:1', '2026-11-01', ?, ?, ?)", [ts(2045.5), ts(2038), ts(2060)])


def test_future_listing_matches_the_crowd(q):
    _crowd(q)
    got = inventions.future_listing(q, 2026)
    assert len(got["future"]) == len(catalogue.inventions()["future"])
    fusion = next(f for f in got["future"] if f["id"] == "fusion-power")
    assert [c["key"] for c in fusion["crowd"]] == ["mc:1", "mc:2"]  # open only, most forecasters first
    assert fusion["crowd"][0]["year"] == 2045.5 and fusion["crowd"][0]["early"] == 2038.0 and fusion["crowd"][0]["late"] == 2060.0
    assert fusion["crowd"][1]["chance"] == 0.31
    assert "guesses" in got["caution"]
    # an item whose middle year has passed is flagged
    assert inventions.future_listing(q, 2200)["future"][0]["overdue"] is True
    assert not any(f["overdue"] for f in got["future"] if f["range"][1] >= 2026)


def test_future_card_has_charts_and_what_it_builds_on(q):
    got = inventions.future_card(q, "nitrogen-fixing-cereals", 2026)
    assert got["item"]["name"] and got["item"]["sources"]
    assert any(c["series"] == "cereal_yield" and c["lines"] for c in got["charts"])
    assert all(b["year"] < 2026 for b in got["built_on"])
    assert got["crowd"] == []  # no crowd tables here: none, no error
    assert inventions.future_card(q, "no-such-thing", 2026) is None
