# Contract changelog

Changes to the warehouse schema, stream definitions and catalogue formats.
External tools that read the API or the warehouse should check this file.

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
