"""Where the pipeline keeps its files, and the local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def raw(self) -> Path:
        """Source files exactly as downloaded, one folder per vintage and fetch."""
        return self.home / "raw"

    @property
    def vintages(self) -> Path:
        """Each vintage normalised to the long observation shape, as Parquet."""
        return self.home / "vintages"

    @property
    def warehouse(self) -> Path:
        return self.home / "warehouse"

    @property
    def builds(self) -> Path:
        return self.warehouse / "builds"

    @property
    def reports(self) -> Path:
        return self.warehouse / "reports"

    @property
    def current_pointer(self) -> Path:
        """Text file naming the live build; the app follows it."""
        return self.warehouse / "CURRENT"

    def current_build(self) -> Path | None:
        if not self.current_pointer.exists():
            return None
        path = self.builds / self.current_pointer.read_text().strip()
        return path if path.exists() else None


def load_env(env_file: Path | None = None) -> None:
    """Load .env from the given path, else from the working directory upwards."""
    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)


def paths(home: str | Path | None = None) -> Paths:
    root = Path(home or os.environ.get("WORLDMODEL_HOME") or Path.cwd() / "var").expanduser().resolve()
    return Paths(root)
