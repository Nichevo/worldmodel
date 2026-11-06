"""Indicator quality: six scores from 1 to 5 and a grade from A to D for every indicator.

Worked out from what a warehouse holds (history, up to date, coverage, dataset health) and
from the catalogue (source standing, standard or exploratory). Both the pipeline (after each
build, to say what changed) and the app (the Indicators page and the drop-downs) use this.

    scores = compute(con)                  # {indicator_id: {...}}
    save(home, build_id, scores)           # <home>/warehouse/quality/<build_id>.json
    changes(previous_scores, scores, stars)

The person's stars (indicators kept in every drop-down) and grade overrides live in the
user folder: indicator_stars.json and grade_overrides.json.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from worldmodel_contract import catalogue, local

SCORES = {
    "history": "History",
    "up_to_date": "Up to date",
    "coverage": "Coverage",
    "standing": "Source standing",
    "health": "Dataset health",
    "definition": "Standard or exploratory",
}
WEIGHTS = {"standing": 2.0, "definition": 2.0, "history": 1.5, "up_to_date": 1.5, "coverage": 1.0, "health": 1.0}
GRADES = {"A": "Core", "B": "Good", "C": "Usable", "D": "Exploratory"}
CUTS = (("A", 4.2), ("B", 3.5), ("C", 2.7))
SHOW = {"A": ("A",), "B": ("A", "B"), "C": ("A", "B", "C"), "all": ("A", "B", "C", "D")}
DEFINITIONS = {"standard": 5, "established": 4, "exploratory": 2}
DEFINITION_TEXT = {
    "standard": "an internationally agreed definition",
    "established": "a well-documented, widely used measure",
    "exploratory": "new, pilot, model-based or rough",
}
STANDING_TEXT = {5: "a national statistics office or the UN, World Bank, IMF or OECD",
                 4: "a long-running research set", 3: "an NGO or think-tank index",
                 2: "crowd-sourced or read from web pages", 1: "unknown"}
KEY_COUNTRIES = ("NZL", "AUS", "GBR", "USA")
MEASURE_TYPES = {"level": "Level", "per_person": "Per person", "rate": "Rate or share", "index": "Index or score",
                 "money": "Money", "count": "Count", "projection": "Projection"}


# ----------------------------------------------------------------------------- the person's choices
def _user_json(name: str, default):
    try:
        data = json.loads((local.user_dir() / name).read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def stars() -> list[str]:
    return [s for s in _user_json("indicator_stars.json", {}).get("stars", []) if isinstance(s, str)]


def overrides() -> dict[str, str]:
    data = _user_json("grade_overrides.json", {}).get("grades", {})
    return {k: v for k, v in data.items() if v in GRADES}


# ----------------------------------------------------------------------------- measure type
_PER_PERSON = re.compile(r"per (capita|person|head|inhabitant|1,?000|100,?000|10,?000|100 people)", re.I)
_MONEY = re.compile(r"us\$|usd|dollar|\bppp\b|\blcu\b|nzd|eur\b|euro|currency|\$", re.I)
_INDEX = re.compile(r"index|score|points|rating|\(0[-–]1\)|0 to 1\b|1 to 10", re.I)
_COUNT = re.compile(r"^(persons|people|count|number|events|cases|deaths|items|countries|sanctions|votes)$", re.I)


def measure_type(indicator_id: str, name: str, unit: str | None) -> str:
    """How a figure is expressed, for the Type filter on the drop-downs."""
    n, u = name or "", (unit or "").strip()
    if re.search(r"projected|projection|forecast", n, re.I) or indicator_id.endswith("_proj"):
        return "projection"
    if _PER_PERSON.search(n) or _PER_PERSON.search(u) or "per_capita" in indicator_id:
        return "per_person"
    if "%" in u or "percent" in u.lower() or re.search(r"\b(rate|share|ratio)\b", n, re.I):
        return "rate"
    if _MONEY.search(u):
        return "money"
    if _INDEX.search(u) or _INDEX.search(n):
        return "index"
    if _COUNT.match(u):
        return "count"
    return "level"


# ----------------------------------------------------------------------------- the scores
def _history(span: int, fill: float) -> tuple[int, str]:
    s = 5 if span >= 50 else 4 if span >= 30 else 3 if span >= 15 else 2 if span >= 5 else 1
    if fill < 0.3 and s > 1:
        s -= 1
    return s, f"{span} year(s), {round(100 * fill)}% of country-years filled"


def _up_to_date(freq: str, last: date | None, today: date) -> tuple[int, str]:
    if last is None:
        return 1, "no figures yet"
    months = (today.year - last.year) * 12 + today.month - last.month
    if freq == "A":
        years = today.year - last.year
        s = 5 if years <= 2 else 4 if years <= 3 else 3 if years <= 5 else 2 if years <= 10 else 1
        return s, f"latest year {last.year}, {years} year(s) ago"
    if freq == "Q":
        s = 5 if months <= 6 else 4 if months <= 12 else 3 if months <= 24 else 2 if months <= 48 else 1
    elif freq == "M":
        s = 5 if months <= 3 else 4 if months <= 6 else 3 if months <= 12 else 2 if months <= 24 else 1
    else:  # daily or weekly
        days = (today - last).days
        s = 5 if days <= 31 else 4 if days <= 90 else 3 if days <= 365 else 2 if days <= 730 else 1
    return s, f"latest {last.isoformat()[:7]}, {months} month(s) ago ({'quarterly' if freq == 'Q' else 'monthly' if freq == 'M' else 'daily'})"


def _coverage(recent: int, keys: list[str]) -> tuple[int, str]:
    s = 5 if recent >= 150 else 4 if recent >= 100 else 3 if recent >= 50 else 2 if recent >= 15 else 1
    missing = [k for k in KEY_COUNTRIES if k not in keys]
    if missing and recent >= 15 and s > 1:
        s -= 1
    note = f"{recent} countries with recent figures"
    return s, note + (f"; none recent for {', '.join(missing)}" if missing else "; NZ, Australia, UK and US all in")


def _health(n: int, out_of_range: int, jumps: int, changes: int, gap: float | None) -> tuple[int, str]:
    s, notes = 5, []
    if out_of_range:
        share = out_of_range / max(n, 1)
        s -= 2 if share > 0.01 else 1
        notes.append(f"{out_of_range} value(s) outside the allowed range")
    if changes:
        share = jumps / changes
        if share > 0.05:
            s -= 2
        elif share > 0.01:
            s -= 1
        if jumps:
            notes.append(f"{round(100 * share, 1)}% of yearly changes are sudden breaks (tenfold or more)")
    if gap is not None:
        if gap > 0.25:
            s -= 2
        elif gap > 0.10:
            s -= 1
        notes.append(f"its two sources differ by {round(100 * gap)}% (median)")
    return max(s, 1), "; ".join(notes) or "no problems found by the checks"


def grade_of(scores: dict[str, int], definition: str) -> str:
    total = sum(WEIGHTS[k] * scores[k] for k in WEIGHTS) / sum(WEIGHTS.values())
    g = next((g for g, cut in CUTS if total >= cut), "D")
    if definition == "exploratory" and g in ("A", "B"):
        g = "C"  # new, pilot or rough figures are never core, however full
    return g


def _catalogue_terms() -> tuple[dict[str, int | None], dict[str, str], dict[str, str]]:
    standing, src_def, ind_def = {}, {}, {}
    try:
        for sid, s in catalogue.sources().items():
            standing[sid] = s.standing
            src_def[sid] = s.definition
        for iid, i in catalogue.indicators().items():
            if i.definition:
                ind_def[iid] = i.definition
    except Exception:  # noqa: BLE001 - a catalogue problem leaves the defaults
        pass
    return standing, src_def, ind_def


SQL = """
WITH r1 AS (SELECT indicator_id, source_id FROM indicator_sources WHERE rank = 1),
s AS (
    SELECT s.indicator_id, s.entity_id, s.period_start, year(s.period_start) AS y, s.freq, s.value
    FROM series s JOIN r1 USING (indicator_id, source_id) JOIN entities e ON e.entity_id = s.entity_id
    WHERE s.status = 'E' AND s.breakdown = '' AND s.variant = 'central' AND e.type = 'country'),
