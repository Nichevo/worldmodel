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
SOURCES = ("un_wpp", "geonames", "bis", "wikidata_places")

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
