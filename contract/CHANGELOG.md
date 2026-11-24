# Contract changelog

Changes to the warehouse schema, stream definitions and catalogue formats.
External tools that read the API or the warehouse should check this file.

## 1.14.0 (2026-11-24)

- New table `layer_items`: every item of the map's dot layers with its country, size figure
  and category (spec in `worldmodel_contract.layer_details`). Absent before 1.14.0; readers
  should treat it as empty.
- New source: map_layers (counted by the build), with indicators `map_<layer>_count`,
  `map_<layer>_per_m` and, where the layer has a size figure, `map_<layer>_<size>`.

## 1.13.0 (2026-11-23)

- New tables `pundits` (named forecasters on Prediction Archive, with their graded counts
  and accuracy) and `pundit_calls` (their calls: outcome, dates, the words used, the
  grader's reasoning, countries named). Both absent before 1.13.0; readers should treat
  them as empty.
- New source: prediction_archive (pages saved by hand).

## 1.12.0 (2026-11-21)

- New tables `conflict_events` (located events from UCDP GED, UCDP Candidate and ACLED),
  `war_losses` (seen and claimed losses by war, side, category, status and day),
  `war_areas` (land held by day), `sanction_counts` and `sanction_listings`
  (OpenSanctions), `military_strength` (Global Firepower by edition) and `arms_deals`
  (SIPRI). All absent before 1.12.0; readers should treat them as empty.
- Event kind `outage` (internet outages and shutdowns: IODA, Cloudflare Radar, KeepItOn).
- `geo_features` layer `front_line` (DeepState, feature_id `<war>:<day>`).
- New module `osint` and catalogue `wars.yaml`.
- New sources: ucdp_ged, ucdp_candidate, acled, oryx, ua_claimed_losses, deepstate,
  kiel_ukraine, ioda, cloudflare_radar, keepiton, opensanctions, gfp, sipri_arms; owid
  adds `nuclear_warheads`.
- `local`: settings `live_military_planes`, `conflict_events_fetch`, `acled_on`,
  `acled_from_year`, `wars_fetch`, `oryx_backfill`, `outages_fetch`, `ioda_from_year`,
  `sanctions_now_fetch`, `gfp_fetch`, `gfp_pages_per_refresh`.

## 1.5.1 (2026-11-01)

No change to the warehouse tables, so existing warehouses stay readable.

- New catalogue `topics.yaml` (`catalogue.topics()`): topic pages with an
  introduction, a map indicator and their indicators in order.
- New module `forecast`: statistical forecasts of yearly series (five simple
  models scored by a rolling back-test, 80% and 95% ranges from its misses).
- New sources: oecd_eo and wb_gep (further sources of `gdp_growth`, and for the
  OECD `inflation`; one vintage per edition, years from the edition's year on
  are projections, status P), eurostat_ai, anthropic_aei and ms_ai_diffusion
  (AI use by country: `ai_use_enterprises`, `ai_claude_use_per_capita_index`,
  `ai_claude_use_share`, `ai_use_population`).
- `cohort.Levers.hold_fertility`: fertility held at its base-year level.
- `local`: settings `forecast_horizon`, `forecast_ranges`, `forecast_official`.

## 1.5.0 (2026-10-30)

- New table `layers`: map overlays (tectonic plate boundaries, active faults,
  volcanoes, earthquakes of magnitude 6 and over), one row per layer with its
  features as a GeoJSON FeatureCollection. Key `layer_id`.
- New sources with their own indicators: bis, oecd, dallas_fed_ihpd, imf_gdd
  (house prices, price-to-income, household debt), un_ims and unhcr (migrants
  in and out, refugees; by country of origin in `breakdown` as origin=<entity>),
  wittgenstein and undp_hdr (schooling, human development), idea_turnout (voter
  turnout); map layers from plates_bird, gem_faults, gvp_volcanoes and
  usgs_earthquakes.
- World Bank: income per person in local currency is a main series
  (`gni_per_capita_lcu`, `gdp_per_capita_lcu`).

## 1.4.0 (2026-10-30)

- `events.color`: a colour the source gives an event, as #RRGGBB. Leaders'
  terms from Wikidata now carry their party in `detail` and the party's
  colour in `color`, for charts coloured by governing party.
- `local`: settings `party_colours` and `party_office`.

## 1.3.0 (2026-10-30)

- New table `events`: dated events and episodes per country (elections, leaders,
  coups, conflicts, crises, sporting events, disasters, epidemics, notable
  episodes, recessions and booms worked out from the data). Key
  (event_id, entity_id); `EVENT_KINDS` and `DATE_PRECISIONS` list the values.
- Catalogues: `notable_episodes.csv` (curated, with sources) and
  `episode_rules.yaml` (how episodes are worked out); new sources
  powell_thyne, ucdp_acd, emdat and notable.
- `catalogue.country_by_name(name, on)`: a country from its name on a date,
  for sources that name countries instead of coding them.
- `local`: settings `events_on_charts`, `event_kinds`, `disaster_min_deaths`,
  `problem_banner`; `problems()` groups the refresh log into distinct problems.

## 1.2.0 (2026-10-30)

- New table `texts`: text about countries (CIA World Factbook fields for every
  edition 1990-2025, Wikidata facts), one row per field.
- New sources `cia_factbook`, `wikidata`, `wikipedia`; crosswalk scheme `fips`
  for the Factbook's World (XX) and EU (EE).

## 1.1.0 (2026-10-30)

- `indicators.default_on`: whether an indicator starts switched on. Indicators
  that sources list themselves (every World Bank WDI series) are added to the
  table, most switched off.
- Entity type `income_group`; crosswalk schemes `wdi` and `owid`.

## 1.0.0 (2026-10-29)

First version: observations, aggregates, series view, catalogues, vintages,
build checks and meta; named streams; driver graph format.
