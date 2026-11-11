"""The weekly digest (Briefing > Week): one Monday-to-Sunday week in one page, made once and kept.

Made on the first visit on or after the Monday that follows the week, from what the app holds then,
and kept in user/digests/<year>-W<week>.json so it reads the same later (Settings: weekly digest).
The week in progress can be looked at too ("so far"); that one is worked out each time and not kept.

Sections: sources with new figures and the key countries' headline figures that changed; finds that
Discover saw first that week; big crowd moves; your predictions that came due or were settled;
CrisisWatch changes; events and the top news of the week. Never breaks: a part that fails is left out.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable

from worldmodel_api import userdata

WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def week_id(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(wid: str) -> date:
    m = WEEK.match(wid)
    if not m:
        raise ValueError("week must look like 2026-W45")
    return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)


def last_complete(today: date | None = None) -> str:
    t = today or date.today()
    return week_id(t - timedelta(days=t.weekday() + 7))


def _file(wid: str) -> str:
    return f"digests/{wid}.json"


def saved() -> list[str]:
    folder = userdata._path("digests")
    return sorted((p.stem for p in folder.glob("*.json") if WEEK.match(p.stem)), reverse=True) if folder.exists() else []


def load(wid: str) -> dict | None:
    return userdata._read_json(_file(wid), None)


def keep(d: dict) -> None:
    userdata._write_json(_file(d["week"]), d)


def _part(fn: Callable[[], list], notes: list[str], label: str) -> list:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - the digest never breaks on one part
        notes.append(f"{label}: left out ({type(exc).__name__})")
        return []


def build(m, wid: str, today: date | None = None) -> dict:
    """The digest for a week. m is the main module (its rows and the Briefing's helpers)."""
    from worldmodel_api import briefing, crowd, predictions
    from worldmodel_contract import crowd as crowd_terms
    from worldmodel_contract import discover

    t = today or date.today()
    lo_d = week_start(wid)
    hi_d = lo_d + timedelta(days=6)
    lo, hi = lo_d.isoformat(), hi_d.isoformat()
    s = userdata.settings()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k] or ["NZL", "AUS", "GBR", "USA"]
    notes: list[str] = []
    rows = m.rows

    def sources():
        return [{"source_id": r["source_id"], "vintage": r["vintage"], "day": str(r["retrieved_at"])[:10], "rows": r["row_count"]}
                for r in rows("""SELECT source_id, vintage, retrieved_at, row_count FROM vintages
                    WHERE CAST(retrieved_at AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY retrieved_at DESC""", [lo, hi])]

    srcs = _part(sources, notes, "New figures")

    def changed():
        """The key countries' headline figures whose newest edition (loaded that week) differs from the one before."""
        ids = [x["source_id"] for x in srcs]
        if not ids:
            return []
        got = rows("""
            WITH first AS (SELECT indicator_id, arg_min(source_id, rank) AS src FROM indicator_sources GROUP BY 1),
            v AS (SELECT s.entity_id, s.indicator_id, s.source_id, s.vintage, year(s.period_start) AS y, s.value
                  FROM series s JOIN first f ON f.indicator_id = s.indicator_id AND f.src = s.source_id
                  WHERE s.source_id IN (SELECT unnest(?)) AND s.indicator_id IN (SELECT unnest(?)) AND s.entity_id IN (SELECT unnest(?))
                    AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E' AND s.value IS NOT NULL),
            ranked AS (SELECT *, dense_rank() OVER (PARTITION BY source_id ORDER BY vintage DESC) AS vr FROM v)
            SELECT a.entity_id, a.indicator_id, a.source_id, a.y, a.value AS now, b.value AS before, a.vintage
            FROM ranked a LEFT JOIN ranked b ON b.entity_id = a.entity_id AND b.indicator_id = a.indicator_id
                AND b.source_id = a.source_id AND b.y = a.y AND b.vr = 2
            WHERE a.vr = 1 AND a.source_id IN (SELECT source_id FROM ranked WHERE vr = 2)  -- a source's first edition is not a change
                AND (b.value IS NULL OR abs(a.value - b.value) > 1e-9 * greatest(abs(a.value), 1))
            QUALIFY row_number() OVER (PARTITION BY a.entity_id, a.indicator_id ORDER BY a.y DESC) = 1
            ORDER BY a.entity_id, a.indicator_id""", [ids, m.HEADLINE, keys])
        names = {r["indicator_id"]: (r["name"], r["unit"]) for r in rows(
            "SELECT indicator_id, name, unit FROM indicators WHERE indicator_id IN (SELECT unnest(?))", [m.HEADLINE])}
        return [{**r, "name": names.get(r["indicator_id"], (r["indicator_id"], ""))[0],
                 "unit": names.get(r["indicator_id"], ("", ""))[1]} for r in got[:60]]

    def finds():
        st_first = discover.user_state().get("first_seen", {})
        pool = [f for f in m._finds() if lo <= (st_first.get(f["key"]) or "")[:10] <= hi]
        pool.sort(key=lambda f: -f.get("rank_score", f.get("score", 0)))
        return briefing.find_cards(pool, 10)

    def crowd_moves():
        f = crowd_terms.load_follow()
        mv = crowd.moves(rows, days=7, min_points=float(s.get("crowd_move_points", 10)), follow=f["follow"], hide=f["hide"], limit=10)
        return [{"title": x["title"], "site": x["site_name"], "chance": x["chance"], "change": x["change"], "url": x["url"],
                 "key": x["question_key"], "countries": x["countries"]} for x in mv]

    def preds():
        out = []
        for p in predictions.items():
            o = p.get("outcome") or {}
            settled = (o.get("at") or "")[:10]
            if lo <= settled <= hi:
                out.append({"id": p["id"], "question": p["question"], "who": p.get("who") or "You", "state": "settled",
                            "day": settled, "score": predictions.score(p)})
            elif lo <= p.get("due", "") <= hi and not o:
                out.append({"id": p["id"], "question": p["question"], "who": p.get("who") or "You", "state": "due", "day": p["due"]})
        return out

    def cw():
        month, got = m._cw_latest()
        if not month or not (lo[:7] <= month <= hi[:7] or month == (lo_d - timedelta(days=10)).isoformat()[:7]):
            return []
        return briefing.crisiswatch_cards(got, month, keys)[:15]

    out = {
        "week": wid, "from": lo, "to": hi, "made": datetime.now().isoformat(timespec="minutes"),
        "complete": hi_d < t, "key_countries": keys,
        "sources": srcs,
        "changed": _part(changed, notes, "Changed figures"),
        "finds": _part(finds, notes, "Discover finds"),
        "crowd": _part(crowd_moves, notes, "Crowd moves"),
        "predictions": _part(preds, notes, "Predictions"),
        "crisiswatch": _part(cw, notes, "CrisisWatch"),
        "events": _part(lambda: briefing.event_cards(m._starting(lo, hi))[:25], notes, "Events"),
        "news": _part(lambda: [c for c in briefing.news_cards(m.news.items(), lo, 40) if (c["date"] or "") <= hi][:10], notes, "News"),
        "notes": notes,
    }
    ids = {e for part in ("finds", "crisiswatch", "events", "news") for c in out[part] for e in c.get("entities", [])[:5]}
    ids |= {r["entity_id"] for r in out["changed"]} | set(keys)
    ids |= {e for c in out["crowd"] for e in (c.get("countries") or [])}
    out["names"] = {r["entity_id"]: r["short_name"] for r in
                    rows("SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [sorted(ids)])}
    return out


def get(m, wid: str | None = None, today: date | None = None) -> dict:
    """A kept digest, or one made now (and kept, when its week is over and the setting is on)."""
    t = today or date.today()
    wid = wid or last_complete(t)
    week_start(wid)  # checks the form
    have = load(wid)
    if have:
        return {**have, "kept": True}
    d = build(m, wid, t)
    if d["complete"] and userdata.settings().get("digest_on", True):
        keep(d)
        return {**d, "kept": True}
    return {**d, "kept": False}
