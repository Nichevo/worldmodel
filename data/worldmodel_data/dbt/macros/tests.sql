{# Fails on any row where the columns together are not unique. #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{# Fails on values outside the bounds the indicator catalogue sets. The bounds are
   for the source's main path; its other variants (the UN's high and low variants
   and prediction intervals) may reach further, so they get room of the bounds' own
   width on either side, never below zero for an indicator that cannot be negative. #}
{% test within_indicator_bounds(model) %}
select m.entity_id, m.indicator_id, m.period_start, m.variant, m.source_id, m.vintage, m.value, i.bound_min, i.bound_max
from {{ model }} m
join {{ ref('indicators') }} i on i.indicator_id = m.indicator_id
where isnan(m.value) or isinf(m.value)
    or (m.variant = 'central' and (m.value < i.bound_min or m.value > i.bound_max))
    or (m.variant <> 'central' and (
        m.value < case when i.bound_min >= 0 then 0 else i.bound_min - (i.bound_max - i.bound_min) end
        or m.value > i.bound_max + (i.bound_max - i.bound_min)))
{% endtest %}

{# Fails on non-null values outside [low, high]. #}
{% test between(model, column_name, low, high) %}
select {{ column_name }} from {{ model }}
where {{ column_name }} is not null and ({{ column_name }} < {{ low }} or {{ column_name }} > {{ high }})
{% endtest %}
