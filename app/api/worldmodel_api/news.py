"""Major news for Discover's News tab, from free sources read politely and kept locally.

* Wikipedia "Current events": the hand-written summary of each day's main world news
  (Portal:Current_events/<year>_<Month>_<day>), one page a day through the official API.
  The first fetch reads the last 14 days; later ones read only the days since, plus today
  and yesterday again (they are still being written).
* GDELT: how much world news names each key country, day by day for three months. A
  week with several times the usual count is a spike ("News about Fiji up 6 times this
  week"), and its tone (GDELT's average article tone) gives the item's tone. Requests are
  five seconds apart, as GDELT asks.
* News feeds: RSS headlines from RNZ, Stuff, ABC Australia, the BBC and the Guardian.
* ReliefWeb (UN): disasters and crises. Off unless you add an app name ReliefWeb has
  approved (free; Settings > Discover).

Items get a category and tags (countries found in the text) like Discover's finds, and
the same Interesting / Not interesting ratings. Kept in <home>/media/news/items.json for
`news_keep_days` (default two years); fetch times and errors in state.json.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from worldmodel_contract import discover, local

log = logging.getLogger(__name__)

USER_AGENT = "worldmodel/0.1 (personal local tool; https://github.com/Nichevo/worldmodel) httpx"
WIKI_API = "https://en.wikipedia.org/w/api.php"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
RELIEFWEB = "https://api.reliefweb.int/v2/disasters"
FEEDS = {  # id: (name, address, country the feed is about when no country is named)
    "rnz": ("RNZ", "https://www.rnz.co.nz/rss/national.xml", "NZL"),
    "rnz_world": ("RNZ world", "https://www.rnz.co.nz/rss/world.xml", None),
    "stuff": ("Stuff", "https://www.stuff.co.nz/rss", "NZL"),
    "abc": ("ABC Australia", "https://www.abc.net.au/news/feed/2942460/rss.xml", "AUS"),
    "bbc": ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", None),
    "guardian": ("The Guardian, world", "https://www.theguardian.com/world/rss", None),
}
SOURCES = {"wikipedia": "Wikipedia Current events", "gdelt": "GDELT news counts", "feeds": "News feeds",
           "reliefweb": "ReliefWeb (UN)"}
FIRST_DAYS = 14
GDELT_GAP = 5.5  # seconds between GDELT requests
SPIKE = 3.0      # a week with this many times the usual news count is a spike
TOPIC_CATEGORY = {
    "armed conflicts and attacks": "Conflict and security", "arts and culture": "Society and laws",
    "business and economy": "Economy", "disasters and accidents": "Climate", "health and environment": "People",
    "international relations": "Government and politics", "law and crime": "Society and laws",
    "politics and elections": "Government and politics", "science and technology": "AI and technology",
    "sports": "Society and laws",
}
BAD_TOPICS = {"armed conflicts and attacks", "disasters and accidents"}

_lock = threading.Lock()
_running = threading.Event()


def root() -> Path:
    return local.home() / "media" / "news"


def _read(name: str, default):
    try:
        return json.loads((root() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    p = root() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(p)


def items() -> list[dict]:
    got = _read("items.json", [])
    return got if isinstance(got, list) else []


def state() -> dict:
    s = _read("state.json", {})
    s.setdefault("last", {})
    s.setdefault("errors", {})
    s.setdefault("wiki_days", [])
    s["running"] = _running.is_set()
    return s


def _key(*parts: str) -> str:
    return "news:" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:14]


# ----------------------------------------------------------------------------- matching countries
class Names:
    """Find countries named in a piece of text, by their names (longest first)."""

    def __init__(self, pairs: list[tuple[str, str]]):
        self.ids = {}
        for ent, name in pairs:
            for n in {name, *ALIASES.get(ent, ())}:
                if n and len(n) > 3:
                    self.ids[n.lower()] = ent
        words = sorted(self.ids, key=len, reverse=True)
        self.pat = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I) if words else None
        self.name = dict(pairs)

    def find(self, text: str, limit: int = 6) -> list[str]:
        if not self.pat or not text:
            return []
        out = []
        for m in self.pat.finditer(text):
            e = self.ids[m.group(1).lower()]
            if e not in out:
                out.append(e)
        return out[:limit]


ALIASES = {"USA": ("United States", "US", "U.S.", "American"), "GBR": ("United Kingdom", "Britain", "British", "UK"),
           "NZL": ("New Zealand", "Aotearoa"), "AUS": ("Australia", "Australian"), "CHN": ("China", "Chinese"),
           "RUS": ("Russia", "Russian"), "UKR": ("Ukraine", "Ukrainian"), "PRK": ("North Korea",), "KOR": ("South Korea",),
           "IRN": ("Iran", "Iranian"), "ISR": ("Israel", "Israeli"), "PSE": ("Gaza", "Palestine", "West Bank"),
           "COD": ("DR Congo", "Democratic Republic of the Congo"), "CIV": ("Ivory Coast", "Côte d'Ivoire"),
           "MMR": ("Myanmar", "Burma"), "TWN": ("Taiwan",), "IND": ("India", "Indian"), "JPN": ("Japan", "Japanese")}


def _tone_cat(text: str, topic: str = "") -> str:
    t = topic.lower()
    if t in TOPIC_CATEGORY:
        return TOPIC_CATEGORY[t]
    return discover.category(None, text)


def _item(source: str, key: str, day: str, headline: str, names: Names, *, url: str | None = None, detail: str = "",
          topic: str = "", tone: str = "neutral", entities: list[str] | None = None, outlet: str | None = None,
          score: float = 0.4) -> dict:
    ents = entities if entities is not None else names.find(f"{headline} {detail}")
    return {"key": key, "kind": "news", "source": source, "outlet": outlet or SOURCES[source], "date": day,
            "headline": headline[:400], "detail": detail[:1200], "url": url, "topic": topic, "category": _tone_cat(f"{headline} {detail}", topic),
            "tone": tone, "entities": ents, "score": score,
            "tags": [*(names.name.get(e, e) for e in ents), *( [topic] if topic else []), SOURCES[source]]}


# ----------------------------------------------------------------------------- Wikipedia Current events
LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
EXT = re.compile(r"\[(https?://[^\s\]]+)\s*([^\]]*)\]")
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
COMMENT = re.compile(r"<!--.*?-->", re.S)
REF = re.compile(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", re.S)


def wiki_plain(s: str) -> str:
    s = REF.sub("", COMMENT.sub("", s))
    for _ in range(3):
        s = TEMPLATE.sub("", s)
    s = EXT.sub("", s)
    s = LINK.sub(lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(" ".join(s.split())).strip(" ()")


def parse_current_events(text: str, day: str, names: Names) -> list[dict]:
    """The day's items: each deepest bullet, with the bullets above it as its context."""
    text = COMMENT.sub("", text)
    out: list[dict] = []
    topic = ""
    stack: list[str] = []
    lines = text.splitlines()
    for n, line in enumerate(lines):
        s = line.strip()
        head = re.fullmatch(r"(?:'''|;)\s*([^']+?)\s*(?:''')?", s)
        if head and not s.startswith("*"):
            topic, stack = wiki_plain(head.group(1)), []
            continue
        m = re.match(r"(\*+)\s*(.*)", s)
        if not m:
            continue
        depth, body = len(m.group(1)), m.group(2)
        stack = stack[:depth - 1] + [body]
        nxt = lines[n + 1].strip() if n + 1 < len(lines) else ""
        deeper = re.match(r"(\*+)", nxt)
        if deeper and len(deeper.group(1)) > depth:
            continue  # a context line: its children are the items
        plain = wiki_plain(body)
        if len(plain) < 25:
            continue
        context = " / ".join(x for x in (wiki_plain(c) for c in stack[:-1]) if x)
        url = next((u for u, _ in EXT.findall(body)), None)
        links = [a for a, _ in LINK.findall(" ".join(stack))]
        ents = names.find(" ".join([plain, context, *links]))
        t = topic.lower()
        out.append(_item("wikipedia", _key("wikipedia", day, plain[:160]), day, plain, names, url=url,
                         detail=context, topic=topic, tone="bad" if t in BAD_TOPICS else "neutral", entities=ents,
                         score=0.45 + (0.1 if t in BAD_TOPICS else 0)))
    return out


