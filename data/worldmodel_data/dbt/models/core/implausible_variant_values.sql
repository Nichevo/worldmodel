-- Non-central variant values left out of observations as meaningless, for the build report.
select s.source_id, s.indicator_id, s.entity_id, s.variant, count(*) as rows,
    min(year(s.period_start)) as first_year, max(year(s.period_start)) as last_year
from {{ ref('int_staged') }} s
join {{ ref('indicators') }} i on i.indicator_id = s.indicator_id
where s.entity_id is not null and s.variant <> 'central' and not {{ variant_value_plausible('s', 'i') }}
group by all
