# Contract changelog

Changes to the warehouse schema, stream definitions and catalogue formats.
External tools that read the API or the warehouse should check this file.

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
