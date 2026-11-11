"""Pollution and nature tables: zone_grids, protected_areas, species_status and
pest_presence, made by the build from src.raw_<table> (the latest vintage of each source;
see connectors/nature.py). Country codes become entity ids."""

from __future__ import annotations

import duckdb

DDL = {
    "zone_grids": "period VARCHAR, scenario VARCHAR, width INTEGER, height INTEGER, grid BLOB, source_id VARCHAR, vintage VARCHAR",
    "protected_areas": ("wdpa_id VARCHAR, name VARCHAR, designation VARCHAR, iucn_cat VARCHAR, entity_id VARCHAR, marine VARCHAR, "
                        "area_km2 DOUBLE, year INTEGER, lat DOUBLE, lon DOUBLE, west DOUBLE, south DOUBLE, east DOUBLE, "
                        "north DOUBLE, geojson VARCHAR, source_id VARCHAR, vintage VARCHAR"),
    "species_status": "entity_id VARCHAR, scientific_name VARCHAR, category VARCHAR, year INTEGER, url VARCHAR, source_id VARCHAR, vintage VARCHAR",
    "pest_presence": ("pest_code VARCHAR, pest_name VARCHAR, entity_id VARCHAR, state VARCHAR, status VARCHAR, present BOOLEAN, "
                      "source_id VARCHAR, vintage VARCHAR"),
}
ISO3 = "(SELECT iso3, min(entity_id) AS entity_id FROM src.entities WHERE iso3 IS NOT NULL GROUP BY iso3)"


def compute(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Create the four tables (empty when no source has a vintage). Returns their row counts."""
    for t, cols in DDL.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    con.execute("""INSERT INTO zone_grids SELECT period, scenario, width, height, grid, source_id, vintage FROM src.raw_zone_grids
                   QUALIFY row_number() OVER (PARTITION BY period, scenario ORDER BY vintage DESC) = 1""")
    con.execute(f"""INSERT INTO protected_areas
        SELECT p.wdpa_id, p.name, p.designation, p.iucn_cat, c.entity_id, p.marine, p.area_km2, p.year, p.lat, p.lon,
               p.west, p.south, p.east, p.north, p.geojson, p.source_id, p.vintage
        FROM src.raw_protected_areas p LEFT JOIN {ISO3} c ON c.iso3 = p.country_code
        WHERE p.geojson IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY p.wdpa_id ORDER BY p.vintage DESC) = 1""")
    con.execute("""INSERT INTO species_status SELECT country_code, scientific_name, category, year, url, source_id, vintage
        FROM src.raw_species_status
        QUALIFY row_number() OVER (PARTITION BY country_code, scientific_name ORDER BY vintage DESC) = 1""")
    con.execute("""INSERT INTO pest_presence SELECT pest_code, pest_name, country_code, state, status, present, source_id, vintage
        FROM src.raw_pest_presence
        QUALIFY row_number() OVER (PARTITION BY pest_code, country_code, coalesce(state, '') ORDER BY vintage DESC) = 1""")
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in DDL}
