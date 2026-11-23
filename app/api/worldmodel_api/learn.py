"""The Learn page: a quiz made from the warehouse's own figures, "draw your guess" charts and the
guided tours, plus the read-only Data console (off by default, from this PC only).

Quiz questions use each indicator's best-ranked source that has figures, actual (not projected)
yearly values, and countries of at least a million people. Every answer carries the real figures,
so a wrong answer still teaches something. Guesses and quiz scores are kept in the user folder
(learn.json), never in the warehouse.
"""

from __future__ import annotations

import math
import random
import re
import threading
from collections import defaultdict
from typing import Callable

from worldmodel_contract import catalogue

from worldmodel_api import userdata

Rows = Callable[[str, list | None], list[dict]]
KEY = ["NZL", "AUS", "GBR", "USA"]
MIN_PEOPLE = 1_000_000
FAMILIAR = 40          # "familiar countries": the key four plus the most populous
KEEP = 500             # guesses and quiz rounds kept


# ----------------------------------------------------------------------------- figures
def best_sources(rows: Rows, indicators: list[str]) -> dict[str, str]:
    """For each indicator, its best-ranked source that has yearly figures in the warehouse."""
    if not indicators:
        return {}
    marks = ", ".join("?" * len(indicators))
    got = rows(f"""SELECT s.indicator_id AS i, s.source_id AS s, min(coalesce(x.rank, 99)) AS r
                   FROM (SELECT DISTINCT indicator_id, source_id FROM series
                         WHERE indicator_id IN ({marks}) AND freq = 'A' AND variant = 'central' AND breakdown = '') s
                   LEFT JOIN indicator_sources x ON x.indicator_id = s.indicator_id AND x.source_id = s.source_id
                   GROUP BY 1, 2 ORDER BY 1, 3, 2""", indicators)
    out: dict[str, str] = {}
    for r in got:
        out.setdefault(r["i"], r["s"])
    return out


def pool(rows: Rows, familiar: bool) -> dict[str, str]:
    """Countries questions are asked about, with their short names."""
    got = rows("""SELECT e.entity_id AS e, coalesce(e.short_name, e.name) AS n, max(s.value) AS p
                  FROM entities e JOIN series s ON s.entity_id = e.entity_id
                  WHERE e.type = 'country' AND s.indicator_id = 'pop_total' AND s.variant = 'central'
                    AND s.breakdown = '' AND s.status = 'E'
                  GROUP BY 1, 2 HAVING max(s.value) >= ? ORDER BY 3 DESC""", [MIN_PEOPLE])
    if familiar:
        keep = set(KEY) | {r["e"] for r in got[:FAMILIAR]}
        got = [r for r in got if r["e"] in keep]
    return {r["e"]: r["n"] for r in got}


def figures(rows: Rows, indicators: list[str], countries: list[str], since: int = 1960) -> dict[str, dict[str, dict[int, float]]]:
    """indicator -> country -> year -> value, actual yearly figures from each indicator's best source."""
    src = best_sources(rows, indicators)
    out: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    if not src or not countries:
        return out
    pairs = " OR ".join("(indicator_id = ? AND source_id = ?)" for _ in src)
    params: list = [x for kv in src.items() for x in kv]
    cmarks = ", ".join("?" * len(countries))
    for r in rows(f"""SELECT indicator_id AS i, entity_id AS e, year(period_start) AS y, value AS v FROM series
                      WHERE ({pairs}) AND entity_id IN ({cmarks}) AND freq = 'A' AND variant = 'central'
                        AND breakdown = '' AND status = 'E' AND value IS NOT NULL AND year(period_start) >= ?""",
                  params + countries + [since]):
        out[r["i"]][r["e"]][int(r["y"])] = float(r["v"])
    return out


def meta(rows: Rows, indicators: list[str]) -> dict[str, dict]:
    if not indicators:
        return {}
    marks = ", ".join("?" * len(indicators))
    return {r["indicator_id"]: r for r in rows(
        f"SELECT indicator_id, name, unit, decimals FROM indicators WHERE indicator_id IN ({marks})", indicators)}


