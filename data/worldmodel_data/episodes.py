"""Episodes worked out from the data: recessions, booms, inflation spikes, debt surges.

Run by the build after dbt, on the new warehouse. Each rule in the contract's
episode_rules.yaml looks at one indicator per country (estimates only, from the
indicator's default source, main series only) and finds runs of consecutive years
that pass its test. Each run becomes a row in the events table with source
"worldmodel", dated 1 January of its first year to 31 December of its last
(precision "year"), with its size and the year-by-year values in detail.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

import duckdb
import yaml

from worldmodel_contract import catalogue

SOURCE = "worldmodel"


@dataclass
class Rule:
    id: str
    kind: str
    title: str
    indicator: str
    test: str
    threshold: float
    min_years: int = 1
    window: int = 3
    size: str = "max"
    size_unit: str = ""
    subkind: str | None = None
    description: str = ""


@dataclass
class Episode:
    rule: Rule
    entity_id: str
    years: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    excess: list[float] = field(default_factory=list)  # how far past the threshold's baseline each year was

    @property
    def size(self) -> float:
        how = self.rule.size
        if how == "sum":
            return sum(self.values)
        if how == "mean":
            return sum(self.values) / len(self.values)
        if how == "min":
            return min(self.values)
        if how == "max_excess":
            return max(self.excess)
        return max(self.values)


def rules() -> list[Rule]:
    with (catalogue.CATALOGUE_DIR / "episode_rules.yaml").open(encoding="utf-8") as f:
        return [Rule(**r) for r in yaml.safe_load(f)]


def find(rule: Rule, series: dict[int, float], entity_id: str) -> list[Episode]:
    """Runs of consecutive years in one country's series that pass the rule's test."""
    years = sorted(series)
    out: list[Episode] = []
    current: Episode | None = None
    for y in years:
        v = series[y]
        hit, excess = _test(rule, series, y, v)
        if hit and current is not None and current.years[-1] == y - 1:
            current.years.append(y)
            current.values.append(v)
            current.excess.append(excess)
            continue
        if current is not None:
            out.append(current)
            current = None
        if hit:
            current = Episode(rule, entity_id, [y], [v], [excess])
    if current is not None:
        out.append(current)
    return [e for e in out if len(e.years) >= rule.min_years]


def _test(rule: Rule, series: dict[int, float], y: int, v: float) -> tuple[bool, float]:
    t = rule.test
    if t == "below":
        return v < rule.threshold, rule.threshold - v
    if t == "above":
        return v >= rule.threshold, v - rule.threshold
    if t == "rise":
        before = series.get(y - rule.window)
        if before is None:
            return False, 0.0
        return v - before >= rule.threshold, v - before
    if t == "above_trend":
        past = [series[p] for p in range(y - rule.window, y) if p in series]
        if len(past) < max(3, rule.window // 2):
            return False, 0.0
        gap = v - statistics.median(past)
        return gap >= rule.threshold, gap
    raise ValueError(f"episode rule {rule.id}: unknown test {t}")


def compute(con: duckdb.DuckDBPyConnection) -> int:
    """Add every rule's episodes to the events table. Returns how many were added."""
    rows = []
    for rule in rules():
        data = con.execute("""
            SELECT s.entity_id, year(s.period_start) AS y, s.value
            FROM series s
            JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id AND r.rank = 1
            JOIN entities e ON e.entity_id = s.entity_id
            WHERE s.indicator_id = ? AND s.status = 'E' AND s.breakdown = '' AND s.variant = 'central'
                AND s.freq = 'A' AND e.type IN ('country', 'historical_country')
            ORDER BY 1, 2""", [rule.indicator]).fetchall()
        by_entity: dict[str, dict[int, float]] = {}
        for entity_id, y, v in data:
            by_entity.setdefault(entity_id, {})[y] = v
        for entity_id, series in by_entity.items():
            for ep in find(rule, series, entity_id):
                rows.append(_row(ep))
    if rows:
        cols = ("event_id", "entity_id", "source_id", "vintage", "kind", "subkind", "title", "start_date", "end_date",
                "precision", "size", "size_unit", "deaths", "affected", "damage_usd", "place", "url", "detail")
        con.executemany(f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
    return len(rows)


def _row(ep: Episode) -> tuple:
    r = ep.rule
    first, last = ep.years[0], ep.years[-1]
    span = str(first) if first == last else f"{first}-{last}"
    values = ", ".join(f"{y}: {v:.1f}" for y, v in zip(ep.years, ep.values))
    return (f"{SOURCE}:{r.id}:{ep.entity_id}:{first}", ep.entity_id, SOURCE, None, r.kind, r.subkind,
            f"{r.title} {span}", date(first, 1, 1), date(last, 12, 31), "year", round(ep.size, 2), r.size_unit,
            None, None, None, None, None, f"{r.description} Values ({r.indicator}): {values}.")
