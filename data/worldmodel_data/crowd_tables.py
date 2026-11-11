"""Crowd forecast tables: crowd_questions, crowd_points, crowd_comments, crowd_mine and
conflict_forecasts, made by the build from src.raw_<table> (the latest vintage of each source,
which carries the whole saved history; see connectors/crowd.py). Each question is matched to the
countries its title names, an indicator it is about and a category (worldmodel_contract.crowd)."""

from __future__ import annotations

import duckdb

from worldmodel_contract import crowd

DDL = {
    "crowd_questions": ("question_key VARCHAR, site VARCHAR, site_id VARCHAR, title VARCHAR, url VARCHAR, kind VARCHAR, "
                        "category VARCHAR, countries VARCHAR, indicator_id VARCHAR, created TIMESTAMP, closes TIMESTAMP, "
                        "resolved_at TIMESTAMP, status VARCHAR, resolution VARCHAR, chance DOUBLE, volume DOUBLE, "
                        "forecasters INTEGER, comments INTEGER, description VARCHAR, options VARCHAR, source_id VARCHAR, "
                        "vintage VARCHAR"),
    "crowd_points": "question_key VARCHAR, at_time TIMESTAMP, chance DOUBLE, lower DOUBLE, upper DOUBLE, origin VARCHAR, source_id VARCHAR, vintage VARCHAR",
    "crowd_comments": ("question_key VARCHAR, comment_id VARCHAR, parent_id VARCHAR, author VARCHAR, created TIMESTAMP, "
                       "votes INTEGER, forecast DOUBLE, text VARCHAR, source_id VARCHAR, vintage VARCHAR"),
    "crowd_mine": "question_key VARCHAR, forecaster VARCHAR, at_time TIMESTAMP, chance DOUBLE, community DOUBLE, source_id VARCHAR, vintage VARCHAR",
    "conflict_forecasts": ("entity_id VARCHAR, month DATE, deaths DOUBLE, chance_25 DOUBLE, kind VARCHAR, run VARCHAR, "
                           "source_id VARCHAR, vintage VARCHAR"),
}
ISO3 = "(SELECT iso3, min(entity_id) AS entity_id FROM src.entities WHERE iso3 IS NOT NULL GROUP BY iso3)"


def compute(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Create the five tables (empty when no source has a vintage). Returns their row counts."""
    for t, cols in DDL.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    ents = con.execute("SELECT entity_id, name, short_name, coalesce(synonyms, '') FROM src.entities "
                       "WHERE type = 'country' AND valid_to IS NULL").fetchall()
    terms = crowd.build_terms(ents)
    qs = con.execute("""SELECT question_key, site, site_id, title, url, kind, tags, created, closes, resolved_at, status,
        resolution, chance, volume, forecasters, comments, description, options, source_id, vintage FROM src.raw_crowd_questions
        QUALIFY row_number() OVER (PARTITION BY question_key ORDER BY vintage DESC) = 1""").fetchall()
    out = []
    for (key, site, sid, title, url, kind, tags, created, closes, resolved_at, status, resolution, chance, volume,
         forecasters, comments, description, options, source_id, vintage) in qs:
        countries = crowd.match_countries(title or "", terms)
        out.append((key, site, sid, title, url, kind, crowd.categorise(title or "", (tags or "").split(","), site),
                    ",".join(countries), crowd.match_indicator(title or ""), created, closes, resolved_at, status,
                    resolution, chance, volume, forecasters, comments, description, options, source_id, vintage))
    if out:
        con.executemany(f"INSERT INTO crowd_questions VALUES ({', '.join('?' * 22)})", out)
    con.execute("""INSERT INTO crowd_points SELECT question_key, at_time, chance, lower, upper, origin, source_id, vintage
        FROM src.raw_crowd_points WHERE chance IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY question_key, at_time ORDER BY origin = 'site' DESC, vintage DESC) = 1""")
    con.execute("""INSERT INTO crowd_comments SELECT question_key, comment_id, parent_id, author, created, votes, forecast,
        text, source_id, vintage FROM src.raw_crowd_comments
        QUALIFY row_number() OVER (PARTITION BY comment_id ORDER BY vintage DESC) = 1""")
    con.execute("""INSERT INTO crowd_mine SELECT question_key, forecaster, at_time, chance, community, source_id, vintage
        FROM src.raw_crowd_mine QUALIFY row_number() OVER (PARTITION BY question_key, forecaster, at_time ORDER BY vintage DESC) = 1""")
    con.execute(f"""INSERT INTO conflict_forecasts SELECT c.entity_id, f.month, f.deaths, f.chance_25, f.kind, f.run,
        f.source_id, f.vintage FROM src.raw_conflict_forecasts f JOIN {ISO3} c ON c.iso3 = f.country_code
        QUALIFY row_number() OVER (PARTITION BY c.entity_id, f.month, f.kind ORDER BY f.vintage DESC) = 1""")
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in DDL}
