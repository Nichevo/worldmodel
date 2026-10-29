-- Every value from every vintage, one long table. Values whose source code
-- has no entity in the crosswalk are left out here and listed in unmapped_codes.
select entity_id, indicator_id, period_start, freq, breakdown, variant, source_id, vintage, value, status
from {{ ref('int_staged') }}
where entity_id is not null
