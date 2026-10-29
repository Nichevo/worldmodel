{# Fails on any row where the columns together are not unique. #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{# Fails on values outside the bounds the indicator catalogue sets. #}
{% test within_indicator_bounds(model) %}
select m.entity_id, m.indicator_id, m.period_start, m.source_id, m.vintage, m.value, i.bound_min, i.bound_max
from {{ model }} m
join {{ ref('indicators') }} i on i.indicator_id = m.indicator_id
where m.value < i.bound_min or m.value > i.bound_max or isnan(m.value) or isinf(m.value)
{% endtest %}

{# Fails on non-null values outside [low, high]. #}
{% test between(model, column_name, low, high) %}
select {{ column_name }} from {{ model }}
where {{ column_name }} is not null and ({{ column_name }} < {{ low }} or {{ column_name }} > {{ high }})
{% endtest %}
