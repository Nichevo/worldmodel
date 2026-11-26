"""Discover, the Briefing, map events and the weekly digest."""

from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import Body, HTTPException, Query

from worldmodel_contract import crowd as crowd_terms
from worldmodel_contract import discover, local
from worldmodel_api import ai, briefing, crowd, highlights, news, predictions, userdata
from worldmodel_api.core import _build_id, _has_cities, _has_table, api, cursor, rows
from worldmodel_api.routes.events import EVENT_COLUMNS
from worldmodel_api.routes.conflict import crisiswatch


# ----------------------------------------------------------------------------- Discover
_d_cache: dict = {"build": None, "finds": []}


def _finds() -> list[dict]:
    """The finds for the live build: the pipeline's saved copy, else worked out here once and saved."""
    build = _build_id()
    if _d_cache["build"] != build:
        saved = discover.load_saved(local.home(), build, exact=True)
        if saved is None:
            found = discover.compute(cursor(), local.home(), userdata.settings())
            try:
                discover.save(local.home(), build, found)
            except OSError:
                pass
        else:
            found = saved.get("finds", [])
        _d_cache.update(build=build, finds=found)
    return _d_cache["finds"]


def _news_names() -> "news.Names":
    return news.Names(cursor().execute("SELECT entity_id, short_name FROM entities WHERE type = 'country' AND short_name IS NOT NULL").fetchall())


def _stamp_first_seen(items: list[dict], st: dict) -> None:
    """The first time each find was listed, for "New since your last visit"."""
    now_ = userdata.now()
    fresh = {f["key"]: now_ for f in items if f["key"] not in st["first_seen"]}
    if fresh:
        st["first_seen"].update(fresh)
        if len(st["first_seen"]) > 50_000:  # keep the newest
            st["first_seen"] = dict(sorted(st["first_seen"].items(), key=lambda kv: kv[1])[-40_000:])
        discover.save_user_state(st)


def _when(f: dict) -> tuple[str, str]:
    """The days a find or news item covers, as ISO dates: a news item's day, a find's years."""
    if f.get("date"):
        return f["date"], f["date"]
    ys = [y for y in (f.get("years") or []) if y]
    return (f"{min(ys)}-01-01", f"{max(ys)}-12-31") if ys else ("", "")


