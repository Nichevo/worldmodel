# "Ask the data" assistant (design; build in phase 3)

A chat box in the app that turns a question such as "compare Nigeria and Kenya
fertility since 1980" into a chart with sources. It never answers with numbers
from the model's memory: every number comes from the warehouse through the API.

## Shape

```
question ─► local LLM (Ollama, tool calling) ─► tools = the API endpoints ─► chart spec + sources ─► web app renders it
```

The model's only job is to pick ids and parameters. Small local models are
reliable at that when the tools have a fixed schema and the ids come from a
search tool rather than from memory.

## Tools (all exist in phase 0 as API endpoints)

| Tool | Endpoint | Used for |
| --- | --- | --- |
| `search(q)` | `GET /api/v1/search` | Words to entity and indicator ids, through names and synonyms ("UK" → GBR, "ageing" → pop_share_65_plus) |
| `describe_indicator(id)` | `GET /api/v1/indicators/{id}` | Unit, definition, years available, source |
| `entity(id)` | `GET /api/v1/entities/{id}` | Members of a bloc, groups a country is in |
| `series(indicator, entities, start, end)` | `GET /api/v1/series` | The data |
| `show_chart(spec)` | (front end) | Hand back a line, bar, map or pyramid spec for the app to draw |

Phase 0 already gives every entity and indicator a plain name, synonyms and a
description, which is what `search` needs.

## Model

Default: Ollama on the same machine through its OpenAI-compatible endpoint
(`OLLAMA_BASE_URL`, default `http://localhost:11434/v1`), with a model that
supports tool calling, for example Qwen 2.5 or Llama 3.1 (`OLLAMA_MODEL`).
Nothing leaves the computer and nothing costs money. A cloud model can be
swapped in through the same interface for harder questions
(`ANTHROPIC_API_KEY`), off by default.

## Where it lives

A small module in `app/api` (`/api/v1/assistant`) that runs the tool loop and
streams back the chart spec. The tool definitions are generated from the same
endpoint signatures as the MCP server (see streams-and-mcp.md), so there is
one integration surface to maintain.

## Guardrails

- Answers cite source and vintage for every series, like every other chart.
- Projections are labelled as projections.
- If search finds nothing, the assistant says so and lists close matches
  instead of guessing.
