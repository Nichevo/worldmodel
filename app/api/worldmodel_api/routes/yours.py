"""Your layouts, settings and history, local AI, highlights and API access keys."""

from __future__ import annotations

import json

from fastapi import Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
import httpx

from worldmodel_contract import local
from worldmodel_api import ai, highlights, layouts, userdata
from worldmodel_api import public as public_api
from worldmodel_api.core import api


# ----------------------------------------------------------------------------- saved layouts
def _layout_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 60 or any(c in name for c in "\r\n\t"):
        raise HTTPException(422, "a layout name is 1 to 60 characters on one line")
    return name


@api.get("/layouts")
def list_layouts():
    return layouts.all_layouts()


@api.put("/layouts/{name}")
def save_layout(name: str, query: str = Body(..., embed=True, max_length=4000)):
    """Save (or overwrite) a named layout: the map page's URL query."""
    try:
        return layouts.save(_layout_name(name), query.lstrip("?"))
    except ValueError as e:
        raise HTTPException(409, str(e))


@api.delete("/layouts/{name}")
def delete_layout(name: str):
    if not layouts.delete(_layout_name(name)):
        raise HTTPException(404, f"no layout {name}")
    return {"deleted": name}


# ----------------------------------------------------------------------------- settings, history
@api.get("/settings")
def get_settings():
    return {"settings": userdata.settings(), "defaults": local.SETTINGS}


@api.put("/settings")
def put_settings(patch: dict = Body(...)):
    """Change some settings; unknown keys are ignored and numbers held to their ranges."""
    saved = userdata.save_settings(patch)
    from worldmodel_api import live

    live.forget_settings()  # live layers and collectors see the change at once
    return {"settings": saved, "defaults": local.SETTINGS}


@api.get("/history")
def get_history(q: str | None = None, kind: str | None = None, starred: bool = False,
                since: str | None = Query(None, description="YYYY-MM-DD"), until: str | None = None,
                limit: int = Query(500, le=5000)):
    """What was opened and looked at, newest first."""
    return userdata.history(q, kind, starred, since, until, limit)


