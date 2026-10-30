# worldmodel

A personal app for exploring, comparing, mapping and (later) forecasting data
about every country, region and bloc. Everything runs on your own machine.

This is **phase 0**: the foundations, with population (UN World Population
Prospects) and GDP growth (IMF World Economic Outlook) as the first data.

![Fertility rate map](docs/img/map.png)

## How it fits together

```
 sources ──► data/ (worldmodel-data CLI) ──► var/warehouse/builds/*.duckdb ──► app/api (FastAPI) ──► app/web (Next.js)
               fetch, keep every vintage,       CURRENT points at the           read-only             map, profiles,
               build with dbt, validate,        live build                                          compare, data health
               swap in only if gates pass                                         ▲
                                                                                  └── other tools: /api/v1/streams, CSV/Parquet/JSON
                          contract/  ◄── both sides depend on this and on nothing of each other:
                                         schema + version, entity crosswalk, indicator catalogue,
                                         sources, named streams, driver graph
```

- **data/** fetches sources, stores each release unchanged as a dated vintage,
  builds the DuckDB warehouse with dbt, runs the validation gates, and only then
  points `var/warehouse/CURRENT` at the new build. Runs headless; no web app needed.
- **app/** is the local API and web app. It reads whichever warehouse it is
  pointed at, never writes to it, and checks the schema version on start. It
  ships with a sample warehouse (`app/sample/`), so it runs with no pipeline.
  The only files it writes are your own, in `var/user/`: saved layouts,
  settings, which indicators are switched on, and the history log.
- **contract/** is the only code both import. Besides the schema and
  catalogues it holds the shared view of the data folder: settings and their
  limits, disk use, and the refresh log (`worldmodel_contract.local`).

More in [docs/architecture.md](docs/architecture.md).

## Quick start

Needs Python 3.11+ and Node 20+.

```sh
make setup        # virtualenv + Python packages + npm install
make api          # terminal 1: API on http://127.0.0.1:8000 (docs at /docs)
make web          # terminal 2: app on http://localhost:3030
```

The app starts on the bundled sample. To load current data:

```sh
make refresh      # fetch every source (UN, IMF, World Bank, OWID), build, validate, go live
```

The API notices the new build on its next request; no restart needed.

### On Windows, with conda

Needs [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html)
and Git. The scripts find conda themselves, so any terminal works: PowerShell,
Command Prompt or an Anaconda Prompt. In PowerShell, type `.\setup.bat` and so on.

```bat
git clone https://github.com/Nichevo/worldmodel D:\worldmodel
cd D:\worldmodel
.\setup.bat       :: once: conda env "worldmodel" (Python, Node, Git) + all packages
.\start.bat       :: API and web app in their own windows, then the browser
.\refresh.bat     :: fetch the latest data, build, check, go live (the app can stay open)
```

If conda is installed somewhere unusual and the scripts can't find it, run them
from an Anaconda Prompt instead.

Your data lives in `var\` inside this folder (set as `WORLDMODEL_HOME` in the
conda environment, so it doesn't depend on where you run commands from). To
load current data, run `.\refresh.bat`. Each refresh is logged; the Data status
page charts the space used, the rows changed and how each run went, and warns
when the folder nears the size limit set in Settings.

### Updating

Stop the app (close its two windows), then:

```bat
.\update.bat       :: Windows: latest code from GitHub + any new packages
```
```sh
make update       # macOS / Linux
```

Updates only touch code and packages; `var/` (your downloads and builds) is
never changed. If an update says `environment.yml` changed, run `setup.bat` again.

## The data side

```sh
worldmodel-data fetch un_wpp                  # download a source, store a new vintage
worldmodel-data fetch imf_weo --from DIR      # or load files you downloaded yourself
worldmodel-data build                         # build + validate + swap in
worldmodel-data refresh                       # fetch every source, then build; logged for Data status
worldmodel-data status                        # vintages, live build, latest report, disk use
worldmodel-data free-space                    # delete old raw downloads (keeps 2 per source)
worldmodel-data validate                      # catalogue checks + gates on the live build
worldmodel-data keys                          # API key register: which keys are set
worldmodel-data export nz-population --format csv
```

Data lives in `./var` (set `WORLDMODEL_HOME` to move it). Back that folder up:
stored vintages are the one thing you cannot download again.

**Validation gates.** A build is swapped in only if every gate passes: dbt
tests (unique keys, every code in the crosswalk, values inside each
indicator's bounds, country populations add up to the UN world total, age
groups add up to the total), at least 200 countries for the core population
indicators and 180 for GDP growth, spot checks against published values, and
no series losing more than 10 percent of its rows. Each build writes a report
to `var/warehouse/reports/` with a random sample of values and links to check
by eye on the source sites. A failed build is kept as `*.failed.duckdb` and
the app keeps reading the previous one.

**Vintages.** Every fetch keeps the source files as downloaded under
`var/raw/`, plus a normalised Parquet copy under `var/vintages/`. A re-fetch
with identical content is skipped; a revised release becomes a new vintage
(`2024+20261105`). The API can answer "as known on a date" from these
(`as_of=` on `/series` and `/streams`).

## Data in this phase

| Source | What | Notes |
| --- | --- | --- |
| UN World Population Prospects 2024 | Population, growth, births, deaths, fertility, mean age at childbearing, sex ratio at birth, life expectancy, median age, migration, population by age and sex (pyramids), age shares, dependency ratio | Estimates to 2023, medium-variant projections to 2100; the low and high variants and the 80% and 95% prediction intervals as variants `low`, `high`, `lower80` .. `upper95` (from the optional "other variants" file) |
| IMF World Economic Outlook | Real GDP growth, GDP in US dollars and PPP, GDP per person, inflation | Latest release from the DataMapper API; projections about five years ahead |
| IMF WEO historical forecasts | What every WEO since 1990 forecast for GDP growth and inflation | One Excel file, linked from the WEO page of the IMF Data Portal; each release kept as breakdown `release=YYYY-MM`, for the track record |
| World Bank World Development Indicators | Every WDI series (about 1,500): economy, prices and price levels, trade, government, military spending (SIPRI), labour, poverty, health, education, environment and more; income groups | One bulk zip (if the World Bank's download server refuses it, the main series come from its Indicators API instead, and the rest wait for the next refresh). About 120 main series start switched on under plain ids (`unemployment`, `military_spending_gdp`, `price_level_ratio`); the rest are `wdi_<code>`, switched off until you switch them on on the Indicators page. Series the catalogue already has (population, GDP, inflation) become a second source for the comparison |
| Our World in Data energy dataset | Electricity by source (Ember), primary energy, production and consumption of oil, gas and coal (Energy Institute, EIA), carbon intensity | One CSV from OWID's GitHub. Shares and per-person figures for continents and blocs are recomputed from the amounts |
| Our World in Data charts | Deaths in armed conflicts (UCDP), by the country where they occurred | One chart download each; a chart OWID has removed only warns |

**Income groups** (high, upper-middle, lower-middle and low income) are regions
like the continents: members are the World Bank's latest classification, and
their values are the World Bank's own where it publishes them, built from
members otherwise.

**Sources compared.** Where two sources publish the same figure (UN and World
Bank population, IMF and World Bank growth and inflation), the **Sources** page
draws them side by side for a country and lists the countries where they
differ most, in each country's latest common year: more than 5% apart, or for
percentages more than a point and 10%. Country pages list their own
disagreements, and each build reports them (`sources:divergence`). API:
`/api/v1/sources/indicators`, `/sources/compare?indicator=gdp_growth&entity=ARG`,
`/sources/divergence?indicator=gdp_growth&flagged=true`.

**The map page** holds up to six panels: one, two side by side or stacked,
one large and two small, three side by side, two by two, one large and four
small, or three by two.

## Forecasts

The **Forecasts** page (also linked from each country's profile) has two parts:

- **Population what-if.** Move fertility, life expectancy and migration away
  from the UN projection and see the total, the age pyramid and key shares
  change. The model (`contract/worldmodel_contract/cohort.py`) ages the
  population a year at a time by single year of age and sex, tuned each year to
  the UN's births and deaths. What you see is the UN projection plus the
  difference your changes make, so at the default settings it is the UN's
  exactly. Each build checks the model on its own against the UN projection and
  in a 30-year back-test (`whatif:` rows in the build report).
- **IMF track record.** Past WEO forecasts of GDP growth and inflation against
  what happened: typical miss and bias by how far ahead the forecast was, for
  each country and all countries together. Releases come from the IMF's
  historical file and from every IMF vintage stored here.

API: `/api/v1/whatif?entity=NZL&tfr=-0.5&e0=2&mig=0.5&extra=0&phase=10` and
`/api/v1/track-record?indicator=gdp_growth&entity=NZL`. `/series` and streams
take several variants (`variant=central,lower80,upper80`); the
`*-forecast` streams carry the UN ranges for forecasting tools.

Regions and blocs are entities with membership over time: the world, UN M49
continents and sub-regions, and EU, euro area, NATO, ASEAN, NAFTA/USMCA,
Mercosur, OPEC, G7, G20 and BRICS. A bloc's value for a year is built from the
members it had that year, with coverage shown. Bloc join and leave dates were
entered by hand and are marked `verified: no` in
`contract/worldmodel_contract/catalogues/memberships.csv` until checked
against the source linked on each row.

**The sample warehouse** holds real UN WPP 2024 data, a real but old IMF
release (April 2015), about 325 real World Bank series from a mirror, and the
main OWID energy series, because the build environment could not reach the UN,
IMF or World Bank sites. Its income groups are worked out from GNI per person
rather than read from the World Bank. The app says so in a banner. See
[scripts/sample/README.md](scripts/sample/README.md).

## Designed now, built later

- **Ask the data** assistant (phase 3), on Ollama: [docs/design/assistant.md](docs/design/assistant.md)
- **Streams and an MCP server** for other tools such as a Metaculus bot: [docs/design/streams-and-mcp.md](docs/design/streams-and-mcp.md)
- **Linked forecasts**: the driver graph format is fixed in `contract/.../driver_graph.yaml`

## Tests

```sh
make test         # contract checks, the pipeline end to end on fixtures, the API on the sample
make typecheck    # the web app
```

Licences and attributions: [NOTICE.md](NOTICE.md).
