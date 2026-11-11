-- Every value from every vintage, one long table. Values whose source code
-- has no entity in the crosswalk are left out here and listed in unmapped_codes.
-- Values outside what the indicator can plausibly be are left out too and listed
-- in implausible_variant_values, so one source's slip (a decimal comma, a unit
-- change) is reported instead of stopping the whole build: central values outside
-- the catalogue's bounds, and variant values that mean nothing (the UN's 95%
-- interval for a tiny population reaching a median age of 180 or an infinite sex
-- ratio late in the century).
-- Sorted by indicator, country and date so a lookup reads only the blocks it needs
-- (about five times faster on a large warehouse than an unsorted table).
select s.entity_id, s.indicator_id, s.period_start, s.freq, s.breakdown, s.variant, s.source_id, s.vintage,
    s.value, s.status
from {{ ref('int_staged') }} s
left join {{ ref('indicators') }} i on i.indicator_id = s.indicator_id
where s.entity_id is not null
    and (i.indicator_id is null
         or (s.variant = 'central' and isfinite(s.value) and s.value between i.bound_min and i.bound_max)
         or (s.variant <> 'central' and {{ variant_value_plausible('s', 'i') }}))
order by s.indicator_id, s.entity_id, s.period_start
