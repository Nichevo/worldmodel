"""Transport and networks tables: geo_features, port_traffic, chokepoint_traffic and
airport_traffic, made by the build from src.raw_<table> (the latest vintage of each
source; see connectors/transport.py and networks.py). Country codes become entity ids."""

from __future__ import annotations

import duckdb

DDL = {
    "geo_features": ("layer_id VARCHAR, feature_id VARCHAR, name VARCHAR, rank INTEGER, props VARCHAR, countries VARCHAR, "
                     "west DOUBLE, south DOUBLE, east DOUBLE, north DOUBLE, geojson VARCHAR, source_id VARCHAR, vintage VARCHAR"),
    "port_traffic": ("port_id VARCHAR, entity_id VARCHAR, year INTEGER, month INTEGER, calls DOUBLE, import_t DOUBLE, "
                     "export_t DOUBLE, source_id VARCHAR, vintage VARCHAR"),
    "chokepoint_traffic": ("chokepoint_id VARCHAR, name VARCHAR, day DATE, transits DOUBLE, tankers DOUBLE, container DOUBLE, "
                           "dry_bulk DOUBLE, cargo DOUBLE, capacity DOUBLE, source_id VARCHAR, vintage VARCHAR"),
    "airport_traffic": ("airport VARCHAR, name VARCHAR, entity_id VARCHAR, year INTEGER, passengers DOUBLE, freight_t DOUBLE, "
                        "source_id VARCHAR, vintage VARCHAR"),
}
ISO3 = "(SELECT iso3, min(entity_id) AS entity_id FROM src.entities WHERE iso3 IS NOT NULL GROUP BY iso3)"
LATEST = "(SELECT source_id, max(vintage) AS vintage FROM src.raw_{t} GROUP BY source_id)"


def compute(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Create the four tables (empty when no source has a vintage). Returns their row counts."""
    for t, cols in DDL.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    # Each source's latest vintage as a whole: a cable gone from the map is gone.
    con.execute(f"""INSERT INTO geo_features
        SELECT g.layer_id, g.feature_id, g.name, g.rank, g.props, g.countries, g.west, g.south, g.east, g.north,
               g.geojson, g.source_id, g.vintage
        FROM src.raw_geo_features g JOIN {LATEST.format(t='geo_features')} l USING (source_id, vintage)
        WHERE g.geojson IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY g.layer_id, g.feature_id ORDER BY g.vintage DESC) = 1""")
    con.execute(f"""INSERT INTO port_traffic
        SELECT p.port_id, c.entity_id, p.year, p.month, p.calls, p.import_t, p.export_t, p.source_id, p.vintage
        FROM src.raw_port_traffic p LEFT JOIN {ISO3} c ON c.iso3 = p.country_code
        QUALIFY row_number() OVER (PARTITION BY p.port_id, p.year, p.month ORDER BY p.vintage DESC) = 1""")
    con.execute("""INSERT INTO chokepoint_traffic
        SELECT chokepoint_id, name, day, transits, tankers, container, dry_bulk, cargo, capacity, source_id, vintage
        FROM src.raw_chokepoint_traffic
        QUALIFY row_number() OVER (PARTITION BY chokepoint_id, day ORDER BY vintage DESC) = 1""")
    con.execute(f"""INSERT INTO airport_traffic
        SELECT a.airport, a.name, c.entity_id, a.year, a.passengers, a.freight_t, a.source_id, a.vintage
        FROM src.raw_airport_traffic a LEFT JOIN {ISO3} c ON c.iso3 = a.country_code
        QUALIFY row_number() OVER (PARTITION BY a.airport, a.year ORDER BY a.vintage DESC) = 1""")
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in DDL}
