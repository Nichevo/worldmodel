"""Read queries over the warehouse, shared by the API and the CLI export.

Pure SQL builders: they take parameters and return (sql, params). Neither
component imports the other, so the query logic every reader of the
warehouse needs lives here, next to the schema it depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

def period_label(alias: str = "") -> str:
    """SQL for the period label: 2024, 2024-Q1, 2024-03 or 2024-03-31."""
    p, f = f"{alias}period_start", f"{alias}freq"
    return (f"CASE {f} WHEN 'A' THEN strftime({p}, '%Y') "
            f"WHEN 'Q' THEN strftime({p}, '%Y') || '-Q' || quarter({p}) "
            f"WHEN 'M' THEN strftime({p}, '%Y-%m') ELSE strftime({p}, '%Y-%m-%d') END")


@dataclass
class SeriesQuery:
    indicator_id: str
    entity_ids: list[str] = field(default_factory=list)
    members_of: str | None = None  # a group id: all members active at any time in the range
    start: int | None = None
    end: int | None = None
    source_id: str | None = None  # default: the indicator's rank-1 source
    breakdown: str | None = ""  # None = every breakdown
    variant: str = "central"
    projections: bool = True
    as_of: date | None = None  # point in time: values as known on this date, from the vintages


def series_sql(q: SeriesQuery) -> tuple[str, list]:
    """Rows of entity_id, indicator_id, period, period_start, freq, breakdown, variant,
    source_id, vintage, value, status, is_aggregate, coverage."""
    params: list = []
    where = ["s.indicator_id = ?"]
    params.append(q.indicator_id)

    if q.source_id:
        where.append("s.source_id = ?")
        params.append(q.source_id)
    else:
        where.append("s.source_id = (SELECT source_id FROM indicator_sources WHERE indicator_id = ? "
                     "ORDER BY rank LIMIT 1)")
        params.append(q.indicator_id)

    entity_filter = []
    if q.entity_ids:
        entity_filter.append(f"s.entity_id IN ({', '.join('?' * len(q.entity_ids))})")
        params.extend(q.entity_ids)
    if q.members_of:
        entity_filter.append("s.entity_id IN (SELECT member_id FROM memberships WHERE group_id = ?)")
        params.append(q.members_of)
    if entity_filter:
        where.append("(" + " OR ".join(entity_filter) + ")")

    if q.start is not None:
        where.append("s.period_start >= make_date(?, 1, 1)")
        params.append(q.start)
    if q.end is not None:
        where.append("s.period_start <= make_date(?, 12, 31)")
        params.append(q.end)
    if q.breakdown is not None:
        where.append("s.breakdown = ?")
        params.append(q.breakdown)
    where.append("s.variant = ?")
    params.append(q.variant)
    if not q.projections:
        where.append("s.status = 'E'")

    if q.as_of is None:
        table = "series s"
        extra = "s.is_aggregate, s.coverage"
    else:
        # Latest vintage retrieved on or before as_of, per source. Aggregates are
        # not stored per vintage, so a point-in-time query returns published values only.
        table = ("observations s JOIN (SELECT source_id, arg_max(vintage, retrieved_at) AS vintage FROM vintages "
                 "WHERE retrieved_at <= ? GROUP BY source_id) v ON v.source_id = s.source_id AND v.vintage = s.vintage")
        params.insert(0, q.as_of)
        extra = "false AS is_aggregate, NULL::DOUBLE AS coverage"

    sql = (f"SELECT s.entity_id, s.indicator_id, {period_label('s.')} AS period, "
           f"s.period_start, s.freq, s.breakdown, s.variant, s.source_id, s.vintage, s.value, s.status, {extra} "
           f"FROM {table} WHERE {' AND '.join(where)} ORDER BY s.entity_id, s.breakdown, s.period_start")
    return sql, params


def stream_query(stream: dict) -> SeriesQuery:
    """Turn a streams.yaml entry into a SeriesQuery."""
    return SeriesQuery(
        indicator_id=stream["indicator"],
        entity_ids=list(stream.get("entities", [])),
        members_of=stream.get("members_of"),
        start=stream.get("start"),
        end=stream.get("end"),
        source_id=stream.get("source"),
        variant=stream.get("variant", "central"),
        projections=stream.get("projections", True),
    )