agg AS (
    SELECT indicator_id, mode(freq) AS freq, min(y) AS y0, max(y) AS y1, max(period_start) AS last,
           count(DISTINCT entity_id) AS countries, count(DISTINCT (entity_id, y)) AS cy, count(*) AS n
    FROM s GROUP BY 1),
recent AS (
    SELECT s.indicator_id, count(DISTINCT s.entity_id) AS recent,
           list(DISTINCT s.entity_id) FILTER (WHERE s.entity_id IN ('NZL', 'AUS', 'GBR', 'USA')) AS keys
    FROM s JOIN agg USING (indicator_id) WHERE s.y >= agg.y1 - 2 GROUP BY 1),
bounds AS (
    SELECT s.indicator_id, count(*) AS out_of_range
    FROM s JOIN indicators i USING (indicator_id)
    WHERE (i.bound_min IS NOT NULL AND s.value < i.bound_min) OR (i.bound_max IS NOT NULL AND s.value > i.bound_max)
    GROUP BY 1),
yearly AS (
    SELECT indicator_id, entity_id, y, avg(value) AS v FROM s GROUP BY ALL),
steps AS (
    SELECT indicator_id, value_now / prev AS ratio FROM (
        SELECT indicator_id, v AS value_now, lag(v) OVER (PARTITION BY indicator_id, entity_id ORDER BY y) AS prev,
               y - lag(y) OVER (PARTITION BY indicator_id, entity_id ORDER BY y) AS gap
        FROM yearly) WHERE gap = 1 AND prev > 0 AND value_now > 0),
