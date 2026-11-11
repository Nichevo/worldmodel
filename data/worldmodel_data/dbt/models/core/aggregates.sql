-- Region and bloc values computed from member countries, kept only where the
-- source does not publish its own value for that group. Sorted for fast lookups.
select a.*, true as is_aggregate
from {{ ref('int_aggregates') }} a
anti join {{ ref('int_latest') }} p
    on p.entity_id = a.entity_id and p.indicator_id = a.indicator_id and p.period_start = a.period_start
    and p.freq = a.freq and p.breakdown = a.breakdown and p.variant = a.variant and p.source_id = a.source_id
order by a.indicator_id, a.entity_id, a.period_start
