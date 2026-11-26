"""Find data: search Dateno's index of open datasets (government, statistics and research portals
worldwide) for topics the app does not hold yet. Needs a free key, DATENO_API_KEY.

- Searches go to https://api.dateno.io/search/0.2/query (q, filters, limit, offset, facets, sort_by;
  key as the `apikey` query parameter). The reply is Elasticsearch-shaped: hits.total.value,
  hits.hits[]._source (the dataset descriptor) and aggregations (the facets).
- Each answer is kept a day (var/cache/dateno), so the same search again costs nothing.
- Dateno sends the searches left today and this month with every reply; the last numbers are kept
  so Settings and the Find data page can show them.
- A file is downloaded only from a link Dateno gave for a dataset (never any address sent in),
  into var/found/<dataset>/, up to MAX_DOWNLOAD bytes.
- "Want this as a source" keeps the dataset in user/data_wishes.json; the To do page lists them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from worldmodel_contract import local

BASE = (os.environ.get("DATENO_SERVER_URL") or "https://api.dateno.io").rstrip("/")
KEY_ENV = "DATENO_API_KEY"
KEEP = 24 * 3600                 # seconds a search answer is kept
FACETS_KEEP = 7 * 24 * 3600      # the list of facets changes rarely
MAX_DOWNLOAD = 500 * 1024 * 1024  # bytes; bigger files are left for the browser
PAGE = 20
UA = {"User-Agent": "worldmodel (personal research tool)", "Dateno-Client": "worldmodel/personal"}
WISHES = "data_wishes.json"
QUOTA = "dateno_quota.json"

# Facets shown as filters, in this order, with plain names (Dateno's own name is used for others).
FACET_NAMES = {
    "source.countries.name": "Country", "source.countries.id": "Country",
    "dataset.formats": "Format", "dataset.topics": "Topic", "source.catalog_type": "Kind of portal",
    "source.macroregions.name": "World region", "source.subregions.name": "Part of the world",
    "source.owner_type": "Publisher type", "source.langs.name": "Language", "dataset.datatypes": "Data type",
    "source.software.name": "Portal software",
}
FACET_ORDER = list(FACET_NAMES)

_lock = threading.Lock()
_seen: dict[str, dict] = {}       # dataset id -> its last descriptor, so a download needs no second call


class DatenoError(Exception):
    """A search that could not be done, with a message fit to show."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def key() -> str:
    return (os.environ.get(KEY_ENV) or "").strip()


def _cache_dir() -> Path:
    return local.home() / "cache" / "dateno"


def found_dir() -> Path:
    return local.home() / "found"


# ----------------------------------------------------------------------------- quota
def _save_quota(headers: httpx.Headers) -> None:
    def num(name: str) -> int | None:
        try:
            return int(headers.get(name))
        except (TypeError, ValueError):
            return None

    q = {"day_left": num("X-RateLimit-Remaining-Day"), "day_limit": num("X-RateLimit-Limit-Day"),
         "month_left": num("X-RateLimit-Remaining-Month"), "month_limit": num("X-RateLimit-Limit-Month"),
         "day_resets_in": num("RateLimit-Reset"), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if all(q[k] is None for k in ("day_left", "month_left")):
        return
    path = local.user_dir() / QUOTA
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(q), encoding="utf-8")
    except OSError:
        pass


