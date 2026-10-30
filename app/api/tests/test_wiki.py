"""Factbook texts and the Wikipedia cache, against the sample warehouse with Wikipedia mocked."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, wiki
from worldmodel_api.warehouse import SAMPLE, Warehouse

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    return TestClient(main.app)


@pytest.fixture()
def wikipedia(monkeypatch):
    """A stand-in for the Wikipedia API; returns the list of requests made."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        q = dict(request.url.params)
        if request.url.host == "upload.wikimedia.org":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        if "extracts" in q.get("prop", ""):
            title = q["titles"]
            return httpx.Response(200, json={"query": {"pages": [{
                "title": title, "extract": f"{title} is a country.", "description": "Country in Oceania",
                "fullurl": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}", "pageimage": "Flag of Somewhere.svg"}]}})
        if q.get("prop") == "imageinfo":
            pages = [{"title": t, "imageinfo": [{
                "thumburl": f"https://upload.wikimedia.org/thumb/{i}/640px-x.png", "thumbwidth": 640, "thumbheight": 320,
                "descriptionurl": f"https://commons.wikimedia.org/wiki/{t}",
                "extmetadata": {"Artist": {"value": '<a href="//x">Some One</a>'},
                                "LicenseShortName": {"value": "Public domain"}}}]}
                for i, t in enumerate(q["titles"].split("|"))]
            return httpx.Response(200, json={"query": {"pages": pages}})
        return httpx.Response(404)

    monkeypatch.setattr(wiki, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    return seen


def test_factbook_editions_and_field_history(client):
    t = client.get("/api/v1/entities/NZL/texts").json()
    assert t["edition"] == 2025 and 1990 in t["editions"]
    assert t["sections"][0]["section"] == "Introduction"
    assert any(f["field"] == "Background" for f in t["sections"][0]["fields"])
    old = client.get("/api/v1/entities/NZL/texts", params={"edition": 1990}).json()
    assert old["edition"] == 1990 and old["sections"]
    hist = client.get("/api/v1/entities/NZL/texts/history", params={"key": "Coastline"}).json()
    assert hist[0]["edition"] <= 1991 and hist[-1]["edition"] == 2025
    assert client.get("/api/v1/entities/NZL/texts", params={"source": "nope"}).json()["sections"] == []


def test_wikipedia_page_is_fetched_once_and_kept(client, wikipedia, tmp_path):
    r = client.get("/api/v1/entities/NZL/wikipedia").json()
    assert r["status"] == "ok" and r["page"]["title"] == "New Zealand"
    assert r["page"]["extract"].startswith("New Zealand is")
    img = r["page"]["images"][0]
    assert img["role"] == "photo" and img["artist"] == "Some One" and img["licence"] == "Public domain"
    assert client.get(img["src"]).content == PNG
    assert r["budget"]["used"] == 1
    made = len(wikipedia)
    again = client.get("/api/v1/entities/NZL/wikipedia").json()
    assert again["status"] == "ok" and len(wikipedia) == made  # the local copy, no new request
    assert (tmp_path / "media" / "wikipedia" / "countries" / "NZL.json").exists()
    assert client.get("/api/v1/media/wikipedia/..%2Fbudget.json").status_code == 404


def test_wikipedia_daily_limit_and_monthly_refresh(client, wikipedia, tmp_path):
    client.put("/api/v1/settings", json={"wikipedia_countries_daily": 1})
    assert client.get("/api/v1/entities/NZL/wikipedia").json()["status"] == "ok"
    over = client.get("/api/v1/entities/AUS/wikipedia").json()
    assert over["status"] == "none" and "used up" in over["message"]
    # A month-old copy is shown as stale until the next day's limit allows a refresh.
    path = tmp_path / "media" / "wikipedia" / "countries" / "NZL.json"
    page = json.loads(path.read_text())
    path.write_text(json.dumps({**page, "fetched_at": "2020-01-01T00:00:00+00:00"}))
    assert client.get("/api/v1/entities/NZL/wikipedia").json()["status"] == "stale"
    client.put("/api/v1/settings", json={"wikipedia_countries_daily": 0})
    assert "off" in client.get("/api/v1/entities/AUS/wikipedia").json()["message"]


def test_wikipedia_background_takes_half_the_limit(client, wikipedia):
    client.put("/api/v1/settings", json={"wikipedia_countries_daily": 4})
    client.post("/api/v1/history", json={"kind": "page", "title": "Chile", "entity": "CHL"})
    bg = wiki.Background(main.wiki_targets)
    assert bg.step() and bg.step() and not bg.step()  # 2 of 4
    first = [r.url.params["titles"] for r in wikipedia if "extracts" in r.url.params.get("prop", "")]
    assert first[0] == "Chile"  # opened countries first, then by population
    assert client.get("/api/v1/wikipedia/status").json()["stored"] == 2
    row = next(d for d in client.get("/api/v1/datasets").json() if d["source_id"] == "wikipedia")
    assert row["on_demand"]["stored"] == 2 and row["on_demand"]["budget"]["used"] == 2
    client.put("/api/v1/settings", json={"wikipedia_background": False, "wikipedia_countries_daily": 40})
    assert not bg.step()
    # Opened pages still have the rest of the day's limit.
    assert client.get("/api/v1/entities/NZL/wikipedia").json()["status"] == "ok"


def test_groups_without_an_article_are_not_fetched(client, wikipedia):
    r = client.get("/api/v1/entities/income-high/wikipedia").json()
    assert r["status"] == "none" and not wikipedia


def test_a_failed_fetch_is_not_retried_the_same_day(client, monkeypatch):
    calls = []
    monkeypatch.setattr(wiki, "_client", httpx.Client(transport=httpx.MockTransport(
        lambda r: calls.append(r) or httpx.Response(503))))
    first = client.get("/api/v1/entities/AUS/wikipedia").json()
    assert first["status"] == "none" and "tried again tomorrow" in first["message"] and first["budget"]["used"] == 1
    second = client.get("/api/v1/entities/AUS/wikipedia").json()
    assert len(calls) == 1 and second["budget"]["used"] == 1
