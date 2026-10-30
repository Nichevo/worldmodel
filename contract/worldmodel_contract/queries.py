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
    variant: str = "central"  # one variant, several comma-separated (central,lower80,upper80), or "all"
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
    variants = [v.strip() for v in q.variant.split(",") if v.strip()]
    if "all" not in variants:
        where.append(f"s.variant IN ({', '.join('?' * len(variants))})")
        params.extend(variants)
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
           f"FROM {table} WHERE {' AND '.join(where)} ORDER BY s.entity_id, s.breakdown, s.variant, s.period_start")
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
        variant=",".join(stream["variants"]) if stream.get("variants") else stream.get("variant", "central"),
        projections=stream.get("projections", True),
    )


def forecast_pairs_sql(indicator_id: str, entity_ids: list[str] | None = None, countries_only: bool = True,
                       source_id: str = "imf_weo") -> tuple[str, list]:
    """Each past forecast next to what happened, for a forecast track record.

    Forecasts come from every stored vintage of the source (one per release) and
    from <source>_history (all releases in one vintage, breakdown 'release=YYYY-MM'),
    the history file winning where both have a release. What happened is the
    latest vintage's estimate (status E), so it is null for years not yet known.
    Rows: entity_id, release ('YYYY-MM'), year, horizon (year - release year),
    forecast, actual."""
    params: list = [source_id, indicator_id, f"{source_id}_history", indicator_id, source_id, indicator_id]
    ent = ""
    if entity_ids:
        ent = f"AND f.entity_id IN ({', '.join('?' * len(entity_ids))})"
        params.extend(entity_ids)
    if countries_only:
        ent += " AND f.entity_id IN (SELECT entity_id FROM entities WHERE type = 'country')"
    sql = f"""
        WITH own AS (
            SELECT entity_id, left(vintage, 7) AS release, year(period_start) AS year, value
            FROM observations
            WHERE source_id = ? AND indicator_id = ? AND breakdown = '' AND variant = 'central' AND freq = 'A'
                AND regexp_matches(vintage, '^\\d{{4}}-\\d{{2}}')
        ),
        hist AS (
            SELECT entity_id, split_part(breakdown, '=', 2) AS release, year(period_start) AS year, value
            FROM series
            WHERE source_id = ? AND indicator_id = ? AND breakdown LIKE 'release=%' AND variant = 'central'
        ),
        forecasts AS (
            SELECT * FROM hist
            UNION ALL
            SELECT * FROM own o WHERE NOT EXISTS (
                SELECT 1 FROM hist h WHERE h.release = o.release AND h.entity_id = o.entity_id)
        ),
        actual AS (
            SELECT entity_id, year(period_start) AS year, value FROM series
            WHERE source_id = ? AND indicator_id = ? AND breakdown = '' AND variant = 'central' AND status = 'E'
        )
        SELECT f.entity_id, f.release, f.year, f.year - CAST(left(f.release, 4) AS INTEGER) AS horizon,
            any_value(f.value) AS forecast, any_value(a.value) AS actual
        FROM forecasts f LEFT JOIN actual a ON a.entity_id = f.entity_id AND a.year = f.year
        WHERE f.year >= CAST(left(f.release, 4) AS INTEGER) - 1 {ent}
        GROUP BY ALL
        ORDER BY f.entity_id, f.release, f.year"""
    return sql, params


# Two sources' values for the same country and year "differ" when they are more than
# this far apart: relative to the larger of the two, or in points for percentages.
DIVERGE_RELATIVE = 0.05
DIVERGE_POINTS = 1.0


def divergence_sql(indicator_id: str | None = None, entity_ids: list[str] | None = None,
                   latest_only: bool = True, flagged_only: bool = False) -> tuple[str, list]:
    """Where an indicator's default source and its other sources disagree.

    Compares the rank-1 source with each other source on the same country and year
    (published estimates only: central values, no breakdowns, no projections, no
    computed aggregates). Rows: indicator_id, entity_id, year, source_a, value_a,
    source_b, value_b, diff (b - a), rel (|diff| / larger of the two), flagged.
    A percentage differs when it is more than DIVERGE_POINTS points and 10% apart;
    anything else when more than DIVERGE_RELATIVE apart. latest_only keeps each
    pair's latest common year for each country."""
    params: list = []
    where = []
    if indicator_id:
        where.append("a.indicator_id = ?")
        params.append(indicator_id)
    if entity_ids:
        where.append(f"a.entity_id IN ({', '.join('?' * len(entity_ids))})")
        params.extend(entity_ids)
    cond = ("AND " + " AND ".join(where)) if where else ""
    sql = f"""
        WITH est AS (
            SELECT s.indicator_id, s.entity_id, year(s.period_start) AS year, s.source_id, s.value, r.rank
            FROM series s
            JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
            JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
            WHERE s.breakdown = '' AND s.variant = 'central' AND s.status = 'E' AND s.freq = 'A'
                AND NOT s.is_aggregate
                AND s.indicator_id IN (SELECT indicator_id FROM indicator_sources GROUP BY 1 HAVING count(*) > 1)
        ),
        pairs AS (
            SELECT a.indicator_id, a.entity_id, a.year, a.source_id AS source_a, a.value AS value_a,
                b.source_id AS source_b, b.value AS value_b, b.value - a.value AS diff,
                abs(b.value - a.value) / nullif(greatest(abs(a.value), abs(b.value)), 0) AS rel
            FROM est a JOIN est b ON b.indicator_id = a.indicator_id AND b.entity_id = a.entity_id
                AND b.year = a.year AND b.rank > a.rank
            WHERE a.rank = 1 {cond}
        )
        SELECT p.*, coalesce(CASE WHEN i.unit = 'percent' OR i.unit LIKE '%\\%%' ESCAPE '\\'
                                  THEN abs(p.diff) > {DIVERGE_POINTS} AND p.rel > 0.1
                                  ELSE p.rel > {DIVERGE_RELATIVE} END, false) AS flagged
        FROM pairs p JOIN indicators i USING (indicator_id)
        {"QUALIFY row_number() OVER (PARTITION BY p.indicator_id, p.entity_id, p.source_b ORDER BY p.year DESC) = 1"
         if latest_only else ""}"""
    if flagged_only:
        sql = f"SELECT * FROM ({sql}) WHERE flagged"
    return sql + " ORDER BY rel DESC NULLS LAST", params
