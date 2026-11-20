"""Add the OSINT detail tables (schema 1.12.0) to the app's sample warehouse.

    python scripts/sample/add_osint.py [sample.duckdb]

The tables are filled from the small test files in data/tests/fixtures (a few UCDP and ACLED
events, Oryx and claimed losses, DeepState shapes, sanctions listings, Global Firepower pages
and SIPRI deals), so the pages have something to show before a refresh. Outages become events."""

import json
import sys
from pathlib import Path

import duckdb

from worldmodel_data import osint_tables
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import EVENT_COLUMNS, HISTORY_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"
FIXTURES = ROOT / "data" / "tests" / "fixtures"
SOURCES = ("ucdp_ged", "ucdp_candidate", "acled", "oryx", "ua_claimed_losses", "deepstate", "ioda", "cloudflare_radar",
           "keepiton", "opensanctions", "gfp", "sipri_arms")


def main(db: str = str(SAMPLE)) -> None:
    con = duckdb.connect(db)
    try:
        for t in osint_tables.DDL:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("DELETE FROM geo_features WHERE layer_id = 'front_line'")
        con.execute("DELETE FROM events WHERE kind = 'outage'")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        for name, cols in HISTORY_COLUMNS.items():
            con.execute(f"CREATE OR REPLACE TABLE src.raw_{name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        con.execute("CREATE OR REPLACE TABLE src.entities AS SELECT * FROM main.entities")
        for sid in SOURCES:
            k = CONNECTORS[sid]()
            staging = duckdb.connect()
            k.stage(staging, FIXTURES / sid, "2026-11-20", "sample")
            for name, q in k.history_queries.items():
                cols = HISTORY_COLUMNS[name]
                names = [c for c in cols if c not in ("source_id", "vintage")]
                sel = ", ".join(f"CAST({c} AS {cols[c]}) AS {c}" for c in names)
                got = staging.execute(f"SELECT '{sid}', 'sample', {sel} FROM ({q})").fetchall()
                if not got:
                    continue
                if name == "geo_features":
                    con.executemany("INSERT INTO geo_features (layer_id, feature_id, name, rank, props, countries, west, south, "
                                    "east, north, geojson, source_id, vintage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    [(*r[2:], r[0], r[1]) for r in got])
                else:
                    con.executemany(f"INSERT INTO src.raw_{name} (source_id, vintage, {', '.join(names)}) "
                                    f"VALUES ({', '.join('?' * (len(names) + 2))})", got)
            if k.events_query:
                ecols = [c for c in EVENT_COLUMNS if c not in ("source_id", "vintage", "scheme", "source_code")]
                ev = staging.execute(f"SELECT source_code, {', '.join(ecols)} FROM ({k.events_query})").fetchall()
                con.executemany(f"""INSERT INTO events (event_id, entity_id, source_id, vintage, {', '.join(c for c in ecols if c != 'event_key')})
                    VALUES ({', '.join('?' * (len(ecols) + 3))})""",
                                [(f"{sid}:{r[1]}", r[0], sid, "sample", *r[2:]) for r in ev])
        print(osint_tables.compute(con))
        con.execute("DROP SCHEMA src CASCADE")
        con.execute("UPDATE meta SET value = '1.12.0' WHERE key = 'schema_version'")
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
