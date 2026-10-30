-- Source codes with no entity in the crosswalk, for the build report.
select source_id, scheme, source_code, count(*) as rows, min(vintage) as first_vintage
from {{ ref('int_staged') }}
where entity_id is null
group by all
union all
select t.source_id, t.scheme, t.source_code, count(*) as rows, min(t.vintage) as first_vintage
from {{ source('src', 'raw_texts') }} t
where not exists (select 1 from {{ source('src', 'entity_codes') }} c where c.scheme = t.scheme and c.code = t.source_code)
group by all