def _wiki_day(client: httpx.Client, d: date) -> str | None:
    title = f"Portal:Current_events/{d.year}_{d.strftime('%B')}_{d.day}"
    r = client.get(WIKI_API, params={"action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": 2})
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        return None  # no page for that day (yet)
    return data["parse"]["wikitext"]


def fetch_wikipedia(client: httpx.Client, names: Names, st: dict, today: date) -> list[dict]:
    done = set(st.get("wiki_days") or [])
    days = [today - timedelta(days=k) for k in range(FIRST_DAYS)]
    want = [d for d in days if d.isoformat() not in done or (today - d).days <= 1]
    out = []
    for d in sorted(want):
        text = _wiki_day(client, d)
        if text:
            out += parse_current_events(text, d.isoformat(), names)
            done.add(d.isoformat())
        time.sleep(1)
    st["wiki_days"] = sorted(done)[-400:]
    return out


# ----------------------------------------------------------------------------- GDELT
def spikes(timeline: list[dict], tones: list[dict] | None = None) -> dict | None:
    """The last week's news count against the 60 days before it: {ratio, week, usual, tone}."""
    vals = [float(p.get("value") or 0) for p in timeline]
    if len(vals) < 40:
        return None
    week, before = vals[-7:], vals[-67:-7]
    usual = sum(before) / len(before) if before else 0
    now = sum(week) / 7
    if usual <= 0:
        return None
    t = None
    if tones:
        tv = [float(p.get("value") or 0) for p in tones]
        if len(tv) >= 14:
            t = sum(tv[-7:]) / 7 - sum(tv[:-7]) / max(1, len(tv) - 7)
    return {"ratio": now / usual, "week": now, "usual": usual, "tone": t}


