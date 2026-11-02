"""Build the cities tables: the GeoNames city list, and every other source's city
figures matched to one of its cities.

Run by the build after dbt. A source's city is matched within its country:

1. With a location (UN WUP gives one): the most populous GeoNames city within
   MATCH_KM of it whose name also matches; failing that, the most populous one
   within NEAR_KM (an agglomeration is named after its main city, which sits near
   its middle).
2. Without one (Numbeo, WhereNext): the most populous city in the country whose
   name or one of its other names matches.

Figures that match nothing are counted in the build report, with examples.
"""

from __future__ import annotations

import math
from collections import defaultdict

import duckdb

from worldmodel_contract.cities import norm_name

MATCH_KM = 60
NEAR_KM = 25

CITIES_DDL = """CREATE TABLE cities (
    city_id VARCHAR PRIMARY KEY, name VARCHAR, ascii_name VARCHAR, synonyms VARCHAR, country_id VARCHAR, admin1 VARCHAR,
    lat DOUBLE, lon DOUBLE, population DOUBLE, capital VARCHAR, feature_code VARCHAR, timezone VARCHAR,
    elevation DOUBLE, source_id VARCHAR, vintage VARCHAR)"""
SERIES_DDL = """CREATE TABLE city_series (
    city_id VARCHAR, indicator_id VARCHAR, period_start DATE, source_id VARCHAR, vintage VARCHAR, value DOUBLE,
    status VARCHAR, source_name VARCHAR)"""


def km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1.0, a)))


def compute(con: duckdb.DuckDBPyConnection) -> tuple[int, int, int, list[str]]:
    """Create cities and city_series from src.raw_cities and src.raw_city_values.
    Returns (cities, figures matched, figures not matched, examples not matched)."""
    con.execute(CITIES_DDL)
    con.execute(SERIES_DDL)
    con.execute("""INSERT INTO cities SELECT city_key, name, ascii_name, synonyms, country_id, admin1, lat, lon, population,
            CASE feature_code WHEN 'PPLC' THEN 'national' WHEN 'PPLA' THEN 'regional' ELSE '' END,
            feature_code, timezone, elevation, source_id, vintage
        FROM src.raw_cities QUALIFY row_number() OVER (PARTITION BY city_key ORDER BY vintage DESC) = 1""")
    cities = con.execute("SELECT city_id, name, ascii_name, synonyms, country_id, lat, lon, population FROM cities").fetchall()
    by_country: dict[str, list[tuple]] = defaultdict(list)
    names: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for c in cities:
        by_country[c[4]].append(c)
        keys = {norm_name(c[1]), norm_name(c[2]), *((c[3] or "").split("|"))}
        for k in keys - {""}:
            names[(c[4], k)].append(c)

    def best(cands):
        return max(cands, key=lambda c: c[7] or 0)[0] if cands else None

    places = con.execute("""SELECT DISTINCT city_name, country_id, lat, lon FROM src.raw_city_values
                            WHERE city_name IS NOT NULL AND country_id IS NOT NULL""").fetchall()
    found: dict[tuple, str | None] = {}
    for name, country, lat, lon in places:
        k = norm_name(name)
        # "Auckland" also matches a source's "Auckland Central"; a WUP name such as "Tokyo" or
        # "Delhi" is the agglomeration's main city.
        named = names.get((country, k), []) or names.get((country, norm_name(name.split("-")[0].split("/")[0])), [])
        city = None
        if lat is not None and lon is not None:
            near = [c for c in named if c[5] is not None and km(lat, lon, c[5], c[6]) <= MATCH_KM]
            city = best(near) or best([c for c in by_country.get(country, [])
                                       if c[5] is not None and km(lat, lon, c[5], c[6]) <= NEAR_KM])
        else:
            city = best(named)
        found[(name, country, lat, lon)] = city

    con.execute("CREATE TEMP TABLE city_match (city_name VARCHAR, country_id VARCHAR, lat DOUBLE, lon DOUBLE, city_id VARCHAR)")
    if found:
        con.executemany("INSERT INTO city_match VALUES (?, ?, ?, ?, ?)", [(*k, v) for k, v in found.items()])
    con.execute("""INSERT INTO city_series
        SELECT m.city_id, v.indicator_id, v.period_start, v.source_id, v.vintage, v.value, v.status, v.city_name
        FROM src.raw_city_values v JOIN city_match m
          ON m.city_name = v.city_name AND m.country_id = v.country_id
         AND m.lat IS NOT DISTINCT FROM v.lat AND m.lon IS NOT DISTINCT FROM v.lon
        WHERE m.city_id IS NOT NULL AND v.value IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY m.city_id, v.indicator_id, v.period_start, v.source_id
                                   ORDER BY v.vintage DESC) = 1""")
    matched = con.execute("SELECT count(*) FROM city_series").fetchone()[0]
    missed = [f"{n} ({c})" for (n, c, _, _), v in found.items() if v is None]
    return len(cities), matched, len(missed), sorted(missed)[:12]
