"""The polite page reader the scraping tools share."""

import json

import pytest

from worldmodel_data.connectors.base import ConnectorError
from worldmodel_data.scrape import PageReader, ScrapeStopped, gap_for, looks_blocked


class FakeConn:
    source_id = "crisiswatch"

    def __init__(self, pages):
        self.pages = pages  # url -> text, or an exception
        self.asked = []

    def get(self, url, dest):
        self.asked.append(url)
        got = self.pages[url]
        if isinstance(got, Exception):
            raise got
        dest.write_text(got, encoding="utf-8")


def test_gaps_grow_with_long_runs():
    assert gap_for(1, 30, 6) == 0
    assert gap_for(2, 3, 6) == 6
    assert gap_for(2, 10, 6) == 12
    assert gap_for(2, 30, 6) == 18
    assert gap_for(11, 30, 6) == 60  # a longer rest after every 10 pages


def test_block_screens_are_noticed():
    assert looks_blocked("<title>Just a moment...</title>")
    assert looks_blocked("Please complete the CAPTCHA")
    assert not looks_blocked("<table><tr><td>New Zealand</td></tr></table>")


def test_stops_at_the_first_problem_and_records_why(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "var"))
    pages = {f"u{i}": "<p>crisiswatch</p>" for i in range(5)}
    pages["u2"] = ConnectorError("GET u2 returned HTTP 403")
    conn, waits = FakeConn(pages), []
    with pytest.raises(ScrapeStopped, match="stopped after 2 of 5"):
        with PageReader(conn, planned=5, gap=6, sleep=waits.append, jitter=0) as r:
            for i in range(5):
                r.read(f"u{i}", tmp_path / f"p{i}.html", expect="crisiswatch")
    assert conn.asked == ["u0", "u1", "u2"]  # nothing asked after the refusal
    assert waits == [6, 6]
    assert not (tmp_path / "p2.html").exists()
    log = json.loads((tmp_path / "var" / "warehouse" / "scrape_log.json").read_text())
    assert log["crisiswatch"]["read"] == 2 and "HTTP 403" in log["crisiswatch"]["stopped"]


def test_a_changed_layout_or_block_page_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "var"))
    conn = FakeConn({"a": "<html>nothing useful</html>", "b": "<title>Attention Required! | Cloudflare</title>"})
    with pytest.raises(ScrapeStopped, match="layout"):
        with PageReader(conn, planned=2, gap=0) as r:
            r.read("a", tmp_path / "a.html", expect="crisiswatch")
    with pytest.raises(ScrapeStopped, match="block screen"):
        with PageReader(conn, planned=1, gap=0) as r:
            r.read("b", tmp_path / "b.html")


def test_a_missing_page_can_be_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "var"))
    conn = FakeConn({"a": ConnectorError("GET a returned HTTP 404"), "b": "ok"})
    with PageReader(conn, planned=2, gap=0) as r:
        assert r.read("a", tmp_path / "a.html", missing_ok=True) is None
        assert r.read("b", tmp_path / "b.html") == "ok"
    assert r.stopped is None and r.read_count == 1


def test_nz_turnout_links():
    from worldmodel_data.connectors.voters import _nz_links

    # the 2026 layout: Participation in voting links each election's page under "historical events"
    page = ('<a href="/democracy-in-nz/historical-events/2023-general-election/voter-turnout-statistics">2023</a>'
            '<a href="/democracy-in-nz/historical-events/2023-general-election/voter-and-non-voter-survey">survey</a>'
            '<a href="/stats-and-research/participation-in-voting">Stats</a><a href="https://example.com/turnout.xlsx">other</a>')
    pages, files = _nz_links(page)
    assert pages == ["https://elections.nz/democracy-in-nz/historical-events/2023-general-election/voter-turnout-statistics"]
    assert files == []
    page = ('<a href="/assets/pagecomponent-file-files/2023-General_Election_Turnout_by_Age_Descent.xlsx">x</a>'
            '<a href="/assets/Neighbourhood-turnout-/2023-General-Election-Voter-Turnout-by-SA2.xlsx">sa2</a>')
    assert _nz_links(page)[1] == ["https://elections.nz/assets/pagecomponent-file-files/2023-General_Election_Turnout_by_Age_Descent.xlsx"]


def test_incapsula_gate_is_a_block():
    from worldmodel_data.scrape import looks_blocked

    gate = ('<html>\r\n<head>\r\n<META NAME="robots" CONTENT="noindex,nofollow">\r\n'
            '<script src="/_Incapsula_Resource?SWJIYLWA=5074a744e2e3d891814e9a2dace20bd4"></script><body></body></html>')
    assert looks_blocked(gate)


def test_corrections_workbook_link():
    from worldmodel_data.connectors.nz import _workbook_link

    assert _workbook_link('<a href="/assets/Prison_Stats_-_Q1_FY_2026_27.xlsx">Download</a>') == \
        "https://www.corrections.govt.nz/assets/Prison_Stats_-_Q1_FY_2026_27.xlsx"
    assert _workbook_link("<a href='/other.pdf'>") is None
