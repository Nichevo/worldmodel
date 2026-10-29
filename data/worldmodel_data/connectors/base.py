"""Connector base class: fetch, keep the raw files, stage one vintage."""

from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_contract import catalogue
from worldmodel_data.vintage_store import STAGED_COLUMNS, Manifest, VintageStore, now_utc, sha256_files

log = logging.getLogger(__name__)

USER_AGENT = "worldmodel-data/0.1 (personal research tool; https://github.com/Nichevo/worldmodel)"


class ConnectorError(RuntimeError):
    pass


class Connector(ABC):
    source_id: str = ""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True)
        return self._client

    # -- to implement ------------------------------------------------------------
    @abstractmethod
    def default_release(self, fetched_at: datetime) -> str:
        """The release a fetch made now would get, for example "2024" or "2025-10"."""

    @abstractmethod
    def download(self, raw_dir: Path, release: str) -> str:
        """Download the source files into raw_dir. Returns a description of where from."""

    @abstractmethod
    def release_from_files(self, files: list[Path]) -> str | None:
        """Work out the release from local file names, if possible."""

    @abstractmethod
    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        """Return a SQL query over the raw files producing STAGED_COLUMNS."""

    # -- shared ------------------------------------------------------------------
    def series_map(self) -> dict[str, tuple[str, float]]:
        """source series code -> (indicator_id, scale) for this source, from the catalogue."""
        out = {}
        for ind in catalogue.indicators().values():
            for s in ind.sources:
                if s.source_id == self.source_id:
                    out[s.series] = (ind.id, s.scale)
        return out

    def known_codes(self, scheme: str) -> set[str]:
        return {c["code"] for c in catalogue.entity_codes() if c["scheme"] == scheme}

    def ingest(self, store: VintageStore, from_path: Path | None = None, release: str | None = None) -> tuple[Manifest, bool]:
        """Fetch (or copy from from_path), store and stage one vintage.

        Returns (manifest, is_new). If the content matches a stored vintage
        exactly, nothing is written and that vintage is returned.
        """
        fetched_at = now_utc()
        staging = store.paths.raw / self.source_id / "_incoming" / fetched_at.strftime("%Y%m%dT%H%M%SZ")
        staging.mkdir(parents=True, exist_ok=True)
        try:
            if from_path:
                origin = self._copy_local(from_path, staging)
                release = release or self.release_from_files(list(staging.iterdir())) or self.default_release(fetched_at)
            else:
                release = release or self.default_release(fetched_at)
                origin = self.download(staging, release)
            files = [p for p in staging.iterdir() if p.is_file()]
            if not files:
                raise ConnectorError(f"{self.source_id}: no files fetched")
            sha, file_info = sha256_files(files)
            existing = store.find_by_hash(self.source_id, sha)
            if existing:
                log.info("%s: content unchanged since vintage %s", self.source_id, existing.vintage)
                shutil.rmtree(staging, ignore_errors=True)
                return existing, False

            vintage = store.vintage_name(self.source_id, release, fetched_at)
            raw_dir = store.new_raw_dir(self.source_id, vintage, fetched_at)
            for f in files:
                shutil.move(str(f), raw_dir / f.name)
            shutil.rmtree(staging, ignore_errors=True)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        out_dir = store.vintage_dir(self.source_id, vintage)
        out_dir.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        try:
            query = self.stage(con, raw_dir, release, vintage)
            cols = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in STAGED_COLUMNS.items())
            con.execute(f"CREATE TABLE staged AS SELECT {cols} FROM ({query}) WHERE value IS NOT NULL")
            rows = con.execute("SELECT count(*) FROM staged").fetchone()[0]
            if rows == 0:
                raise ConnectorError(f"{self.source_id}: staged 0 rows from {raw_dir}")
            parquet = out_dir / "observations.parquet"
            con.execute(f"COPY staged TO '{parquet.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        finally:
            con.close()

        manifest = Manifest(
            source_id=self.source_id, vintage=vintage, release=release, retrieved_at=fetched_at.isoformat(),
            origin=origin, sha256=sha, raw_dir=str(raw_dir.relative_to(store.paths.home)), row_count=rows,
            files=file_info,
        )
        manifest.write(out_dir / "manifest.json")
        log.info("%s: stored vintage %s (%s rows)", self.source_id, vintage, rows)
        return manifest, True

    def _copy_local(self, from_path: Path, dest: Path) -> str:
        from_path = Path(from_path)
        files = [from_path] if from_path.is_file() else sorted(p for p in from_path.iterdir() if p.is_file())
        for f in files:
            shutil.copy2(f, dest / f.name)
        return f"file:{from_path.resolve()}"

    def get(self, url: str, dest: Path) -> None:
        log.info("GET %s", url)
        with self.client.stream("GET", url) as r:
            if r.status_code != 200:
                raise ConnectorError(f"GET {url} returned HTTP {r.status_code}")
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"
