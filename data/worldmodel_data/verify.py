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
PDF_LIMIT = 40  # PDFs of an archive opened in one run (it picks up where it stopped next time)
PDF_PAUSE = 4.0  # seconds between them
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
    name: str = ""                   # what you type to pick it (default: the source)
    pdf_archive: bool = False        # a page listing PDFs: save it, then each PDF not saved yet
    only_by_name: bool = False       # long: opened only when asked for by name, never by a plain verify.bat

    @property
    def key(self) -> str:
        return self.name or self.source


def _crisiswatch(today: date) -> list[Target]:
    from worldmodel_data.connectors.crisiswatch import BASE, month_pages, month_slug

    out = []
    for back in (1, 2):
        y, m = today.year, today.month - back
        while m < 1:
            y, m = y - 1, m + 12
        slug = month_slug(date(y, m, 1))
        out.append(Target("crisiswatch", f"CrisisWatch {slug}", BASE + month_pages(date(y, m, 1))[0], f"{slug}.html",
                          r"(?i)crisiswatch[\s\S]*" + r"\W+".join(slug.split("-")),
                          by_hand=True))  # its check page reloads for ever in a window the app drives
    return out


def targets(today: date | None = None) -> list[Target]:
    from worldmodel_data.connectors.crisiswatch import ARCHIVE as CW_ARCHIVE
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
        Target("crisiswatch", "CrisisWatch PDF archive (every month since 2003)", CW_ARCHIVE, "pdf-archive.html",
               r"(?i)\.pdf", by_hand=True, name="crisiswatch_pdf", pdf_archive=True, only_by_name=True),
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
    asked = [t for t in targets(today) if (t.key in sources if sources else not t.only_by_name)]
    if keep_days is None:
        return asked, []
    fresh_ = [t for t in asked if fresh(p, t, keep_days.get(t.source, 30))]
    return [t for t in asked if t not in fresh_], fresh_


def run(p: Paths, sources: list[str] | None, echo: Callable[[str], None], wait: int = WAIT,
        keep_days: dict[str, int] | None = None, pdf_limit: int = PDF_LIMIT) -> dict[str, list[Path]]:
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
                    if t.pdf_archive:
                        got_pdfs = pdf_archive(t, folder, wait, echo, pdf_limit)
                        if got_pdfs:
                            saved.setdefault(t.source, []).extend(got_pdfs)
                        continue
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


def pdf_links(page: str, base: str) -> list[str]:
    """The PDF addresses on an archive page, in page order (newest first), once each."""
    from urllib.parse import urljoin

    out: list[str] = []
    for href in re.findall(r"""href=["']([^"']+?\.pdf)(?:\?[^"']*)?["']""", page, re.I):
        u = urljoin(base, href.replace("&amp;", "&"))
        if u not in out:
            out.append(u)
    return out


def pdf_name(url: str) -> str:
    from urllib.parse import unquote, urlparse

    name = unquote(Path(urlparse(url).path).name)
    return re.sub(r'[<>:"/\\|?*]+', "_", name)


def pdf_archive(t: Target, folder: Path, wait: int, echo, limit: int = PDF_LIMIT,
                opener: Callable[[str], object] | None = None, watch: list[Path] | None = None,
                pause: float = PDF_PAUSE, poll: float = 2.0) -> list[Path]:
    """Save an archive page by hand, then open each PDF on it not saved yet in your own browser,
    a few seconds apart, and move each one that lands in Downloads into the manual folder.
    At most `limit` a run; the next run picks up where this one stopped."""
    import webbrowser

    page_file = folder / t.save_as
    if not (page_file.is_file() and time.time() - page_file.stat().st_mtime < 7 * 86400):
        if not _by_hand(t, folder, wait, echo, opener=opener, watch=watch, pause=poll):
            echo("    the archive page was not saved; nothing to open")
            return []
    links = pdf_links(page_file.read_text(encoding="utf-8", errors="replace"), t.url)
    have = {f.name.lower() for f in folder.glob("*.pdf")}
    todo = [u for u in links if pdf_name(u).lower() not in have]
    echo(f"    {len(links)} PDFs listed, {len(links) - len(todo)} saved already; opening up to {min(limit, len(todo))} now.")
    if not todo:
        return []
    echo("    Tip: in Edge, Settings > Cookies and site permissions > PDF documents > 'Always download PDF files'\n"
         "    saves each one by itself. Otherwise press Ctrl+S on each and save it into Downloads.")
    places = watch if watch is not None else [folder, downloads_dir()]
    saved: list[Path] = []
    misses = 0
    for n, url in enumerate(todo[:limit], 1):
        start = time.time() - 1
        (opener or webbrowser.open)(url)
        dest = folder / pdf_name(url)
        got = None
        end = time.time() + min(wait, 120)
        while time.time() < end and not got:
            for place in places:
                if not place.is_dir():
                    continue
                for f in place.iterdir():
                    if (f.is_file() and f.suffix.lower() == ".pdf" and f.stat().st_mtime >= start and f != dest
                            and f.name.lower() not in have and not f.name.lower().endswith((".crdownload", ".part"))):
                        got = f
                        break
                if got:
                    break
            if not got:
                time.sleep(poll)
        if got:
            got.replace(dest)
            have.add(dest.name.lower())
            saved.append(dest)
            echo(f"    [{n}/{min(limit, len(todo))}] saved {dest.name}")
            misses = 0
        else:
            misses += 1
            echo(f"    [{n}/{min(limit, len(todo))}] {pdf_name(url)} did not arrive; skipped")
            if misses >= 3:
                echo("    Three in a row did not arrive, so stopping here. Check the tip above, then run it again.")
                break
        time.sleep(pause)
    return saved