# ----------------------------------------------------------------------------- quiz
def _apart(a: float, b: float, by: float = 0.15) -> bool:
    """Far enough apart that the question has a fair answer (15% of the larger, by default)."""
    big = max(abs(a), abs(b))
    return big > 0 and abs(a - b) >= by * big


MOST = {"more": "the most", "higher": "the highest", "larger": "the largest", "longer": "the longest", "older": "the oldest",
        "bigger": "the biggest", "faster": "the fastest", "lower": "the lowest", "fewer": "the fewest"}


def most(phrase: str) -> str:
    """'higher inflation' -> 'the highest inflation', for questions about four countries."""
    phrase = re.sub(r"^(a|an) ", "", phrase)
    first, _, rest = phrase.partition(" ")
    return f"{MOST[first]} {rest}" if first in MOST else f"the {phrase}"


def _higher_of(rng: random.Random, ind: dict, by_c: dict[str, dict[int, float]], names: dict[str, str], k: int) -> dict | None:
    years = defaultdict(list)
    for c, ys in by_c.items():
        for y in ys:
            years[y].append(c)
    usable = sorted((y for y, cs in years.items() if len(cs) >= max(k, 8)), reverse=True)[:6]
    if not usable:
        return None
    year = rng.choice(usable[:3])
    cands = sorted(c for c in years[year] if c in names)  # sorted, so a seed always gives the same questions
    for _ in range(30):
        pick = rng.sample(cands, k)
        vals = [by_c[c][year] for c in pick]
        if all(_apart(a, b) for i, a in enumerate(vals) for b in vals[i + 1:]):
            best = max(range(k), key=lambda i: vals[i])
            return {"kind": "higher" if k == 2 else "top", "year": year,
                    "question": f"Which had {ind['higher']} in {year}?" if k == 2 else f"Which of these had {most(ind['higher'])} in {year}?",
                    "choices": [{"id": c, "label": names[c], "value": v} for c, v in zip(pick, vals)],
                    "answer": pick[best]}
    return None


def _rise_fall(rng: random.Random, ind: dict, by_c: dict[str, dict[int, float]], names: dict[str, str]) -> dict | None:
    cs = sorted(c for c in by_c if c in names and len(by_c[c]) >= 12)
    rng.shuffle(cs)
    for c in cs[:30]:
        ys = sorted(by_c[c])
        y1 = ys[-1]
        y0 = rng.choice([y for y in ys if y1 - 25 <= y <= y1 - 10] or [ys[0]])
        a, b = by_c[c][y0], by_c[c][y1]
        if _apart(a, b, 0.08):
            name = ind["name"][0].lower() + ind["name"][1:]
            return {"kind": "risefall", "year": y1, "from_year": y0, "country": c,
                    "question": f"Between {y0} and {y1}, did {names[c]}'s {name} go up or down?",
                    "choices": [{"id": "up", "label": "Up", "value": b}, {"id": "down", "label": "Down", "value": a}],
                    "answer": "up" if b > a else "down", "values": [[y0, a], [y1, b]]}
    return None


def topics() -> list[dict]:
    return catalogue.learn().get("quiz", [])


def quiz(rows: Rows, topic: str | None = None, n: int = 10, seed: int | None = None, familiar: bool = True) -> dict:
    """n questions from a topic (or all topics mixed): which of two is higher, which of four is highest,
    and did a figure go up or down. Each question carries its unit, source and the real figures."""
    chosen = [t for t in topics() if topic in (None, "", "all", t["id"])]
    if not chosen:
        raise KeyError(topic)
    inds = {i["id"]: i for t in chosen for i in t["indicators"]}
    names = pool(rows, familiar)
    data = figures(rows, list(inds), list(names))
    info = meta(rows, list(data))
    src = best_sources(rows, list(data))
    usable = [i for i in inds if i in data and i in info and len(data[i]) >= 8]
    seed = seed if seed is not None else random.randrange(1_000_000)
    rng = random.Random(seed)
    out: list[dict] = []
    tries = 0
    while usable and len(out) < n and tries < n * 6:
        tries += 1
        iid = rng.choice(usable)
        ind = {**inds[iid], "name": info[iid]["name"]}
        kind = rng.choices(["higher", "top", "risefall"], [5, 3, 2])[0]
        q = (_rise_fall(rng, ind, data[iid], names) if kind == "risefall"
             else _higher_of(rng, ind, data[iid], names, 2 if kind == "higher" else 4))
        if not q or any(o["question"] == q["question"] and o.get("answer") == q["answer"] for o in out):
            continue
        if q["kind"] != "risefall":
            rng.shuffle(q["choices"])
        q.update(indicator_id=iid, indicator=info[iid]["name"], unit=info[iid]["unit"] or "",
                 decimals=int(info[iid]["decimals"] if info[iid]["decimals"] is not None else 1), source_id=src.get(iid))
        out.append(q)
    return {"seed": seed, "topic": topic or "all", "questions": out,
            "topics": [{"id": t["id"], "name": t["name"]} for t in topics()]}


