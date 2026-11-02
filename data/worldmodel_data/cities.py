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

import json
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


PLACE_KM = 40
PLACES_DDL = """CREATE TABLE places (
    place_id VARCHAR PRIMARY KEY, kind VARCHAR, subkind VARCHAR, name VARCHAR, country_id VARCHAR, city_id VARCHAR,
    city_name VARCHAR, lat DOUBLE, lon DOUBLE, founded DATE, url VARCHAR, facts VARCHAR, size DOUBLE,
    source_id VARCHAR, vintage VARCHAR)"""
RATE_INDICATORS = ("exchange_rate_usd", "bis_usd_exchange_rate")  # local currency per US dollar


def compute_places(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    """Create places from src.raw_places: each matched to its nearest city in the same country
    (or the one with the name its source gives), and companies' revenue turned into US dollars
    with the exchange rate of the revenue's year (or the nearest year with one).
    Returns (places, places matched to a city)."""
    con.execute(PLACES_DDL)
    rows = con.execute("""SELECT place_key, kind, subkind, name, country_id, lat, lon, city_name, founded, url, facts,
            source_id, vintage FROM src.raw_places
        QUALIFY row_number() OVER (PARTITION BY kind, place_key ORDER BY vintage DESC) = 1""").fetchall()
    if not rows:
        return 0, 0
    cities = con.execute("SELECT city_id, name, ascii_name, country_id, lat, lon, population FROM cities").fetchall()
    by_country: dict[str, list[tuple]] = defaultdict(list)
    for c in cities:
        by_country[c[3]].append(c)
    rates: dict[str, dict[int, float]] = defaultdict(dict)
    have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if "series" in have:
        for ind in reversed(RATE_INDICATORS):  # the first one wins where both have a year
            for ent, year, value in con.execute(
                    "SELECT entity_id, year(period_start), value FROM series WHERE indicator_id = ? AND variant = 'central' "
                    "AND freq = 'A' AND value > 0", [ind]).fetchall():
                rates[ent][year] = value

    def rate(country: str | None, year: int | None) -> float | None:
        found = rates.get(country or "")
        if not found:
            return None
        y = year or max(found)
        return found.get(y) or found[min(found, key=lambda k: abs(k - y))]

    out, matched = [], 0
    for key, kind, sub, name, country, lat, lon, city_name, founded, url, facts, src, vintage in rows:
        city = None
        cands = by_country.get(country, [])
        if lat is not None and lon is not None:
            near = [(km(lat, lon, c[4], c[5]), c) for c in cands if c[4] is not None]
            near = [x for x in near if x[0] <= PLACE_KM]
            if near:  # the closest, unless a much bigger city is almost as close (suburbs of a capital)
                near.sort(key=lambda x: x[0])
                city = max((x for x in near if x[0] <= near[0][0] + 10), key=lambda x: x[1][6] or 0)[1][0]
        if city is None and city_name:
            k = norm_name(city_name)
            named = [c for c in cands if k in (norm_name(c[1]), norm_name(c[2]))]
            city = max(named, key=lambda c: c[6] or 0)[0] if named else None
        matched += city is not None
        f = json.loads(facts or "{}")
        if kind == "company" and f.get("revenue"):
            r = 1.0 if f.get("currency") == "USD" else rate(f.get("rate_country"), f.get("revenue_year"))
            if r:
                f["revenue_usd"] = round(f["revenue"] / r)
        size = (f.get("revenue_usd") if kind == "company" else f.get("students") if kind == "university"
                else f.get("riders") or (f.get("length_km") or 0) * 1e6 or None)
        out.append((f"{src}:{kind}:{key}", kind, sub, name, country, city, city_name, lat, lon, founded, url,
                    json.dumps(f), size, src, vintage))
    con.executemany(f"INSERT INTO places VALUES ({', '.join('?' * 15)})", out)
    return len(out), matched
