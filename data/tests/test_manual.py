"""The manual downloads folder: files saved by hand in <home>/manual/<source>/."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldmodel_data import cli, manual
from worldmodel_data.config import paths
from worldmodel_data.connectors import CONNECTORS

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "var"))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    built = []
    monkeypatch.setattr(cli, "_build_and_log", lambda allow_shrink, record: built.append(record))
    return tmp_path / "var", built


def test_prepare_makes_a_folder_per_hand_loaded_or_often_blocked_source(home):
    made = manual.prepare(paths(), CONNECTORS)
    assert {"emdat", "rbnz", "powell_thyne", "nz_election_turnout"} <= set(made)
    note = (manual.folder(paths(), "powell_thyne") / manual.ABOUT).read_text(encoding="utf-8")
    assert "uky.edu" in note and "load.bat powell_thyne" in note
    assert manual.prepare(paths(), CONNECTORS) == []  # already there
    assert manual.files(manual.folder(paths(), "powell_thyne")) == []  # the note is not a file to load


def test_load_copies_a_file_in_then_loads_folders(home):
    src = FIX / "emdat" / "public_emdat_custom_request_2025-06-01_test.xlsx"
    out = CliRunner().invoke(cli.app, ["load", "emdat", str(src)])
    assert out.exit_code == 0, out.output
    assert "stored new vintage" in out.output
    assert (manual.folder(paths(), "emdat") / src.name).is_file()
    out = CliRunner().invoke(cli.app, ["load"])  # every folder: the same file again changes nothing
    assert out.exit_code == 0, out.output
    assert "emdat: unchanged" in out.output


def test_load_moves_older_files_aside_for_one_file_sources(home, tmp_path):
    d = manual.folder(paths(), "emdat")
    d.mkdir(parents=True)
    (d / "older.xlsx").write_bytes(b"x")
    src = FIX / "emdat" / "public_emdat_custom_request_2025-06-01_test.xlsx"
    manual.keep_copy(paths(), "emdat", src, keeps_files=False)
    assert (d / "old" / "older.xlsx").is_file() and [f.name for f in manual.files(d)] == [src.name]


def test_refresh_reads_the_folder_of_a_hand_loaded_source(home, monkeypatch):
    _, built = home
    monkeypatch.setattr(cli, "CONNECTORS", {"emdat": CONNECTORS["emdat"]})
    d = manual.folder(paths(), "emdat")
    d.mkdir(parents=True)
    shutil.copy(FIX / "emdat" / "public_emdat_custom_request_2025-06-01_test.xlsx", d)
    out = CliRunner().invoke(cli.app, ["refresh"])
    assert out.exit_code == 0, out.output
    assert built[0]["sources"][0]["status"] == "new"
    assert "manual downloads folder" in built[0]["sources"][0]["note"]


def test_refresh_falls_back_to_the_folder_when_the_download_is_blocked(home, monkeypatch):
    _, built = home
    cls = CONNECTORS["powell_thyne"]

    def blocked(self, raw_dir, release):
        raise RuntimeError("HTTP 403 Forbidden")

    monkeypatch.setattr(cls, "download", blocked)
    monkeypatch.setattr(cli, "CONNECTORS", {"powell_thyne": cls})
    out = CliRunner().invoke(cli.app, ["refresh"])  # nothing saved yet: fails, and says where to save it
    assert out.exit_code == 1
    assert "load.bat powell_thyne" in built[0]["sources"][0]["error"]
    shutil.copy(FIX / "powell_thyne" / "powell_thyne_coups_final.txt", manual.folder(paths(), "powell_thyne"))
    out = CliRunner().invoke(cli.app, ["refresh"])
    assert out.exit_code == 0, out.output
    e = built[1]["sources"][0]
    assert e["status"] == "new" and "403" in e["note"] and "manual downloads folder" in e["note"]


def test_every_manual_folder_says_where_to_get_the_file():
    from worldmodel_contract import catalogue
    from worldmodel_data.connectors import CONNECTORS
    from worldmodel_data import manual
    srcs = catalogue.sources()
    missing = [s for s in manual.wanted(CONNECTORS) if not (srcs.get(s) and srcs[s].manual)]
    assert not missing, f"add a manual: block in sources.yaml for {missing}"
    assert all(srcs[s].manual.by_hand == bool(CONNECTORS[s].manual) for s in manual.wanted(CONNECTORS))
