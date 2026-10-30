-- Region and bloc values built from member countries, by each indicator's
-- aggregation rule in the catalogue. Coverage is the share of the group's
-- population (UN WPP) living in members that reported a value.
-- Prediction-interval bounds (lower80 .. upper95) are not added up: the sum of
-- countries' upper bounds is far wider than the group's own range.
with members as (
    select * from {{ ref('int_active_members') }}
),
pop as (
    select entity_id, period_start, freq, value from {{ ref('int_default_values') }}
    where indicator_id = 'pop_total'
),
group_size as (
    select m.group_id, m.period_start, m.freq, count(*) as members_total, sum(p.value) as pop_total
    from members m
    left join pop p on p.entity_id = m.member_id and p.period_start = m.period_start and p.freq = m.freq
    group by all
),
country_values as (
    select l.*, m.group_id
    from {{ ref('int_latest') }} l
    join members m on m.member_id = l.entity_id and m.period_start = l.period_start and m.freq = l.freq
    where l.variant not like 'lower%' and l.variant not like 'upper%'
),
dv as (
    select * from {{ ref('int_default_values') }}
),
summed as (
    select cv.group_id as entity_id, cv.indicator_id, cv.period_start, cv.freq, cv.breakdown, cv.variant,
        cv.source_id, max(cv.vintage) as vintage, sum(cv.value) as value, max(cv.status) as status,
        count(*) as members_reporting, sum(p.value) as reporting_pop
    from country_values cv
    join {{ ref('indicators') }} i on i.indicator_id = cv.indicator_id and i.agg_method = 'sum'
    left join pop p on p.entity_id = cv.entity_id and p.period_start = cv.period_start and p.freq = cv.freq
    group by all
),
weighted as (
    select cv.group_id as entity_id, cv.indicator_id, cv.period_start, cv.freq, cv.breakdown, cv.variant,
        cv.source_id, max(cv.vintage) as vintage, sum(cv.value * w.value) / sum(w.value) as value,
        max(cv.status) as status, count(*) as members_reporting, sum(p.value) as reporting_pop
    from country_values cv
    join {{ ref('indicators') }} i on i.indicator_id = cv.indicator_id and i.agg_method = 'weighted_mean'
    join dv w on w.indicator_id = i.agg_weight and w.entity_id = cv.entity_id
        and w.period_start = cv.period_start and w.freq = cv.freq
    left join pop p on p.entity_id = cv.entity_id and p.period_start = cv.period_start and p.freq = cv.freq
    where cv.breakdown = '' and w.value > 0
    group by all
),
ratio as (
    select m.group_id as entity_id, i.indicator_id, n.period_start, n.freq, '' as breakdown, 'central' as variant,
        s.source_id, max(n.vintage) as vintage,
        sum(n.value) / nullif(sum(d.value), 0) * any_value(i.agg_multiplier) as value,
        greatest(max(n.status), max(d.status)) as status, count(*) as members_reporting,
        sum(p.value) as reporting_pop
    from {{ ref('indicators') }} i
    join {{ ref('indicator_sources') }} s on s.indicator_id = i.indicator_id and s.rank = 1
    join dv n on n.indicator_id = i.agg_numerator
    join dv d on d.indicator_id = i.agg_denominator and d.entity_id = n.entity_id
        and d.period_start = n.period_start and d.freq = n.freq
    join members m on m.member_id = n.entity_id and m.period_start = n.period_start and m.freq = n.freq
    left join pop p on p.entity_id = n.entity_id and p.period_start = n.period_start and p.freq = n.freq
    where i.agg_method = 'ratio'
    group by m.group_id, i.indicator_id, n.period_start, n.freq, s.source_id, i.agg_multiplier
),
combined as (
    select * from summed
    union all select * from weighted
    union all select * from ratio
)
select c.entity_id, c.indicator_id, c.period_start, c.freq, c.breakdown, c.variant, c.source_id, c.vintage,
    c.value, c.status,
    coalesce(c.reporting_pop / nullif(g.pop_total, 0), c.members_reporting / g.members_total) as coverage,
    g.members_total::integer as members_total,
    c.members_reporting::integer as members_reporting
from combined c
join group_size g on g.group_id = c.entity_id and g.period_start = c.period_start and g.freq = c.freq
where c.value is not null