def quota() -> dict | None:
    try:
        return json.loads((local.user_dir() / QUOTA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------------- asking Dateno
def _get(path: str, params: list[tuple[str, str]], client: httpx.Client | None = None) -> dict:
    k = key()
    if not k:
        raise DatenoError("No Dateno key yet. Add DATENO_API_KEY on the Data status page (Keys you can add) or in .env.", 400)
    own = client is None
    c = client or httpx.Client(timeout=30, headers=UA, follow_redirects=True)
    try:
        r = c.get(f"{BASE}{path}", params=[*params, ("apikey", k)])
    except httpx.HTTPError as exc:
        raise DatenoError(f"Could not reach Dateno ({type(exc).__name__}). Check the internet connection and try again.") from None
    finally:
        if own:
            c.close()
    _save_quota(r.headers)
    if r.status_code in (401, 403):
        raise DatenoError("Dateno refused the key. Check DATENO_API_KEY (copy it again from My Account on dateno.io).", 403)
    if r.status_code == 429:
        q = quota() or {}
        when = q.get("day_resets_in")
        more = f" The daily count starts again in about {round(when / 3600)} hours." if isinstance(when, int) and when > 0 else ""
        raise DatenoError(f"Out of Dateno searches for now (free tier).{more} Searches already made still show.", 429)
    if r.status_code >= 400:
        raise DatenoError(f"Dateno answered {r.status_code}: {r.text[:200]}", 502)
    try:
        return r.json()
    except ValueError:
        raise DatenoError("Dateno sent something that is not JSON.") from None


def _cached(name: str, keep: int) -> dict | None:
    path = _cache_dir() / f"{name}.json"
    try:
        if time.time() - path.stat().st_mtime < keep:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _store(name: str, data: dict) -> None:
    path = _cache_dir() / f"{name}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


# ----------------------------------------------------------------------------- reading the answer
def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        return str(v.get("name") or v.get("title") or v.get("id") or "")
    return str(v)


def _names(items) -> list[str]:
    return [t for t in (_text(x).strip() for x in (items or [])) if t]


def _plain(html: str | None, limit: int = 600) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    t = re.sub(r"&nbsp;", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def dataset(hit: dict) -> dict:
    """One search hit (or entry) as the page shows it."""
    src = hit.get("_source") if isinstance(hit.get("_source"), dict) else hit
    d = src.get("dataset") or {}
    s = src.get("source") or {}
    pubs = [p for p in d.get("responsible") or [] if isinstance(p, dict)]
    publisher = next((p.get("title") for p in pubs if str(p.get("role", "")).lower() == "publisher" and p.get("title")), None)
    files = []
    for i, r in enumerate(src.get("resources") or []):
        if not isinstance(r, dict) or not str(r.get("url") or "").startswith(("http://", "https://")):
            continue
        size = r.get("datasize")
        if isinstance(size, dict):
            size = size.get("value") or size.get("size")
        files.append({"n": i, "name": r.get("name") or Path(urlparse(r["url"]).path).name or "file",
                      "format": (r.get("format") or r.get("d_ext") or "").lstrip(".").upper() or None,
                      "url": r["url"], "size": size if isinstance(size, (int, float)) else None})
    out = {
        "id": str(hit.get("_id") or src.get("id") or ""),
        "title": _plain(d.get("title"), 300) or "(no title)",
        "text": _plain(d.get("description") or d.get("short_text")),
        "url": d.get("url") or s.get("url"),
        "publisher": publisher or s.get("owner_name") or s.get("name"),
        "portal": s.get("name"), "portal_url": s.get("url"), "portal_kind": _text(s.get("catalog_type")) or None,
        "countries": [{"id": _text(c.get("id")) if isinstance(c, dict) else "", "name": _text(c)} for c in s.get("countries") or []],
        "formats": sorted({f.lstrip(".").upper() for f in _names(d.get("formats"))}),
        "topics": _names(d.get("topics")) or _names(d.get("topics_original")),
        "tags": _names(d.get("tags"))[:12],
        "licence": d.get("license_name") or d.get("license_id"), "licence_url": d.get("license_url"),
        "created": (d.get("date_created") or "")[:10] or None, "changed": (d.get("date_changed") or "")[:10] or None,
        "files": files[:40], "more_files": max(0, len(files) - 40),
    }
    if out["id"]:
        with _lock:
            _seen[out["id"]] = out
            if len(_seen) > 2000:
                for k in list(_seen)[:500]:
                    _seen.pop(k, None)
    return out


def facets_from(aggs: dict | None, names: dict[str, str]) -> list[dict]:
    """Elasticsearch aggregations -> [{key, name, values: [{value, count}]}], known facets first."""
    out = []
    for k, a in (aggs or {}).items():
        if not isinstance(a, dict):
            continue
        buckets = a.get("buckets")
        if buckets is None:  # a nested aggregation holds its terms one level down
            inner = next((v for v in a.values() if isinstance(v, dict) and "buckets" in v), None)
            buckets = inner.get("buckets") if inner else None
        if not isinstance(buckets, list):
            continue
        vals = [{"value": _text(b.get("key")), "count": int(b.get("doc_count") or b.get("num") or 0)}
                for b in buckets if isinstance(b, dict) and _text(b.get("key"))]
        if vals:
            out.append({"key": k, "name": FACET_NAMES.get(k) or names.get(k) or k, "values": vals[:60]})
    out.sort(key=lambda f: (FACET_ORDER.index(f["key"]) if f["key"] in FACET_ORDER else 99, f["name"]))
    return out


def facet_list(client: httpx.Client | None = None) -> dict[str, str]:
    """Dateno's facet keys -> their names (asked once a week)."""
    have = _cached("facets", FACETS_KEEP)
    if have is not None:
        return have
    try:
        data = _get("/search/0.2/list_facets", [], client)
    except DatenoError:
        return {}
    items = data if isinstance(data, list) else data.get("facets") or data.get("items") or []
    out = {str(f["key"]): str(f.get("name") or f["key"]) for f in items if isinstance(f, dict) and f.get("key")}
    _store("facets", out)
    return out


def _filter(field: str, value: str) -> str:
    return f'"{field}"="{value.replace(chr(34), "")}"'


def search(q: str = "", filters: dict[str, list[str]] | None = None, country: str | None = None, offset: int = 0,
           limit: int = PAGE, sort: str = "relevance", client: httpx.Client | None = None) -> dict:
    """Search Dateno. filters: facet key -> values (each its own filter); country: ISO 2 code."""
    q = " ".join((q or "").split())[:300]
    fl: list[str] = []
    if country and re.fullmatch(r"[A-Za-z]{2}", country):
        fl.append(_filter("source.countries.id", country.upper()))
    for field, values in (filters or {}).items():
        if not re.fullmatch(r"[A-Za-z0-9_.]{1,60}", field):
            continue
        for v in values[:5]:
            if v:
                fl.append(_filter(field, str(v)[:120]))
    if not q and not fl:
        raise DatenoError("Type what you are looking for.", 422)
    limit = max(1, min(100, int(limit)))
    offset = max(0, min(10000 - limit, int(offset)))
    sort_by = {"relevance": "_score", "quality": "scores.feature_score"}.get(sort, "_score")
    params = [("q", q), ("limit", str(limit)), ("offset", str(offset)), ("facets", "true"), ("sort_by", sort_by)]
    params += [("filters", f) for f in fl]
    name = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20]
    data = _cached(name, KEEP)
    kept = data is not None
    if data is None:
        data = _get("/search/0.2/query", params, client)
        _store(name, data)
    hits = (data.get("hits") or {}) if isinstance(data, dict) else {}
    total = hits.get("total")
    total = total.get("value") if isinstance(total, dict) else total
    items = [dataset(h) for h in hits.get("hits") or [] if isinstance(h, dict)]
    return {"q": q, "filters": fl, "offset": offset, "limit": limit, "total": int(total or 0),
            "total_more": isinstance(hits.get("total"), dict) and hits["total"].get("relation") == "gte",
            "items": items, "facets": facets_from(data.get("aggregations"), facet_list(client)),
            "from_cache": kept, "quota": quota()}


def entry(entry_id: str, client: httpx.Client | None = None) -> dict:
    with _lock:
        have = _seen.get(entry_id)
    if have:
        return have
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", entry_id):
        raise DatenoError("Not a Dateno dataset id.", 422)
    data = _get(f"/search/0.1/entry/{entry_id}", [], client)
    return dataset(data if isinstance(data, dict) else {})


def similar(entry_id: str, client: httpx.Client | None = None) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", entry_id):
        raise DatenoError("Not a Dateno dataset id.", 422)
    data = _cached(f"similar-{entry_id}", KEEP)
    if data is None:
        data = _get(f"/search/0.2/similar/{entry_id}", [("limit", "10")], client)
        _store(f"similar-{entry_id}", data)
    hits = (data.get("hits") or {}).get("hits") if isinstance(data, dict) else data
    return [dataset(h) for h in hits or [] if isinstance(h, dict)]


# ----------------------------------------------------------------------------- downloading a file
def _safe(name: str, limit: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", unquote(name)).strip(" ._") or "file"
    return s[:limit]


def download(entry_id: str, n: int, client: httpx.Client | None = None) -> dict:
    """Save file n of a dataset into var/found/<title>/. Only links Dateno gave for that dataset."""
    d = entry(entry_id, client)
    f = next((x for x in d["files"] if x["n"] == n), None)
    if f is None:
        raise DatenoError("That file is not in the dataset's list.", 404)
    folder = found_dir() / _safe(f"{d['title'][:60]} {entry_id[-8:]}")
    folder.mkdir(parents=True, exist_ok=True)
    name = _safe(Path(urlparse(f["url"]).path).name or f["name"], 120)
    if f.get("format") and "." not in name:
        name += "." + f["format"].lower()
    path = folder / name
    tmp = path.with_suffix(path.suffix + ".part")
    own = client is None
    c = client or httpx.Client(timeout=httpx.Timeout(60, read=300), headers=UA, follow_redirects=True)
    got = 0
    try:
        with c.stream("GET", f["url"]) as r:
            if r.status_code >= 400:
                raise DatenoError(f"The publisher's site answered {r.status_code}; open the link in the browser instead.", 502)
            size = int(r.headers.get("content-length") or 0)
            if size > MAX_DOWNLOAD:
                raise DatenoError(f"The file is {size / 1e6:.0f} MB, over the {MAX_DOWNLOAD // 2**20} MB the app downloads; "
                                  "open the link in the browser instead.", 413)
            with open(tmp, "wb") as out:
                for chunk in r.iter_bytes(1 << 16):
                    got += len(chunk)
                    if got > MAX_DOWNLOAD:
                        raise DatenoError(f"The file is over {MAX_DOWNLOAD // 2**20} MB; open the link in the browser instead.", 413)
                    out.write(chunk)
        tmp.replace(path)
    except httpx.HTTPError as exc:
        raise DatenoError(f"Could not download the file ({type(exc).__name__}); open the link in the browser instead.") from None
    finally:
        if own:
            c.close()
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    about = folder / "about.json"
    about.write_text(json.dumps({k: d.get(k) for k in ("id", "title", "url", "publisher", "portal", "licence", "licence_url", "changed")}
                                | {"saved": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1), encoding="utf-8")
    return {"path": str(path), "folder": str(folder), "bytes": got, "name": name}


def found_files(limit: int = 40) -> list[dict]:
    """Files downloaded from Find data, newest first."""
    root = found_dir()
    if not root.exists():
        return []
    out = []
    for p in root.glob("*/*"):
        if p.is_file() and p.name != "about.json" and not p.name.endswith(".part"):
            st = p.stat()
            out.append({"name": p.name, "path": str(p), "folder": p.parent.name, "bytes": st.st_size,
                        "at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")})
    out.sort(key=lambda r: r["at"], reverse=True)
    return out[:limit]


# ----------------------------------------------------------------------------- the wish list
def _wish_path() -> Path:
    return local.user_dir() / WISHES


def wishes() -> list[dict]:
    try:
        data = json.loads(_wish_path().read_text(encoding="utf-8"))
        return [w for w in data if isinstance(w, dict) and w.get("id")] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_wishes(items: list[dict]) -> None:
    path = _wish_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def add_wish(d: dict, note: str = "") -> list[dict]:
    """Keep a dataset to turn into a source later. d is a dataset as search() gives it."""
    wid = str(d.get("id") or "")[:200]
    if not wid:
        raise DatenoError("A dataset id is needed.", 422)
    keep = {"id": wid, "title": str(d.get("title") or "")[:300], "url": d.get("url"), "publisher": d.get("publisher"),
            "portal": d.get("portal"), "countries": [c.get("name") for c in d.get("countries") or [] if isinstance(c, dict)][:6],
            "formats": list(d.get("formats") or [])[:8], "licence": d.get("licence"), "note": str(note or "")[:500],
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _lock:
        items = [w for w in wishes() if w["id"] != wid] + [keep]
        _write_wishes(items)
    return items


def remove_wish(wid: str) -> list[dict]:
    with _lock:
        items = [w for w in wishes() if w["id"] != wid]
        _write_wishes(items)
    return items
