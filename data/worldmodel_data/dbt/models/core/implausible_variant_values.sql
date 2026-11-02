-- Values left out of observations as implausible, for the build report: central
-- values outside the indicator's bounds, and variant values that mean nothing.
select s.source_id, s.indicator_id, s.entity_id, s.variant, count(*) as rows,
    min(year(s.period_start)) as first_year, max(year(s.period_start)) as last_year,
    min(s.value) as min_value, max(s.value) as max_value, any_value(i.bound_min) as bound_min, any_value(i.bound_max) as bound_max
from {{ ref('int_staged') }} s
join {{ ref('indicators') }} i on i.indicator_id = s.indicator_id
where s.entity_id is not null
    and ((s.variant = 'central' and not (isfinite(s.value) and s.value between i.bound_min and i.bound_max))
         or (s.variant <> 'central' and not {{ variant_value_plausible('s', 'i') }}))
group by all
