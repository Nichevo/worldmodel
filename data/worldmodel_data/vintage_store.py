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