@api.post("/history")
def post_history(entry: dict = Body(...)):
    """Log one thing opened: {kind, title, url?, entity?, indicator?, detail?}. Ignored while paused."""
    try:
        return {"entry": userdata.add_history(entry)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.patch("/history/{entry_id}")
def patch_history(entry_id: str, star: bool | None = Body(None), note: str | None = Body(None, max_length=2000)):
    """Star an entry (a bookmark) or write a note on it."""
    try:
        return userdata.mark(entry_id, star, note)
    except KeyError:
        raise HTTPException(404, f"no history entry {entry_id}")


@api.delete("/history")
def delete_history(keep_starred: bool = True, before: str | None = Query(None, description="YYYY-MM-DD")):
    """Clear the history (or the part before a date), keeping starred entries unless told not to."""
    return {"deleted": userdata.clear_history(keep_starred, before)}


@api.get("/history/interest")
def history_interest(limit: int = 50):
    """Countries by how often and how recently they were opened; on-demand fetches go in this order."""
    return userdata.entity_interest(limit)


# ----------------------------------------------------------------------------- local AI
@api.get("/ai/status")
def ai_status():
    """Is Ollama reachable, which models it has, the default model, and the web search engine with its usage."""
    return ai.status()


@api.post("/ai/search")
def ai_search(question: str = Body(..., max_length=20_000), model: str | None = Body(None),
              query: str | None = Body(None, max_length=300)):
    """One web search for a question: the model writes the query (unless one is given), the engine in
    Settings answers. Brave searches count against the limits in Settings."""
    s = userdata.settings()
    ready, why = ai.search_ready(s)
    if not ready:
        raise HTTPException(409, why)
    q = query
    if not q:
        try:
            q = ai.write_query(question, model or ai.default_model(s, ai.models(s)) or "", s)
        except (httpx.HTTPError, ValueError):  # the model could not write a query: search the question itself
            q = question[:200]
    try:
        results = ai.web_search(q, s)
    except ai.SearchLimit as e:
        raise HTTPException(409, str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{s['ai_search_engine']} search failed: HTTP {e.response.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{s['ai_search_engine']} search failed: {e}")
    return {"query": q, "results": results, "engine": s["ai_search_engine"], "usage": ai.search_usage(s)}


@api.post("/ai/ask")
def ai_ask(req: dict = Body(...)):
    """Ask a model in Ollama; streams one JSON object a line: start, token {text}, done {answer} or error {message}.
    Body: question, context [{label, text}], model?, web? {query, results}, title?, page?, entity?, indicator?, group?"""
    if not userdata.settings()["ai_enabled"]:
        raise HTTPException(409, "Local AI is switched off (Settings: Local AI).")

    def lines():
        for event in ai.ask(req):
            yield json.dumps(event, ensure_ascii=False) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@api.get("/ai/answers")
def ai_answers(q: str | None = None, entity: str | None = None, indicator: str | None = None, model: str | None = None,
               limit: int = Query(200, le=5000)):
    """Saved answers, newest first."""
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for a in reversed(ai.answers()):
        if entity and a.get("entity") != entity or indicator and a.get("indicator") != indicator or model and a["model"] != model:
            continue
        hay = f"{a['question']} {a['answer']} {a.get('title', '')} {a.get('note', '')} {' '.join(a.get('tags', []))}".lower()
        if all(w in hay for w in words):
            out.append(a)
        if len(out) >= limit:
            break
    return out


@api.patch("/ai/answers/{answer_id}")
def ai_patch_answer(answer_id: str, patch: dict = Body(...)):
    """Rate an answer (rating 1, -1 or 0), or set its tags or note."""
    try:
        return ai.update_answer(answer_id, patch)
    except KeyError:
        raise HTTPException(404, f"no answer {answer_id}")


@api.delete("/ai/answers/{answer_id}")
def ai_delete_answer(answer_id: str):
    if not ai.delete_answer(answer_id):
        raise HTTPException(404, f"no answer {answer_id}")
    return {"deleted": answer_id}


@api.get("/ai/stats")
def ai_stats():
    """Your own AI use: per model questions, tokens, speed, time to first word and ratings; web searches."""
    return ai.stats()


# ----------------------------------------------------------------------------- highlights
@api.get("/highlights")
def get_highlights(q: str | None = None, kind: str | None = None, tag: str | None = None, entity: str | None = None):
    """Everything kept, newest first, with the tags in use."""
    return {"items": highlights.search(q, kind, tag, entity), "tags": highlights.tags()}


@api.post("/highlights")
def post_highlight(item: dict = Body(...)):
    """Keep something: {kind: text|chart|table|answer, title?, text?, page_url?, page_title?, entities?, indicator?,
    query? (chart settings), table? {columns, rows, unit?}, picture? (PNG data URL), answer_id?, question?, model?,
    sources?, tags?, note?}."""
    try:
        return highlights.add(item)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.patch("/highlights/{item_id}")
def patch_highlight(item_id: str, patch: dict = Body(...)):
    try:
        return highlights.update(item_id, patch)
    except KeyError:
        raise HTTPException(404, f"no highlight {item_id}")


@api.delete("/highlights/{item_id}")
def delete_highlight(item_id: str):
    if not highlights.delete(item_id):
        raise HTTPException(404, f"no highlight {item_id}")
    return {"deleted": item_id}


@api.get("/highlights/{item_id}/picture")
def highlight_picture(item_id: str):
    p = highlights.picture_path(item_id)
    if not p:
        raise HTTPException(404, "no picture")
    return FileResponse(p, media_type="image/png")


@api.get("/highlights-export.md")
def export_highlights(q: str | None = None, kind: str | None = None, tag: str | None = None, entity: str | None = None,
                      base: str = Query("", max_length=200)):
    """The highlights shown (same filters) as one Markdown file."""
    text = highlights.markdown(highlights.search(q, kind, tag, entity), base.rstrip("/"))
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="highlights.md"'})


# ----------------------------------------------------------------------------- Settings > API access
@api.get("/api-access")
def api_access(request: Request):
    """The public API's switch, keys (never the keys themselves) and recent calls."""
    s = userdata.settings()
    return {"on": bool(s.get("api_public_on")), "daily_limit": s.get("api_daily_limit"), "keys": public_api.key_list(),
            "recent": public_api.recent(40), "local": public_api.is_local(request), "mcp_command": public_api.mcp_command()}


@api.post("/api-access/keys")
def api_key_make(body: dict = Body(..., examples=[{"name": "Laptop"}])):
    """Make a key for another PC; the key is in this answer only, so copy it now."""
    return public_api.make_key(body.get("name", ""), body.get("daily_limit"))


@api.delete("/api-access/keys/{key_id}")
def api_key_revoke(key_id: str):
    if not public_api.revoke_key(key_id):
        raise HTTPException(404, "no such key")
    return {"ok": True}
