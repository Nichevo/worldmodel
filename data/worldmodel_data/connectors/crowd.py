"""Crowd forecasts: Polymarket, Metaculus and Manifold questions, and ViEWS conflict forecasts.

The three sites are read the same way: the open questions in the categories chosen in Settings
(and recently resolved ones, so forecasts can be scored), plus the full history of the questions
you follow and the busiest ones. Each refresh saves every open question's chance, and each
vintage carries everything saved before it (questions.json.gz, points.csv.gz, comments.json.gz,
mine.json.gz), so the latest vintage alone holds the whole history, and only the last few
vintages are kept on disk (keep_vintages).

stage() reads those files; when a folder has only pages as the sites send them (files named
<site>_page_*.json, as in the test fixtures or a hand-saved copy), it merges them first.

Reading is polite: one request at a time with a gap, stopping at the first refusal.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from worldmodel_contract import crowd, local
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS

log = logging.getLogger(__name__)

QUESTIONS, POINTS, COMMENTS, MINE = "questions.json.gz", "points.csv.gz", "comments.json.gz", "mine.json.gz"
POINT_FIELDS = ["question_key", "at", "chance", "lower", "upper", "origin"]
TRACK = 60          # busiest questions per site whose full history is read (besides those you follow)
COMMENTED = 30      # questions per refresh whose Metaculus comments are read (followed ones first)
MOVE = 0.005        # a refresh saves a question's chance when it moved at least this much...
QUIET_DAYS = 7      # ...or this many days have passed since the last save


# ----------------------------------------------------------------------------- small helpers
def ts(v) -> str | None:
    """An ISO timestamp (UTC, seconds) from seconds, milliseconds or an ISO string."""
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace(".", "", 1).isdigit()):
            x = float(v)
            if x > 1e11:
                x /= 1000.0
            return datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OverflowError, OSError):
        return None


def fnum(v) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def jlist(v) -> list:
    """Polymarket sends some lists as JSON text."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.startswith("["):
        try:
            return json.loads(v)
        except ValueError:
            return []
    return []


def read_gz_json(path: Path, default):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return default


def write_gz_json(path: Path, data) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)


def read_points(path: Path) -> list[dict]:
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            return [{**r, "chance": fnum(r["chance"]), "lower": fnum(r.get("lower")), "upper": fnum(r.get("upper"))}
                    for r in csv.DictReader(f)]
    except (FileNotFoundError, OSError):
        return []


def write_points(path: Path, points: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=POINT_FIELDS, extrasaction="ignore")
    w.writeheader()
    for p in sorted(points, key=lambda p: (p["question_key"], p["at"])):
        w.writerow({k: ("" if p.get(k) is None else p[k]) for k in POINT_FIELDS})
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def insert(con: duckdb.DuckDBPyConnection, sql: str, rows: list) -> None:
    if rows:
        con.executemany(sql, rows)


def daily(points: list[dict]) -> list[dict]:
    """At most one point per question, origin and day (the last of the day)."""
    keep: dict[tuple, dict] = {}
    for p in sorted(points, key=lambda p: p["at"]):
        keep[(p["question_key"], p.get("origin"), p["at"][:10])] = p
    return list(keep.values())


