"""The user's own files beside layouts.json: settings, indicator switches and the history log.

All live in the user folder (see worldmodel_contract.local.user_dir), never in the
warehouse, and are written atomically so a crash never leaves half a file.

  settings.json     the Settings page; defaults and ranges in worldmodel_contract.local
  indicators.json   indicators switched on or off, where that differs from the default
  history.jsonl     one line per thing opened or looked at; append-only
  history_marks.json  stars and notes on history entries, by entry id
  milestones.json   your own dated events (a policy change, a deal, a personal marker), shown with the rest
"""

from __future__ import annotations

import json
import secrets
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldmodel_contract import local

_lock = threading.Lock()
HISTORY_KINDS = ("page", "view", "indicator", "pin", "fetch")
MAX_TEXT = 300


def _path(name: str) -> Path:
    return local.user_dir() / name


def _read_json(name: str, default):
    try:
        return json.loads(_path(name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(name: str, data) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------- settings
def settings() -> dict:
    return local.clean_settings(_read_json("settings.json", {}))


def save_settings(patch: dict) -> dict:
    with _lock:
        merged = local.clean_settings(patch, settings())
        _write_json("settings.json", merged)
        return merged


# ----------------------------------------------------------------------------- indicator switches
def indicator_overrides() -> dict[str, bool]:
    data = _read_json("indicators.json", {})
    return {k: bool(v) for k, v in data.get("enabled", {}).items()} if isinstance(data, dict) else {}


def set_indicators(changes: dict[str, bool], defaults: dict[str, bool]) -> dict[str, bool]:
    """Record switches; a switch back to the default drops the override."""
    with _lock:
        cur = indicator_overrides()
        for k, v in changes.items():
            if defaults.get(k) == bool(v):
                cur.pop(k, None)
            else:
                cur[k] = bool(v)
        _write_json("indicators.json", {"enabled": cur, "saved_at": now()})
        return cur


def reset_indicators() -> None:
    with _lock:
        _write_json("indicators.json", {"enabled": {}, "saved_at": now()})


# ----------------------------------------------------------------------------- history
_cache: dict = {"mtime": None, "entries": []}


def _history() -> list[dict]:
    """Every entry, oldest first; re-read only when the file changes."""
    path = _path("history.jsonl")
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return []
    if _cache["mtime"] != mtime:
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        _cache.update(mtime=mtime, entries=entries)
    return _cache["entries"]


def _rewrite(entries: list[dict]) -> None:
    path = _path("history.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    tmp.replace(path)


def _marks() -> dict[str, dict]:
    return _read_json("history_marks.json", {})


def add_history(entry: dict) -> dict | None:
    """Log one thing opened. Nothing while history is paused; the same thing logged
    again within ten minutes only moves the earlier entry's time forward."""
    s = settings()
    if s["history_paused"]:
        return None
    kind = entry.get("kind")
    if kind not in HISTORY_KINDS:
        raise ValueError(f"kind must be one of {', '.join(HISTORY_KINDS)}")
    clean = {k: str(entry[k])[:MAX_TEXT if k != "url" else 4000] for k in ("title", "url", "entity", "indicator", "detail")
             if entry.get(k)}
    if not clean.get("title"):
        raise ValueError("a history entry needs a title")
    with _lock:
        entries = list(_history())
        stamp = now()
        last = entries[-1] if entries else None
        if (last and last.get("kind") == kind and last.get("url") == clean.get("url") and last.get("title") == clean["title"]
                and _age(last["at"]) < timedelta(minutes=10)):
            last["at"] = stamp
            _rewrite(entries)
            return last
        rec = {"id": secrets.token_hex(6), "at": stamp, "kind": kind, **clean}
        entries.append(rec)
        entries = _apply_retention(entries, s["history_retention_days"])
        if len(entries) == len(_history()) + 1:
            path = _path("history.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        else:
            _rewrite(entries)
        return rec


def _age(at: str) -> timedelta:
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(at)
    except ValueError:
        return timedelta.max


def _apply_retention(entries: list[dict], days: int) -> list[dict]:
    if not days:
        return entries
    marks = _marks()
    cutoff = timedelta(days=days)
    return [e for e in entries if _age(e["at"]) <= cutoff or marks.get(e["id"], {}).get("star")]


def history(q: str | None = None, kind: str | None = None, starred: bool = False, since: str | None = None,
            until: str | None = None, limit: int = 500) -> list[dict]:
    """Newest first, with stars and notes attached."""
    marks = _marks()
    out = []
    needle = (q or "").lower()
    for e in reversed(_history()):
        m = marks.get(e["id"], {})
        rec = {**e, "star": bool(m.get("star")), "note": m.get("note", "")}
        if kind and e["kind"] != kind:
            continue
        if starred and not rec["star"]:
            continue
        if since and e["at"][:10] < since:
            continue
        if until and e["at"][:10] > until:
            continue
        if needle and needle not in " ".join(str(v) for v in rec.values()).lower():
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def mark(entry_id: str, star: bool | None = None, note: str | None = None) -> dict:
    with _lock:
        if not any(e["id"] == entry_id for e in _history()):
            raise KeyError(entry_id)
        marks = _marks()
        m = marks.get(entry_id, {})
        if star is not None:
            m["star"] = bool(star)
        if note is not None:
            m["note"] = note.strip()[:2000]
        marks[entry_id] = m
        if not m.get("star") and not m.get("note"):
            marks.pop(entry_id)
        _write_json("history_marks.json", marks)
        return {"id": entry_id, "star": bool(m.get("star")), "note": m.get("note", "")}


def clear_history(keep_starred: bool = True, before: str | None = None) -> int:
    """Delete entries (all, or those before a date), keeping starred ones unless told not to."""
    with _lock:
        entries = _history()
        marks = _marks()
        keep = [e for e in entries
                if (keep_starred and marks.get(e["id"], {}).get("star")) or (before and e["at"][:10] >= before)]
        _rewrite(keep)
        kept = {e["id"] for e in keep}
        _write_json("history_marks.json", {k: v for k, v in marks.items() if k in kept})
        return len(entries) - len(keep)


def entity_interest(limit: int = 50) -> list[dict]:
    """Countries and groups by how often and how lately they were opened: the order
    in which on-demand fetches (Wikipedia, Numbeo) should go."""
    score: Counter[str] = Counter()
    last: dict[str, str] = {}
    for e in _history():
        ent = e.get("entity")
        if not ent:
            continue
        days = max(0.0, _age(e["at"]).total_seconds() / 86400)
        score[ent] += 0.5 ** (days / 30)  # an open counts half as much a month later
        last[ent] = e["at"]
    return [{"entity_id": k, "score": round(v, 3), "last": last[k]} for k, v in score.most_common(limit)]


# ----------------------------------------------------------------------------- milestones
def _date(v, field: str, required: bool) -> str | None:
    v = (str(v).strip() if v is not None else "")
    if not v:
        if required:
            raise ValueError(f"{field} is required (YYYY-MM-DD)")
        return None
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a date, YYYY-MM-DD") from None


def milestones() -> list[dict]:
    """Your own events, oldest first."""
    return sorted(_read_json("milestones.json", []), key=lambda m: m["start_date"])


def save_milestone(data: dict, milestone_id: str | None = None) -> dict:
    """Add a milestone, or change one: {entity_id, title, start_date, end_date?, subkind?, note?, url?}."""
    title = str(data.get("title") or "").strip()[:MAX_TEXT]
    entity = str(data.get("entity_id") or "").strip()[:40]
    if not title or not entity:
        raise ValueError("a milestone needs a title and a country (entity_id)")
    start = _date(data.get("start_date"), "start_date", True)
    end = _date(data.get("end_date"), "end_date", False)
    if end and end < start:
        raise ValueError("end_date is before start_date")
    m = {"entity_id": entity, "title": title, "start_date": start, "end_date": end,
         "subkind": str(data.get("subkind") or "").strip()[:60] or None,
         "note": str(data.get("note") or "").strip()[:2000], "url": str(data.get("url") or "").strip()[:500] or None}
    with _lock:
        items = _read_json("milestones.json", [])
        if milestone_id:
            old = next((x for x in items if x["id"] == milestone_id), None)
            if old is None:
                raise KeyError(milestone_id)
            old.update(m, updated_at=now())
            m = old
        else:
            m = {"id": secrets.token_hex(6), **m, "created_at": now()}
            items.append(m)
        _write_json("milestones.json", items)
        return m


def delete_milestone(milestone_id: str) -> bool:
    with _lock:
        items = _read_json("milestones.json", [])
        kept = [x for x in items if x["id"] != milestone_id]
        if len(kept) == len(items):
            return False
        _write_json("milestones.json", kept)
        return True
