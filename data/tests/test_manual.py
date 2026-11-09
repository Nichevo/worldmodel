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
    assert [t.save_as for t in ts if t.key == "crisiswatch"] == ["october-2026.html", "september-2026.html"]
    assert [t.key for t in ts if t.pdf_archive] == ["crisiswatch_pdf"]
    assert sum(t.download for t in ts) == 4  # the RBNZ tables
    assert verify.CHECK_WORDS.search("<title>Just a moment...</title>") and not verify.CHECK_WORDS.search("<h1>Vetoes</h1>")


def test_a_site_that_keeps_refusing_is_switched_and_switched_back(home, monkeypatch):
    import json

    from worldmodel_contract import fetch_methods as fm

    _, built = home
    cls = CONNECTORS["powell_thyne"]
    tries = []
    works = {"ok": False}

    def download(self, raw_dir, release):
        tries.append(1)
        if not works["ok"]:
            raise RuntimeError("HTTP 403 Forbidden")
        shutil.copy(FIX / "powell_thyne" / "powell_thyne_coups_final.txt", raw_dir)
        return "https://example.org/pt.txt"

    monkeypatch.setattr(cls, "download", download)
    monkeypatch.setattr(cli, "CONNECTORS", {"powell_thyne": cls})
    assert CliRunner().invoke(cli.app, ["refresh"]).exit_code == 1  # refused once: keeps trying
    out = CliRunner().invoke(cli.app, ["refresh"])  # refused twice in a row: switched to your file
    assert "switched to your file" in out.output
    state = fm.read_state(paths().home)["sources"]["powell_thyne"]
    assert state["auto"] == "file" and state["method"] == "file" and state["can"] == ["site", "file"]
    CliRunner().invoke(cli.app, ["refresh"])
    assert len(tries) == 2  # the site is left alone now
    assert "switched to your file automatically" in built[2]["sources"][0]["note"]

    fm.set_choice("powell_thyne", "site", paths().home)  # you can make it try anyway
    CliRunner().invoke(cli.app, ["refresh"])
    assert len(tries) == 3
    fm.set_choice("powell_thyne", "auto", paths().home)

    path = fm.state_path(paths().home)  # the retry date comes round, and the site works again
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sources"]["powell_thyne"]["retry_from"] = "2000-01-01"
    path.write_text(json.dumps(data), encoding="utf-8")
    works["ok"] = True
    out = CliRunner().invoke(cli.app, ["refresh"])
    assert out.exit_code == 0, out.output
    assert len(tries) == 4 and fm.read_state(paths().home)["sources"]["powell_thyne"]["auto"] == "site"


def test_a_failed_download_says_what_went_wrong():
    from worldmodel_contract.fetch_methods import classify

    assert classify("Client error '403 Forbidden' for url") == "blocked"
    assert classify("HTTP 202 (a check page)") == "blocked"
    assert classify("Client error '404 Not Found'") == "gone"
    assert classify("ReadTimeout: timed out") == "network"
    assert classify("no table with a Resolution column") == "changed"


def test_verify_opens_a_looping_site_in_your_own_browser_and_waits_for_the_save(tmp_path):
    from datetime import date

    from worldmodel_data import verify

    t = next(x for x in verify.targets(date(2026, 11, 6)) if x.save_as == "october-2026.html")
    assert t.by_hand
    folder, downloads = tmp_path / "manual", tmp_path / "Downloads"
    folder.mkdir()
    downloads.mkdir()
    (downloads / "old.html").write_text("CrisisWatch October 2026")  # saved before: not taken
    import os
    os.utime(downloads / "old.html", (1, 1))

    def you_save(url):
        assert url.endswith("crisiswatch/october-trends-and-november-alerts-2026")
        (downloads / "check.html").write_text("<title>Performing security verification</title> Just a moment")
        (downloads / "CrisisWatch October 2026 _ Crisis Group.html").write_text("<h1>CrisisWatch</h1> October 2026 ...")

    said = []
    got = verify._by_hand(t, folder, 5, said.append, opener=you_save, watch=[folder, downloads], pause=0.05)
    assert got == folder / "october-2026.html" and "October 2026" in got.read_text()
    assert (downloads / "check.html").exists() and not (downloads / "CrisisWatch October 2026 _ Crisis Group.html").exists()
    assert "Ctrl+S" in said[0]


