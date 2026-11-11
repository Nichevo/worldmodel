"""Add the transport and networks tables (schema 1.10.0) to the app's sample warehouse.

    python scripts/sample/add_transport.py [sample.duckdb] [airports.csv] [Shipping_Lanes_v1.geojson]

geo_features, port_traffic, chokepoint_traffic and airport_traffic are created empty: the
sample shows the pages' "not loaded yet" notes for them until a refresh. The curated
cable, pipeline and canal events (transport.yaml) are added to events, and the airports
and shipping lanes layers are added from the two real files when given."""

import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

from worldmodel_data import network_tables
from worldmodel_data.connectors.transport import OurAirports, ShippingLanes, TransportCurated
from worldmodel_data.vintage_store import HISTORY_COLUMNS

SAMPLE = Path(__file__).resolve().parents[2] / "app" / "sample" / "worldmodel-sample.duckdb"


def main(db: str = str(SAMPLE), airports: str | None = None, lanes: str | None = None) -> None:
    raw = Path(tempfile.mkdtemp())
    con = duckdb.connect(db)
    try:
        for t in network_tables.DDL:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("CREATE SCHEMA IF NOT EXISTS src")
        for name, cols in HISTORY_COLUMNS.items():
            con.execute(f"CREATE OR REPLACE TABLE src.raw_{name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        con.execute("CREATE OR REPLACE TABLE src.entities AS SELECT * FROM main.entities")
        print(network_tables.compute(con))
        con.execute("DROP SCHEMA src CASCADE")
        # The curated events, as a build would add them.
        c = TransportCurated()
        c.download(raw, "sample")
        staging = duckdb.connect()
        c.stage(staging, raw, "sample", "sample")
        ev = staging.execute(c.events_query).fetchall()
        cols = [d[0] for d in staging.description]
        have = [r[0] for r in con.execute("DESCRIBE events").fetchall()]
        con.execute("DELETE FROM events WHERE source_id = 'transport_curated'")
        for r in ev:
            d = dict(zip(cols, r))
            d["entity_id"] = d.pop("source_code")
            d["event_id"] = f"{d['source_id']}:{d['event_key']}"
            con.execute(f"INSERT INTO events ({', '.join(k for k in have if k in d)}) VALUES ({', '.join('?' for k in have if k in d)})",
                        [d[k] for k in have if k in d])
        print(f"{len(ev)} curated events")
        # Two small real layers
        for conn, path, name in ((OurAirports, airports, "airports.csv"), (ShippingLanes, lanes, "Shipping_Lanes_v1.geojson")):
            if not path:
                continue
            d = raw / conn.source_id
            d.mkdir()
            shutil.copy(path, d / name)
            k = conn()
            k.stage(duckdb.connect(), d, "sample", "sample")
            for layer in k.layers:
                con.execute("DELETE FROM layers WHERE layer_id = ?", [layer["layer_id"]])
                con.execute("INSERT INTO layers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            [layer["layer_id"], layer["name"], layer["description"], layer["kind"], k.source_id, "sample",
                             layer["feature_count"], layer["geojson"]])
                print(f"layer {layer['layer_id']}: {layer['feature_count']}")
        con.execute("UPDATE meta SET value = '1.10.0' WHERE key = 'schema_version'")
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
