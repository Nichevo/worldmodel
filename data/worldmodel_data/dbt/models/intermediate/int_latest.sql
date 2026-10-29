-- The latest vintage of each source.
select o.*
from {{ ref('observations') }} o
join {{ ref('vintages') }} v on v.source_id = o.source_id and v.vintage = o.vintage and v.is_latest