# ----------------------------------------------------------------------------- draw your guess
def guess_chart(rows: Rows, entity: str, indicator: str, hide_from: int) -> dict:
    """The line to draw on: actual yearly figures from the best source, split at hide_from. The y-axis range
    covers the hidden part too (padded), so the axis does not give the answer away by its size alone."""
    src = best_sources(rows, [indicator]).get(indicator)
    data = figures(rows, [indicator], [entity], since=1900).get(indicator, {}).get(entity, {})
    if not src or len(data) < 6:
        raise LookupError(f"Not enough yearly figures for {indicator} in {entity}.")
    years = sorted(data)
    hide_from = min(max(hide_from, years[0] + 3), years[-1] - 2)
    vals = list(data.values())
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.35 or abs(hi) * 0.2 or 1
    info = meta(rows, [indicator]).get(indicator, {})
    name = rows("SELECT coalesce(short_name, name) AS n FROM entities WHERE entity_id = ?", [entity])
    return {"entity_id": entity, "name": name[0]["n"] if name else entity, "indicator_id": indicator,
            "indicator": info.get("name", indicator), "unit": info.get("unit") or "", "decimals": info.get("decimals"),
            "source_id": src, "hide_from": hide_from, "first": years[0], "last": years[-1],
            "shown": [[y, data[y]] for y in years if y <= hide_from],
            "y_min": max(lo - pad, 0) if lo >= 0 else lo - pad, "y_max": hi + pad}


def score_guess(actual: list[list[float]], drawn: list[list[float]], y_span: float) -> dict:
    """How close a drawn line came: the average gap to the real line over the hidden years, as a share of the
    chart's height, turned into 0-100 (100 is spot on; a gap of half the chart's height or more scores 0)."""
    real = {int(y): v for y, v in actual}
    mine = sorted((float(y), float(v)) for y, v in drawn)
    if not mine or not real:
        return {"score": 0, "years": 0, "gap": None}

    def at(y: float) -> float | None:  # the drawn line read at a year, joining the dots
        if y < mine[0][0] - 0.5 or y > mine[-1][0] + 0.5:
            return None
        for (x0, v0), (x1, v1) in zip(mine, mine[1:]):
            if x0 <= y <= x1:
                return v0 if x1 == x0 else v0 + (v1 - v0) * (y - x0) / (x1 - x0)
        return mine[0][1] if y < mine[0][0] else mine[-1][1]

    gaps = [abs(g - v) for y, v in real.items() if (g := at(y)) is not None]
    covered = len(gaps) / len(real)
    if not gaps:
        return {"score": 0, "years": 0, "gap": None}
    gap = sum(gaps) / len(gaps)
    share = gap / (y_span or 1)
    score = max(0, round(100 * (1 - share / 0.5) * min(1, covered / 0.8)))
    return {"score": score, "years": len(gaps), "gap": gap}


def presets() -> list[dict]:
    return catalogue.learn().get("guess", [])


# ----------------------------------------------------------------------------- your record
_lock = threading.Lock()


def record() -> dict:
    got = userdata._read_json("learn.json", {})
    return {"guesses": got.get("guesses", []), "quiz": got.get("quiz", [])}


