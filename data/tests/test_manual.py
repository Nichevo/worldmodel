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
    assert "jonathanmpowell.com" in note and "load.bat powell_thyne" in note
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


def test_loading_by_hand_closes_a_refused_download(home):
    from worldmodel_contract import local
    from worldmodel_data import monitor

    root, _ = home
    monitor.append(paths(), {"kind": "refresh", "started_at": "2026-11-02T01:00:00+00:00", "status": "ok",
                             "sources": [{"source_id": "powell_thyne", "status": "error", "error": "HTTP 403"}]})
    assert next(p for p in local.problems(root) if p["key"] == "fetch:powell_thyne")["open"]
    manual.folder(paths(), "powell_thyne").mkdir(parents=True)
    shutil.copy(FIX / "powell_thyne" / "powell_thyne_coups_final.txt", manual.folder(paths(), "powell_thyne"))
    out = CliRunner().invoke(cli.app, ["load", "powell_thyne"])
    assert out.exit_code == 0, out.output
    assert not next(p for p in local.problems(root) if p["key"] == "fetch:powell_thyne")["open"]


def test_a_hand_saved_file_stops_the_retries_until_it_is_due(home, monkeypatch):
    import os
    import time

    _, built = home
    cls = CONNECTORS["powell_thyne"]
    tries = []

    def blocked(self, raw_dir, release):
        tries.append(1)
        raise RuntimeError("HTTP 403 Forbidden")

    monkeypatch.setattr(cls, "download", blocked)
    monkeypatch.setattr(cli, "CONNECTORS", {"powell_thyne": cls})
    d = manual.folder(paths(), "powell_thyne")
    d.mkdir(parents=True)
    shutil.copy(FIX / "powell_thyne" / "powell_thyne_coups_final.txt", d)
    os.utime(d / "powell_thyne_coups_final.txt", (time.time() - 3600,) * 2)
    assert CliRunner().invoke(cli.app, ["refresh"]).exit_code == 0  # site refused: the file is loaded
    assert len(tries) == 1
    out = CliRunner().invoke(cli.app, ["refresh"])  # the site is left alone while the file is current
    assert out.exit_code == 0, out.output
    assert len(tries) == 1 and "using your file loaded" in built[1]["sources"][0]["note"]
    assert built[1]["sources"][0]["status"] == "skipped"
    newer = d / "powell_thyne_coups_newer.txt"
    newer.write_text((d / "powell_thyne_coups_final.txt").read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(newer, (time.time() + 60,) * 2)
    out = CliRunner().invoke(cli.app, ["refresh"])  # a newer file saved: read it, still without the site
    assert out.exit_code == 0, out.output
    assert len(tries) == 1 and "manual downloads folder" in built[2]["sources"][0]["note"]


def test_big_sources_are_not_fetched_every_day():
    for s in ("world_bank_wdi", "imf_weo", "oecd", "bis", "owid_grapher", "un_wpp"):
        assert CONNECTORS[s].fetch_every_days, s


def test_verify_lists_the_pages_with_person_checks():
    from datetime import date

    from worldmodel_data import verify
    from worldmodel_data.connectors import CONNECTORS

    ts = verify.targets(date(2026, 11, 6))
    assert {t.source for t in ts} == {"rbnz", "mbie_energy", "un_vetoes", "wto_disputes", "crisiswatch"}
    assert all(t.source in CONNECTORS for t in ts)
    assert [t.save_as for t in ts if t.source == "crisiswatch"] == ["october-2026.html", "september-2026.html"]
    assert sum(t.download for t in ts) == 4  # the RBNZ tables
    assert verify.CHECK_WORDS.search("<title>Just a moment...</title>") and not verify.CHECK_WORDS.search("<h1>Vetoes</h1>")
