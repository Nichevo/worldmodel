"""WORLD Policy from Harvard Dataverse: listing, guestbook answers, unchanged files carried over."""

import json

import duckdb
import httpx

from worldmodel_data.config import Paths
from worldmodel_data.connectors.laws import WorldPolicy
from worldmodel_data.vintage_store import VintageStore

CSV_A = "country,iso3,year,paid_leave_weeks\nNew Zealand,NZL,2022,26\nAustralia,AUS,2022,20\n"
CSV_B = "Country,Year,Minimum wage exists\nNew Zealand,2021,Yes\n"


def handler(log, versions):
    def h(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        log.append((req.method, path))
        if path == "/api/dataverses/WORLD/contents":
            return httpx.Response(200, json={"data": [
                {"type": "dataset", "protocol": "doi", "authority": "10.7910", "identifier": "DVN/AAA"},
                {"type": "dataverse", "id": 77}]})
        if path == "/api/dataverses/77/contents":
            return httpx.Response(200, json={"data": [{"type": "dataset", "protocol": "doi", "authority": "10.7910",
                                                       "identifier": "DVN/BBB"}]})
        if path == "/api/datasets/:persistentId/":
            pid = req.url.params["persistentId"]
            title = "Paid leave" if pid.endswith("AAA") else "Minimum wage"
            files = [{"dataFile": {"id": 1 if pid.endswith("AAA") else 2, "filename": "data.tab",
                                   "originalFileName": "leave.csv" if pid.endswith("AAA") else "wage.csv",
                                   "checksum": {"type": "MD5", "value": versions[pid[-3:]]}}},
                     {"dataFile": {"id": 9, "filename": "codebook.pdf"}}]
            return httpx.Response(200, json={"data": {"guestbookId": 5 if pid.endswith("BBB") else None, "latestVersion": {
                "files": files, "metadataBlocks": {"citation": {"fields": [{"typeName": "title", "value": title}]}}}}})
        if path == "/api/guestbooks/5":
            return httpx.Response(200, json={"data": {"customQuestions": [{"id": 31, "questionString": "Why?"}]}})
        if path == "/api/access/datafile/1":
            return httpx.Response(200, text=CSV_A)
        if path == "/api/access/datafile/2":
            if req.method == "GET":
                return httpx.Response(400, json={"message": "guestbook response required"})
            body = json.loads(req.content)["guestbookResponse"]
            assert body["email"] == "me@example.org" and body["answers"] == [{"id": 31, "value": "Personal research"}]
            return httpx.Response(200, json={"data": {"signedUrl": "https://dataverse.harvard.edu/signed/2?token=x"}})
        if path == "/signed/2":
            return httpx.Response(200, text=CSV_B)
        return httpx.Response(404)
    return h


def test_dataverse_download(tmp_path, monkeypatch):
    home = tmp_path / "var"
    monkeypatch.setenv("WORLDMODEL_HOME", str(home))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    (home / "user").mkdir(parents=True)
    (home / "user" / "settings.json").write_text(json.dumps({"world_dataverse_name": "Me", "world_dataverse_email": "me@example.org",
                                                             "world_dataverse_purpose": "Personal research"}))
    store = VintageStore(Paths(home))
    log, versions = [], {"AAA": "a1", "BBB": "b1"}
    c = WorldPolicy(httpx.Client(transport=httpx.MockTransport(handler(log, versions))))
    c.pause_seconds = 0
    m, new = c.ingest(store)
    assert new
    d = store.vintage_dir("world_policy", m.vintage)
    got = {(r[0], r[1]): r[2] for r in duckdb.sql(
        f"SELECT source_code, indicator_id, value FROM '{d / 'observations.parquet'}'").fetchall()}
    assert got[("NZL", "world_paid_leave_weeks")] == 26
    assert got[("NZL", "world_minimum_wage_exists")] == 1
    assert ("POST", "/api/access/datafile/2") in log
    # Again with one dataset changed: only that file is fetched; the other is carried over.
    log.clear()
    versions["AAA"] = "a2"
    c2 = WorldPolicy(httpx.Client(transport=httpx.MockTransport(handler(log, versions))))
    c2.pause_seconds = 0
    m2, _ = c2.ingest(store)
    fetched = [p for _, p in log if p.startswith("/api/access/datafile") or p.startswith("/signed")]
    assert fetched == ["/api/access/datafile/1"]
    d2 = store.vintage_dir("world_policy", m2.vintage)
    ids = {r[0] for r in duckdb.sql(f"SELECT DISTINCT indicator_id FROM '{d2 / 'observations.parquet'}'").fetchall()}
    assert "world_minimum_wage_exists" in ids
