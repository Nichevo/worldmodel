"""The public API (off by default, keys from other PCs, daily limit, log), the Python client and MCP
server against it, and countries like this one / synthetic comparison, on the sample warehouse."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, similar
from worldmodel_client import ApiOff, Client

LAN = {"x-forwarded-for": "192.168.1.20"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    return TestClient(main.app)


def test_off_by_default_then_local_needs_no_key(client):
    r = client.get("/api/public/v1/countries")
    assert r.status_code == 403 and "Settings > API access" in r.json()["detail"]
    client.put("/api/v1/settings", json={"api_public_on": True})
    assert any(c["id"] == "NZL" for c in client.get("/api/public/v1/countries").json())
    d = client.get("/api/public/v1/data", params={"indicator": "gdp_growth", "entities": "NZL", "from": 2010, "to": 2012}).json()
    assert d["unit"] and {r["year"] for r in d["rows"]} <= {2010, 2011, 2012} and d["rows"]
    csv = client.get("/api/public/v1/data", params={"indicator": "gdp_growth", "entities": "NZL", "format": "csv"}).text
    assert csv.startswith("entity,year,period,value,status")
    f = client.get("/api/public/v1/forecast", params={"indicator": "gdp_growth", "entity": "NZL", "horizon": 3}).json()
    p = f["points"][0]
    assert len(f["points"]) == 3 and p["p10"] < p["p50"] < p["p90"]
    svg = client.get("/api/public/v1/chart.svg", params={"indicator": "gdp_growth", "entities": "NZL,AUS"})
    assert svg.headers["content-type"].startswith("image/svg") and "<path" in svg.text and "New Zealand" in svg.text
    assert client.get("/api/public/v1/data", params={"indicator": "nope"}).status_code == 404


def test_lan_needs_a_key_with_a_daily_limit(client):
    client.put("/api/v1/settings", json={"api_public_on": True})
    assert client.get("/api/public/v1/countries", headers=LAN).status_code == 401
    k = client.post("/api/v1/api-access/keys", json={"name": "Laptop", "daily_limit": 2}).json()
    h = {**LAN, "Authorization": f"Bearer {k['key']}"}
    assert client.get("/api/public/v1/countries", headers=h).status_code == 200
    assert client.get("/api/public/v1/countries", headers={**LAN, "x-api-key": k["key"]}).status_code == 200
    assert client.get("/api/public/v1/countries", headers=h).status_code == 429
    assert client.get("/api/public/v1/countries", headers={**LAN, "Authorization": "Bearer wm_wrong"}).status_code == 401
    acc = client.get("/api/v1/api-access").json()
    assert acc["keys"][0]["today"] == 2 and "hash" not in acc["keys"][0] and k["key"] not in str(acc)
    assert [x["status"] for x in acc["recent"][:4]] == [401, 429, 200, 200]
    client.delete(f"/api/v1/api-access/keys/{k['id']}")
    assert client.get("/api/public/v1/countries", headers={**LAN, "Authorization": f"Bearer {k['key']}"}).status_code == 401


def test_python_client_and_mcp(client):
    wm = Client(http=TestClient(main.app, base_url="http://testserver/api/public/v1"))
    with pytest.raises(ApiOff):
        wm.countries()
    client.put("/api/v1/settings", json={"api_public_on": True})
    rows = wm.data("gdp_growth", ["NZL"], start=2010, frame=False)
    assert rows and rows[0]["entity"] == "NZL"
    assert "<svg" in wm.chart("gdp_growth", ["NZL"])
    assert any(r["id"] == "NZL" for r in wm.search("zealand"))
    made = wm.predict(question="NZ growth above 2% in 2027?", kind="binary", chance=0.6, due="2028-04-30")
    assert made["who"] == "Python client" and wm.predictions()[0]["id"] == made["id"]
    mcp = pytest.importorskip("mcp")
    assert mcp
    from worldmodel_client.mcp_server import build
    server = build(wm)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"search", "data", "forecast", "events", "crowd", "alike", "synthetic"} <= names


def test_alike_and_synthetic(client):
    near = client.get("/api/v1/alike", params={"entity": "NZL", "preset": "economy", "year": 2015, "n": 5}).json()
    assert len(near["nearest"]) == 5 and all(0 < r["likeness"] <= 100 for r in near["nearest"])
    assert near["nearest"] == sorted(near["nearest"], key=lambda r: r["distance"])
    assert client.get("/api/v1/alike", params={"entity": "NZL", "preset": "nope"}).status_code == 422
    mv = client.get("/api/v1/alike/move", params={"indicator": "gdp_growth", "start": 1995, "end": 2020, "groups": 4}).json()
    assert 2 <= len(mv["groups"]) <= 4 and sum(g["size"] for g in mv["groups"]) == len(mv["members"])
    syn = client.get("/api/v1/synthetic", params={"entity": "NZL", "indicator": "inflation", "year": 2000}).json()
    assert abs(sum(w["weight"] for w in syn["weights"]) - 1) < 0.05 and len(syn["actual"]) == len(syn["synthetic"])
    assert syn["p_value"] is not None and syn["verdict"]
    assert client.get("/api/v1/synthetic", params={"entity": "NZL", "indicator": "inflation", "year": 1500}).status_code == 422


def test_synthetic_finds_a_real_effect():
    """A made-up panel: the treated country is an exact mix of two others until a jump of +5 after the event."""
    years = range(1990, 2011)
    base = {f"C{i}": {y: float(i + (y - 1990) * (0.1 * i) + ((y * 7 + i * 3) % 5)) for y in years} for i in range(1, 12)}
    base["T"] = {y: 0.5 * base["C2"][y] + 0.5 * base["C5"][y] + (5 if y >= 2005 else 0) for y in years}

    def rows(sql, params):
        return [{"entity_id": e, "indicator_id": "x", "y": y, "v": v} for e, ys in base.items() for y, v in ys.items()]

    out = similar.synthetic(rows, {}, "T", "x", 2005, start=1990)
    top = {w["entity_id"] for w in out["weights"][:2]}
    assert top == {"C2", "C5"} and out["mean_gap_after"] == pytest.approx(5, abs=0.5)
    assert out["rank"] == 1
