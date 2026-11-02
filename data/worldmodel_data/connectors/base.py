"""Connector base class: fetch, keep the raw files, stage one vintage."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_contract import catalogue
from worldmodel_data.vintage_store import (EVENT_COLUMNS, LAYER_COLUMNS, STAGED_COLUMNS, TEXT_COLUMNS, Manifest, VintageStore,
                                          now_utc, sha256_files)

log = logging.getLogger(__name__)

# Waits, in seconds, before each new try after HTTP 429 (too many requests) or 503.
RETRY_WAITS = (15, 45, 90)
USER_AGENT = "worldmodel-data/0.1 (personal research tool; https://github.com/Nichevo/worldmodel)"


class ConnectorError(RuntimeError):
    pass


# A connection that drops part way through a download.
CUT_OFF = (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout)


def tls_context():
    """Certificates checked against the computer's own trust store (Windows, macOS or
    Linux) where truststore is installed. The Windows store fetches an intermediate
    certificate a site forgets to send (as www.uky.edu does), which Python's bundled
    list cannot; elsewhere, or without truststore, the usual check (True)."""
    try:
        import ssl

        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 - fall back to httpx's own certificate bundle
        return True


def aia_context(host: str, port: int = 443):
    """A certificate check that also trusts the intermediate certificates a site should
    have sent but did not, fetched from the addresses its certificate names (Authority
    Information Access). The chain is still checked against the usual trusted roots."""
    import ssl

    import certifi

    pems: list[str] = []
    try:
        der = ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate((host, port), timeout=20))
        for _ in range(3):  # leaf -> intermediate -> (another intermediate)
            urls = re.findall(rb"(https?://[\x21-\x7e]+?\.(?:crt|cer|der))", der)
            if not urls:
                break
            r = httpx.get(urls[0].decode(), timeout=20, follow_redirects=True)
            if r.status_code != 200:
                break
            if r.content.startswith(b"-----BEGIN"):
                pem = r.text
                der = ssl.PEM_cert_to_DER_cert(pem)
            else:
                der = r.content
                pem = ssl.DER_cert_to_PEM_cert(der)
            pems.append(pem)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        log.info("could not fetch the missing certificate for %s: %s", host, exc)
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        ctx.load_default_certs()
    except OSError:
        pass
    if pems:
        ctx.load_verify_locations(cadata="\n".join(pems))
    return ctx


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
    pack: str | None = None            # a country pack ("nz"): fetched only while Settings switches it on (pack_<x>)
    manual = False                     # True: never downloaded; loaded with `fetch <source> --from FILE` only
    keeps_files = False                # True: files of the last vintage that this fetch did not bring again are
                                       # carried into the new one (files loaded by hand one at a time add up)
    fetch_every_days: int | None = None  # a refresh skips the source until its last fetch is this many days old
    # Raise when stage() changes in a way that alters stored output: vintages staged by an
    # older version are staged again from their raw files (by `upgrade`, or the next fetch).
    stage_version = 1
    # Raise when download() starts fetching more files: the next refresh fetches the source
    # even if its schedule says it is not due yet (or it is a frozen archive).
    fetch_version = 1

    def __init__(self, client: httpx.Client | None = None):
        self._client = client
        self._cache: HttpCache | None = None
        self.downloaded_bytes = 0  # over the network, this run; for the refresh log
        # Set by stage() for sources that describe themselves; saved beside the vintage.
        self.listed_indicators: list[dict] = []   # indicators.json: catalogue-shaped, see catalogue.source_indicators
        self.listed_memberships: list[dict] = []  # memberships.json: rows shaped like memberships.csv
        self.texts_query: str | None = None  # texts.parquet: a SQL query producing TEXT_COLUMNS, for sources with text
        self.events_query: str | None = None  # events.parquet: a SQL query producing EVENT_COLUMNS, for dated events
        # layers.parquet: map overlays, dicts with layer_id, name, description, kind (line or point), geojson
        self.layers: list[dict] = []

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True,
                                        verify=tls_context())
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
            if self.keeps_files:
                self._carry_files(store, staging)
                files = [p for p in staging.iterdir() if p.is_file()]
            sha, file_info = sha256_files(files)
            existing = store.find_by_hash(self.source_id, sha)
            if existing:
                log.info("%s: content unchanged since vintage %s", self.source_id, existing.vintage)
                shutil.rmtree(staging, ignore_errors=True)
                if self._cache:
                    self._cache.commit(store.paths.home / existing.raw_dir)
                if existing.stage_version < self.stage_version:
                    self.restage(store, existing)
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

        manifest = Manifest(
            source_id=self.source_id, vintage=vintage, release=release, retrieved_at=fetched_at.isoformat(),
            origin=origin, sha256=sha, raw_dir=str(raw_dir.relative_to(store.paths.home)), files=file_info,
            fetch_version=self.fetch_version,
        )
        self._stage_vintage(store, manifest)
        log.info("%s: stored vintage %s (%s rows)", self.source_id, vintage, manifest.row_count)
        return manifest, True

    def restage(self, store: VintageStore, manifest: Manifest) -> Manifest:
        """Stage a stored vintage again from its raw files, after a fix to stage()."""
        raw_dir = store.paths.home / manifest.raw_dir
        if not raw_dir.is_dir():
            raise ConnectorError(f"{self.source_id}: raw files for vintage {manifest.vintage} are gone ({raw_dir})")
        self._stage_vintage(store, manifest)
        log.info("%s: staged vintage %s again (%s rows)", self.source_id, manifest.vintage, manifest.row_count)
        return manifest

    def _stage_vintage(self, store: VintageStore, manifest: Manifest) -> None:
        """Write the staged parquet files and manifest for a vintage whose raw files are stored."""
        raw_dir, release, vintage = store.paths.home / manifest.raw_dir, manifest.release, manifest.vintage
        out_dir = store.vintage_dir(self.source_id, vintage)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("texts.parquet", "events.parquet", "layers.parquet"):
            (out_dir / name).unlink(missing_ok=True)
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
            events = 0
            if self.events_query:
                ecols = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in EVENT_COLUMNS.items())
                con.execute(f"CREATE TABLE staged_events AS SELECT {ecols} FROM ({self.events_query}) "
                            "WHERE start_date IS NOT NULL AND kind IS NOT NULL")
                events = con.execute("SELECT count(*) FROM staged_events").fetchone()[0]
                if events:
                    con.execute(f"COPY staged_events TO '{(out_dir / 'events.parquet').as_posix()}' "
                                "(FORMAT parquet, COMPRESSION zstd)")
            if self.layers:
                con.execute(f"CREATE TABLE staged_layers ({', '.join(f'{c} {t}' for c, t in LAYER_COLUMNS.items())})")
                con.executemany(f"INSERT INTO staged_layers VALUES ({', '.join('?' * len(LAYER_COLUMNS))})", [
                    (self.source_id, manifest.vintage, lay["layer_id"], lay["name"], lay.get("description", ""), lay["kind"],
                     lay.get("feature_count", 0), lay["geojson"]) for lay in self.layers])
                con.execute(f"COPY staged_layers TO '{(out_dir / 'layers.parquet').as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
            if rows == 0 and texts == 0 and events == 0 and not self.layers:
                raise ConnectorError(f"{self.source_id}: staged 0 rows from {raw_dir}")
            parquet = out_dir / "observations.parquet"
            con.execute(f"COPY staged TO '{parquet.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        finally:
            con.close()

        # What the source lists about itself: its own series as indicators, and group memberships.
        for name, data in (("indicators.json", self.listed_indicators), ("memberships.json", self.listed_memberships)):
            if data:
                (out_dir / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

        manifest.row_count, manifest.stage_version = rows, self.stage_version
        manifest.text_count, manifest.event_count, manifest.layer_count = texts, events, len(self.layers)
        manifest.write(out_dir / "manifest.json")

    def _carry_files(self, store: VintageStore, staging: Path) -> None:
        """Copy into `staging` the last vintage's files whose names it does not have."""
        last = store.latest(self.source_id)
        if not last:
            return
        have = {p.name.lower() for p in staging.iterdir()}
        old = store.paths.home / last.raw_dir
        for f in sorted(old.iterdir()) if old.is_dir() else []:
            if f.is_file() and f.name.lower() not in have and f.name != "http_cache.json":
                shutil.copy2(f, staging / f.name)

    def _copy_local(self, from_path: Path, dest: Path) -> str:
        from_path = Path(from_path)
        if from_path.is_file():
            files = [from_path]
        else:
            from worldmodel_data.manual import files as folder_files  # skips notes, part downloads, subfolders
            files = folder_files(from_path)
            if not files:
                raise FileNotFoundError(f"no files to load in {from_path}")
        for f in files:
            shutil.copy2(f, dest / f.name)
        return f"file:{from_path.as_posix()}"

    def get(self, url: str, dest: Path) -> None:
        """Download url to dest, unless the server says our stored copy is still current.
        A download cut off part way is resumed where it stopped (HTTP Range); a site that
        does not send its intermediate certificate gets it fetched from the address its
        own certificate names (AIA), then the download is tried again."""
        cache = self._cache
        headers = cache.conditional_headers(url) if cache else {}
        log.info("GET %s%s", url, " (if changed)" if headers else "")
        fixed_chain = False
        attempt = 0
        while True:
            try:
                with self.client.stream("GET", url, headers=headers) as r:
                    if r.status_code in (429, 503) and attempt < len(RETRY_WAITS):
                        wait = _retry_after(r.headers.get("retry-after"), RETRY_WAITS[attempt])
                        log.info("HTTP %s (server busy or asking us to slow down); trying again in %ss",
                                 r.status_code, wait)
                        attempt += 1
                        time.sleep(wait)
                        continue
                    try:
                        self._save(r, url, dest, cache)
                        return
                    except CUT_OFF as exc:
                        cut, first = exc, r.headers
                self._resume(url, dest, cut)
                if cache:
                    cache.note(url, dest.name, first.get("etag"), first.get("last-modified"))
                return
            except httpx.ConnectError as exc:
                if fixed_chain or "certificate verify failed" not in str(exc).lower():
                    raise
                fixed_chain = True
                self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True,
                                            verify=aia_context(httpx.URL(url).host))
                log.info("%s did not send its full certificate chain; fetched the missing certificate and trying again",
                         httpx.URL(url).host)

    def _resume(self, url: str, dest: Path, exc: Exception, tries: int = 6) -> None:
        """Carry on a download that was cut off, from the bytes already in dest."""
        total = None
        for i in range(tries):
            have = dest.stat().st_size if dest.exists() else 0
            if total is not None and have >= total:
                return
            log.warning("download of %s cut off after %.0f MB (%s); resuming", url, have / 1e6, exc)
            time.sleep(2 * (i + 1))
            try:
                with self.client.stream("GET", url, headers={"Range": f"bytes={have}-"}) as r:
                    if r.status_code == 416:  # nothing left to send
                        return
                    if r.status_code not in (200, 206):
                        raise ConnectorError(f"GET {url} returned HTTP {r.status_code} while resuming")
                    if r.status_code == 206:
                        m = re.search(r"/(\d+)$", r.headers.get("content-range", ""))
                        total = int(m.group(1)) if m else None
                    else:  # the server ignores ranges: start again
                        have, total = 0, int(r.headers["content-length"]) if r.headers.get("content-length") else None
                    with dest.open("ab" if r.status_code == 206 else "wb") as fh:
                        for chunk in r.iter_bytes():
                            fh.write(chunk)
                            self.downloaded_bytes += len(chunk)
                if total is None or dest.stat().st_size >= total:
                    return
            except CUT_OFF as e:
                exc = e
        raise ConnectorError(f"GET {url}: the download was cut off {tries + 1} times (last: {exc}); "
                             "the next refresh tries again")

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
