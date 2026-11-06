"""Sites that turn programs away with a "are you a person?" check, opened in your own browser.

`worldmodel-data verify` (verify.bat) opens each page in a browser window on your screen
(Microsoft Edge, else Chrome), one at a time. If the site shows a check you complete it
yourself, as you would when visiting; the app never answers it. Once the page or file has
arrived it is saved into the source's var/manual folder, and at the end those folders are
loaded as if you had saved the files by hand. The browser keeps its own profile in
var/browser, so a site that remembers you passed asks less often.

It reads a handful of pages, once each, only when you run it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from worldmodel_data.config import Paths

WAIT = 240  # seconds to wait for each page while you complete a check


@dataclass
class Target:
    source: str
    what: str
    url: str
    save_as: str = ""                # page: file name in the manual folder
    expect: str = ""                 # page: a pattern the real page has (the check page does not)
    download: bool = False           # the URL is a file
    link: str = ""                   # open url, then download the first link matching this
    extra: list["Target"] = field(default_factory=list)


def _crisiswatch(today: date) -> list[Target]:
    from worldmodel_data.connectors.crisiswatch import BASE, month_slug

    out = []
    for back in (1, 2):
        y, m = today.year, today.month - back
        while m < 1:
            y, m = y - 1, m + 12
        slug = month_slug(date(y, m, 1))
        out.append(Target("crisiswatch", f"CrisisWatch {slug}", BASE + slug, f"{slug}.html", r"(?i)crisiswatch"))
    return out


def targets(today: date | None = None) -> list[Target]:
    from worldmodel_data.connectors.nz import MBIE_PAGE, RBNZ_FILES, RBNZ_URL
    from worldmodel_data.connectors.world_bodies import MEMBERS_PAGE, VETO_PAGE, WTO_PAGE

    today = today or date.today()
    rbnz = []
    for name, code in RBNZ_FILES.items():
        rbnz.append(Target("rbnz", f"RBNZ {code.upper()}", RBNZ_URL.format(letter=code[0], code=code, name=name),
                           f"{name}.xlsx", download=True))
    return [
        *rbnz,
        Target("mbie_energy", "MBIE energy balance tables", MBIE_PAGE, "energy-balance-tables.xlsx",
               link=r"energy-balance[^\"']*\.xlsx"),
        Target("un_vetoes", "UN vetoes list", VETO_PAGE, "vetoes.html", r"(?i)veto"),
        Target("un_vetoes", "UN Security Council elected members", MEMBERS_PAGE, "elected_members.html", r"(?i)elected"),
        Target("wto_disputes", "WTO disputes list", WTO_PAGE, "disputes.html", r"DS\s?\d"),
        *_crisiswatch(today),
    ]


CHECK_WORDS = re.compile(r"(?i)verify you are human|checking your browser|are you a robot|captcha|just a moment|access denied|"
                         r"request unsuccessful|incapsula|cf-challenge")


def _open_browser(pw, profile: Path):
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            kw = {"channel": channel} if channel else {}
            return pw.chromium.launch_persistent_context(str(profile), headless=False, accept_downloads=True,
                                                         viewport=None, **kw)
        except Exception as exc:  # noqa: BLE001 - try the next browser
            last = exc
    raise RuntimeError(f"no browser could be opened (Edge, Chrome or Playwright's own): {last}")


def _wait_for(page, expect: str, wait: int, echo: Callable[[str], None]) -> str | None:
    """The page's HTML once it has the expected text and no check; None after `wait` seconds."""
    told = False
    end = time.time() + wait
    while time.time() < end:
        try:
            html = page.content()
        except Exception:  # noqa: BLE001 - the page is navigating (after a check, say)
            html = ""
        if html and re.search(expect, html) and not CHECK_WORDS.search(html[:20000]):
            return html
        if not told and html and CHECK_WORDS.search(html[:20000]):
            echo("    The site is checking that you are a person: complete the check in the browser window.")
            told = True
        time.sleep(2)
    return None


def run(p: Paths, sources: list[str] | None, echo: Callable[[str], None], wait: int = WAIT) -> dict[str, list[Path]]:
    """Open each target, save what arrives into var/manual/<source>/; returns the files saved per source."""
    from playwright.sync_api import sync_playwright

    from worldmodel_data import manual

    todo = [t for t in targets() if not sources or t.source in sources]
    saved: dict[str, list[Path]] = {}
    with sync_playwright() as pw:
        ctx = _open_browser(pw, p.home / "browser")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for n, t in enumerate(todo, 1):
                folder = manual.folder(p, t.source)
                folder.mkdir(parents=True, exist_ok=True)
                echo(f"[{n}/{len(todo)}] {t.what}: {t.url}")
                try:
                    got = _one(page, t, folder, wait, echo)
                except Exception as exc:  # noqa: BLE001 - one site must not stop the others
                    echo(f"    not saved: {str(exc).splitlines()[0][:200]}")
                    continue
                if got:
                    echo(f"    saved {got}")
                    saved.setdefault(t.source, []).append(got)
                else:
                    echo(f"    nothing arrived within {wait} seconds; skipped")
                time.sleep(3)  # a pause between sites
        finally:
            ctx.close()
    return saved


def _one(page, t: Target, folder: Path, wait: int, echo) -> Path | None:
    dest = folder / t.save_as
    if t.download:
        with page.expect_download(timeout=wait * 1000) as d:
            try:
                page.goto(t.url)
            except Exception:  # noqa: BLE001 - "Download is starting" is how a file shows up
                pass
            if CHECK_WORDS.search(page.content()[:20000] if page.url.startswith("http") else ""):
                echo("    The site is checking that you are a person: complete the check in the browser window.")
        d.value.save_as(dest)
        return dest
    page.goto(t.url, wait_until="domcontentloaded", timeout=wait * 1000)
    if t.link:
        html = _wait_for(page, t.link, wait, echo)
        if html is None:
            return None
        href = re.search(rf"""href=["']([^"']*{t.link})""", html, re.I)
        if not href:
            return None
        with page.expect_download(timeout=wait * 1000) as d:
            page.click(f"a[href='{href.group(1)}']")
        d.value.save_as(dest)
        return dest
    html = _wait_for(page, t.expect, wait, echo)
    if html is None:
        return None
    dest.write_text(html, encoding="utf-8")
    return dest
