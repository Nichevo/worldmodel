"""Looking after the data folder: backups of the files only you can replace, and the
Windows scheduled task that runs refresh.bat on its own.

Backups hold <home>/manual (the files you saved by hand), <home>/user (settings,
predictions, highlights, layouts) and the .env file (your keys), zipped into one file
in the backup folder (by default worldmodel-backups beside the worldmodel folder).
Downloads, vintages and warehouse builds are left out: a refresh makes them again.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from worldmodel_contract import local

PREFIX = "worldmodel-backup-"
TASK = "worldmodel refresh"
DAYS = {"mon": "MON", "tue": "TUE", "wed": "WED", "thu": "THU", "fri": "FRI", "sat": "SAT", "sun": "SUN"}


def repo_dir() -> Path:
    """The worldmodel folder (where the .bat files and .env are)."""
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "refresh.bat").exists() or (p / ".env").exists():
            return p
    return Path.cwd()


def env_file() -> Path:
    for d in (Path.cwd(), *Path.cwd().parents):
        if (d / ".env").is_file():
            return d / ".env"
    return repo_dir() / ".env"


def backup_dir(settings: dict | None = None, root: Path | None = None) -> Path:
    s = settings or local.load_settings(root)
    if s.get("backup_folder"):
        return Path(str(s["backup_folder"])).expanduser()
    home = (root or local.home()).resolve()
    return home.parent.parent / "worldmodel-backups"


def backups(settings: dict | None = None, root: Path | None = None) -> list[dict]:
    d = backup_dir(settings, root)
    if not d.is_dir():
        return []
    out = [{"name": f.name, "bytes": f.stat().st_size,
            "at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes")}
           for f in d.glob(f"{PREFIX}*.zip")]
    return sorted(out, key=lambda r: r["name"], reverse=True)


def backup(root: Path | None = None, settings: dict | None = None, to: Path | None = None, say=print) -> Path:
    """Zip the manual folder, the user folder and .env into one file; keep the newest
    `backup_keep` backups the app made and remove older ones (only files named worldmodel-backup-*.zip)."""
    root = root or local.home()
    s = settings or local.load_settings(root)
    d = Path(to).expanduser() if to else backup_dir(s, root)
    d.mkdir(parents=True, exist_ok=True)
    big = int(float(s.get("backup_big_mb", 200)) * 1024 ** 2)
    target = d / f"{PREFIX}{datetime.now().strftime('%Y-%m-%d-%H%M')}.zip"
    user = Path(os.environ["WORLDMODEL_USER_DIR"]) if os.environ.get("WORLDMODEL_USER_DIR") else root / "user"
    skipped = []
    n = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, name in ((root / "manual", "manual"), (user, "user")):
            if not base.is_dir():
                continue
            for dirpath, _, files in os.walk(base):
                for f in files:
                    p = Path(dirpath) / f
                    try:
                        size = p.stat().st_size
                    except OSError:
                        continue
                    if big and size > big:
                        skipped.append(f"{p.relative_to(base.parent)} ({size / 1024 ** 2:.0f} MB)")
                        continue
                    z.write(p, f"{name}/{p.relative_to(base).as_posix()}")
                    n += 1
        env = env_file()
        if env.is_file():
            z.write(env, ".env")
            n += 1
    say(f"Backed up {n} files to {target} ({target.stat().st_size / 1024 ** 2:.1f} MB).")
    if skipped:
        say(f"Left out {len(skipped)} files over {big // 1024 ** 2} MB (the site can give them again): "
            + ", ".join(skipped[:5]) + (" ..." if len(skipped) > 5 else ""))
    keep = int(s.get("backup_keep", 10))
    old = sorted(d.glob(f"{PREFIX}*.zip"), key=lambda f: f.name, reverse=True)[keep:] if keep else []
    for f in old:
        try:
            f.unlink()
            say(f"Removed an old backup: {f.name}")
        except OSError:
            pass
    return target


def backed_up_today(settings: dict | None = None, root: Path | None = None) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    return any(b["name"].startswith(f"{PREFIX}{today}") for b in backups(settings, root))


# ----------------------------------------------------------------------------- the scheduled refresh
def schedule(on: bool, how_often: str = "weekly", day: str = "sun", at: str = "03:00") -> dict:
    """Make (or remove) the Windows scheduled task that runs refresh.bat. Returns {ok, message}."""
    if sys.platform != "win32":
        return {"ok": False, "message": "A scheduled refresh can only be set up on Windows; on this computer use cron or similar."}
    bat = repo_dir() / "refresh.bat"
    if on:
        if not bat.exists():
            return {"ok": False, "message": f"refresh.bat not found in {bat.parent}."}
        args = ["schtasks", "/Create", "/F", "/TN", TASK, "/TR", f'"{bat}"', "/ST", at]
        args += ["/SC", "DAILY"] if how_often == "daily" else ["/SC", "WEEKLY", "/D", DAYS.get(day, "SUN")]
    else:
        args = ["schtasks", "/Delete", "/F", "/TN", TASK]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "message": f"Windows did not take the task: {exc}"}
    out = (p.stdout or p.stderr or "").strip()
    if p.returncode != 0 and not (not on and "cannot find" in out.lower()):
        return {"ok": False, "message": f"Windows did not take the task: {out}"}
    when = "every night" if how_often == "daily" else f"every {day.title()}"
    return {"ok": True, "message": f"refresh.bat runs {when} at {at} while you are signed in to Windows." if on
            else "The scheduled refresh is off."}


def schedule_state() -> dict:
    """Whether Windows has the task, and when it runs next."""
    if sys.platform != "win32":
        return {"available": False, "exists": False}
    try:
        p = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/FO", "LIST"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {"available": True, "exists": False}
    if p.returncode != 0:
        return {"available": True, "exists": False}
    info = {}
    for line in p.stdout.splitlines():
        k, _, v = line.partition(":")
        info[k.strip()] = v.strip()
    return {"available": True, "exists": True, "next_run": info.get("Next Run Time"), "status": info.get("Status")}
