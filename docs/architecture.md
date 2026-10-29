# Architecture

Two components linked by one contract. Either runs without the other.

## The contract (`contract/`)

The Python package `worldmodel_contract` and the files it ships:

| File | What it holds |
| --- | --- |
| `schema.py` | Warehouse tables and columns, and `SCHEMA_VERSION` (semver). The pipeline stamps the version into the warehouse's `meta` table; the app refuses a warehouse with a different major version or an older minor version. |
| `catalogues/entities.csv` | Every entity: countries and areas (ISO 3166 alpha-3), historical states (USSR, Yugoslavia, ...), the world, UN M49 continents and sub-regions, blocs. Plain names, short names, synonyms, validity dates. |
| `catalogues/entity_codes.csv` | Crosswalk from each source's codes to entity ids, with validity dates. Schemes: `iso3`, `iso2`, `m49`, `un_wpp` (UN location id), `imf`. |
| `catalogues/memberships.csv` | Who belonged to which group, from when to when, with a source link and a `verified` flag. |
| `catalogues/successions.csv` | Splits, mergers and dissolutions (USSR to its 15 successors, ...). |
| `catalogues/indicators.yaml` | The indicator catalogue: plain name, description, synonyms, unit, bounds, aggregation rule, and each source's series code and scale, ranked. |
| `catalogues/sources.yaml` | Sources with licence, cadence and attribution. |
| `catalogues/streams.yaml` | Named streams for external tools. |
| `catalogues/driver_graph.yaml` | Which variable drives which, for linked forecasts (format fixed now, used in phase 3). |
| `queries.py` | SQL builders for reading series, shared by the API and the CLI export. |

`catalogue.validate()` cross-checks all of it and runs before every build and in the tests.

## The data side (`data/`)

```
fetch ─► var/raw/<source>/<vintage>/<fetched-at>/   files exactly as downloaded
      └► var/vintages/<source>/<vintage>/observations.parquet + manifest.json
build ─► var/warehouse/builds/<build-id>.duckdb.tmp
           1. load catalogues and every vintage into schema src
           2. dbt build: models + tests (data/worldmodel_data/dbt)
           3. Python gates: coverage, spot checks, shrinkage, unmapped codes
           4. compact into <build-id>.duckdb, write var/warehouse/CURRENT
```

A connector (`data/worldmodel_data/connectors/`) knows how to download one
source and turn its files into the long shape: `source_code, indicator_id,
period_start, freq, breakdown, variant, value, status`. It takes series codes
and scales from the indicator catalogue, so adding an indicator from an
existing source is a catalogue edit, not code. Entity resolution happens in
dbt through the crosswalk, so an unknown code shows up in the build report
instead of disappearing.

### Warehouse tables

| Table | Rows |
| --- | --- |
| `observations` | Every value from every vintage, as published. Key: entity, indicator, period, breakdown, variant, source, vintage. |
| `aggregates` | Region and bloc values computed from the latest vintage of their members, where the source publishes none itself, with coverage (share of the group's population that reported). |
| `series` (view) | What the app shows: latest vintage of each source plus `aggregates`. |
| `entities`, `entity_codes`, `memberships`, `successions`, `indicators`, `indicator_sources`, `sources` | The contract catalogues as of the build. |
| `vintages` | Every stored release, with fetch time, hash and origin. |
| `build_checks`, `meta` | Gate results and the build stamp. |

`period_start` plus `freq` (A, Q, M, D) carry the period, so monthly and daily
series (policy rates, FX) fit without a schema change. `breakdown` carries
dimensions such as `age=0-4|sex=female`; `variant` carries projection
variants and, later, forecast quantiles.

### Aggregation rules

Set per indicator in the catalogue: `sum` (population, GDP), `weighted_mean`
with a weight indicator (fertility by female population, growth by GDP at
PPP), `ratio` of two summed indicators (crude birth rate = births / population),
or `none` (medians). Membership is resolved at the middle of each period.

## The app side (`app/`)

- `app/api`: FastAPI on 127.0.0.1:8000, read-only. Opens the warehouse named
  by `WORLDMODEL_WAREHOUSE` (a file, or a data folder with `warehouse/CURRENT`),
  else `./var`, else the sample. Reopens when the live build changes.
  Endpoints: `/api/v1/meta`, `/sources`, `/build-checks`, `/entities`,
  `/entities/{id}`, `/entities/{id}/profile`, `/indicators`, `/search`,
  `/series`, `/map`, `/pyramid`, `/streams`, `/streams/{name}`. Interactive
  docs at `/docs`.
- `app/web`: Next.js with MapLibre (country outlines from Natural Earth,
  bundled; no tile server or internet needed) and ECharts. Pages: map,
  entity profile (country, region or bloc), compare, sources and data health.
  It calls the API through `/api`, proxied by `next.config.mjs`.

Notes and bookmarks (phase 2) will live in their own local file, never in the warehouse.

## Rules

- No imports between `data/` and `app/`. Both import `contract/`.
- The app never writes to the warehouse.
- A build is atomic: a new file, then a pointer swap. Old builds are pruned to three.
- Every number carries its source and vintage to the screen.