# ----------------------------------------------------------------------------- Polymarket
def pm_markets(events: list[dict]) -> list[dict]:
    """Questions from Gamma API events: one binary question per market ("Will X win?")."""
    out = []
    for ev in events:
        tags = [t.get("slug") or "" for t in ev.get("tags") or [] if isinstance(t, dict)]
        for m in ev.get("markets") or []:
            title = (m.get("question") or "").strip()
            if not title or not m.get("id"):
                continue
            outcomes = [str(x) for x in jlist(m.get("outcomes"))]
            prices = [fnum(x) for x in jlist(m.get("outcomePrices"))]
            binary = [o.lower() for o in outcomes] == ["yes", "no"]
            closed = bool(m.get("closed"))
            resolution = None
            if closed and binary and len(prices) == 2 and None not in prices:
                resolution = "yes" if prices[0] >= 0.99 else "no" if prices[1] >= 0.99 else None
            tokens = jlist(m.get("clobTokenIds"))
            out.append({
                "key": f"polymarket:{m['id']}", "site": "polymarket", "site_id": str(m["id"]), "title": title,
                "url": f"https://polymarket.com/event/{ev.get('slug') or m.get('slug')}", "kind": "binary" if binary else "multiple",
                "tags": tags, "created": ts(m.get("createdAt") or m.get("startDate")), "closes": ts(m.get("endDate") or ev.get("endDate")),
                "resolved_at": ts(m.get("closedTime")) if resolution else None,
                "status": "resolved" if resolution else "closed" if closed else "open", "resolution": resolution,
                "chance": prices[0] if binary and prices and not closed else None,
                "volume": fnum(m.get("volumeNum") or m.get("volume")), "forecasters": None, "comments": None,
                "description": (m.get("description") or ev.get("description") or "")[:1500],
                "options": None if binary else [[o, p] for o, p in zip(outcomes, prices)],
                "token": tokens[0] if tokens else None,
            })
    return out


def pm_history(data: dict) -> list[tuple[str, float]]:
    return [(ts(h.get("t")), fnum(h.get("p"))) for h in (data or {}).get("history") or [] if ts(h.get("t")) and fnum(h.get("p")) is not None]


# ----------------------------------------------------------------------------- Metaculus
def mc_scale(c, q: dict) -> float | None:
    """A Metaculus location (0 to 1 on the question's own scale) as a value."""
    c = fnum(c)
    s = q.get("scaling") or {}
    lo, hi, zero = fnum(s.get("range_min")), fnum(s.get("range_max")), fnum(s.get("zero_point"))
    if c is None or lo is None or hi is None:
        return c
    if zero is not None and zero != lo:
        r = (hi - zero) / (lo - zero)
        if r > 0 and r != 1:
            return lo + (hi - lo) * (r ** c - 1) / (r - 1)
    return lo + (hi - lo) * c


def _mc_point(entry: dict, q: dict, kind: str) -> tuple[float | None, float | None, float | None]:
    centers = entry.get("centers") or []
    if kind == "binary":
        fv = entry.get("forecast_values") or []
        p = fnum(fv[1]) if len(fv) == 2 else fnum(centers[0]) if centers else fnum(entry.get("probability_yes"))
        return p, None, None
    if kind in ("numeric", "date", "discrete"):
        lo = (entry.get("interval_lower_bounds") or [None])[0]
        hi = (entry.get("interval_upper_bounds") or [None])[0]
        return mc_scale(centers[0] if centers else None, q), mc_scale(lo, q), mc_scale(hi, q)
    return None, None, None


