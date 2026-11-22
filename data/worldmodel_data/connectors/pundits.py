"""Pundits: named forecasters and their calls, from Prediction Archive (predictionarchive.com).

Prediction Archive collects predictions that named people and bodies made in articles,
podcasts and speeches, and grades each one with an AI reader against later reporting:
Correct, Incorrect, Indeterminate (cannot tell) or Pending (not yet due). The site turns
programs away and has no download or API, so its pages are saved by hand (Ctrl+S in the
browser, or .\\verify.bat prediction_archive) into var/manual/prediction_archive/, and every
saved page is loaded together.

Four kinds of page are read, told apart by the small heading above the title:

- Ranking ("Top Predictors"): each forecaster's rank, accuracy and counts.
- Predictor: one forecaster's counts, the site's note on who they are, and a page of their
  calls (25 a page; the Pending filter lists open ones with their next check date).
- Prediction: one call in full: the words used, the source, the time horizon, the grade,
  the reasoning behind it and when it was graded.
- Search results: calls whose words match (for example "New Zealand"), without grades.

A call seen on several pages is one call: later pages fill in what earlier ones lacked.
Calls are keyed by forecaster and title (a saved prediction page does not carry its own
address), and keep the site's prediction id when a list page gave it.
"""

from __future__ import annotations

import html as htmlmod
import re
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS

SITE = "https://predictionarchive.com"
RANKING = f"{SITE}/top-predictors"
SEARCH = f"{SITE}/search?q={{q}}&type=prediction"
PAGE_SUFFIXES = (".htm", ".html", ".xhtml")
OUTCOMES = {"correct": "correct", "incorrect": "incorrect", "indeterminate": "indeterminate", "pending": "pending"}

_TAG = re.compile(r"<[^>]+>")
_KIND = re.compile(r"<header[^>]*>\s*<small>\s*([A-Za-z ]+?)\s*</small>\s*<h1>([\s\S]*?)</h1>", re.I)
_PREDICTOR_HREF = re.compile(r"/predictors/([0-9a-f-]{36})/detail")
_PREDICTION_HREF = re.compile(r"/predictions/([0-9a-f-]{36})/detail")
_LIST_ITEM = re.compile(r"<li class=\"list-item-row\">([\s\S]*?)</li>", re.I)
_LONG_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def text(s: str | None) -> str:
    """Plain text of an HTML fragment, spaces collapsed."""
    return re.sub(r"\s+", " ", htmlmod.unescape(_TAG.sub(" ", s or ""))).strip()


def day(s: str | None) -> date | None:
    """A date from 'June 19, 2026', 'Jun 09, 2011' or '11/22/2026'."""
    s = (s or "").strip().rstrip(".")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def num(s: str | None) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def title_key(title: str) -> str:
    """Titles differ in capitals between pages (the prediction page title-cases them)."""
    return re.sub(r"[^a-z0-9]+", "", htmlmod.unescape(title).lower().replace("’", "'"))


def call_key(predictor_id: str | None, predictor: str | None, title: str) -> str:
    who = predictor_id or re.sub(r"[^a-z0-9]+", "-", (predictor or "unknown").lower()).strip("-")
    return f"pa:{who}:{title_key(title)}"


def page_kind(html: str) -> tuple[str | None, str]:
    """('ranking' | 'predictor' | 'prediction' | 'search' | None, the page's h1 text)."""
    m = _KIND.search(html)
    if not m:
        return None, ""
    small, h1 = m.group(1).strip().lower(), text(m.group(2))
    kind = {"ranking": "ranking", "predictor": "predictor", "prediction": "prediction", "search": "search"}.get(small)
    return kind, h1


def _data_item(html: str, key: str) -> str | None:
    """The value of a 'data-key' row on a prediction page (raw HTML)."""
    m = re.search(r"<div class=\"data-key\">\s*" + re.escape(key) + r"\s*:?\s*</div>\s*<div class=\"data-value\">([\s\S]*?)</div>\s*</div>",
                  html, re.I)
    return m.group(1) if m else None


