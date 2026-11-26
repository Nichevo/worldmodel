"""Find data: search Dateno's index of open datasets, download a file, keep a wish list (dateno.py)."""

from __future__ import annotations

from fastapi import Body, HTTPException, Query

from worldmodel_api import dateno, userdata
from worldmodel_api.core import api


def _on() -> None:
    if not userdata.settings().get("find_data", True):
        raise HTTPException(403, "Find data is switched off in Settings.")


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except dateno.DatenoError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@api.get("/find/status")
def find_status():
    """Whether Find data can search (switched on, key set), the searches left, files saved and wishes kept."""
    return {"on": bool(userdata.settings().get("find_data", True)), "key_set": bool(dateno.key()), "env": dateno.KEY_ENV,
            "quota": dateno.quota(), "found_folder": str(dateno.found_dir()), "found": dateno.found_files(),
            "wishes": dateno.wishes(), "max_download_mb": dateno.MAX_DOWNLOAD // 2**20}


@api.get("/find/search")
def find_search(q: str = "", country: str | None = None, f: list[str] = Query(default=[]),
                offset: int = Query(0, ge=0, le=10000), limit: int = Query(dateno.PAGE, ge=1, le=100),
                sort: str = Query("relevance", pattern="^(relevance|quality)$")):
    """Search Dateno. country: ISO 2 code; f: facet filters as "key=value" (repeat for more)."""
    _on()
    filters: dict[str, list[str]] = {}
    for item in f[:12]:
        k, _, v = item.partition("=")
        if k and v:
            filters.setdefault(k, []).append(v)
    return _call(dateno.search, q, filters, country, offset, limit, sort)


@api.get("/find/similar/{entry_id}")
def find_similar(entry_id: str):
    """Datasets like this one."""
    _on()
    return {"items": _call(dateno.similar, entry_id)}


@api.post("/find/download")
def find_download(body: dict = Body(...)):
    """Save one of a dataset's files into var/found: {"id": dataset id, "n": file number}."""
    _on()
    try:
        n = int(body.get("n"))
    except (TypeError, ValueError):
        raise HTTPException(422, "n is the file's number") from None
    return _call(dateno.download, str(body.get("id") or ""), n)


@api.get("/find/wishes")
def find_wishes():
    return {"items": dateno.wishes()}


@api.post("/find/wishes")
def find_wish_add(body: dict = Body(...)):
    """Keep a dataset to become a source later: {"dataset": {...as search gives it}, "note": "..."}."""
    return {"items": _call(dateno.add_wish, body.get("dataset") or {}, body.get("note") or "")}


@api.delete("/find/wishes/{wid:path}")
def find_wish_remove(wid: str):
    return {"items": dateno.remove_wish(wid)}
