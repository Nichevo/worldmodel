-- Map overlays (plate boundaries, active faults, volcanoes, earthquakes) from the
-- latest vintage of each source that has some: one row per layer, its features as
-- one GeoJSON FeatureCollection.
select layer_id, name, description, kind, source_id, vintage, feature_count, geojson
from {{ source('src', 'raw_layers') }}