def _badge(fragment: str) -> tuple[str | None, date | None]:
    """(outcome, next check) from a list item's or a page's badge."""
    m = re.search(r"<span class=\"badge\"[^>]*>([\s\S]*?)</span>", fragment)
    if not m:
        return None, None
    label = text(m.group(1))
    if label.lower().startswith("next eval"):
        return "pending", day(label.split(":", 1)[-1])
    return OUTCOMES.get(label.lower()), None


def list_items(html: str) -> list[dict]:
    """Calls listed on a predictor page or a search page."""
    out = []
    for m in _LIST_ITEM.finditer(html):
        li = m.group(1)
        pid = _PREDICTION_HREF.search(li)
        if not pid:
            continue  # a forecaster in search results
        title_m = re.search(r"<a [^>]*class=\"list-item-header-text\"[^>]*>([\s\S]*?)</a>", li) or \
            re.search(r"<a [^>]*>([\s\S]*?)</a>", li)
        title = text(title_m.group(1)) if title_m else ""
        if not title:
            continue
        outcome, next_check = _badge(li.split("list-item-meta-row")[0])
        by = re.search(r"by\s*<a href=\"[^\"]*/predictors/([0-9a-f-]{36})/detail\"[^>]*>([\s\S]*?)</a>\s*(?:&mdash;|—|-)\s*([A-Z][a-z]{2,} \d{1,2}, \d{4})", li)
        out.append({"prediction_id": pid.group(1), "title": title, "outcome": outcome, "next_check": next_check,
                    "predictor_id": by.group(1) if by else None, "predictor": text(by.group(2)) if by else None,
                    "made": day(by.group(3)) if by else None})
    return out


def parse_prediction(html: str) -> dict | None:
    """One call in full, from a saved prediction page."""
    kind, title = page_kind(html)
    if kind != "prediction" or not title:
        return None
    by = re.search(r"Predicted By\s*<a href=\"[^\"]*/predictors/([0-9a-f-]{36})/detail\"[^>]*>([\s\S]*?)</a>\s*on\s*([A-Z][a-z]+ \d{1,2}, \d{4})", html)
    outcome_html = re.search(r"prediction-outcome\">[\s\S]*?<div class=\"data-value\">([\s\S]*?)</div>", html)
    outcome, _ = _badge(outcome_html.group(1)) if outcome_html else (None, None)
    src = _data_item(html, "Prediction Source") or ""
    src_a = re.search(r"<a href=\"(https?://[^\"]+)\"[^>]*>([\s\S]*?)</a>", src)
    web = re.search(r"/web-content/([0-9a-f-]{36})/detail", src)
    horizon = text(_data_item(html, "Time Horizon"))
    evaluated = re.search(r"evaluation-date\">\s*Evaluated on\s*([^<]+)<", html)
    reasoning = re.search(r"<p class=\"evaluation-reasoning\">([\s\S]*?)</p>", html)
    next_check = re.search(r"next check is scheduled for\s*([A-Z][a-z]+ \d{1,2}, \d{4})", html)
    sources = re.search(r"<div class=\"evaluation-sources\">([\s\S]*?)</div>", html)
    return {
        "title": title, "predictor_id": by.group(1) if by else None, "predictor": text(by.group(2)) if by else None,
        "made": day(by.group(3)) if by else None, "outcome": outcome,
        "verbatim": text(_data_item(html, "Verbatim Statement")) or None,
        "source_url": src_a.group(1) if src_a else None, "source_title": text(src_a.group(2)) if src_a else None,
        "web_content_id": web.group(1) if web else None,
        "horizon": None if not horizon or horizon.lower().startswith("no time horizon") else horizon,
        "evaluated": day(evaluated.group(1)) if evaluated else None,
        "reasoning": text(reasoning.group(1)) or None if reasoning else None,
        "checked_against": len(re.findall(r"<a href=\"https?://", sources.group(1))) if sources else None,
        "next_check": day(next_check.group(1)) if next_check else None,
    }


