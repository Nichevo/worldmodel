"""Map layer details: every dot layer's items with a country (named by the source, or worked
out from where it sits), and the map_layers indicators the main page can show."""

import json
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.layer_tables import Placer, items
from worldmodel_data.vintage_store import VintageStore
from worldmodel_contract import layer_details as spec

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "geonames", "bis", "wikidata_places", "usgs_earthquakes")

# Two boxes for countries: New Zealand around Auckland, Australia around Canberra.
COUNTRIES = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"ISO_A3": "NZL", "ADM0_A3": "NZL"},
     "geometry": {"type": "Polygon", "coordinates": [[[165, -48], [179, -48], [179, -34], [165, -34], [165, -48]]]}},
    {"type": "Feature", "properties": {"ISO_A3": "AUS", "ADM0_A3": "AUS"},
     "geometry": {"type": "Polygon", "coordinates": [[[113, -44], [154, -44], [154, -10], [113, -10], [113, -44]]]}},
]}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    shapes = home.raw / "internet_speed" / "2026-01" / "20260101T000000Z" / "ne_50m_admin_0_countries.geojson"
    shapes.parent.mkdir(parents=True, exist_ok=True)
    shapes.write_text(json.dumps(COUNTRIES), encoding="utf-8")
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def test_items_get_the_country_their_source_names(built):
    _, con = built
    rows = con.execute("SELECT name, entity_id, size, placed FROM layer_items WHERE layer_id = 'hospitals'").fetchall()
    h = {r[0]: r[1:] for r in rows}
    assert h["Auckland City Hospital"] == ("NZL", 1100, False)
    bases = dict(con.execute("SELECT name, category FROM layer_items WHERE layer_id = 'military_bases'").fetchall())
    assert bases["RNZAF Base Ohakea"] == "air base"


def test_count_and_per_million_are_indicators(built):
    _, con = built
    got = dict(con.execute("""SELECT indicator_id, value FROM series WHERE entity_id = 'NZL' AND source_id = 'map_layers'
                              AND indicator_id LIKE 'map_hospitals_%'""").fetchall())
    n = con.execute("SELECT count(DISTINCT item_id) FROM layer_items WHERE layer_id = 'hospitals' AND entity_id = 'NZL'").fetchone()[0]
    assert got["map_hospitals_count"] == n and got["map_hospitals_beds"] >= 1100
    assert got["map_hospitals_per_m"] > 0  # with the population of the nearest year
    ind = con.execute("SELECT name, agg_method FROM indicators WHERE indicator_id = 'map_hospitals_count'").fetchone()
    assert ind == ("Hospitals on the map", "sum")


def test_earthquakes_count_magnitude_6_or_more_each_year(built):
    _, con = built
    # Kaikoura 7.8 (2016) and Wellington's 3.4 (2024, GeoNet) are both NZ items; only the 6+ one counts, in its own year.
    mags = sorted(r[0] for r in con.execute("SELECT size FROM layer_items WHERE layer_id = 'earthquakes' AND entity_id = 'NZL'").fetchall())
    assert 3.4 in mags and 7.8 in mags
    got = dict(con.execute("""SELECT year(period_start), value FROM series WHERE entity_id = 'NZL'
                              AND indicator_id = 'map_earthquakes_count'""").fetchall())
    assert got.get(2016) == 1 and 2024 not in got
    assert not con.execute("SELECT count(*) FROM indicators WHERE indicator_id = 'map_earthquakes_per_m'").fetchone()[0]


def test_items_without_a_country_are_placed_from_where_they_sit(tmp_path):
    shapes = tmp_path / "ne.geojson"
    shapes.write_text(json.dumps(COUNTRIES), encoding="utf-8")
    con = duckdb.connect()
    con.execute("CREATE SCHEMA src")
    con.execute("CREATE TABLE src.entities AS SELECT * FROM (VALUES ('NZL'), ('AUS')) t(entity_id)")
    con.execute("CREATE TABLE src.entity_codes AS SELECT * FROM (VALUES ('iso3', 'NZL', 'NZL', NULL), ('iso2', 'NZ', 'NZL', NULL), "
                "('iso3', 'AUS', 'AUS', NULL)) t(scheme, code, entity_id, valid_to)")
    placer = Placer(con, shapes)
    feats = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [174.76, -36.85]}, "properties": {"name": "Auckland Uni"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [149.1, -35.3]}, "properties": {"name": "ANU", "students": "25,000"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-150, 0]}, "properties": {"name": "Mid ocean"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [174, -41]}, "properties": {"name": "Shared", "countries": "NZL,AUS"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [174, -41]}, "properties": {"name": "By code", "country": "NZ"}},
    ]
    got = {(r[1], r[2]): r for r in items(spec.BY_ID["universities"], feats, placer)}
    assert got[("Auckland Uni", "NZL")][-1] is True  # placed from where it sits
    assert got[("ANU", "AUS")][5] == 25000
    assert ("Mid ocean", None) in got
    assert ("Shared", "NZL") in got and ("Shared", "AUS") in got
    assert got[("By code", "NZL")][-1] is False