def _gdelt(client: httpx.Client, query: str, mode: str) -> list[dict]:
    r = client.get(GDELT, params={"query": query, "mode": mode, "timespan": "3m", "format": "json"})
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:  # GDELT answers a refused or malformed query with plain text
        raise RuntimeError(r.text[:200]) from None
    series = data.get("timeline") or []
    return series[0].get("data", []) if series else []


def fetch_gdelt(client: httpx.Client, names: Names, countries: list[str], today: date) -> list[dict]:
    out = []
    for ent in countries:
        name = names.name.get(ent)
        if not name:
            continue
        q = f'"{name}"'
        vol = _gdelt(client, q, "timelinevolraw")
        time.sleep(GDELT_GAP)
        tones = _gdelt(client, q, "timelinetone")
        time.sleep(GDELT_GAP)
        s = spikes(vol, tones)
        if not s or s["ratio"] < SPIKE:
            continue
        tone = "neutral" if s["tone"] is None or abs(s["tone"]) < 1 else ("bad" if s["tone"] < 0 else "good")
        week = (today - timedelta(days=today.weekday())).isoformat()
        out.append(_item("gdelt", _key("gdelt", ent, week), today.isoformat(), f"News about {name} up {s['ratio']:.0f} times this week",
                         names, detail=f"About {s['week']:.0f} articles a day in the last week, against {s['usual']:.0f} a day in the two months before "
                                       f"(GDELT's count of world news naming {name})."
                                       + (f" Their tone is {'darker' if s['tone'] < 0 else 'brighter'} than usual." if s["tone"] is not None and abs(s["tone"]) >= 1 else ""),
                         url=f"{GDELT}?query={quote(q)}&mode=artlist&timespan=7d&sort=hybridrel",
                         topic="News spike", tone=tone, entities=[ent], score=0.5 + 0.1 * min(4, s["ratio"] - SPIKE)))
    return out


# ----------------------------------------------------------------------------- feeds
def parse_feed(text: str, feed_id: str, names: Names) -> list[dict]:
    title, _url, home = FEEDS[feed_id]
    try:
        root_el = ET.fromstring(text.encode() if isinstance(text, str) else text)
    except ET.ParseError:
        return []
    out = []
    for it in root_el.iter("item"):
        head = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip() or None
        desc = re.sub(r"<[^>]+>", "", html.unescape(it.findtext("description") or "")).strip()
        when = it.findtext("pubDate")
        try:
            day = parsedate_to_datetime(when).date().isoformat() if when else date.today().isoformat()
        except (TypeError, ValueError):
            day = date.today().isoformat()
        if not head:
            continue
        ents = names.find(f"{head} {desc}") or ([home] if home else [])
        out.append(_item("feeds", _key("feeds", link or head), day, head, names, url=link, detail=desc[:400],
                         entities=ents, outlet=title, score=0.35))
    return out


