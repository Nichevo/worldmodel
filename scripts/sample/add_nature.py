"""Add the pollution and nature tables (schema 1.9.0) to the app's sample warehouse.

    python scripts/sample/add_nature.py [sample.duckdb]

zone_grids, protected_areas, species_status and pest_presence are created empty: the
sample shows the pages' "not loaded yet" notes for them until a refresh. The curated
animal disease, pest and pollution events (nature.yaml) are added to events."""

import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

from worldmodel_data import nature_tables
from worldmodel_data.connectors.nature import NatureCurated
from worldmodel_data.vintage_store import HISTORY_COLUMNS

SAMPLE = Path(__file__).resolve().parents[2] / "app" / "sample" / "worldmodel-sample.duckdb"


def main(db: str = str(SAMPLE)) -> None:
    raw = Path(tempfile.mkdtemp())
    con = duckdb.connect(db)
    try:
        for t in nature_tables.DDL:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        for name, cols in HISTORY_COLUMNS.items():
            con.execute(f"CREATE OR REPLACE TABLE src.raw_{name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        con.execute("CREATE OR REPLACE TABLE src.entities AS SELECT * FROM main.entities")
        print(nature_tables.compute(con))
        con.execute("DROP SCHEMA src CASCADE")
        # The curated events, as a build would add them.
        c = NatureCurated()
        c.download(raw, "sample")
        staging = duckdb.connect()
        c.stage(staging, raw, "sample", "sample")
        ev = staging.execute(c.events_query).fetchall()
        cols = [d[0] for d in staging.description]
        have = [r[0] for r in con.execute("DESCRIBE events").fetchall()]
        con.execute("DELETE FROM events WHERE source_id = 'nature_curated'")
        for r in ev:
            d = dict(zip(cols, r))
            d["entity_id"] = d.pop("source_code")
            d["event_id"] = f"{d['source_id']}:{d['event_key']}"
            con.execute(f"INSERT INTO events ({', '.join(k for k in have if k in d)}) VALUES ({', '.join('?' for k in have if k in d)})",
                        [d[k] for k in have if k in d])
        print(f"{len(ev)} curated events")
        con.execute("UPDATE meta SET value = '1.9.0' WHERE key = 'schema_version'")
        con.execute("CHECKPOINT")
        compact = Path(db).with_suffix(".compact")
        compact.unlink(missing_ok=True)
        con.execute(f"ATTACH '{compact.as_posix()}' AS compact")
        name = con.execute("SELECT current_database()").fetchone()[0]
        con.execute(f'COPY FROM DATABASE "{name}" TO compact')
        con.execute("DETACH compact")
    finally:
        con.close()
        shutil.rmtree(raw, ignore_errors=True)
    compact.replace(db)


if __name__ == "__main__":
    main(*sys.argv[1:])
