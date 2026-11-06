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
STUCK = 45  # a check page still showing after this long (it reloads itself): open the site in your own browser


@dataclass
class Target:
    source: str
    what: str
    url: str
    save_as: str = ""                # page: file name in the manual folder
    expect: str = ""                 # page: a pattern the real page has (the check page does not)
    download: bool = False           # the URL is a file
    link: str = ""                   # open url, then download the first link matching this
    by_hand: bool = False            # the site loops on its check in a driven window: open it in your own browser
    extra: list["Target"] = field(default_factory=list)


def _crisiswatch(today: date) -> list[Target]:
    from worldmodel_data.connectors.crisiswatch import BASE, month_slug

    out = []
    for back in (1, 2):
        y, m = today.year, today.month - back
        while m < 1:
            y, m = y - 1, m + 12
        slug = month_slug(date(y, m, 1))
        out.append(Target("crisiswatch", f"CrisisWatch {slug}", BASE + slug, f"{slug}.html",
                          r"(?i)crisiswatch[\s\S]*" + r"\W+".join(slug.split("-")),
                          by_hand=True))  # its check page reloads for ever in a window the app drives
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


class Stuck(Exception):
    """The site's check keeps coming back in the window the app opened."""


def _wait_for(page, expect: str, wait: int, echo: Callable[[str], None], stuck: int = STUCK) -> str | None:
    """The page's HTML once it has the expected text and no check; None after `wait` seconds.
    Raises Stuck when a check page is still showing `stuck` seconds after it first appeared."""
    told = False
    first_check = None
    end = time.time() + wait
    while time.time() < end:
        try:
            html = page.content()
        except Exception:  # noqa: BLE001 - the page is navigating (after a check, say)
            html = ""
        if html and re.search(expect, html) and not CHECK_WORDS.search(html[:20000]):
            return html
        if html and CHECK_WORDS.search(html[:20000]):
            first_check = first_check or time.time()
            if time.time() - first_check > stuck:
                raise Stuck()
            if not told:
                echo("    The site is checking that you are a person: complete the check in the browser window.")
                told = True
        time.sleep(2)
    return None


def fresh(p: Paths, t: Target, days: int) -> bool:
    """The file this target saves is already in its manual folder and under `days` old."""
    from worldmodel_data import manual

    f = manual.folder(p, t.source) / t.save_as
    return f.is_file() and time.time() - f.stat().st_mtime < days * 86400


def todo_list(p: Paths, sources: list[str] | None, keep_days: dict[str, int] | None = None,
              today: date | None = None) -> tuple[list[Target], list[Target]]:
    """(to open, left alone because their file is still fresh). keep_days: source -> days a
    saved file stays fresh; None opens everything asked for."""
    asked = [t for t in targets(today) if not sources or t.source in sources]
    if keep_days is None:
        return asked, []
    fresh_ = [t for t in asked if fresh(p, t, keep_days.get(t.source, 30))]
    return [t for t in asked if t not in fresh_], fresh_


def run(p: Paths, sources: list[str] | None, echo: Callable[[str], None], wait: int = WAIT,
        keep_days: dict[str, int] | None = None) -> dict[str, list[Path]]:
    """Open each target, save what arrives into var/manual/<source>/; returns the files saved per source.
    With keep_days, a target whose file was saved within that many days is left alone."""
    from playwright.sync_api import sync_playwright

    from worldmodel_data import manual

    todo, left = todo_list(p, sources, keep_days)
    if left:
        echo(f"Left alone, saved recently: {', '.join(t.what for t in left)} (.\\verify.bat all opens them anyway).")
    if not todo:
        return {}
    saved: dict[str, list[Path]] = {}
    by_hand: set[str] = set()
    with sync_playwright() as pw:
        ctx = _open_browser(pw, p.home / "browser")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for n, t in enumerate(todo, 1):
                folder = manual.folder(p, t.source)
                folder.mkdir(parents=True, exist_ok=True)
                echo(f"[{n}/{len(todo)}] {t.what}: {t.url}")
                try:
                    if t.by_hand or _host(t.url) in by_hand:
                        got = _by_hand(t, folder, wait, echo)
                    else:
                        try:
                            got = _one(page, t, folder, wait, echo)
                        except Stuck:
                            echo("    The check keeps coming back in this window. Opening the page in your own browser instead.")
                            by_hand.add(_host(t.url))
                            got = _by_hand(t, folder, wait, echo)
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


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower()


def downloads_dir() -> Path:
    return Path.home() / "Downloads"


def _by_hand(t: Target, folder: Path, wait: int, echo, opener: Callable[[str], object] | None = None,
             watch: list[Path] | None = None, pause: float = 2.0) -> Path | None:
    """Open the page in your everyday browser (where the site knows you), and wait for you
    to save it: into the source's manual folder, or anywhere in Downloads. A saved page
    counts once it has the page's own text and not the check; it is moved to `t.save_as`."""
    import webbrowser

    dest = folder / t.save_as
    start = time.time() - 1
    suffixes = (dest.suffix.lower(),) if t.download or t.link else (".html", ".htm")
    places = watch if watch is not None else [folder, downloads_dir()]
    (opener or webbrowser.open)(t.url)
    what = "the file it offers" if t.download or t.link else "the page with Ctrl+S (Save as type: Webpage, HTML only)"
    echo(f"    Opened in your own browser. Pass any check there, then save {what} into {folder} or Downloads.")
    end = time.time() + wait
    seen: set[Path] = set()
    while time.time() < end:
        for place in places:
            if not place.is_dir():
                continue
            for f in place.iterdir():
                if (f in seen or not f.is_file() or f.suffix.lower() not in suffixes
                        or f.stat().st_mtime < start or f.name.lower().endswith((".crdownload", ".part", ".tmp"))):
                    continue
                if not (t.download or t.link):
                    text = f.read_text(encoding="utf-8", errors="replace")
                    if CHECK_WORDS.search(text[:20000]) or (t.expect and not re.search(t.expect, text)):
                        seen.add(f)  # the check page, or some other page
                        continue
                if f != dest:
                    dest.unlink(missing_ok=True)
                    f.replace(dest)
                return dest
        time.sleep(pause)
    return None
