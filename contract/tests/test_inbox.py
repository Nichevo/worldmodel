"""The inbox: working out a downloaded file's source, filing it, and learning from your choices."""

import json
import zipfile

from worldmodel_contract import inbox, upkeep


def _home(tmp_path, monkeypatch, **settings):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    (tmp_path / "user").mkdir(parents=True)
    (tmp_path / "user" / "settings.json").write_text(json.dumps({"inbox_downloads": False, **settings}))
    (tmp_path / "manual").mkdir()
    info = {"powell_thyne": {"keeps_files": False}, "nz_election_turnout": {"keeps_files": True}, "emdat": {"keeps_files": False},
            "un_vetoes": {"keeps_files": False}, "wto_disputes": {"keeps_files": False}}
    (tmp_path / "manual" / "_sources.json").write_text(json.dumps(info))
    return tmp_path


def test_shape():
    assert inbox.shape("pt_20251001 (2).CSV") == "pt_#.csv"
    assert inbox.shape("Data Export.xlsx") == "data_export.xlsx"


def test_files_by_pattern_and_old_files_moved(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    old = home / "manual" / "powell_thyne"
    old.mkdir()
    (old / "pt_20240101.csv").write_text("a")
    box = inbox.inbox_dir(home)
    box.mkdir()
    (box / "pt_20251001.csv").write_text("b")
    got = inbox.file_all(home)
    assert [e["source_id"] for e in got["filed"]] == ["powell_thyne"]
    assert (old / "pt_20251001.csv").read_text() == "b"
    assert (old / "old" / "pt_20240101.csv").exists()  # one-file source: the older file moved aside, not deleted
    assert not (box / "pt_20251001.csv").exists()


def test_learns_from_folders_and_choices(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    (home / "manual" / "emdat").mkdir()
    (home / "manual" / "emdat" / "disasters_2024.xlsx").write_text("x")
    box = inbox.inbox_dir(home)
    box.mkdir()
    (box / "disasters_2025.xlsx").write_text("y")  # same shape as a file already loaded for emdat
    (box / "mystery thing.csv").write_text("z")    # unknown: waits for you
    got = inbox.file_all(home)
    assert [e["source_id"] for e in got["filed"]] == ["emdat"]
    assert [w["name"] for w in got["waiting"]] == ["mystery thing.csv"]
    inbox.assign("mystery thing.csv", "un_vetoes", home)
    assert (home / "manual" / "un_vetoes" / "mystery thing.csv").exists()
    (box / "mystery thing.csv").write_text("again")  # named the same: now known
    assert inbox.Recogniser(home).guess(box / "mystery thing.csv")["source_id"] == "un_vetoes"


def test_saved_page_matched_by_address(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    box = inbox.inbox_dir(home)
    box.mkdir()
    (box / "Some page.html").write_text("<!-- saved from url=(0060)https://www.wto.org/english/tratop_e/dispu_e/dispu_status_e.htm -->\n<html></html>")
    g = inbox.Recogniser(home).guess(box / "Some page.html")
    assert g["source_id"] == "wto_disputes" and g["sure"]


def test_downloads_copied_only_when_sure(tmp_path, monkeypatch):
    dl = tmp_path / "dl"
    dl.mkdir()
    home = _home(tmp_path / "h", monkeypatch, inbox_downloads=True, inbox_downloads_folder=str(dl))
    (dl / "pt_20251001.csv").write_text("b")
    (dl / "holiday photo.jpg").write_text("p")
    got = inbox.file_all(home)
    assert [e["source_id"] for e in got["filed"]] == ["powell_thyne"]
    assert (dl / "pt_20251001.csv").exists() and (dl / "holiday photo.jpg").exists()  # Downloads is never changed
    assert got["waiting"] == []
    assert inbox.file_all(home)["filed"] == []  # copied once only


def test_backup_keeps_your_files_only(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch, backup_folder=str(tmp_path / "bk"), backup_keep=1)
    (home / "manual" / "emdat").mkdir()
    (home / "manual" / "emdat" / "a.xlsx").write_text("x")
    (home / "raw").mkdir()
    (home / "raw" / "big.zip").write_text("y")
    z = upkeep.backup(home, say=lambda *_: None)
    names = zipfile.ZipFile(z).namelist()
    assert "manual/emdat/a.xlsx" in names and "user/settings.json" in names and not any(n.startswith("raw") for n in names)
    assert len(upkeep.backups(root=home)) == 1
