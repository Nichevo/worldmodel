"""Highlights: everything you keep, in one place (highlights.json in the user folder).

Kinds:
  text     a passage selected on a page, with the page and date it came from
  chart    a chart or map kept live: its settings (`query`, the map page's address
           for a one-panel workspace) reopen it as a working panel; optionally a
           frozen picture too (saved as highlights/<id>.png)
  table    rows and columns as they were
  answer   an AI answer (question, model and answer copied, so the export stands alone)

Each item takes a title, tags and a note; the list can be searched and filtered by
kind, tag or country, and exported as Markdown.
"""

from __future__ import annotations

import base64
import re
import secrets
from pathlib import Path

from worldmodel_api import userdata
from worldmodel_api.ai import clean_tags

KINDS = ("text", "chart", "table", "answer")
MAX_ITEMS = 20_000
MAX_PICTURE = 8 * 1024 * 1024


def _items() -> list[dict]:
    items = userdata._read_json("highlights.json", [])
    return items if isinstance(items, list) else []


def picture_dir() -> Path:
    return userdata._path("highlights")


def picture_path(item_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{12}", item_id):
        return None
    p = picture_dir() / f"{item_id}.png"
    return p if p.is_file() else None


def _str(v, n: int) -> str:
    return str(v or "").strip()[:n]


def add(data: dict) -> dict:
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    item = {"id": secrets.token_hex(6), "kind": kind, "created_at": userdata.now(), "updated_at": None,
            "title": _str(data.get("title"), 300), "text": _str(data.get("text"), 100_000),
            "page_url": _str(data.get("page_url"), 4000), "page_title": _str(data.get("page_title"), 300),
            "entities": [e for e in (_str(x, 60) for x in (data.get("entities") or [])) if e][:12],
            "indicator": _str(data.get("indicator"), 80) or None, "query": _str(data.get("query"), 4000) or None,
            "table": _table(data.get("table")), "answer_id": _str(data.get("answer_id"), 20) or None,
            "question": _str(data.get("question"), 20_000) or None, "model": _str(data.get("model"), 120) or None,
            "sources": _str(data.get("sources"), 2000) or None,
            "tags": clean_tags(data.get("tags")), "note": _str(data.get("note"), 10_000), "picture": False}
    if kind == "text" and not item["text"]:
        raise ValueError("a text highlight needs its text")
    if kind == "chart" and not item["query"]:
        raise ValueError("a chart highlight needs its settings (query)")
    if kind == "answer" and not item["text"]:
        raise ValueError("an answer highlight needs the answer text")
    if not item["title"]:
        item["title"] = (item["text"][:80] + ("…" if len(item["text"]) > 80 else "")) if item["text"] else kind.title()
    picture = data.get("picture")
    if picture:
        _save_picture(item["id"], picture)
        item["picture"] = True
    with userdata._lock:
        items = _items() + [item]
        userdata._write_json("highlights.json", items[-MAX_ITEMS:])
    try:
        userdata.add_history({"kind": "highlight", "title": f"Kept: {item['title']}", "url": f"/highlights?item={item['id']}",
                              "entity": item["entities"][0] if item["entities"] else None, "indicator": item["indicator"]})
    except ValueError:
        pass
    return item


def _table(t) -> dict | None:
    if not isinstance(t, dict) or not isinstance(t.get("columns"), list) or not isinstance(t.get("rows"), list):
        return None
    cols = [_str(c, 120) for c in t["columns"][:40]]
    rows = [[None if v is None else (v if isinstance(v, (int, float)) else _str(v, 300)) for v in r[:40]]
            for r in t["rows"][:5000] if isinstance(r, list)]
    return {"columns": cols, "rows": rows, "unit": _str(t.get("unit"), 80) or None}


def _save_picture(item_id: str, data_url: str) -> None:
    m = re.fullmatch(r"data:image/png;base64,([A-Za-z0-9+/=\s]+)", str(data_url))
    if not m:
        raise ValueError("the picture must be a PNG data URL")
    raw = base64.b64decode(m.group(1))
    if len(raw) > MAX_PICTURE or not raw.startswith(b"\x89PNG"):
        raise ValueError("the picture must be a PNG under 8 MB")
    picture_dir().mkdir(parents=True, exist_ok=True)
    (picture_dir() / f"{item_id}.png").write_bytes(raw)


def search(q: str | None = None, kind: str | None = None, tag: str | None = None, entity: str | None = None) -> list[dict]:
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for it in reversed(_items()):
        if kind and it["kind"] != kind:
            continue
        if tag and tag.lower() not in it.get("tags", []):
            continue
        if entity and entity not in it.get("entities", []):
            continue
        hay = " ".join(str(it.get(k) or "") for k in ("title", "text", "note", "page_title", "question", "model")).lower()
        hay += " " + " ".join(it.get("tags", []))
        if all(w in hay for w in words):
            out.append(it)
    return out


def tags() -> list[dict]:
    counts: dict[str, int] = {}
    for it in _items():
        for t in it.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def update(item_id: str, patch: dict) -> dict:
    with userdata._lock:
        items = _items()
        it = next((x for x in items if x["id"] == item_id), None)
        if it is None:
            raise KeyError(item_id)
        if "title" in patch:
            it["title"] = _str(patch["title"], 300) or it["title"]
        if "note" in patch:
            it["note"] = _str(patch["note"], 10_000)
        if "tags" in patch:
            it["tags"] = clean_tags(patch["tags"])
        it["updated_at"] = userdata.now()
        userdata._write_json("highlights.json", items)
        return it


def delete(item_id: str) -> bool:
    with userdata._lock:
        items = _items()
        kept = [x for x in items if x["id"] != item_id]
        if len(kept) == len(items):
            return False
        userdata._write_json("highlights.json", kept)
    p = picture_path(item_id)
    if p:
        p.unlink()
    return True


def markdown(items: list[dict], base_url: str = "") -> str:
    """Highlights as one Markdown document, newest first."""
    lines = ["# Highlights", ""]
    for it in items:
        lines.append(f"## {it['title']}")
        meta = [it["kind"], it["created_at"][:10]]
        if it.get("tags"):
            meta.append("tags: " + ", ".join(it["tags"]))
        lines += [f"*{' · '.join(meta)}*", ""]
        if it["kind"] == "answer":
            if it.get("question"):
                lines += [f"**Question:** {it['question']}", ""]
            lines += [it["text"], ""]
            if it.get("model"):
                lines += [f"*Answered by {it['model']}.*", ""]
        elif it["kind"] == "text":
            lines += ["> " + it["text"].replace("\n", "\n> "), ""]
        elif it.get("text"):
            lines += [it["text"], ""]
        t = it.get("table")
        if t and t.get("columns"):
            lines.append("| " + " | ".join(t["columns"]) + " |")
            lines.append("| " + " | ".join("---" for _ in t["columns"]) + " |")
            for r in t["rows"][:500]:
                lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
            lines.append("")
        if it.get("query"):
            lines += [f"[Open the chart]({base_url}/?{it['query']})", ""]
        if it.get("page_url"):
            lines += [f"From: [{it.get('page_title') or it['page_url']}]({base_url}{it['page_url'] if it['page_url'].startswith('/') else ''}"
                      f"{'' if it['page_url'].startswith('/') else it['page_url']})", ""]
        if it.get("sources"):
            lines += [f"Sources: {it['sources']}", ""]
        if it.get("note"):
            lines += [f"**Note:** {it['note']}", ""]
    return "\n".join(lines).rstrip() + "\n"
