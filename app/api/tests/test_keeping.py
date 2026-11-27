"""Warnings for saved data near the age its Settings keep it for, and for the drive and limits."""

import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import keeping, main
from worldmodel_contract import local


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "var"
    monkeypatch.setenv("WORLDMODEL_HOME", str(h))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    (h / "user").mkdir(parents=True)
    return h


def _settings(h, **kw):
    (h / "user" / "settings.json").write_text(json.dumps(kw))


def test_planes_warned_before_first_deletion_and_keep_as_is(home):
    planes = home / "live" / "planes"
    planes.mkdir(parents=True)
    for d in ("2026-11-01", "2026-11-02"):
        (planes / f"{d}.parquet").write_bytes(b"x")
    _settings(home, planes_keep_days=30, expiry_warn_days=7)
    # 2026-11-01 goes on 2026-12-02 (once more than 30 days old)
    assert keeping.expiring(today=date(2026, 11, 20))["items"] == []
    got = keeping.expiring(today=date(2026, 11, 26))["items"]
    assert [(i["key"], i["deletes_from"], i["days_left"]) for i in got] == [("planes", "2026-12-02", 6)]
    assert keeping.expiring(today=date(2026, 12, 20))["items"][0]["days_left"] < 0  # already deleting: still shown
    keeping.keep_as_is("planes")
    assert keeping.expiring(today=date(2026, 11, 26))["items"] == []
    _settings(home, planes_keep_days=31, expiry_warn_days=7)  # a new limit warns again when it comes close
    assert [i["key"] for i in keeping.expiring(today=date(2026, 11, 27))["items"]] == ["planes"]
    _settings(home, planes_keep_days=31, expiry_warn_days=0)
    assert keeping.expiring(today=date(2026, 11, 27))["items"] == []


def test_schedules_news_history_backups(home, tmp_path):
    ships = home / "live" / "ships"
    ships.mkdir(parents=True)
    t = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
    (ships / "schedules.json").write_text(json.dumps({"etas": {"1": [[t, "NZAKL"]]}, "calls": {}, "bookings": {}}))
    news = home / "media" / "news"
    news.mkdir(parents=True)
    (news / "items.json").write_text(json.dumps([{"key": "a", "date": "2024-12-05"}]))
    (home / "user" / "history.jsonl").write_text(json.dumps({"id": "x", "at": "2026-10-01T00:00:00+00:00", "kind": "page", "title": "t"}) + "\n")
    bk = tmp_path / "bk"
    bk.mkdir()
    for n in ("2026-11-01-0100", "2026-11-02-0100"):
        (bk / f"worldmodel-backup-{n}.zip").write_bytes(b"z")
    _settings(home, schedules_keep_days=90, news_keep_days=700, history_retention_days=60, backup_keep=2,
              backup_folder=str(bk), expiry_warn_days=14)
    got = {i["key"]: i for i in keeping.expiring(today=date(2026, 11, 27))["items"]}
    assert set(got) == {"schedules", "news", "history", "backups"}
    assert got["schedules"]["deletes_from"] == "2026-11-30" and got["news"]["days_left"] < 0
    assert "worldmodel-backup-2026-11-01-0100.zip" in got["backups"]["what"]


def test_endpoints_and_drive_level(home, monkeypatch):
    planes = home / "live" / "planes"
    planes.mkdir(parents=True)
    (planes / "2020-01-01.csv").write_text("")
    _settings(home, drive_free_warn_gb=10_000, storage_warn_pct=50, storage_critical_pct=40)
    client = TestClient(main.app)
    items = client.get("/api/v1/storage/expiring").json()["items"]
    assert [i["key"] for i in items] == ["planes"]
    assert client.post("/api/v1/storage/expiring/planes/keep").json()["items"] == []
    assert client.post("/api/v1/storage/expiring/nope/keep").status_code == 404
    assert [i["ok"] for i in client.get("/api/v1/storage/expiring", params={"all": True}).json()["items"]] == [True]
    st = client.get("/api/v1/storage").json()
    d = st["limits"][-1]
    assert d["key"] == "drive" and d["level"] in ("warn", "critical", "full") and st["limits"][0]["key"] == "disk"
    assert st["warn_at"] == 0.5 and st["critical_at"] == pytest.approx(0.51)  # critical kept above warn
    assert local.level(60, 100, 0.5, 0.9) == "warn"
