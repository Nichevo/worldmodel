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


PUNDIT_DDL = {
    "pundits": ("predictor_id VARCHAR, name VARCHAR, about VARCHAR, site_rank INTEGER, accuracy DOUBLE, correct INTEGER, "
                "incorrect INTEGER, indeterminate INTEGER, pending INTEGER, total INTEGER, calls_held INTEGER, from_site BOOLEAN, "
                "url VARCHAR, seen DATE, source_id VARCHAR, vintage VARCHAR"),
    "pundit_calls": ("call_key VARCHAR, prediction_id VARCHAR, predictor_id VARCHAR, predictor VARCHAR, title VARCHAR, made DATE, "
                     "outcome VARCHAR, next_check DATE, evaluated DATE, verbatim VARCHAR, reasoning VARCHAR, checked_against INTEGER, "
                     "source_url VARCHAR, source_title VARCHAR, horizon VARCHAR, countries VARCHAR, category VARCHAR, url VARCHAR, "
                     "seen DATE, source_id VARCHAR, vintage VARCHAR"),
}
SITE = "https://predictionarchive.com"


def compute_pundits(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """pundits and pundit_calls from the latest Prediction Archive vintage (which carries every saved page)."""
    from urllib.parse import quote_plus

    for t, cols in PUNDIT_DDL.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    latest = con.execute("SELECT max(vintage) FROM src.raw_pundit_calls").fetchone()[0]
    latest_s = con.execute("SELECT max(vintage) FROM src.raw_pundit_scores").fetchone()[0]
    vintage = max(v for v in (latest, latest_s, "") if v is not None)
    if not vintage:
        return {t: 0 for t in PUNDIT_DDL}
    ents = con.execute("SELECT entity_id, name, short_name, coalesce(synonyms, '') FROM src.entities "
                       "WHERE type = 'country' AND valid_to IS NULL").fetchall()
    terms = crowd.build_terms(ents)
    calls = con.execute("""SELECT call_key, prediction_id, predictor_id, predictor, title, made, outcome, next_check, evaluated,
        verbatim, reasoning, checked_against, source_url, source_title, horizon, seen, source_id, vintage
        FROM src.raw_pundit_calls WHERE vintage = ? AND title IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY call_key ORDER BY seen DESC NULLS LAST) = 1""", [vintage]).fetchall()
    out = []
    for (key, pid, who_id, who, title, made, outcome, next_check, evaluated, verbatim, reasoning, checked, src_url, src_title,
         horizon, seen, source_id, vin) in calls:
        url = f"{SITE}/predictions/{pid}/detail" if pid else f"{SITE}/search?q={quote_plus(title)}&type=prediction"
        countries = crowd.match_countries(f"{title} {verbatim or ''}", terms)
        out.append((key, pid, who_id, who, title, made, outcome, next_check, evaluated, verbatim, reasoning, checked, src_url,
                    src_title, horizon, ",".join(countries), crowd.categorise(title, [], "prediction_archive"), url, seen,
                    source_id, vin))
    if out:
        con.executemany(f"INSERT INTO pundit_calls VALUES ({', '.join('?' * 21)})", out)
    # A forecaster's counts: the site's own where a saved page gave them, else counted from the calls held.
    con.execute(f"""INSERT INTO pundits
        WITH s AS (SELECT * FROM src.raw_pundit_scores WHERE vintage = ?
                   QUALIFY row_number() OVER (PARTITION BY coalesce(predictor_id, lower(name))
                                              ORDER BY (total IS NOT NULL) DESC, seen DESC NULLS LAST) = 1),
        c AS (SELECT coalesce(predictor_id, 'name:' || lower(predictor)) AS k, any_value(predictor_id) AS predictor_id,
                     any_value(predictor) AS name, count(*) AS held,
                     count(*) FILTER (WHERE outcome = 'correct') AS correct, count(*) FILTER (WHERE outcome = 'incorrect') AS incorrect,
                     count(*) FILTER (WHERE outcome = 'indeterminate') AS indeterminate,
                     count(*) FILTER (WHERE outcome = 'pending') AS pending, max(seen) AS seen
              FROM pundit_calls GROUP BY 1)
        SELECT coalesce(s.predictor_id, c.predictor_id, c.k), coalesce(s.name, c.name), s.about, s.rank,
               CASE WHEN s.correct IS NOT NULL AND s.correct + s.incorrect > 0 THEN s.correct / (s.correct + s.incorrect)
                    WHEN s.accuracy IS NOT NULL THEN s.accuracy
                    WHEN c.correct + c.incorrect > 0 THEN c.correct / (c.correct + c.incorrect) END,
               coalesce(s.correct, c.correct), coalesce(s.incorrect, c.incorrect), coalesce(s.indeterminate, c.indeterminate),
               coalesce(s.pending, CASE WHEN s.total IS NULL THEN c.pending END), coalesce(s.total, c.held), coalesce(c.held, 0),
               s.correct IS NOT NULL, CASE WHEN coalesce(s.predictor_id, c.predictor_id) IS NOT NULL
                    THEN '{SITE}/predictors/' || coalesce(s.predictor_id, c.predictor_id) || '/detail' END,
               greatest(s.seen, c.seen), 'prediction_archive', ?
        FROM s FULL JOIN c ON c.k = coalesce(s.predictor_id, 'name:' || lower(s.name))""", [vintage, vintage])
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in PUNDIT_DDL}
