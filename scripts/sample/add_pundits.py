"""Add the Pundits tables (schema 1.13.0) to the app's sample warehouse.

    python scripts/sample/add_pundits.py [sample.duckdb]

Filled from the made-up Prediction Archive pages in data/tests/fixtures/prediction_archive,
so the Pundits tab has something to show before you save real pages."""

import json
import sys
from pathlib import Path

import duckdb

from worldmodel_data import crowd_tables
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import HISTORY_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"
FIXTURES = ROOT / "data" / "tests" / "fixtures"


def main(db: str = str(SAMPLE)) -> None:
    con = duckdb.connect(db)
    try:
        for t in crowd_tables.PUNDIT_DDL:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        for name in ("pundit_scores", "pundit_calls"):
            cols = HISTORY_COLUMNS[name]
            con.execute(f"CREATE OR REPLACE TABLE src.raw_{name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        con.execute("CREATE OR REPLACE TABLE src.entities AS SELECT * FROM main.entities")
        k = CONNECTORS["prediction_archive"]()
        staging = duckdb.connect()
        k.stage(staging, FIXTURES / "prediction_archive", "2026-11-22", "sample")
        for name, q in k.history_queries.items():
            cols = HISTORY_COLUMNS[name]
            names = [c for c in cols if c not in ("source_id", "vintage")]
            sel = ", ".join(f"CAST({c} AS {cols[c]}) AS {c}" for c in names)
            got = staging.execute(f"SELECT 'prediction_archive', 'sample', {sel} FROM ({q})").fetchall()
            con.executemany(f"INSERT INTO src.raw_{name} (source_id, vintage, {', '.join(names)}) "
                            f"VALUES ({', '.join('?' * (len(names) + 2))})", got)
        print(crowd_tables.compute_pundits(con))
        con.execute("DROP SCHEMA src CASCADE")
        con.execute("UPDATE meta SET value = '1.13.0' WHERE key = 'schema_version'")
        con.execute("CHECKPOINT")
        compact = Path(db).with_suffix(".compact")
        compact.unlink(missing_ok=True)
        con.execute(f"ATTACH '{compact.as_posix()}' AS compact")
        name = con.execute("SELECT current_database()").fetchone()[0]
        con.execute(f'COPY FROM DATABASE "{name}" TO compact')
        con.execute("DETACH compact")
    finally:
        con.close()
    compact.replace(db)
    print(json.dumps({"sample": db}))


if __name__ == "__main__":
    main(*sys.argv[1:])
