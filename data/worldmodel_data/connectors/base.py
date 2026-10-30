"""Connector base class: fetch, keep the raw files, stage one vintage."""

from __future__ import annotations

import json
import logging
import shutil
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_contract import catalogue
from worldmodel_data.vintage_store import STAGED_COLUMNS, TEXT_COLUMNS, Manifest, VintageStore, now_utc, sha256_files

log = logging.getLogger(__name__)

# Waits, in seconds, before each new try after HTTP 429 (too many requests) or 503.
RETRY_WAITS = (15, 45, 90)
USER_AGENT = "worldmodel-data/0.1 (personal research tool; https://github.com/Nichevo/worldmodel)"


class ConnectorError(RuntimeError):
    pass


class HttpCache:
    """Remembers each URL's ETag / Last-Modified and where its stored copy is, so a
    refresh can ask the server "changed since?" and reuse the stored file on a 304
    instead of downloading it again. Kept beside the raw files as http_cache.json."""

    def __init__(self, path: Path, home: Path):
        self.path, self.home = path, home
        try:
            self.entries: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.entries = {}
        self.pending: dict[str, dict] = {}  # url -> validators and file name from this fetch

    def stored_file(self, url: str) -> Path | None:
        e = self.entries.get(url)
        f = self.home / e["file"] if e and e.get("file") else None
        return f if f and f.is_file() else None

    def conditional_headers(self, url: str) -> dict[str, str]:
        e = self.entries.get(url, {})
        if not self.stored_file(url):
            return {}
        h = {}
        if e.get("etag"):
            h["If-None-Match"] = e["etag"]
        if e.get("last_modified"):
            h["If-Modified-Since"] = e["last_modified"]
        return h

    def note(self, url: str, name: str, etag: str | None, last_modified: str | None) -> None:
        if etag or last_modified:
            self.pending[url] = {"name": name, "etag": etag, "last_modified": last_modified}

    def commit(self, raw_dir: Path) -> None:
        """Point this fetch's URLs at their files in the vintage that now holds them."""
        for url, p in self.pending.items():
            f = raw_dir / p["name"]
            if f.is_file():
                self.entries[url] = {"etag": p["etag"], "last_modified": p["last_modified"],
                                     "file": f.relative_to(self.home).as_posix()}
        self.pending = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")
        tmp.replace(self.path)


class Connector(ABC):
    source_id: str = ""
    frozen = False                     # True: a refresh skips the source once it has a vintage (a closed archive)
    fetch_every_days: int | None = None  # a refresh skips the source until its last fetch is this many days old

    def __init__(self, client: httpx.Client | None = None):
        self._client = client
        self._cache: HttpCache | None = None
        self.downloaded_bytes = 0  # over the network, this run; for the refresh log
        # Set by stage() for sources that describe themselves; saved beside the vintage.
        self.listed_indicators: list[dict] = []   # indicators.json: catalogue-shaped, see catalogue.source_indicators
        self.listed_memberships: list[dict] = []  # memberships.json: rows shaped like memberships.csv
        self.texts_query: str | None = None  # texts.parquet: a SQL query producing TEXT_COLUMNS, for sources with text

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
                self._cache = HttpCache(store.paths.raw / self.source_id / "http_cache.json", store.paths.home)
                origin = self.download(staging, release)
            files = [p for p in staging.iterdir() if p.is_file()]
            if not files:
                raise ConnectorError(f"{self.source_id}: no files fetched")
            sha, file_info = sha256_files(files)
            existing = store.find_by_hash(self.source_id, sha)
            if existing:
                log.info("%s: content unchanged since vintage %s", self.source_id, existing.vintage)
                shutil.rmtree(staging, ignore_errors=True)
                if self._cache:
                    self._cache.commit(store.paths.home / existing.raw_dir)
                return existing, False

            vintage = store.vintage_name(self.source_id, release, fetched_at)
            raw_dir = store.new_raw_dir(self.source_id, vintage, fetched_at)
            for f in files:
                shutil.move(str(f), raw_dir / f.name)
            shutil.rmtree(staging, ignore_errors=True)
            if self._cache:
                self._cache.commit(raw_dir)
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
            texts = 0
            if self.texts_query:
                tcols = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in TEXT_COLUMNS.items())
                con.execute(f"CREATE TABLE staged_texts AS SELECT {tcols} FROM ({self.texts_query}) "
                            "WHERE content IS NOT NULL AND content <> ''")
                texts = con.execute("SELECT count(*) FROM staged_texts").fetchone()[0]
                if texts:
                    con.execute(f"COPY staged_texts TO '{(out_dir / 'texts.parquet').as_posix()}' "
                                "(FORMAT parquet, COMPRESSION zstd)")
            if rows == 0 and texts == 0:
                raise ConnectorError(f"{self.source_id}: staged 0 rows from {raw_dir}")
            parquet = out_dir / "observations.parquet"
            con.execute(f"COPY staged TO '{parquet.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        finally:
            con.close()

        # What the source lists about itself: its own series as indicators, and group memberships.
        for name, data in (("indicators.json", self.listed_indicators), ("memberships.json", self.listed_memberships)):
            if data:
                (out_dir / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

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
        return f"file:{from_path.as_posix()}"

    def get(self, url: str, dest: Path) -> None:
        """Download url to dest, unless the server says our stored copy is still current."""
        cache = self._cache
        headers = cache.conditional_headers(url) if cache else {}
        log.info("GET %s%s", url, " (if changed)" if headers else "")
        for attempt in range(len(RETRY_WAITS) + 1):
            with self.client.stream("GET", url, headers=headers) as r:
                if r.status_code in (429, 503) and attempt < len(RETRY_WAITS):
                    wait = _retry_after(r.headers.get("retry-after"), RETRY_WAITS[attempt])
                    log.info("HTTP %s (server busy or asking us to slow down); trying again in %ss",
                             r.status_code, wait)
                    time.sleep(wait)
                    continue
                self._save(r, url, dest, cache)
                return

    def _save(self, r: httpx.Response, url: str, dest: Path, cache: HttpCache | None) -> None:
        """Store a response, or reuse the stored copy on 304 Not Modified."""
        if r.status_code == 304 and cache and (stored := cache.stored_file(url)):
            log.info("not modified, reusing %s", stored)
            shutil.copy2(stored, dest)
            cache.note(url, dest.name, cache.entries[url].get("etag"), cache.entries[url].get("last_modified"))
            return
        if r.status_code != 200:
            raise ConnectorError(f"GET {url} returned HTTP {r.status_code}")
        with dest.open("wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
                self.downloaded_bytes += len(chunk)
        if cache:
            cache.note(url, dest.name, r.headers.get("etag"), r.headers.get("last-modified"))


def _retry_after(header: str | None, default: int) -> int:
    """Seconds to wait from a Retry-After header (seconds only), capped at two minutes."""
    try:
        return max(1, min(int(header), 120)) if header else default
    except ValueError:
        return default


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"