def mc_question(post: dict) -> tuple[dict | None, list[dict], list[dict]]:
    """One post: its question, its community history points and your forecasts (if the token's
    user forecast on it). Group posts (several questions) are left out."""
    q = post.get("question")
    if not isinstance(q, dict) or not post.get("id"):
        return None, [], []
    kind = {"binary": "binary", "numeric": "numeric", "discrete": "numeric", "date": "date",
            "multiple_choice": "multiple"}.get(q.get("type") or "", "other")
    key = f"metaculus:{post['id']}"
    agg = ((q.get("aggregations") or {}).get("recency_weighted") or {})
    latest = agg.get("latest") or {}
    chance, lower, upper = _mc_point(latest, q, kind) if latest else (None, None, None)
    projects = post.get("projects") or {}
    tags = [p.get("slug") or "" for k in ("category", "tag", "topic") for p in projects.get(k) or [] if isinstance(p, dict)]
    status = post.get("status") or q.get("status") or "open"
    res = q.get("resolution")
    resolution = None if res in (None, "") else str(res).lower()
    options = None
    if kind == "multiple" and latest.get("forecast_values"):
        options = [[o, fnum(v)] for o, v in zip(q.get("options") or [], latest["forecast_values"])]
    rec = {
        "key": key, "site": "metaculus", "site_id": str(post["id"]), "title": (post.get("title") or q.get("title") or "").strip(),
        "url": f"https://www.metaculus.com/questions/{post['id']}/", "kind": kind, "tags": tags,
        "created": ts(post.get("published_at") or post.get("created_at")),
        "closes": ts(q.get("scheduled_close_time") or post.get("scheduled_close_time")),
        "resolved_at": ts(q.get("actual_resolve_time") or post.get("actual_resolve_time")) if resolution else None,
        "status": "resolved" if resolution else "closed" if status == "closed" else "open", "resolution": resolution,
        "chance": chance, "lower": lower, "upper": upper, "volume": None,
        "forecasters": post.get("nr_forecasters") or q.get("nr_forecasters"), "comments": post.get("comment_count"),
        "description": (q.get("description") or post.get("description") or "")[:1500], "options": options,
    }
    pts = []
    for h in agg.get("history") or []:
        c, lo, hi = _mc_point(h, q, kind)
        at = ts(h.get("start_time"))
        if at and c is not None:
            pts.append({"question_key": key, "at": at, "chance": c, "lower": lo, "upper": hi, "origin": "site"})
    mine = []
    for h in ((q.get("my_forecasts") or {}).get("history") or []):
        c, _, _ = _mc_point(h, q, kind)
        at = ts(h.get("start_time"))
        if at and c is not None and kind == "binary":
            mine.append({"question_key": key, "at": at, "chance": c})
    return rec, pts, mine


def mc_comments(key: str, results: list[dict]) -> list[dict]:
    out = []
    for c in results or []:
        if not c.get("id") or not (c.get("text") or "").strip():
            continue
        f = c.get("included_forecast") or {}
        fv = f.get("forecast_values") or []
        forecast = fnum(fv[1]) if len(fv) == 2 else fnum(f.get("probability_yes"))
        author = c.get("author") or {}
        out.append({"question_key": key, "comment_id": f"metaculus:{c['id']}",
                    "parent_id": f"metaculus:{c['parent_id']}" if c.get("parent_id") else None,
                    "author": author.get("username") if isinstance(author, dict) else str(author),
                    "created": ts(c.get("created_at")), "votes": c.get("vote_score") or 0, "forecast": forecast,
                    "text": c["text"][:6000]})
    return out


def community_at(points: list[dict], key: str, at: str) -> float | None:
    """The community chance at a moment: the last site point at or before it."""
    best = None
    for p in points:
        if p["question_key"] == key and p.get("origin") == "site" and p["at"] <= at:
            if best is None or p["at"] > best["at"]:
                best = p
    return best["chance"] if best else None


