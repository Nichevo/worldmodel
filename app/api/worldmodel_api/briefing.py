"""The Briefing page, the "Latest on" strip on country pages, and news watch words.

Everything the app hears about arrives as one of five kinds, shown on one shared card:
feeds (news and CrisisWatch), finds (Discover), events (dated things that happened),
due (things coming up) and yours (what you kept). The Briefing sorts them into four
lanes: Happening, Found, Due and Yours.

Watch words: news that names one of your watch words (coup, protest, assassination...)
and a country becomes a "reported" item. Items about the same word, country and day
from several outlets are merged, placed on a city named in the text where one matches
(else the country), and marked confirmed once a dataset holds a matching event within
three days. The map draws reported items hollow and confirmed ones solid.

The functions here are pure (lists in, lists out) so they can be tested without a
warehouse; main.py feeds them.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# Which kind of dataset event confirms a news item about each watch word.
WORD_KIND = {
    "coup": {"coup"}, "assassination": {"leader", "notable", "conflict"}, "assassinated": {"leader", "notable", "conflict"},
    "invasion": {"conflict"}, "airstrike": {"conflict"}, "air strike": {"conflict"}, "massacre": {"conflict"},
    "ceasefire": {"conflict"}, "hostage": {"conflict"}, "blockade": {"conflict"},
    "tsunami": {"disaster", "earthquake"}, "eruption": {"disaster"}, "earthquake": {"disaster", "earthquake"},
    "cyclone": {"disaster", "storm"}, "hurricane": {"disaster", "storm"}, "typhoon": {"disaster", "storm"},
    "flood": {"disaster"}, "floods": {"disaster"}, "wildfire": {"disaster"}, "famine": {"disaster"},
    "outbreak": {"epidemic"}, "sanctions": {"sanction"}, "default": {"crisis"}, "impeachment": {"leader"},
    "resigns": {"leader"}, "protest": {"protest"}, "protests": {"protest"}, "riot": {"protest"}, "riots": {"protest"},
    "uprising": {"protest", "conflict"}, "martial law": {"coup", "conflict"}, "state of emergency": {"disaster", "conflict"},
}

# The colour family of each kind of marker on the map (the app maps these to its palette).
KIND_GROUP = {
    "coup": "conflict", "conflict": "conflict", "protest": "conflict", "sanction": "politics", "election": "politics",
    "leader": "politics", "summit": "politics", "un": "politics", "court": "politics", "treaty": "politics",
    "disaster": "hazard", "earthquake": "hazard", "storm": "hazard", "epidemic": "hazard",
    "crisis": "economy", "recession": "economy", "imf": "economy", "trade_dispute": "economy",
}

# Kinds that are not news on a map or in a briefing: long episodes worked out from yearly data,
# and holidays (every country has dozens).
QUIET_KINDS = {"recession", "boom", "inflation", "debt", "holiday", "independence", "notable", "law", "crisiswatch"}


def words(setting: str) -> list[str]:
    """The watch words from the setting, in order."""
    return [w.strip() for w in (setting or "").split(",") if w.strip()]


def _pattern(ws: list[str]) -> re.Pattern | None:
    if not ws:
        return None
    alts = sorted(ws, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in alts) + r")\b", re.I)


def matched(text: str, ws: list[str]) -> list[str]:
    """The watch words found in a piece of text, each once, in the order of the list."""
    p = _pattern(ws)
    if not p:
        return []
    found = {" ".join(m.group(1).lower().split()) for m in p.finditer(text or "")}
    return [w for w in ws if w in found]


def _day(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def place_in(text: str, cities: list[tuple[str, float, float]]) -> dict | None:
    """The biggest city of the country named in the text (cities come biggest first)."""
    low = f" {(text or '').lower()} "
    for name, lat, lon in cities:
        n = name.lower()
        if len(n) >= 4 and re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", low):
            return {"name": name, "lat": lat, "lon": lon}
    return None


def watch_hits(items: list[dict], ws: list[str], since: str, *, until: str | None = None, min_outlets: int = 1,
               cities: dict[str, list[tuple[str, float, float]]] | None = None,
               confirm: list[dict] | None = None) -> list[dict]:
    """News items naming a watch word and a country, merged by word, country and day.
    confirm: dataset events (entity_id, kind, start_date) that turn a report solid."""
    if not ws:
        return []
    groups: dict[tuple, dict] = {}
    for it in items:
        if it.get("kind") != "news" or it.get("source") == "gdelt":  # GDELT items are counts, not reports
            continue
        day = (it.get("date") or "")[:10]
        if not day or day < since[:10] or (until and day > until[:10]):
            continue
        text = f"{it.get('headline', '')} {it.get('detail', '')}"
        hit = matched(text, ws)
        ents = it.get("entities") or []
        if not hit or not ents:
            continue
        key = (hit[0], ents[0], day)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "key": f"watch:{hit[0]}:{ents[0]}:{day}", "word": hit[0], "words": list(hit), "date": day,
                "entity_id": ents[0], "entities": list(ents), "headline": it.get("headline", ""), "detail": it.get("detail", ""),
                "url": it.get("url"), "outlets": [], "urls": [], "score": it.get("score", 0.4), "place": None,
                "confirmed": False, "tone": "bad" if hit[0] not in ("ceasefire",) else "good",
            }
        outlet = it.get("outlet") or it.get("source") or ""
        if outlet and outlet not in g["outlets"]:
            g["outlets"].append(outlet)
        if it.get("url") and it["url"] not in g["urls"]:
            g["urls"].append(it["url"])
        g["words"] = list(dict.fromkeys([*g["words"], *hit]))
        if it.get("score", 0) > g["score"]:
            g.update(headline=it.get("headline", ""), detail=it.get("detail", ""), url=it.get("url"), score=it.get("score", 0))
        if g["place"] is None and cities:
            g["place"] = place_in(text, cities.get(ents[0], []))
    out = [g for g in groups.values() if len(g["outlets"]) >= min_outlets]
    by_entity: dict[str, list[dict]] = {}
    for e in confirm or []:
        by_entity.setdefault(e["entity_id"], []).append(e)
    for g in out:
        want = set().union(*(WORD_KIND.get(w, set()) for w in g["words"]))
        d = _day(g["date"])
        for e in by_entity.get(g["entity_id"], []):
            ed = _day(str(e.get("start_date")))
            if e.get("kind") in want and d and ed and abs((ed - d).days) <= 3:
                g["confirmed"] = True
                g["confirmed_by"] = e.get("title")
                break
        g["n_outlets"] = len(g["outlets"])
        g["group"] = next((KIND_GROUP[k] for w in g["words"] for k in sorted(WORD_KIND.get(w, ())) if k in KIND_GROUP), "news")
    out.sort(key=lambda g: (g["date"], g["n_outlets"], g["score"]), reverse=True)
    return out


# ----------------------------------------------------------------------------- the shared card
def card(kind: str, key: str, title: str, *, detail: str = "", day: str | None = None, entities: list[str] | None = None,
         source: str = "", url: str | None = None, href: str | None = None, tone: str = "neutral", group: str | None = None,
         **extra) -> dict:
    """One item on the shared card. kind: feed, find, event, due or yours."""
    return {"kind": kind, "key": key, "title": title, "detail": detail, "date": day, "entities": entities or [],
            "source": source, "url": url, "href": href, "tone": tone, "group": group, **extra}


CW_WORDS = {"deteriorated": "Deteriorated", "risk_alert": "Conflict risk alert", "improved": "Improved",
            "resolution_opportunity": "Resolution opportunity", "unchanged": "Unchanged"}


def crisiswatch_cards(rows: list[dict], month: str | None, keys: list[str]) -> list[dict]:
    """The month's changed CrisisWatch situations, key countries and alerts first."""
    order = {"risk_alert": 0, "deteriorated": 1, "resolution_opportunity": 2, "improved": 3}
    changed = [r for r in rows if r.get("subkind") in order]
    changed.sort(key=lambda r: (r["entity_id"] not in keys, order[r["subkind"]], r.get("name") or ""))
    return [card("feed", f"cw:{month}:{r['entity_id']}:{r.get('place') or ''}",
                 f"{r.get('name') or r['entity_id']}{' (' + r['place'] + ')' if r.get('place') else ''}: {CW_WORDS[r['subkind']].lower()}",
                 detail=r.get("detail") or "", day=f"{month}-01" if month else None, entities=[r["entity_id"]],
                 source="CrisisWatch", url=r.get("url"), href=f"/entity/{r['entity_id']}#crisiswatch",
                 tone="good" if r["subkind"] in ("improved", "resolution_opportunity") else "bad", group="crisiswatch",
                 rating=r["subkind"]) for r in changed]


