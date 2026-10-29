-- Gate: the UN's own world population total must match the sum of the
-- countries we loaded to within 1 percent in every year. A gap means
-- countries are missing from the crosswalk or loaded twice.
with countries as (
    select l.period_start, sum(l.value) as total
    from {{ ref('int_latest') }} l
    join {{ ref('entities') }} e on e.entity_id = l.entity_id and e.type = 'country'
    where l.indicator_id = 'pop_total' and l.source_id = 'un_wpp' and l.breakdown = '' and l.variant = 'central'
    group by all
),
world as (
    select period_start, value as total
    from {{ ref('int_latest') }}
    where entity_id = 'world' and indicator_id = 'pop_total' and source_id = 'un_wpp'
        and breakdown = '' and variant = 'central'
)
select w.period_start, w.total as world_total, c.total as countries_total,
    abs(c.total - w.total) / w.total as gap
from world w
left join countries c using (period_start)
where c.total is null or abs(c.total - w.total) / w.total > 0.01