# ----------------------------------------------------------------------------- Manifold
def mf_markets(markets: list[dict], topic: str | None = None) -> list[dict]:
    out = []
    for m in markets or []:
        if not m.get("id") or m.get("outcomeType") not in (None, "BINARY"):
            continue
        res = (m.get("resolution") or "").upper()
        resolution = {"YES": "yes", "NO": "no", "CANCEL": "annulled", "MKT": "partly"}.get(res) if m.get("isResolved") else None
        closes = ts(m.get("closeTime"))
        closed = bool(closes and closes < datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        out.append({
            "key": f"manifold:{m['id']}", "site": "manifold", "site_id": str(m["id"]), "title": (m.get("question") or "").strip(),
            "url": m.get("url") or f"https://manifold.markets/{m.get('creatorUsername', '')}/{m.get('slug', '')}",
            "kind": "binary", "tags": [t for t in [topic, *(m.get("groupSlugs") or [])] if t],
            "created": ts(m.get("createdTime")), "closes": closes,
            "resolved_at": ts(m.get("resolutionTime")) if resolution else None,
            "status": "resolved" if resolution else "closed" if closed else "open", "resolution": resolution,
            "chance": None if resolution else fnum(m.get("probability")), "volume": fnum(m.get("volume")),
            "forecasters": m.get("uniqueBettorCount"), "comments": None,
            "description": (m.get("textDescription") or "")[:1500], "options": None,
        })
    return out


# ----------------------------------------------------------------------------- merging
def keep_question(q: dict, follow: set[str]) -> bool:
    """Read questions: in a chosen category (by the site's tags or the title's words) and not sport,
    crypto or entertainment; followed questions always."""
    if q["key"] in follow:
        return True
    return bool(q["title"]) and crowd.wanted(q["title"]) and crowd.categorise(q["title"], q.get("tags") or [], q["site"]) is not None


def merge(old_q: dict, old_points: list[dict], new_q: list[dict], site_points: list[dict], at: str,
          follow: set[str]) -> tuple[dict, list[dict]]:
    """Questions and points after a refresh: questions seen now replace their earlier record
    (one seen before but not now keeps its last record, so resolved questions stay); each open
    question's chance is saved when it moved or a week has passed; the sites' own history points
    are added once."""
    qs = dict(old_q)
    for q in new_q:
        if keep_question(q, follow):
            prev = qs.get(q["key"]) or {}
            qs[q["key"]] = {**prev, **{k: v for k, v in q.items() if v is not None or k not in prev}, "seen": at}
    points = list(old_points)
    have_site = {p["question_key"] for p in points if p.get("origin") == "site"}
    for p in site_points:
        if p["question_key"] in qs and (p["question_key"] not in have_site):
            points.append(p)
    last: dict[str, dict] = {}
    for p in points:
        if p["chance"] is not None and (p["question_key"] not in last or p["at"] > last[p["question_key"]]["at"]):
            last[p["question_key"]] = p
    cutoff = (datetime.fromisoformat(at) - timedelta(days=QUIET_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    for q in new_q:
        if q["key"] not in qs or q.get("status") != "open" or q.get("chance") is None:
            continue
        prev = last.get(q["key"])
        if prev is None or abs(prev["chance"] - q["chance"]) >= MOVE or prev["at"] < cutoff:
            points.append({"question_key": q["key"], "at": at, "chance": q["chance"], "lower": q.get("lower"),
                           "upper": q.get("upper"), "origin": "refresh"})
    return qs, daily(points)


def tracked(questions: list[dict], follow: set[str], n: int = TRACK) -> list[dict]:
    """Followed questions first, then the busiest open binary ones (by volume or forecasters)."""
    open_q = [q for q in questions if q.get("status") == "open" and q.get("kind") in ("binary", "numeric", "date")]
    first = [q for q in open_q if q["key"] in follow]
    rest = sorted((q for q in open_q if q["key"] not in follow),
                  key=lambda q: -(q.get("volume") or 0) - 1000 * (q.get("forecasters") or 0))
    return first + rest[:n]


# ----------------------------------------------------------------------------- the connectors
class _Crowd(Connector):
    site = ""
    gap = 1.0
    keep_vintages = 3
    stage_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def _home(self) -> Path:
        from worldmodel_data.config import paths
        return paths().home

    def _settings(self, raw_dir: Path) -> dict:
        return local.load_settings(self._home())

    def _follow(self, raw_dir: Path) -> set[str]:
        f = crowd.load_follow(self._home())
        return {k for k in f["follow"] if k.startswith(self.site + ":")}

    def _categories(self, settings: dict) -> list[str]:
        cats = [c for c in (settings.get("crowd_categories") or "").split(",") if c in crowd.CATEGORIES]
        return cats or list(crowd.CATEGORIES)

    def _get(self, url: str, **kw):
        r = self.client.get(url, **kw)
        if r.status_code in (401, 403, 429):
            raise ConnectorError(f"{self.source_id}: the site refused the request ({r.status_code}); stopped there")
        r.raise_for_status()
        time.sleep(self.gap)
        return r.json()

    def _last(self, raw_dir: Path) -> Path | None:
        return self.last_vintage_dir(raw_dir)

    def save_state(self, raw_dir: Path, new_q: list[dict], site_points: list[dict], at: str, follow: set[str],
                   comments: list[dict] | None = None, mine: list[dict] | None = None) -> int:
        last = self._last(raw_dir)
        old_q = read_gz_json(last / QUESTIONS, {}) if last else {}
        old_p = read_points(last / POINTS) if last else []
        qs, pts = merge(old_q, old_p, new_q, site_points, at, follow)
        write_gz_json(raw_dir / QUESTIONS, qs)
        write_points(raw_dir / POINTS, pts)
        old_c = read_gz_json(last / COMMENTS, []) if last else []
        if comments or old_c:
            by = {c["comment_id"]: c for c in old_c}
            by.update({c["comment_id"]: c for c in comments or []})
            write_gz_json(raw_dir / COMMENTS, list(by.values()))
        old_m = read_gz_json(last / MINE, []) if last else []
        if mine or old_m:
            by = {(m["question_key"], m["forecaster"], m["at"]): m for m in old_m}
            by.update({(m["question_key"], m["forecaster"], m["at"]): m for m in mine or []})
            write_gz_json(raw_dir / MINE, list(by.values()))
        return len(qs)

    # Pages as the sites send them, for fixtures and hand-saved copies: <site>_page_*.json
    def parse_pages(self, raw_dir: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        raise NotImplementedError

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        raw_dir = Path(raw_dir)
        if not (raw_dir / QUESTIONS).exists():
            pages = sorted(raw_dir.glob(f"{self.site}_page_*.json"))
            if not pages:
                raise ConnectorError(f"{self.source_id}: no {QUESTIONS} or {self.site}_page_*.json in {raw_dir}")
            q, pts, comments, mine = self.parse_pages(raw_dir)
            at = f"{release[:10]}T00:00:00" if len(release) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            qs, points = merge({}, [], q, pts, at, set())
        else:
            qs, points = read_gz_json(raw_dir / QUESTIONS, {}), read_points(raw_dir / POINTS)
            comments, mine = read_gz_json(raw_dir / COMMENTS, []), read_gz_json(raw_dir / MINE, [])
        con.execute("""CREATE TABLE cq (question_key VARCHAR, site VARCHAR, site_id VARCHAR, title VARCHAR, url VARCHAR,
            kind VARCHAR, tags VARCHAR, created TIMESTAMP, closes TIMESTAMP, resolved_at TIMESTAMP, status VARCHAR,
            resolution VARCHAR, chance DOUBLE, volume DOUBLE, forecasters INTEGER, comments INTEGER, description VARCHAR,
            options VARCHAR)""")
        insert(con, "INSERT INTO cq VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (q["key"], q["site"], q["site_id"], q["title"], q.get("url"), q.get("kind"), ",".join(q.get("tags") or []),
             q.get("created"), q.get("closes"), q.get("resolved_at"), q.get("status"), q.get("resolution"), q.get("chance"),
             q.get("volume"), q.get("forecasters"), q.get("comments"), q.get("description"),
             json.dumps(q["options"]) if q.get("options") else None) for q in qs.values()])
        con.execute("CREATE TABLE cp (question_key VARCHAR, at_time TIMESTAMP, chance DOUBLE, lower DOUBLE, upper DOUBLE, origin VARCHAR)")
        insert(con, "INSERT INTO cp VALUES (?, ?, ?, ?, ?, ?)", [
            (p["question_key"], p["at"], p["chance"], p.get("lower"), p.get("upper"), p.get("origin") or "refresh")
            for p in points if p["chance"] is not None and p["question_key"] in qs])
        con.execute("""CREATE TABLE cc (question_key VARCHAR, comment_id VARCHAR, parent_id VARCHAR, author VARCHAR,
            created TIMESTAMP, votes INTEGER, forecast DOUBLE, text VARCHAR)""")
        insert(con, "INSERT INTO cc VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            (c["question_key"], c["comment_id"], c.get("parent_id"), c.get("author"), c.get("created"), c.get("votes"),
             c.get("forecast"), c.get("text")) for c in comments or []])
        con.execute("CREATE TABLE cm (question_key VARCHAR, forecaster VARCHAR, at_time TIMESTAMP, chance DOUBLE, community DOUBLE)")
        insert(con, "INSERT INTO cm VALUES (?, ?, ?, ?, ?)", [
            (m["question_key"], m.get("forecaster") or "you", m["at"], m["chance"],
             m.get("community") if m.get("community") is not None else community_at(points, m["question_key"], m["at"]))
            for m in mine or []])
        self.history_queries = {"crowd_questions": "SELECT * FROM cq", "crowd_points": "SELECT * FROM cp",
                                "crowd_comments": "SELECT * FROM cc", "crowd_mine": "SELECT * FROM cm"}
        return EMPTY_OBSERVATIONS


