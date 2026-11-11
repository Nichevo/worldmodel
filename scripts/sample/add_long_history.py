"""Add the Long history tables (schema 1.8.0) to the app's sample warehouse.

    python scripts/sample/add_long_history.py <cliopatria geojson or zip> [sample.duckdb]

Borders come from the real Cliopatria file, only the powers and dynasties in history.yaml,
simplified harder than a refresh does (about 20 km) so the sample stays small. long_series and history_events are left empty: the
sample shows the page's "not loaded yet" notes for them until a refresh."""

import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue

from worldmodel_data import history
from worldmodel_data.connectors import history as conn
from worldmodel_data.vintage_store import HISTORY_COLUMNS

SAMPLE = Path(__file__).resolve().parents[2] / "app" / "sample" / "worldmodel-sample.duckdb"


def main(src: str, db: str = str(SAMPLE)) -> None:
    raw = Path(tempfile.mkdtemp())
    shutil.copy(src, raw / Path(src).name)
    c = conn.Cliopatria()
    c.tolerance = 0.2
    con = duckdb.connect(db)
    try:
        for t in ("long_series", "polities", "history_events"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        staging = duckdb.connect()
        c.stage(staging, raw, "sample", "sample")
        keep = {n for p in catalogue.history_powers().values() for n in p.get("polities") or []}
        rows = [r for r in staging.execute(c.history_queries["polities"]).fetchall() if r[1] in keep]
        for name, cols in HISTORY_COLUMNS.items():
            con.execute(f"CREATE OR REPLACE TABLE src.raw_{name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        con.executemany(f"INSERT INTO src.raw_polities VALUES ('cliopatria', 'sample', {', '.join('?' * 17)})", rows)
        for name in ("entities", "entity_codes"):
            con.execute(f"CREATE OR REPLACE TABLE src.{name} AS SELECT * FROM main.{name}")
        print(history.compute(con))
        con.execute("DROP SCHEMA src CASCADE")
        con.execute("UPDATE meta SET value = '1.8.0' WHERE key = 'schema_version'")
        con.execute("CHECKPOINT")
        # Copy into a fresh file: dropped and rewritten tables leave free blocks behind.
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
