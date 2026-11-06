"""Discover and news endpoints on the sample warehouse, and the news parsers on small samples."""

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, news
from worldmodel_api.warehouse import SAMPLE, Warehouse
from worldmodel_contract import discover

NAMES = news.Names([("NZL", "New Zealand"), ("FJI", "Fiji"), ("UKR", "Ukraine"), ("RUS", "Russia")])

WIKITEXT = """{{Current events|year=2026|month=11|day=5|content=
<!-- All news items below this line -->
'''Armed conflicts and attacks'''
* [[Russian invasion of Ukraine]]
** [[Russia]]n forces strike power stations across [[Ukraine]], leaving millions without electricity. ([https://www.reuters.com/x Reuters])
'''Disasters and accidents'''
* A magnitude 6.8 [[earthquake]] strikes near [[Suva]], [[Fiji]], with no tsunami warning issued.<ref>x</ref> ([https://apnews.com/y AP])
'''Politics and elections'''
* [[New Zealand]] Prime Minister announces a snap election for March. ([https://rnz.co.nz/z RNZ])
}}"""

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Fiji floods: thousands evacuated</title><link>https://x/1</link><description>&lt;p&gt;Heavy rain&lt;/p&gt;</description>
<pubDate>Wed, 05 Nov 2026 10:00:00 +1300</pubDate></item>
<item><title>Council votes on water</title><link>https://x/2</link></item></channel></rss>"""


def test_current_events_items_topics_and_countries():
    items = news.parse_current_events(WIKITEXT, "2026-11-05", NAMES)
    assert len(items) == 3
    war, quake, vote = items
    assert war["topic"] == "Armed conflicts and attacks" and war["tone"] == "bad" and war["category"] == "Conflict and security"
    assert war["detail"] == "Russian invasion of Ukraine" and set(war["entities"]) == {"RUS", "UKR"}
    assert quake["entities"] == ["FJI"] and quake["url"] == "https://apnews.com/y" and "<ref" not in quake["headline"]
    assert vote["entities"] == ["NZL"] and vote["tone"] == "neutral" and vote["category"] == "Government and politics"
    assert len({i["key"] for i in items}) == 3


def test_feed_items_and_home_country():
    items = news.parse_feed(RSS, "rnz", NAMES)
    assert [i["entities"] for i in items] == [["FJI"], ["NZL"]]  # RNZ is about New Zealand unless a country is named
    assert items[0]["date"] == "2026-11-05" and items[0]["detail"] == "Heavy rain" and items[0]["outlet"] == "RNZ"


def test_gdelt_spike_and_reliefweb():
    tl = [{"value": 10} for _ in range(80)]
    for k in range(7):
        tl[-1 - k]["value"] = 60
    s = news.spikes(tl, [{"value": -2}] * 73 + [{"value": -6}] * 7)
    assert round(s["ratio"]) == 6 and s["tone"] < -1
    assert news.spikes(tl[:20]) is None
    rw = news.parse_reliefweb({"data": [{"id": 1, "fields": {"name": "Fiji: Floods - Nov 2026", "country": [{"iso3": "fji"}],
                                                             "date": {"created": "2026-11-04T00:00:00+00:00"}, "type": [{"name": "Flood"}], "status": "ongoing"}}]}, NAMES)
    assert rw[0]["entities"] == ["FJI"] and rw[0]["date"] == "2026-11-04" and rw[0]["tone"] == "bad"


