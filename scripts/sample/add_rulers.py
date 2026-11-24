"""Add rulers and a few events far back (schema 1.15.0) to the app's sample warehouse.

    python scripts/sample/add_rulers.py [sample.duckdb]

Stages the wikidata_history test fixtures (a few battles, plagues, famous buildings, cities,
a religion, writing and rulers) and puts their rows in the sample's history_events and the
new history_rulers table, so the World-in-year map has something to show without a refresh.
The fixtures' made-up rulers (ids Q999...) are left out."""

import sys
from pathlib import Path

import duckdb

from worldmodel_data import history
from worldmodel_data.connectors.history import WikidataHistory

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"
FIXTURES = ROOT / "data" / "tests" / "fixtures" / "wikidata_history"


def main(db: str = str(SAMPLE)) -> None:
    c = WikidataHistory()
    staging = duckdb.connect()
    c.stage(staging, FIXTURES, "sample", "sample")
    events = staging.execute(c.history_queries["history_events"]).fetchall()
    rulers = [r for r in staging.execute(c.history_queries["history_rulers"]).fetchall() if not r[1].startswith("Q999")]
    con = duckdb.connect(db)
    try:
        con.execute("DROP TABLE IF EXISTS history_rulers")
        con.execute(history.RULERS_DDL)
        con.executemany(f"INSERT INTO history_rulers VALUES ({', '.join('?' * 10)}, 'wikidata_history', 'sample')", rulers)
        con.execute("DELETE FROM history_events WHERE source_id = 'wikidata_history'")
        con.execute(f"CREATE TEMP TABLE hev ({', '.join(f'c{i} {t}' for i, t in enumerate(['VARCHAR'] * 3 + ['INTEGER'] * 4 + ['DOUBLE'] * 2 + ['VARCHAR'] * 2 + ['DOUBLE'] * 2 + ['VARCHAR', 'INTEGER', 'VARCHAR']))})")
        con.executemany(f"INSERT INTO hev VALUES ({', '.join('?' * 16)})", events)
        con.execute(f"""
            INSERT INTO history_events
            SELECT c0, c1, c2, c3, c4, c5, c6, c7, c8, c9, ent.entity_id,
                   CASE WHEN c7 IS NULL THEN NULL ELSE {history.region_sql('c7', 'c8')} END,
                   c11, c12, c13, c14, c15, 'wikidata_history', 'sample'
            FROM hev LEFT JOIN (SELECT iso3, min(entity_id) AS entity_id FROM entities WHERE iso3 IS NOT NULL GROUP BY iso3) ent
                 ON ent.iso3 = hev.c10""")
        print(con.execute("SELECT count(*) FROM history_events").fetchone(), con.execute("SELECT count(*) FROM history_rulers").fetchone())
        con.execute("UPDATE meta SET value = '1.15.0' WHERE key = 'schema_version'")
        con.execute("CHECKPOINT")
    finally:
        con.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
