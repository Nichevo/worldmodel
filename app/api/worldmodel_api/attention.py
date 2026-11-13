"""Wikipedia attention: how many people read each country's English Wikipedia article each
day, from the Wikimedia pageviews API (wikimedia.org/api/rest_v1/metrics/pageviews, keyless).

* A country page asks for its article's last 90 days (one request, kept 12 hours).
* The Briefing asks once a day for Wikipedia's 1,000 most-read articles of the day before,
  and picks out the countries among them, plus the key countries' own counts.

A spike is a day with at least three times the usual views (the median of the 28 days before)
and at least 5,000 of them: usually a sign something is happening there.
Settings > Outlook > attention_on switches it off.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import httpx

from worldmodel_contract import local

log = logging.getLogger(__name__)

BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
PER_ARTICLE = BASE + "/per-article/en.wikipedia.org/all-access/user/{title}/daily/{start}/{end}"
TOP = BASE + "/top/en.wikipedia.org/all-access/{y}/{m:02d}/{d:02d}"
USER_AGENT = "worldmodel/0.1 (personal local tool; https://github.com/Nichevo/worldmodel) httpx"
KEEP_HOURS = 12
SPIKE, SPIKE_MIN = 3.0, 5000


def _get(url: str) -> str:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def root() -> Path:
    return local.home() / "media" / "attention"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write(p: Path, data) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _fresh(kept: dict | None) -> bool:
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(kept["fetched_at"]) < timedelta(hours=KEEP_HOURS)
    except (TypeError, KeyError, ValueError):
        return False


def summarise(points: list[list]) -> dict:
    """The latest day, the usual level, the ratio and the spike days."""
    views = [v for _, v in points]
    spikes = []
    for i in range(28, len(points)):
        usual = statistics.median(views[i - 28:i]) or 1
        if views[i] >= SPIKE * usual and views[i] >= SPIKE_MIN:
            spikes.append({"day": points[i][0], "views": views[i], "times": round(views[i] / usual, 1)})
    if not views:
        return {"latest": None, "usual": None, "ratio": None, "spikes": []}
    usual = statistics.median(views[-31:-3] or views)
    week = sum(views[-7:]) / len(views[-7:])
    return {"latest": views[-1], "latest_day": points[-1][0], "usual": round(usual), "week_avg": round(week),
            "ratio": round(week / usual, 2) if usual else None, "spikes": spikes[-5:]}


def country(entity: str, title: str, enabled: bool, fetch: Callable[[str], str] = _get, today: date | None = None) -> dict:
    """The last 90 days of views of one article."""
    out = {"entity": entity, "article": title, "points": []}
    if not enabled:
        return {**out, "note": "Wikipedia attention is off in Settings."}
    path = root() / f"{entity}.json"
    kept = _read(path)
    if kept and _fresh(kept) and kept.get("article") == title:
        return kept
    today = today or date.today()
    start, end = today - timedelta(days=91), today - timedelta(days=1)
    try:
        data = json.loads(fetch(PER_ARTICLE.format(title=quote(title.replace(" ", "_"), safe=""),
                                                   start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))))
    except (httpx.HTTPError, OSError, ValueError) as exc:
        if kept:
            return {**kept, "note": f"Could not reach Wikimedia ({exc}); showing the copy from {kept['fetched_at'][:10]}."}
        return {**out, "note": f"Could not reach Wikimedia ({exc})."}
    pts = [[f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}", int(i.get("views", 0))]
           for i in data.get("items", [])]
    got = {**out, "points": pts, **summarise(pts), "fetched_at": datetime.now(timezone.utc).isoformat()}
    _write(path, got)
    return got


def top(titles: dict[str, str], enabled: bool, fetch: Callable[[str], str] = _get, today: date | None = None) -> dict:
    """Countries among the day's 1,000 most-read articles (yesterday's, or the day before when
    yesterday's list is not out yet). titles maps article title -> entity."""
    if not enabled:
        return {"day": None, "countries": [], "note": "Wikipedia attention is off in Settings."}
    today = today or date.today()
    for back in (1, 2):
        day = today - timedelta(days=back)
        path = root() / f"top-{day.isoformat()}.json"
        kept = _read(path)
        if kept is None:
            try:
                kept = json.loads(fetch(TOP.format(y=day.year, m=day.month, d=day.day)))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                return {"day": None, "countries": [], "note": f"Could not reach Wikimedia ({exc})."}
            except (httpx.HTTPError, OSError, ValueError) as exc:
                return {"day": None, "countries": [], "note": f"Could not reach Wikimedia ({exc})."}
            _write(path, kept)
        arts = (kept.get("items") or [{}])[0].get("articles", [])
        found = []
        for a in arts:
            t = a.get("article", "").replace("_", " ")
            if t in titles:
                found.append({"entity": titles[t], "article": t, "views": a.get("views"), "rank": a.get("rank")})
        return {"day": day.isoformat(), "countries": found[:20]}
    return {"day": None, "countries": [], "note": "Wikipedia's most-read list for the last two days is not out yet."}
