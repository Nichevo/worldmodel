"""Trim the sample warehouse's Factbook text after `worldmodel-data publish`.

The sample is built from a cut of the Factbook archive (make_factbook_sample.py)
that still holds every edition of the fields its numeric series read, for every
country. Their text would double the sample's size, so this keeps the text of the
last edition (2025) for every country and every edition for the sample countries
only, then writes the file again to reclaim the space.

Usage: python scripts/sample/trim_sample_texts.py app/sample/worldmodel-sample.duckdb
"""

import os
import sys

import duckdb

KEEP = ("NZL", "USA", "CHN", "DEU", "GBR", "IND", "RUS", "BRA", "JPN", "AUS", "SOM", "YEM", "SUN", "YAR", "YMD")


def main(path: str) -> None:
    tmp = path + ".trim"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = duckdb.connect(path)
    keep = ", ".join(f"'{k}'" for k in KEEP)
    con.execute(f"DELETE FROM texts WHERE source_id = 'cia_factbook' AND edition <> 2025 AND entity_id NOT IN ({keep})")
    db = con.execute("SELECT current_database()").fetchone()[0]
    con.execute(f"ATTACH '{tmp}' AS trimmed")
    con.execute(f'COPY FROM DATABASE "{db}" TO trimmed')
    con.close()
    os.replace(tmp, path)
    print(f"{path}: {os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
