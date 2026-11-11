"""The inbox: save a downloaded file anywhere the app looks, and it goes to the right source.

Files dropped in <home>/inbox are moved into their source's manual folder
(<home>/manual/<source>/); files in your Downloads folder (when Settings allows it) are
copied there instead, and only when the source is certain, so the rest of Downloads is
never touched. Loading what was filed is the data side's job (`worldmodel-data inbox`).

How a file's source is worked out, in order:
  1. its name matches one of the source's file patterns in the catalogue (pt_*.csv);
  2. its name has the same shape (digits ignored) as a file already loaded for a source,
     or as a file you filed by hand once (the app remembers your choice);
  3. Windows noted the page it was downloaded from (Edge and Chrome record it with the file),
     or a page saved from the browser says which address it was saved from;
     that address is matched to the sources' download pages.
A file that matches more than one source, or none, waits in the inbox for you to choose.
Nothing is ever deleted: older files of a one-file source move to its 'old' folder.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from worldmodel_contract import local

SKIP = (".tmp", ".crdownload", ".part", ".partial", ".download")
# Names too plain to tell sources apart, never learnt from.
GENERIC = {"data", "download", "downloads", "export", "file", "table", "tables", "sheet", "report", "results", "query",
           "page", "index", "#", "untitled", "document", "book", "workbook", "output", "dataset", "csv", "excel"}
LEARNT = "_known files.json"
LOG = "_filed.jsonl"
SOURCES = "_sources.json"  # written by the data side: how each source keeps its files


def inbox_dir(root: Path | None = None) -> Path:
    return (root or local.home()) / "inbox"


def manual_root(root: Path | None = None) -> Path:
    return (root or local.home()) / "manual"


def downloads_dir(settings: dict | None = None) -> Path | None:
    """Your Downloads folder, when Settings lets the app look in it."""
    s = settings or local.load_settings()
    if not s.get("inbox_downloads", True):
        return None
    d = Path(s.get("inbox_downloads_folder") or (Path.home() / "Downloads")).expanduser()
    return d if d.is_dir() else None


def source_info(root: Path | None = None) -> dict[str, dict]:
    """source -> {keeps_files, manual, fallback, every_days, needs_env, needs_settings, pack, switch}, as the data side last wrote it."""
    try:
        data = json.loads((manual_root(root) / SOURCES).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def shape(name: str) -> str:
    """A file name with its digits and case ignored: pt_20251001.CSV -> pt_#.csv."""
    stem, dot, ext = name.lower().rpartition(".")
    if not dot:
        stem, ext = name.lower(), ""
    stem = re.sub(r"\(\d+\)$", "", stem.strip()).strip()  # "file (2)" from a second download
    stem = re.sub(r"\d+", "#", stem)
    stem = re.sub(r"[\s_.-]+", "_", stem).strip("_")
    return f"{stem}.{ext}" if ext else stem


def _plain(sh: str) -> bool:
    stem = sh.rsplit(".", 1)[0]
    return stem in GENERIC or len(stem.replace("#", "").replace("_", "")) < 3


def _learnt(root: Path | None) -> dict[str, str]:
    try:
        data = json.loads((manual_root(root) / LEARNT).read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def learn(name: str, source_id: str, root: Path | None = None) -> None:
    """Remember that a file named like this belongs to this source (your choice wins)."""
    sh = shape(name)
    if _plain(sh):
        return
    known = _learnt(root)
    known[sh] = source_id
    path = manual_root(root) / LEARNT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")


def _shapes_in_folders(root: Path | None) -> dict[str, set[str]]:
    """Shapes of the files already in each source's manual folder (and its 'old' folder)."""
    out: dict[str, set[str]] = {}
    base = manual_root(root)
    if not base.is_dir():
        return out
    for d in base.iterdir():
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        for sub in (d, d / "old"):
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                if f.is_file() and not f.name.startswith(("_", ".", "~$")):
                    sh = shape(f.name)
                    if not _plain(sh):
                        out.setdefault(sh, set()).add(d.name)
    return out


def _where_from(path: Path) -> list[str]:
    """The addresses a file came from: Windows' note on a download (Zone.Identifier: the
    page and the file's own address), or the 'saved from' line of a page saved from a browser."""
    urls: list[str] = []
    try:
        with open(f"{path}:Zone.Identifier", encoding="utf-8", errors="ignore") as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() in ("ReferrerUrl", "HostUrl") and v.strip().startswith("http"):
                    urls.append(v.strip())
    except OSError:
        pass
    if path.suffix.lower() in (".htm", ".html", ".mhtml", ".mht"):
        try:
            head = path.open("rb").read(20000).decode("utf-8", "ignore")
        except OSError:
            head = ""
        m = re.search(r"saved from url=\(\d+\)(\S+?)\s*-->", head)
        if m:
            urls.append(m.group(1))
        m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', head, re.I)
        if m:
            urls.append(m.group(1))
        m = re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)', head, re.I)
        if m:
            urls.append(m.group(1))
    return urls


