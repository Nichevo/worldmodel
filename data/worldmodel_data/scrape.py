"""Polite page reading for the scraping tools (sources that read web pages, not files or APIs).

Every scraper reads its pages through a PageReader, which:

* waits between pages: the gap in Settings (scrape_gap_seconds, 6 s by default), doubled
  for a run of more than 5 pages and tripled past 20, plus a little random extra, and a
  longer rest (ten gaps) after every 10th page;
* stops at the first problem instead of carrying on: a refused or failed page, a page that
  looks like a "check you are human" or "access denied" screen, or one that is missing what
  the scraper expects (the site's layout has probably changed). Nothing more is asked of
  the site in that run;
* says what happened: each page as it goes (log and, for the .bat tools, the console),
  and a record per source of the last run (pages planned, read, and why it stopped) in
  warehouse/scrape_log.json, shown on the Data status page.

The 429/503 "slow down" answers are already waited on and retried by Connector.get
(15, 45 then 90 s, or what Retry-After asks); a page still refused after that stops the run.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from worldmodel_data.connectors.base import ConnectorError

log = logging.getLogger(__name__)

DEFAULT_GAP = 6.0
# Words of a page that is a gate rather than the page asked for. Only looked for near the
# top of short pages, so an article that mentions "captcha" does not stop a run.
BLOCKED = re.compile(r"captcha|are you (a )?(human|robot)|access denied|request blocked|unusual traffic|"
                     r"just a moment\.\.\.|cf-chl|attention required|enable javascript and cookies|"
                     r"too many requests|rate limit", re.I)
BLOCK_CHECK_BYTES = 60_000


class ScrapeStopped(ConnectorError):
    """A scraper stopped early; the message says where and why."""


def gap_setting() -> float:
    try:
        from worldmodel_contract.local import load_settings
        from worldmodel_data.config import paths

        return float(load_settings(paths().home).get("scrape_gap_seconds", DEFAULT_GAP))
    except Exception:  # noqa: BLE001 - settings unreadable: the default
        return DEFAULT_GAP


def gap_for(page_no: int, planned: int, base: float) -> float:
    """Seconds to wait before page page_no (1-based; none before the first) of a run of planned pages."""
    if page_no <= 1:
        return 0.0
    g = base * (3 if planned > 20 else 2 if planned > 5 else 1)
    if (page_no - 1) % 10 == 0:  # a longer rest after every 10 pages
        g = max(g, base * 10)
    return g


def looks_blocked(text: str) -> str | None:
    """The gate's words when a page is a block or check screen rather than content."""
    if len(text) > BLOCK_CHECK_BYTES * 4:
        return None
    m = BLOCKED.search(text[:BLOCK_CHECK_BYTES])
    return m.group(0) if m else None


def _write_log(source_id: str, record: dict) -> None:
    try:
        from worldmodel_contract.local import scrape_log_path
        from worldmodel_data.config import paths

        p = scrape_log_path(paths().home)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data[source_id] = record
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(p)
    except Exception as exc:  # noqa: BLE001 - the record is a nicety; never fail a run over it
        log.warning("scrape log not written (%s)", exc)


class PageReader:
    """Read a run of pages from one site for one source, politely. Use as a context manager:

        with PageReader(conn, planned=len(urls)) as pages:
            for url in urls:
                text = pages.read(url, dest, expect=r"<table")

    read() raises ScrapeStopped at the first problem; the with block records the run either way.
    """

    def __init__(self, conn, planned: int, *, gap: float | None = None, echo: Callable[[str], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep, jitter: float = 0.3):
        self.conn = conn
        self.source_id = conn.source_id
        self.planned = max(1, planned)
        self.base = gap_setting() if gap is None else gap
        self.echo = echo
        self.sleep = sleep
        self.jitter = jitter
        self.read_count = 0
        self.asked = 0
        self.stopped: str | None = None
        self.last_url = ""

    def say(self, msg: str) -> None:
        log.info("%s: %s", self.source_id, msg)
        if self.echo:
            self.echo(f"  {msg}")

    def stop(self, why: str) -> None:
        self.stopped = why
        raise ScrapeStopped(f"{self.source_id}: stopped after {self.read_count} of {self.planned} page(s): {why}")

    def read(self, url: str, dest: Path, *, expect: str | None = None, what: str = "",
             missing_ok: bool = False) -> str | None:
        """Fetch url into dest (after the polite wait) and return its text. Stops the run on a
        failure, a block screen, or a page without `expect` (a regular expression). With
        missing_ok, a page the site says is not there (HTTP 404 or 410) returns None instead."""
        if self.stopped:
            raise ScrapeStopped(f"{self.source_id}: already stopped ({self.stopped})")
        self.asked += 1
        wait = gap_for(self.asked, self.planned, self.base)
        if wait:
            self.sleep(wait * (1 + random.uniform(0, self.jitter)))
        label = what or url
        self.last_url = url
        part = dest  # written in place (the "changed since?" cache knows it by this name); removed if unusable
        try:
            self.conn.get(url, part)
        except Exception as exc:  # noqa: BLE001 - any failure stops the run
            part.unlink(missing_ok=True)
            if missing_ok and re.search(r"HTTP 40[4]|HTTP 410", str(exc)):
                self.say(f"page {self.asked} of {self.planned}: {label} is not on the site (skipped)")
                return None
            self.stop(f"page {self.asked} ({label}) could not be read: {exc}. "
                      "Nothing more was asked of the site; try again later, or save the page from your browser (Ctrl+S) "
                      "into the source's var\\manual folder.")
        text = part.read_text(encoding="utf-8", errors="replace")
        if gate := looks_blocked(text):
            part.unlink(missing_ok=True)
            self.stop(f"page {self.asked} ({label}) is a check or block screen (\"{gate}\"), not the page; the site "
                      "is turning programs away. Save the page from your browser (Ctrl+S) into the source's "
                      "var\\manual folder instead.")
        if expect and not re.search(expect, text, re.I | re.S):
            part.unlink(missing_ok=True)
            self.stop(f"page {self.asked} ({label}) does not look like before (no {expect!r} on it); the site's layout "
                      "has probably changed and the scraper needs a fix. Save the page (Ctrl+S) into the source's "
                      "var\\manual folder so it can be looked at.")
        self.read_count += 1
        self.say(f"page {self.asked} of {self.planned}: {label} read")
        return text

    def __enter__(self) -> "PageReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None and not self.stopped:
            self.stopped = str(exc)
        _write_log(self.source_id, {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "planned": self.planned,
            "read": self.read_count, "stopped": self.stopped, "url": self.last_url, "gap_seconds": self.base})
        return False
