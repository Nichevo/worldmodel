{{ config(severity='warn') }}
-- Check: our continent totals, built from member countries, against the UN's
-- published continent totals. Differences point to membership mismatches
-- between the UN M49 regions in the crosswalk and the regions WPP uses.
select a.entity_id, a.period_start, a.value as ours, p.value as un, abs(a.value - p.value) / p.value as gap
from {{ ref('int_aggregates') }} a
join {{ ref('int_latest') }} p
    on p.entity_id = a.entity_id and p.indicator_id = a.indicator_id and p.period_start = a.period_start
    and p.source_id = a.source_id and p.breakdown = a.breakdown and p.variant = a.variant
where a.indicator_id = 'pop_total' and a.source_id = 'un_wpp' and a.entity_id <> 'world'
    and abs(a.value - p.value) / p.value > 0.005
