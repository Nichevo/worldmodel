"""Cut the Factbook archive's factbook.db down for the sample warehouse.

The full database is about 690 MB and its text about 40 MB once stored, too much
for the sample in the repository. This keeps:

* every field of the last edition (2025) for every country,
* every field of every edition for a few countries (SAMPLE_COUNTRIES, FIPS codes),
* for all countries and editions, only the fields the numeric series read, so the
  sample's Factbook series are complete.

Usage: python scripts/sample/make_factbook_sample.py FULL_factbook.db OUT.db
"""

import sqlite3
import sys

sys.path.insert(0, "data")
from worldmodel_data.connectors.cia_factbook import SERIES  # noqa: E402

SAMPLE_COUNTRIES = ("NZ", "US", "CH", "GM", "UK", "IN", "RS", "BR", "JA", "AS", "SO", "YM")


def main(src_path: str, out_path: str) -> None:
    src = sqlite3.connect(src_path)
    out = sqlite3.connect(out_path)
    names = ("MasterCountries", "Countries", "CountryCategories", "CountryFields", "FieldNameMappings", "FieldValues")
    for (sql,) in src.execute(f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name IN {names}"):
        out.execute(sql)
    out.execute(f"ATTACH '{src_path}' AS full")
    fields = sorted({f for s in SERIES for f in s.fields})
    out.execute("CREATE TEMP TABLE keep_names (n TEXT)")
    out.executemany("INSERT INTO keep_names VALUES (?)", [(f,) for f in fields])
    countries = ", ".join(f"'{c}'" for c in SAMPLE_COUNTRIES)
    for t in ("MasterCountries", "Countries", "CountryCategories", "FieldNameMappings"):
        out.execute(f"INSERT INTO {t} SELECT * FROM full.{t}")
    out.execute(f"""INSERT INTO CountryFields SELECT cf.* FROM full.CountryFields cf
        JOIN full.Countries c USING (CountryID) LEFT JOIN full.MasterCountries m USING (MasterCountryID)
        LEFT JOIN full.FieldNameMappings fm ON fm.OriginalName = cf.FieldName
        WHERE c.Year = 2025 OR upper(m.CanonicalCode) IN ({countries})
            OR coalesce(fm.CanonicalName, cf.FieldName) IN (SELECT n FROM keep_names)""")
    out.execute("""INSERT INTO FieldValues SELECT fv.* FROM full.FieldValues fv
        WHERE fv.FieldID IN (SELECT FieldID FROM CountryFields)""")
    out.commit()
    out.execute("DETACH full")
    out.execute("VACUUM")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
