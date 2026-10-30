{# True for a value of a non-central variant (the UN's high and low variants and
   prediction intervals) that is finite and inside the room it gets around the
   indicator's bounds: the bounds' own width on either side, never below zero for an
   indicator that cannot be negative. `m` is the observation, `i` its indicator. #}
{% macro variant_value_plausible(m, i) %}
(isfinite({{ m }}.value)
    and {{ m }}.value >= case when {{ i }}.bound_min >= 0 then 0 else {{ i }}.bound_min - ({{ i }}.bound_max - {{ i }}.bound_min) end
    and {{ m }}.value <= {{ i }}.bound_max + ({{ i }}.bound_max - {{ i }}.bound_min))
{% endmacro %}
