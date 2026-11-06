"""International Crisis Group's CrisisWatch: a monthly rating and a paragraph for every
country in conflict or at risk, since August 2003.

    https://www.crisisgroup.org/crisiswatch/<month>-<year>          (one month, for example october-2024)
    https://www.crisisgroup.org/crisiswatch/database?date=<Month> <year>   (tried when the first is missing)

One month's page at a time, a few seconds apart: each refresh reads the latest
LATEST months again (ratings are finished a few days into the next month) and then
fills in up to `crisiswatch_backfill` older months (Settings) that are not stored yet,
working back to August 2003. Pages already stored are kept (files of earlier vintages
are carried forward), so after a year or two of refreshes the whole history is there.
Pages saved by hand work too (name them after the month, as october-2024.html).

Each entry on a page is a country (or a conflict, such as "Israel/Palestine") with a
rating: Deteriorated, Improved, Unchanged, Conflict Risk Alert or Resolution
Opportunity, and a paragraph on what happened that month. Each becomes a
"crisiswatch" event on the country (an entry naming two countries gives each one), dated
the first of the month, subkind the rating, detail the paragraph.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, country, stage_events
from worldmodel_data.connectors.world_bodies import text_of

log = logging.getLogger(__name__)

BASE = "https://www.crisisgroup.org/crisiswatch/"
FIRST = date(2003, 8, 1)
LATEST = 2  # months read again on every refresh
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december")
# Rating -> (subkind, label); matched on the words in an entry's class names, icon or heading.
RATINGS = (
    ("resolution", ("resolution_opportunity", "Resolution opportunity")),
    ("risk", ("risk_alert", "Conflict risk alert")),
    ("deteriorat", ("deteriorated", "Deteriorated")),
    ("improv", ("improved", "Improved")),
    ("unchanged", ("unchanged", "Unchanged")),
)
# Entries that are not one country: name -> the countries it covers.
SPLIT = {"Israel/Palestine": ("Israel", "Palestine"), "Nagorno-Karabakh (Azerbaijan)": ("Azerbaijan",),
         "Nagorno-Karabakh Conflict": ("Armenia", "Azerbaijan"), "Korean Peninsula": ("North Korea", "South Korea"),
         "Kashmir": ("India", "Pakistan"), "India-Pakistan (Kashmir)": ("India", "Pakistan"),
         "China/Japan": ("China", "Japan"), "Taiwan Strait": ("China", "Taiwan"), "South China Sea": ("China",),
         "Russia/Ukraine": ("Russia", "Ukraine"), "Ukraine": ("Ukraine",), "Western Sahara": ("Morocco",),
         "Northern Ireland (UK)": ("United Kingdom",), "Basque Country (Spain)": ("Spain",),
         "Cyprus": ("Cyprus",), "Kosovo": ("Kosovo",), "Eastern Mediterranean": ("Greece", "Turkey"),
         "Gulf and Arabian Peninsula": (), "Great Lakes": (), "Sahel": (), "Lake Chad Basin": (),
         "Nile Waters": ("Egypt", "Ethiopia", "Sudan"), "Armenia/Azerbaijan": ("Armenia", "Azerbaijan"),
         "Somaliland": ("Somalia",), "Chechnya (Russia)": ("Russia",), "North Caucasus (Russia)": ("Russia",),
         "Abkhazia (Georgia)": ("Georgia",), "South Ossetia (Georgia)": ("Georgia",), "Papua (Indonesia)": ("Indonesia",),
         "Aceh (Indonesia)": ("Indonesia",), "Bougainville (Papua New Guinea)": ("Papua New Guinea",)}


def month_slug(d: date) -> str:
    return f"{MONTH_NAMES[d.month - 1]}-{d.year}"


def months_back(today: date, n: int) -> list[date]:
    """The first of each month, newest first, from the month before today back n months."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(date(y, m, 1))
    return out


def month_pages(m: date) -> list[str]:
    """Names a month's page has had, newest style first: october-trends-and-november-alerts-2026
    (the year of the alerts month), the older november-alerts-and-october-trends-2026, and plain
    october-2026."""
    a, b = MONTH_NAMES[m.month - 1], MONTH_NAMES[m.month % 12]
    ny = m.year + (m.month == 12)
    out = [f"{a}-trends-and-{b}-alerts-{ny}"]
    if ny != m.year:
        out.append(f"{a}-trends-and-{b}-alerts-{m.year}")
    return out + [f"{b}-alerts-and-{a}-trends-{ny}", month_slug(m)]


def page_month(page: str) -> date | None:
    """The month a saved page is for, from the month in its main heading (a page saved with
    the browser's own name, such as 'CrisisWatch Database _ International Crisis Group.htm')."""
    heads = [h for h in re.findall(r"<h1\b[^>]*>(.*?)</h1>", page, re.S | re.I) if "<time" in h]
    heads += re.findall(r"<time\b[^>]*>(.*?)</time>", page, re.S | re.I)
    for part in heads:
        t = re.search(r"(?i)\b(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})\b", re.sub(r"<[^>]+>", " ", part))
        if t:
            return date(int(t.group(2)), MONTH_NAMES.index(t.group(1).lower()) + 1, 1)
    return None


