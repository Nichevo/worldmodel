-- Every value from every vintage, one long table. Values whose source code
-- has no entity in the crosswalk are left out here and listed in unmapped_codes.
-- Values of non-central variants that mean nothing (the UN's 95% interval for a
-- tiny population reaching a median age of 180 or an infinite sex ratio late in
-- the century) are left out too and listed in implausible_variant_values.
select s.entity_id, s.indicator_id, s.period_start, s.freq, s.breakdown, s.variant, s.source_id, s.vintage,
    s.value, s.status
from {{ ref('int_staged') }} s
left join {{ ref('indicators') }} i on i.indicator_id = s.indicator_id
where s.entity_id is not null
    and (s.variant = 'central' or i.indicator_id is null or {{ variant_value_plausible('s', 'i') }})
