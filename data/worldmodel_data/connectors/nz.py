"""New Zealand pack: extra New Zealand sources that need no key.

rbnz
    Reserve Bank of New Zealand statistics spreadsheets (rbnz.govt.nz/statistics):
    B1 exchange rates (monthly), B2 wholesale interest rates (monthly close: the
    official cash rate, bank bills, government bonds), B3 retail interest rates and
    B20 mortgage rates. The site sits behind Cloudflare, which often turns away
    programs, so each file is tried and, if refused, the refresh says how to load
    them by hand: download them in a browser into one folder and run
    `.\\load.bat rbnz <folder>`.

    Every RBNZ spreadsheet has the same layout: a "Series Definitions" sheet (one row
    per series: Group, Series, Unit, Series Id ...) and a "Data" sheet with a few
    header rows (one of them the series ids) and then one row per date. Every series
    in the files becomes its own indicator (rbnz_<series id>), averaged over each
    year; a few headline series get friendly ids and are switched on in the menus,
    the rest are listed on the Indicators page switched off.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, indicator, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)

RBNZ_FILES = {  # file name (without .xlsx) -> table code
    "hb1-monthly": "b1", "hb2-monthly-close": "b2", "hb3": "b3", "hb20": "b20",
}
RBNZ_URL = "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/{letter}/{code}/{name}.xlsx"
RBNZ_PAGE = "https://www.rbnz.govt.nz/statistics"
# Headline series: a pattern on "group series" (lower case) -> (indicator id, name, description).
RBNZ_HEADLINE = [
    (r"official cash rate", "rbnz_ocr", "Official cash rate (RBNZ)",
     "The Reserve Bank of New Zealand's official cash rate, yearly average of month-end rates."),
    (r"90.?day", "rbnz_bill_90d", "90-day bank bill rate (NZ)",
     "New Zealand 90-day bank bill yield, yearly average."),
    (r"10.?year", "rbnz_govt_bond_10y", "10-year government bond yield (NZ)",
     "New Zealand government 10-year bond yield, yearly average of month-end closes."),
    (r"\btwi\b|trade.?weighted", "rbnz_twi", "Trade-weighted index of the NZ dollar",
     "The New Zealand dollar against a basket of trading partners' currencies (TWI), yearly average."),
    (r"united states dollar|\busd\b", "rbnz_nzd_usd", "NZ dollar in US dollars",
     "US dollars per New Zealand dollar, yearly average of monthly averages (RBNZ)."),
    (r"floating", "rbnz_mortgage_floating", "Floating mortgage rate (NZ)",
     "Standard floating first-mortgage interest rate for new borrowers, yearly average."),
    (r"2.?year", "rbnz_mortgage_2y", "2-year fixed mortgage rate (NZ)",
     "Standard 2-year fixed mortgage interest rate for new borrowers, yearly average."),
]


def _cell_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.match(r"\s*(\d{4})-(\d{2})", str(v or ""))
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))  # dd/mm/yyyy
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def read_rbnz(path: Path) -> list[dict]:
    """One RBNZ spreadsheet as series: id, group, name, unit, points [(date, value)]."""
    sheets = xlsx_sheet_names(path)
    defs_name = next((s for s in sheets if "definition" in s.lower()), None)
    data_name = next((s for s in sheets if s.strip().lower() == "data"), None)
    if not defs_name or not data_name:
        raise ConnectorError(f"rbnz: {path.name} has no 'Series Definitions' and 'Data' sheets; is it an RBNZ "
                             "statistics spreadsheet?")
    defs = xlsx_rows(path, defs_name)
    head = [key(c) for c in defs[0]]
    gi, si, ui, ii = (head.index(k) if k in head else None for k in ("group", "series", "unit", "seriesid"))
    if ii is None:
        raise ConnectorError(f"rbnz: no 'Series Id' column in {path.name}'s definitions")
    meta = []
    for r in defs[1:]:
        if len(r) > ii and r[ii]:
            meta.append({"id": str(r[ii]).strip(), "group": str(r[gi] or "") if gi is not None else "",
                         "name": str(r[si] or "") if si is not None else str(r[ii]),
                         "unit": str(r[ui] or "") if ui is not None and len(r) > ui else "", "points": []})
    rows = xlsx_rows(path, data_name)
    ids = {m["id"]: m for m in meta}
    # The header row that holds the series ids maps columns; else the definitions' order.
    cols: dict[int, dict] = {}
    start = 0
    for i, r in enumerate(rows[:12]):
        hits = {j: ids[str(c).strip()] for j, c in enumerate(r) if str(c or "").strip() in ids}
        if len(hits) >= max(1, len(meta) // 2):
            cols, start = hits, i + 1
            break
    if not cols:
        cols = {j + 1: m for j, m in enumerate(meta)}
        start = next((i for i, r in enumerate(rows) if r and _cell_date(r[0])), len(rows))
    for r in rows[start:]:
        d = _cell_date(r[0]) if r else None
        if not d:
            continue
        for j, m in cols.items():
            if j < len(r):
                v = num(r[j])
                if v is not None:
                    m["points"].append((d, v))
    return meta


class RBNZ(Connector):
    source_id = "rbnz"
    pack = "nz"
    fetch_every_days = 7

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got, refused = [], []
        for name, code in RBNZ_FILES.items():
            url = RBNZ_URL.format(letter=code[0], code=code, name=name)
            try:
                self.get(url, raw_dir / f"{name}.xlsx")
                if (raw_dir / f"{name}.xlsx").read_bytes()[:2] != b"PK":  # a challenge page, not a spreadsheet
                    (raw_dir / f"{name}.xlsx").unlink()
                    raise ConnectorError("not a spreadsheet")
                got.append(url)
            except ConnectorError as exc:
                refused.append(f"{name} ({exc})")
        if not got:
            raise ConnectorError(
                "rbnz: the Reserve Bank's website turned the download away (it blocks most programs). Download "
                f"these from {RBNZ_PAGE} in your browser into one folder: B1 exchange rates (monthly), B2 wholesale "
                r"interest rates (monthly close), B3 retail interest rates and B20 mortgage rates; then run: "
                r".\load.bat rbnz <folder>")
        if refused:
            log.warning("rbnz: not downloaded: %s", "; ".join(refused))
        return " ".join(got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"rbnz: no .xlsx files in {raw_dir}")
        rows, listed, used = Rows(), [], set()
        for p in files:
            try:
                series = read_rbnz(p)
            except ConnectorError as exc:
                log.warning("%s", exc)
                continue
            table = next((c.upper() for n, c in RBNZ_FILES.items() if p.stem.lower().startswith(n)), p.stem)
            for s in series:
                if not s["points"]:
                    continue
                text = f"{s['group']} {s['name']}".lower()
                head = next((h for h in RBNZ_HEADLINE if re.search(h[0], text)), None)
                # A headline id goes to the first series that matches it (the B20 2-year rate, not the B2 bond).
                if head and head[1] in used:
                    head = None
                if head and head[1] in ("rbnz_mortgage_floating", "rbnz_mortgage_2y") and "mortgage" not in text \
                        and table != "B20":
                    head = None
                if head and head[1] == "rbnz_govt_bond_10y" and "bond" not in text and "government" not in text:
                    head = None
                if head and head[1] == "rbnz_nzd_usd" and table != "B1":
                    head = None
                ind = head[1] if head else "rbnz_" + re.sub(r"[^a-z0-9]+", "_", s["id"].lower()).strip("_")
                if ind in used:
                    continue
                used.add(ind)
                for d, v in s["points"]:
                    rows.add_period("iso3", "NZL", ind, d.year, v)
                name = head[2] if head else f"{s['group']}: {s['name']}".strip(": ") + " (RBNZ)"
                desc = head[3] if head else f"RBNZ table {table}, series {s['id']}: {s['group']} – {s['name']}. Yearly average."
                listed.append(indicator(ind, name, desc, s["unit"] or "", "finance", self.source_id,
                                        f"{table}:{s['id']}", decimals=2, default_on=bool(head)))
        rows.finish_periods(need=1)
        if not len(rows):
            raise ConnectorError("rbnz: no series read; are these RBNZ statistics spreadsheets (B1, B2, B3, B20)?")
        self.listed_indicators = listed
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------------- Corrections
CORRECTIONS_INDEX = "https://www.corrections.govt.nz/resources/statistics/quarterly_prison_statistics"
CORRECTIONS_SITE = "https://www.corrections.govt.nz"
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
QUARTER_LINK = re.compile(r"""href=["']([^"']*quarterly_prison_statistics/[^"']*?(march|june|september|december)[_-]?(\d{4})[^"']*)["']""",
                          re.I)
