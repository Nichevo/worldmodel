"""Reuse a build step's result when what it reads has not changed since the last build.

Every build starts from an empty warehouse, so without this the slow steps (merging the
hospital lists, placing every map dot in a country, port pressure) were worked out again on
each refresh even when their sources had brought nothing new. A step names the queries it
reads; the cache key is a hash of those queries' rows (DuckDB hashes them in a fraction of a
second, millions of rows included), the code of the pipeline and the DuckDB version. When the
key matches the one saved last time, the step loads its saved result (Parquet files under
warehouse/builds/step_cache) instead of working it out.

Settings > Looking after the data: "Reuse unchanged build steps" switches this off
(build_reuse); every step is then worked out again on each build.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from functools import lru_cache
from importlib import resources
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

CODE_SUFFIXES = {".py", ".sql", ".yml", ".yaml", ".csv", ".json"}


@lru_cache(maxsize=1)
def code_hash() -> str:
    """A hash of the pipeline's and the contract's code and lists, so a code update starts afresh."""
    h = hashlib.sha256(duckdb.__version__.encode())
    for pkg in ("worldmodel_data", "worldmodel_contract"):
        root = Path(str(resources.files(pkg)))
        for f in sorted(root.rglob("*")):
            if f.suffix in CODE_SUFFIXES and f.is_file() and not {"__pycache__", "target", "logs"} & set(f.relative_to(root).parts):
                h.update(f.relative_to(root).as_posix().encode())
                h.update(f.read_bytes())
    return h.hexdigest()


def rows_hash(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> str:
    """Rows and a content hash of a query's result, whatever the order of its rows."""
    try:
        n, s = con.execute(f"SELECT count(*), sum(hash(q)) FROM ({sql}) q", params or []).fetchone()
    except duckdb.Error as exc:  # a table missing from this build reads as "nothing"
        return f"missing:{type(exc).__name__}"
    return f"{n}:{s}"


def key(*parts) -> str:
    h = hashlib.sha256(code_hash().encode())
    for p in parts:
        h.update(repr(p).encode())
        h.update(b"\x00")
    return h.hexdigest()[:24]


class StepCache:
    """Saved results of build steps, by step name and key. `on=False` never hits and saves nothing."""

    def __init__(self, folder: Path | None, on: bool = True):
        self.folder = folder
        self.on = bool(on and folder)
        self.reused: list[str] = []   # steps (or parts of them) loaded from the cache in this build
        self.worked: list[str] = []   # steps worked out again

    def _dir(self, step: str) -> Path:
        return self.folder / step  # type: ignore[operator]

    def hit(self, step: str, k: str, names: list[str]) -> Path | None:
        """The folder holding `names`.parquet for this key, or None."""
        if not self.on:
            return None
        d = self._dir(step) / k
        if all((d / f"{n}.parquet").is_file() for n in names) and (d / "done").is_file():
            return d
        return None

    def load(self, con: duckdb.DuckDBPyConnection, step: str, k: str, tables: dict[str, str],
             first: list[tuple[str, list]] | None = None) -> bool:
        """Insert the saved rows into each table ({name: table}), after running `first` (deletes of
        what the saved rows replace), all in one transaction; True when it did. On a damaged
        file nothing is changed, the saved result is removed and False is returned."""
        d = self.hit(step, k, list(tables))
        if d is None:
            return False
        con.execute("BEGIN TRANSACTION")
        try:
            for sql, params in first or []:
                con.execute(sql, params)
            for name, table in tables.items():
                con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM read_parquet(?)", [(d / f"{name}.parquet").as_posix()])
        except duckdb.Error as exc:  # a damaged or outdated file: work the step out instead
            con.execute("ROLLBACK")
            log.warning("%s: saved result could not be read (%s); working it out again", step, exc)
            shutil.rmtree(d, ignore_errors=True)
            return False
        con.execute("COMMIT")
        self.reused.append(step)
        return True

    def save(self, con: duckdb.DuckDBPyConnection, step: str, k: str, queries: dict[str, str],
             params: dict[str, list] | None = None, keep_others: bool = False) -> None:
        """Save each query's rows as <name>.parquet under the key; other keys of the step are removed
        (unless keep_others, for steps saved in parts that clean up with prune())."""
        if not self.on:
            return
        base = self._dir(step)
        d, tmp = base / k, base / f"{k}.tmp"
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            for name, sql in queries.items():
                con.execute(f"COPY ({sql}) TO '{(tmp / f'{name}.parquet').as_posix()}' (FORMAT parquet, COMPRESSION zstd)",
                            (params or {}).get(name) or [])
            (tmp / "done").write_text(k)
            shutil.rmtree(d, ignore_errors=True)
            os.replace(tmp, d)
        except (OSError, duckdb.Error) as exc:  # a cache that cannot be written only costs time next build
            log.warning("%s: could not save its result for the next build (%s)", step, exc)
            shutil.rmtree(tmp, ignore_errors=True)
            return
        if not keep_others:
            self.prune(step, {k})

    def prune(self, step: str, keep: set[str]) -> None:
        """Remove the step's saved results other than `keep`."""
        if not self.on or not self._dir(step).is_dir():
            return
        for old in self._dir(step).iterdir():
            if old.name not in keep:
                shutil.rmtree(old, ignore_errors=True)

    def note_worked(self, step: str) -> None:
        self.worked.append(step)


OFF = StepCache(None, on=False)