@api.get("/discover")
def discover_list(tab: str = Query("finds", pattern="^(finds|interesting|hidden|news)$"), category: str | None = None,
                  kind: str | None = None, tone: str | None = None, entity: str | None = None, tag: str | None = None,
                  q: str | None = None, sort: str = Query("score", pattern="^(score|newest|key)$"), new: bool = False,
                  since: str | None = Query(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$"), until: str | None = Query(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$"),
                  limit: int = Query(60, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Interesting finds on the live build (and news), scored for you. Tabs: finds (all but the
    ones you hid), interesting (the ones you marked), hidden (marked Not interesting, or a kind
    you never want), news. Filters by category, kind, tone, country, tag, words and dates
    (since/until: a news item's day, or the years a find covers)."""
    s = userdata.settings()
    st = discover.user_state()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    finds = _finds() if tab != "news" else []
    pool = finds + (news.items() if tab in ("news", "interesting", "hidden") else [])
    _stamp_first_seen(pool, st)
    ranked = discover.ranked(pool, st, keys, float(s.get("discover_key_boost", 1.5)), bool(s.get("discover_tune", True)))
    if tab == "news":
        ranked = [f for f in ranked if f["kind"] == "news" and f["rating"] >= 0]
    elif tab == "interesting":
        ranked = [f for f in ranked if f["rating"] > 0]
    elif tab == "hidden":
        ranked = [f for f in ranked if f["rating"] < 0 or f["never"]]
    else:
        ranked = [f for f in ranked if f["rating"] >= 0 and not f["never"] and f["kind"] != "news"]
    last = st.get("last_visit")
    for f in ranked:
        f["new"] = bool(last and f.get("first_seen") and f["first_seen"] > last)
    facets = {"categories": {}, "kinds": {}, "tones": {}, "entities": {}, "tags": {}}
    words = [w for w in (q or "").lower().split() if w]

    def keep(f: dict) -> bool:
        if category and f["category"] != category or kind and f["kind"] != kind or tone and f["tone"] != tone:
            return False
        if entity and entity not in f.get("entities", []) or tag and tag not in f.get("tags", []) or new and not f["new"]:
            return False
        if since or until:
            first, last_ = _when(f)
            if not first or since and last_ < since[:10] or until and first[: len(until)] > until:
                return False
        hay = f"{f['headline']} {f.get('detail', '')} {' '.join(f.get('tags', []))}".lower()
        return all(w in hay for w in words)

    shown = [f for f in ranked if keep(f)]
    for f in ranked:  # counts across the tab, so a filter can be changed without losing the others
        for k, v in (("categories", f["category"]), ("kinds", f["kind"]), ("tones", f["tone"])):
            facets[k][v] = facets[k].get(v, 0) + 1
        for e in f.get("entities", []):
            facets["entities"][e] = facets["entities"].get(e, 0) + 1
        for t in f.get("tags", []):
            facets["tags"][t] = facets["tags"].get(t, 0) + 1
    facets["tags"] = dict(sorted(facets["tags"].items(), key=lambda kv: -kv[1])[:60])
    if sort == "newest":
        shown.sort(key=lambda f: (f.get("first_seen") or "", f.get("date") or str((f.get("years") or [0])[-1])), reverse=True)
    elif sort == "key":
        order = {k: i for i, k in enumerate(keys)}
        shown.sort(key=lambda f: (min((order.get(e, 99) for e in f.get("entities", [])), default=99), -f["rank_score"]))
    names = dict(cursor().execute("SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))",
                                  [list(facets["entities"])]).fetchall())
    st_news = news.state()
    return {"items": shown[offset: offset + limit], "total": len(shown), "facets": facets, "names": names,
            "build_id": _build_id(), "last_visit": last, "new_count": sum(1 for f in ranked if f["new"]),
            "kinds": {**discover.KINDS, "news": "News"}, "categories": discover.CATEGORIES, "never": st["never"],
            "news": {"on": bool(s.get("news_on", True)), "running": st_news["running"], "finished_at": st_news.get("finished_at"),
                     "errors": st_news["errors"], "last": st_news["last"], "due": news.is_due(s, st_news)}}


def _discover_find(key: str) -> dict | None:
    for f in _finds():
        if f["key"] == key:
            return f
    return next((i for i in news.items() if i["key"] == key), None)


@api.put("/discover/{key:path}")
def discover_mark(key: str, change: dict = Body(...)):
    """Your mark on one find: rating 1 (Interesting), -1 (Not interesting) or 0; tags (your own);
    tone ("good", "bad", "neutral", or null for the app's own)."""
    st = discover.user_state()
    f = _discover_find(key) or st["kept"].get(key)
    if f is None:
        raise HTTPException(404, f"no find {key}")
    if "rating" in change:
        r = int(change["rating"] or 0)
        if r not in (-1, 0, 1):
            raise HTTPException(422, "rating is 1, -1 or 0")
        if r:
            st["ratings"][key] = r
        else:
            st["ratings"].pop(key, None)
        if r > 0:
            st["kept"][key] = {k: v for k, v in f.items() if k not in ("stale", "rating", "rank_score", "new")}
        else:
            st["kept"].pop(key, None)
    if "tags" in change:
        tags = ai.clean_tags(change.get("tags"))
        if tags:
            st["tags"][key] = tags
        else:
            st["tags"].pop(key, None)
    if "tone" in change:
        t = change.get("tone")
        if t in discover.TONES:
            st["tones"][key] = t
        elif t is None:
            st["tones"].pop(key, None)
        else:
            raise HTTPException(422, "tone is good, bad, neutral or null")
    discover.save_user_state(st)
    return {"key": key, "rating": st["ratings"].get(key, 0), "my_tags": st["tags"].get(key, []), "tone": st["tones"].get(key, f["tone"])}


@api.put("/discover-never/{kind}")
def discover_never(kind: str, on: bool = Body(..., embed=True)):
    """Never show this kind of find (or show it again)."""
    if kind not in discover.KINDS and kind != "news":
        raise HTTPException(404, f"no kind {kind}")
    st = discover.user_state()
    st["never"] = sorted({*st["never"], kind} if on else set(st["never"]) - {kind})
    discover.save_user_state(st)
    return {"never": st["never"]}


@api.post("/discover-seen")
def discover_seen():
    """Mark the feed as seen now: later finds are "new since your last visit"."""
    st = discover.user_state()
    st["last_visit"] = userdata.now()
    discover.save_user_state(st)
    return {"last_visit": st["last_visit"]}


@api.get("/discover-entity/{entity_id}")
def discover_entity(entity_id: str, limit: int = Query(5, ge=1, le=50)):
    """A country's top finds, for the Discover card on its page."""
    s = userdata.settings()
    st = discover.user_state()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    mine = [f for f in _finds() if entity_id in f.get("entities", [])]
    ranked = [f for f in discover.ranked(mine, st, keys, float(s.get("discover_key_boost", 1.5)), bool(s.get("discover_tune", True)))
              if f["rating"] >= 0 and not f["never"] and entity_id in f.get("entities", [])]
    # One find per kind of change on one measure: a record in population, male population
    # and female population is one find on the card, not three.
    seen: set[tuple] = set()
    items = []
    for f in ranked:
        fam = (f.get("kind"), re.sub(r"_(total|male|female|men|women)$", "", f.get("indicator_id") or f.get("key", "")))
        if fam in seen:
            continue
        seen.add(fam)
        items.append(f)
    return {"items": items[:limit], "total": len(items)}


@api.post("/news/fetch")
def news_fetch(force: bool = False):
    """Fetch major news in the background (when due, or now with force); see GET /discover?tab=news."""
    s = userdata.settings()
    if not s.get("news_on", True):
        raise HTTPException(409, "News is switched off (Settings: Discover).")
    if not force and not news.is_due(s):
        return {"started": False, "why": "fetched recently", **news.state()}
    return {"started": news.start(s, _news_names()), **news.state()}


@api.post("/discover-rescan")
def discover_rescan():
    """Work the finds out again on the live build (after changing Discover's settings)."""
    found = discover.compute(cursor(), local.home(), userdata.settings())
    discover.save(local.home(), _build_id(), found)
    _d_cache.update(build=_build_id(), finds=found)
    return {"finds": len(found)}


# ----------------------------------------------------------------------------- Briefing, map events, watch words


def _city_index(entities: list[str]) -> dict[str, list[tuple[str, float, float]]]:
    """Cities of 100,000 people or more in these countries, biggest first, for placing news on the map."""
    if not entities or not _has_cities():
        return {}
    out: dict[str, list[tuple[str, float, float]]] = {}
    for r in rows("""SELECT country_id, name, lat, lon FROM cities WHERE population >= 100000
            AND country_id IN (SELECT unnest(?)) ORDER BY population DESC""", [sorted(set(entities))]):
        out.setdefault(r["country_id"], []).append((r["name"], r["lat"], r["lon"]))
    return out


def _starting(lo: str, hi: str, entity: str | None = None, quiet: bool = False) -> list[dict]:
    """Events that start between two days (not the long worked-out episodes, unless quiet)."""
    where = ["e.start_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"]
    params: list = [lo, hi]
    if not quiet:
        where.append("e.kind NOT IN (SELECT unnest(?))")
        params.append(sorted(briefing.QUIET_KINDS))
    if entity:
        where.append("e.entity_id = ?")
        params.append(entity)
    found = rows(f"""SELECT {', '.join('e.' + c for c in EVENT_COLUMNS)}, n.short_name AS entity_name FROM events e
        LEFT JOIN entities n USING (entity_id) WHERE {' AND '.join(where)} ORDER BY e.start_date DESC LIMIT 3000""", params)
    for r in found:
        for k in ("start_date", "end_date"):
            r[k] = r[k].isoformat() if r[k] else None
        r["group"] = briefing.KIND_GROUP.get(r["kind"], "other")
    return found


def _watch(lo: str, hi: str, entity: str | None = None) -> list[dict]:
    s = userdata.settings()
    ws = briefing.words(s.get("news_watch_words", ""))
    items = [i for i in news.items() if entity is None or entity in (i.get("entities") or [])]
    ents = sorted({e for i in items for e in (i.get("entities") or [])[:1]})
    confirm = rows("""SELECT entity_id, kind, start_date, title FROM events WHERE start_date BETWEEN
        CAST(? AS DATE) - INTERVAL 3 DAY AND CAST(? AS DATE) + INTERVAL 3 DAY""", [lo, hi])
    return briefing.watch_hits(items, ws, lo, until=hi, min_outlets=int(s.get("news_watch_outlets", 1)),
                               cities=_city_index(ents), confirm=confirm)


@api.get("/map-events")
def map_events(start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """What happened between two days, for the map's Events and News layers: dated events that start in the
    window (placed on their country), and news that names a watch word (placed on a city it names, else
    its country; confirmed once a dataset holds a matching event). Earthquakes and storm tracks are map
    layers of their own (GET /layers), filtered to the same window by the app."""
    if start > end:
        raise HTTPException(422, "start is after end")
    return {"start": start, "end": end, "events": _starting(start, end), "watch": _watch(start, end),
            "words": briefing.words(userdata.settings().get("news_watch_words", ""))}


def _cw_latest() -> tuple[str | None, list[dict]]:
    found = crisiswatch(None) if _has_table("events") else {"month": None, "rows": []}
    return found["month"], found["rows"]


def _briefing_predict(s: dict, keys: list[str], days: int) -> tuple[list[dict], list[dict]]:
    """The Briefing's prediction cards: big crowd moves and watchlist alerts for Happening; followed
    crowd questions closing and your predictions coming due for Due. Never breaks the page."""
    happening: list[dict] = []
    due: list[dict] = []
    try:
        f = crowd_terms.load_follow()
        h, d = crowd.briefing_cards(rows, briefing.card, key_countries=keys, follow=f["follow"], hide=f["hide"],
                                    min_points=float(s.get("crowd_move_points", 10)), days=min(days, 30))
        happening += h
        due += d
    except Exception:  # noqa: BLE001
        pass
    try:
        if s.get("watchlist_on", True):
            for w in predictions.check_watch(rows, s.get("crowd_move_points", 10)):
                if w.get("alert"):
                    happening.append(briefing.card("feed", f"watch:{w['id']}", w.get("title") or w.get("note") or
                                                   f"{w.get('indicator')} in {w.get('entity')}",
                                                   detail=w.get("text") or "", day=w.get("date"), group="alert",
                                                   entities=[w["entity"]] if w.get("entity") else [], source="Your watchlist",
                                                   href="/predictions?tab=watchlist", tone="neutral"))
        for p in predictions.due_soon(30):
            due.append(briefing.card("due", f"pred:{p['id']}", p["question"], detail=f"Your log: {p.get('who') or 'You'}",
                                     day=p["due"], entities=[p["entity"]] if p.get("entity") else [], source="Predictions",
                                     href="/predictions", group="prediction"))
    except Exception:  # noqa: BLE001
        pass
    return happening, due


@api.get("/briefing")
def briefing_page(days: int | None = Query(None, ge=1, le=90)):
    """Everything new in four lanes, each a list of the shared card: happening (CrisisWatch's month,
    news that names a watch word, events of the last days, top news), found (Discover's best finds),
    due (events coming up in the next 60 days) and yours (what you kept lately)."""
    s = userdata.settings()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    days = days or int(s.get("briefing_days", 7))
    lo, hi = briefing.window(days)
    month, cw = _cw_latest()
    feed = discover_list(tab="finds", category=None, kind=None, tone=None, entity=None, tag=None, q=None, sort="score",
                         new=False, since=None, until=None, limit=12, offset=0)
    finds = sorted(feed["items"], key=lambda f: (not f.get("new"), -f.get("rank_score", 0)))
    ahead = (date.today() + timedelta(days=60)).isoformat()
    due = [e for e in _starting((date.today() + timedelta(days=1)).isoformat(), ahead)
           if e["kind"] in ("election", "sport", "summit", "court", "un", "treaty") or e["entity_id"] in keys]
    hl = highlights.search()
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities")}
    p_happening, p_due = _briefing_predict(s, keys, days)
    return {
        "days": days, "since": lo, "build_id": _build_id(), "crisiswatch_month": month, "key_countries": keys, "names": names,
        "news_due": bool(s.get("news_on", True)) and news.is_due(s),
        "lanes": {
            "happening": [*briefing.crisiswatch_cards(cw, month, keys), *briefing.watch_cards(_watch(lo, hi)),
                          *briefing.event_cards(_starting(lo, hi)), *briefing.news_cards(news.items(), lo, 8), *p_happening],
            "found": briefing.find_cards(finds, 8),
            "due": [*briefing.event_cards(due, due=True)[:20], *p_due],
            "yours": briefing.yours_cards(hl, 6),
        },
    }


@api.get("/entities/{entity_id}/latest")
def entity_latest(entity_id: str, days: int = Query(30, ge=1, le=365)):
    """The "Latest on" strip of a country page: its CrisisWatch rating this month (and last), news that names
    a watch word, events of the last days, top news and its best Discover finds, as shared cards."""
    lo, hi = briefing.window(days)
    cw = None
    if _has_table("events"):
        got = rows("""SELECT strftime(start_date, '%Y-%m') AS month, subkind, detail, place, url FROM events
            WHERE kind = 'crisiswatch' AND entity_id = ? ORDER BY start_date DESC LIMIT 2""", [entity_id])
        if got:
            cw = {**got[0], "label": briefing.CW_WORDS.get(got[0]["subkind"] or "", got[0]["subkind"]),
                  "previous": got[1]["subkind"] if len(got) > 1 else None}
    # Finds about this country itself, not ones where it is one of a hundred countries setting a record.
    finds = [f for f in discover_entity(entity_id, limit=30)["items"] if entity_id in (f.get("entities") or []) and len(f.get("entities") or []) <= 3]
    cards = [*briefing.watch_cards(_watch(lo, hi, entity_id)), *briefing.event_cards(_starting(lo, hi, entity_id)),
             *briefing.news_cards(news.items(), lo, 5, entity_id), *briefing.find_cards(finds, 3)]
    ids = sorted({e for c in cards for e in c["entities"][:3]} | {entity_id})
    names = {r["entity_id"]: r["short_name"] for r in rows(
        "SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [ids])}
    return {"entity_id": entity_id, "days": days, "crisiswatch": cw, "cards": cards, "names": names}

# ----------------------------------------------------------------------------- weekly digest (Briefing > Week)
@api.get("/digest")
def digest_view(week: str | None = Query(None, pattern=r"^\d{4}-W\d{2}$", description="2026-W45; default the last whole week")):
    """One Monday-to-Sunday week: new figures, finds, crowd moves, predictions due and settled, CrisisWatch,
    events and news. Kept once the week is over (Settings: weekly digest); the week in progress is worked out each time."""
    from worldmodel_api import digest
    import sys
    try:
        return digest.get(sys.modules[__name__], week)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@api.get("/digests")
def digests_list():
    """The weeks with a kept digest, newest first, and the last whole week and this one."""
    from worldmodel_api import digest
    return {"kept": digest.saved(), "last_complete": digest.last_complete(), "this_week": digest.week_id(date.today())}
