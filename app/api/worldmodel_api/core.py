"""What every area of the API shares: the router the calls hang on, the warehouse, a cursor
that also sees your ratios as indicators, and small helpers used across areas."""

from __future__ import annotations

import re

from dotenv import load_dotenv
from fastapi import APIRouter

from worldmodel_api import userdata
from worldmodel_api.warehouse import Warehouse

load_dotenv()
API_VERSION = "1"
HEADLINE = ["pop_total", "pop_growth_rate", "tfr", "median_age", "life_expectancy", "pop_share_65_plus",
            "net_migration", "gdp_growth", "gdp_usd", "gdp_per_capita_usd", "inflation"]
api = APIRouter(prefix="/api/v1")  # every area module in routes/ adds its calls here
warehouse = Warehouse()  # tests swap it: read it as core.warehouse, never import the name


def cursor():
    """A cursor on the warehouse that also sees your ratios as indicators (see _ratio_views)."""
    cur = warehouse.cursor()
    found = userdata.ratios()
    if found:
        _ratio_views(cur, found)
    return cur


def _ratio_views(cur, found: list[dict]) -> None:
    """Your ratios as indicators: temporary views, for this cursor only, that put each
    ratio beside the warehouse's own rows in series, indicators and indicator_sources
    (the warehouse itself is never written). A ratio's value is numerator / denominator
    x multiplier for each country, year and variant where both have a value from their
    first-ranked source; a projection on either side makes it a projection."""
    db = cur.execute("SELECT current_database()").fetchone()[0].replace('"', '""')
    main = lambda t: f'"{db}".main.{t}'  # noqa: E731
    known = {r[0] for r in cur.execute(f"SELECT indicator_id FROM {main('indicators')}").fetchall()}
    found = [r for r in found if r["numerator"] in known and r["denominator"] in known
             and re.fullmatch(r"my_[a-z0-9_]{1,60}", str(r.get("id", "")))]
    if not found:
        return
    best = lambda i: (f"(SELECT * FROM {main('series')} WHERE indicator_id = '{i}' AND breakdown = '' AND source_id = "  # noqa: E731
                      f"(SELECT source_id FROM {main('indicator_sources')} WHERE indicator_id = '{i}' ORDER BY rank LIMIT 1))")
    parts = [f"""
        SELECT a.entity_id, '{r["id"]}' AS indicator_id, a.period_start, a.freq, '' AS breakdown, a.variant,
            'user' AS source_id, 'ratio' AS vintage, a.value / b.value * {float(r["multiplier"])!r} AS value,
            CASE WHEN a.status = 'P' OR b.status = 'P' THEN 'P' ELSE 'E' END AS status,
            a.is_aggregate OR b.is_aggregate AS is_aggregate, least(a.coverage, b.coverage) AS coverage
        FROM {best(r["numerator"])} a
        JOIN {best(r["denominator"])} b
            ON b.entity_id = a.entity_id AND b.period_start = a.period_start AND b.freq = a.freq AND b.variant = a.variant
        WHERE b.value <> 0""" for r in found]
    cur.execute(f"CREATE OR REPLACE TEMP VIEW series AS SELECT * FROM {main('series')} UNION ALL BY NAME "
                + " UNION ALL ".join(parts))
    cur.execute(f"CREATE OR REPLACE TEMP TABLE ratio_indicators AS SELECT * FROM {main('indicators')} LIMIT 0")
    names = dict(cur.execute(f"SELECT indicator_id, name FROM {main('indicators')}").fetchall())
    for r in found:
        mult = r["multiplier"]
        times = "" if mult == 1 else f" × {mult:g}"
        cur.execute("INSERT INTO ratio_indicators BY NAME SELECT ? AS indicator_id, ? AS name, ? AS description, '' AS synonyms, "
                    "'Your ratios' AS domain, ? AS unit, ? AS decimals, 'A' AS frequency, '' AS breakdowns, 'none' AS agg_method, "
                    "-1e300 AS bound_min, 1e300 AS bound_max, true AS default_on",
                    [r["id"], r["name"], r.get("description") or f"Your ratio: {names[r['numerator']]} ÷ {names[r['denominator']]}{times}.",
                     r.get("unit") or "", int(r.get("decimals", 2))])
    cur.execute(f"CREATE OR REPLACE TEMP VIEW indicators AS SELECT * FROM {main('indicators')} UNION ALL BY NAME "
                "SELECT * FROM ratio_indicators")
    values = ", ".join(f"('{r['id']}', 'user', '{r['id']}', 1.0, 1, 'Worked out from your ratio')" for r in found)
    cur.execute(f"CREATE OR REPLACE TEMP VIEW indicator_sources AS SELECT * FROM {main('indicator_sources')} UNION ALL BY NAME "
                f"SELECT * FROM (VALUES {values}) v(indicator_id, source_id, series, scale, rank, notes)")


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = cursor()
    rel = cur.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def split(s: str | None) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


_lh_cache: dict[tuple, object] = {}


def _build_id() -> str:
    return warehouse.current().path.stem


def _has_cities() -> bool:
    return bool(rows("SELECT 1 FROM information_schema.tables WHERE table_name = 'cities' AND table_schema = 'main'"))


def _has_table(name: str) -> bool:
    return bool(rows("SELECT 1 FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'", [name]))


def _lh(key: tuple, make):
    """Answers that take a while (who ruled where, the factors), kept until the build changes."""
    k = (_build_id(), *key)
    if k not in _lh_cache:
        if len(_lh_cache) > 64:
            _lh_cache.clear()
        _lh_cache[k] = make()
    return _lh_cache[k]
