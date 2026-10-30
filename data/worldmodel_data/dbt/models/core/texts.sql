-- Text about countries (Factbook fields for every edition, Wikidata facts), with
-- source codes resolved through the crosswalk. A code maps if it was valid at any
-- time in the edition's year, so a state that began or ended that year still maps;
-- text with no edition (Wikidata) maps whatever the dates, as it can be about a
-- state that no longer exists.
select
    c.entity_id,
    t.source_id,
    t.vintage,
    t.edition,
    t.section,
    t.field,
    t.field_key,
    t.content,
    t.position
from {{ source('src', 'raw_texts') }} t
join {{ source('src', 'entity_codes') }} c
    on c.scheme = t.scheme
    and c.code = t.source_code
    and (t.edition is null or c.valid_from is null or make_date(t.edition, 12, 31) >= c.valid_from)
    and (t.edition is null or c.valid_to is null or make_date(t.edition, 1, 1) <= c.valid_to)
