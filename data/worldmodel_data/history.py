"""The long view: long_series, polities and history_events, made by the build from
src.raw_long_series, src.raw_polities and src.raw_history_events (the latest vintage of
each source; see connectors/history.py).

* long_series: each source code matched to an entity (ISO3 country codes, "World");
* polities: each shape given one of history.yaml's regions by the centre of its largest
  piece (the Pacific too);
* history_events: each event given a country (from its ISO3 code) and a region (from its
  place), one row per event.
"""

from __future__ import annotations

import duckdb

from worldmodel_contract import catalogue

LONG_DDL = """CREATE TABLE long_series (entity_id VARCHAR, series_id VARCHAR, year INTEGER, value DOUBLE,
    source_id VARCHAR, vintage VARCHAR)"""
POLITIES_DDL = """CREATE TABLE polities (polity_key VARCHAR, name VARCHAR, from_year INTEGER, to_year INTEGER,
    area_km2 DOUBLE, composite BOOLEAN, components VARCHAR, member_of VARCHAR, wikipedia VARCHAR, wikidata VARCHAR,
    region VARCHAR, lat DOUBLE, lon DOUBLE, west DOUBLE, south DOUBLE, east DOUBLE, north DOUBLE, geojson VARCHAR,
    source_id VARCHAR, vintage VARCHAR)"""
EVENTS_DDL = """CREATE TABLE history_events (event_id VARCHAR, kind VARCHAR, title VARCHAR, year INTEGER,
    end_year INTEGER, month INTEGER, day INTEGER, lat DOUBLE, lon DOUBLE, place VARCHAR, entity_id VARCHAR,
    region VARCHAR, deaths DOUBLE, size DOUBLE, size_unit VARCHAR, links INTEGER, url VARCHAR, source_id VARCHAR,
    vintage VARCHAR)"""


def region_boxes() -> list[tuple[str, float, float, float, float]]:
    """(region id, west, south, east, north), in the order they are tried; the Pacific last."""
    h = catalogue.history()
    out = []
    for r in [*h["regions"], h["pacific"]]:
        for w, s, e, n in r["boxes"]:
            out.append((r["id"], float(w), float(s), float(e), float(n)))
    return out


def region_sql(lat: str, lon: str) -> str:
    """A SQL CASE giving the region of a point."""
    whens = " ".join(f"WHEN {lon} BETWEEN {w} AND {e} AND {lat} BETWEEN {s} AND {n} THEN '{rid}'"
                     for rid, w, s, e, n in region_boxes())
    return f"CASE {whens} ELSE NULL END"


def compute(con: duckdb.DuckDBPyConnection) -> tuple[int, int, int]:
    """Create the three tables (empty when no source has a vintage). Returns their row counts."""
    con.execute(LONG_DDL)
    con.execute(POLITIES_DDL)
    con.execute(EVENTS_DDL)
    # Source codes: ISO3 as an entity's own id or one of its iso3 codes; "World" by name.
    con.execute("""
        INSERT INTO long_series
        WITH codes AS (
            SELECT DISTINCT code, entity_id FROM (
                SELECT iso3 AS code, entity_id FROM src.entities WHERE iso3 IS NOT NULL
                UNION ALL SELECT code, entity_id FROM src.entity_codes WHERE scheme = 'iso3'))
        SELECT coalesce(c.entity_id, CASE WHEN r.scheme = 'name' AND r.source_code = 'World' THEN 'world' END) AS entity_id,
               r.series_id, r.year, r.value, r.source_id, r.vintage
        FROM src.raw_long_series r
        LEFT JOIN (SELECT code, min(entity_id) AS entity_id FROM codes GROUP BY code) c
               ON r.scheme = 'iso3' AND c.code = r.source_code
        WHERE coalesce(c.entity_id, CASE WHEN r.scheme = 'name' AND r.source_code = 'World' THEN 'world' END) IS NOT NULL
          AND r.value IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY 1, r.series_id, r.year,
                                   coalesce(c.entity_id, 'world') ORDER BY r.vintage DESC) = 1""")
    con.execute(f"""
        INSERT INTO polities
        SELECT polity_key, name, from_year, to_year, area_km2, composite, components, member_of, wikipedia, wikidata,
               {region_sql('lat', 'lon')} AS region, lat, lon, west, south, east, north, geojson, source_id, vintage
        FROM src.raw_polities
        WHERE from_year IS NOT NULL AND to_year IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY polity_key ORDER BY vintage DESC) = 1""")
    con.execute(f"""
        INSERT INTO history_events
        SELECT e.event_key, e.kind, e.title, e.year, e.end_year, e.month, e.day, e.lat, e.lon, e.place,
               ent.entity_id, CASE WHEN e.lat IS NULL THEN NULL ELSE {region_sql('e.lat', 'e.lon')} END,
               e.deaths, e.size, e.size_unit, e.links, e.url, e.source_id, e.vintage
        FROM src.raw_history_events e
        LEFT JOIN (SELECT iso3, min(entity_id) AS entity_id FROM src.entities WHERE iso3 IS NOT NULL GROUP BY iso3) ent
               ON ent.iso3 = e.country_code
        WHERE e.year IS NOT NULL AND e.title IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY e.event_key ORDER BY e.vintage DESC) = 1""")
    return tuple(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # type: ignore[return-value]
                 for t in ("long_series", "polities", "history_events"))
