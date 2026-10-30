"""Saved workspace layouts: the one thing the API writes, and never into the warehouse.

They live in a small JSON file in a user folder beside the data, so they survive
app updates and new warehouse builds:
  WORLDMODEL_USER_DIR, else WORLDMODEL_HOME/user, else ./var/user.
A layout is a name and the map page's URL query, which already holds the whole workspace.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_LAYOUTS = 200
_lock = threading.Lock()


def user_dir() -> Path:
    if os.environ.get("WORLDMODEL_USER_DIR"):
        return Path(os.environ["WORLDMODEL_USER_DIR"]).expanduser()
    home = os.environ.get("WORLDMODEL_HOME")
    return (Path(home).expanduser() if home else Path.cwd() / "var") / "user"


def _path() -> Path:
    return user_dir() / "layouts.json"


def _read() -> dict[str, dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write(data: dict[str, dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic, so a crash never leaves half a file


def all_layouts() -> list[dict]:
    return sorted(({"name": k, **v} for k, v in _read().items()), key=lambda r: r["name"].lower())


def save(name: str, query: str) -> dict:
    with _lock:
        data = _read()
        if name not in data and len(data) >= MAX_LAYOUTS:
            raise ValueError(f"at most {MAX_LAYOUTS} saved layouts")
        data[name] = {"query": query, "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _write(data)
        return {"name": name, **data[name]}


def delete(name: str) -> bool:
    with _lock:
        data = _read()
        if name not in data:
            return False
        del data[name]
        _write(data)
        return True
