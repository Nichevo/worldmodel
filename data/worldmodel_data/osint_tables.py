"""Tables for the detail from the OSINT communities, made by the build from src.raw_<table>
(see connectors/conflict_events.py, wars.py, sanctions_now.py, military.py):

* conflict_events: UCDP's yearly events, then its candidate events only after the last day
  the yearly dataset covers, and ACLED's; countries matched to entity ids.
* war_losses, war_areas: every day held across vintages (Oryx keeps a file per day).
* sanction_counts, sanction_listings, military_strength, arms_deals: the latest vintage.

Each table is created empty when no source has a vintage, so the app can always query it."""

from __future__ import annotations

import duckdb

DDL = {
    "conflict_events": ("event_id VARCHAR, entity_id VARCHAR, day DATE, end_day DATE, kind VARCHAR, subkind VARCHAR, "
                        "deaths DOUBLE, deaths_low DOUBLE, deaths_high DOUBLE, civilians DOUBLE, lat DOUBLE, lon DOUBLE, "
                        "place VARCHAR, admin1 VARCHAR, actors VARCHAR, note VARCHAR, geo_precision INTEGER, "
                        "source_id VARCHAR, vintage VARCHAR"),
    "war_losses": ("war_id VARCHAR, side VARCHAR, day DATE, category VARCHAR, status VARCHAR, count DOUBLE, basis VARCHAR, "
                   "source_id VARCHAR, vintage VARCHAR"),
    "war_areas": "war_id VARCHAR, day DATE, holder VARCHAR, land_of VARCHAR, area_km2 DOUBLE, source_id VARCHAR, vintage VARCHAR",
    "sanction_counts": ("target VARCHAR, authority VARCHAR, schema VARCHAR, listed INTEGER, added_365 INTEGER, "
                        "source_id VARCHAR, vintage VARCHAR"),
    "sanction_listings": ("os_id VARCHAR, name VARCHAR, schema VARCHAR, targets VARCHAR, authorities VARCHAR, first_seen DATE, "
                          "last_change DATE, identifiers VARCHAR, source_id VARCHAR, vintage VARCHAR"),
    "military_strength": "entity_id VARCHAR, edition INTEGER, measure VARCHAR, value DOUBLE, source_id VARCHAR, vintage VARCHAR",
    "arms_deals": ("supplier VARCHAR, recipient VARCHAR, ordered INTEGER, delivered_from INTEGER, delivered_to INTEGER, "
                   "weapon VARCHAR, description VARCHAR, number DOUBLE, tiv DOUBLE, status VARCHAR, source_id VARCHAR, vintage VARCHAR"),
}
ISO3 = "(SELECT iso3, min(entity_id) AS entity_id FROM src.entities WHERE iso3 IS NOT NULL GROUP BY iso3)"
LATEST = "QUALIFY vintage = max(vintage) OVER (PARTITION BY source_id)"


def compute(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    for t, cols in DDL.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    # Located events: the latest vintage of each source; candidate events only after the yearly dataset ends.
    con.execute(f"""CREATE TEMP TABLE ce_latest AS SELECT * FROM src.raw_conflict_events {LATEST}""")
    con.execute(f"""INSERT INTO conflict_events SELECT e.event_id, coalesce(c.entity_id, e.country_code), e.day, e.end_day,
        e.kind, e.subkind, e.deaths, e.deaths_low, e.deaths_high, e.civilians, e.lat, e.lon, e.place, e.admin1, e.actors,
        e.note, e.geo_precision, e.source_id, e.vintage
        FROM ce_latest e LEFT JOIN {ISO3} c ON c.iso3 = e.country_code
        WHERE e.source_id <> 'ucdp_candidate'
           OR e.day > coalesce((SELECT max(day) FROM ce_latest WHERE source_id = 'ucdp_ged'), DATE '1900-01-01')""")
    con.execute("DROP TABLE ce_latest")
    # Loss totals: every vintage's days, the newest vintage winning for a day it holds twice.
    con.execute("""INSERT INTO war_losses SELECT war_id, side, day, category, status, count, basis, source_id, vintage
        FROM src.raw_war_losses QUALIFY row_number() OVER (PARTITION BY war_id, side, day, category, status, basis
                                                            ORDER BY vintage DESC) = 1""")
    con.execute("""INSERT INTO war_areas SELECT war_id, day, holder, land_of, area_km2, source_id, vintage
        FROM src.raw_war_areas QUALIFY row_number() OVER (PARTITION BY war_id, day, holder ORDER BY vintage DESC) = 1""")
    con.execute(f"""INSERT INTO sanction_counts SELECT target, authority, schema, listed, added_365, source_id, vintage
        FROM src.raw_sanction_counts {LATEST}""")
    con.execute(f"""INSERT INTO sanction_listings SELECT os_id, name, schema, targets, authorities, first_seen, last_change,
        identifiers, source_id, vintage FROM src.raw_sanction_listings {LATEST}""")
    con.execute(f"""INSERT INTO military_strength SELECT c.entity_id, m.edition, m.measure, m.value, m.source_id, m.vintage
        FROM (SELECT * FROM src.raw_military_strength {LATEST}) m JOIN {ISO3} c ON c.iso3 = m.country_code""")
    con.execute(f"""INSERT INTO arms_deals SELECT supplier, recipient, ordered, delivered_from, delivered_to, weapon,
        description, number, tiv, status, source_id, vintage FROM src.raw_arms_deals {LATEST}""")
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in DDL}
