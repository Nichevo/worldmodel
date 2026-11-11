"""Jobs the app starts on the data side: a refresh (all, some, or one source), filing and
loading the inbox, getting every due download, and a backup. Each runs as
`worldmodel-data ...` in the background, one at a time, with its console output kept in
warehouse/job.log for the Data status page. A refresh started from refresh.bat (or the
scheduled task) shows its progress here too, from warehouse/refresh_progress.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from worldmodel_contract import local, upkeep

KINDS = {"refresh": "Refresh", "inbox": "File and load the inbox", "get": "Get the due files", "backup": "Back up your files",
         "load": "Load saved files"}
_lock = threading.Lock()
_job: dict | None = None


def _log_path() -> Path:
    return local.home() / "warehouse" / "job.log"


def _progress() -> dict | None:
    try:
        return json.loads((local.home() / "warehouse" / "refresh_progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=10).stdout
            return str(pid) in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _command(kind: str, sources: list[str]) -> list[str]:
    base = [sys.executable, "-m", "worldmodel_data.cli"]
    if kind == "refresh":
        return base + ["refresh"] + (["--only", ",".join(sources)] if sources else [])
    if kind == "inbox":
        return base + ["inbox"]
    if kind == "get":
        return base + ["get", *sources]
    if kind == "backup":
        return base + ["backup"]
    if kind == "load":  # load then build: one source's folder, or every folder
        return base + ["load", *sources[:1], "--build"]
    raise ValueError(kind)


def start(kind: str, sources: list[str] | None = None) -> dict:
    """Start a job unless one (or a refresh from refresh.bat) is already running."""
    global _job
    if kind not in KINDS:
        raise ValueError(f"unknown job {kind}")
    with _lock:
        now = status()
        if now["running"]:
            raise RuntimeError(f"{now['label']} is already running; wait for it to finish.")
        log = _log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        f = log.open("w", encoding="utf-8")
        cmd = _command(kind, sources or [])
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(upkeep.repo_dir()), env=env,
                             creationflags=flags)
        _job = {"kind": kind, "sources": sources or [], "pid": p.pid, "proc": p, "file": f,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return status()


def status() -> dict:
    """The job running or last run: what, since when, its last console lines, how far a
    refresh has got and a guess at the time left (from how long each source took last time)."""
    global _job
    job = _job
    out: dict = {"running": False, "kind": None, "label": None, "lines": [], "exit_code": None}
    if job:
        code = job["proc"].poll()
        if code is not None and not job.get("closed"):
            job["file"].close()
            job["closed"] = True
            job["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out.update(running=code is None, kind=job["kind"], label=KINDS[job["kind"]], sources=job["sources"],
                   started_at=job["started_at"], finished_at=job.get("finished_at"), exit_code=code, by="app")
        try:
            out["lines"] = _log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        except OSError:
            pass
    prog = _progress()
    if prog and not prog.get("finished_at") and _alive(prog.get("pid")):
        if not out["running"]:
            out.update(running=True, kind="refresh", label="Refresh (started outside the app)", by="outside", lines=[],
                       started_at=prog.get("started_at"), exit_code=None)
        out["progress"] = {**prog, "seconds_left": _time_left(prog)}
    elif prog and job and job["kind"] == "refresh":
        out["progress"] = {**prog, "seconds_left": 0}
    return out


def _time_left(prog: dict) -> int | None:
    """Seconds the sources not yet done took in the last full refresh."""
    last: dict[str, float] = {}
    for run in local.read_refresh_log():
        if run.get("kind") == "refresh":
            for s in run.get("sources") or []:
                if s.get("seconds") is not None:
                    last[s["source_id"]] = float(s["seconds"])
    srcs = prog.get("sources") or []
    rest = srcs[int(prog.get("done") or 0):]
    if not last:
        return None
    return int(sum(last.get(s, 2.0) for s in rest) + 60)  # and about a minute to build
