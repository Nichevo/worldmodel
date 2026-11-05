"""Indicator quality: the six scores, the grade, the measure type, and what changed between builds."""

from datetime import date

import duckdb

from worldmodel_contract import quality as q


def test_measure_types():
    assert q.measure_type("gdp_per_capita_usd", "GDP per person, current US dollars", "US$") == "per_person"
    assert q.measure_type("inflation", "Inflation", "%") == "rate"
    assert q.measure_type("gdp_usd", "GDP, current US dollars", "US$") == "money"
    assert q.measure_type("hdi", "Human Development Index", "index (0-1)") == "index"
    assert q.measure_type("pop_total", "Population", "persons") == "count"
    assert q.measure_type("co2_kt", "CO2 emissions", "kt") == "level"


def test_grade_weights_and_the_exploratory_cap():
    top = dict(history=5, up_to_date=5, coverage=5, standing=5, health=5, definition=5)
    assert q.grade_of(top, "standard") == "A"
    assert q.grade_of({**top, "definition": 2}, "exploratory") == "C"  # never core, however full
    assert q.grade_of(dict(history=1, up_to_date=1, coverage=1, standing=2, health=3, definition=4), "established") == "D"


def test_scores_from_a_small_warehouse():
    con = duckdb.connect()
    con.execute("CREATE TABLE indicators AS SELECT * FROM (VALUES ('good', 'Good thing', '%', 'A', 0.0, 100.0), "
                "('thin', 'Thin thing', 'persons', 'A', NULL, NULL), ('none', 'Nothing yet', '%', 'A', NULL, NULL)) "
                "t(indicator_id, name, unit, frequency, bound_min, bound_max)")
    con.execute("CREATE TABLE indicator_sources AS SELECT * FROM (VALUES ('good', 'world_bank_wdi', 1), ('thin', 'numbeo', 1)) "
                "t(indicator_id, source_id, rank)")
    countries = [f"C{i:03d}" for i in range(160)] + ["NZL", "AUS", "GBR", "USA"]
    con.execute("CREATE TABLE entities AS SELECT unnest(?) AS entity_id, 'country' AS type", [countries])
    rows = [(c, "good", date(y, 1, 1), 50.0 + (y % 3)) for c in countries for y in range(1960, 2025)]
    rows += [("C000", "thin", date(2019, 1, 1), 10.0), ("C001", "thin", date(2020, 1, 1), 2000.0)]
    con.execute("CREATE TABLE series (entity_id TEXT, indicator_id TEXT, period_start DATE, value DOUBLE)")
    con.executemany("INSERT INTO series VALUES (?, ?, ?, ?)", rows)
    con.execute("""CREATE OR REPLACE TABLE series AS SELECT *, 'A' AS freq, '' AS breakdown, 'central' AS variant, 'E' AS status,
        (SELECT source_id FROM indicator_sources r WHERE r.indicator_id = series.indicator_id) AS source_id FROM series""")
    got = q.compute(con, today=date(2026, 6, 1))
    assert got["good"]["grade"] == "A" and got["good"]["scores"]["coverage"] == 5 and got["good"]["type"] == "rate"
    thin = got["thin"]
    assert thin["scores"]["history"] == 1 and thin["scores"]["standing"] == 2 and thin["definition"] == "exploratory"
    assert thin["grade"] in ("C", "D") and "NZL" in thin["notes"]["coverage"]
    assert got["none"]["scores"]["history"] == 1 and "no figures" in got["none"]["notes"]["history"]


def test_changes_between_builds():
    before = {"x": {"grade": "A", "scores": {"up_to_date": 4, "health": 5}}, "y": {"grade": "C", "scores": {"up_to_date": 5, "health": 5}}}
    after = {"x": {"grade": "B", "scores": {"up_to_date": 2, "health": 3}, "notes": {"up_to_date": "old", "health": "breaks"}},
             "y": {"grade": "B", "scores": {"up_to_date": 5, "health": 5}}}
    ch = q.changes(before, after, {"x"})
    assert ch["lost"] == [{"indicator_id": "x", "from": "A", "to": "B"}] and ch["gained"][0]["indicator_id"] == "y"
    assert ch["stale"][0]["note"] == "old" and ch["flagged"][0]["note"] == "breaks" and ch["starred_fell"] == ch["lost"]


def test_saved_per_build_and_the_one_before(tmp_path):
    q.save(tmp_path, "20261101T000000Z", {"x": {"grade": "A"}})
    q.save(tmp_path, "20261105T000000Z", {"x": {"grade": "B"}})
    assert q.load(tmp_path, "20261105T000000Z") == {"x": {"grade": "B"}}
    assert q.previous(tmp_path, "20261105T000000Z") == ("20261101T000000Z", {"x": {"grade": "A"}})
    assert q.previous(tmp_path, "20261101T000000Z") is None

