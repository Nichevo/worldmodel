"""The Briefing, the map's events and news watch words."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import briefing, main, news
from worldmodel_api.warehouse import SAMPLE, Warehouse

WORDS = ["coup", "protest", "protests", "martial law", "ceasefire", "earthquake"]


def _news(key, day, headline, ents, outlet="RNZ", score=0.4, source="feeds"):
    return {"key": key, "kind": "news", "source": source, "outlet": outlet, "date": day, "headline": headline,
            "detail": "", "url": f"https://x/{key}", "entities": ents, "score": score, "tone": "bad"}


def test_matched_words_whole_words_and_phrases():
    assert briefing.matched("Army declares MARTIAL   law after coup attempt", WORDS) == ["coup", "martial law"]
    assert briefing.matched("Coupon prices", WORDS) == []
    assert briefing.matched("Protests spread", WORDS) == ["protests"]


def test_watch_hits_merge_outlets_place_and_confirm():
    items = [
        _news("a", "2026-11-05", "Coup in Niamey as soldiers seize power", ["NER"], "BBC World", 0.5),
        _news("b", "2026-11-05", "Soldiers stage coup in Niger", ["NER"], "The Guardian, world"),
        _news("c", "2026-11-04", "Protest in Suva over prices", ["FJI"], "RNZ"),
        _news("d", "2026-10-01", "Old coup news", ["NER"], "RNZ"),  # before the window
        _news("e", "2026-11-05", "A coup somewhere", [], "RNZ"),  # no country
        _news("f", "2026-11-05", "Coup talk", ["NER"], "GDELT", source="gdelt"),  # counts, not reports
    ]
    cities = {"NER": [("Niamey", 13.5, 2.1)], "FJI": [("Suva", -18.1, 178.4)]}
    confirm = [{"entity_id": "NER", "kind": "coup", "start_date": date(2026, 11, 6), "title": "2026 Niger coup"}]
    hits = briefing.watch_hits(items, WORDS, "2026-11-01", cities=cities, confirm=confirm)
    assert [h["entity_id"] for h in hits] == ["NER", "FJI"]
    ner, fji = hits
    assert ner["n_outlets"] == 2 and ner["headline"].startswith("Coup in Niamey") and ner["place"]["name"] == "Niamey"
    assert ner["confirmed"] and ner["confirmed_by"] == "2026 Niger coup" and ner["group"] == "conflict"
    assert fji["place"]["name"] == "Suva" and not fji["confirmed"]
    two = briefing.watch_hits(items, WORDS, "2026-11-01", min_outlets=2)
    assert [h["entity_id"] for h in two] == ["NER"]


def test_crisiswatch_cards_changed_only_key_countries_first():
    rows = [{"entity_id": "AAA", "name": "Aland", "subkind": "deteriorated", "detail": "x"},
            {"entity_id": "NZL", "name": "New Zealand", "subkind": "improved", "detail": "y"},
            {"entity_id": "BBB", "name": "Bland", "subkind": "unchanged", "detail": "z"}]
    cards = briefing.crisiswatch_cards(rows, "2026-10", ["NZL"])
    assert [c["entities"][0] for c in cards] == ["NZL", "AAA"]
    assert cards[0]["tone"] == "good" and cards[1]["title"] == "Aland: deteriorated" and cards[0]["group"] == "crisiswatch"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    today = date.today()
    (tmp_path / "media" / "news").mkdir(parents=True)
    (tmp_path / "media" / "news" / "items.json").write_text(json.dumps([
        _news("n1", (today - timedelta(days=1)).isoformat(), "Coup attempt in Turkey", ["TUR"], "BBC World"),
        _news("n2", (today - timedelta(days=2)).isoformat(), "New Zealand budget announced", ["NZL"], "RNZ", 0.6),
    ]))
    with TestClient(main.app) as c:
        yield c


def test_briefing_lanes(client):
    b = client.get("/api/v1/briefing").json()
    assert set(b["lanes"]) == {"happening", "found", "due", "yours"}
    happening = b["lanes"]["happening"]
    watch = [c for c in happening if c["group"] == "watch"]
    assert watch and watch[0]["entities"] == ["TUR"] and watch[0]["word"] == "coup"
    assert any(c["group"] == "news" and c["entities"] == ["NZL"] for c in happening)
    assert all(c["kind"] in ("feed", "find", "event", "due", "yours") for lane in b["lanes"].values() for c in lane)
    assert b["days"] == 7 and b["names"]["NZL"]


def test_map_events_window_and_latest(client):
    today = date.today().isoformat()
    week = (date.today() - timedelta(days=7)).isoformat()
    m = client.get("/api/v1/map-events", params={"start": week, "end": today}).json()
    assert [w["entity_id"] for w in m["watch"]] == ["TUR"] and "coup" in m["words"]
    old = client.get("/api/v1/map-events", params={"start": "2016-07-01", "end": "2016-07-31"}).json()
    assert any(e["kind"] == "coup" and e["entity_id"] == "TUR" and e["group"] == "conflict" for e in old["events"])
    assert client.get("/api/v1/map-events", params={"start": today, "end": week}).status_code == 422
    latest = client.get("/api/v1/entities/NZL/latest").json()
    assert latest["crisiswatch"] is None and any(c["group"] == "news" for c in latest["cards"])
    # Watch words come from Settings.
    client.put("/api/v1/settings", json={"news_watch_words": "budget"})
    m = client.get("/api/v1/map-events", params={"start": week, "end": today}).json()
    assert [w["entity_id"] for w in m["watch"]] == ["NZL"]