jumps AS (
    SELECT indicator_id, count(*) AS changes, count(*) FILTER (WHERE ratio >= 10 OR ratio <= 0.1) AS jumps
    FROM steps GROUP BY 1),
r2 AS (SELECT indicator_id, source_id FROM indicator_sources WHERE rank = 2),
agree AS (
    SELECT a.indicator_id, median(abs(a.value - b.value) / greatest(abs(a.value), abs(b.value))) AS gap
    FROM series a JOIN r1 ON r1.indicator_id = a.indicator_id AND r1.source_id = a.source_id
    JOIN series b ON b.indicator_id = a.indicator_id AND b.entity_id = a.entity_id AND b.period_start = a.period_start
        AND b.breakdown = '' AND b.variant = 'central' AND b.status = 'E'
    JOIN r2 ON r2.indicator_id = b.indicator_id AND r2.source_id = b.source_id
    WHERE a.breakdown = '' AND a.variant = 'central' AND a.status = 'E' AND greatest(abs(a.value), abs(b.value)) > 0
    GROUP BY 1)
SELECT i.indicator_id, i.name, i.unit, i.frequency, r1.source_id, agg.freq, agg.y0, agg.y1, agg.last, agg.countries,
       agg.cy, agg.n, coalesce(recent.recent, 0) AS recent, recent.keys, coalesce(bounds.out_of_range, 0) AS out_of_range,
       coalesce(jumps.jumps, 0) AS jumps, coalesce(jumps.changes, 0) AS changes, agree.gap
