"""Big episodes: the typed-in list (contract episodes.yaml) with, for each, its charts with the
episode shaded, who was hit (the fall in output), figures before, during and after, and how
today compares with the run-up. Also the recessions, booms and crises the app finds in the data
(the events table), and the typed-in episodes as dated events for the bands on charts.

Everything is read from series already loaded: no downloads of its own.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Callable

from worldmodel_contract import catalogue

Q = Callable[[str, list], list[dict]]

KEY = ("NZL", "AUS", "GBR", "USA")
# The before/during/after table, in this order.
TABLE = {"gdp_growth": ("Growth", "%"), "inflation": ("Inflation", "%"), "unemployment": ("Unemployment", "%"),
         "govt_debt_gdp": ("Government debt", "% of GDP")}
# "Does today look like this?": the measures compared and how far apart counts as close.
LIKE = {"inflation": ("Inflation", "%", 3.0), "gdp_growth": ("Growth", "%", 2.0), "unemployment": ("Unemployment", "%", 2.0),
        "govt_debt_gdp": ("Government debt", "% of GDP", 25.0), "private_credit_gdp": ("Private credit", "% of GDP", 25.0),
        "credit_rise": ("Rise in private credit over 3 years", "points of GDP", 8.0),
        "current_account_gdp": ("Current account", "% of GDP", 3.0), "real_interest_rate": ("Real interest rate", "%", 3.0)}
# Short chart titles for the usual measures (the indicators' own names can be long).
CHART_NAMES = {"gdp_growth": ("GDP growth", "%"), "inflation": ("Inflation", "%"), "unemployment": ("Unemployment", "% of workers"),
               "govt_debt_gdp": ("Government debt", "% of GDP"), "govt_debt_gdp_long": ("Government debt", "% of GDP"),
               "private_credit_gdp": ("Credit to the private sector", "% of GDP"), "real_interest_rate": ("Real interest rate", "%"),
               "current_account_gdp": ("Current account", "% of GDP"), "bis_policy_rate_m": ("Central bank rate", "%"),
               "gdp_growth_q": ("GDP growth on the quarter", "%"), "pindex_energy": ("Energy prices (World Bank index)", "2010 = 100"),
               "oecd_cli": ("OECD leading indicator", "100 = trend")}
MIN_PEOPLE = 1_000_000  # who was hit: countries of a million people or more
FOUND_KINDS = ("recession", "boom", "crisis", "inflation", "debt")
RUN_UP = 3  # years before the start that make the run-up, and after the end that make "after"


def year_of(s: str) -> int:
    return int(str(s)[:4])


def years(e: dict) -> tuple[int, int]:
    return year_of(e["start"]), year_of(e["end"])


def frac(s: str, end: bool = False) -> float:
    """A date (YYYY, YYYY-MM or YYYY-MM-DD) as a fractional year; an end runs to the end of its period."""
    s = str(s)
    y = int(s[:4])
    if len(s) == 4:
        return y + (1.0 if end else 0.0)
    m = int(s[5:7])
    if len(s) == 7:
        return y + (m if end else m - 1) / 12
    d = int(s[8:10])
    return y + (m - 1) / 12 + (d - (0 if end else 1)) / 365.25


def _names() -> dict[str, str]:
    return {e.entity_id: e.short_name or e.name for e in catalogue.entities().values()}


def by_id(eid: str) -> dict | None:
    return next((e for e in catalogue.episodes()["episodes"] if e["id"] == eid), None)


# ----------------------------------------------------------------------------- reading series
def annual(q: Q, entities: list[str] | None, indicators: list[str], lo: int, hi: int) -> dict[tuple[str, str], dict[int, float]]:
    """Yearly values from each indicator's first-ranked source that has them. entities None: every
    country (no groups)."""
    if entities is not None and not entities or not indicators:
        return {}
    who = "s.entity_id IN (SELECT unnest(?))" if entities is not None else "NOT s.is_aggregate"
    found = q(f"""SELECT s.entity_id AS e, s.indicator_id AS i, year(s.period_start) AS y, s.value AS v FROM series s
                 LEFT JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
                 WHERE {who} AND s.indicator_id IN (SELECT unnest(?)) AND s.freq = 'A'
                   AND s.variant = 'central' AND s.breakdown = '' AND year(s.period_start) BETWEEN ? AND ?
                 QUALIFY row_number() OVER (PARTITION BY s.entity_id, s.indicator_id, s.period_start
                                            ORDER BY coalesce(r.rank, 99), s.source_id) = 1""",
              [*([entities] if entities is not None else []), indicators, lo, hi])
    out: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for r in found:
        if r["v"] is not None:
            out[(r["e"], r["i"])][r["y"]] = r["v"]
    return out


def sub_annual(q: Q, entities: list[str], indicator: str, lo: int, hi: int) -> dict[str, list[tuple[float, float]]]:
    """Monthly or quarterly values as (fractional year, value), averaged across sources."""
    found = q("""SELECT entity_id AS e, period_start AS d, freq AS f, avg(value) AS v FROM series
                 WHERE entity_id IN (SELECT unnest(?)) AND indicator_id = ? AND freq IN ('M', 'Q') AND variant = 'central'
                   AND breakdown = '' AND year(period_start) BETWEEN ? AND ? GROUP BY 1, 2, 3 ORDER BY 2""",
              [entities, indicator, lo, hi])
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in found:
        d = r["d"]
        step = 1 / 12 if r["f"] == "M" else 0.25
        out[r["e"]].append((round(d.year + (d.month - 1) / 12 + step / 2, 3), r["v"]))
    return out


def long_annual(q: Q, entities: list[str], series_id: str, lo: int, hi: int) -> dict[str, dict[int, float]]:
    """Long-run figures (Maddison and others) from the long_series table, when it is there."""
    try:
        found = q("""SELECT entity_id AS e, year AS y, value AS v FROM long_series WHERE entity_id IN (SELECT unnest(?))
                     AND series_id = ? AND year BETWEEN ? AND ?""", [entities, series_id, lo, hi])
    except Exception:  # noqa: BLE001 - no long-run table loaded yet
        return {}
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for r in found:
        out[r["e"]][r["y"]] = r["v"]
    return out


def indicator_meta(q: Q, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    try:
        return {r["indicator_id"]: r for r in q("SELECT indicator_id, name, unit, decimals FROM indicators "
                                                 "WHERE indicator_id IN (SELECT unnest(?))", [ids])}
    except Exception:  # noqa: BLE001
        return {}


# ----------------------------------------------------------------------------- the sums
def avg(d: dict[int, float], lo: int, hi: int) -> float | None:
    vals = [v for y, v in d.items() if lo <= y <= hi]
    return sum(vals) / len(vals) if vals else None


def output_fall(growth: dict[int, float], lo: int, hi: int) -> float | None:
    """The deepest fall in output from its level before the window, in % (negative), from yearly
    growth; 0 when output never fell below the starting level. None without figures."""
    level, peak, worst, seen = 100.0, 100.0, 0.0, False
    for y in range(lo, hi + 1):
        g = growth.get(y)
        if g is None:
            continue
        seen = True
        level *= 1 + g / 100
        peak = max(peak, level)
        worst = min(worst, 100 * (level / peak - 1))
    return round(worst, 1) if seen else None


def level_fall(levels: dict[int, float], lo: int, hi: int) -> float | None:
    """The same from levels (GDP per person): the deepest fall from the highest level before it."""
    ys = [y for y in sorted(levels) if lo - 1 <= y <= hi]
    if len(ys) < 2:
        return None
    peak, worst = levels[ys[0]], 0.0
    for y in ys[1:]:
        peak = max(peak, levels[y])
        worst = min(worst, 100 * (levels[y] / peak - 1))
    return round(worst, 1)


def profile(data: dict[tuple[str, str], dict[int, float]], entities: list[str], lo: int, hi: int) -> dict[str, float]:
    """The run-up (or today's) figures: each measure averaged over the years and the countries."""
    out: dict[str, float] = {}
    for ind in LIKE:
        vals = []
        for ent in entities:
            if ind == "credit_rise":
                c = data.get((ent, "private_credit_gdp"), {})
                a, b = c.get(lo - 1) if lo - 1 in c else c.get(lo), c.get(hi)
                if a is not None and b is not None:
                    vals.append(b - a)
            else:
                v = avg(data.get((ent, ind), {}), lo, hi)
                if v is not None:
                    vals.append(v)
        if vals:
            out[ind] = sum(vals) / len(vals)
    return out


def distance(a: dict[str, float], b: dict[str, float]) -> tuple[float | None, int]:
    """Root mean square of the differences in "close" units, over the measures both have."""
    common = [k for k in LIKE if k in a and k in b]
    if len(common) < 3:
        return None, len(common)
    return math.sqrt(sum(((a[k] - b[k]) / LIKE[k][2]) ** 2 for k in common) / len(common)), len(common)


# ----------------------------------------------------------------------------- the list
def listing(q: Q, this_year: int | None = None) -> dict:
    """Every typed-in episode with how far output fell in its worst-hit country (where known)."""
    cat = catalogue.episodes()
    eps = cat["episodes"]
    ents = sorted({c for e in eps for c in e["countries"] if c != "world"})
    growth = annual(q, ents, ["gdp_growth"], 1945, this_year or date.today().year)
    long_gdp = long_annual(q, ents, "gdp_per_capita", 1900, 1960)
    names = _names()
    out = []
    for e in eps:
        y0, y1 = years(e)
        falls = []
        for c in e["countries"]:
            g = growth.get((c, "gdp_growth"))
            f = output_fall(g, y0, y1 + 1) if g and y0 >= 1961 else level_fall(long_gdp.get(c, {}), y0, y1)
            if f is not None:
                falls.append((f, c))
        worst = min(falls) if falls else None
        out.append({**{k: e[k] for k in ("id", "title", "kind", "nz", "start", "end", "countries", "summary")},
                    "kind_name": cat["kinds"].get(e["kind"], e["kind"]), "years": [y0, y1],
                    "country_names": [names.get(c, c) for c in e["countries"]],
                    "worst": {"entity": worst[1], "name": names.get(worst[1], worst[1]), "fall": worst[0]} if worst and worst[0] < 0 else None})
    out.sort(key=lambda r: r["start"], reverse=True)
    return {"kinds": cat["kinds"], "episodes": out}


# ----------------------------------------------------------------------------- one episode
def page(q: Q, eid: str, this_year: int | None = None) -> dict | None:
    e = by_id(eid)
    if e is None:
        return None
    this_year = this_year or date.today().year
    cat = catalogue.episodes()
    names = _names()
    y0, y1 = years(e)
    lo, hi = y0 - 6, min(y1 + 6, this_year)
    centre = [c for c in e["countries"] if c != "world"]
    shown = list(dict.fromkeys([*centre, *KEY]))
    annual_charts = [c for c in e["charts"] if not c.startswith("long:")]
    want = sorted(set(annual_charts) | set(TABLE) | {"private_credit_gdp"})
    data = annual(q, shown + (["world"] if "world" in e["countries"] else []), want, lo - 1, hi)
    meta = indicator_meta(q, [c for c in annual_charts])

    charts = []
    for c in e["charts"]:
        lines = []
        if c.startswith("long:"):
            sid = c[5:]
            got = long_annual(q, shown, sid, lo, hi)
            for ent in shown:
                pts = sorted(got.get(ent, {}).items())
                if pts:
                    lines.append({"entity": ent, "name": names.get(ent, ent), "points": [[y, round(v, 2)] for y, v in pts]})
            unit = "international $ (2011 prices)" if sid == "gdp_per_capita" else ""
            charts.append({"indicator": c, "name": {"gdp_per_capita": "GDP per person (Maddison)"}.get(sid, sid), "unit": unit,
                           "freq": "A", "lines": lines})
            continue
        m = meta.get(c, {"name": c, "unit": "", "decimals": 1})
        if c in CHART_NAMES:
            m = {**m, "name": CHART_NAMES[c][0], "unit": CHART_NAMES[c][1]}
        if c.startswith("pindex_") or c in ("bis_policy_rate_m", "gdp_growth_q", "oecd_cli"):
            ents = ["world"] if c.startswith("pindex_") else shown
            got = sub_annual(q, ents, c, lo, hi)
            for ent in ents:
                if got.get(ent):
                    lines.append({"entity": ent, "name": names.get(ent, ent), "points": [[x, round(v, 2)] for x, v in got[ent]]})
            freq = "M"
        else:
            ents = shown + (["world"] if "world" in e["countries"] else [])
            for ent in ents:
                pts = sorted((y, v) for y, v in data.get((ent, c), {}).items() if lo <= y <= hi)
                if pts:
                    lines.append({"entity": ent, "name": names.get(ent, ent), "points": [[y, round(v, 2)] for y, v in pts]})
            freq = "A"
        charts.append({"indicator": c, "name": m["name"], "unit": m.get("unit") or "", "freq": freq, "lines": lines})

    # Who was hit: every country's deepest fall in output over the episode (and the year after).
    hit: list[dict] = []
    if y0 >= 1961:
        allg = annual(q, None, ["gdp_growth"], y0, y1 + 1)
        for (ent, _), g in allg.items():
            f = output_fall(g, y0, y1 + 1)
            if f is not None:
                hit.append({"entity_id": ent, "name": names.get(ent, ent), "value": f})
        hit_how = (f"The deepest fall in GDP below its {y0 - 1} level during {y0}-{y1 + 1}, from yearly growth "
                   "(0 means output never fell below it). Countries of a million people or more.")
    else:
        lg = long_annual(q, [x for x in names], "gdp_per_capita", y0 - 1, y1)
        for ent, lv in lg.items():
            f = level_fall(lv, y0, y1)
            if f is not None:
                hit.append({"entity_id": ent, "name": names.get(ent, ent), "value": f})
        hit_how = f"The deepest fall in GDP per person (Maddison) from its highest level, {y0 - 1}-{y1}."
    big = {r["e"] for r in q("""SELECT entity_id AS e FROM series WHERE indicator_id = 'pop_total' AND freq = 'A'
                                 AND variant = 'central' AND value >= ? GROUP BY 1""", [MIN_PEOPLE])}
    if big:
        hit = [h for h in hit if h["entity_id"] in big]
    hit.sort(key=lambda r: r["value"])

    # Before, during and after.
    table = []
    for ent in shown:
        row = {"entity": ent, "name": names.get(ent, ent), "centre": ent in centre, "values": {}}
        for ind in TABLE:
            d = data.get((ent, ind), {})
            row["values"][ind] = {k: (round(v, 1) if v is not None else None) for k, v in
                                  (("before", avg(d, y0 - RUN_UP, y0 - 1)), ("during", avg(d, y0, y1)),
                                   ("after", avg(d, y1 + 1, y1 + RUN_UP)))}
        if any(v is not None for x in row["values"].values() for v in x.values()):
            table.append(row)

    return {"episode": {**e, "kind_name": cat["kinds"].get(e["kind"], e["kind"]), "years": [y0, y1],
                        "from": round(frac(e["start"]), 3), "to": round(frac(e["end"], end=True), 3),
                        "country_names": [names.get(c, c) for c in e["countries"]],
                        "timeline": [{**t, "at": round(frac(t["date"]), 3)} for t in e.get("timeline", [])]},
            "charts": charts, "hit": hit, "hit_how": hit_how,
            "table": table, "table_measures": [{"id": k, "name": n, "unit": u} for k, (n, u) in TABLE.items()],
            "table_how": f"Averages: before is {y0 - RUN_UP}-{y0 - 1}, during {y0}-{y1}, after {y1 + 1}-{y1 + RUN_UP}.",
            **today_like(q, e, this_year)}


def today_like(q: Q, e: dict, this_year: int) -> dict:
    """The run-up to this episode (the three years before it, averaged over its countries) against
    the last three years in each key country, and the other episodes whose run-up was most like it."""
    eps = catalogue.episodes()["episodes"]
    ents = sorted({c for x in eps for c in x["countries"] if c != "world"} | set(KEY))
    inds = [i for i in LIKE if i != "credit_rise"]
    data = annual(q, ents, inds, 1955, this_year)
    names = _names()
    y0, _ = years(e)
    centre = [c for c in e["countries"] if c != "world"]
    run_up = profile(data, centre, y0 - RUN_UP, y0 - 1)
    now = {}
    for ent in KEY:
        last = max((max(d) for (c, i), d in data.items() if c == ent and i == "gdp_growth" and d), default=None)
        if last is None:
            continue
        p = profile(data, [ent], last - RUN_UP + 1, last)
        dist, n = distance(run_up, p)
        close = [k for k in LIKE if k in run_up and k in p and abs(run_up[k] - p[k]) <= LIKE[k][2]]
        now[ent] = {"name": names.get(ent, ent), "years": [last - RUN_UP + 1, last], "values": {k: round(v, 1) for k, v in p.items()},
                    "close": close, "compared": n,
                    "likeness": None if dist is None else round(100 * math.exp(-dist * dist / 2))}
    similar = []
    for x in eps:
        if x["id"] == e["id"]:
            continue
        xy0, _ = years(x)
        if xy0 - RUN_UP < 1960:
            continue
        other = profile(data, [c for c in x["countries"] if c != "world"], xy0 - RUN_UP, xy0 - 1)
        dist, n = distance(run_up, other)
        if dist is not None:
            similar.append({"id": x["id"], "title": x["title"], "years": list(years(x)),
                            "likeness": round(100 * math.exp(-dist * dist / 2)), "compared": n})
    similar.sort(key=lambda r: -r["likeness"])
    return {"like": {"run_up_years": [y0 - RUN_UP, y0 - 1], "run_up": {k: round(v, 1) for k, v in run_up.items()},
                     "measures": [{"id": k, "name": n, "unit": u, "close_within": c} for k, (n, u, c) in LIKE.items()],
                     "today": now, "similar": similar[:4],
                     "how": ("Likeness is 100 when every measure matches and falls as they differ: each measure's gap is "
                             "counted in its own \"close\" step (for example 3 points of inflation, 25 points of debt). "
                             "A pattern to think about, not a forecast.")}}


# ----------------------------------------------------------------------------- found in the data
def found(q: Q, entity: str | None = None, kinds: list[str] | None = None, limit: int = 600) -> dict:
    """Recessions, booms, inflation spikes, debt surges and crises the app works out from the data,
    and the years when many countries went into recession or crisis together."""
    ks = [k for k in (kinds or FOUND_KINDS) if k in FOUND_KINDS]
    where, params = ["kind IN (SELECT unnest(?))"], [ks]
    if entity:
        where.append("entity_id = ?")
        params.append(entity)
    try:
        got = q(f"""SELECT e.event_id, e.entity_id, e.source_id, e.kind, e.subkind, e.title, e.start_date, e.end_date,
                           e.size, e.size_unit FROM events e WHERE {' AND '.join(where)}
                    ORDER BY e.start_date DESC LIMIT ?""", [*params, limit])
        waves = q("""SELECT year(start_date) AS y, kind, count(DISTINCT entity_id) AS n, list(DISTINCT entity_id) AS ents
                     FROM events WHERE kind IN ('recession', 'crisis') AND entity_id IN (SELECT entity_id FROM entities
                     WHERE type = 'country') GROUP BY 1, 2 HAVING count(DISTINCT entity_id) >= 8 ORDER BY 1""")
    except Exception:  # noqa: BLE001 - no events table yet
        return {"events": [], "waves": [], "note": "No events loaded yet (run .\\refresh.bat)."}
    names = _names()
    for r in got:
        r["start_date"] = r["start_date"].isoformat() if r["start_date"] else None
        r["end_date"] = r["end_date"].isoformat() if r["end_date"] else None
        r["name"] = names.get(r["entity_id"], r["entity_id"])
    eps = catalogue.episodes()["episodes"]
    wave_rows = []
    for w in waves:
        ep = next((x for x in eps if years(x)[0] - 1 <= w["y"] <= years(x)[1] + 1 and x["kind"] in ("financial", "energy", "disaster", "policy")), None)
        wave_rows.append({"year": w["y"], "kind": w["kind"], "n": w["n"], "countries": sorted(w["ents"])[:60],
                          "episode": {"id": ep["id"], "title": ep["title"]} if ep else None})
    return {"events": got, "waves": wave_rows}


# ----------------------------------------------------------------------------- as events for charts
def as_events(entities: list[str] | None = None) -> list[dict]:
    """Each episode as a dated event per country it centres on (the World too for world-wide ones),
    so charts can band it and the band can link to its page."""
    out = []
    for e in catalogue.episodes()["episodes"]:
        prec = "day" if len(e["start"]) == 10 else "month" if len(e["start"]) == 7 else "year"
        start = e["start"] + ("-01-01" if len(e["start"]) == 4 else "-01" if len(e["start"]) == 7 else "")
        end = _end_date(e["end"])
        for c in e["countries"]:
            if entities and c not in entities:
                continue
            out.append({"event_id": f"episode:{e['id']}:{c}", "entity_id": c, "source_id": "episodes", "kind": "episode",
                        "subkind": e["kind"], "title": e["title"], "start_date": start, "end_date": end, "precision": prec,
                        "size": None, "size_unit": None, "deaths": None, "affected": None, "damage_usd": None, "place": None,
                        "url": f"/episodes/{e['id']}", "detail": e["summary"], "color": None})
    return out


def _end_date(s: str) -> str:
    if len(s) == 4:
        return f"{s}-12-31"
    if len(s) == 7:
        y, m = int(s[:4]), int(s[5:7])
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        return (nxt.fromordinal(nxt.toordinal() - 1)).isoformat()
    return s