def parse_predictor(html: str) -> dict | None:
    """One forecaster's counts, note and listed calls, from a saved predictor page."""
    kind, name = page_kind(html)
    if kind != "predictor" or not name:
        return None
    ids = [m.group(1) for m in re.finditer(r"@get\('/predictors/([0-9a-f-]{36})/detail", html)]
    ids += [m.group(1) for m in _PREDICTOR_HREF.finditer(html)]
    pid = max(set(ids), key=ids.count) if ids else None
    about = re.search(r"<h2 class=\"section-title\">About</h2>[\s\S]*?<div class=\"data-value\">([\s\S]*?)</div>", html)

    def stat(label: str) -> str | None:
        m = re.search(r"<div class=\"stat-label\">\s*" + label + r"([\s\S]*?)</article>", html)
        return m.group(1) if m else None

    acc, ev, tot = stat(r"Accuracy %\s*</div>"), stat(r"Evaluated"), stat(r"Total Predictions\s*</div>")

    def breakdown(word: str) -> float | None:
        m = re.search(word + r"</span>\s*<span[^>]*>\s*([\d,]+)\s*</span>", ev or "")
        return num(m.group(1)) if m else None

    pending = re.search(r"([\d,]+)\s*Pending Evaluation", tot or "")
    total = re.search(r"stat-value\">\s*([\d,]+)", tot or "")
    accuracy = re.search(r"stat-value\">\s*([\d.]+)%", acc or "")
    evaluated = re.search(r"\(([\d,]+)\)", ev or "")
    items = list_items(html)
    for it in items:
        it["predictor_id"] = it["predictor_id"] or pid
        it["predictor"] = it["predictor"] or name
    return {
        "predictor_id": pid, "name": name, "about": text(about.group(1)) if about else None,
        "accuracy": float(accuracy.group(1)) / 100 if accuracy else None,
        "correct": breakdown("Correct"), "incorrect": breakdown("Incorrect"), "indeterminate": breakdown("Indeterminate"),
        "evaluated": num(evaluated.group(1)) if evaluated else None,
        "total": num(total.group(1)) if total else None, "pending": num(pending.group(1)) if pending else None,
        "calls": items,
    }


def parse_ranking(html: str) -> list[dict]:
    """The Top Predictors table: rank, forecaster, accuracy and counts."""
    kind, _ = page_kind(html)
    if kind != "ranking":
        return []
    out = []
    for row in re.finditer(r"<tr>([\s\S]*?)</tr>", html):
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row.group(1))
        if len(cells) < 8:
            continue
        who = _PREDICTOR_HREF.search(cells[1])
        acc = num(cells[2])
        out.append({"rank": int(num(cells[0]) or 0) or None, "predictor_id": who.group(1) if who else None,
                    "name": text(cells[1]), "accuracy": acc / 100 if acc is not None else None,
                    "evaluated": num(cells[3]), "correct": num(cells[4]), "incorrect": num(cells[5]),
                    "indeterminate": num(cells[6]), "total": num(cells[7])})
    return out


def parse_search(html: str) -> tuple[str, list[dict]]:
    """(the words searched for, the calls listed)."""
    kind, _ = page_kind(html)
    if kind != "search":
        return "", []
    q = re.search(r"Showing Results for:\s*<strong>([\s\S]*?)</strong>", html)
    return text(q.group(1)) if q else "", list_items(html)


