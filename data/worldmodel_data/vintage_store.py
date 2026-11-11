"""The raw vintage store.

Every fetch keeps the source files unchanged under
    raw/<source>/<vintage>/<fetched-at>/
and writes the normalised long table for that vintage to
    vintages/<source>/<vintage>/observations.parquet
with a manifest.json beside it. Nothing here is ever overwritten in place:
a re-fetch of the same release with different content becomes a new vintage
(`<release>+<date>`), so revisions stay visible.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from worldmodel_data.config import Paths

STAGED_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "scheme": "VARCHAR",
    "source_code": "VARCHAR",
    "indicator_id": "VARCHAR",
    "period_start": "DATE",
    "freq": "VARCHAR",
    "breakdown": "VARCHAR",
    "variant": "VARCHAR",
    "value": "DOUBLE",
    "status": "VARCHAR",
}

# texts.parquet beside a vintage, for sources with text as well as numbers (Factbook
# fields, Wikidata facts). edition is the year of the edition the text is from, if any;
# field_key a name that stays the same across editions; position orders the fields.
TEXT_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "scheme": "VARCHAR",
    "source_code": "VARCHAR",
    "edition": "INTEGER",
    "section": "VARCHAR",
    "field": "VARCHAR",
    "field_key": "VARCHAR",
    "content": "VARCHAR",
    "position": "BIGINT",
}

# events.parquet beside a vintage, for sources of dated events (elections, coups,
# conflicts, disasters...). event_key is the source's own id for the event, unique
# within the source; dates are DATEs, with precision saying how exact they are.
EVENT_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "scheme": "VARCHAR",
    "source_code": "VARCHAR",
    "event_key": "VARCHAR",
    "kind": "VARCHAR",
    "subkind": "VARCHAR",
    "title": "VARCHAR",
    "start_date": "DATE",
    "end_date": "DATE",
    "precision": "VARCHAR",
    "size": "DOUBLE",
    "size_unit": "VARCHAR",
    "deaths": "DOUBLE",
    "affected": "DOUBLE",
    "damage_usd": "DOUBLE",
    "place": "VARCHAR",
    "url": "VARCHAR",
    "detail": "VARCHAR",
    "color": "VARCHAR",
}


# layers.parquet beside a vintage, for sources of map overlays (plate boundaries, faults,
# volcanoes, earthquakes): one row per layer, its features as one GeoJSON FeatureCollection.
LAYER_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "layer_id": "VARCHAR",
    "name": "VARCHAR",
    "description": "VARCHAR",
    "kind": "VARCHAR",
    "feature_count": "INTEGER",
    "geojson": "VARCHAR",
}


# cities.parquet beside a vintage, for a source of places (GeoNames): one row per city.
# city_key is the source's own id; synonyms are other names (lower case, "|" between).
CITY_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "city_key": "VARCHAR",
    "name": "VARCHAR",
    "ascii_name": "VARCHAR",
    "synonyms": "VARCHAR",
    "country_id": "VARCHAR",
    "admin1": "VARCHAR",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
    "population": "DOUBLE",
    "feature_code": "VARCHAR",
    "timezone": "VARCHAR",
    "elevation": "DOUBLE",
}

# places.parquet beside a vintage: things with a location in a country (metro and rail
# systems, universities, companies' head offices). facts is a JSON object of the kind's
# figures (length_km, stations, students, revenue with currency and year...); the build
# matches each place to its nearest city and works out revenue in US dollars.
PLACE_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "place_key": "VARCHAR",
    "kind": "VARCHAR",
    "subkind": "VARCHAR",
    "name": "VARCHAR",
    "country_id": "VARCHAR",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
    "city_name": "VARCHAR",
    "founded": "DATE",
    "url": "VARCHAR",
    "facts": "VARCHAR",
}

# The long view (Long history page): tables whose years can be before AD 1, so years are
# whole numbers (negative for BC), not dates. One parquet file per table beside a vintage.
#   long_series:    figures over centuries (population since 10,000 BC, Maddison GDP per
#                   person...), by the source's own country code (ISO3, or a name for regions);
#   polities:       states and empires with their borders over time (Seshat's Cliopatria),
#                   one row per stretch of years with unchanged borders; geojson is the
#                   simplified geometry; composite rows (names in brackets) join their parts;
#   history_events: wars, battles, epidemics, famines, treaties (Wikidata) and earthquakes,
#                   eruptions and tsunamis (NOAA), with a place where known.
HISTORY_COLUMNS = {
    "long_series": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "source_code": "VARCHAR", "scheme": "VARCHAR",
        "series_id": "VARCHAR", "year": "INTEGER", "value": "DOUBLE",
    },
    "polities": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "polity_key": "VARCHAR", "name": "VARCHAR",
        "from_year": "INTEGER", "to_year": "INTEGER", "area_km2": "DOUBLE", "composite": "BOOLEAN",
        "components": "VARCHAR", "member_of": "VARCHAR", "wikipedia": "VARCHAR", "wikidata": "VARCHAR",
        "lat": "DOUBLE", "lon": "DOUBLE", "west": "DOUBLE", "south": "DOUBLE", "east": "DOUBLE", "north": "DOUBLE",
        "geojson": "VARCHAR",
    },
    "history_events": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "event_key": "VARCHAR", "kind": "VARCHAR", "title": "VARCHAR",
        "year": "INTEGER", "end_year": "INTEGER", "month": "INTEGER", "day": "INTEGER", "lat": "DOUBLE", "lon": "DOUBLE",
        "place": "VARCHAR", "country_code": "VARCHAR", "deaths": "DOUBLE", "size": "DOUBLE", "size_unit": "VARCHAR",
        "links": "INTEGER", "url": "VARCHAR",
    },
    # Pollution and nature (connectors/nature.py)
    "zone_grids": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "period": "VARCHAR", "scenario": "VARCHAR", "width": "INTEGER",
        "height": "INTEGER", "grid": "BLOB",
    },
    "protected_areas": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "wdpa_id": "VARCHAR", "name": "VARCHAR", "designation": "VARCHAR",
        "iucn_cat": "VARCHAR", "country_code": "VARCHAR", "marine": "VARCHAR", "area_km2": "DOUBLE", "year": "INTEGER",
        "lat": "DOUBLE", "lon": "DOUBLE", "west": "DOUBLE", "south": "DOUBLE", "east": "DOUBLE", "north": "DOUBLE",
        "geojson": "VARCHAR",
    },
    "species_status": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "country_code": "VARCHAR", "scientific_name": "VARCHAR",
        "category": "VARCHAR", "year": "INTEGER", "url": "VARCHAR",
    },
    "pest_presence": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "pest_code": "VARCHAR", "pest_name": "VARCHAR",
        "country_code": "VARCHAR", "state": "VARCHAR", "status": "VARCHAR", "present": "BOOLEAN",
    },
    # Transport and networks (connectors/transport.py, networks.py)
    "geo_features": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "layer_id": "VARCHAR", "feature_id": "VARCHAR", "name": "VARCHAR",
        "rank": "INTEGER", "props": "VARCHAR", "countries": "VARCHAR", "west": "DOUBLE", "south": "DOUBLE",
        "east": "DOUBLE", "north": "DOUBLE", "geojson": "VARCHAR",
    },
    "port_traffic": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "port_id": "VARCHAR", "country_code": "VARCHAR", "year": "INTEGER",
        "month": "INTEGER", "calls": "DOUBLE", "import_t": "DOUBLE", "export_t": "DOUBLE",
    },
    "chokepoint_traffic": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "chokepoint_id": "VARCHAR", "name": "VARCHAR", "day": "DATE",
        "transits": "DOUBLE", "tankers": "DOUBLE", "container": "DOUBLE", "dry_bulk": "DOUBLE", "cargo": "DOUBLE",
        "capacity": "DOUBLE",
    },
    "airport_traffic": {
        "source_id": "VARCHAR", "vintage": "VARCHAR", "airport": "VARCHAR", "name": "VARCHAR", "country_code": "VARCHAR",
        "year": "INTEGER", "passengers": "DOUBLE", "freight_t": "DOUBLE",
    },
}

# city_values.parquet beside a vintage: figures about cities as the source names them
# (with its country's entity id and, where known, location). The build matches each to a city.
CITY_VALUE_COLUMNS = {
    "source_id": "VARCHAR",
    "vintage": "VARCHAR",
    "city_name": "VARCHAR",
    "country_id": "VARCHAR",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
    "indicator_id": "VARCHAR",
    "period_start": "DATE",
    "status": "VARCHAR",
    "value": "DOUBLE",
}


@dataclass
class Manifest:
    source_id: str
    vintage: str
    release: str
    retrieved_at: str
    origin: str  # URL list or "file:<path>"
    sha256: str  # over all raw files, sorted by name
    raw_dir: str
    row_count: int = 0
    files: list[dict] = field(default_factory=list)
    stage_version: int = 1  # the connector's stage_version when the staged files were written
    fetch_version: int = 1  # the connector's fetch_version when the raw files were downloaded
    text_count: int = 0     # rows in texts.parquet, if any
    event_count: int = 0    # rows in events.parquet, if any
    layer_count: int = 0    # map layers in layers.parquet, if any
    city_count: int = 0     # rows in cities.parquet, if any
    city_value_count: int = 0  # rows in city_values.parquet, if any
    place_count: int = 0    # rows in places.parquet, if any
    history_count: int = 0  # rows in the long-view tables (HISTORY_COLUMNS), if any

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        data = json.loads(path.read_text())
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def sha256_files(files: list[Path]) -> tuple[str, list[dict]]:
    total = hashlib.sha256()
    info = []
    for f in sorted(files, key=lambda p: p.name):
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
                total.update(chunk)
        info.append({"name": f.name, "bytes": f.stat().st_size, "sha256": h.hexdigest()})
    return total.hexdigest(), info


class VintageStore:
    def __init__(self, paths: Paths):
        self.paths = paths

    def manifests(self, source_id: str | None = None) -> list[Manifest]:
        root = self.paths.vintages
        pattern = f"{source_id}/*/manifest.json" if source_id else "*/*/manifest.json"
        return sorted((Manifest.read(p) for p in root.glob(pattern)), key=lambda m: (m.source_id, m.retrieved_at))

    def latest(self, source_id: str) -> Manifest | None:
        ms = self.manifests(source_id)
        return ms[-1] if ms else None

    def find_by_hash(self, source_id: str, sha: str) -> Manifest | None:
        return next((m for m in self.manifests(source_id) if m.sha256 == sha), None)

    def new_raw_dir(self, source_id: str, release: str, fetched_at: datetime) -> Path:
        d = self.paths.raw / source_id / release / fetched_at.strftime("%Y%m%dT%H%M%SZ")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def vintage_name(self, source_id: str, release: str, fetched_at: datetime) -> str:
        """`release`, or `release+YYYYMMDD` if that release is already stored with other content."""
        taken = {m.vintage for m in self.manifests(source_id)}
        if release not in taken:
            return release
        name = f"{release}+{fetched_at:%Y%m%d}"
        n = 2
        while name in taken:
            name = f"{release}+{fetched_at:%Y%m%d}.{n}"
            n += 1
        return name

    def vintage_dir(self, source_id: str, vintage: str) -> Path:
        return self.paths.vintages / source_id / vintage.replace("/", "_")

    def discard_raw(self, raw_dir: Path) -> None:
        shutil.rmtree(raw_dir, ignore_errors=True)