def month_of(name: str) -> date | None:
    """The month a stored page is for, from its file name (october-2024.html, 2024-10.html)."""
    s = name.lower()
    m = re.search(r"(" + "|".join(MONTH_NAMES) + r")[-_ ](\d{4})", s)
    if m:
        return date(int(m.group(2)), MONTH_NAMES.index(m.group(1)) + 1, 1)
    m = re.search(r"(\d{4})-(\d{2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1)
    return None


class CrisisWatch(Connector):
    source_id = "crisiswatch"
    switch = "crisiswatch_fetch"
    keeps_files = True
    fetch_every_days = 7
    stage_version = 2  # pages saved under the browser's name; the entry's own icon for its rating

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def backfill(self) -> int:
        try:
            from worldmodel_contract.local import load_settings
            from worldmodel_data.config import paths

            return int(load_settings(paths().home).get("crisiswatch_backfill", 12))
        except Exception:  # noqa: BLE001 - settings unreadable: the default
            return 12

    def stored_months(self) -> set[date]:
        """Months already held in the source's raw files (any earlier vintage)."""
        try:
            from worldmodel_data.config import paths

            root = paths().raw / self.source_id
        except Exception:  # noqa: BLE001
            return set()
        return {m for p in root.glob("**/*.htm*") if (m := month_of(p.name))}

    def download(self, raw_dir: Path, release: str) -> str:
        today = date.today()
        have = self.stored_months()
        wanted = months_back(today, LATEST)
        older = [m for m in months_back(today, (today.year - FIRST.year + 1) * 12) if m >= FIRST and m not in have
                 and m not in wanted]
        wanted += older[: self.backfill()]
        from worldmodel_data.scrape import PageReader

        got = []
        with PageReader(self, planned=len(wanted)) as pages:
            for m in wanted:
                dest = raw_dir / f"{month_slug(m)}.html"
                text = None
                for slug in month_pages(m):  # the page's name has changed over the years
                    text = pages.read(BASE + slug, dest, missing_ok=True, what=month_slug(m), expect=r"crisiswatch")
                    if text is not None:
                        break
                if text is not None:
                    got.append(month_slug(m))
        if not got:
            raise ConnectorError("crisiswatch: no month's page could be read")
        return f"{BASE} ({', '.join(got)})"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, unmatched = [], set()
        for p in sorted(raw_dir.glob("*.htm*")):
            text = p.read_text(encoding="utf-8", errors="replace")
            m = month_of(p.name) or page_month(text)
            if not m:
                log.warning("crisiswatch: cannot tell the month of %s (name it like october-2024.html); skipped", p.name)
                continue
            rows += month_events(m, text, unmatched)
        if not rows:
            raise ConnectorError("crisiswatch: no ratings read; the pages' layout may have changed")
        uniq = {(r[0], r[1]): r for r in rows}
        self.events_query = stage_events(con, self.source_id, vintage, list(uniq.values()), unmatched)
        return EMPTY_OBSERVATIONS


def rating(fragment: str) -> tuple[str, str] | None:
    s = fragment.lower()
    for word, r in RATINGS:
        if word in s:
            return r
    return None


def entries(page: str) -> list[tuple[str, tuple[str, str], str]]:
    """(name, rating, paragraph) for each entry on a month's page."""
    blocks = re.split(r'(?=<(?:div|article|li)\b[^>]*class="[^"]*crisiswatch-entry(?![-_a-z]))', page)
    if len(blocks) < 3:  # another layout: a heading per country
        blocks = re.split(r"(?=<h[234]\b)", page)
    out = []
    for b in blocks[1:]:
        head = re.search(r"<h[234]\b[^>]*>(.*?)</h[234]>", b, re.S)
        if not head:
            continue
        name = text_of(head.group(1)).strip()
        # the rating: from class names or alt text before the paragraphs, else from words near the heading
        icons = " ".join(re.findall(r'href="#([a-z-]+)"', head.group(0)))  # the entry's own icons, not the months strip
        if rating(icons):
            r = rating(icons)
            paras = [text_of(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", b, re.S)]
            body = " ".join(p for p in paras if p).strip()
            if name and len(name) <= 80 and body:
                out.append((name, r, body))
            continue
        before = b[: head.start()] + b[head.end(): head.end() + 600]
        r = rating(" ".join(re.findall(r'(?:class|alt|title)="([^"]+)"', before))) or rating(text_of(before)[:200])
        paras = [text_of(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", b, re.S)]
        body = " ".join(p for p in paras if p).strip()
        if not name or not r or len(name) > 80 or not body:
            continue
        out.append((name, r, body))
    return out


def month_events(month: date, page: str, unmatched: set[str]) -> list[tuple]:
    out = []
    url = BASE + month_slug(month)
    for name, (sub, label), body in entries(page):
        names = SPLIT.get(name, (name,))
        for n in names:
            ent = country(n, month, unmatched)
            if not ent:
                continue
            out.append((ent, f"cw:{month.isoformat()[:7]}:{ent}", "crisiswatch", sub, f"CrisisWatch: {label}",
                        month, None, "month", None, None, None, None, None, name if name != n else None, url, body[:4000]))
    return out
