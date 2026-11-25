"""Flu, COVID, RSV, measles and other infections over time, from the warehouse's weekly and yearly
series (the measures are listed in the contract's disease.py).

Seasons
    Each measure's weeks are grouped into seasons. Where the measure peaks mid-year in a country
    (southern winters: New Zealand, Australia) a season is the calendar year; elsewhere it runs from
    the start of July to the end of June, so a northern winter is one season ("2025/26"). Which one
    is worked out from the data: the week of the year with the highest average.
Normal range
    For each week of the season, the lowest and highest value and the average over the baseline
    seasons (2015-2019, before COVID); with fewer than three of those, every earlier season except
    2020 and 2021.
Now
    The latest week of a measure for every country that reported in the last eight weeks, against
    the average of the same week (and the weeks either side) in the normal range.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

from worldmodel_contract import disease as D

Q = Callable[[str, list], list[dict]]
STRAINS = (("flu_a_h1n1_positive", "A(H1N1)"), ("flu_a_h3_positive", "A(H3N2)"), ("flu_b_positive", "B"))


def _in(n: int) -> str:
    return ", ".join("?" * n)


def weekly(q: Q, indicator: str, entities: list[str] | None = None, since: date | None = None) -> dict[str, list[tuple[date, float]]]:
    """Weekly points by entity, from the best-ranked source each entity has."""
    where, params = "", [indicator]
    if entities:
        where += f" AND s.entity_id IN ({_in(len(entities))})"
        params += entities
    if since:
        where += " AND s.period_start >= ?"
        params.append(since)
    got = q(f"""SELECT s.entity_id AS e, s.period_start AS d, s.value AS v, s.source_id AS src, coalesce(r.rank, 99) AS rk
                FROM series s LEFT JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
                WHERE s.indicator_id = ? AND s.freq = 'D' AND s.variant = 'central' AND s.breakdown = ''{where}""", params)
    best: dict[str, int] = {}
    for r in got:
        best[r["e"]] = min(best.get(r["e"], 99), r["rk"])
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for r in got:
        if r["rk"] == best[r["e"]] and r["v"] is not None:
            out[r["e"]][r["d"]] = r["v"]
    return {e: sorted(p.items()) for e, p in out.items()}


def sources_of(q: Q, indicator: str, entity: str) -> list[str]:
    got = q("""SELECT DISTINCT coalesce(o.short_name, s.source_id) AS name FROM series s LEFT JOIN sources o ON o.source_id = s.source_id
               WHERE s.indicator_id = ? AND s.entity_id = ? AND s.freq = 'D'""", [indicator, entity])
    return [r["name"] for r in got]


# ------------------------------------------------------------------------------------------- seasons
def split_week(points: list[tuple[date, float]]) -> int:
    """1 when the measure peaks mid-year (weeks 14 to 40, a southern winter), else 27 (seasons run July to June)."""
    by_week: dict[int, list[float]] = defaultdict(list)
    for d, v in points:
        if d.year not in D.SKIP_YEARS:
            by_week[d.isocalendar()[1]].append(v)
    if not by_week:
        return 27
    peak = max(by_week, key=lambda w: sum(by_week[w]) / len(by_week[w]))
    return 1 if 14 <= peak <= 40 else 27


def season_start(season: int, split: int) -> date:
    return date.fromisocalendar(season, split, 1)


def by_season(points: list[tuple[date, float]], split: int) -> dict[int, list[tuple[int, date, float]]]:
    """Season -> [(week of the season from 1, date, value)]."""
    out: dict[int, list[tuple[int, date, float]]] = defaultdict(list)
    for d, v in points:
        y, w, _ = d.isocalendar()
        s = D.season_of(y, w, split)
        out[s].append(((d - season_start(s, split)).days // 7 + 1, d, v))
    return dict(out)


def normal_range(seasons: dict[int, list[tuple[int, date, float]]], before: int) -> tuple[dict[int, tuple[float, float, float]], str]:
    """Week of the season -> (lowest, highest, average), and which seasons it is from."""
    lo, hi = D.BASELINE
    use = [s for s in seasons if lo <= s <= hi]
    label = f"{lo}-{hi}"
    if len(use) < 3:
        use = [s for s in seasons if s < before and s not in D.SKIP_YEARS]
        label = f"{min(use)}-{max(use)}, without 2020 and 2021" if use else ""
    if len(use) < 3:
        return {}, ""
    vals: dict[int, list[float]] = defaultdict(list)
    for s in use:
        for x, _d, v in seasons[s]:
            vals[x].append(v)
    return {x: (min(v), max(v), sum(v) / len(v)) for x, v in vals.items() if len(v) >= 2}, label


def seasons_view(q: Q, entity: str, measure: str) -> dict:
    m = D.MEASURE.get(measure) or {"id": measure, "label": measure, "unit": "", "kind": "rate"}
    pts = weekly(q, measure, [entity]).get(entity, [])
    if not pts:
        return {"entity": entity, "measure": m, "seasons": [], "band": [], "note": "No weekly figures for this country yet."}
    split = split_week(pts)
    seasons = by_season(pts, split)
    latest = max(seasons)
    band, band_label = normal_range(seasons, latest)
    peaks = {s: max(p, key=lambda x: x[2]) for s, p in seasons.items() if len(p) >= 8}
    head = None
    cur = seasons[latest]
    if cur:
        pk = max(cur, key=lambda x: x[2])
        last = cur[-1]
        full = [s for s in peaks if s != latest]
        rank = 1 + sum(1 for s in full if peaks[s][2] > pk[2])
        usual = band.get(last[0], (None, None, None))[2]
        head = {"season": D.season_label(latest, split), "peak": pk[2], "peak_week": pk[1].isoformat(), "peak_x": pk[0],
                "rank": rank, "of": len(full) + 1, "since": D.season_label(min(peaks), split) if peaks else None,
                "latest": last[2], "latest_week": last[1].isoformat(), "usual": usual,
                "ratio": round(last[2] / usual, 2) if usual else None}
    return {
        "entity": entity, "measure": m, "split_week": split,
        "season_note": "Calendar years (the season peaks mid-year here)" if split == 1 else "July to June (the season peaks in winter here)",
        "seasons": [{"season": s, "label": D.season_label(s, split), "points": [[x, d.isoformat(), v] for x, d, v in p],
                     "peak": peaks[s][2] if s in peaks else None} for s, p in sorted(seasons.items())],
        "band": [[x, *band[x]] for x in sorted(band)], "band_label": band_label, "headline": head,
        "sources": sources_of(q, measure, entity),
    }


def heat_view(q: Q, entity: str, measure: str) -> dict:
    """Every season as a row of weeks, with the main flu strain each week where FluNet says."""
    view = seasons_view(q, entity, measure)
    strains: dict[date, str] = {}
    if measure.startswith("flu_"):
        parts = {ind: dict(weekly(q, ind, [entity]).get(entity, [])) for ind, _ in STRAINS}
        days = set().union(*[set(p) for p in parts.values()]) if parts else set()
        for d in days:
            got = [(parts[ind].get(d) or 0, name) for ind, name in STRAINS]
            tot = sum(v for v, _ in got)
            if tot >= 5:
                v, name = max(got)
                strains[d] = f"{name} {round(100 * v / tot)}%"
    for s in view.get("seasons", []):
        s["strain"] = {p[0]: strains[date.fromisoformat(p[1])] for p in s["points"] if date.fromisoformat(p[1]) in strains}
    return view


# --------------------------------------------------------------------------------------------- now
def usual_for_week(points: list[tuple[date, float]], when: date) -> float | None:
    """The average of the same ISO week and the weeks either side, in the baseline years (or, with
    fewer than three of those, every earlier year but 2020 and 2021)."""
    wk = when.isocalendar()[1]
    near = {(wk + k - 1) % 52 + 1 for k in (-1, 0, 1)}
    lo, hi = D.BASELINE
    pick = [v for d, v in points if lo <= d.year <= hi and d.isocalendar()[1] in near]
    years = {d.year for d, _ in points if lo <= d.year <= hi}
    if len(years) < 3:
        pick = [v for d, v in points if d.year < when.year and d.year not in D.SKIP_YEARS and d.isocalendar()[1] in near]
        years = {d.year for d, _ in points if d.year < when.year and d.year not in D.SKIP_YEARS}
    if len(years) < 3 or not pick:
        return None
    return sum(pick) / len(pick)


def level(ratio: float | None) -> str:
    if ratio is None:
        return "no_usual"
    return "low" if ratio < 0.67 else "usual" if ratio <= 1.5 else "high" if ratio <= 3 else "very_high"


LEVEL_WORDS = {"low": "Below usual", "usual": "Usual for the week", "high": "Above usual", "very_high": "Well above usual",
               "no_usual": "No usual level yet"}


def trend(points: list[tuple[date, float]]) -> str | None:
    """Rising or falling over the last three weeks (each week at least 5% up or down), else steady."""
    last = [v for _d, v in points[-4:]]
    if len(last) < 4:
        return None
    ups = sum(1 for a, b in zip(last, last[1:]) if b > a * 1.05)
    downs = sum(1 for a, b in zip(last, last[1:]) if b < a * 0.95)
    return "rising" if ups == 3 else "falling" if downs == 3 else "steady"


def now_view(q: Q, measure: str, entities: list[str] | None = None) -> dict:
    m = D.MEASURE.get(measure) or {"id": measure, "label": measure, "unit": "", "kind": "rate"}
    all_pts = weekly(q, measure, entities)
    if not all_pts:
        return {"measure": m, "week": None, "rows": []}
    newest = max(p[-1][0] for p in all_pts.values() if p)
    rows = []
    for e, pts in all_pts.items():
        if not pts or pts[-1][0] < newest - timedelta(weeks=8):
            continue
        d, v = pts[-1]
        usual = usual_for_week(pts, d)
        ratio = round(v / usual, 2) if usual else None
        rows.append({"entity": e, "week": d.isoformat(), "value": v, "usual": usual, "ratio": ratio, "level": level(ratio),
                     "trend": trend(pts)})
    rows.sort(key=lambda r: (-(r["ratio"] if r["ratio"] is not None else -1), -r["value"]))
    return {"measure": m, "week": newest.isoformat(), "rows": rows, "levels": LEVEL_WORDS}


def compare_view(q: Q, entities: list[str], measure: str, years: int) -> dict:
    since = date.today() - timedelta(days=365 * years + 7)
    pts = weekly(q, measure, entities, since)
    return {"measure": D.MEASURE.get(measure), "since": since.isoformat(),
            "series": [{"entity": e, "points": [[d.isoformat(), v] for d, v in pts.get(e, [])]} for e in entities]}


# ------------------------------------------------------------------------------------------ country
def card_view(q: Q, entity: str) -> dict:
    """The country card's tiles: each weekly measure the country has had in the last four months, and
    the yearly measles count."""
    since = date.today() - timedelta(days=3 * 365 + 30)
    got = q(f"""SELECT DISTINCT indicator_id AS i FROM series WHERE entity_id = ? AND freq = 'D'
                AND indicator_id IN ({_in(len(D.MEASURES))}) AND period_start >= ?""",
            [entity, *[m["id"] for m in D.MEASURES], date.today() - timedelta(days=120)])
    have = {r["i"] for r in got}
    tiles = []
    for m in D.MEASURES:
        if m["id"] not in have:
            continue
        pts = weekly(q, m["id"], [entity], date(D.BASELINE[0], 1, 1)).get(entity, [])
        if not pts:
            continue
        d, v = pts[-1]
        usual = usual_for_week(pts, d)
        ratio = round(v / usual, 2) if usual else None
        tiles.append({"measure": m, "week": d.isoformat(), "value": v, "usual": usual, "ratio": ratio, "level": level(ratio),
                      "trend": trend(pts), "spark": [[p[0].isoformat(), p[1]] for p in pts if p[0] >= since][-26:]})
    tiles.sort(key=lambda t: (not t["measure"].get("main"), [d["key"] for d in D.DISEASES].index(t["measure"]["disease"])))
    yearly = []
    for y in ("measles_cases", "pertussis_cases"):
        r = q("SELECT year(period_start) AS y, value AS v FROM series WHERE entity_id = ? AND indicator_id = ? AND freq = 'A' "
              "AND variant = 'central' ORDER BY 1", [entity, y])
        if r:
            last = r[-1]
            since2000 = [x for x in r if x["y"] >= 2000]
            rank = 1 + sum(1 for x in since2000 if x["v"] > last["v"])
            yearly.append({"indicator": y, "label": next(x["label"] for x in D.YEARLY if x["id"] == y), "year": last["y"],
                           "value": last["v"], "rank": rank, "of": len(since2000), "since": since2000[0]["y"] if since2000 else None})
    return {"entity": entity, "tiles": tiles, "yearly": yearly, "levels": LEVEL_WORDS}


# -------------------------------------------------------------------------------------- long view
def long_view(q: Q, entities: list[str], indicator: str) -> dict:
    meta = next((y for y in D.YEARLY if y["id"] == indicator), {"id": indicator, "label": indicator, "per_million": False})
    if meta.get("from_weekly"):
        got = q(f"""SELECT entity_id AS e, year(period_start) AS y, sum(value) AS v FROM series
                    WHERE indicator_id = ? AND freq = 'D' AND variant = 'central' AND entity_id IN ({_in(len(entities))})
                    GROUP BY 1, 2""", [indicator, *entities])
    else:
        got = q(f"""SELECT entity_id AS e, year(period_start) AS y, avg(value) AS v FROM series
                    WHERE indicator_id = ? AND freq = 'A' AND variant = 'central' AND breakdown = '' AND entity_id IN ({_in(len(entities))})
                    GROUP BY 1, 2""", [indicator, *entities])
    pop: dict[tuple[str, int], float] = {}
    if meta.get("per_million"):
        for r in q(f"""SELECT entity_id AS e, year(period_start) AS y, avg(value) AS v FROM series WHERE indicator_id = 'pop_total'
                       AND freq = 'A' AND variant = 'central' AND breakdown = '' AND status = 'E' AND entity_id IN ({_in(len(entities))})
                       GROUP BY 1, 2""", entities):
            pop[(r["e"], r["y"])] = r["v"]
    series = []
    for e in entities:
        pts = []
        for r in sorted((r for r in got if r["e"] == e), key=lambda r: r["y"]):
            v = r["v"]
            if meta.get("per_million"):
                p = pop.get((e, r["y"])) or pop.get((e, r["y"] - 1))
                if not p:
                    continue
                v = v / p * 1e6
            pts.append([r["y"], v, r["v"]])
        series.append({"entity": e, "points": pts})
    return {"indicator": meta, "unit": "per million people" if meta.get("per_million") else "", "series": series,
            "pandemics": D.PANDEMICS, "choices": D.YEARLY}


# ------------------------------------------------------------------------- NZ notifiable diseases
NOTIFIABLE_NAMES = {"vtec_stec_infection": "VTEC/STEC infection", "hepatitis_nos": "Hepatitis NOS", "q_fever": "Q fever",
                    "haemophilus_influenzae_type_b": "Haemophilus influenzae type b (Hib)",
                    "invasive_group_a_streptococcal_infection": "Invasive group A streptococcal infection",
                    "meningoencephalitis_primary_amoebic": "Meningoencephalitis (primary amoebic)",
                    "rabies_and_other_lyssaviruses": "Rabies and other lyssaviruses"}


def notifiable(q: Q) -> dict:
    """New Zealand's notifiable diseases by year (PHF Science): each disease's cases and rate per 100,000, with the
    latest year against the average of the five years before it (leaving out 2020 and 2021)."""
    got = q("""SELECT indicator_id AS i, breakdown AS b, year(period_start) AS y, value AS v FROM series
               WHERE entity_id = 'NZL' AND indicator_id IN ('nz_notifiable_cases', 'nz_notifiable_rate') AND freq = 'A'
               AND variant = 'central' ORDER BY 3""", [])
    by: dict[str, dict] = {}
    for r in got:
        key = r["b"].split("=", 1)[-1]
        d = by.setdefault(key, {"key": key, "name": NOTIFIABLE_NAMES.get(key, key.replace("_", " ").capitalize()), "cases": [], "rate": []})
        d["cases" if r["i"] == "nz_notifiable_cases" else "rate"].append([r["y"], r["v"]])
    out = []
    for d in by.values():
        if not d["cases"]:
            continue
        year, last = d["cases"][-1]
        before = [v for y, v in d["cases"] if year - 6 < y < year and y not in D.SKIP_YEARS]
        usual = sum(before) / len(before) if before else None
        rate = dict((y, v) for y, v in d["rate"]).get(year)
        out.append({**d, "year": year, "latest": last, "latest_rate": rate, "usual": usual,
                    "ratio": round(last / usual, 2) if usual else None})
    out.sort(key=lambda d: -d["latest"])
    return {"diseases": out, "year": max((d["year"] for d in out), default=None)}


# ------------------------------------------------------------------------------- causes of death
CAUSE_PREFIX = "cause_death_rate_"


def causes(q: Q, entities: list[str]) -> dict:
    """Age-standardised death rates per 100,000 by broad cause (WHO Mortality Database) for each country."""
    got = q(f"""SELECT s.entity_id AS e, s.indicator_id AS i, year(s.period_start) AS y, avg(s.value) AS v FROM series s
                WHERE s.indicator_id LIKE '{CAUSE_PREFIX}%' AND s.freq = 'A' AND s.variant = 'central' AND s.breakdown = ''
                AND s.entity_id IN ({_in(len(entities))}) GROUP BY 1, 2, 3 ORDER BY 3""", list(entities))
    names = {r["i"]: r["n"] for r in q(f"SELECT indicator_id AS i, name AS n FROM indicators WHERE indicator_id LIKE '{CAUSE_PREFIX}%'", [])}
    pts: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in got:
        pts[r["e"]][r["i"]].append([r["y"], r["v"]])
    ids = sorted(names, key=lambda i: -max((p[-1][1] for e in pts.values() if (p := e.get(i))), default=0))
    return {"causes": [{"id": i, "name": names[i]} for i in ids],
            "series": [{"entity": e, "causes": {i: pts[e][i] for i in ids if pts[e].get(i)}} for e in entities],
            "source": "WHO Mortality Database (through Our World in Data), age-standardised deaths per 100,000 people"}


# --------------------------------------------------------------------------------------- outbreaks
def outbreaks(q: Q, entities: list[str] | None, limit: int) -> list[dict]:
    where, params = "", []
    if entities:
        where = f" AND e.entity_id IN ({_in(len(entities))})"
        params = list(entities)
    return q(f"""SELECT e.entity_id AS entity, coalesce(n.short_name, n.name) AS name, e.subkind AS disease, e.title, e.start_date AS day,
                        e.place, e.url, e.detail FROM events e LEFT JOIN entities n ON n.entity_id = e.entity_id
                 WHERE e.source_id = 'who_don'{where} ORDER BY e.start_date DESC, e.entity_id LIMIT {int(limit)}""", params)


def measures(q: Q) -> dict:
    """Each weekly measure with how many places have it, its latest week and the key countries that have it."""
    ids = [m["id"] for m in D.MEASURES]
    got = q(f"""SELECT indicator_id AS i, count(DISTINCT entity_id) AS n, max(period_start) AS last,
                       list(DISTINCT entity_id) FILTER (WHERE entity_id IN ({_in(len(D.KEY))})) AS key
                FROM series WHERE freq = 'D' AND indicator_id IN ({_in(len(ids))}) GROUP BY 1""", [*D.KEY, *ids])
    by = {r["i"]: r for r in got}
    out = []
    for m in D.MEASURES:
        r = by.get(m["id"])
        out.append({**m, "places": r["n"] if r else 0, "latest": r["last"].isoformat() if r and r["last"] else None,
                    "key": sorted(r["key"] or []) if r else []})
    return {"diseases": D.DISEASES, "measures": out, "yearly": D.YEARLY, "key": list(D.KEY)}
