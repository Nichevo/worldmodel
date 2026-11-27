"""Saved data that is about to reach the age (or count) its Settings keep it for.

Several stores delete their oldest part as they go: saved plane, ship and train positions
(`planes_keep_days`, `ships_keep_days`, `trains_keep_days`), cargo-ship schedules (`schedules_keep_days`), news
(`news_keep_days`), the private History log (`history_retention_days`) and backups
(`backup_keep`). Each is looked at here: how old its oldest part is and when that part
first goes. Anything within `expiry_warn_days` of its first deletion, or already being
deleted, is listed for the banner, so the setting can be reviewed and extended in time.

Once a store is full it deletes a day every day, so a warning would never end. "Keep as is"
records the setting's value (user/expiry_ok.json); the warning stays away until that
setting changes and the new limit comes close in its turn.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from worldmodel_contract import local
from worldmodel_contract import upkeep as backups_mod

OK_FILE = "expiry_ok.json"
_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}  # path -> (mtime, oldest) for the big JSON files


def _ok_path() -> Path:
    return local.user_dir() / OK_FILE


def _oks() -> dict:
    try:
        got = json.loads(_ok_path().read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def keep_as_is(key: str) -> dict:
    """Silence one warning until its setting changes."""
    found = {i["key"]: i for i in _items(local.load_settings())}
    if key not in found:
        raise KeyError(key)
    with _lock:
        oks = _oks()
        oks[key] = found[key]["keep"]
        p = _ok_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(oks), encoding="utf-8")
        tmp.replace(p)
    return oks


def _day_files(folder: Path) -> date | None:
    """Oldest YYYY-MM-DD day file (.csv or .parquet) in a position store."""
    if not folder.is_dir():
        return None
    days = []
    for f in folder.iterdir():
        if f.suffix in (".csv", ".parquet"):
            try:
                days.append(date.fromisoformat(f.stem))
            except ValueError:
                pass
    return min(days) if days else None


def _train_days(folder: Path) -> date | None:
    """Oldest day in the train store (<feed>_<YYYY-MM-DD>....jsonl.gz)."""
    days = []
    for f in folder.glob("*_*.jsonl.gz") if folder.is_dir() else []:
        try:
            days.append(date.fromisoformat(f.name.split("_", 1)[1][:10]))
        except ValueError:
            pass
    return min(days) if days else None


def _cached(path: Path, read):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    got = _cache.get(str(path))
    if got and got[0] == mtime:
        return got[1]
    try:
        value = read(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        value = None
    _cache[str(path)] = (mtime, value)
    return value


def _schedules_oldest(data: dict) -> date | None:
    stamps = [e[0] for v in (data.get("etas") or {}).values() for e in v if e]
    stamps += [c.get("left") or c.get("arrived") for v in (data.get("calls") or {}).values() for c in v]
    stamps += [b.get("arrival") or (b.get("first") or [None])[0] for v in (data.get("bookings") or {}).values() for b in v]
    stamps = [float(t) for t in stamps if isinstance(t, (int, float)) and t > 0]
    return datetime.fromtimestamp(min(stamps), timezone.utc).date() if stamps else None


def _news_oldest(items) -> date | None:
    days = []
    for i in items if isinstance(items, list) else []:
        try:
            days.append(date.fromisoformat(str(i.get("date", ""))[:10]))
        except ValueError:
            pass
    return min(days) if days else None


def _history_oldest() -> date | None:
    from worldmodel_api import userdata

    for e in userdata._history():  # oldest first
        try:
            return datetime.fromisoformat(e["at"]).date()
        except (KeyError, ValueError):
            continue
    return None


def _dated(key: str, label: str, setting: str, keep: int, oldest: date | None, today: date, href: str, what: str,
           whole_days: bool = True) -> dict | None:
    if oldest is None or not keep:
        return None
    # A whole day (a position file, a news date) goes once it is more than `keep` days old; a timed
    # entry (an ETA, a History entry) as soon as it is `keep` days old, during that day.
    first_goes = oldest + timedelta(days=keep + 1 if whole_days else keep)
    return {"key": key, "label": label, "setting": setting, "keep": keep, "unit": "days", "oldest": oldest.isoformat(),
            "deletes_from": first_goes.isoformat(), "days_left": (first_goes - today).days, "href": href, "what": what}


def _items(s: dict, today: date | None = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    home = local.home()
    out = [
        _dated("planes", "Saved plane positions", "planes_keep_days", int(s.get("planes_keep_days") or 30),
               _day_files(home / "live" / "planes"), today, "/settings#keep-planes", "older days of positions are deleted"),
        _dated("ships", "Saved ship positions", "ships_keep_days", int(s.get("ships_keep_days") or 30),
               _day_files(home / "live" / "ships"), today, "/settings#keep-ships",
               "older days of positions are deleted, and ships not seen since drop out of the table"),
        _dated("trains", "Saved train positions", "trains_keep_days", int(s.get("trains_keep_days") or 14),
               _train_days(home / "congestion" / "trains"), today, "/settings#keep-trains",
               "older days of train positions and lateness by line are deleted"),
        _dated("schedules", "Ship schedules and port calls", "schedules_keep_days", int(s.get("schedules_keep_days") or 90),
               _cached(home / "live" / "ships" / "schedules.json", _schedules_oldest), today, "/settings#keep-ships",
               "older ETAs, port calls and bookings are dropped (learned routes need a few months)", whole_days=False),
        _dated("news", "News", "news_keep_days", int(s.get("news_keep_days") or 730),
               _cached(home / "media" / "news" / "items.json", _news_oldest), today, "/settings#keep-news",
               "older items are dropped at the next fetch, unless marked Interesting"),
    ]
    hist_days = int(s.get("history_retention_days") or 0)
    if hist_days:
        try:
            oldest = _history_oldest()
        except Exception:  # noqa: BLE001 - a broken log only loses its warning
            oldest = None
        out.append(_dated("history", "Your History log", "history_retention_days", hist_days, oldest, today,
                          "/settings#keep-history", "older entries are dropped, except starred ones", whole_days=False))
    keep = int(s.get("backup_keep") or 10)
    try:
        have = backups_mod.backups(s)
    except OSError:
        have = []
    if have and len(have) >= keep:
        out.append({"key": "backups", "label": "Backups", "setting": "backup_keep", "keep": keep, "unit": "backups",
                    "oldest": have[min(len(have), keep) - 1]["at"][:10], "deletes_from": None, "days_left": 0,
                    "href": "/settings#keep-backups",
                    "what": f"the next backup removes the oldest one ({have[min(len(have), keep) - 1]['name']})"})
    return [i for i in out if i]


def expiring(s: dict | None = None, today: date | None = None, everything: bool = False) -> dict:
    """Saved data within `expiry_warn_days` of its first deletion (or already being deleted),
    except stores where Keep as is was pressed for the setting's present value.
    everything=True lists every store, with `due` and `ok` on each."""
    s = s or local.load_settings()
    warn = int(s.get("expiry_warn_days", 7))
    oks = _oks()
    items = []
    for i in _items(s, today):
        i["due"] = bool(warn) and i["days_left"] <= warn
        i["ok"] = oks.get(i["key"]) == i["keep"]
        if everything or (i["due"] and not i["ok"]):
            items.append(i)
    items.sort(key=lambda i: (i["unit"] == "backups", i["days_left"]))
    return {"warn_days": warn, "items": items}
