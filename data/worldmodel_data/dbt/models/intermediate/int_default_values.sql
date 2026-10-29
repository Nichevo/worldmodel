-- Latest values from each indicator's default (rank 1) source, used as
-- weights, ratio parts and the population for coverage.
select l.*
from {{ ref('int_latest') }} l
join {{ ref('indicator_sources') }} s
    on s.indicator_id = l.indicator_id and s.source_id = l.source_id and s.rank = 1
where l.breakdown = '' and l.variant = 'central'
