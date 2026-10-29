-- Catalogue table copied from the contract (see worldmodel_contract/catalogues).
select * from {{ source('src', 'entity_codes') }}
