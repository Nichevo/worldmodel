-- Dated events per country from every source that has some (elections, leaders,
-- coups, conflicts, sporting events, disasters), with source codes resolved through
-- the crosswalk: a code maps if it was valid at any time during the event. Then the
-- curated notable episodes from the contract. Recessions and booms worked out from
-- the data are added after dbt runs (worldmodel_data.episodes), as source worldmodel.
select
    t.source_id || ':' || t.event_key as event_id,
    c.entity_id,
    t.source_id,
    t.vintage,
    t.kind,
    t.subkind,
    t.title,
    t.start_date,
    t.end_date,
    coalesce(t.precision, 'day') as precision,
    t.size,
    t.size_unit,
    t.deaths,
    t.affected,
    t.damage_usd,
    t.place,
    t.url,
    t.detail,
    t.color
from {{ source('src', 'raw_events') }} t
join {{ source('src', 'entity_codes') }} c
    on c.scheme = t.scheme
    and c.code = t.source_code
    and (c.valid_from is null or coalesce(t.end_date, t.start_date) >= c.valid_from)
    and (c.valid_to is null or t.start_date <= c.valid_to)
qualify row_number() over (partition by t.source_id, t.event_key, c.entity_id order by t.start_date) = 1
union all
select
    'notable:' || n.event_key as event_id,
    n.entity_id,
    'notable' as source_id,
    null as vintage,
    'notable' as kind,
    n.subkind,
    n.title,
    n.start_date,
    n.end_date,
    n.precision,
    n.size,
    n.size_unit,
    null as deaths,
    null as affected,
    null as damage_usd,
    null as place,
    n.url,
    n.detail,
    null as color
from {{ source('src', 'notable_episodes') }} n
