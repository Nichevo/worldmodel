"""Ask your local AI: questions about what is on screen, answered by a model in Ollama.

The app's server talks to Ollama (Settings: Ollama address), so a page opened from
another PC on the network can ask too. A question goes with the context the page
attached (the chart's figures as a table, descriptions, events, a highlighted
passage), each part ticked or unticked by the user. With "Search the web" ticked,
the model first writes a search query, the search engine in Settings answers it
(Brave Search with BRAVE_API_KEY, which can cost money past its monthly credit, or
SearXNG running locally, which is free), and the results go in as numbered sources
the answer cites as [1], [2] ...

Every answer is kept in the user folder (ai_answers.json) with its question,
context, model, sources and Ollama's own timings (tokens in and out, tokens a
second, load time), plus the time to the first word measured here; the AI notes
page lists them and its Statistics tab adds them up. Brave searches are counted
per day (ai_search_usage.json) and held to the daily and monthly limits in Settings.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterator

import httpx

from worldmodel_api import userdata

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
SYSTEM = (
    "You are a careful analyst inside a personal data app about countries. Answer the user's question using the "
    "context they attached (figures from the app's data, with units, years and sources) and, if given, the "
    "numbered web results. Rules: use figures from the context rather than from memory, and say which year and "
    "source a figure comes from; mark projections as projections; when the context does not answer the question, "
    "say so plainly before adding what you know in general; cite web results by their number in square brackets, "
    "like [2], and only for what they actually say; keep the answer short and clear, in plain English, with short "
    "paragraphs or a short list."
)
QUERY_PROMPT = ("Write one web search query (at most 12 words) that would find up-to-date facts to answer this "
                "question. Reply with the query only, no quotes.\n\nQuestion: {q}")
_lock = threading.Lock()
MAX_ANSWERS = 5000


class SearchLimit(Exception):
    """A Brave search would go past a limit set in Settings."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client(timeout: float = 30) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=5), follow_redirects=True)