def _host(u: str) -> str:
    h = (urlparse(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _by_address(urls: list[str], candidates: dict[str, list[str]]) -> list[str]:
    """Sources whose download page best matches one of the addresses: same site, then the
    longest shared path."""
    best: tuple[int, list[str]] = (0, [])
    for u in urls:
        h, path = _host(u), urlparse(u).path.lower().rstrip("/")
        if not h:
            continue
        for sid, pages in candidates.items():
            for page in pages:
                ph, pp = _host(page), urlparse(page).path.lower().rstrip("/")
                if not ph or not (h == ph or h.endswith("." + ph) or ph.endswith("." + h)):
                    continue
                common = os.path.commonprefix([path.split("/"), pp.split("/")])
                score = 10 + len([c for c in common if c])
                if score > best[0]:
                    best = (score, [sid])
                elif score == best[0] and sid not in best[1]:
                    best[1].append(sid)
    return best[1]


class Recogniser:
    """Works out a file's source; build one per run (it reads the catalogue and the folders once)."""

    def __init__(self, root: Path | None = None):
        from worldmodel_contract import catalogue

        self.root = root
        self.info = source_info(root)
        meta = catalogue.sources()
        self.patterns = {s.id: list(s.manual.files) for s in meta.values() if s.manual and s.manual.files}
        # Sources a file can go to: those with a manual folder (by hand, or a fallback).
        allowed = set(self.info) or {s.id for s in meta.values() if s.manual}
        self.allowed = allowed
        self.pages = {s.id: [u for u in (s.manual.get if s.manual else "", s.url) if u and u.startswith("http")]
                      for s in meta.values() if s.id in allowed}
        self.names = {s.id: s.name for s in meta.values()}
        self.learnt = _learnt(root)
        self.folders = _shapes_in_folders(root)

    def guess(self, path: Path) -> dict:
        """{"source_id": the one source or None, "candidates": [...], "how": why it was chosen, "sure": bool}."""
        name = path.name
        hits = [sid for sid, pats in self.patterns.items() if sid in self.allowed
                and any(fnmatch.fnmatch(name.lower(), p.lower()) for p in pats)]
        if len(hits) == 1:
            return {"source_id": hits[0], "candidates": hits, "how": "its name matches the source's files", "sure": True}
        sh = shape(name)
        if sh in self.learnt and self.learnt[sh] in self.allowed:
            return {"source_id": self.learnt[sh], "candidates": [self.learnt[sh]], "how": "you filed a file named like it there before",
                    "sure": True}
        seen = sorted(self.folders.get(sh, set()) & self.allowed)
        if len(seen) == 1:
            return {"source_id": seen[0], "candidates": seen, "how": "a file named like it is already in that folder", "sure": True}
        by_url = _by_address(_where_from(path), {k: v for k, v in self.pages.items() if not hits or k in hits})
        if len(by_url) == 1:
            return {"source_id": by_url[0], "candidates": by_url, "how": "it was downloaded from that source's site", "sure": True}
        cands = hits or seen or by_url
        return {"source_id": None, "candidates": cands, "how": "more than one source fits" if cands else "no source recognised", "sure": False}


def _files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(f for f in folder.iterdir() if f.is_file() and not f.name.startswith(("_", ".", "~$"))
                  and not f.name.lower().endswith(SKIP) and f.name.lower() != "desktop.ini")


def _ledger(root: Path | None) -> dict[str, str]:
    """Downloads files already copied in: "name|size|mtime" -> source."""
    try:
        data = json.loads((inbox_dir(root) / "_copied.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _ledger_key(f: Path) -> str:
    st = f.stat()
    return f"{f.name}|{st.st_size}|{int(st.st_mtime)}"


def place(file: Path, source_id: str, root: Path | None = None, move: bool = True) -> Path:
    """Put a file in its source's manual folder (moved from the inbox, copied from elsewhere).
    For a source that reads one file at a time, the folder's other files move to 'old'."""
    d = manual_root(root) / source_id
    d.mkdir(parents=True, exist_ok=True)
    keeps = bool((source_info(root).get(source_id) or {}).get("keeps_files"))
    target = d / file.name
    if target.exists() and target.stat().st_size == file.stat().st_size and target.read_bytes() == file.read_bytes():
        if move:  # the same file again: tidy it out of the inbox, into the source's old folder
            (d / "old").mkdir(exist_ok=True)
            shutil.move(str(file), str(_free(d / "old" / file.name)))
        return target
    if not keeps:
        for f in _files(d):
            if f.name != file.name:
                (d / "old").mkdir(exist_ok=True)
                shutil.move(str(f), str(_free(d / "old" / f.name)))
    if target.exists():
        (d / "old").mkdir(exist_ok=True)
        shutil.move(str(target), str(_free(d / "old" / target.name)))
    if move:
        shutil.move(str(file), str(target))
    else:
        shutil.copy2(file, target)
    return target


def _free(path: Path) -> Path:
    """path, or path with (2), (3) ... added when the name is taken."""
    if not path.exists():
        return path
    for i in range(2, 1000):
        p = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not p.exists():
            return p
    return path


def _log(entry: dict, root: Path | None) -> None:
    path = inbox_dir(root) / LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def file_all(root: Path | None = None, settings: dict | None = None) -> dict:
    """File everything waiting: the inbox (moved) and, when allowed, recent files in Downloads
    whose source is certain (copied). Returns {"filed": [...], "waiting": [...]}; the sources
    filed into are the ones to load next."""
    s = settings or local.load_settings(root)
    inbox = inbox_dir(root)
    inbox.mkdir(parents=True, exist_ok=True)
    _readme(inbox)
    rec = Recogniser(root)
    off = set(filter(None, str(s.get("sources_off") or "").split(",")))
    filed, waiting = [], []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for f in _files(inbox):
        g = rec.guess(f)
        if g["source_id"]:
            try:
                to = place(f, g["source_id"], root, move=True)
            except OSError as exc:  # open in another program, say
                waiting.append({"name": f.name, "candidates": [g["source_id"]], "how": f"could not move it: {exc}"})
                continue
            e = {"at": now, "name": f.name, "from": "inbox", "source_id": g["source_id"], "how": g["how"], "to": str(to)}
            _log(e, root)
            filed.append(e)
        else:
            waiting.append({"name": f.name, "size": f.stat().st_size, "candidates": g["candidates"], "how": g["how"]})
    dl = downloads_dir(s)
    if dl:
        days = int(s.get("inbox_downloads_days", 14))
        since = (datetime.now() - timedelta(days=days)).timestamp()
        ledger = _ledger(root)
        changed = False
        for f in _files(dl):
            try:
                if f.stat().st_mtime < since:
                    continue
                key = _ledger_key(f)
            except OSError:
                continue
            if key in ledger:
                continue
            g = rec.guess(f)
            if not g["source_id"] or g["source_id"] in off:
                continue
            try:
                to = place(f, g["source_id"], root, move=False)
            except OSError:
                continue
            ledger[key] = g["source_id"]
            changed = True
            e = {"at": now, "name": f.name, "from": "Downloads", "source_id": g["source_id"], "how": g["how"], "to": str(to)}
            _log(e, root)
            filed.append(e)
        if changed:
            (inbox / "_copied.json").write_text(json.dumps(ledger, indent=0), encoding="utf-8")
    return {"filed": filed, "waiting": waiting}


def assign(name: str, source_id: str, root: Path | None = None) -> dict:
    """File one inbox file into the source you chose, and remember files named like it."""
    f = inbox_dir(root) / Path(name).name
    if not f.is_file():
        raise FileNotFoundError(f"{name} is not in the inbox")
    to = place(f, source_id, root, move=True)
    learn(f.name, source_id, root)
    e = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "name": f.name, "from": "inbox",
         "source_id": source_id, "how": "you chose it", "to": str(to)}
    _log(e, root)
    return e


def state(root: Path | None = None, settings: dict | None = None) -> dict:
    """What is waiting in the inbox (with guesses), what was filed lately, and where the app looks."""
    s = settings or local.load_settings(root)
    rec = Recogniser(root)
    waiting = []
    for f in _files(inbox_dir(root)):
        g = rec.guess(f)
        waiting.append({"name": f.name, "size": f.stat().st_size, **g,
                        "candidate_names": {c: rec.names.get(c, c) for c in g["candidates"]}})
    recent = []
    try:
        lines = (inbox_dir(root) / LOG).read_text(encoding="utf-8").splitlines()[-40:]
        recent = [json.loads(x) for x in reversed(lines) if x.strip()]
    except (OSError, ValueError):
        pass
    for r in recent:
        r["source_name"] = rec.names.get(r.get("source_id"), r.get("source_id"))
    dl = downloads_dir(s)
    return {"inbox": str(inbox_dir(root)), "downloads": str(dl) if dl else None,
            "downloads_on": bool(s.get("inbox_downloads", True)), "downloads_days": s.get("inbox_downloads_days", 14),
            "waiting": waiting, "recent": recent,
            "sources": sorted(({"source_id": k, "name": rec.names.get(k, k)} for k in rec.allowed), key=lambda x: x["name"])}


def _readme(inbox: Path) -> None:
    p = inbox / "_read me.txt"
    if p.exists():
        return
    p.write_text(
        "Save any file you download for the app here, with the name the site gives it.\r\n\r\n"
        "At each refresh (or 'File them now' on the To do page, or .\\load.bat) the app works out\r\n"
        "which source each file belongs to, moves it into var\\manual\\<source>\\ and loads it.\r\n"
        "A file it cannot place stays here; the To do page asks you which source it is.\r\n", encoding="utf-8")
