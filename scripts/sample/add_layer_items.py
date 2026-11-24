"""Add the map layer details table (schema 1.14.0) to the app's sample warehouse.

    python scripts/sample/add_layer_items.py [sample.duckdb]

Lists the items of the sample's dot layers (airports and volcanoes) with the country each
names, so the Details page behind a map layer has something to show."""

import json
import sys
from pathlib import Path

import duckdb

from worldmodel_contract import layer_details as spec
from worldmodel_data.layer_tables import COLUMNS, DDL, Placer, items

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"


def main(db: str = str(SAMPLE)) -> None:
    con = duckdb.connect(db)
    try:
        con.execute("DROP TABLE IF EXISTS layer_items")
        con.execute(f"CREATE TABLE layer_items ({DDL})")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        con.execute("CREATE OR REPLACE TABLE src.entities AS SELECT * FROM main.entities")
        con.execute("CREATE OR REPLACE TABLE src.entity_codes AS SELECT * FROM main.entity_codes")
        placer = Placer(con, None)
        cols = list(COLUMNS)
        for layer_id, geojson, source_id, vintage in con.execute(
                "SELECT layer_id, geojson, source_id, vintage FROM layers WHERE kind = 'point'").fetchall():
            d = spec.BY_ID.get(layer_id)
            if d is None or d.kind != "stored":
                continue
            rows = items(d, json.loads(geojson)["features"], placer)
            con.executemany(f"INSERT INTO layer_items ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [(layer_id, *r, source_id, vintage) for r in rows])
        print(dict(con.execute("SELECT layer_id, count(*) FROM layer_items GROUP BY 1").fetchall()))
        con.execute("DROP SCHEMA src CASCADE")
        con.execute("UPDATE meta SET value = '1.14.0' WHERE key = 'schema_version'")
        con.execute("CHECKPOINT")
    finally:
        con.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