def event_cards(events: list[dict], *, due: bool = False) -> list[dict]:
    """Dated events as cards, newest first (or soonest first for things due)."""
    out = []
    for e in events:
        if e.get("kind") in QUIET_KINDS:
            continue
        size = ""
        if e.get("deaths"):
            size = f"{int(e['deaths']):,} deaths"
        elif e.get("size") and e.get("size_unit"):
            size = f"{e['size']:g} {e['size_unit']}"
        detail = " · ".join(x for x in (e.get("place") or "", size, (e.get("detail") or "")[:300]) if x)
        out.append(card("due" if due else "event", f"ev:{e['event_id']}:{e['entity_id']}", e["title"], detail=detail,
                        day=str(e["start_date"])[:10], entities=[e["entity_id"]], source=e.get("source_id") or "",
                        url=e.get("url"), href=f"/events?entity={e['entity_id']}", group=e.get("kind"),
                        tone="neutral" if due or e.get("kind") in ("election", "sport", "summit") else "bad"))
    out.sort(key=lambda c: c["date"] or "", reverse=not due)
    return out


def watch_cards(hits: list[dict]) -> list[dict]:
    return [card("feed", h["key"], h["headline"], detail=f"{', '.join(h['outlets'])}", day=h["date"], entities=h["entities"],
                 source="Reported in the news", url=h["url"], href="/?w=7d", tone=h["tone"], group="watch", word=h["word"],
                 confirmed=h["confirmed"], n_outlets=h["n_outlets"]) for h in hits]


