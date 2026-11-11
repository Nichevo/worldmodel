"""The Predictions page: your log of calls (yours, experts', the app's and the crowd's), each
checked and scored when it comes due; the scorecard; the base rates library; and the watchlist.

The log is predictions.json and the watchlist watchlist.json in the user folder (never the
warehouse). Functions that read the warehouse take `rows` (main.rows: SQL and parameters in,
a list of dicts out) so they can be tested on a small database.

Scores:
  yes/no calls   Brier score (chance minus outcome, squared; 0 is perfect, 0.25 is a coin toss)
                 and a hit when the side given 50% or more happened;
  number calls   the miss (outcome minus call, and as a share of the outcome) and a hit when
                 the outcome fell inside the range given;
  date calls     the miss in days and a hit when within the window given (30 days if none).
"""

from __future__ import annotations

import json
import math
import re
import secrets
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from worldmodel_contract import crowd, local

Rows = Callable[..., list[dict]]
_lock = threading.Lock()
KINDS = ("binary", "number", "date")
WHO_KINDS = ("you", "expert", "app", "crowd")
MAX_TEXT = 2000


def _path(name: str):
    return local.user_dir() / name


def _read(name: str) -> list[dict]:
    try:
        d = json.loads(_path(name).read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(name: str, data: list[dict]) -> None:
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(p)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _day(v, field: str, required: bool = False) -> str | None:
    if v in (None, ""):
        if required:
            raise ValueError(f"{field} is needed (YYYY-MM-DD)")
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a date (YYYY-MM-DD)")


def _num(v, field: str) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if not math.isfinite(x):
        raise ValueError(f"{field} must be a number")
    return x


def _text(v, n: int = MAX_TEXT) -> str:
    return " ".join(str(v or "").split())[:n] if n <= 300 else str(v or "").strip()[:n]


# ----------------------------------------------------------------------------- the log
def clean(data: dict, old: dict | None = None) -> dict:
    """A prediction from a form, checked: raises ValueError with a message for the page."""
    d = {**(old or {}), **data}
    kind = d.get("kind") or "binary"
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    q = _text(d.get("question"), 300)
    if not q:
        raise ValueError("Write the question or claim")
    who_kind = d.get("who_kind") or "you"
    if who_kind not in WHO_KINDS:
        raise ValueError(f"who_kind must be one of {', '.join(WHO_KINDS)}")
    out = {
        "id": (old or {}).get("id") or secrets.token_hex(6), "question": q, "kind": kind, "who_kind": who_kind,
        "who": _text(d.get("who"), 80) or ("You" if who_kind == "you" else "Worldmodel" if who_kind == "app" else ""),
        "link": _text(d.get("link"), 300) or None,
        "made": _day(d.get("made"), "made") or date.today().isoformat(), "due": _day(d.get("due"), "due", True),
        "category": _text(d.get("category"), 40) or None,
        "tags": [t for t in (_text(x, 30).lower() for x in (d.get("tags") or [])) if t][:12],
        "why": _text(d.get("why")) or None,
        "indicator": _text(d.get("indicator"), 80) or None, "entity": _text(d.get("entity"), 40) or None,
        "year": int(d["year"]) if d.get("year") not in (None, "") else None,
        "crowd_key": _text(d.get("crowd_key"), 80) or None, "unit": _text(d.get("unit"), 40) or None,
        "created_at": (old or {}).get("created_at") or now(), "outcome": (old or {}).get("outcome"),
    }
    if out["who_kind"] != "you" and not out["who"]:
        raise ValueError("Say whose prediction it is")
    if kind == "binary":
        c = _num(d.get("chance"), "chance")
        if c is None:
            raise ValueError("Give the chance of yes (0 to 100%)")
        if c > 1:
            c /= 100.0
        if not 0 <= c <= 1:
            raise ValueError("The chance must be between 0 and 100%")
        out["chance"] = c
    elif kind == "number":
        out["value"] = _num(d.get("value"), "value")
        if out["value"] is None:
            raise ValueError("Give the number")
        out["low"], out["high"] = _num(d.get("low"), "low"), _num(d.get("high"), "high")
        if out["low"] is not None and out["high"] is not None and out["low"] > out["high"]:
            out["low"], out["high"] = out["high"], out["low"]
    else:
        out["date_call"] = _day(d.get("date_call"), "date called", True)
        out["window_days"] = int(_num(d.get("window_days"), "window") or 30)
    if out["made"] > out["due"]:
        raise ValueError("The due date must be on or after the date made")
    return out


def items() -> list[dict]:
    return _read("predictions.json")


def save(data: dict, pred_id: str | None = None) -> dict:
    with _lock:
        all_ = items()
        old = next((p for p in all_ if p["id"] == pred_id), None) if pred_id else None
        if pred_id and old is None:
            raise KeyError(pred_id)
        p = clean(data, old)
        all_ = [x for x in all_ if x["id"] != p["id"]] + [p]
        _write("predictions.json", all_)
        return p


def delete(pred_id: str) -> bool:
    with _lock:
        all_ = items()
        keep = [p for p in all_ if p["id"] != pred_id]
        _write("predictions.json", keep)
        return len(keep) < len(all_)


def set_outcome(pred_id: str, actual, by: str = "you") -> dict:
    """Mark how it turned out (actual: true/false, a number or a date; null clears it)."""
    with _lock:
        all_ = items()
        p = next((x for x in all_ if x["id"] == pred_id), None)
        if p is None:
            raise KeyError(pred_id)
        if actual is None:
            p["outcome"] = None
        else:
            if p["kind"] == "binary":
                if isinstance(actual, str):
                    actual = actual.lower() in ("yes", "true", "1")
                actual = bool(actual)
            elif p["kind"] == "number":
                actual = _num(actual, "outcome")
            else:
                actual = _day(actual, "outcome", True)
            p["outcome"] = {"actual": actual, "at": now(), "by": by}
        _write("predictions.json", all_)
        return p


def score(p: dict) -> dict:
    """The score of one prediction with an outcome: hit, brier, miss, rel_miss."""
    o = p.get("outcome")
    if not o:
        return {}
    a = o["actual"]
    if p["kind"] == "binary":
        return {"hit": (p["chance"] >= 0.5) == bool(a), "brier": crowd.brier(p["chance"], bool(a)), "yes": bool(a)}
    if p["kind"] == "number":
        miss = a - p["value"]
        rel = abs(miss) / abs(a) if a else None
        hit = (p["low"] <= a <= p["high"]) if p.get("low") is not None and p.get("high") is not None else None
        return {"hit": hit, "miss": miss, "rel_miss": rel}
    days = (date.fromisoformat(a) - date.fromisoformat(p["date_call"])).days
    return {"hit": abs(days) <= (p.get("window_days") or 30), "miss": days}


def check(rows: Rows, today: date | None = None) -> list[dict]:
    """Fill in outcomes the app can see: a number call on an indicator once that year's figure is
    published, a yes/no call linked to a crowd question once the question resolved. Returns the
    ones newly settled."""
    today = today or date.today()
    settled = []
    with _lock:
        all_ = items()
        for p in all_:
            if p.get("outcome"):
                continue
            if p["kind"] == "number" and p.get("indicator") and p.get("entity") and p.get("year"):
                got = rows("""SELECT value FROM series WHERE indicator_id = ? AND entity_id = ? AND year(period_start) = ?
                    AND breakdown = '' AND variant = 'central' AND status = 'E' ORDER BY source_id LIMIT 1""",
                           [p["indicator"], p["entity"], int(p["year"])])
                if got and got[0]["value"] is not None and p["due"] <= today.isoformat():
                    p["outcome"] = {"actual": got[0]["value"], "at": now(), "by": "auto"}
                    settled.append(p)
            elif p["kind"] == "binary" and p.get("crowd_key"):
                got = _safe(rows, "SELECT resolution FROM crowd_questions WHERE question_key = ?", [p["crowd_key"]])
                res = got[0]["resolution"] if got else None
                if res in ("yes", "no"):
                    p["outcome"] = {"actual": res == "yes", "at": now(), "by": "auto"}
                    settled.append(p)
        if settled:
            _write("predictions.json", all_)
    return settled


def _safe(rows: Rows, sql: str, params: list | None = None) -> list[dict]:
    try:
        return rows(sql, params or [])
    except Exception:  # noqa: BLE001 - warehouses before 1.11.0 have no crowd tables
        return []


def listing(filt: dict | None = None, today: date | None = None) -> list[dict]:
    """The log with each one's state (open, due, settled) and score, newest first."""
    f = filt or {}
    t = (today or date.today()).isoformat()
    out = []
    for p in items():
        if f.get("who") and p["who"] != f["who"]:
            continue
        if f.get("category") and p.get("category") != f["category"]:
            continue
        if f.get("entity") and p.get("entity") != f["entity"]:
            continue
        if f.get("indicator") and p.get("indicator") != f["indicator"]:
            continue
        state = "settled" if p.get("outcome") else "due" if p["due"] <= t else "open"
        if f.get("state") and state != f["state"]:
            continue
        out.append({**p, "state": state, "score": score(p)})
    out.sort(key=lambda p: (p["state"] != "due", p["due"] if p["state"] != "settled" else "", p["made"]), reverse=False)
    return out


def due_soon(days: int = 30, today: date | None = None) -> list[dict]:
    t = today or date.today()
    hi = (t + timedelta(days=days)).isoformat()
    return [p for p in listing(today=t) if p["state"] in ("open", "due") and p["due"] <= hi]


# ----------------------------------------------------------------------------- scorecard
BINS = [(i / 10, (i + 1) / 10) for i in range(10)]


def _summary(name: str, kind: str, scored: list[tuple[dict, dict]], n_all: int) -> dict:
    """scored: (prediction-like {kind, chance}, score) pairs."""
    hits = [s["hit"] for _, s in scored if s.get("hit") is not None]
    briers = [s["brier"] for _, s in scored if s.get("brier") is not None]
    rel = [s["rel_miss"] for _, s in scored if s.get("rel_miss") is not None]
    cal = []
    for lo, hi in BINS:
        sel = [(p, s) for p, s in scored if p["kind"] == "binary" and (lo <= p["chance"] < hi or (hi == 1 and p["chance"] == 1))]
        if sel:
            cal.append({"from": lo, "to": hi, "n": len(sel), "forecast": sum(p["chance"] for p, _ in sel) / len(sel),
                        "observed": sum(1 for _, s in sel if s.get("yes")) / len(sel)})
    return {"name": name, "kind": kind, "n": n_all, "settled": len(scored), "hits": sum(hits), "scored_hits": len(hits),
            "hit_rate": sum(hits) / len(hits) if hits else None, "brier": sum(briers) / len(briers) if briers else None,
            "brier_n": len(briers), "rel_miss": sum(rel) / len(rel) if rel else None, "calibration": cal}


def scorecard(rows: Rows, *, category: str | None = None, entity: str | None = None, since: str | None = None,
              score_days: int = 7) -> list[dict]:
    """One row per forecaster: you, each expert, the app, each crowd site and each Metaculus account."""
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in items():
        if category and p.get("category") != category:
            continue
        if entity and p.get("entity") != entity:
            continue
        if since and p["made"] < since:
            continue
        by[(p["who"], p["who_kind"])].append(p)
    out = [_summary(who, kind, [(p, score(p)) for p in ps if p.get("outcome")], len(ps)) for (who, kind), ps in by.items()]
    out += crowd_scores(rows, score_days=score_days, category=category, entity=entity, since=since)
    out.sort(key=lambda r: (r["kind"] != "you", -(r["settled"] or 0)))
    return out


def crowd_scores(rows: Rows, *, score_days: int = 7, category: str | None = None, entity: str | None = None,
                 since: str | None = None) -> list[dict]:
    """Each crowd site, scored on resolved yes/no questions by its chance `score_days` before the
    question closed (the last saved chance on or before then); and each Metaculus account by its
    last forecast before the close."""
    where, params = ["q.kind = 'binary'", "q.resolution IN ('yes', 'no')"], []
    if category:
        where.append("q.category = ?")
        params.append(category)
    if entity:
        where.append("list_contains(string_split(q.countries, ','), ?)")
        params.append(entity)
    if since:
        where.append("coalesce(q.created, q.closes) >= ?")
        params.append(since)
    got = _safe(rows, f"""SELECT q.site, q.question_key, q.resolution,
            (SELECT p.chance FROM crowd_points p WHERE p.question_key = q.question_key
               AND p.at_time <= coalesce(q.closes, q.resolved_at) - INTERVAL {int(score_days)} DAY
             ORDER BY p.at_time DESC LIMIT 1) AS chance
        FROM crowd_questions q WHERE {' AND '.join(where)}""", params)
    sites: dict[str, list] = defaultdict(list)
    for r in got:
        if r["chance"] is not None:
            p = {"kind": "binary", "chance": r["chance"]}
            sites[r["site"]].append((p, {"hit": (r["chance"] >= 0.5) == (r["resolution"] == "yes"),
                                         "brier": crowd.brier(r["chance"], r["resolution"] == "yes"),
                                         "yes": r["resolution"] == "yes"}))
    out = [_summary(crowd.SITES.get(s, s), "crowd", v, len(v)) for s, v in sites.items()]
    mine = _safe(rows, f"""SELECT m.forecaster, q.resolution, arg_max(m.chance, m.at_time) AS chance
        FROM crowd_mine m JOIN crowd_questions q USING (question_key)
        WHERE {' AND '.join(where)} AND m.at_time <= coalesce(q.closes, q.resolved_at) GROUP BY ALL""", params)
    acc: dict[str, list] = defaultdict(list)
    for r in mine:
        p = {"kind": "binary", "chance": r["chance"]}
        acc[r["forecaster"]].append((p, {"hit": (r["chance"] >= 0.5) == (r["resolution"] == "yes"),
                                         "brier": crowd.brier(r["chance"], r["resolution"] == "yes"),
                                         "yes": r["resolution"] == "yes"}))
    out += [_summary(f"{name} on Metaculus", "you", v, len(v)) for name, v in acc.items()]
    return out


# ----------------------------------------------------------------------------- base rates
PRESETS = [
    {"id": "coup", "title": "A coup (or attempt) in a country in a year", "kind": "event", "event": "coup"},
    {"id": "recession", "title": "A recession starting in a country in a year", "kind": "event", "event": "recession"},
    {"id": "conflict", "title": "A war or armed conflict starting in a country in a year", "kind": "event", "event": "conflict"},
    {"id": "leader", "title": "A new head of state or government in a year", "kind": "event", "event": "leader"},
    {"id": "crisis", "title": "A banking or debt crisis starting in a year", "kind": "event", "event": "crisis"},
    {"id": "inflation_back", "title": "Inflation back under 3% within 2 years, once over 5%", "kind": "rule",
     "indicator": "inflation", "if_op": "above", "if_value": 5, "then_op": "below", "then_value": 3, "within": 2},
    {"id": "high_inflation", "title": "Inflation over 20% within 3 years, once over 10%", "kind": "rule",
     "indicator": "inflation", "if_op": "above", "if_value": 10, "then_op": "above", "then_value": 20, "within": 3},
    {"id": "boom_bust", "title": "Shrinking economy within 2 years, after growth over 5%", "kind": "rule",
     "indicator": "gdp_growth", "if_op": "above", "if_value": 5, "then_op": "below", "then_value": 0, "within": 2},
    {"id": "debt_down", "title": "Government debt under 60% of GDP within 10 years, once over 90%", "kind": "rule",
     "indicator": "govt_debt_gdp", "if_op": "above", "if_value": 90, "then_op": "below", "then_value": 60, "within": 10},
    {"id": "unemployment_low", "title": "Unemployment under 5% within 3 years, once over 8%", "kind": "rule",
     "indicator": "unemployment", "if_op": "above", "if_value": 8, "then_op": "below", "then_value": 5, "within": 3},
]


def _members(rows: Rows, group: str | None) -> set[str] | None:
    if not group:
        return None
    got = rows("SELECT member_id FROM memberships WHERE group_id = ?", [group])
    return {r["member_id"] for r in got} or {group}


def event_rate(rows: Rows, kind: str, *, entity: str | None = None, group: str | None = None, start: int = 1960,
               end: int | None = None, years: int = 1) -> dict:
    """How often a kind of event starts in a country in a year: country-years with one, out of all
    country-years since `start`, and the chance of at least one within `years` years if each year
    were alike (1 - (1 - rate)^years)."""
    end = end or date.today().year - 1
    members = _members(rows, group)
    countries = [r["entity_id"] for r in rows("""SELECT entity_id FROM entities WHERE type = 'country'
        AND (valid_to IS NULL OR year(valid_to) >= ?) AND (valid_from IS NULL OR year(valid_from) <= ?)""", [start, end])]
    if members is not None:
        countries = [c for c in countries if c in members]
    if entity:
        countries = [entity]
    got = rows("""SELECT entity_id, year(start_date) AS y, min(title) AS title FROM events
        WHERE kind = ? AND year(start_date) BETWEEN ? AND ? AND entity_id IN (SELECT unnest(?)) GROUP BY 1, 2""",
               [kind, start, end, countries])
    span = end - start + 1
    n_years = len(countries) * span
    hits = len(got)
    rate = hits / n_years if n_years else None
    by_decade: dict[int, int] = defaultdict(int)
    for r in got:
        by_decade[r["y"] // 10 * 10] += 1
    top: dict[str, int] = defaultdict(int)
    for r in got:
        top[r["entity_id"]] += 1
    return {"kind": "event", "event": kind, "start": start, "end": end, "countries": len(countries), "country_years": n_years,
            "cases": hits, "rate": rate, "within": years, "chance_within": (1 - (1 - rate) ** years) if rate is not None else None,
            "by_decade": [{"decade": d, "cases": n, "rate": n / (len(countries) * 10) if countries else None}
                          for d, n in sorted(by_decade.items())],
            "top": sorted(({"entity_id": e, "cases": n} for e, n in top.items()), key=lambda x: -x["cases"])[:15],
            "examples": sorted(({"entity_id": r["entity_id"], "year": r["y"], "title": r["title"]} for r in got),
                               key=lambda x: -x["year"])[:12]}


def _ok(v: float, op: str, x: float) -> bool:
    return v > x if op == "above" else v < x


def indicator_rule(rows: Rows, indicator: str, if_op: str, if_value: float, then_op: str, then_value: float, within: int,
                   *, entity: str | None = None, group: str | None = None, start: int = 1960) -> dict:
    """From each year a country first met the condition (the start of a spell), how often the
    outcome followed within `within` years. Spells too recent to have had the full time to play
    out are left out."""
    if if_op not in ("above", "below") or then_op not in ("above", "below"):
        raise ValueError("if_op and then_op are above or below")
    members = _members(rows, group)
    got = rows("""SELECT s.entity_id, year(s.period_start) AS y, avg(s.value) AS v FROM series s
        JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
        WHERE s.indicator_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E' AND year(s.period_start) >= ?
        GROUP BY 1, 2 ORDER BY 1, 2""", [indicator, start])
    by: dict[str, dict[int, float]] = defaultdict(dict)
    for r in got:
        if r["v"] is not None and (members is None or r["entity_id"] in members) and (not entity or r["entity_id"] == entity):
            by[r["entity_id"]][r["y"]] = r["v"]
    last_year = max((max(v) for v in by.values() if v), default=start)
    cases = []
    for e, ys in by.items():
        prev = None
        for y in sorted(ys):
            now_ok = _ok(ys[y], if_op, if_value)
            if now_ok and not (prev is not None and _ok(prev, if_op, if_value)) and y + within <= last_year:
                hit = next((y2 for y2 in range(y + 1, y + within + 1) if y2 in ys and _ok(ys[y2], then_op, then_value)), None)
                cases.append({"entity_id": e, "year": y, "value": ys[y], "then_year": hit,
                              "then_value": ys.get(hit) if hit else None})
            prev = ys[y]
    n, k = len(cases), sum(1 for c in cases if c["then_year"])
    return {"kind": "rule", "indicator": indicator, "if_op": if_op, "if_value": if_value, "then_op": then_op,
            "then_value": then_value, "within": within, "start": start, "cases": n, "happened": k,
            "rate": k / n if n else None, "examples": sorted(cases, key=lambda c: -c["year"])[:20]}


def base_rate(rows: Rows, preset: str | None = None, **kw) -> dict:
    p = next((x for x in PRESETS if x["id"] == preset), None) if preset else None
    if preset and p is None:
        raise KeyError(preset)
    spec = {**(p or {}), **{k: v for k, v in kw.items() if v not in (None, "")}}
    common = {k: spec.get(k) for k in ("entity", "group") if spec.get(k)}
    if spec.get("kind") == "event" or spec.get("event"):
        out = event_rate(rows, spec["event"], start=int(spec.get("start") or 1960), years=int(spec.get("within") or 1), **common)
    else:
        out = indicator_rule(rows, spec["indicator"], spec["if_op"], float(spec["if_value"]), spec["then_op"],
                             float(spec["then_value"]), int(spec["within"]), start=int(spec.get("start") or 1960), **common)
    out["title"] = (p or {}).get("title") or ""
    out["preset"] = preset
    return out


# ----------------------------------------------------------------------------- watchlist
WATCH_KINDS = ("indicator", "crowd", "forecast")


def watchlist() -> list[dict]:
    return _read("watchlist.json")


def add_watch(d: dict) -> dict:
    kind = d.get("kind")
    if kind not in WATCH_KINDS:
        raise ValueError(f"kind must be one of {', '.join(WATCH_KINDS)}")
    w = {"id": secrets.token_hex(5), "kind": kind, "created_at": now(), "note": _text(d.get("note"), 200) or None}
    if kind in ("indicator", "forecast"):
        if not d.get("indicator") or not d.get("entity"):
            raise ValueError("Pick an indicator and a country")
        w.update(indicator=_text(d["indicator"], 80), entity=_text(d["entity"], 40))
        if kind == "indicator":
            if d.get("op") not in ("above", "below"):
                raise ValueError("op is above or below")
            w.update(op=d["op"], threshold=_num(d.get("threshold"), "threshold"))
            if w["threshold"] is None:
                raise ValueError("Give the line to watch")
        else:
            w["threshold"] = abs(_num(d.get("threshold"), "threshold") or 0.5)
    else:
        if not d.get("question_key"):
            raise ValueError("Pick a crowd question")
        w.update(question_key=_text(d["question_key"], 80), points=_num(d.get("points"), "points"))
    with _lock:
        all_ = watchlist() + [w]
        _write("watchlist.json", all_[-500:])
    return w


def delete_watch(watch_id: str) -> bool:
    with _lock:
        all_ = watchlist()
        keep = [w for w in all_ if w["id"] != watch_id]
        _write("watchlist.json", keep)
        return len(keep) < len(all_)


def check_watch(rows: Rows, move_points: float = 10) -> list[dict]:
    """Each watch with its state now and whether it is alerting: an indicator past its line (the
    latest figure on the other side from the one before), a crowd chance that moved at least
    `points` (else move_points) percentage points in a week, an IMF forecast revised by at least
    the threshold between its last two releases."""
    out = []
    for w in watchlist():
        r = {**w, "alert": False, "text": "", "date": None}
        if w["kind"] == "indicator":
            got = rows("""SELECT year(period_start) AS y, value FROM series WHERE indicator_id = ? AND entity_id = ?
                AND breakdown = '' AND variant = 'central' AND status = 'E' ORDER BY 1 DESC LIMIT 2""", [w["indicator"], w["entity"]])
            if got:
                now_ok = _ok(got[0]["value"], w["op"], w["threshold"])
                before = _ok(got[1]["value"], w["op"], w["threshold"]) if len(got) > 1 else False
                r.update(value=got[0]["value"], year=got[0]["y"], alert=now_ok and not before, date=f"{got[0]['y']}-12-31",
                         text=f"{got[0]['value']:.4g} in {got[0]['y']}, {'now ' if now_ok and not before else ''}"
                              f"{'above' if got[0]['value'] > w['threshold'] else 'below'} {w['threshold']:g}")
        elif w["kind"] == "crowd":
            pts = _safe(rows, """SELECT at_time, chance FROM crowd_points WHERE question_key = ?
                AND at_time >= now() - INTERVAL 30 DAY ORDER BY at_time""", [w["question_key"]])
            q = _safe(rows, "SELECT title, chance FROM crowd_questions WHERE question_key = ?", [w["question_key"]])
            if pts:
                last = pts[-1]
                week = [p for p in pts if p["at_time"] <= last["at_time"] - timedelta(days=7)]
                then = week[-1] if week else pts[0]
                move = (last["chance"] - then["chance"]) * 100
                lim = w.get("points") or move_points
                r.update(title=q[0]["title"] if q else w["question_key"], chance=last["chance"], move=move,
                         alert=abs(move) >= lim, date=str(last["at_time"])[:10],
                         text=f"{last['chance'] * 100:.0f}% ({'+' if move >= 0 else ''}{move:.0f} points in a week)")
            elif q:
                r.update(title=q[0]["title"], chance=q[0]["chance"], text="No saved chances in the last month yet")
        else:
            got = _safe(rows, """SELECT left(vintage, 7) AS vintage, avg(value) AS v FROM observations
                WHERE source_id LIKE 'imf_weo%' AND indicator_id = ? AND entity_id = ? AND year(period_start) = ?
                    AND breakdown = '' AND variant = 'central'
                GROUP BY 1 ORDER BY 1 DESC LIMIT 2""", [w["indicator"], w["entity"], date.today().year + 1])
            if len(got) == 2 and got[0]["v"] is not None and got[1]["v"] is not None:
                ch = got[0]["v"] - got[1]["v"]
                r.update(alert=abs(ch) >= w["threshold"], date=None,
                         text=f"IMF forecast for {date.today().year + 1}: {got[0]['v']:.2f} ({got[0]['vintage']}), "
                              f"{'+' if ch >= 0 else ''}{ch:.2f} since {got[1]['vintage']}")
            else:
                r["text"] = "Needs two IMF releases with a forecast for next year"
        out.append(r)
    return out


# ----------------------------------------------------------------------------- drafting from a link
DRAFT_PROMPT = """Below is the text of an article. Find the clearest prediction in it that someone made about the future
(who made it, what they said will happen, by when). Answer with JSON only, no other words:
{{"question": "...", "who": "...", "kind": "binary|number|date", "chance": 0.0-1.0 or null, "value": number or null,
"low": number or null, "high": number or null, "unit": "..." or null, "date_call": "YYYY-MM-DD" or null,
"due": "YYYY-MM-DD", "made": "YYYY-MM-DD" or null, "why": "one sentence"}}
If there is no prediction, answer {{"question": null}}.

Article ({url}):
{text}"""


def page_text(html: str, limit: int = 12000) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return " ".join(text.split())[:limit]


def parse_draft(answer: str) -> dict:
    answer = re.sub(r"<think>.*?</think>", "", answer or "", flags=re.S)
    m = re.search(r"\{.*\}", answer, re.S)
    if not m:
        raise ValueError("The local AI did not answer with a draft")
    try:
        d = json.loads(m.group(0))
    except ValueError:
        raise ValueError("The local AI's draft was not readable; try again or fill the form yourself")
    if not d.get("question"):
        raise ValueError("The local AI found no prediction in that page")
    d["kind"] = d.get("kind") if d.get("kind") in KINDS else "binary"
    d["who_kind"] = "expert"
    return {k: v for k, v in d.items() if v not in (None, "")}
