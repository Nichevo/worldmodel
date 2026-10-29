# Streams and the MCP server (design; streams partly built)

Other programs on the machine, for example a Metaculus forecasting bot, should
be able to pull exactly the series they need without knowing SQL.

## Named streams (built in phase 0)

A stream is a saved query in `contract/worldmodel_contract/catalogues/streams.yaml`:

```yaml
- name: g7-gdp-growth
  indicator: gdp_growth
  members_of: g7
  start: 1980
  end: 2030
  projections: true
```

Pull it by URL, CLI or file:

```sh
curl "http://127.0.0.1:8000/api/v1/streams/g7-gdp-growth?format=csv"
curl "http://127.0.0.1:8000/api/v1/streams/g7-gdp-growth?as_of=2025-06-01"   # as known on that date
worldmodel-data export g7-gdp-growth --format parquet --out g7.parquet
```

Each row carries entity, period, value, status (E estimate, P projection),
source and vintage. `as_of` serves the latest vintage fetched on or before
that date, which is what an honest back-test needs. Any ad hoc query works the
same way through `/api/v1/series`.

## Machine-readable forecasts (phase 3)

When the forecast engine lands, its output is written to the warehouse as
another source, with quantiles in the `variant` column (`q05`, `q25`, `q50`,
`q75`, `q95`), so a stream of a forecast series returns the full distribution.
A forecast's model, back-test skill score and scenario assumptions go in a
`forecast_runs` table keyed by the vintage. That is a minor schema version bump.

## MCP server (phase 3)

A thin `worldmodel-mcp` entry point in `app/api` exposing the same endpoints
as MCP tools (`search`, `describe_indicator`, `entity`, `series`, `stream`,
`list_streams`), so an LLM agent (Claude or an Ollama model) can query the
data directly. The in-app assistant uses the same tool definitions.

## Stability

- The API is versioned in its path (`/api/v1`); breaking changes get `/api/v2`.
- Stream definitions and the warehouse schema live in `contract/`, and
  changes are listed in its changelog.
- The Metaculus bot itself (reading questions, mapping them to streams,
  submitting forecasts) is a separate project that depends on this one.
