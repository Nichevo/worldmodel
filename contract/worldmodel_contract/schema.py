"""Warehouse schema: the tables the data side writes and the app reads.

The version follows semver. The app accepts a warehouse whose major version
matches its own and whose minor version is at least the one it needs; a
patch difference never matters. Bump the major version for any change that
removes or renames a column, the minor version for added tables or columns.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "1.4.0"

# Status codes in observations.status / series.status
STATUS_ESTIMATE = "E"  # observed or estimated by the source
STATUS_PROJECTION = "P"  # the source's own projection or forecast

# Variant labels in observations.variant / series.variant
VARIANT_CENTRAL = "central"
VARIANTS = ("central", "low", "high", "lower80", "upper80", "lower95", "upper95")

# Period frequencies in the freq column; period_start is the first day.
FREQUENCIES = ("A", "Q", "M", "D")

# Kinds of dated event in the events table, in the order the app lists them.
EVENT_KINDS = {
    "independence": "Independence and statehood",
    "election": "Elections",
    "leader": "Heads of state and government",
    "coup": "Coups",
    "conflict": "Wars and armed conflicts",
    "crisis": "Banking and debt crises",
    "recession": "Recessions",
    "boom": "Booms",
    "inflation": "Inflation spikes",
    "debt": "Debt surges",
    "sport": "Major sporting events",
    "disaster": "Disasters and extreme weather",
    "epidemic": "Epidemics and pandemics",
    "notable": "Notable episodes",
    "user": "Your milestones",
}
# How exact an event's dates are: a year-only date is stored as 1 January (start) or 31 December (end).
DATE_PRECISIONS = ("day", "month", "year")


@dataclass(frozen=True)
class Table:
    name: str
    columns: dict[str, str]
    key: tuple[str, ...] = ()
    description: str = ""


OBSERVATION_COLUMNS = {
    "entity_id": "VARCHAR",
    "indicator_id": "VARCHAR",
    "period_start": "DATE",
    "freq": "VARCHAR",
    "breakdown": "VARCHAR",
    "variant": "VARCHAR",
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "value": "DOUBLE",
    "status": "VARCHAR",
}

OBSERVATION_KEY = ("entity_id", "indicator_id", "period_start", "freq", "breakdown", "variant", "source_id", "vintage")

TABLES: dict[str, Table] = {
    t.name: t
    for t in [
        Table("meta", {"key": "VARCHAR", "value": "VARCHAR"}, ("key",),
              "Build stamp: schema_version, build_id, built_at, builder."),
        Table("entities", {
            "entity_id": "VARCHAR", "name": "VARCHAR", "short_name": "VARCHAR", "type": "VARCHAR",
            "iso3": "VARCHAR", "iso2": "VARCHAR", "m49": "VARCHAR", "valid_from": "DATE", "valid_to": "DATE",
            "synonyms": "VARCHAR", "description": "VARCHAR",
        }, ("entity_id",), "Countries, historical states, regions and blocs."),
        Table("entity_codes", {
            "entity_id": "VARCHAR", "scheme": "VARCHAR", "code": "VARCHAR", "valid_from": "DATE",
            "valid_to": "DATE",
        }, ("scheme", "code", "valid_from"), "Crosswalk from each source's codes to entity ids."),
        Table("memberships", {
            "group_id": "VARCHAR", "member_id": "VARCHAR", "valid_from": "DATE", "valid_to": "DATE",
            "source": "VARCHAR", "verified": "VARCHAR",
        }, ("group_id", "member_id", "valid_from"), "Group membership over time."),
        Table("successions", {
            "predecessor_id": "VARCHAR", "successor_id": "VARCHAR", "date": "DATE", "kind": "VARCHAR",
        }, ("predecessor_id", "successor_id"), "Splits, mergers and dissolutions of states."),
        Table("indicators", {
            "indicator_id": "VARCHAR", "name": "VARCHAR", "description": "VARCHAR", "synonyms": "VARCHAR",
            "domain": "VARCHAR", "unit": "VARCHAR", "decimals": "INTEGER", "frequency": "VARCHAR",
            "breakdowns": "VARCHAR", "agg_method": "VARCHAR", "agg_weight": "VARCHAR",
            "agg_numerator": "VARCHAR", "agg_denominator": "VARCHAR", "agg_multiplier": "DOUBLE",
            "bound_min": "DOUBLE", "bound_max": "DOUBLE", "default_on": "BOOLEAN",
        }, ("indicator_id",), "Indicator catalogue: the contract's own, plus indicators a source lists itself "
            "(every World Bank WDI series, say), which start switched off."),
        Table("indicator_sources", {
            "indicator_id": "VARCHAR", "source_id": "VARCHAR", "series": "VARCHAR", "scale": "DOUBLE",
            "rank": "INTEGER", "notes": "VARCHAR",
        }, ("indicator_id", "source_id"), "Which source series feed each indicator, ranked."),
        Table("sources", {
            "source_id": "VARCHAR", "name": "VARCHAR", "short_name": "VARCHAR", "publisher": "VARCHAR",
            "url": "VARCHAR", "licence": "VARCHAR", "licence_url": "VARCHAR", "commercial_use": "BOOLEAN",
            "cadence": "VARCHAR", "attribution": "VARCHAR", "status": "VARCHAR", "default_rank": "INTEGER",
        }, ("source_id",), "Data sources with licence and cadence."),
        Table("vintages", {
            "source_id": "VARCHAR", "vintage": "VARCHAR", "release": "VARCHAR", "retrieved_at": "TIMESTAMP",
            "sha256": "VARCHAR", "row_count": "BIGINT", "origin": "VARCHAR", "is_latest": "BOOLEAN",
        }, ("source_id", "vintage"), "Every ingested release of every source."),
        Table("observations", OBSERVATION_COLUMNS, OBSERVATION_KEY,
              "Every value from every vintage, in one long table, as the sources published it."),
        Table("aggregates", {
            **OBSERVATION_COLUMNS,
            "is_aggregate": "BOOLEAN",
            "coverage": "DOUBLE",
            "members_total": "INTEGER",
            "members_reporting": "INTEGER",
        }, OBSERVATION_KEY,
            "Region and bloc values computed from the latest vintage of member countries, by each "
            "indicator's aggregation rule, where the source publishes no value for that group itself. "
            "coverage is the share of the group's population living in members that reported."),
        Table("series", {
            **OBSERVATION_COLUMNS,
            "is_aggregate": "BOOLEAN",
            "coverage": "DOUBLE",
            "members_total": "INTEGER",
            "members_reporting": "INTEGER",
        }, OBSERVATION_KEY,
            "View. What the app shows: the latest vintage of each source as published, plus aggregates."),
        Table("texts", {
            "entity_id": "VARCHAR", "source_id": "VARCHAR", "vintage": "VARCHAR", "edition": "INTEGER",
            "section": "VARCHAR", "field": "VARCHAR", "field_key": "VARCHAR", "content": "VARCHAR",
            "position": "BIGINT",
        }, ("entity_id", "source_id", "edition", "position"),
            "Text about countries from the latest vintage of each source that has some: every field of every "
            "CIA World Factbook edition (edition = its year), Wikidata facts (edition empty). field is the name "
            "as published, field_key one that stays the same across editions, position the order on the page."),
        Table("events", {
            "event_id": "VARCHAR", "entity_id": "VARCHAR", "source_id": "VARCHAR", "vintage": "VARCHAR",
            "kind": "VARCHAR", "subkind": "VARCHAR", "title": "VARCHAR", "start_date": "DATE", "end_date": "DATE",
            "precision": "VARCHAR", "size": "DOUBLE", "size_unit": "VARCHAR", "deaths": "DOUBLE",
            "affected": "DOUBLE", "damage_usd": "DOUBLE", "place": "VARCHAR", "url": "VARCHAR", "detail": "VARCHAR",
            "color": "VARCHAR",
        }, ("event_id", "entity_id"),
            "Dated events and episodes per country: elections, leaders' terms, coups, conflicts, crises, sporting "
            "events and disasters from their sources, recessions and booms worked out from the data (source "
            "worldmodel), and the curated notable episodes. kind is one of EVENT_KINDS; an event with several "
            "countries (a co-hosted World Cup) has a row for each. end_date is empty for a one-day event or one "
            "still going; size is the event's own measure (magnitude, cumulative fall in GDP, peak inflation) "
            "in size_unit. For a leader's term, detail is their party and color the party's colour (#RRGGBB) "
            "where Wikidata has one."),
        Table("build_checks", {
            "check_id": "VARCHAR", "kind": "VARCHAR", "status": "VARCHAR", "detail": "VARCHAR",
        }, ("check_id",), "Validation gate results for this build."),
    ]
}


def parse_version(v: str) -> tuple[int, int, int]:
    major, minor, patch = (int(x) for x in v.split("."))
    return major, minor, patch


def is_compatible(found: str, required: str = SCHEMA_VERSION) -> bool:
    """True if a warehouse stamped `found` can be read by code expecting `required`."""
    f, r = parse_version(found), parse_version(required)
    return f[0] == r[0] and f[1] >= r[1]
