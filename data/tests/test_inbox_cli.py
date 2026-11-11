"""worldmodel-data inbox and refresh --only: files are filed from the inbox before loading."""

import json

from typer.testing import CliRunner

from worldmodel_data.cli import app


def test_inbox_files_and_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    (tmp_path / "user").mkdir()
    (tmp_path / "user" / "settings.json").write_text(json.dumps({"inbox_downloads": False}))
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "not a known file.txt").write_text("x")
    r = CliRunner().invoke(app, ["inbox", "--no-build"])
    assert r.exit_code == 0, r.output
    assert "need you to choose" in r.output and "Nothing new to file" in r.output
    info = json.loads((tmp_path / "manual" / "_sources.json").read_text())
    assert info["emdat"]["manual"] is True and "keeps_files" in info["powell_thyne"]


def test_refresh_only_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    r = CliRunner().invoke(app, ["refresh", "--only", "nosuch"])
    assert r.exit_code != 0
