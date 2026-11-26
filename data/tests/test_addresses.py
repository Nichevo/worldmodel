import httpx

from worldmodel_data import addresses


def test_remember_keeps_a_few_addresses_without_queries(tmp_path):
    addresses.remember(tmp_path, "src", [
        "https://a.org/data/file.csv?api_key=SECRET", "https://a.org/data/other.csv", "https://b.org/x.zip",
        "https://a.org/data/file.csv", "ftp://c.org/y", "https://a.org/data/third.csv"])
    kept = addresses.load(tmp_path)["sources"]["src"]["urls"]
    assert kept == ["https://a.org/data/file.csv", "https://b.org/x.zip", "https://a.org/data/other.csv"]
    assert "SECRET" not in (tmp_path / "warehouse" / "addresses.json").read_text()


def test_check_flags_gone_and_down_but_not_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(addresses, "GAP", 0)
    answers = {"/ok": 200, "/gone": 404, "/needs-key": 401, "/no-head": 405, "/broken": 503}

    def handle(req):
        code = answers[req.url.path]
        if req.url.path == "/no-head" and req.method == "GET":
            code = 206
        return httpx.Response(code)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    for s, path in [("fine", "/ok"), ("moved", "/gone"), ("keyed", "/needs-key"), ("nohead", "/no-head"), ("sick", "/broken"),
                    ("today", "/gone")]:
        addresses.remember(tmp_path, s, [f"https://x.org{path}"])
    assert addresses.due(tmp_path, 7)
    bad = addresses.check(tmp_path, skip={"today"}, client=client, say=lambda *_: None)
    assert set(bad) == {"moved", "sick"}
    assert bad["moved"][0]["status"] == "gone" and bad["sick"][0]["status"] == "down"
    assert not addresses.due(tmp_path, 7) and not addresses.due(tmp_path, 0)
    assert addresses.load(tmp_path)["checked"] == 5
