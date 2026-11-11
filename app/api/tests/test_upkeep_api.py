"""Looking after the sources: the To do list, the inbox, every source's health, keys and jobs."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_contract import upkeep


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setattr(upkeep, "env_file", lambda: tmp_path / ".env")
    (tmp_path / "manual").mkdir()
    (tmp_path / "manual" / "_sources.json").write_text(json.dumps({"emdat": {"manual": True, "keeps_files": False},
                                                                   "world_policy": {"needs_settings": ["world_dataverse_name"]}}))
    return TestClient(main.app)


def test_todo_lists_mark_and_snooze(client):
    d = client.get("/api/v1/todo").json()
    kinds = {i["kind"] for i in d["items"]}
    assert "download" in kinds and "form" in kinds
    first = d["items"][0]
    after = client.put(f"/api/v1/todo/{first['key']}", json={"action": "snooze", "days": 7}).json()
    assert after["count"] == d["count"] - 1 and after["hidden"][0]["key"] == first["key"]
    back = client.put(f"/api/v1/todo/{first['key']}", json={"action": "clear"}).json()
    assert back["count"] == d["count"]
    client.put("/api/v1/settings", json={"sources_off": "emdat"})
    assert not any(i["source_id"] == "emdat" for i in client.get("/api/v1/todo").json()["items"])


def test_inbox_waiting_file(client, tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "whatever.bin").write_bytes(b"x")
    d = client.get("/api/v1/inbox").json()
    assert d["waiting"][0]["name"] == "whatever.bin" and d["waiting"][0]["source_id"] is None
    assert any(i["kind"] == "inbox" for i in client.get("/api/v1/todo").json()["items"])
    assert client.post("/api/v1/inbox/assign", json={"name": "nope.csv", "source_id": "emdat"}).status_code == 404
    assert client.post("/api/v1/inbox/assign", json={"name": "whatever.bin", "source_id": "nosuch"}).status_code == 422


def test_source_health(client):
    d = client.get("/api/v1/source-health").json()
    row = next(r for r in d["sources"] if r["source_id"] == "world_bank_wdi")
    assert row["uses"] > 10 and row["state"] in ("ok", "due", "never", "failing")
    client.put("/api/v1/settings", json={"sources_off": "world_bank_wdi"})
    row = next(r for r in client.get("/api/v1/source-health").json()["sources"] if r["source_id"] == "world_bank_wdi")
    assert row["state"] == "off"


def test_keys_written_to_env(client, tmp_path, monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OTHER=1\nEIA_API_KEY=old\n")
    assert client.put("/api/v1/keys/NOT_A_KEY", json={"value": "x"}).status_code == 404
    assert client.put("/api/v1/keys/EIA_API_KEY", json={"value": "a\nb"}).status_code == 422
    assert client.put("/api/v1/keys/EIA_API_KEY", json={"value": "new"}).json()["set"]
    assert (tmp_path / ".env").read_text() == "OTHER=1\nEIA_API_KEY=new\n"
    client.put("/api/v1/keys/EIA_API_KEY", json={"value": ""})
    assert "EIA_API_KEY" not in (tmp_path / ".env").read_text()


def test_backup_job(client, tmp_path):
    client.put("/api/v1/settings", json={"backup_folder": str(tmp_path / "bk")})
    assert client.post("/api/v1/jobs", json={"kind": "nope"}).status_code == 422
    j = client.post("/api/v1/jobs", json={"kind": "backup"}).json()
    assert j["kind"] == "backup"
    for _ in range(60):
        j = client.get("/api/v1/jobs").json()
        if not j["running"]:
            break
        time.sleep(0.5)
    assert j["exit_code"] == 0, j["lines"]
    assert client.get("/api/v1/upkeep").json()["backups"]
