-- Every staged vintage with its source codes resolved to entity ids through
-- the crosswalk. A code maps only for dates inside its validity window.
select
    c.entity_id,
    r.indicator_id,
    r.period_start,
    r.freq,
    coalesce(r.breakdown, '') as breakdown,
    coalesce(r.variant, 'central') as variant,
    r.source_id,
    r.vintage,
    r.value,
    r.status,
    r.scheme,
    r.source_code
from {{ source('src', 'raw_observations') }} r
left join {{ source('src', 'entity_codes') }} c
    on c.scheme = r.scheme
    and c.code = r.source_code
    and (c.valid_from is null or r.period_start >= c.valid_from)
    and (c.valid_to is null or r.period_start <= c.valid_to)
