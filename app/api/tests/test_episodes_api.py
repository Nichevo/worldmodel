"""Big episodes and big cycles: the sums, the rules and one episode page on made-up figures."""

from datetime import date

import duckdb
import pytest

from worldmodel_api import cycles, episodes


def test_output_fall_and_level_fall():
    # Falls 5% then 5% again, then recovers: about -9.75% from the start.
    assert episodes.output_fall({2008: -5, 2009: -5, 2010: 12}, 2008, 2010) == pytest.approx(-9.8, abs=0.1)
    assert episodes.output_fall({2008: 2, 2009: 1}, 2008, 2009) == 0
    assert episodes.output_fall({}, 2008, 2009) is None
    assert episodes.level_fall({1928: 100, 1929: 100, 1932: 75, 1936: 102}, 1929, 1939) == -25.0


def test_dates_as_fractional_years():
    assert episodes.frac("2008") == 2008
    assert episodes.frac("2008", end=True) == 2009
    assert episodes.frac("2008-07") == pytest.approx(2008.5)
    assert episodes.frac("2008-12", end=True) == pytest.approx(2009)
    assert episodes._end_date("2009-02") == "2009-02-28"
    assert episodes._end_date("2009") == "2009-12-31"


def test_episodes_as_events_link_to_their_pages():
    rows = episodes.as_events(["NZL"])
    assert rows and all(r["entity_id"] == "NZL" and r["kind"] == "episode" for r in rows)
    gfc = next(r for r in rows if r["url"] == "/episodes/gfc")
    assert gfc["start_date"] == "2007-08-01" and gfc["end_date"] == "2009-06-30" and gfc["precision"] == "month"


def test_phases_rise_top_decline():
    pts = [[y, v] for y, v in zip(range(1500, 1600, 10), [0.1, 0.2, 0.3, 0.38, 0.4, 0.37, 0.3, 0.2, 0.15, 0.1])]
    got = cycles.phases(pts)
    assert got["peak"] == [1540, 0.4]
    assert [p["phase"] for p in got["phases"]] == ["rise", "top", "decline"]
    assert got["phases"][1] == {"phase": "top", "from": 1530, "to": 1550}
    assert got["now"] == "decline"
    rising = cycles.phases([[1500, 0.1], [1510, 0.2], [1520, 0.3]])
    assert rising["now"] == "top" and rising["phases"][-1]["phase"] == "top"


def test_figures_at_a_decade():
    s = {"debt": {y: 40 + (y - 1960) for y in range(1960, 2001)}, "growth": {1965: 3.0}}
    f = cycles.figures_at(s, 1990)
    assert f["debt"]["latest"] == 70 and f["debt"]["ten_ago"] == 60 and f["debt"]["year"] == 1990
    assert "growth" not in f  # older than five years


@pytest.mark.parametrize("figs, phase", [
    ({"g": -1.0, "q_last": -0.5, "q_prev": -0.2}, "Recession"),
    ({"g": 0.8, "g_prev": 1.2, "rate": 3.0, "rate_chg": -1.0, "cli_chg": -0.4}, "Easing"),
    ({"g": 1.2, "g_prev": -0.5, "rate": 2.0, "rate_chg": -1.0}, "Early recovery"),
    ({"g": 1.0, "g_prev": 2.5, "rate": 4.5, "rate_chg": 0.5, "cli_chg": -0.8}, "Slowdown"),
    ({"g": 3.0, "g_prev": 2.8, "infl": 5.0, "rate": 4.0, "rate_chg": 1.0}, "Late expansion"),
    ({"g": 2.5, "g_prev": 2.4, "infl": 2.0, "rate": 3.0, "rate_chg": 0.0}, "Expansion"),
])
def test_clock_rules(figs, phase):
    got, reasons = cycles.clock_place(figs)
    assert got == phase and reasons


def test_clock_without_figures():
    assert cycles.clock_place({}) == (None, ["No recent growth figures."])


@pytest.fixture
def q():
    con = duckdb.connect()
    con.execute("""CREATE TABLE series (entity_id VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, breakdown VARCHAR,
                   variant VARCHAR, status VARCHAR, value DOUBLE, source_id VARCHAR, is_aggregate BOOLEAN)""")
    con.execute("CREATE TABLE indicator_sources (indicator_id VARCHAR, source_id VARCHAR, rank INTEGER)")
    con.execute("CREATE TABLE indicators (indicator_id VARCHAR, name VARCHAR, unit VARCHAR, decimals INTEGER)")
    con.execute("CREATE TABLE events (event_id VARCHAR, entity_id VARCHAR, source_id VARCHAR, kind VARCHAR, subkind VARCHAR, title VARCHAR, start_date DATE, end_date DATE, size DOUBLE, size_unit VARCHAR)")
    con.execute("CREATE TABLE entities (entity_id VARCHAR, type VARCHAR)")
    con.execute("INSERT INTO indicator_sources VALUES ('gdp_growth', 'good', 1), ('gdp_growth', 'worse', 2)")
    rows = []
    for e, dip in (("USA", -2.5), ("GBR", -4.0), ("IRL", -5.0), ("NZL", -1.5), ("AUS", 1.5), ("ISL", -6.0), ("ESP", -3.0)):
        for y in range(1998, 2020):
            g = dip if y == 2009 else 2.5
            rows += [(e, "gdp_growth", date(y, 1, 1), "A", "", "central", "E", g, "good", False),
                     (e, "gdp_growth", date(y, 1, 1), "A", "", "central", "E", 99.0, "worse", False),
                     (e, "inflation", date(y, 1, 1), "A", "", "central", "E", 2.0, "x", False),
                     (e, "pop_total", date(y, 1, 1), "A", "", "central", "E", 5e6, "x", False)]
    con.executemany("INSERT INTO series VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def run(sql, params=None):
        rel = con.execute(sql, params or [])
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, r)) for r in rel.fetchall()]
    return run


def test_annual_takes_the_first_ranked_source(q):
    got = episodes.annual(q, ["USA"], ["gdp_growth"], 2009, 2009)
    assert got[("USA", "gdp_growth")] == {2009: -2.5}


def test_episode_page(q):
    p = episodes.page(q, "gfc", 2020)
    assert p["episode"]["title"] == "Global financial crisis"
    assert p["hit"][0] == {"entity_id": "ISL", "name": "Iceland", "value": -6.0}
    assert {h["entity_id"] for h in p["hit"]} >= {"USA", "AUS"}
    usa = next(r for r in p["table"] if r["entity"] == "USA")
    assert usa["values"]["gdp_growth"]["before"] == 2.5 and usa["values"]["inflation"]["during"] == 2.0
    growth = next(c for c in p["charts"] if c["indicator"] == "gdp_growth")
    assert growth["name"] == "GDP growth" and growth["lines"]
    assert "today" in p["like"] and p["like"]["run_up_years"] == [2004, 2006]
    assert episodes.page(q, "no-such-episode") is None


def test_listing_names_the_worst_hit(q):
    gfc = next(e for e in episodes.listing(q, 2020)["episodes"] if e["id"] == "gfc")
    assert gfc["worst"]["entity"] == "ISL" and gfc["worst"]["fall"] == -6.0