def test_insert_many_in_chunks():
    from worldmodel_data.layer_tables import insert_many

    con = duckdb.connect()
    con.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
    insert_many(con, "t", ["a", "b"], [(i, str(i)) for i in range(1203)], per=500)
    assert con.execute("SELECT count(*), sum(a) FROM t").fetchone() == (1203, sum(range(1203)))
    insert_many(con, "t", ["a", "b"], [])  # nothing to add is fine


def test_a_slip_in_layer_details_does_not_stop_the_build(tmp_path, monkeypatch):
    """The details pages are left empty; the rest of the warehouse builds as before."""
    from worldmodel_data import layer_tables

    def boom(con, raw, today=None):
        con.execute(f"CREATE TABLE src.raw_layer_items ({layer_tables.DDL})")
        raise RuntimeError("bad layer")

    monkeypatch.setattr(layer_tables, "prepare", boom)
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    con = duckdb.connect(str(result.path), read_only=True)
    assert con.execute("SELECT count(*) FROM layer_items").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM series WHERE source_id = 'map_layers'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM series").fetchone()[0] > 0


def test_a_slip_after_a_good_build_does_not_fail_the_shrinkage_check(tmp_path, monkeypatch):
    """The live build has map layer figures; the next build's layer step fails. Losing those
    figures on purpose must not fail the 'series shrank' check and stop the build."""
    from worldmodel_data import layer_tables

    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    first = build(home)
    con = duckdb.connect(str(first.path), read_only=True)
    had = con.execute("SELECT count(*) FROM series WHERE source_id = 'map_layers'").fetchone()[0]
    con.close()

    def boom(con, raw, today=None):
        raise RuntimeError("bad layer")

    monkeypatch.setattr(layer_tables, "prepare", boom)
    second = build(home)
    shrunk = [c for c in second.checks if c.check_id.startswith("shrinkage:map_layers")]
    assert all(c.status == "warn" for c in shrunk)
    if had:
        assert shrunk


def test_a_layer_without_figures_of_its_own_is_skipped_for_indicators():
    """Chokepoints have a details page but no count indicators; one placed in a country must not stop the step."""
    from datetime import date

    from worldmodel_contract.schema import TABLES
    from worldmodel_data import layer_tables

    con = duckdb.connect()
    con.execute("CREATE SCHEMA src")
    for name in ("indicators", "indicator_sources", "vintages"):
        con.execute(f"CREATE TABLE src.{name} ({', '.join(f'{c} {t}' for c, t in TABLES[name].columns.items())})")
    con.execute("CREATE TABLE src.raw_observations (source_id VARCHAR, vintage VARCHAR, scheme VARCHAR, source_code VARCHAR, "
                "indicator_id VARCHAR, period_start DATE, freq VARCHAR, breakdown VARCHAR, variant VARCHAR, value DOUBLE, status VARCHAR)")
    con.execute("CREATE TABLE src.entity_codes (scheme VARCHAR, code VARCHAR, entity_id VARCHAR, valid_to DATE)")
    con.execute(f"CREATE TABLE src.raw_layer_items ({layer_tables.DDL})")
    cols = list(layer_tables.COLUMNS)
    row = {c: None for c in cols} | {"layer_id": "chokepoints", "item_id": "suez", "name": "Suez Canal", "entity_id": "EGY"}
    layer_tables.insert_many(con, "src.raw_layer_items", cols, [tuple(row[c] for c in cols)])
    row = row | {"layer_id": "airports", "item_id": "NZAA", "name": "Auckland", "entity_id": "NZL"}
    layer_tables.insert_many(con, "src.raw_layer_items", cols, [tuple(row[c] for c in cols)])
    layer_tables._indicators(con, {"chokepoints", "airports"}, date(2026, 1, 1))
    got = con.execute("SELECT indicator_id, source_code, value FROM src.raw_observations").fetchall()
    assert ("map_airports_count", "NZL", 1.0) in got and not any("chokepoints" in r[0] for r in got)


def test_a_retired_indicator_only_warns(tmp_path):
    """map_earthquakes_per_m was dropped on purpose: its rows going must not stop the build."""
    from worldmodel_data import gates

    prev = tmp_path / "prev.duckdb"
    with duckdb.connect(str(prev)) as c:
        c.execute("CREATE TABLE series AS SELECT * FROM (VALUES ('map_layers', 'map_earthquakes_per_m'), "
                  "('map_layers', 'map_hospitals_count')) t(source_id, indicator_id)")
    now = duckdb.connect()
    now.execute("CREATE TABLE series (source_id VARCHAR, indicator_id VARCHAR)")
    got = {c.check_id: c.status for c in gates.shrinkage(now, prev, allow_shrink=False)}
    assert got["shrinkage:map_layers:map_earthquakes_per_m"] == "warn"
    assert got["shrinkage:map_layers:map_hospitals_count"] == "fail"
