"""Find data (Dateno): the search reply read into datasets and filters, answers kept a day, the
searches left read from the headers, files saved only from Dateno's own links, the wish list on
the To do page. The reply's shape follows Dateno's Python SDK models (November 2026); the network
is replaced."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import dateno

HIT = {"_index": "datasets", "_id": "dateno-abc123", "_score": 12.3, "_source": {
    "id": "dateno-abc123", "int_id": "1",
    "dataset": {"title": "Household <b>food</b> waste by region", "description": "<p>Tonnes of food waste&nbsp;per household.</p>",
                "url": "https://data.example.govt.nz/dataset/food-waste", "formats": [".csv", ".xlsx"],
                "topics": [{"id": "env", "name": "Environment", "type": "eu"}], "tags": ["waste", "food"],
                "responsible": [{"title": "Ministry for the Environment", "role": "Publisher"}],
                "license_name": "CC BY 4.0", "date_changed": "2026-05-01T00:00:00"},
    "source": {"uid": "cdi00000001", "name": "data.govt.nz", "url": "https://data.govt.nz", "catalog_type": "Open data portal",
               "owner_name": "Stats NZ", "owner_type": "Central government", "countries": [{"id": "NZ", "name": "New Zealand"}],
               "langs": [{"id": "EN", "name": "English"}]},
    "resources": [{"name": "Food waste CSV", "format": "CSV", "url": "https://data.example.govt.nz/files/food_waste.csv"},
                  {"name": "No link", "format": "PDF"},
                  {"name": "Bad link", "format": "CSV", "url": "file:///etc/passwd"}]}}
REPLY = {"took": 5, "timed_out": False, "hits": {"total": {"value": 1234, "relation": "eq"}, "max_score": 12.3, "hits": [HIT]},
         "aggregations": {"dataset.formats": {"buckets": [{"key": ".csv", "doc_count": 900}, {"key": ".xlsx", "doc_count": 40}]},
                          "source.countries.name": {"buckets": [{"key": "New Zealand", "doc_count": 1000}]},
                          "source.something": {"doc_count": 3, "inner": {"buckets": [{"key": "x", "doc_count": 3}]}}}}
HEADERS = {"X-RateLimit-Remaining-Day": "97", "X-RateLimit-Limit-Day": "100",
           "X-RateLimit-Remaining-Month": "990", "X-RateLimit-Limit-Month": "1000", "RateLimit-Reset": "7200"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    monkeypatch.delenv("WORLDMODEL_WAREHOUSE", raising=False)
    monkeypatch.setenv("DATENO_API_KEY", "test-key")
    dateno._seen.clear()
    return tmp_path


def fake(calls, status=200):
    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.path.endswith("/list_facets"):
            return httpx.Response(200, json=[{"key": "source.something", "name": "Something else"}], headers=HEADERS)
        if req.url.host == "data.example.govt.nz":
            return httpx.Response(200, content=b"region,tonnes\nAuckland,1\n")
        return httpx.Response(status, json=REPLY if status == 200 else {"detail": "no"}, headers=HEADERS)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_reads_datasets_facets_and_quota(home):
    calls = []
    out = dateno.search("food waste", {"dataset.formats": [".csv"]}, "nz", client=fake(calls))
    q = calls[0].url.params
    assert calls[0].url.path == "/search/0.2/query"
    assert q["q"] == "food waste" and q["apikey"] == "test-key" and q["facets"] == "true"
    assert q.get_list("filters") == ['"source.countries.id"="NZ"', '"dataset.formats"=".csv"']
    assert out["total"] == 1234
    d = out["items"][0]
    assert d["title"] == "Household food waste by region"
    assert d["text"] == "Tonnes of food waste per household."
    assert d["publisher"] == "Ministry for the Environment" and d["portal"] == "data.govt.nz"
    assert d["formats"] == ["CSV", "XLSX"] and d["topics"] == ["Environment"] and d["licence"] == "CC BY 4.0"
    assert d["changed"] == "2026-05-01" and d["countries"] == [{"id": "NZ", "name": "New Zealand"}]
    assert [f["name"] for f in d["files"]] == ["Food waste CSV"]  # no link and non-web links left out
    keys = [f["key"] for f in out["facets"]]
    assert keys[:2] == ["source.countries.name", "dataset.formats"]
    assert next(f for f in out["facets"] if f["key"] == "source.something")["name"] == "Something else"
    assert out["quota"]["day_left"] == 97 and out["quota"]["month_limit"] == 1000


def test_same_search_is_kept_a_day(home):
    calls = []
    c = fake(calls)
    dateno.search("food waste", client=c)
    n = len(calls)
    again = dateno.search("food  waste", client=c)
    assert len(calls) == n and again["from_cache"] is True


def test_clear_messages(home, monkeypatch):
    with pytest.raises(dateno.DatenoError) as e:
        dateno.search("x", client=fake([], 429))
    assert e.value.status == 429 and "about 2 hours" in str(e.value)
    with pytest.raises(dateno.DatenoError) as e:
        dateno.search("y", client=fake([], 401))
    assert e.value.status == 403
    with pytest.raises(dateno.DatenoError):
        dateno.search("", client=fake([]))
    monkeypatch.delenv("DATENO_API_KEY")
    with pytest.raises(dateno.DatenoError) as e:
        dateno.search("z", client=fake([]))
    assert "DATENO_API_KEY" in str(e.value)


def test_download_only_dateno_links(home):
    c = fake([])
    dateno.search("food", client=c)
    got = dateno.download("dateno-abc123", 0, client=c)
    assert got["name"] == "food_waste.csv" and got["bytes"] > 0
    about = json.loads((home / "found" / got["folder"].split("/")[-1].split("\\")[-1] / "about.json").read_text())
    assert about["licence"] == "CC BY 4.0"
    assert dateno.found_files()[0]["name"] == "food_waste.csv"
    with pytest.raises(dateno.DatenoError):
        dateno.download("dateno-abc123", 2, client=c)  # the file:// link was never offered


def test_wishes_show_on_todo(home):
    from worldmodel_api.main import app

    d = dateno.search("food", client=fake([]))["items"][0]
    with TestClient(app) as tc:
        assert tc.post("/api/v1/find/wishes", json={"dataset": d, "note": "regional"}).status_code == 200
        todo = tc.get("/api/v1/todo").json()["items"]
        wish = next(i for i in todo if i["kind"] == "wish")
        assert wish["title"] == "Make a source from Household food waste by region" and "regional" in wish["why"]
        assert wish["link"] == "https://data.example.govt.nz/dataset/food-waste"
        tc.delete("/api/v1/find/wishes/dateno-abc123")
        assert not any(i["kind"] == "wish" for i in tc.get("/api/v1/todo").json()["items"])
        st = tc.get("/api/v1/find/status").json()
        assert st["key_set"] is True and st["on"] is True
