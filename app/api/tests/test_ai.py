"""Local AI and highlights, against a fake Ollama and a fake Brave (no network)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import ai, main
from worldmodel_api.warehouse import SAMPLE, Warehouse

CALLS: list[dict] = []


def fake(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    CALLS.append({"url": url, "body": json.loads(request.content) if request.content else None})
    if url.endswith("/api/tags"):
        return httpx.Response(200, json={"models": [
            {"name": "small:8b", "size": 5e9, "details": {"parameter_size": "8B", "family": "qwen3"}},
            {"name": "big:70b", "size": 4e10, "details": {"parameter_size": "70B", "family": "llama"}}]})
    if url.endswith("/api/show"):
        model = json.loads(request.content)["model"]
        return httpx.Response(200, json={"capabilities": ["completion", "vision"] if model == "big:70b" else ["completion"]})
    if url.endswith("/api/version"):
        return httpx.Response(200, json={"version": "0.12.0"})
    if url.endswith("/api/chat"):
        body = json.loads(request.content)
        if not body.get("stream"):
            return httpx.Response(200, json={"message": {"content": "New Zealand fertility 2024\n"}, "done": True})
        lines = [{"message": {"content": "<think>hmm</think>"}, "done": False},
                 {"message": {"content": "Fertility fell "}, "done": False},
                 {"message": {"content": "to 1.6 [1]."}, "done": False},
                 {"message": {"content": ""}, "done": True, "prompt_eval_count": 120, "eval_count": 40,
                  "eval_duration": 2_000_000_000, "load_duration": 500_000_000}]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
    if "search.brave.com" in url:
        assert request.headers["X-Subscription-Token"] == "test-key"
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Births <strong>2024</strong>", "url": "https://stats.govt.nz/x", "description": "TFR 1.56"}]}})
    return httpx.Response(404, json={"error": "not found"})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(ai, "_client", lambda timeout=30: httpx.Client(transport=httpx.MockTransport(fake)))
    CALLS.clear()
    main.warehouse = Warehouse(str(SAMPLE))
    return TestClient(main.app)


def test_status_lists_models(client):
    st = client.get("/api/v1/ai/status").json()
    assert st["ollama"]["ok"] and st["ollama"]["version"] == "0.12.0"
    assert [m["name"] for m in st["models"]] == ["big:70b", "small:8b"] and st["default_model"] == "big:70b"
    assert [m["vision"] for m in st["models"]] == [True, False]
    assert st["search"]["ready"] and st["search"]["usage"]["today"] == 0


def test_search_then_ask_streams_and_saves(client):
    s = client.post("/api/v1/ai/search", json={"question": "Why is NZ fertility falling?", "model": "small:8b"}).json()
    assert s["query"] == "New Zealand fertility 2024" and s["results"][0]["title"] == "Births 2024"
    assert s["usage"]["today"] == 1
    with client.stream("POST", "/api/v1/ai/ask", json={
            "question": "Why is NZ fertility falling?", "model": "small:8b", "web": s, "title": "Fertility",
            "page": "/entity/NZL", "entity": "NZL", "indicator": "tfr",
            "context": [{"label": "Data", "text": "year,NZL\n2023,1.56"}, {"label": "Empty", "text": " "}]}) as r:
        events = [json.loads(line) for line in r.iter_lines() if line]
    assert [e["type"] for e in events][0] == "start" and events[-1]["type"] == "done"
    rec = events[-1]["answer"]
    assert rec["answer"] == "Fertility fell to 1.6 [1]."
    assert rec["stats"]["tokens_per_s"] == 20.0 and rec["stats"]["prompt_tokens"] == 120 and rec["stats"]["load_s"] == 0.5
    prompt = CALLS[-1]["body"]["messages"][1]["content"]
    assert "## Data\nyear,NZL" in prompt and "[1] Births 2024 (https://stats.govt.nz/x)" in prompt and "Empty" not in prompt
    assert client.patch(f"/api/v1/ai/answers/{rec['id']}", json={"rating": 1, "tags": "nz, Fertility"}).json()["tags"] == ["nz", "fertility"]
    stats = client.get("/api/v1/ai/stats").json()
    assert stats["models"][0] == {"model": "small:8b", "questions": 1, "prompt_tokens": 120, "answer_tokens": 40,
                                  "tokens_per_s": 20.0, "first_token_s": stats["models"][0]["first_token_s"],
                                  "thumbs_up": 1, "thumbs_down": 0, "with_web": 1}
    assert client.get("/api/v1/ai/answers", params={"entity": "NZL"}).json()[0]["id"] == rec["id"]
    hist = client.get("/api/v1/history", params={"kind": "ai"}).json()
    assert hist and hist[0]["url"] == f"/ai?answer={rec['id']}"


def test_brave_daily_limit(client):
    client.put("/api/v1/settings", json={"brave_daily_limit": 1})
    assert client.post("/api/v1/ai/search", json={"question": "a", "query": "a"}).status_code == 200
    r = client.post("/api/v1/ai/search", json={"question": "b", "query": "b"})
    assert r.status_code == 409 and "limit" in r.json()["detail"]
    client.put("/api/v1/settings", json={"brave_daily_limit": 0, "brave_free_monthly": 0, "brave_price_per_1000": 5})
    u = client.post("/api/v1/ai/search", json={"question": "c", "query": "c"}).json()["usage"]
    assert u["month"] == 2 and u["daily_limit"] is None and u["estimated_cost_usd"] == 0.01


def test_ollama_down_is_explained(client, monkeypatch):
    def down(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(ai, "_client", lambda timeout=30: httpx.Client(transport=httpx.MockTransport(down)))
    st = client.get("/api/v1/ai/status").json()
    assert not st["ollama"]["ok"] and "Is it running?" in st["ollama"]["error"]
    with client.stream("POST", "/api/v1/ai/ask", json={"question": "hi", "model": "x"}) as r:
        events = [json.loads(line) for line in r.iter_lines() if line]
    assert events[-1]["type"] == "error" and "Could not reach Ollama" in events[-1]["message"]


def test_highlights(client):
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    a = client.post("/api/v1/highlights", json={"kind": "text", "text": "Fertility has fallen below replacement.",
                                                "page_url": "/entity/NZL", "page_title": "New Zealand", "entities": ["NZL"],
                                                "tags": ["fertility"]}).json()
    b = client.post("/api/v1/highlights", json={"kind": "chart", "title": "TFR, NZ and Australia", "query": "l=1&p=chart.tfr&s=NZL,AUS",
                                                "entities": ["NZL", "AUS"], "indicator": "tfr", "picture": png,
                                                "table": {"columns": ["Year", "NZL"], "rows": [[2023, 1.56]]}}).json()
    assert client.post("/api/v1/highlights", json={"kind": "chart"}).status_code == 422
    assert client.get(f"/api/v1/highlights/{b['id']}/picture").content.startswith(b"\x89PNG")
    got = client.get("/api/v1/highlights", params={"entity": "NZL"}).json()
    assert [x["id"] for x in got["items"]] == [b["id"], a["id"]] and got["tags"] == [{"tag": "fertility", "count": 1}]
    assert [x["id"] for x in client.get("/api/v1/highlights", params={"q": "replacement"}).json()["items"]] == [a["id"]]
    client.patch(f"/api/v1/highlights/{b['id']}", json={"note": "Compare with Japan", "tags": "fertility,charts"})
    md = client.get("/api/v1/highlights-export.md", params={"base": "http://pc:3030"}).text
    assert "> Fertility has fallen below replacement." in md and "[Open the chart](http://pc:3030/?l=1&p=chart.tfr&s=NZL,AUS)" in md
    assert "| 2023 | 1.56 |" in md and "**Note:** Compare with Japan" in md
    assert client.delete(f"/api/v1/highlights/{b['id']}").status_code == 200
    assert client.get(f"/api/v1/highlights/{b['id']}/picture").status_code == 404


def test_chart_picture_goes_only_to_models_that_see(client):
    ai._SEES.clear()
    pic = "data:image/png;base64,iVBORw0KGgo="
    for model, sent in (("big:70b", True), ("small:8b", False)):
        with client.stream("POST", "/api/v1/ai/ask", json={"question": "What does this chart show?", "model": model,
                                                            "images": [pic]}) as r:
            events = [json.loads(line) for line in r.iter_lines() if line]
        user = CALLS[-1]["body"]["messages"][1]
        assert ("images" in user) is sent
        if sent:
            assert user["images"] == ["iVBORw0KGgo="] and events[-1]["answer"]["picture"] == "sent"
        else:
            assert "cannot see pictures" in events[-1]["answer"]["picture"]