class FakeClient:
    """Answers the news requests from the samples above, without the internet."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)

        class R:
            def __init__(self, text=None, js=None):
                self.text, self._js = text or "", js

            def raise_for_status(self):
                pass

            def json(self):
                return self._js

        if url == news.WIKI_API:
            return R(js={"parse": {"wikitext": WIKITEXT}})
        return R(text=RSS)

    def close(self):
        pass


def test_run_keeps_items_once_and_skips_sources_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    from datetime import date

    s = {"news_sources": "wikipedia,feeds", "news_feeds": "rnz", "news_keep_days": 730, "discover_key_countries": "NZL"}
    c = FakeClient()
    st = news.run(s, NAMES, c, date(2026, 11, 6))
    first = news.items()
    assert st["last"]["wikipedia"]["items"] > 0 and "gdelt" not in st["last"] and not st["errors"]
    assert len({i["key"] for i in first}) == len(first) == 3 * 14 + 2  # 14 days of three items, and two headlines
    news.run(s, NAMES, c, date(2026, 11, 6))
    assert len(news.items()) == len(first)
    assert not news.is_due({"news_every_hours": 6})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    main.warehouse = Warehouse(str(SAMPLE))
    main._d_cache["build"] = None
    yield TestClient(main.app)
    main._d_cache["build"] = None


def test_feed_marks_and_tabs(client, tmp_path):
    first = client.get("/api/v1/discover?limit=500").json()
    assert first["build_id"] and first["total"] == len(first["items"]) and first["items"]
    assert discover.load_saved(tmp_path, first["build_id"], exact=True) is not None  # worked out once and kept
    f = first["items"][0]
    key = f["key"]
    r = client.put(f"/api/v1/discover/{key}", json={"rating": 1, "tags": ["watch"], "tone": "good"}).json()
    assert r == {"key": key, "rating": 1, "my_tags": ["watch"], "tone": "good"}
    mine = client.get("/api/v1/discover?tab=interesting").json()
    assert [x["key"] for x in mine["items"]] == [key] and "watch" in mine["items"][0]["tags"]
    assert client.get("/api/v1/discover?tag=watch").json()["total"] == 1
    client.put(f"/api/v1/discover/{key}", json={"rating": -1})
    assert key not in [x["key"] for x in client.get("/api/v1/discover?limit=500").json()["items"]]
    assert key in [x["key"] for x in client.get("/api/v1/discover?tab=hidden").json()["items"]]
    assert client.put(f"/api/v1/discover/{key}", json={"rating": 3}).status_code == 422
    assert client.put("/api/v1/discover/nope", json={"rating": 1}).status_code == 404
    # Never show a kind: every find of that kind moves to Hidden.
    kind = f["kind"]
    client.put(f"/api/v1/discover-never/{kind}", json={"on": True})
    assert all(x["kind"] != kind for x in client.get("/api/v1/discover?limit=500").json()["items"])
    client.put(f"/api/v1/discover-never/{kind}", json={"on": False})


def test_new_since_last_visit_and_country_card(client):
    feed = client.get("/api/v1/discover").json()
    assert feed["new_count"] == 0  # no visit yet: nothing counts as new
    client.post("/api/v1/discover-seen")
    st = discover.user_state()
    st["first_seen"][feed["items"][0]["key"]] = "2999-01-01T00:00:00+00:00"
    discover.save_user_state(st)
    again = client.get("/api/v1/discover?new=true").json()
    assert again["new_count"] == 1 and again["items"][0]["key"] == feed["items"][0]["key"]
    ent = feed["items"][0]["entities"][0] if feed["items"][0]["entities"] else "NZL"
    card = client.get(f"/api/v1/discover-entity/{ent}").json()
    assert all(ent in x["entities"] for x in card["items"])


def test_news_tab_and_switch(client, tmp_path):
    news._write("items.json", news.parse_current_events(WIKITEXT, "2026-11-05", NAMES))
    tab = client.get("/api/v1/discover?tab=news&tone=bad").json()
    assert tab["total"] == 2 and all(x["kind"] == "news" for x in tab["items"])
    assert tab["news"]["on"] and tab["news"]["due"]
    client.put("/api/v1/settings", json={"news_on": False})
    assert client.post("/api/v1/news/fetch").status_code == 409


def test_gdelt_slow_down_keeps_what_it_found_and_starts_there_next_time(monkeypatch):
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    from datetime import date

    class R:
        def __init__(self, code):
            self.status_code, self.text = code, ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"timeline": [{"data": [{"value": 10}] * 80}]}

    class Slow:
        def __init__(self):
            self.n = 0

        def get(self, url, params=None):
            self.n += 1
            return R(200 if self.n <= 2 else 429)  # the first country, then refused

    st = {}
    assert news.fetch_gdelt(Slow(), NAMES, ["NZL", "FJI"], date(2026, 11, 6), st) == []  # no spike, but no error
    assert st["gdelt_next"] == 1  # Fiji first next time
    with pytest.raises(news.Slowed):
        news.fetch_gdelt(type("C", (), {"get": lambda self, url, params=None: R(429)})(), NAMES, ["NZL"], date(2026, 11, 6), {})


def test_one_feed_down_does_not_stop_the_others():
    import httpx

    class C:
        def get(self, url, params=None):
            if "stuff" in url:
                raise httpx.ConnectError("refused")

            class R:
                text = RSS

                def raise_for_status(self):
                    pass
            return R()

    got = news.fetch_feeds(C(), NAMES, ["stuff", "rnz"])
    assert len(got) == 2
    with pytest.raises(RuntimeError, match="Stuff"):
        news.fetch_feeds(C(), NAMES, ["stuff"])


def test_good_news_words_and_date_filter(client):
    assert news.word_tone("Ceasefire agreed in Sudan as aid arrives") == "good"
    assert news.word_tone("Floods kill 12 in Fiji") == "bad"
    assert news.word_tone("Council votes on water") == "neutral"
    assert news.word_tone("Hostages released after ceasefire", "bad") == "good"
    items = news.parse_current_events(WIKITEXT, "2026-11-05", NAMES) + news.parse_feed(RSS, "rnz", NAMES)
    items[-1]["headline"] = "Peace deal signed; survivors found"
    news._write("items.json", items)
    tab = client.get("/api/v1/discover?tab=news&tone=good").json()
    assert [x["headline"] for x in tab["items"]] == ["Peace deal signed; survivors found"]
    assert client.get("/api/v1/discover?tab=news&since=2999").json()["total"] == 0
    assert client.get("/api/v1/discover?tab=news&since=2026-11-05&until=2026-11-05").json()["total"] == 4
    assert client.get("/api/v1/discover?tab=news&until=2025").json()["total"] == 0
    assert client.get("/api/v1/discover?since=1800").json()["total"] == client.get("/api/v1/discover").json()["total"]
    assert client.get("/api/v1/discover?since=bad").status_code == 422
