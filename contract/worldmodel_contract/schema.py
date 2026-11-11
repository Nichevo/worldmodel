"""Warehouse schema: the tables the data side writes and the app reads.

The version follows semver. The app accepts a warehouse whose major version
matches its own and whose minor version is at least the one it needs; a
patch difference never matters. Bump the major version for any change that
removes or renames a column, the minor version for added tables or columns.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "1.10.0"

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
    "animal_disease": "Animal disease outbreaks",
    "pest": "Pests, weeds and plant diseases arriving",
    "pollution": "Pollution disasters and smoke across borders",
    "notable": "Notable episodes",
    "un": "United Nations: Security Council seats, vetoes and resolutions",
    "sanction": "Sanctions",
    "imf": "IMF lending programmes",
    "trade_dispute": "WTO trade disputes",
    "treaty": "Treaties joined",
    "court": "International court cases",
    "summit": "Summits hosted",
    "crisiswatch": "CrisisWatch monthly ratings",
    "holiday": "Public holidays",
    "law": "Laws and rules changed",
    "transport": "Air, sea and rail accidents",
    "infrastructure": "Cables, pipelines, canals and shipping cut or blocked",
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
        Table("subdivisions", {
            "entity_id": "VARCHAR", "parent_id": "VARCHAR", "level": "VARCHAR", "code": "VARCHAR",
        }, ("entity_id",), "Areas inside a country (entities of type subnational), with the country they are in: "
            "New Zealand's 16 regions (level region, code the Stats NZ regional council code). Absent in warehouses "
            "built before 1.7.0."),
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
        Table("layers", {
            "layer_id": "VARCHAR", "name": "VARCHAR", "description": "VARCHAR", "kind": "VARCHAR",
            "source_id": "VARCHAR", "vintage": "VARCHAR", "feature_count": "INTEGER", "geojson": "VARCHAR",
        }, ("layer_id",),
            "Map overlays from the latest vintage of their source: plate boundaries, active faults, volcanoes and "
            "earthquakes. kind is line or point; geojson holds the layer's features as one FeatureCollection, with "
            "their properties trimmed to what the map shows."),
        Table("cities", {
            "city_id": "VARCHAR", "name": "VARCHAR", "ascii_name": "VARCHAR", "synonyms": "VARCHAR", "country_id": "VARCHAR",
            "admin1": "VARCHAR", "lat": "DOUBLE", "lon": "DOUBLE", "population": "DOUBLE", "capital": "VARCHAR",
            "feature_code": "VARCHAR", "timezone": "VARCHAR", "elevation": "DOUBLE", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("city_id",),
            "Places of 15,000 people or more (GeoNames). capital is national, regional or empty. Made by the build "
            "(worldmodel_data.cities); absent in warehouses built before it (the app shows none)."),
        Table("city_series", {
            "city_id": "VARCHAR", "indicator_id": "VARCHAR", "period_start": "DATE", "source_id": "VARCHAR",
            "vintage": "VARCHAR", "value": "DOUBLE", "status": "VARCHAR", "source_name": "VARCHAR",
        }, ("city_id", "indicator_id", "period_start", "source_id"),
            "Figures about cities from the latest vintage of each source (indicators in worldmodel_contract.cities), "
            "each matched to a city; source_name is the name the source used."),
        Table("places", {
            "place_id": "VARCHAR", "kind": "VARCHAR", "subkind": "VARCHAR", "name": "VARCHAR", "country_id": "VARCHAR",
            "city_id": "VARCHAR", "city_name": "VARCHAR", "lat": "DOUBLE", "lon": "DOUBLE", "founded": "DATE", "url": "VARCHAR",
            "facts": "VARCHAR", "size": "DOUBLE", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("place_id",),
            "Things with a location in a country, from the latest vintage of their source: metro and rail systems "
            "(kind transit), universities and companies. city_id is the nearest city of the same country within "
            "40 km (or the one named city_name); facts is a JSON object of the kind's figures; size is what the app "
            "sorts by: yearly passengers or length for a system, students for a university, revenue in US dollars "
            "for a company (worked out by the build from the World Bank's exchange rate). Absent in warehouses built "
            "before 1.6.0."),
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
        Table("long_series", {
            "entity_id": "VARCHAR", "series_id": "VARCHAR", "year": "INTEGER", "value": "DOUBLE",
            "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("entity_id", "series_id", "year"),
            "Figures over centuries for the Long history page (series in worldmodel_contract history.yaml): "
            "population since 10,000 BC, GDP per person since AD 1 and others. year is a whole number, negative "
            "for BC. Absent in warehouses built before 1.8.0."),
        Table("polities", {
            "polity_key": "VARCHAR", "name": "VARCHAR", "from_year": "INTEGER", "to_year": "INTEGER",
            "area_km2": "DOUBLE", "composite": "BOOLEAN", "components": "VARCHAR", "member_of": "VARCHAR",
            "wikipedia": "VARCHAR", "wikidata": "VARCHAR", "region": "VARCHAR", "lat": "DOUBLE", "lon": "DOUBLE",
            "west": "DOUBLE", "south": "DOUBLE", "east": "DOUBLE", "north": "DOUBLE", "geojson": "VARCHAR",
            "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("polity_key",),
            "States and empires with their borders, one row per stretch of years (from_year to to_year, "
            "inclusive) with unchanged borders (Cliopatria). Composite rows (names in brackets) join an empire's "
            "parts; a part names its composite in member_of. region is one of history.yaml's regions, by the "
            "centre of the largest piece. geojson is the simplified geometry. Absent before 1.8.0."),
        Table("history_events", {
            "event_id": "VARCHAR", "kind": "VARCHAR", "title": "VARCHAR", "year": "INTEGER", "end_year": "INTEGER",
            "month": "INTEGER", "day": "INTEGER", "lat": "DOUBLE", "lon": "DOUBLE", "place": "VARCHAR",
            "entity_id": "VARCHAR", "region": "VARCHAR", "deaths": "DOUBLE", "size": "DOUBLE", "size_unit": "VARCHAR",
            "links": "INTEGER", "url": "VARCHAR", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("event_id",),
            "Events far back in time for the Long history page: wars, battles, sieges, epidemics, famines, "
            "revolutions and treaties (Wikidata, links = Wikipedias with an article) and earthquakes, eruptions "
            "and tsunamis (NOAA; size is magnitude, VEI or wave height). year is negative for BC. Absent before 1.8.0."),
        Table("zone_grids", {
            "period": "VARCHAR", "scenario": "VARCHAR", "width": "INTEGER", "height": "INTEGER", "grid": "BLOB",
            "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("period", "scenario"),
            "Köppen-Geiger climate zones (Beck et al. 2023) as grids: one byte per cell (0 = sea or no data, 1-30 "
            "the zones in catalogue order), rows from 90°N, columns from 180°W, zlib-compressed. period is "
            "1901-1930 ... 2071-2099; scenario is historical, ssp126, ssp245 or ssp585. Absent before 1.9.0."),
        Table("protected_areas", {
            "wdpa_id": "VARCHAR", "name": "VARCHAR", "designation": "VARCHAR", "iucn_cat": "VARCHAR",
            "entity_id": "VARCHAR", "marine": "VARCHAR", "area_km2": "DOUBLE", "year": "INTEGER", "lat": "DOUBLE",
            "lon": "DOUBLE", "west": "DOUBLE", "south": "DOUBLE", "east": "DOUBLE", "north": "DOUBLE", "geojson": "VARCHAR",
            "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("wdpa_id",),
            "Protected areas from the World Database on Protected Areas: 10 km² or more, and every one in New "
            "Zealand, with simplified shapes. marine is 0 (land), 1 (land and sea) or 2 (sea); year is when it was "
            "protected. Absent before 1.9.0."),
        Table("species_status", {
            "entity_id": "VARCHAR", "scientific_name": "VARCHAR", "category": "VARCHAR", "year": "INTEGER",
            "url": "VARCHAR", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("entity_id", "scientific_name"),
            "Species extinct, extinct in the wild or critically endangered in a country (IUCN Red List; New Zealand, "
            "Australia, the United States and the United Kingdom). Absent before 1.9.0."),
        Table("pest_presence", {
            "pest_code": "VARCHAR", "pest_name": "VARCHAR", "entity_id": "VARCHAR", "state": "VARCHAR",
            "status": "VARCHAR", "present": "BOOLEAN", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("pest_code", "entity_id", "state"),
            "Where each pest on nature.yaml's watch list is found (EPPO): status as EPPO words it, present when it "
            "is there (present or transient). state is a state or province, or empty for the whole country. "
            "Absent before 1.9.0."),
        Table("geo_features", {
            "layer_id": "VARCHAR", "feature_id": "VARCHAR", "name": "VARCHAR", "rank": "INTEGER", "props": "VARCHAR",
            "countries": "VARCHAR", "west": "DOUBLE", "south": "DOUBLE", "east": "DOUBLE", "north": "DOUBLE",
            "geojson": "VARCHAR", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("layer_id", "feature_id"),
            "Lines and areas too big for one map layer, sent by the box in view: rivers (HydroRIVERS, rank = flow "
            "order, 1 biggest), river_names (Natural Earth), basins (HydroBASINS, whole river basins; props has area, "
            "shares by country, of_country, flow, transboundary), waterways, cables (TeleGeography), gas_pipelines, "
            "oil_pipelines (Global Energy Monitor). countries is a comma list of entity ids; props is JSON. "
            "Absent before 1.10.0."),
        Table("port_traffic", {
            "port_id": "VARCHAR", "entity_id": "VARCHAR", "year": "INTEGER", "month": "INTEGER", "calls": "DOUBLE",
            "import_t": "DOUBLE", "export_t": "DOUBLE", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("port_id", "year", "month"),
            "Ship calls and estimated tonnes unloaded and loaded at each port a month (IMF PortWatch, from 2019). "
            "Absent before 1.10.0."),
        Table("chokepoint_traffic", {
            "chokepoint_id": "VARCHAR", "name": "VARCHAR", "day": "DATE", "transits": "DOUBLE", "tankers": "DOUBLE",
            "container": "DOUBLE", "dry_bulk": "DOUBLE", "cargo": "DOUBLE", "capacity": "DOUBLE",
            "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("chokepoint_id", "day"),
            "Ships through each shipping chokepoint a day, by type, and their capacity in tonnes (IMF PortWatch, "
            "from 2019). Absent before 1.10.0."),
        Table("airport_traffic", {
            "airport": "VARCHAR", "name": "VARCHAR", "entity_id": "VARCHAR", "year": "INTEGER", "passengers": "DOUBLE",
            "freight_t": "DOUBLE", "source_id": "VARCHAR", "vintage": "VARCHAR",
        }, ("airport", "year"),
            "Passengers and freight a year at each airport (Eurostat; files saved by hand for other countries). "
            "airport is the ICAO code where known. Absent before 1.10.0."),
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
