"""Add the port pressure tables (schema 1.16.0) to the app's sample warehouse, empty.

    python scripts/sample/add_port_pressure.py [sample.duckdb]

port_daily, port_links, port_disruptions, traffic_weekly and traffic_impacts come from IMF
PortWatch and the build; the sample has no PortWatch data, so they stay empty and the Port
pressure tab says a refresh fills it."""

import sys
from pathlib import Path

import duckdb

from worldmodel_contract.schema import TABLES

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"
NEW = ("port_daily", "port_links", "port_disruptions", "traffic_weekly", "traffic_impacts")


def main(db: str = str(SAMPLE)) -> None:
    con = duckdb.connect(db)
    try:
        for t in NEW:
            con.execute(f"DROP TABLE IF EXISTS {t}")
            con.execute(f"CREATE TABLE {t} ({', '.join(f'{c} {ty}' for c, ty in TABLES[t].columns.items())})")
        con.execute("UPDATE meta SET value = '1.16.0' WHERE key = 'schema_version'")
        con.execute("CHECKPOINT")
    finally:
        con.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