def news_cards(items: list[dict], since: str, limit: int, entity: str | None = None) -> list[dict]:
    """Top news (Wikipedia Current events and the feeds) since a day, best first."""
    keep = [i for i in items if i.get("kind") == "news" and i.get("source") != "gdelt" and (i.get("date") or "") >= since
            and (entity is None or entity in (i.get("entities") or []))]
    # newest day first, the most important first within a day: by score alone, a week-old Wikipedia
    # or ReliefWeb item (scored higher) pushed every one of today's headlines off the list
    keep.sort(key=lambda i: (i.get("date") or "", i.get("score", 0)), reverse=True)
    return [card("feed", i["key"], i["headline"], detail=i.get("detail") or "", day=i.get("date"), entities=i.get("entities") or [],
                 source=i.get("outlet") or "News", url=i.get("url"), href="/discover?tab=news", tone=i.get("tone", "neutral"),
                 group="news") for i in keep[:limit]]


def find_cards(finds: list[dict], limit: int) -> list[dict]:
    return [card("find", f["key"], f["headline"], detail=f.get("detail") or "", entities=f.get("entities") or [],
                 source=f.get("kind", ""), href=f"/discover?q={f['headline'][:60]}", tone=f.get("tone", "neutral"),
                 group=f.get("category"), new=bool(f.get("new")), rating=f.get("rating", 0),
                 find_kind=f.get("kind"), chart=f.get("chart")) for f in finds[:limit]]


def yours_cards(items: list[dict], limit: int) -> list[dict]:
    return [card("yours", f"hl:{h['id']}", h.get("title") or h.get("text", "")[:80] or "Kept item", detail=(h.get("note") or h.get("text") or "")[:300],
                 day=(h.get("created_at") or "")[:10], entities=h.get("entities") or [], source="Highlights",
                 href=f"/highlights?q={h['id']}", group=h.get("kind")) for h in items[:limit]]


def window(days: int, today: date | None = None) -> tuple[str, str]:
    t = today or date.today()
    return (t - timedelta(days=days)).isoformat(), t.isoformat()