# ----------------------------------------------------------------------------- Ollama
def ollama_url(settings: dict | None = None) -> str:
    s = settings or userdata.settings()
    return (s.get("ollama_url") or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/").removesuffix("/v1")


def models(settings: dict | None = None) -> list[dict]:
    """The models installed in Ollama, largest first: name, size (bytes), parameters, family, quantisation."""
    with _client(5) as c:
        r = c.get(f"{ollama_url(settings)}/api/tags")
        r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        d = m.get("details") or {}
        out.append({"name": m.get("name") or m.get("model"), "size": m.get("size"), "parameters": d.get("parameter_size"),
                    "family": d.get("family"), "quantization": d.get("quantization_level"), "modified_at": m.get("modified_at")})
    return sorted(out, key=lambda m: -(m["size"] or 0))


def default_model(settings: dict, installed: list[dict]) -> str | None:
    names = [m["name"] for m in installed]
    if settings.get("ai_model") in names:
        return settings["ai_model"]
    return names[0] if names else (settings.get("ai_model") or None)


def _options(settings: dict, **extra) -> dict:
    return {"temperature": settings["ai_temperature"], "num_ctx": settings["ai_context_tokens"], **extra}


def write_query(question: str, model: str, settings: dict) -> str:
    """The model's search query for a question (the question itself if the model gives nothing usable)."""
    try:
        with _client(120) as c:
            r = c.post(f"{ollama_url(settings)}/api/chat", json={
                "model": model, "stream": False,
                "messages": [{"role": "user", "content": QUERY_PROMPT.format(q=question[:2000])}],
                "options": _options(settings, temperature=0, num_predict=60)})
            r.raise_for_status()
            text = (r.json().get("message") or {}).get("content") or ""
    except httpx.HTTPError:
        text = ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip().splitlines()
    q = text[0].strip().strip('"').strip("'") if text else ""
    return q[:200] if 2 <= len(q) else question[:200]


# ----------------------------------------------------------------------------- web search
def _usage() -> dict:
    data = userdata._read_json("ai_search_usage.json", {})
    return data if isinstance(data, dict) else {}


def search_usage(settings: dict | None = None) -> dict:
    """Brave searches today and this month (UTC), the limits, and the estimated cost past the free credit."""
    s = settings or userdata.settings()
    days = _usage().get("brave", {})
    today, month = _now().strftime("%Y-%m-%d"), _now().strftime("%Y-%m")
    used_today = int(days.get(today, 0))
    used_month = sum(int(v) for d, v in days.items() if d.startswith(month))
    over = max(0, used_month - s["brave_free_monthly"])
    return {"engine": s["ai_search_engine"], "today": used_today, "month": used_month,
            "daily_limit": s["brave_daily_limit"] or None, "monthly_limit": s["brave_monthly_limit"] or None,
            "free_monthly": s["brave_free_monthly"], "price_per_1000": s["brave_price_per_1000"],
            "estimated_cost_usd": round(over * s["brave_price_per_1000"] / 1000, 2),
            "by_day": {d: v for d, v in sorted(days.items())[-62:]}}


def _count_brave() -> None:
    with _lock:
        data = _usage()
        days = data.setdefault("brave", {})
        today = _now().strftime("%Y-%m-%d")
        days[today] = int(days.get(today, 0)) + 1
        userdata._write_json("ai_search_usage.json", data)


def search_ready(settings: dict) -> tuple[bool, str]:
    engine = settings["ai_search_engine"]
    if engine == "off":
        return False, "Web search is off (Settings: Local AI)."
    if engine == "brave" and not os.environ.get("BRAVE_API_KEY"):
        return False, "No Brave key: add BRAVE_API_KEY=... to the .env file in the worldmodel folder and restart."
    if engine == "brave":
        u = search_usage(settings)
        if u["daily_limit"] and u["today"] >= u["daily_limit"]:
            return False, f"Today's Brave limit is used up ({u['today']} of {u['daily_limit']}; Settings: Local AI)."
        if u["monthly_limit"] and u["month"] >= u["monthly_limit"]:
            return False, f"This month's Brave limit is used up ({u['month']} of {u['monthly_limit']}; Settings: Local AI)."
    return True, ""


def web_search(query: str, settings: dict) -> list[dict]:
    """Results (title, url, snippet) from the engine in Settings. Raises SearchLimit or httpx errors."""
    ok, why = search_ready(settings)
    if not ok:
        raise SearchLimit(why)
    n = settings["ai_search_results"]
    if settings["ai_search_engine"] == "brave":
        with _client(20) as c:
            r = c.get(BRAVE_URL, params={"q": query, "count": n},
                      headers={"Accept": "application/json", "X-Subscription-Token": os.environ["BRAVE_API_KEY"]})
        if r.status_code < 500:
            _count_brave()  # Brave counts every request it answers
        r.raise_for_status()
        items = (r.json().get("web") or {}).get("results") or []
        return [{"title": _plain(i.get("title")), "url": i.get("url"), "snippet": _plain(i.get("description"))}
                for i in items[:n] if i.get("url")]
    with _client(20) as c:
        r = c.get(f"{settings['searxng_url']}/search", params={"q": query, "format": "json"})
        if r.status_code == 403:
            raise SearchLimit("SearXNG refused JSON answers: add 'json' under search: formats: in its settings.yml.")
        r.raise_for_status()
    items = r.json().get("results") or []
    return [{"title": _plain(i.get("title")), "url": i.get("url"), "snippet": _plain(i.get("content"))}
            for i in items[:n] if i.get("url")]


def _plain(text) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&")[:600]


# ----------------------------------------------------------------------------- answers
def answers() -> list[dict]:
    items = userdata._read_json("ai_answers.json", [])
    return items if isinstance(items, list) else []


def _save(rec: dict) -> None:
    with _lock:
        items = [x for x in answers() if x["id"] != rec["id"]] + [rec]
        userdata._write_json("ai_answers.json", items[-MAX_ANSWERS:])


def update_answer(answer_id: str, patch: dict) -> dict:
    with _lock:
        items = answers()
        rec = next((x for x in items if x["id"] == answer_id), None)
        if rec is None:
            raise KeyError(answer_id)
        if "rating" in patch:
            rec["rating"] = patch["rating"] if patch["rating"] in (-1, 0, 1) else rec.get("rating", 0)
        if "note" in patch:
            rec["note"] = str(patch["note"] or "")[:5000]
        if "tags" in patch:
            rec["tags"] = clean_tags(patch["tags"])
        userdata._write_json("ai_answers.json", items)
        return rec


def delete_answer(answer_id: str) -> bool:
    with _lock:
        items = answers()
        kept = [x for x in items if x["id"] != answer_id]
        if len(kept) == len(items):
            return False
        userdata._write_json("ai_answers.json", kept)
        return True


def clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for t in tags or []:
        t = " ".join(str(t).split()).lower()[:40]
        if t and t not in out:
            out.append(t)
    return out[:20]


def _prompt(question: str, context: list[dict], web: dict | None) -> str:
    parts = []
    for c in context:
        text = str(c.get("text") or "").strip()
        if text:
            parts.append(f"## {str(c.get('label') or 'Context')[:120]}\n{text[:200_000]}")
    if web and web.get("results"):
        lines = [f"[{i}] {r['title']} ({r['url']})\n{r['snippet']}" for i, r in enumerate(web["results"], 1)]
        parts.append(f"## Web results for \"{web.get('query', '')}\"\n" + "\n\n".join(lines))
    head = "\n\n".join(parts)
    return (f"{head}\n\n## Question\n{question}" if head else question)


def ask(req: dict, settings: dict | None = None) -> Iterator[dict]:
    """Stream one answer: events start, token (text), done (the saved record) or error.

    req: question, context [{label, text}], model, web {query, results} (from /ai/search),
    title, page, entity, indicator, group (shared by side-by-side answers)."""
    s = settings or userdata.settings()
    question = str(req.get("question") or "").strip()[:20_000]
    if not question:
        yield {"type": "error", "message": "Type a question first."}
        return
    model = req.get("model") or s.get("ai_model")
    if not model:
        try:
            model = default_model(s, models(s))
        except httpx.HTTPError as exc:
            yield {"type": "error", "message": _ollama_problem(exc, s)}
            return
    if not model:
        yield {"type": "error", "message": "No model installed in Ollama. Install one, for example: ollama pull qwen3:32b"}
        return
    context = [{"label": str(c.get("label") or "")[:120], "text": str(c.get("text") or "")} for c in req.get("context") or []
               if isinstance(c, dict) and str(c.get("text") or "").strip()]
    web = req.get("web") if isinstance(req.get("web"), dict) else None
    rec = {"id": secrets.token_hex(6), "created_at": userdata.now(), "question": question, "context": context,
           "model": model, "temperature": s["ai_temperature"], "web": web, "answer": "", "stats": {},
           "title": str(req.get("title") or "")[:200], "page": str(req.get("page") or "")[:2000],
           "entity": str(req.get("entity") or "")[:60] or None, "indicator": str(req.get("indicator") or "")[:80] or None,
           "group": str(req.get("group") or "")[:20] or None, "rating": 0, "tags": [], "note": ""}
    yield {"type": "start", "id": rec["id"], "model": model}
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(question, context, web)}]
    started, first, final = time.monotonic(), None, {}
    try:
        with _client(600) as c, c.stream("POST", f"{ollama_url(s)}/api/chat", json={
                "model": model, "messages": messages, "stream": True, "options": _options(s)}) as r:
            if r.status_code >= 400:
                r.read()
                raise httpx.HTTPStatusError(_ollama_error_text(r), request=r.request, response=r)
            for line in r.iter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                msg = chunk.get("message") or {}
                if msg.get("thinking") and first is None:
                    yield {"type": "thinking"}
                text = msg.get("content") or ""
                if text:
                    if first is None:
                        first = time.monotonic() - started
                    rec["answer"] += text
                    yield {"type": "token", "text": text}
                if chunk.get("done"):
                    final = chunk
    except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as exc:
        msg = _ollama_problem(exc, s)
        if rec["answer"]:
            rec["stats"] = {"error": msg}
            _save(rec)
        yield {"type": "error", "message": msg, **({"id": rec["id"]} if rec["answer"] else {})}
        return
    ns = 1e9
    ev, evd = final.get("eval_count"), final.get("eval_duration")
    rec["stats"] = {
        "prompt_tokens": final.get("prompt_eval_count"), "answer_tokens": ev,
        "tokens_per_s": round(ev / (evd / ns), 1) if ev and evd else None,
        "first_token_s": round(first, 2) if first is not None else None,
        "load_s": round(final["load_duration"] / ns, 2) if final.get("load_duration") else None,
        "total_s": round(time.monotonic() - started, 2),
    }
    rec["answer"] = strip_thinking(rec["answer"])
    _save(rec)
    if rec["page"] or rec["title"]:
        try:
            userdata.add_history({"kind": "ai", "title": f"Asked {model}: {question[:200]}", "url": "/ai?answer=" + rec["id"],
                                  "entity": rec["entity"], "indicator": rec["indicator"]})
        except ValueError:
            pass
    yield {"type": "done", "answer": rec}


