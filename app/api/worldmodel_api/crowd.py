"""The Crowd page: Polymarket, Metaculus and Manifold questions matched to countries and
indicators, each one's chance over time, comments, the biggest moves, events against
predictions, the country card, and ViEWS conflict forecasts.

Functions take `rows` (main.rows) so they can be tested on a small database. Every query
tolerates a warehouse without the crowd tables (before schema 1.11.0): it answers empty."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable

from worldmodel_contract import crowd

Rows = Callable[..., list[dict]]


def _safe(rows: Rows, sql: str, params: list | None = None) -> list[dict]:
    try:
        return rows(sql, params or [])
    except Exception:  # noqa: BLE001 - warehouses before 1.11.0
        return []


def has_data(rows: Rows) -> bool:
    return bool(_safe(rows, "SELECT 1 FROM crowd_questions LIMIT 1"))


CHANGE = """(SELECT p.chance FROM crowd_points p WHERE p.question_key = q.question_key
             AND p.at_time <= now() - INTERVAL {days} DAY ORDER BY p.at_time DESC LIMIT 1)"""
LAST = """(SELECT p.chance FROM crowd_points p WHERE p.question_key = q.question_key ORDER BY p.at_time DESC LIMIT 1)"""


def _row(r: dict) -> dict:
    r = dict(r)
    r["countries"] = [c for c in (r.get("countries") or "").split(",") if c]
    if r.get("options"):
        try:
            r["options"] = json.loads(r["options"])
        except ValueError:
            r["options"] = None
    for k in ("created", "closes", "resolved_at"):
        if r.get(k) is not None:
            r[k] = str(r[k])[:19]
    if r.get("chance") is not None and r.get("before") is not None and r.get("kind") == "binary":
        r["change"] = r["chance"] - r["before"]
    else:
        r["change"] = None
    r.pop("before", None)
    r["site_name"] = crowd.SITES.get(r.get("site") or "", r.get("site"))
    return r


def questions(rows: Rows, *, site: str | None = None, category: str | None = None, country: str | None = None,
              status: str | None = "open", q: str | None = None, indicator: str | None = None, follow: list[str] | None = None,
              hide: list[str] | None = None, only_followed: bool = False, show_hidden: bool = False, sort: str = "busy",
              days: int = 7, limit: int = 50, offset: int = 0) -> dict:
    where, params = ["true"], []
    if site:
        where.append("q.site = ?")
        params.append(site)
    if category:
        where.append("q.category = ?")
        params.append(category)
    if country:
        where.append("list_contains(string_split(q.countries, ','), ?)")
        params.append(country)
    if status:
        where.append("q.status = ?")
        params.append(status)
    if indicator:
        where.append("q.indicator_id = ?")
        params.append(indicator)
    if q:
        where.append("q.title ILIKE ?")
        params.append(f"%{q}%")
    if only_followed:
        where.append("q.question_key IN (SELECT unnest(?))")
        params.append(list(follow or []) or [""])
    if hide and not show_hidden:
        where.append("q.question_key NOT IN (SELECT unnest(?))")
        params.append(list(hide))
    order = {"busy": "coalesce(q.forecasters, 0) * 1000 + coalesce(q.volume, 0) DESC",
             "closing": "q.closes NULLS LAST", "newest": "q.created DESC NULLS LAST",
             "moved": f"abs(coalesce(q.chance, {LAST}) - coalesce({CHANGE.format(days=int(days))}, q.chance)) DESC NULLS LAST",
             "resolved": "q.resolved_at DESC NULLS LAST"}.get(sort, "q.closes")
    base = f"FROM crowd_questions q WHERE {' AND '.join(where)}"
    total = _safe(rows, f"SELECT count(*) AS n {base}", params)
    got = _safe(rows, f"""SELECT q.question_key, q.site, q.title, q.url, q.kind, q.category, q.countries, q.indicator_id,
            q.created, q.closes, q.resolved_at, q.status, q.resolution, coalesce(q.chance, {LAST}) AS chance, q.volume,
            q.forecasters, q.comments, q.options, {CHANGE.format(days=int(days))} AS before
        {base} ORDER BY {order} LIMIT ? OFFSET ?""", [*params, limit, offset])
    fol, hid = set(follow or []), set(hide or [])
    items = [{**_row(r), "followed": r["question_key"] in fol, "hidden": r["question_key"] in hid} for r in got]
    counts = _safe(rows, "SELECT site, status, count(*) AS n FROM crowd_questions GROUP BY ALL")
    return {"total": total[0]["n"] if total else 0, "items": items, "counts": counts, "days": days}


def question(rows: Rows, key: str) -> dict | None:
    got = _safe(rows, f"""SELECT q.*, {CHANGE.format(days=7)} AS before FROM crowd_questions q WHERE q.question_key = ?""", [key])
    if not got:
        return None
    rec = _row({k: v for k, v in got[0].items() if k not in ("source_id", "vintage")})
    pts = _safe(rows, "SELECT at_time, chance, lower, upper, origin FROM crowd_points WHERE question_key = ? ORDER BY at_time", [key])
    rec["points"] = [{"at": str(p["at_time"])[:19], "chance": p["chance"], "lower": p["lower"], "upper": p["upper"],
                      "origin": p["origin"]} for p in pts]
    mine = _safe(rows, "SELECT forecaster, at_time, chance, community FROM crowd_mine WHERE question_key = ? ORDER BY at_time", [key])
    rec["mine"] = [{"forecaster": m["forecaster"], "at": str(m["at_time"])[:19], "chance": m["chance"], "community": m["community"]}
                   for m in mine]
    com = _safe(rows, """SELECT comment_id, parent_id, author, created, votes, forecast, text FROM crowd_comments
        WHERE question_key = ? ORDER BY created DESC""", [key])
    rec["comment_list"] = [{**c, "created": str(c["created"])[:19] if c["created"] else None} for c in com]
    # The same question elsewhere: other sites' questions on the same countries whose titles share most words.
    rec["similar"] = similar(rows, rec)
    lo = (rec.get("created") or "2000-01-01")[:10]
    rec["events"] = _safe(rows, """SELECT event_id, entity_id, kind, title, start_date, end_date FROM events
        WHERE entity_id IN (SELECT unnest(?)) AND start_date >= ? AND kind NOT IN ('holiday', 'crisiswatch', 'law', 'boom',
            'inflation', 'debt', 'independence', 'notable') ORDER BY start_date DESC LIMIT 40""", [rec["countries"] or [""], lo])
    for e in rec["events"]:
        e["start_date"] = str(e["start_date"])[:10]
        e["end_date"] = str(e["end_date"])[:10] if e.get("end_date") else None
    return rec


def _words(t: str) -> set[str]:
    import re
    stop = {"will", "the", "a", "an", "of", "in", "on", "by", "be", "to", "before", "after", "and", "or", "for", "is", "at",
            "than", "more", "less", "what", "who", "which", "win", "next"}
    return {w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if w not in stop and len(w) > 2}


def similar(rows: Rows, rec: dict, n: int = 5) -> list[dict]:
    if not rec.get("countries"):
        return []
    got = _safe(rows, """SELECT question_key, site, title, chance, status, url FROM crowd_questions
        WHERE question_key <> ? AND site <> ? AND list_has_any(string_split(countries, ','), ?) AND status = 'open'
        LIMIT 400""", [rec["question_key"], rec["site"], rec["countries"]])
    mine = _words(rec["title"])
    scored = []
    for g in got:
        w = _words(g["title"])
        j = len(mine & w) / len(mine | w) if mine | w else 0
        if j >= 0.3:
            scored.append({**g, "site_name": crowd.SITES.get(g["site"], g["site"]), "match": j})
    return sorted(scored, key=lambda g: -g["match"])[:n]


def moves(rows: Rows, *, days: int = 7, min_points: float = 10, countries: list[str] | None = None,
          follow: list[str] | None = None, hide: list[str] | None = None, limit: int = 30) -> list[dict]:
    """Open yes/no questions whose chance moved most over `days` days (at least min_points points);
    with countries or follow, only those questions."""
    got = _safe(rows, f"""SELECT q.question_key, q.site, q.title, q.url, q.kind, q.category, q.countries, q.indicator_id,
            q.closes, q.status, coalesce(q.chance, {LAST}) AS chance, {CHANGE.format(days=int(days))} AS before, q.created,
            q.resolved_at, q.resolution, q.volume, q.forecasters, q.comments, q.options
        FROM crowd_questions q WHERE q.status = 'open' AND q.kind = 'binary'""")
    want_c, fol, hid = set(countries or []), set(follow or []), set(hide or [])
    out = []
    for r in got:
        if r["question_key"] in hid or r["before"] is None or r["chance"] is None:
            continue
        cs = set((r["countries"] or "").split(","))
        if (want_c or fol) and not (cs & want_c or r["question_key"] in fol):
            continue
        if abs(r["chance"] - r["before"]) * 100 >= min_points:
            out.append(_row(r))
    out.sort(key=lambda r: -abs(r["change"]))
    return out[:limit]


def closing(rows: Rows, keys: list[str], days: int = 30) -> list[dict]:
    if not keys:
        return []
    got = _safe(rows, """SELECT question_key, site, title, url, kind, category, countries, closes, status, chance
        FROM crowd_questions WHERE question_key IN (SELECT unnest(?)) AND status = 'open'
            AND closes BETWEEN now() AND now() + INTERVAL ? DAY ORDER BY closes""", [keys, days])
    return [{**_row(r), "change": None} for r in got]


def events_vs(rows: Rows, score_days: int = 7) -> dict:
    """For resolved yes/no questions with saved chances: did the crowd see it coming (the chance
    `score_days` before closing), when it first passed 50%, how many days ahead of the
    resolution that was, and surprises (a yes the crowd gave under 20%, a no it gave over 80%).
    Summed by category and by site."""
    got = _safe(rows, """SELECT q.question_key, q.site, q.title, q.url, q.category, q.countries, q.resolution,
            q.closes, q.resolved_at, list(struct_pack(at := p.at_time, c := p.chance) ORDER BY p.at_time) AS pts
        FROM crowd_questions q JOIN crowd_points p USING (question_key)
        WHERE q.kind = 'binary' AND q.resolution IN ('yes', 'no') GROUP BY ALL""")
    items = []
    for r in got:
        end = r["closes"] or r["resolved_at"]
        if end is None:
            continue
        pts = [(p["at"], p["c"]) for p in r["pts"] if p["c"] is not None]
        cutoff = end - timedelta(days=score_days)
        before = [c for at, c in pts if at <= cutoff]
        chance = before[-1] if before else None
        yes = r["resolution"] == "yes"
        first50 = next((at for at, c in pts if (c >= 0.5) == yes), None)
        lead = (end - first50).days if first50 and yes else None
        items.append({"question_key": r["question_key"], "site": r["site"], "site_name": crowd.SITES.get(r["site"], r["site"]),
                      "title": r["title"], "url": r["url"], "category": r["category"],
                      "countries": [c for c in (r["countries"] or "").split(",") if c], "resolution": r["resolution"],
                      "closed": str(end)[:10], "chance": chance, "brier": crowd.brier(chance, yes) if chance is not None else None,
                      "first_right": str(first50)[:10] if first50 else None, "lead_days": lead,
                      "surprise": chance is not None and ((yes and chance < 0.2) or (not yes and chance > 0.8))})
    def summary(key: str) -> list[dict]:
        by: dict[str, list[dict]] = defaultdict(list)
        for i in items:
            by[i[key] or "other"].append(i)
        out = []
        for k, v in by.items():
            scored = [i for i in v if i["brier"] is not None]
            leads = [i["lead_days"] for i in v if i["lead_days"] is not None]
            out.append({"key": k, "n": len(v), "brier": sum(i["brier"] for i in scored) / len(scored) if scored else None,
                        "surprises": sum(1 for i in v if i["surprise"]), "median_lead": sorted(leads)[len(leads) // 2] if leads else None})
        return sorted(out, key=lambda x: -x["n"])
    items.sort(key=lambda i: i["closed"], reverse=True)
    return {"score_days": score_days, "items": items[:300], "by_category": summary("category"), "by_site": summary("site_name"),
            "n": len(items)}


def country(rows: Rows, entity: str, hide: list[str] | None = None, limit: int = 8) -> dict:
    qs = questions(rows, country=entity, status="open", hide=hide, sort="busy", limit=limit)["items"]
    vf = _safe(rows, """SELECT month, deaths, chance_25 FROM conflict_forecasts WHERE entity_id = ? AND kind = 'sb'
        AND month >= date_trunc('month', current_date) ORDER BY month LIMIT 36""", [entity])
    views = None
    if vf:
        first12 = vf[:12]
        views = {"months": [{"month": str(v["month"])[:7], "deaths": v["deaths"], "chance_25": v["chance_25"]} for v in vf],
                 "deaths_12": sum(v["deaths"] or 0 for v in first12),
                 "max_chance": max((v["chance_25"] or 0) for v in first12)}
    return {"entity_id": entity, "questions": qs, "views": views}


def conflict_map(rows: Rows) -> dict:
    """ViEWS by country: predicted deaths over the next 12 months and the highest monthly chance of 25 or more."""
    got = _safe(rows, """SELECT entity_id, sum(deaths) AS deaths, max(chance_25) AS chance, min(month) AS first, max(run) AS run
        FROM conflict_forecasts WHERE kind = 'sb' AND month >= date_trunc('month', current_date)
            AND month < date_trunc('month', current_date) + INTERVAL 12 MONTH GROUP BY 1 ORDER BY 2 DESC""")
    return {"rows": [{**r, "first": str(r["first"])[:7]} for r in got]}


def briefing_cards(rows: Rows, card, *, key_countries: list[str], follow: list[str], hide: list[str], min_points: float,
                   days: int = 7) -> tuple[list[dict], list[dict]]:
    """Big moves this week (key countries and followed questions) for Happening, and followed
    questions closing in the next 30 days for Due, as the Briefing's shared card."""
    mv = moves(rows, days=days, min_points=min_points, countries=key_countries, follow=follow, hide=hide, limit=12)
    happening = [card("feed", f"crowd:{m['question_key']}", m["title"],
                      detail=f"{m['site_name']}: {m['chance'] * 100:.0f}% ({'+' if m['change'] >= 0 else ''}{m['change'] * 100:.0f} points in {days} days)",
                      day=datetime.now().date().isoformat(), entities=m["countries"], source=m["site_name"], url=m["url"],
                      href=f"/crowd/question?key={m['question_key']}", group="crowd",
                      tone="neutral", chance=m["chance"], change=m["change"]) for m in mv]
    due = [card("due", f"crowdclose:{c['question_key']}", c["title"],
                detail=f"{c['site_name']}: {c['chance'] * 100:.0f}% now" if c.get("chance") is not None else c["site_name"],
                day=(c.get("closes") or "")[:10], entities=c["countries"], source=c["site_name"], url=c["url"],
                href=f"/crowd/question?key={c['question_key']}", group="crowd") for c in closing(rows, follow)]
    return happening, due
