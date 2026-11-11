"""An MCP server, so an AI assistant (Claude Desktop, or any MCP client) can use the app's data.

Run `worldmodel-mcp` (installed with the app). In Claude Desktop's settings file add:

    "mcpServers": {"worldmodel": {"command": "worldmodel-mcp"}}

with the full path to worldmodel-mcp.exe in the worldmodel conda environment if it is not on PATH
(Settings > API access in the app shows the exact lines). WORLDMODEL_URL and WORLDMODEL_KEY in
"env" point it at the app on another PC. The public API must be switched on in the app.
"""

from __future__ import annotations

import json

from worldmodel_client.client import Client, WorldmodelError


def build(client: Client | None = None):
    try:  # mcp 2.x
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server

    c = client or Client()
    mcp = Server("worldmodel", instructions=(
        "Country and region data from the user's own worldmodel app: demographics, economy, trade, energy, climate, "
        "conflict, events, crowd forecasts and the user's predictions log. Use search to turn names into ids first."))

    def safe(fn, *a, **k) -> str:
        try:
            return json.dumps(fn(*a, **k), default=str)[:200_000]
        except WorldmodelError as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def search(q: str) -> str:
        """Find country, group and indicator ids by name (for example 'new zealand', 'inflation')."""
        return safe(c.search, q)

    @mcp.tool()
    def data(indicator: str, entities: str = "", start: int | None = None, end: int | None = None, as_of: str | None = None) -> str:
        """Yearly figures for one indicator. entities: comma-separated ids (blank for every country).
        as_of: YYYY-MM-DD for the figures as known on that date. Each row says estimate or projection and its source."""
        return safe(c.data, indicator, entities or None, start, end, None, as_of, True, False)

    @mcp.tool()
    def forecast(indicator: str, entity: str, horizon: int = 10) -> str:
        """A statistical forecast with p10, p50 and p90 for each future year."""
        return safe(c.forecast, indicator, entity, horizon)

    @mcp.tool()
    def events(entities: str = "", kinds: str = "", start: str | None = None, end: str | None = None, q: str | None = None) -> str:
        """Dated events (elections, coups, conflicts, disasters, recessions...) for countries and years."""
        return safe(c.events, entities or None, kinds or None, start, end, q, 300)

    @mcp.tool()
    def crowd(country: str | None = None, q: str | None = None) -> str:
        """Open crowd forecasting questions (Polymarket, Metaculus, Manifold) with their chances now."""
        return safe(c.crowd, country, q)

    @mcp.tool()
    def predictions(entity: str | None = None, indicator: str | None = None) -> str:
        """The user's predictions log, with states and scores."""
        return safe(c.predictions, entity, indicator)

    @mcp.tool()
    def alike(entity: str, preset: str = "everything", year: int | None = None) -> str:
        """The countries most like one country in a year (presets: economy, people, government, energy, everything)."""
        return safe(c.alike, entity, preset, year)

    @mcp.tool()
    def synthetic(entity: str, indicator: str, year: int) -> str:
        """Synthetic comparison: what a country's indicator might have done without an event in that year."""
        return safe(c.synthetic, entity, indicator, year)

    return mcp


def main() -> None:
    build().run()


if __name__ == "__main__":
    main()