def test_a_check_that_keeps_coming_back_is_noticed():
    from worldmodel_data import verify

    class Page:
        def content(self):
            return "<title>Performing security verification</title> Just a moment..."

    with pytest.raises(verify.Stuck):
        verify._wait_for(Page(), "CrisisWatch", 10, lambda m: None, stuck=0)


def test_verify_leaves_alone_files_saved_recently(home):
    from datetime import date

    from worldmodel_data import verify

    d = manual.folder(paths(), "un_vetoes")
    d.mkdir(parents=True)
    (d / "vetoes.html").write_text("Vetoes")
    todo, left = verify.todo_list(paths(), ["un_vetoes", "wto_disputes"], {"un_vetoes": 30, "wto_disputes": 30}, date(2026, 11, 6))
    assert [t.save_as for t in left] == ["vetoes.html"]
    assert {t.save_as for t in todo} == {"elected_members.html", "disputes.html"}
    assert len(verify.todo_list(paths(), ["un_vetoes"], None)[0]) == 2  # verify.bat all, or names given: every one


def test_crisiswatch_reads_a_page_saved_under_the_browsers_name():
    from datetime import date

    from worldmodel_data.connectors import crisiswatch as cw

    page = """<h1><time datetime="2026-10-30">October 2026</time></h1>
    <div class="c-crisiswatch-entry u-pr" id="benin"><h3 class="u-df"><span class="o-icon"><svg><use xlink:href="#unchanged"></use></svg></span>
    Benin</h3><time>October 2026</time><div class="o-crisis-states"><div title="June 2026"><a href="/crisiswatch/june-trends-and-july-alerts-2026#benin">
    <span class="state-unchanged"></span><span class="state-resolution"></span></a></div></div>
    <div class="o-entry-text"><p>President reaffirmed ties.</p></div></div>
    <div class="c-crisiswatch-entry u-pr" id="mali"><h3><svg><use xlink:href="#deteriorated"></use></svg> Mali</h3>
    <p>Jihadists blockaded the capital.</p></div>
    <div class="c-crisiswatch-entry u-pr" id="x"><h3>Nowhere</h3></div>"""
    assert cw.page_month(page) == date(2026, 10, 1) and cw.month_of("CrisisWatch Database _ International Crisis Group.htm") is None
    got = {n: r[0] for n, r, _ in cw.entries(page)}
    assert got == {"Benin": "unchanged", "Mali": "deteriorated"}
    assert cw.month_pages(date(2026, 10, 1))[0] == "october-trends-and-november-alerts-2026"
    assert cw.month_pages(date(2026, 12, 1))[:2] == ["december-trends-and-january-alerts-2027",
                                                     "december-trends-and-january-alerts-2026"]


def test_crisiswatch_reads_a_database_page_of_one_country_over_many_months():
    from datetime import date

    from worldmodel_data.connectors import crisiswatch as cw

    def entry(month, icon, text):
        return (f'<div class="c-crisiswatch-entry u-pr" id="albania"><h3><svg><use xlink:href="#{icon}"></use></svg> Albania</h3>'
                f'<time class="u-ttu">{month}</time><p>{text}</p></div>')

    page = '<div class="cw-database"><h1>Tracking</h1>' + entry("March 2026", "unchanged", "Calm.") + \
        entry("February 2026", "deteriorated", "Protests.") + entry("January 2026", "unchanged", "Talks.") + "</div>"
    got = cw.by_entry_month(page)
    assert sorted(got) == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert [r[0] for _, r, _ in cw.entries(got[date(2026, 2, 1)])] == ["deteriorated"]