def remember(kind: str, entry: dict) -> dict:
    with _lock:
        got = record()
        got[kind] = (got[kind] + [{**entry, "at": userdata.now()}])[-KEEP:]
        userdata._write_json("learn.json", got)
        return got


# ----------------------------------------------------------------------------- data console
ALLOWED_START = re.compile(r"^\s*(select|with|from)\b", re.I)
# Anything that writes, changes settings, or reads files or the network. The warehouse is opened
# read-only already; this keeps the console to questions about what is in it.
BLOCKED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|copy|attach|detach|install|load|pragma|set|reset|export|import|"
    r"call|checkpoint|vacuum|use|read_\w+|glob|parquet_\w+|sniff_csv|query_table|getenv|http\w*)\b"
    r"|\b(from|join)\s*'|\bs3://|\bhttps?://", re.I)
MAX_ROWS = 5000
SECONDS = 20


def check_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise ValueError("Type a question in SQL first.")
    # strings first, so a word inside quotes ('Insert coin') does not count; comments are refused outright
    bare = re.sub(r"'(?:[^']|'')*'", "''", s)
    if "--" in bare or "/*" in bare:
        raise ValueError("Leave comments out of the query.")
    if ";" in bare:
        raise ValueError("One query at a time, please (no ';' in the middle).")
    if not ALLOWED_START.match(bare):
        raise ValueError("Only questions are allowed here: start with SELECT, WITH or FROM.")
    hit = BLOCKED.search(bare)
    if hit and hit.group(0).lower().startswith(("from", "join", "s3", "http")):
        raise ValueError("Reading files or web addresses is not allowed in the console: it reads the warehouse only.")
    if hit:
        raise ValueError(f"'{hit.group(0).strip()}' is not allowed in the console: it is read-only and reads the warehouse only.")
    return s


def run_sql(cursor, sql: str, limit: int = 1000) -> dict:
    """Runs one read-only query with a row limit and a time limit, returning columns and rows."""
    s = check_sql(sql)
    limit = max(1, min(int(limit), MAX_ROWS))
    timer = threading.Timer(SECONDS, cursor.interrupt)
    timer.start()
    try:
        rel = cursor.execute(f"SELECT * FROM ({s}) AS q LIMIT {limit + 1}")
        cols = [d[0] for d in rel.description]
        got = rel.fetchall()
    except Exception as exc:  # noqa: BLE001 (any DuckDB error goes back to the page as text)
        msg = str(exc).split("\n")[0]
        if "nterrupt" in msg:
            msg = f"Stopped after {SECONDS} seconds. Narrow the question (a WHERE on entity_id or indicator_id helps)."
        raise ValueError(msg) from None
    finally:
        timer.cancel()

    def plain(v):
        if v is None or isinstance(v, (int, str, bool)):
            return v
        if isinstance(v, float):
            return None if math.isnan(v) or math.isinf(v) else v
        return str(v)

    return {"columns": cols, "rows": [[plain(v) for v in r] for r in got[:limit]], "more": len(got) > limit, "limit": limit}


def tables(cursor) -> list[dict]:
    rel = cursor.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
                            WHERE table_schema = 'main' ORDER BY table_name, ordinal_position""")
    out: dict[str, list] = {}
    for t, c, d in rel.fetchall():
        out.setdefault(t, []).append({"name": c, "type": d})
    return [{"table": t, "columns": cs} for t, cs in out.items()]


def saved_queries() -> list[dict]:
    return userdata._read_json("console_queries.json", [])


def save_query(name: str, sql: str) -> list[dict]:
    name = " ".join(name.split())[:80]
    if not name:
        raise ValueError("Give the query a name.")
    with _lock:
        got = [q for q in saved_queries() if q["name"] != name] + [{"name": name, "sql": sql[:20000], "at": userdata.now()}]
        userdata._write_json("console_queries.json", got[-200:])
        return got


def drop_query(name: str) -> list[dict]:
    with _lock:
        got = [q for q in saved_queries() if q["name"] != name]
        userdata._write_json("console_queries.json", got)
        return got