class Polymarket(_Crowd):
    source_id = "polymarket"
    site = "polymarket"
    switch = "crowd_polymarket"
    GAMMA = "https://gamma-api.polymarket.com/events"
    HISTORY = "https://clob.polymarket.com/prices-history"

    def parse_pages(self, raw_dir):
        events = []
        for p in sorted(raw_dir.glob("polymarket_page_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            events += d if isinstance(d, list) else d.get("data") or d.get("events") or []
        pts = []
        for p in sorted(raw_dir.glob("polymarket_history_*.json")):
            mid = p.stem.split("_")[-1]
            pts += [{"question_key": f"polymarket:{mid}", "at": at, "chance": c, "origin": "site"}
                    for at, c in pm_history(json.loads(p.read_text(encoding="utf-8")))]
        return pm_markets(events), pts, [], []

    def download(self, raw_dir: Path, release: str) -> str:
        s, follow = self._settings(raw_dir), self._follow(raw_dir)
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
        events, seen = [], set()
        for cat in self._categories(s):
            for slug in crowd.SITE_TAGS["polymarket"][cat]:
                for closed, pages in ((False, 5), (True, 2)):
                    for page in range(pages):
                        params = {"tag_slug": slug, "closed": str(closed).lower(), "limit": 100, "offset": page * 100,
                                  "order": "volume", "ascending": "false"}
                        if closed:
                            params["end_date_min"] = since
                        got = self._get(self.GAMMA, params=params)
                        got = got if isinstance(got, list) else got.get("data") or []
                        new = [e for e in got if e.get("id") not in seen]
                        seen |= {e.get("id") for e in got}
                        events += new
                        if len(got) < 100:
                            break
        qs = pm_markets(events)
        last = self._last(raw_dir)
        have = {p["question_key"] for p in read_points(last / POINTS) if p.get("origin") == "site"} if last else set()
        pts = []
        for q in tracked([q for q in qs if keep_question(q, follow)], follow):
            if q["key"] in have or not q.get("token"):
                continue
            try:
                data = self._get(self.HISTORY, params={"market": q["token"], "interval": "max", "fidelity": 1440})
            except ConnectorError:
                raise
            except Exception as exc:  # noqa: BLE001 - one market's history is not worth the whole refresh
                log.info("polymarket: no history for %s (%s)", q["key"], exc)
                continue
            pts += [{"question_key": q["key"], "at": a, "chance": c, "origin": "site"} for a, c in pm_history(data)]
        n = self.save_state(raw_dir, qs, pts, at, follow)
        return f"{self.GAMMA} ({n:,} questions kept)"


class Manifold(_Crowd):
    source_id = "manifold"
    site = "manifold"
    switch = "crowd_manifold"
    SEARCH = "https://api.manifold.markets/v0/search-markets"

    def parse_pages(self, raw_dir):
        qs = []
        for p in sorted(raw_dir.glob("manifold_page_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            topic = p.stem.split("_page_")[-1].rsplit("_", 1)[0] if "_page_" in p.stem else None
            qs += mf_markets(d if isinstance(d, list) else d.get("data") or [], topic)
        return qs, [], [], []

    def download(self, raw_dir: Path, release: str) -> str:
        s, follow = self._settings(raw_dir), self._follow(raw_dir)
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        qs = []
        for cat in self._categories(s):
            for slug in crowd.SITE_TAGS["manifold"][cat]:
                for filt, sort, limit in (("open", "most-popular", 500), ("resolved", "newest", 200)):
                    got = self._get(self.SEARCH, params={"term": "", "topicSlug": slug, "filter": filt, "sort": sort,
                                                         "contractType": "BINARY", "limit": limit})
                    qs += mf_markets(got if isinstance(got, list) else [], slug)
        uniq = {q["key"]: q for q in qs}
        n = self.save_state(raw_dir, list(uniq.values()), [], at, follow)
        return f"{self.SEARCH} ({n:,} questions kept)"


class Metaculus(_Crowd):
    source_id = "metaculus"
    site = "metaculus"
    switch = "crowd_metaculus"
    needs_env = ("METACULUS_TOKEN",)
    POSTS = "https://www.metaculus.com/api/posts/"
    COMMENTS = "https://www.metaculus.com/api/comments/"
    ME = "https://www.metaculus.com/api/users/me/"

    def parse_pages(self, raw_dir):
        qs, pts, mine = [], [], []
        for p in sorted(raw_dir.glob("metaculus_page_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            for post in (d.get("results") if isinstance(d, dict) else d) or []:
                rec, hp, my = mc_question(post)
                if rec:
                    qs.append(rec)
                    pts += hp
                    mine += [{**m, "forecaster": "you"} for m in my]
        comments = []
        for p in sorted(raw_dir.glob("metaculus_comments_*.json")):
            pid = p.stem.split("_")[-1]
            d = json.loads(p.read_text(encoding="utf-8"))
            comments += mc_comments(f"metaculus:{pid}", d.get("results") if isinstance(d, dict) else d)
        return qs, pts, comments, mine

    def _posts(self, headers: dict, params: dict, pages: int) -> list[dict]:
        out = []
        for page in range(pages):
            d = self._get(self.POSTS, headers=headers, params={**params, "limit": 100, "offset": page * 100})
            got = d.get("results") or []
            out += got
            if not d.get("next") or not got:
                break
        return out

    def _mine(self, token: str, at_points: list[dict]) -> list[dict]:
        headers = {"Authorization": f"Token {token}"}
        me = self._get(self.ME, headers=headers)
        name, uid = me.get("username") or "you", me.get("id")
        if not uid:
            return []
        out = []
        for post in self._posts(headers, {"forecaster_id": uid, "with_cp": "true"}, 10):
            rec, _, my = mc_question(post)
            if rec:
                out += [{**m, "forecaster": name, "community": community_at(at_points, m["question_key"], m["at"])} for m in my]
        return out

    def download(self, raw_dir: Path, release: str) -> str:
        s, follow = self._settings(raw_dir), self._follow(raw_dir)
        token = self.env("METACULUS_TOKEN")
        headers = {"Authorization": f"Token {token}"}
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
        posts, seen = [], set()
        for cat in self._categories(s):
            for slug in crowd.SITE_TAGS["metaculus"][cat]:
                for params, pages in (({"categories": slug, "statuses": "open", "order_by": "-hotness"}, 4),
                                      ({"categories": slug, "statuses": "resolved", "order_by": "-actual_resolve_time",
                                        "actual_resolve_time__gt": since}, 2)):
                    for p in self._posts(headers, {**params, "with_cp": "true"}, pages):
                        if p.get("id") not in seen:
                            seen.add(p.get("id"))
                            posts.append(p)
        qs, pts = [], []
        for post in posts:
            rec, hp, _ = mc_question(post)
            if rec:
                qs.append(rec)
                pts += hp
        last = self._last(raw_dir)
        old_p = read_points(last / POINTS) if last else []
        have = {p["question_key"] for p in old_p if p.get("origin") == "site"} | {p["question_key"] for p in pts}
        kept = [q for q in qs if keep_question(q, follow)]
        for q in tracked(kept, follow):  # the full community history, once per question
            if q["key"] in have:
                continue
            d = self._get(f"{self.POSTS}{q['site_id']}/", headers=headers, params={"with_cp": "true"})
            _, hp, _ = mc_question(d)
            pts += hp
        comments = []
        busy = [q for q in kept if q["key"] in follow] + sorted(
            (q for q in kept if q["key"] not in follow and q.get("status") == "open"), key=lambda q: -(q.get("comments") or 0))
        for q in busy[:COMMENTED] if s.get("crowd_comments", True) else []:
            d = self._get(self.COMMENTS, headers=headers, params={"on_post": q["site_id"], "limit": 100, "sort": "-created_at"})
            comments += mc_comments(q["key"], d.get("results") if isinstance(d, dict) else d)
        mine = []
        if s.get("crowd_mine", True):
            all_points = old_p + pts
            mine = self._mine(token, all_points)
            bot = self._optional_env("METACULUS_BOT_TOKEN")
            if bot:
                mine += self._mine(bot, all_points)
        n = self.save_state(raw_dir, qs, pts, at, follow, comments, mine)
        return f"{self.POSTS} ({n:,} questions kept)"

    @staticmethod
    def _optional_env(name: str) -> str | None:
        import os
        return os.environ.get(name, "").strip() or None


# ----------------------------------------------------------------------------- ViEWS
def views_rows(pages: list[dict]) -> list[tuple]:
    out = []
    for d in pages:
        for r in d.get("data") or []:
            iso = r.get("isoab") or r.get("iso") or r.get("country_iso")
            y, m = r.get("year"), r.get("month")
            if not iso or not y or not m:
                continue
            deaths = fnum(r.get("main_mean"))
            if deaths is None and fnum(r.get("main_mean_ln")) is not None:
                deaths = math.expm1(fnum(r.get("main_mean_ln")))
            out.append((str(iso).upper(), f"{int(y):04d}-{int(m):02d}-01", deaths, fnum(r.get("main_dich")), "sb",
                        d.get("run") or d.get("run_id") or ""))
    return out


class ViEWS(Connector):
    source_id = "views"
    switch = "views_fetch"
    fetch_every_days = 25
    keep_vintages = 4
    URL = "https://api.viewsforecasting.org/current/cm/sb"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url, page = self.URL, 0
        while url and page < 200:
            r = self.client.get(url)
            if r.status_code in (401, 403, 429):
                raise ConnectorError(f"views: the site refused the request ({r.status_code})")
            r.raise_for_status()
            d = r.json()
            (raw_dir / f"views_page_{page:03d}.json").write_text(json.dumps(d), encoding="utf-8")
            url = d.get("next_page") or None
            page += 1
            time.sleep(1.0)
        return self.URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pages = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(raw_dir).glob("views_page_*.json"))]
        rows = views_rows(pages)
        if not rows:
            raise ConnectorError(f"views: no forecasts in {raw_dir}")
        con.execute("CREATE TABLE vf (country_code VARCHAR, month DATE, deaths DOUBLE, chance_25 DOUBLE, kind VARCHAR, run VARCHAR)")
        insert(con, "INSERT INTO vf VALUES (?, ?, ?, ?, ?, ?)", rows)
        self.history_queries = {"conflict_forecasts": "SELECT * FROM vf"}
        return EMPTY_OBSERVATIONS
