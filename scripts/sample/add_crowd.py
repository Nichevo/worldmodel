"""Add the crowd forecast tables (schema 1.11.0) to the app's sample warehouse.

    python scripts/sample/add_crowd.py [sample.duckdb]

The tables are filled from the small test pages in data/tests/fixtures (a few Polymarket,
Metaculus and Manifold questions and the ViEWS conflict forecasts), so the Crowd pages have
something to show before a refresh."""

import shutil
import sys
from pathlib import Path

import duckdb

from worldmodel_data import crowd_tables
from worldmodel_data.connectors.crowd import Manifold, Metaculus, Polymarket, ViEWS
from worldmodel_data.vintage_store import HISTORY_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"
FIXTURES = ROOT / "data" / "tests" / "fixtures"


def main(db: str = str(SAMPLE)) -> None:
    con = duckdb.connect(db)
    try:
        for t in crowd_tables.DDL:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        for name, cols in HISTORY_COLUMNS.items():
            con.execute(f"CREATE OR REPLACE TABLE src.raw_{name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        con.execute("CREATE OR REPLACE TABLE src.entities AS SELECT * FROM main.entities")
        for conn in (Polymarket, Metaculus, Manifold, ViEWS):
            k = conn()
            staging = duckdb.connect()
            k.stage(staging, FIXTURES / k.source_id, "sample", "sample")
            for name, q in k.history_queries.items():
                cols = HISTORY_COLUMNS[name]
                sel = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in cols.items() if c not in ("source_id", "vintage"))
                rows = staging.execute(f"SELECT '{k.source_id}' AS source_id, 'sample' AS vintage, {sel} FROM ({q})").fetchall()
                if rows:
                    con.executemany(f"INSERT INTO src.raw_{name} ({', '.join(['source_id', 'vintage'] + [c for c in cols if c not in ('source_id', 'vintage')])}) "
                                    f"VALUES ({', '.join('?' * len(rows[0]))})", rows)
        print(crowd_tables.compute(con))
        con.execute("DROP SCHEMA src CASCADE")
        con.execute("UPDATE meta SET value = '1.11.0' WHERE key = 'schema_version'")
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


if __name__ == "__main__":
    main(*sys.argv[1:])
