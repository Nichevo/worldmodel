"""Find and open the warehouse, read-only, and follow it when the pipeline swaps in a new build.

WORLDMODEL_WAREHOUSE may name
  * a .duckdb file, or
  * a data folder (the pipeline's WORLDMODEL_HOME) holding warehouse/CURRENT.
If unset: the pipeline's data folder (WORLDMODEL_HOME, else ./var) when it has a live
build, else the sample shipped in app/sample/.
The app never writes to the warehouse.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

from worldmodel_contract import SCHEMA_VERSION, is_compatible

SAMPLE = Path(__file__).resolve().parents[2] / "sample" / "worldmodel-sample.duckdb"


class WarehouseError(RuntimeError):
    pass


@dataclass
class Opened:
    path: Path
    mtime: float
    con: duckdb.DuckDBPyConnection
    meta: dict[str, str]


def resolve(setting: str | None = None) -> Path:
    setting = setting if setting is not None else os.environ.get("WORLDMODEL_WAREHOUSE", "")
    home = os.environ.get("WORLDMODEL_HOME")
    candidates = [Path(setting).expanduser()] if setting else [Path(home).expanduser() if home else Path.cwd() / "var", SAMPLE]
    for c in candidates:
        if c.is_file():
            return c.resolve()
        pointer = c / "warehouse" / "CURRENT"
        if not pointer.exists():
            pointer = c / "CURRENT"
        if pointer.exists():
            target = pointer.parent / "builds" / pointer.read_text().strip()
            if target.exists():
                return target.resolve()
        if setting:
            raise WarehouseError(f"WORLDMODEL_WAREHOUSE={setting} is neither a .duckdb file nor a folder "
                                 f"with a live build (warehouse/CURRENT)")
    raise WarehouseError(f"no warehouse found: set WORLDMODEL_WAREHOUSE, run the pipeline, or restore {SAMPLE}")


class Warehouse:
    """One read-only connection, reopened when the live build changes."""

    def __init__(self, setting: str | None = None):
        self.setting = setting
        self._opened: Opened | None = None
        self._lock = threading.Lock()

    def _open(self, path: Path) -> Opened:
        con = duckdb.connect(str(path), read_only=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        except duckdb.Error as exc:
            con.close()
            raise WarehouseError(f"{path} has no meta table; is it a worldmodel warehouse? ({exc})")
        found = meta.get("schema_version", "0.0.0")
        if not is_compatible(found, SCHEMA_VERSION):
            con.close()
            raise WarehouseError(f"{path} has schema {found}; this app reads {SCHEMA_VERSION}. "
                                 "Rebuild the warehouse or update the app.")
        return Opened(path, path.stat().st_mtime, con, meta)

    def current(self) -> Opened:
        with self._lock:
            path = resolve(self.setting)
            o = self._opened
            if o is None or o.path != path or o.mtime != path.stat().st_mtime:
                if o is not None:
                    o.con.close()
                self._opened = o = self._open(path)
            return o

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A cursor per request: DuckDB connections are not safe to share across threads."""
        return self.current().con.cursor()

    @property
    def is_sample(self) -> bool:
        return self.current().path == SAMPLE.resolve()
