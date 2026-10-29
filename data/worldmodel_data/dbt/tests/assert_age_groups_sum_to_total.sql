-- Gate: for every country and year, the age groups (both sexes) must add up
-- to the total population within 0.5 percent.
with ages as (
    select entity_id, period_start, vintage, sum(value) as total
    from {{ ref('observations') }}
    where indicator_id = 'pop_by_age_sex' and breakdown like '%|sex=total'
    group by all
)
select a.entity_id, a.period_start, a.total as age_sum, o.value as pop_total
from ages a
join {{ ref('observations') }} o
    on o.entity_id = a.entity_id and o.period_start = a.period_start and o.vintage = a.vintage
    and o.indicator_id = 'pop_total' and o.breakdown = '' and o.variant = 'central'
where abs(a.total - o.value) / nullif(o.value, 0) > 0.005