def read_folder(folder: Path) -> tuple[list[dict], list[dict], list[str]]:
    """(forecasters, calls, notes on pages that could not be read) from every saved page in a folder."""
    pages = sorted((f for f in Path(folder).iterdir() if f.is_file() and f.suffix.lower() in PAGE_SUFFIXES),
                   key=lambda f: (f.stat().st_mtime, f.name))
    people: dict[str, dict] = {}
    calls: dict[str, dict] = {}
    alias: dict[str, str] = {}   # site prediction id -> call key
    notes: list[str] = []

    def merge(into: dict, new: dict) -> None:
        for k, v in new.items():
            if v not in (None, ""):
                into[k] = v

    def add_person(p: dict, seen: date, page: str) -> None:
        key = p.get("predictor_id") or f"name:{p['name'].lower()}"
        row = people.setdefault(key, {"predictor_id": p.get("predictor_id"), "name": p["name"]})
        merge(row, {k: v for k, v in p.items() if k != "calls"})
        row["seen"], row["page"] = seen, page

    def add_call(c: dict, seen: date, page: str, detail: bool) -> None:
        key = alias.get(c.get("prediction_id") or "") or call_key(c.get("predictor_id"), c.get("predictor"), c["title"])
        row = calls.get(key)
        if row is None:
            row = calls[key] = {"call_key": key}
        if c.get("prediction_id"):
            alias[c["prediction_id"]] = key
        if detail:
            row["title_full"] = c["title"]
        merge(row, {k: v for k, v in c.items() if k != "title" or "title" not in row or not detail})
        row["seen"] = seen
        row.setdefault("first_seen", seen)
        row["page"] = page

    for f in pages:
        try:
            html = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(f"{f.name}: {exc}")
            continue
        seen = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).date()
        kind, _ = page_kind(html)
        if kind == "ranking":
            for p in parse_ranking(html):
                add_person(p, seen, f.name)
        elif kind == "predictor":
            p = parse_predictor(html)
            if p:
                add_person(p, seen, f.name)
                for c in p["calls"]:
                    add_call(c, seen, f.name, False)
        elif kind == "prediction":
            c = parse_prediction(html)
            if c:
                add_call(c, seen, f.name, True)
                if c.get("predictor"):
                    key = c.get("predictor_id") or f"name:{c['predictor'].lower()}"
                    people.setdefault(key, {"predictor_id": c.get("predictor_id"), "name": c["predictor"], "seen": seen, "page": f.name})
        elif kind == "search":
            _, items = parse_search(html)
            for c in items:
                add_call(c, seen, f.name, False)
        else:
            notes.append(f"{f.name}: not a Prediction Archive page the app knows (ranking, forecaster, prediction or search)")
    # A list page and a prediction page differ only in capitals: keep the list's (sentence case).
    for row in calls.values():
        row.setdefault("title", row.get("title_full", ""))
        row.pop("title_full", None)
    return list(people.values()), list(calls.values()), notes


class PredictionArchive(Connector):
    source_id = "prediction_archive"
    manual = True
    keeps_files = True  # every saved page is loaded together

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("prediction_archive: saved by hand (the site turns programs away); "
                             "save pages into var\\manual\\prediction_archive or run .\\verify.bat prediction_archive")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        people, calls, notes = read_folder(Path(raw_dir))
        if not people and not calls:
            why = "; ".join(notes[:3]) or "no saved .htm or .html pages"
            raise ConnectorError(f"prediction_archive: nothing read from {raw_dir} ({why})")
        con.execute("""CREATE TABLE ps (predictor_id VARCHAR, name VARCHAR, about VARCHAR, rank INTEGER, accuracy DOUBLE,
            correct DOUBLE, incorrect DOUBLE, indeterminate DOUBLE, evaluated DOUBLE, total DOUBLE, pending DOUBLE,
            seen DATE, page VARCHAR)""")
        con.executemany("INSERT INTO ps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (p.get("predictor_id"), p["name"], p.get("about"), p.get("rank"), p.get("accuracy"), p.get("correct"),
             p.get("incorrect"), p.get("indeterminate"), p.get("evaluated"), p.get("total"), p.get("pending"),
             p.get("seen"), p.get("page")) for p in people])
        con.execute("""CREATE TABLE pc (call_key VARCHAR, prediction_id VARCHAR, predictor_id VARCHAR, predictor VARCHAR,
            title VARCHAR, made DATE, outcome VARCHAR, next_check DATE, evaluated DATE, verbatim VARCHAR, reasoning VARCHAR,
            checked_against INTEGER, source_url VARCHAR, source_title VARCHAR, web_content_id VARCHAR, horizon VARCHAR,
            first_seen DATE, seen DATE, page VARCHAR)""")
        con.executemany(f"INSERT INTO pc VALUES ({', '.join('?' * 19)})", [
            (c["call_key"], c.get("prediction_id"), c.get("predictor_id"), c.get("predictor"), c.get("title"), c.get("made"),
             c.get("outcome"), c.get("next_check"), c.get("evaluated"), c.get("verbatim"), c.get("reasoning"),
             c.get("checked_against"), c.get("source_url"), c.get("source_title"), c.get("web_content_id"), c.get("horizon"),
             c.get("first_seen"), c.get("seen"), c.get("page")) for c in calls if c.get("title")])
        self.history_queries = {"pundit_scores": "SELECT * FROM ps", "pundit_calls": "SELECT * FROM pc"}
        return EMPTY_OBSERVATIONS