FROM indicators i LEFT JOIN r1 USING (indicator_id) LEFT JOIN agg USING (indicator_id)
LEFT JOIN recent USING (indicator_id) LEFT JOIN bounds USING (indicator_id) LEFT JOIN jumps USING (indicator_id)
LEFT JOIN agree USING (indicator_id)
"""


def compute(con, today: date | None = None) -> dict[str, dict]:
    """Scores, notes, grade and measure type for every indicator in the warehouse behind con."""
    today = today or date.today()
    standing, src_def, ind_def = _catalogue_terms()
    cur = con.execute(SQL)
    cols = [d[0] for d in cur.description]
    out = {}
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        iid, src = r["indicator_id"], r["source_id"] or ""
        sc, notes = {}, {}
        if r["y0"] is None:
            sc.update(history=1, up_to_date=1, coverage=1, health=3)
            notes.update(history="no figures in the warehouse yet", up_to_date="no figures yet", coverage="no countries yet",
                         health="nothing to check yet")
        else:
            span = r["y1"] - r["y0"] + 1
            fill = r["cy"] / max(1, r["countries"] * span)
            sc["history"], notes["history"] = _history(span, fill)
            last = r["last"] if isinstance(r["last"], date) else None
            sc["up_to_date"], notes["up_to_date"] = _up_to_date(r["freq"] or r["frequency"] or "A", last, today)
            sc["coverage"], notes["coverage"] = _coverage(r["recent"], list(r["keys"] or []))
            sc["health"], notes["health"] = _health(r["n"], r["out_of_range"], r["jumps"], r["changes"], r["gap"])
        st = standing.get(src)
        sc["standing"] = st if st else 3
        notes["standing"] = (f"{src}: {STANDING_TEXT.get(st, 'unknown')}" if st
                             else f"{src or 'no source'}: worked out here from other figures")
        definition = ind_def.get(iid) or src_def.get(src) or "standard"
        sc["definition"] = DEFINITIONS.get(definition, 4)
        notes["definition"] = f"{definition}: {DEFINITION_TEXT.get(definition, '')}"
        out[iid] = {"scores": sc, "notes": notes, "definition": definition, "source_id": src,
                    "grade": grade_of(sc, definition),
                    "type": measure_type(iid, r["name"], r["unit"])}
    return out


def with_choices(scores: dict[str, dict]) -> dict[str, dict]:
    """The scores with the person's grade overrides and stars applied."""
    over, starred = overrides(), set(stars())
    out = {}
    for iid, q in scores.items():
        q = dict(q)
        q["worked_grade"] = q["grade"]
        if iid in over:
            q["grade"], q["overridden"] = over[iid], True
        q["starred"] = iid in starred
        out[iid] = q
    return out


# ----------------------------------------------------------------------------- kept per build
def quality_dir(home: Path) -> Path:
    return Path(home) / "warehouse" / "quality"


def save(home: Path, build_id: str, scores: dict[str, dict]) -> Path:
    d = quality_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{build_id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"build_id": build_id, "made": date.today().isoformat(), "indicators": scores}),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def load(home: Path, build_id: str) -> dict[str, dict] | None:
    try:
        return json.loads((quality_dir(home) / f"{build_id}.json").read_text(encoding="utf-8"))["indicators"]
    except (OSError, ValueError, KeyError):
        return None


def previous(home: Path, build_id: str) -> tuple[str, dict[str, dict]] | None:
    """The newest saved quality before build_id's (build ids sort by time)."""
    d = quality_dir(home)
    if not d.is_dir():
        return None
    older = sorted(p.stem for p in d.glob("*.json") if p.stem < build_id)
    for b in reversed(older):
        q = load(home, b)
        if q is not None:
            return b, q
    return None


ORDER = "ABCD"


def changes(before: dict[str, dict], after: dict[str, dict], starred: set[str] | None = None) -> dict:
    """What changed between two builds' quality: grades lost and gained, figures gone stale,
    new problems found by the checks, and starred indicators whose grade fell."""
    starred = starred or set()
    lost, gained, stale, flagged = [], [], [], []
    for iid, q in after.items():
        p = before.get(iid)
        if not p:
            continue
        g0, g1 = p.get("grade"), q.get("grade")
        if g0 in GRADES and g1 in GRADES and g0 != g1:
            (lost if ORDER.index(g1) > ORDER.index(g0) else gained).append({"indicator_id": iid, "from": g0, "to": g1})
        s0, s1 = p.get("scores", {}), q.get("scores", {})
        if s0.get("up_to_date", 5) > 2 >= s1.get("up_to_date", 5):
            stale.append({"indicator_id": iid, "note": q.get("notes", {}).get("up_to_date", "")})
        if s1.get("health", 5) < s0.get("health", 5):
            flagged.append({"indicator_id": iid, "note": q.get("notes", {}).get("health", "")})
    return {"lost": lost, "gained": gained, "stale": stale, "flagged": flagged,
            "starred_fell": [c for c in lost if c["indicator_id"] in starred]}