def fetch_feeds(client: httpx.Client, names: Names, ids: list[str]) -> list[dict]:
    out = []
    for f in ids:
        if f not in FEEDS:
            continue
        r = client.get(FEEDS[f][1])
        r.raise_for_status()
        out += parse_feed(r.text, f, names)
        time.sleep(1)
    return out


# ----------------------------------------------------------------------------- ReliefWeb
def parse_reliefweb(data: dict, names: Names) -> list[dict]:
    out = []
    for d in data.get("data", []):
        f = d.get("fields") or {}
        name = f.get("name") or ""
        ents = [c.get("iso3", "").upper() for c in f.get("country") or [] if c.get("iso3")]
        day = ((f.get("date") or {}).get("created") or "")[:10] or date.today().isoformat()
        kinds = ", ".join(t.get("name", "") for t in f.get("type") or [])
        out.append(_item("reliefweb", _key("reliefweb", str(d.get("id") or name)), day, name, names,
                         url=f.get("url_alias") or f.get("url"), detail=f"{kinds}. Status: {f.get('status', '')}." if kinds else "",
                         topic="Disasters and accidents", tone="bad", entities=ents[:6], score=0.5))
    return out


def fetch_reliefweb(client: httpx.Client, names: Names, app: str) -> list[dict]:
    params = [("appname", app), ("preset", "latest"), ("limit", "50"),
              *(("fields[include][]", f) for f in ("name", "country", "date", "type", "status", "url_alias"))]
    r = client.get(RELIEFWEB, params=params)
    r.raise_for_status()
    return parse_reliefweb(r.json(), names)


# ----------------------------------------------------------------------------- run
def is_due(settings: dict, st: dict | None = None) -> bool:
    st = st or state()
    last = st.get("finished_at")
    if not last:
        return True
    try:
        at = datetime.fromisoformat(last)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - at >= timedelta(hours=float(settings.get("news_every_hours", 6)))


def run(settings: dict, names: Names, client: httpx.Client | None = None, today: date | None = None) -> dict:
    """Fetch every switched-on source; one failing never stops the others. Returns the state."""
    if _running.is_set():
        return state()
    _running.set()
    return _run(settings, names, client, today)


def _run(settings: dict, names: Names, client: httpx.Client | None, today: date | None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    today = today or date.today()
    try:
        st = state()
        on = [w for w in str(settings.get("news_sources") or "").split(",") if w in SOURCES]
        got: list[dict] = []
        jobs = {
            "wikipedia": lambda: fetch_wikipedia(client, names, st, today),
            "feeds": lambda: fetch_feeds(client, names, str(settings.get("news_feeds") or "").split(",")),
            "reliefweb": lambda: fetch_reliefweb(client, names, str(settings.get("news_reliefweb_app") or "")),
            "gdelt": lambda: fetch_gdelt(client, names, [k for k in str(settings.get("discover_key_countries") or "").split(",") if k], today),
        }
        for src in ("wikipedia", "feeds", "reliefweb", "gdelt"):
            if src not in on or (src == "reliefweb" and not settings.get("news_reliefweb_app")):
                continue
            try:
                found = jobs[src]()
                got += found
                st["last"][src] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": len(found)}
                st["errors"].pop(src, None)
            except Exception as exc:  # noqa: BLE001 - one source down must not stop the others
                log.warning("news: %s failed: %s", src, exc)
                st["errors"][src] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": str(exc)[:300]}
        keep_from = (today - timedelta(days=int(settings.get("news_keep_days", 730)))).isoformat()
        with _lock:
            by = {i["key"]: i for i in items() if i.get("date", "") >= keep_from}
            for i in got:
                if i["date"] >= keep_from:
                    by.setdefault(i["key"], {**i, "first_seen": today.isoformat()})
            _write("items.json", sorted(by.values(), key=lambda i: (i["date"], i["key"]), reverse=True))
            st["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            st.pop("running", None)
            _write("state.json", st)
        return state()
    finally:
        if own:
            client.close()
        _running.clear()


def start(settings: dict, names: Names) -> bool:
    """Fetch in the background; False when a fetch is already running."""
    with _lock:
        if _running.is_set():
            return False
        _running.set()
    threading.Thread(target=_run, args=(settings, names, None, None), daemon=True, name="news").start()
    return True
