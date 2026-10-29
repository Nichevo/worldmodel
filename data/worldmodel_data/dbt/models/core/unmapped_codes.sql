-- Source codes with no entity in the crosswalk, for the build report.
select source_id, scheme, source_code, count(*) as rows, min(vintage) as first_vintage
from {{ ref('int_staged') }}
where entity_id is null
group by all
