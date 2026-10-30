"""Cut a small factbook.db for the tests from the archive's full one.

Keeps the 1990, 2020 and 2025 editions of New Zealand, the United States, Somalia
(whose FIPS code the Soviet Union shared in early editions), the two Yemens, the
World, Gaza Strip and Guernsey, with every table the connector reads.

Usage: python scripts/sample/make_factbook_fixture.py FULL_factbook.db OUT.db
"""
import sqlite3, sys
src_path, out_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
out = sqlite3.connect(out_path)
for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name IN ('MasterCountries','Countries','CountryCategories','CountryFields','FieldNameMappings','FieldValues')"):
    out.execute(sql)
ids = [r[0] for r in src.execute("""SELECT CountryID FROM Countries c JOIN MasterCountries m USING (MasterCountryID)
    WHERE c.Year IN (1990, 2020, 2025) AND m.CanonicalCode IN ('NZ','US','SO','YM','XX','GZ','GK')""")]
q = ",".join("?" * len(ids))
def copy(table, where, params):
    rows = src.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchall()
    if rows:
        out.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
    return len(rows)
print(copy("Countries", f"CountryID IN ({q})", ids))
print(copy("MasterCountries", f"MasterCountryID IN (SELECT MasterCountryID FROM Countries WHERE CountryID IN ({q}))", ids))
print(copy("CountryCategories", f"CountryID IN ({q})", ids))
print(copy("CountryFields", f"CountryID IN ({q})", ids))
print(copy("FieldValues", f"FieldID IN (SELECT FieldID FROM CountryFields WHERE CountryID IN ({q}))", ids))
print(copy("FieldNameMappings", "1=1", []))
out.commit()
out.execute("VACUUM")