def strip_thinking(text: str) -> str:
    """The answer without a reasoning model's <think> ... </think> part."""
    return re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S).strip()


def _ollama_error_text(r: httpx.Response) -> str:
    try:
        return r.json().get("error") or r.text
    except ValueError:
        return r.text[:300]


def _ollama_problem(exc: Exception, s: dict) -> str:
    if isinstance(exc, httpx.ConnectError):
        return (f"Could not reach Ollama at {ollama_url(s)}. Is it running? Start it (the Ollama app, or `ollama serve`), "
                "or change the address in Settings: Local AI.")
    if isinstance(exc, httpx.TimeoutException):
        return "Ollama took too long to answer; a large model may still be loading. Try again in a minute."
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Ollama said: {exc.args[0] if exc.args else exc.response.status_code}"
    return f"Ollama: {exc}"


def status(settings: dict | None = None) -> dict:
    s = settings or userdata.settings()
    out = {"enabled": s["ai_enabled"], "ollama": {"url": ollama_url(s), "ok": False, "error": None, "version": None},
           "models": [], "default_model": None, "compare_model": s["ai_model_compare"] or None}
    try:
        out["models"] = models(s)
        out["ollama"]["ok"] = True
        with _client(5) as c:
            v = c.get(f"{ollama_url(s)}/api/version")
            out["ollama"]["version"] = v.json().get("version") if v.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as exc:
        out["ollama"]["error"] = _ollama_problem(exc, s)
    out["default_model"] = default_model(s, out["models"])
    ready, why = search_ready(s)
    out["search"] = {"engine": s["ai_search_engine"], "ready": ready, "why": why or None,
                     "brave_key": bool(os.environ.get("BRAVE_API_KEY")), "usage": search_usage(s)}
    return out


