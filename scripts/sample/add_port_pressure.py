"""Add the port pressure and goods by port tables (schema 1.16.0 and 1.17.0) to the app's sample
warehouse, empty.

    python scripts/sample/add_port_pressure.py [sample.duckdb]

port_daily, port_links, port_disruptions, traffic_weekly and traffic_impacts come from IMF
PortWatch and the build, port_goods from national statistics; the sample has none of them,
so they stay empty and the Port pressure and Goods by port tabs say a refresh fills them."""

import sys
from pathlib import Path

import duckdb

from worldmodel_contract.schema import SCHEMA_VERSION, TABLES

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "sample" / "worldmodel-sample.duckdb"
NEW = ("port_daily", "port_links", "port_disruptions", "traffic_weekly", "traffic_impacts", "port_goods")


def main(db: str = str(SAMPLE)) -> None:
    con = duckdb.connect(db)
    try:
        for t in NEW:
            con.execute(f"DROP TABLE IF EXISTS {t}")
            con.execute(f"CREATE TABLE {t} ({', '.join(f'{c} {ty}' for c, ty in TABLES[t].columns.items())})")
        con.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", [SCHEMA_VERSION])
        con.execute("CHECKPOINT")
    finally:
        con.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
