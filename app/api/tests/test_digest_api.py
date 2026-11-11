"""The weekly digest: weeks by ISO number, kept once over, the week in progress worked out each time."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import digest, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    return TestClient(main.app)


def test_weeks():
    assert digest.week_id(date(2026, 11, 11)) == "2026-W46"
    assert digest.week_start("2026-W46") == date(2026, 11, 9)
    assert digest.last_complete(date(2026, 11, 9)) == "2026-W45"  # Monday: last week is now whole
    assert digest.last_complete(date(2026, 11, 15)) == "2026-W45"
    with pytest.raises(ValueError):
        digest.week_start("2026-46")


def test_kept_and_so_far(client):
    d = client.get("/api/v1/digest", params={"week": "2026-W44"}).json()
    assert d["complete"] and d["kept"] and d["from"] == "2026-10-26" and d["to"] == "2026-11-01"
    for part in ("sources", "changed", "finds", "crowd", "predictions", "crisiswatch", "events", "news"):
        assert isinstance(d[part], list)
    assert client.get("/api/v1/digests").json()["kept"] == ["2026-W44"]
    again = client.get("/api/v1/digest", params={"week": "2026-W44"}).json()
    assert again["made"] == d["made"]
    now = client.get("/api/v1/digest", params={"week": digest.week_id(date.today())}).json()
    assert not now["complete"] and not now["kept"]
    assert digest.week_id(date.today()) not in client.get("/api/v1/digests").json()["kept"]
    assert client.get("/api/v1/digest", params={"week": "2026-46"}).status_code == 422


def test_off_keeps_nothing(client):
    client.put("/api/v1/settings", json={"digest_on": False})
    d = client.get("/api/v1/digest", params={"week": "2026-W40"}).json()
    assert not d["kept"] and client.get("/api/v1/digests").json()["kept"] == []
