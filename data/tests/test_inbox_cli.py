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


def test_a_build_that_stops_without_a_report_says_where(tmp_path, monkeypatch):
    """An error no check catches: a short message, and the details in a -stopped.txt beside the reports."""
    from worldmodel_data import build as build_mod
    from worldmodel_data.cli import _build_and_log
    from worldmodel_data.config import paths
    import typer
    import pytest

    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))

    def stop(p, allow_shrink=False, **kw):
        raise RuntimeError("something broke")

    monkeypatch.setattr(build_mod, "build", stop)
    with pytest.raises(typer.Exit):
        _build_and_log(False, {"kind": "build", "sources": []})
    files = list(paths().reports.glob("*-stopped.txt"))
    assert len(files) == 1 and "RuntimeError: something broke" in files[0].read_text(encoding="utf-8")
