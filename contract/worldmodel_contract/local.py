"""The local data folder, as both sides see it: user settings, disk use and the refresh log.

The pipeline writes raw downloads, vintages, builds and the refresh log; the app
writes only user files (settings, layouts, history) under user/. Both need the
same answers to "where is everything, how big is it, what are the limits", so
those live here rather than in either side.

    <home>/raw/        source files as downloaded         (pipeline)
    <home>/vintages/   normalised Parquet per vintage     (pipeline)
    <home>/warehouse/  builds, reports, refresh_log.jsonl (pipeline)
    <home>/media/      pictures and page caches           (pipeline, later)
    <home>/user/       settings, layouts, history         (app)

home is WORLDMODEL_HOME, else a WORLDMODEL_WAREHOUSE that names a folder, else ./var.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

GB = 1024 ** 3

# Every user setting with its default. The app's Settings page edits these; the
# pipeline reads the storage limits. Unknown keys in the file are ignored.
SETTINGS: dict[str, object] = {
    "click_mode": "popup",          # "popup": click opens a popup, shift-click selects; "select": click selects, double-click opens
    "hover_sparkline": True,         # small trend line in the map tooltip
    "popup_tabs": True,              # popups get a tab per indicator shown in the panels
    "side_panel": True,              # the pinboard down the right of the map page
    "disk_limit_gb": 100.0,          # the whole data folder
    "pictures_limit_gb": 2.0,        # media/ (pictures, cached pages)
    "numbeo_daily": 20,              # single-page Numbeo fetches per day, all countries together
    "wikipedia_countries_daily": 20,
    "wikipedia_cities_daily": 10,
    "history_paused": False,
    "history_retention_days": 0,     # 0 keeps history forever
}
CHOICES = {"click_mode": ("popup", "select")}
RANGES = {"disk_limit_gb": (1, 10_000), "pictures_limit_gb": (0.1, 1_000), "numbeo_daily": (0, 200),
          "wikipedia_countries_daily": (0, 500), "wikipedia_cities_daily": (0, 500),
          "history_retention_days": (0, 36_500)}
WARN_AT, CRITICAL_AT = 0.80, 0.95

# Disk categories, in display order. "pictures" is media/ and has its own limit.
CATEGORIES = [("raw", "Raw downloads"), ("vintages", "Vintages (Parquet)"), ("builds", "Warehouse builds"),
              ("reports", "Reports and logs"), ("pictures", "Pictures and pages"), ("user", "Your files"),
              ("other", "Other")]


def home() -> Path:
    if os.environ.get("WORLDMODEL_HOME"):
        return Path(os.environ["WORLDMODEL_HOME"]).expanduser()
    wh = os.environ.get("WORLDMODEL_WAREHOUSE", "")
    if wh and Path(wh).expanduser().is_dir():
        return Path(wh).expanduser()
    return Path.cwd() / "var"


def user_dir() -> Path:
    """WORLDMODEL_USER_DIR, else WORLDMODEL_HOME/user, else ./var/user (where layouts have always been)."""
    if os.environ.get("WORLDMODEL_USER_DIR"):
        return Path(os.environ["WORLDMODEL_USER_DIR"]).expanduser()
    h = os.environ.get("WORLDMODEL_HOME")
    return (Path(h).expanduser() if h else Path.cwd() / "var") / "user"


def refresh_log_path(root: Path | None = None) -> Path:
    return (root or home()) / "warehouse" / "refresh_log.jsonl"


# ----------------------------------------------------------------------------- settings
def clean_settings(data: dict, base: dict | None = None) -> dict:
    """The known settings from data, each checked and held to its range; the rest
    (and anything invalid) come from base, else the defaults."""
    out = dict(base or SETTINGS)
    for key, default in SETTINGS.items():
        if key not in data:
            continue
        v = data[key]
        if isinstance(default, bool):
            out[key] = bool(v)
        elif key in CHOICES:
            if v in CHOICES[key]:
                out[key] = v
        elif isinstance(default, (int, float)):
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            lo, hi = RANGES[key]
            num = min(hi, max(lo, num))
            out[key] = int(num) if isinstance(default, int) else round(num, 2)
    return out


def load_settings(root: Path | None = None) -> dict:
    """Settings from the user folder (or root/user when given and no WORLDMODEL_USER_DIR)."""
    base = root / "user" if root and not os.environ.get("WORLDMODEL_USER_DIR") else user_dir()
    path = base / "settings.json"
    try:
        return clean_settings(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(SETTINGS)


# ----------------------------------------------------------------------------- disk use
def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def disk_usage(root: Path | None = None) -> dict[str, int]:
    """Bytes per category, plus "total"."""
    root = root or home()
    out = {k: 0 for k, _ in CATEGORIES}
    if not root.exists():
        return {**out, "total": 0}
    for child in root.iterdir():
        name = child.name
        if name == "warehouse":
            for sub in child.iterdir():
                out["builds" if sub.name == "builds" else "reports"] += _size(sub)
        elif name == "media":
            out["pictures"] += _size(child)
        elif name in out:
            out[name] += _size(child)
        else:
            out["other"] += _size(child)
    out["total"] = sum(out.values())
    return out


def level(used: float, limit: float) -> str:
    share = used / limit if limit else 0
    return "full" if share >= 1 else "critical" if share >= CRITICAL_AT else "warn" if share >= WARN_AT else "ok"


def storage(root: Path | None = None) -> dict:
    """Disk use against the limits in settings, with a warning level for each limit."""
    s = load_settings(root)
    root = root or home()
    use = disk_usage(root)
    disk, pics = s["disk_limit_gb"] * GB, s["pictures_limit_gb"] * GB
    limits = [
        {"key": "disk", "label": "Whole data folder", "used": use["total"], "limit": disk, "level": level(use["total"], disk)},
        {"key": "pictures", "label": "Pictures and pages", "used": use["pictures"], "limit": pics,
         "level": level(use["pictures"], pics)},
    ]
    order = ["ok", "warn", "critical", "full"]
    worst = max((lim["level"] for lim in limits), key=order.index)
    return {"home": str(root), "categories": [{"key": k, "label": label, "bytes": use[k]} for k, label in CATEGORIES],
            "total": use["total"], "limits": limits, "level": worst, "warn_at": WARN_AT, "critical_at": CRITICAL_AT,
            "freeable": sum(f["bytes"] for f in freeable_raw(root))}


# ----------------------------------------------------------------------------- freeing space
STAMP = re.compile(r"^\d{8}T\d{6}Z$")


def freeable_raw(root: Path | None = None, keep: int = 2) -> list[dict]:
    """Old raw downloads that can go: per source, all but the newest `keep` fetches,
    never one the download cache still points at. Vintages (the normalised data
    every build reads) are never offered."""
    root = root or home()
    raw = root / "raw"
    if not raw.exists():
        return []
    out = []
    for source in sorted(p for p in raw.iterdir() if p.is_dir()):
        try:
            cached = {Path(e["file"]).parent.as_posix() for e in
                      json.loads((source / "http_cache.json").read_text(encoding="utf-8")).values() if e.get("file")}
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            cached = set()
        fetches = sorted((d for d in source.glob("*/*") if d.is_dir() and STAMP.match(d.name)
                          and d.parent.name != "_incoming"), key=lambda d: d.name)
        for d in fetches[:-keep] if keep else fetches:
            rel = d.relative_to(root).as_posix()
            if rel in cached:
                continue
            out.append({"source_id": source.name, "path": rel, "fetched": d.name, "bytes": _size(d)})
    return out


def free_raw(root: Path | None = None, keep: int = 2) -> dict:
    """Delete the old raw downloads listed by freeable_raw. Only ever on request."""
    root = root or home()
    removed, freed = [], 0
    for f in freeable_raw(root, keep):
        shutil.rmtree(root / f["path"], ignore_errors=True)
        if not (root / f["path"]).exists():
            removed.append(f["path"])
            freed += f["bytes"]
            try:  # drop the release folder too once it is empty
                (root / f["path"]).parent.rmdir()
            except OSError:
                pass
    return {"removed": removed, "freed_bytes": freed}


# ----------------------------------------------------------------------------- refresh log
def read_refresh_log(root: Path | None = None) -> list[dict]:
    """One record per refresh or build, oldest first. Builds from before the log
    existed are filled in from their reports and the stored vintages."""
    root = root or home()
    logged: list[dict] = []
    try:
        for line in refresh_log_path(root).read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    logged.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    known = {r.get("build_id") for r in logged}
    backfill = [r for r in _from_reports(root) if r["build_id"] not in known]
    return sorted(logged + backfill, key=lambda r: r.get("started_at") or "")


def _from_reports(root: Path) -> list[dict]:
    reports = root / "warehouse" / "reports"
    if not reports.exists():
        return []
    manifests = []
    for m in (root / "vintages").glob("*/*/manifest.json"):
        try:
            manifests.append(json.loads(m.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    out = []
    previous = ""
    for rep in sorted(reports.glob("*.md")):
        build_id = rep.stem
        try:
            started = datetime.strptime(build_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            text = rep.read_text(encoding="utf-8")
        except (ValueError, OSError):
            continue
        counts = {s: 0 for s in ("pass", "warn", "fail", "skip")}
        for line in text.splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 5 and cells[3] in counts:
                counts[cells[3]] += 1
        # Vintages fetched since the previous build were what this build brought in.
        new = [m for m in manifests if previous < m.get("retrieved_at", "") <= started]
        out.append({
            "build_id": build_id, "kind": "build", "started_at": started, "finished_at": None, "backfilled": True,
            "status": "failed" if "FAILED" in text.split("\n", 3)[2] else "ok", "checks": counts,
            "sources": [{"source_id": m["source_id"], "status": "new", "vintage": m["vintage"], "rows": m.get("row_count"),
                         "download_bytes": sum(f.get("bytes", 0) for f in m.get("files", []))} for m in new],
            "disk": None,
        })
        previous = started
    return out
