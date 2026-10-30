"""Shared helpers for connectors whose data are dated events named by country."""

from __future__ import annotations

import logging
from datetime import date

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import sql_str

log = logging.getLogger(__name__)

# (entity_id, event_key, kind, subkind, title, start, end, precision, size, size_unit, deaths, affected,
#  damage_usd, place, url, detail)
EVENT_ROW = ("entity_id", "event_key", "kind", "subkind", "title", "start_date", "end_date", "precision", "size",
             "size_unit", "deaths", "affected", "damage_usd", "place", "url", "detail")


def make_date(year, month=None, day=None) -> tuple[date | None, str]:
    """A date from parts that may be missing or zero, with how precise it is."""
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None, "day"
    m = _int(month)
    d = _int(day)
    if not m:
        return date(y, 1, 1), "year"
    if not d:
        return date(y, m, 1), "month"
    try:
        return date(y, m, d), "day"
    except ValueError:  # 31 April and the like
        return date(y, m, 1), "month"


def _int(v) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n or None


def country(name: str, on: date | None, unmatched: set[str]) -> str | None:
    """The entity for a country name on a date, noting names that do not match."""
    found = catalogue.country_by_name(name, on)
    if found is None and name:
        unmatched.add(name)
    return found


def stage_events(con: duckdb.DuckDBPyConnection, source_id: str, vintage: str, rows: list[tuple],
                 unmatched: set[str]) -> str:
    """Load event rows (EVENT_ROW order) into a table and return the events query for them.
    Entities are already matched, so the scheme is iso3 on the entity id."""
    if unmatched:
        log.warning("%s: %s country names not matched, left out: %s", source_id, len(unmatched),
                    ", ".join(sorted(unmatched)[:40]))
    types = {"start_date": "DATE", "end_date": "DATE", "size": "DOUBLE", "deaths": "DOUBLE", "affected": "DOUBLE",
             "damage_usd": "DOUBLE"}
    con.execute(f"CREATE TABLE ev ({', '.join(f'{c} {types.get(c, 'VARCHAR')}' for c in EVENT_ROW)})")
    if rows:
        con.executemany(f"INSERT INTO ev VALUES ({', '.join('?' * len(EVENT_ROW))})", rows)
    # The crosswalk's iso3 scheme holds every country and former state under its entity id.
    return (f"SELECT {sql_str(source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, "
            "entity_id AS source_code, event_key, kind, subkind, title, start_date, end_date, precision, size, "
            "size_unit, deaths, affected, damage_usd, place, url, detail FROM ev")


EMPTY_OBSERVATIONS = ("SELECT NULL AS source_id, NULL AS vintage, NULL AS scheme, NULL AS source_code, "
                      "NULL AS indicator_id, NULL AS period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, "
                      "NULL AS value, 'E' AS status WHERE false")
