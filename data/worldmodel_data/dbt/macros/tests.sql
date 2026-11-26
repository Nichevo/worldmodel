{# Fails on any row where the columns together are not unique. #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{# Fails on values outside the bounds the indicator catalogue sets. The bounds are
   for the source's main path; its other variants may reach further (see
   variant_value_plausible; the observations model leaves out the ones that do not). #}
{# With has_aggregates, a group total the build adds up itself (agg_method 'sum') is
   checked against the lower bound only: the upper bound is set for one country, and a
   region's total of a count such as heritage sites rightly goes past it. #}
{% test within_indicator_bounds(model, has_aggregates=false) %}
select m.entity_id, m.indicator_id, m.period_start, m.variant, m.source_id, m.vintage, m.value, i.bound_min, i.bound_max
from {{ model }} m
join {{ ref('indicators') }} i on i.indicator_id = m.indicator_id
where isnan(m.value) or isinf(m.value)
    or (m.variant = 'central' and (m.value < i.bound_min or (m.value > i.bound_max
        {% if has_aggregates %}and not (m.is_aggregate and i.agg_method = 'sum'){% endif %})))
    or (m.variant <> 'central' and not {{ variant_value_plausible('m', 'i') }})
{% endtest %}

{# Fails on non-null values outside [low, high]. #}
{% test between(model, column_name, low, high) %}
select {{ column_name }} from {{ model }}
where {{ column_name }} is not null and ({{ column_name }} < {{ low }} or {{ column_name }} > {{ high }})
{% endtest %}