def test_crisiswatch_reads_the_months_strip_beside_each_entry():
    from datetime import date

    from worldmodel_data.connectors import crisiswatch as cw

    page = ('<div class="c-crisiswatch-entry u-pr" id="benin"><h3><svg><use xlink:href="#unchanged"></use></svg> Benin</h3>'
            '<div class="o-crisis-states u-df">'
            '<div title="June 2026" class="o-state-entry u-df u-pr"><a href="#"><span class="state-unchanged"></span>'
            '<span class="state-resolution"></span><aside>Unchanged Situation</aside></a></div>'
            '<div title="July 2026" class="o-state-entry u-df u-pr"><a href="#"><span class="state-deteriorated"></span>'
            '<aside>x</aside></a></div></div><p>Text.</p></div>')
    assert cw.strips(page) == [("Benin", date(2026, 6, 1), ("resolution_opportunity", "Resolution opportunity")),
                               ("Benin", date(2026, 7, 1), ("deteriorated", "Deteriorated"))]


def test_crisiswatch_reads_a_month_from_the_pdf_archive():
    from datetime import date

    from worldmodel_data.connectors import crisiswatch as cw

    text = ("CrisisWatch 2025 – February Trends and March Alerts\nMiddle East and North Africa\nEastern Mediterranean\n"
            "\U0001F5F2 Israel/Palestine    Israel’s broadest operation in decades.\nMore on Gaza.\n"
            " Jordan   Amman rejected the idea.\nGulf and Arabian Peninsula\n"
            " Korean Peninsula North Korea fired missiles.\n"
            " India (non -Kashmir)  In Jharkhand, police were killed.\n"
            " Mali   Something new.\n")
    month = cw.pdf_month("x.pdf", text, {})
    assert month == date(2025, 2, 1)
    unknown: set[str] = set()
    got = cw.pdf_entries(text, month, unknown)
    assert [(p, r[0]) for p, r, _ in got] == [("Israel/Palestine", "risk_alert"), ("Jordan", "unchanged"),
                                             ("Korean Peninsula", "unchanged"), ("India (non-Kashmir)", "unchanged"),
                                             ("Mali", "rated")]
    assert got[0][2] == "Israel’s broadest operation in decades. More on Gaza."
    assert got[1][2] == "Amman rejected the idea."  # the region heading after it is dropped
    assert unknown == {"U+F0C9"}
    # Older PDFs have no title: the month comes from the file name, else the day it was made.
    assert cw.pdf_month("crisiswatch-november-2019.pdf", "Asia", {}) == date(2019, 11, 1)
    assert cw.pdf_month("Asia.pdf", "Asia", {"/CreationDate": "D:20191203164956+01'00'"}) == date(2019, 11, 1)


def test_verify_collects_an_archives_pdfs_a_few_at_a_time(tmp_path):
    from worldmodel_data import verify

    folder, downloads = tmp_path / "manual", tmp_path / "Downloads"
    folder.mkdir()
    downloads.mkdir()
    t = next(x for x in verify.targets() if x.pdf_archive)
    (folder / t.save_as).write_text('<a href="/sites/default/files/cw-2025-02-mena.pdf">Feb</a>'
                                    '<a href="https://x.org/files/cw%202019-11.pdf?v=2">Nov</a>'
                                    '<a href="/sites/default/files/old.pdf">Old</a>', encoding="utf-8")
    (folder / "old.pdf").write_bytes(b"%PDF saved before")
    opened = []

    def opener(url):  # the browser saves the PDF into Downloads under its own name
        opened.append(url)
        (downloads / f"download-{len(opened)}.pdf").write_bytes(b"%PDF")

    got = verify.pdf_archive(t, folder, 5, lambda s: None, limit=5, opener=opener, watch=[downloads], pause=0, poll=0.01)
    assert [p.name for p in got] == ["cw-2025-02-mena.pdf", "cw 2019-11.pdf"]
    assert opened[0] == "https://www.crisisgroup.org/sites/default/files/cw-2025-02-mena.pdf"
    assert not list(downloads.iterdir())
    assert verify.pdf_archive(t, folder, 5, lambda s: None, opener=opener, watch=[downloads], pause=0, poll=0.01) == []
