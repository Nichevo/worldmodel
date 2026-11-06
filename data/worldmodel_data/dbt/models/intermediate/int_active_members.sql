-- Members of each group in each period, resolved at the middle of the period,
-- so a 1990 EU value uses the twelve members of 1990.
-- Only the periods of indicators that are added up for groups (and population, for coverage):
-- daily market series (aggregation none) would otherwise multiply this table by thousands of days.
with periods as (
    select distinct l.period_start, l.freq from {{ ref('int_latest') }} l
    join {{ ref('indicators') }} i on i.indicator_id = l.indicator_id
    where i.agg_method <> 'none' or i.indicator_id = 'pop_total'
),
mid as (
    select period_start, freq,
        period_start + case freq
            when 'A' then interval 182 day
            when 'Q' then interval 45 day
            when 'M' then interval 14 day
            else interval 0 day end as mid_date
    from periods
)
select m.group_id, m.member_id, p.period_start, p.freq
from {{ ref('memberships') }} m
join {{ ref('entities') }} e on e.entity_id = m.member_id and e.type = 'country'
join mid p
    on (m.valid_from is null or m.valid_from <= p.mid_date)
    and (m.valid_to is null or m.valid_to >= p.mid_date)
