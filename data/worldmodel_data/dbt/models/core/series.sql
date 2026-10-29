{{ config(materialized='view') }}
-- What the app shows: the latest vintage of every source as published, plus
-- computed aggregates for groups the source does not publish itself.
select o.entity_id, o.indicator_id, o.period_start, o.freq, o.breakdown, o.variant, o.source_id, o.vintage,
    o.value, o.status, false as is_aggregate, null::double as coverage, null::integer as members_total,
    null::integer as members_reporting
from {{ ref('observations') }} o
join {{ ref('vintages') }} v on v.source_id = o.source_id and v.vintage = o.vintage and v.is_latest
union all
select entity_id, indicator_id, period_start, freq, breakdown, variant, source_id, vintage, value, status,
    is_aggregate, coverage, members_total, members_reporting
from {{ ref('aggregates') }}