# Row label (start, lower case) -> indicator; columns found by their headings.
PRISON_ROWS = {"grand total": "", "total male": "_male", "total female": "_female"}
PRISON_COLS = {"remand accused": "remand_accused", "remand convicted": "remand_convicted", "sentenced": "sentenced",
               "total population": "total"}


def html_tables(text: str) -> list[list[list[str]]]:
    """Every table in an HTML page as rows of cell texts."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables, self.row, self.cell = [], None, None

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.tables.append([])
            elif tag == "tr" and self.tables:
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = []

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
                self.cell = None
            elif tag == "tr" and self.row is not None and self.tables:
                self.tables[-1].append(self.row)
                self.row = None

        def handle_data(self, data):
            if self.cell is not None:
                self.cell.append(data)

    p = P()
    p.feed(text)
    return p.tables


def read_prison_page(text: str) -> dict[str, float]:
    """The custody table of a Corrections quarterly page: indicator suffix -> count."""
    out: dict[str, float] = {}
    for table in html_tables(text):
        head = next((r for r in table if any("sentenced" in c.lower() for c in r)), None)
        if not head:
            continue
        cols = {}
        for j, c in enumerate(head):
            k = next((v for h, v in PRISON_COLS.items() if c.lower().startswith(h)), None)
            if k and k not in cols.values():
                cols[j] = k
        for r in table:
            label = (r[0] if r else "").lower()
            suffix = next((v for h, v in PRISON_ROWS.items() if label.startswith(h)), None)
            if suffix is None:
                continue
            for j, k in cols.items():
                if j < len(r) and (v := num(r[j])) is not None:
                    out[f"{k}{suffix}"] = v
    return out


class NZCorrections(Connector):
    """Department of Corrections quarterly prison statistics: people in prison at the
    end of each quarter by custody status (remand accused, remand convicted,
    sentenced) and sex. Each fetch (every four weeks) reads the index and the newest
    20 quarterly pages it links to (five years), a second apart; pages that have not
    changed since the last fetch are not downloaded again (the server is asked "changed
    since?"). A year's figure is its latest quarter (usually 31 December)."""

    source_id = "nz_corrections"
    pack = "nz"
    fetch_every_days = 28
    BACKFILL = 20

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def quarter_links(self) -> list[tuple[date, str]]:
        r = self.client.get(CORRECTIONS_INDEX)
        r.raise_for_status()
        found = {}
        for url, month, year in QUARTER_LINK.findall(r.text):
            d = date(int(year), MONTHS[month.lower()], 1)
            found.setdefault(d, url if url.startswith("http") else CORRECTIONS_SITE + url)
        return sorted(found.items(), reverse=True)

    def download(self, raw_dir: Path, release: str) -> str:
        import time

        try:
            links = self.quarter_links()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"nz_corrections: the quarterly statistics index could not be read ({exc})")
        if not links:
            raise ConnectorError(f"nz_corrections: no quarterly pages linked from {CORRECTIONS_INDEX}")
        for i, (d, url) in enumerate(links[: self.BACKFILL]):
            if i:
                time.sleep(1)
            try:
                self.get(url, raw_dir / f"prisons_{d.isoformat()[:7]}.html")
            except ConnectorError as exc:
                log.warning("nz_corrections: %s not read (%s)", url, exc)
        return CORRECTIONS_INDEX

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, latest = Rows(), {}
        for p in sorted(raw_dir.glob("prisons_*.html")):
            m = re.search(r"(\d{4})-(\d{2})", p.name)
            if not m:
                continue
            got = read_prison_page(p.read_text(encoding="utf-8", errors="replace"))
            y, mo = int(m.group(1)), int(m.group(2))
            if got and (y not in latest or mo > latest[y][0]):
                latest[y] = (mo, got)
        for y, (_, got) in latest.items():
            for k, v in got.items():
                rows.add("iso3", "NZL", f"nz_prisoners_{k}", y, v)
        if not len(rows):
            raise ConnectorError("nz_corrections: no custody table found on the quarterly pages")
        names = {"total": "People in prison", "remand_accused": "People in prison on remand, not yet convicted",
                 "remand_convicted": "People in prison on remand, convicted awaiting sentence",
                 "sentenced": "People in prison serving a sentence"}
        self.listed_indicators = []
        for k, n in names.items():
            for suffix, who in (("", ""), ("_male", " (men)"), ("_female", " (women)")):
                ind = f"nz_prisoners_{k}{suffix}"
                self.listed_indicators.append(indicator(
                    ind, f"{n}{who} (NZ)", f"{n}{who} at the end of the year's latest quarter (usually 31 December). "
                    "Department of Corrections quarterly prison statistics.", "persons", "justice", self.source_id,
                    f"prison_stats:{k}{suffix}", decimals=0, default_on=(k == "total" or k.startswith("remand")) and not suffix))
        return rows.stage(con, self.source_id, vintage)