def stats() -> dict:
    """Totals per model: questions, tokens in and out, typical speed and time to the first word, ratings."""
    per: dict[str, dict] = defaultdict(lambda: {"questions": 0, "prompt_tokens": 0, "answer_tokens": 0, "speeds": [],
                                                "firsts": [], "up": 0, "down": 0, "searched": 0})
    for a in answers():
        m = per[a["model"]]
        st = a.get("stats") or {}
        m["questions"] += 1
        m["prompt_tokens"] += st.get("prompt_tokens") or 0
        m["answer_tokens"] += st.get("answer_tokens") or 0
        if st.get("tokens_per_s"):
            m["speeds"].append(st["tokens_per_s"])
        if st.get("first_token_s") is not None:
            m["firsts"].append(st["first_token_s"])
        m["up"] += a.get("rating") == 1
        m["down"] += a.get("rating") == -1
        m["searched"] += bool((a.get("web") or {}).get("results"))

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None

    rows = [{"model": k, "questions": v["questions"], "prompt_tokens": v["prompt_tokens"], "answer_tokens": v["answer_tokens"],
             "tokens_per_s": median(v["speeds"]), "first_token_s": median(v["firsts"]), "thumbs_up": v["up"],
             "thumbs_down": v["down"], "with_web": v["searched"]} for k, v in per.items()]
    by_day: dict[str, int] = defaultdict(int)
    for a in answers():
        by_day[a["created_at"][:10]] += 1
    return {"models": sorted(rows, key=lambda r: -r["questions"]), "questions_by_day": dict(sorted(by_day.items())[-90:]),
            "search": search_usage()}
