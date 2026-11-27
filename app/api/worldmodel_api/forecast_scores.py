"""How good are the app's forecasts? Back-tests and a running record, for every kind of forecast it makes.

Four kinds of forecast are scored:

    disease    the flu and RSV season forecasts (disease_forecast.py), 1, 2, 4 and 8 weeks ahead
    stat       the statistical forecast of yearly figures (the Forecast button on charts,
               contract forecast.py), 1, 2, 3 and 5 years ahead
    nowcast    this quarter's GDP growth before the official figure (outlook.py)
    recession  the odds of a recession starting within twelve months (outlook.py)

Back-test ("rolling origin")
    The forecast is made again at each past point using only the figures there were then, and set
    against what came. Flu and RSV: every week of the last few years (Settings > Forecasts, 3 by
    default). Yearly figures: each of the last ten years. Nowcasts: each of the last 20 quarters.
    Recession odds: every third month of the last 15 years, the model refitted each time on the
    recessions known by then.

Baselines (the forecast has to beat these to be worth anything)
    disease    "same as last week" and "usual for this week of the year" (the 2015-2019 average)
    stat       "last value carries on"
    nowcast    "last quarter's growth again"
    recession  the share of months a recession followed (the model's own base rate)

Scores
    typical miss   mean absolute miss: in the figure's own units for one country; pooled across
                   countries as a share of the usual peak (disease) or of the figure (levels such
                   as population), else in its units (rates such as growth)
    skill          how much smaller the typical miss is than the best baseline's (0% = no better,
                   negative = worse)
    in range       how often what came fell inside the forecast's 80% range (80% is right; less
                   means the ranges are too narrow)
    Brier score    for the recession odds: (chance - outcome)^2, 0 perfect; skill against the base rate

Running record
    After each new build (refresh) the forecasts of the moment are saved to
    <data folder>/forecasts/log.sqlite, the first one made from each set of figures, and each is
    scored once its figure comes in. Settings > Forecasts can stop the saving.

Everything is worked out in one background thread after each new build, kept on disk per build
(<data folder>/forecasts/scores-<build>.json), and read by the Forecasts page's Scores tab.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from worldmodel_contract import disease as D
from worldmodel_contract import forecast as statforecast
from worldmodel_contract import local

from worldmodel_api import disease_forecast as DF
from worldmodel_api import outlook
from worldmodel_api.disease import split_week, usual_for_week, weekly

log = logging.getLogger(__name__)
Q = Callable[..., list[dict]]

HORIZONS = {"disease": (1, 2, 4, 8), "stat": (1, 2, 3, 5), "nowcast": (0,), "recession": (12,)}
HORIZON_UNIT = {"disease": "weeks", "stat": "years", "nowcast": "quarters", "recession": "months"}
STAT_DEFAULT = ("gdp_growth", "inflation", "unemployment", "pop_total", "life_expectancy", "tfr", "govt_debt_gdp",
                "gdp_per_capita_usd")
STAT_ORIGINS = 10        # yearly figures: forecasts made from each of the last ten years
RECESSION_YEARS = 15     # recession odds: origins over the last fifteen years ...
RECESSION_STEP = 3       # ... every third month
KEY = D.KEY
PARTS_DEFAULT = ("disease", "nowcast", "recession", *(f"stat:{i}" for i in STAT_DEFAULT), "live")
BASE_NAMES = {"last": "Same as last time", "usual": "Usual for the time of year", "naive": "Last value carries on",
              "prev": "Last quarter's growth again", "rate": "Base rate"}


# ============================================================================= scoring
def summarise(pairs: list[dict], bases: tuple[str, ...]) -> dict:
    """Scores of a set of pairs {f, lo, hi, a, scale, base: {name: value}}: n, mae (own units),
    rel (mean miss / scale), bias, cover (share inside lo-hi), base mae and rel per baseline, skill."""
    n = len(pairs)
    if not n:
        return {"n": 0}
    rel = sum(abs(p["f"] - p["a"]) / p["scale"] for p in pairs) / n
    out = {"n": n, "mae": sum(abs(p["f"] - p["a"]) for p in pairs) / n, "rel": rel,
           "bias": sum(p["f"] - p["a"] for p in pairs) / n, "base": {}}
    ranged = [p for p in pairs if p.get("lo") is not None and p.get("hi") is not None]
    out["cover"] = sum(1 for p in ranged if p["lo"] <= p["a"] <= p["hi"]) / len(ranged) if ranged else None
    best = None
    for b in bases:
        got = [p for p in pairs if p["base"].get(b) is not None]
        if len(got) < n:  # a baseline missing for some pairs is scored on the pairs it has, but never "best"
            if got:
                out["base"][b] = {"mae": sum(abs(p["base"][b] - p["a"]) for p in got) / len(got),
                                  "rel": sum(abs(p["base"][b] - p["a"]) / p["scale"] for p in got) / len(got), "n": len(got)}
            continue
        r = sum(abs(p["base"][b] - p["a"]) / p["scale"] for p in pairs) / n
        out["base"][b] = {"mae": sum(abs(p["base"][b] - p["a"]) for p in pairs) / n, "rel": r, "n": n}
        if best is None or r < out["base"][best]["rel"]:
            best = b
    out["best_base"] = best
    out["skill"] = (1 - rel / out["base"][best]["rel"]) if best and out["base"][best]["rel"] > 0 else None
    return out


def summarise_odds(pairs: list[dict]) -> dict:
    """Scores of chances {p, a (0/1), base}: Brier score, the base rate's, skill, events, mean chance."""
    n = len(pairs)
    if not n:
        return {"n": 0}
    brier = sum((p["p"] - p["a"]) ** 2 for p in pairs) / n
    base = sum((p["base"] - p["a"]) ** 2 for p in pairs) / n
    hits = [p for p in pairs if p["a"] == 1]
    return {"n": n, "brier": brier, "base_brier": base, "skill": (1 - brier / base) if base > 0 else None,
            "events": len(hits), "mean_p": sum(p["p"] for p in pairs) / n, "rate": len(hits) / n,
            "mean_p_events": sum(p["p"] for p in hits) / len(hits) if hits else None,
            "mean_p_none": sum(p["p"] for p in pairs if p["a"] == 0) / (n - len(hits)) if n > len(hits) else None}


def _r(v, k: int = 4):
    return None if v is None else round(v, k)


def _tidy(s: dict) -> dict:
    """Round a summary for the page."""
    out = {k: (_r(v) if isinstance(v, float) else v) for k, v in s.items() if k != "base"}
    if "base" in s:
        out["base"] = {b: {"mae": _r(v["mae"]), "rel": _r(v["rel"]), "n": v["n"]} for b, v in s["base"].items()}
    return out


def table(pairs: list[dict], horizons: tuple[int, ...], bases: tuple[str, ...], names: dict[str, str],
          odds: bool = False) -> dict:
    """Pooled scores by horizon (all countries, and the key four), and each country's by horizon."""
    score = (lambda ps: _tidy(summarise_odds(ps))) if odds else (lambda ps: _tidy(summarise(ps, bases)))
    by_h: dict[int, list] = defaultdict(list)
    by_eh: dict[tuple[str, int], list] = defaultdict(list)
    for p in pairs:
        by_h[p["h"]].append(p)
        by_eh[(p["e"], p["h"])].append(p)
    pooled = []
    for h in horizons:
        ps = by_h.get(h, [])
        if ps:
            pooled.append({"h": h, "group": "all", **score(ps)})
            key = [p for p in ps if p["e"] in KEY]
            if key:
                pooled.append({"h": h, "group": "key", **score(key)})
    ents = sorted({e for e, _ in by_eh}, key=lambda e: (e not in KEY, KEY.index(e) if e in KEY else 0, names.get(e, e)))
    countries = [{"e": e, "name": names.get(e, e), "h": h, **score(by_eh[(e, h)])} for e in ents for h in horizons if (e, h) in by_eh]
    when = sorted(p["t"] for p in pairs if p.get("t"))
    return {"pooled": pooled, "countries": countries, "from": when[0] if when else None, "to": when[-1] if when else None,
            "n": len(pairs)}


# ============================================================================= disease
def _signal(everyone, south: bool, when: date, cache: dict) -> float | None:
    key = (south, when.year, when.month)
    if key not in cache:
        cache[key] = DF.hemisphere_signal(everyone, south, date(when.year, when.month, 1))["ratio"]
    return cache[key]


def disease_pairs(pts: list[tuple[date, float]], everyone: dict, origins_from: date, e: str, cache: dict,
                  horizons: tuple[int, ...] = HORIZONS["disease"]) -> list[dict]:
    """The season forecast made after each week from origins_from on, from the weeks before, against what came."""
    if len(pts) < 52 * 4:
        return []
    dates = [d for d, _ in pts]
    actual = dict(pts)
    out = []
    start = bisect_right(dates, origins_from - timedelta(days=1))
    for i in range(start, len(pts)):
        d0 = dates[i]
        if all(d0 + timedelta(weeks=h) not in actual for h in horizons):
            continue
        before = pts[: i + 1]
        south = split_week(before) == 1
        f = DF.forecast(before, _signal(everyone, not south, d0, cache), d0)
        if not f:
            continue
        fc = {p[1]: p for p in f["points"]}
        scale = f["normal_peak"] or 1.0
        for h in horizons:
            t = d0 + timedelta(weeks=h)
            p = fc.get(t.isoformat())
            if t not in actual or not p:
                continue
            out.append({"e": e, "h": h, "o": d0.isoformat(), "t": t.isoformat(), "f": p[2], "lo": p[3], "hi": p[4],
                        "a": actual[t], "scale": scale, "base": {"last": before[-1][1], "usual": usual_for_week(before, t)}})
    return out


def disease_backtest(q: Q, years: int, names: dict[str, str], measures: list[str] | None = None) -> dict:
    out = {}
    for m in measures or list(DF.SIGNAL):
        own = weekly(q, m)
        if not own:
            continue
        everyone = own if DF.SIGNAL[m] == m else weekly(q, DF.SIGNAL[m])
        last = max(p[-1][0] for p in own.values() if p)
        since = last - timedelta(days=round(365.25 * years))
        cache: dict = {}
        pairs = []
        for e, pts in own.items():
            if pts and pts[-1][0] >= since:
                pairs += disease_pairs(pts, everyone, since, e, cache)
        if pairs:
            meta = D.MEASURE.get(m, {"label": m, "unit": ""})
            out[m] = {"label": meta["label"], "unit": meta.get("unit", ""), "years": years,
                      **table(pairs, HORIZONS["disease"], ("last", "usual"), names)}
    return out


# ============================================================================= yearly figures (the Forecast button)
def _yearly(q: Q, indicator: str) -> tuple[dict, dict[str, list[tuple[int, float]]]]:
    meta = q("SELECT name, unit, decimals, bound_min, bound_max FROM indicators WHERE indicator_id = ?", [indicator])
    if not meta:
        return {}, {}
    got = q("""SELECT s.entity_id AS e, year(s.period_start) AS y, s.value AS v FROM series s JOIN entities n USING (entity_id)
               WHERE s.indicator_id = ? AND s.freq = 'A' AND s.status = 'E' AND s.variant = 'central' AND s.breakdown = ''
                 AND n.type = 'country' AND s.value IS NOT NULL
                 AND s.source_id = (SELECT source_id FROM indicator_sources WHERE indicator_id = ? ORDER BY rank LIMIT 1)
               ORDER BY 1, 2""", [indicator, indicator])
    by: dict[str, list] = defaultdict(list)
    for r in got:
        by[r["e"]].append((int(r["y"]), float(r["v"])))
    return meta[0], dict(by)


def _bounds(meta: dict) -> tuple[float, float]:
    return (meta["bound_min"] if meta.get("bound_min") is not None else -1e18,
            meta["bound_max"] if meta.get("bound_max") is not None else 1e18)


def stat_pairs(series: list[tuple[int, float]], meta: dict, e: str, origins: int = STAT_ORIGINS,
               horizons: tuple[int, ...] = HORIZONS["stat"]) -> list[dict]:
    """The yearly forecast made from each of the last `origins` years, from the years before, against what came."""
    ys, vs = statforecast.recent_run([y for y, _ in series], [v for _, v in series])
    if len(vs) < statforecast.MIN_POINTS + 1:
        return []
    actual = dict(zip(ys, vs))
    log_scale = statforecast.use_log(vs, meta.get("unit"))
    out = []
    for cut in range(max(statforecast.MIN_POINTS, len(ys) - origins), len(ys)):
        o = ys[cut - 1]
        try:
            f = statforecast.forecast(ys[:cut], vs[:cut], max(horizons), meta.get("unit"), _bounds(meta))
        except ValueError:
            continue
        pts = {p["year"]: p for p in f["points"]}
        for h in horizons:
            if o + h in actual and o + h in pts:
                a, p = actual[o + h], pts[o + h]
                out.append({"e": e, "h": h, "o": str(o), "t": str(o + h), "f": p["mean"], "lo": p["lo80"], "hi": p["hi80"],
                            "lo95": p["lo95"], "hi95": p["hi95"], "a": a, "scale": abs(a) if log_scale and a else 1.0,
                            "base": {"naive": vs[cut - 1]}})
    return out


def stat_backtest(q: Q, indicator: str, names: dict[str, str]) -> dict | None:
    meta, by = _yearly(q, indicator)
    if not by:
        return None
    pairs = []
    for e, s in by.items():
        pairs += stat_pairs(s, meta, e)
    if not pairs:
        return None
    t = table(pairs, HORIZONS["stat"], ("naive",), names)
    for row in t["pooled"] + t["countries"]:  # the 95% range too
        sel = [p for p in pairs if p["h"] == row["h"] and (row.get("e") == p["e"] if "e" in row
                                                            else row["group"] == "all" or p["e"] in KEY)]
        row["cover95"] = _r(sum(1 for p in sel if p["lo95"] <= p["a"] <= p["hi95"]) / len(sel)) if sel else None
    return {"indicator": indicator, "label": meta["name"], "unit": meta["unit"], "decimals": meta["decimals"],
            "rel_is_share": statforecast.use_log([1.0], meta["unit"]), "origins": STAT_ORIGINS, **t}


# ============================================================================= nowcasts and recession odds
def nowcast_pairs(track: list[dict], e: str) -> list[dict]:
    """The nowcast track (each quarter estimated from those before) as pairs; the 80% range from the misses before each."""
    out = []
    for i, t in enumerate(track):
        prior = [x["actual"] - x["estimate"] for x in track[:i]]
        rmse = math.sqrt(sum(v * v for v in prior) / len(prior)) if len(prior) >= 6 else None
        out.append({"e": e, "h": 0, "o": t["quarter"], "t": t["quarter"], "f": t["estimate"], "a": t["actual"], "scale": 1.0,
                    "lo": t["estimate"] - 1.2816 * rmse if rmse else None, "hi": t["estimate"] + 1.2816 * rmse if rmse else None,
                    "base": {"prev": t.get("before")}})
    return out


def nowcast_backtest(q: Q, version: str, names: dict[str, str]) -> dict | None:
    F = outlook.fit(q, version)
    pairs = []
    for e in F["gdp"]:
        n = outlook.nowcast(q, e, version, remember=False)
        pairs += nowcast_pairs(n.get("track") or [], e)
    if not pairs:
        return None
    return {"label": "GDP growth this quarter (nowcast)", "unit": "%", **table(pairs, HORIZONS["nowcast"], ("prev",), names)}


def recession_pairs(F: dict, years: int = RECESSION_YEARS, step: int = RECESSION_STEP) -> list[dict]:
    """The pooled recession model refitted at each origin on what was known then, and its odds for every country."""
    panel, gdp = F["panel"], F["gdp"]
    if not panel:
        return []
    last = max((max(r) for r in panel.values() if r), default=None)
    if last is None:
        return []
    full = {e: outlook.recessions(g) for e, g in gdp.items()}
    out = []
    for o in range(last - years * 12, last - 11, step):
        known = {}
        for e, g in gdp.items():
            gk = {m: v for m, v in g.items() if m + 5 <= o}
            if gk:
                known[e] = (outlook.recessions(gk), max(gk))
        models = {}
        for name, feats in outlook.MODELS:
            X, y = [], []
            for e, rows in panel.items():
                if e not in known:
                    continue
                recs, lq = known[e]
                for m, f in rows.items():
                    if m > o or any(f[k] is None for k in feats):
                        continue
                    lab = outlook._label(m, recs, lq)
                    if lab is not None:
                        X.append([f[k] for k in feats])
                        y.append(lab)
            if len(y) < 60 or sum(y) < 5:
                continue
            Xa = np.array(X, dtype=float)
            mu, sd = Xa.mean(0), Xa.std(0)
            sd[sd == 0] = 1
            w = outlook.logit(np.c_[np.ones(len(Xa)), (Xa - mu) / sd], np.array(y, dtype=float))
            models[name] = {"features": feats, "w": w.tolist(), "mu": mu.tolist(), "sd": sd.tolist(), "base": float(np.mean(y))}
        if not models:
            continue
        for e, rows in panel.items():
            f = rows.get(o)
            name = outlook._pick(models, f) if f else None
            if not name or e not in gdp:
                continue
            a = outlook._label(o, full[e], max(gdp[e]))
            if a is None:
                continue
            p, _ = outlook._prob(models[name], f)
            out.append({"e": e, "h": 12, "o": outlook.md(o).isoformat()[:7], "t": outlook.md(o + 12).isoformat()[:7],
                        "p": p, "a": a, "base": models[name]["base"]})
    return out


def recession_backtest(q: Q, version: str, names: dict[str, str]) -> dict | None:
    pairs = recession_pairs(outlook.fit(q, version))
    if not pairs:
        return None
    return {"label": "Recession starting within 12 months (odds)", "unit": "chance", "years": RECESSION_YEARS,
            **table(pairs, HORIZONS["recession"], (), names, odds=True)}


# ============================================================================= the running record
def _db() -> sqlite3.Connection:
    p = local.home() / "forecasts" / "log.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS made (
        family TEXT, measure TEXT, entity TEXT, origin TEXT, target TEXT, horizon INTEGER,
        value REAL, lo REAL, hi REAL, scale REAL, bases TEXT, made_at TEXT, build TEXT,
        PRIMARY KEY (family, measure, entity, origin, target))""")
    return con


def save(rows: list[dict], build: str, con: sqlite3.Connection | None = None) -> int:
    """Keep forecasts not kept before (the first made from each set of figures). Returns how many were new."""
    if not rows:
        return 0
    own = con is None
    con = con or _db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    before = con.total_changes
    con.executemany("INSERT OR IGNORE INTO made VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(r["family"], r["measure"], r["e"], r["o"], r["t"], r["h"], r["f"], r.get("lo"), r.get("hi"),
                      r.get("scale", 1.0), json.dumps(r.get("base", {})), now, build) for r in rows])
    con.commit()
    n = con.total_changes - before
    if own:
        con.close()
    return n


def kept(con: sqlite3.Connection | None = None) -> list[dict]:
    own = con is None
    con = con or _db()
    cur = con.execute("SELECT family, measure, entity, origin, target, horizon, value, lo, hi, scale, bases, made_at FROM made")
    cols = [c[0] for c in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    if own:
        con.close()
    return out


def disease_now(q: Q, measure: str, today: date) -> list[dict]:
    """Today's flu or RSV forecasts, every country with recent figures, as rows to keep."""
    own = weekly(q, measure)
    everyone = own if DF.SIGNAL[measure] == measure else weekly(q, DF.SIGNAL[measure])
    cache: dict = {}
    out = []
    for e, pts in own.items():
        if len(pts) < 52 * 4 or pts[-1][0] < today - timedelta(days=60):
            continue
        d0 = pts[-1][0]
        f = DF.forecast(pts, _signal(everyone, split_week(pts) != 1, today, cache), today)
        if not f:
            continue
        fc = {p[1]: p for p in f["points"]}
        for h in HORIZONS["disease"]:
            t = d0 + timedelta(weeks=h)
            p = fc.get(t.isoformat())
            if p:
                out.append({"family": "disease", "measure": measure, "e": e, "h": h, "o": d0.isoformat(), "t": t.isoformat(),
                            "f": p[2], "lo": p[3], "hi": p[4], "scale": f["normal_peak"] or 1.0,
                            "base": {"last": pts[-1][1], "usual": usual_for_week(pts, t)}})
    return out


def stat_now(q: Q, indicator: str) -> list[dict]:
    meta, by = _yearly(q, indicator)
    out = []
    for e, s in by.items():
        ys, vs = statforecast.recent_run([y for y, _ in s], [v for _, v in s])
        if len(vs) < statforecast.MIN_POINTS or ys[-1] < date.today().year - 4:
            continue
        try:
            f = statforecast.forecast(ys, vs, max(HORIZONS["stat"]), meta["unit"], _bounds(meta))
        except ValueError:
            continue
        log_scale = statforecast.use_log(vs, meta["unit"])
        for p in f["points"]:
            h = p["year"] - ys[-1]
            if h in HORIZONS["stat"]:
                out.append({"family": "stat", "measure": indicator, "e": e, "h": h, "o": str(ys[-1]), "t": str(p["year"]),
                            "f": p["mean"], "lo": p["lo80"], "hi": p["hi80"], "scale": abs(vs[-1]) if log_scale else 1.0,
                            "base": {"naive": vs[-1]}})
    return out


def nowcast_now(q: Q, version: str) -> list[dict]:
    F = outlook.fit(q, version)
    out = []
    for e in F["gdp"]:
        n = outlook.nowcast(q, e, version, remember=False)
        if n.get("estimate") is None or n.get("official") is not None:
            continue
        out.append({"family": "nowcast", "measure": "gdp_growth_q", "e": e, "h": 0, "o": n["last_quarter"], "t": n["quarter"],
                    "f": n["estimate"], "lo": n.get("low"), "hi": n.get("high"), "scale": 1.0, "base": {"prev": n["last_actual"]}})
    return out


def recession_now(q: Q, version: str) -> list[dict]:
    F = outlook.fit(q, version)
    got = outlook.recession_odds(q, list(F["panel"]), version)
    base = {k: v["base"] for k, v in F["models"].items()}
    out = []
    for c in got["countries"]:
        if c.get("odds") is None or c.get("in_recession"):
            continue
        y, mo = (int(x) for x in c["month"].split("-"))
        t = outlook.md(y * 12 + mo - 1 + 12).isoformat()[:7]
        out.append({"family": "recession", "measure": "recession_12m", "e": c["entity"], "h": 12, "o": c["month"], "t": t,
                    "f": c["odds"] / 100, "scale": 1.0, "base": {"rate": base.get(c["model"])}})
    return out


def score_kept(q: Q, version: str, made: list[dict], names: dict[str, str]) -> dict:
    """Each kept forecast whose figure has come in, scored like the back-tests."""
    fam: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in made:
        fam[r["family"]][r["measure"]].append(r)
    out: dict = {"saved": len(made), "first": min((r["made_at"] for r in made), default=None), "families": {}}
    for family, by_m in fam.items():
        res = {}
        for m, rs in by_m.items():
            actual: dict = {}
            if family == "disease":
                actual = {(e, d.isoformat()): v for e, pts in weekly(q, m, sorted({r["entity"] for r in rs})).items() for d, v in pts}
            elif family == "stat":
                _, by = _yearly(q, m)
                actual = {(e, str(y)): v for e, s in by.items() for y, v in s}
            elif family == "nowcast":
                F = outlook.fit(q, version)
                actual = {(e, outlook.qlabel(k)): v for e, g in F["gdp"].items() for k, v in g.items()}
            elif family == "recession":
                F = outlook.fit(q, version)
                for e, g in F["gdp"].items():
                    recs, lq = F["recs"].get(e, []), max(g)
                    for r in rs:
                        if r["entity"] == e:
                            y, mo = (int(x) for x in r["origin"].split("-"))
                            lab = outlook._label(y * 12 + mo - 1, recs, lq)
                            if lab is not None:
                                actual[(e, r["target"])] = lab
            pairs, waiting = [], 0
            for r in rs:
                a = actual.get((r["entity"], r["target"]))
                if a is None:
                    waiting += 1
                    continue
                base = json.loads(r["bases"] or "{}")
                if family == "recession":
                    pairs.append({"e": r["entity"], "h": r["horizon"], "t": r["target"], "p": r["value"], "a": a,
                                  "base": base.get("rate") if base.get("rate") is not None else 0.1})
                else:
                    pairs.append({"e": r["entity"], "h": r["horizon"], "t": r["target"], "f": r["value"], "lo": r["lo"],
                                  "hi": r["hi"], "a": a, "scale": r["scale"] or 1.0, "base": base})
            bases = {"disease": ("last", "usual"), "stat": ("naive",), "nowcast": ("prev",), "recession": ()}[family]
            res[m] = {"waiting": waiting, "first": min(r["made_at"] for r in rs), **_about(q, family, m),
                      **table(pairs, HORIZONS[family], bases, names, odds=family == "recession")}
        out["families"][family] = res
    return out


def _about(q: Q, family: str, m: str) -> dict:
    """Label and units of a kept forecast's measure, for the page."""
    if family == "disease":
        meta = D.MEASURE.get(m, {"label": m, "unit": ""})
        return {"label": meta["label"], "unit": meta.get("unit", "")}
    if family == "stat":
        got = q("SELECT name, unit, decimals FROM indicators WHERE indicator_id = ?", [m])
        if got:
            return {"label": got[0]["name"], "unit": got[0]["unit"], "decimals": got[0]["decimals"],
                    "rel_is_share": statforecast.use_log([1.0], got[0]["unit"])}
        return {"label": m}
    if family == "nowcast":
        return {"label": "GDP growth this quarter (nowcast)", "unit": "%", "decimals": 2}
    return {"label": "Recession starting within 12 months (odds)", "unit": "chance"}


def live(q: Q, version: str, build: str, names: dict[str, str], keep: bool) -> dict:
    """Save this build's forecasts (unless switched off), then score everything kept."""
    con = _db()
    try:
        added = 0
        if keep:
            today = date.today()
            for m in DF.SIGNAL:
                added += save(disease_now(q, m, today), build, con)
            for ind in STAT_DEFAULT:
                added += save(stat_now(q, ind), build, con)
            added += save(nowcast_now(q, version), build, con)
            added += save(recession_now(q, version), build, con)
        out = score_kept(q, version, kept(con), names)
        out.update(added=added, keeping=keep)
        return out
    finally:
        con.close()


# ============================================================================= the background worker
class Scores:
    """Works the parts out one at a time in a background thread, once per build, and keeps them on disk."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.queue: list[str] = []
        self.done: dict[str, dict] = {}    # part -> result, for self.build
        self.failed: dict[str, str] = {}
        self.working: str | None = None
        self.build: str | None = None
        self.thread: threading.Thread | None = None
        self.q: Q | None = None
        self.version: Callable[[], str] | None = None
        self.build_id: Callable[[], str] | None = None
        self.settings: Callable[[], dict] | None = None

    def _file(self, build: str) -> Path:
        return local.home() / "forecasts" / f"scores-{build}.json"

    def _load(self, build: str) -> None:
        try:
            self.done = json.loads(self._file(build).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.done = {}

    def _store(self) -> None:
        try:
            p = self._file(self.build or "none")
            p.parent.mkdir(parents=True, exist_ok=True)
            for old in p.parent.glob("scores-*.json"):  # only the current build's are kept
                if old != p:
                    old.unlink(missing_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.done), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass

    def configure(self, q: Q, build_id: Callable[[], str], version: Callable[[], str], settings: Callable[[], dict]) -> None:
        self.q, self.build_id, self.version, self.settings = q, build_id, version, settings

    def _sync(self) -> None:
        """A new build: drop the old results, read any kept for it, queue the rest."""
        b = self.build_id()
        if b != self.build:
            self.build = b
            self._load(b)
            self.failed = {}
            self.queue = [p for p in PARTS_DEFAULT if p not in self.done]

    def ask(self, part: str) -> dict:
        """The part's result, or its state while it is worked out (queued first if asked for)."""
        with self.lock:
            self._sync()
            if part in self.done:
                return {"status": "ready", **self.done[part]}
            if part in self.failed:
                return {"status": "failed", "error": self.failed[part]}
            if part != self.working:
                if part in self.queue:
                    self.queue.remove(part)
                self.queue.insert(0, part)
            self._start()
            return {"status": "working", "working_on": self.working, "queued": len(self.queue)}

    def state(self) -> dict:
        with self.lock:
            self._sync()
            return {"build": self.build, "ready": sorted(self.done), "working_on": self.working, "queued": list(self.queue),
                    "failed": dict(self.failed)}

    def _start(self) -> None:
        if self.queue and not (self.thread and self.thread.is_alive()):
            self.thread = threading.Thread(target=self._run, name="forecast-scores", daemon=True)
            self.thread.start()

    def kick(self) -> None:
        """Start on a new build's parts, if any wait (called now and then while the app runs)."""
        with self.lock:
            self._sync()
            self._start()

    def _run(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    self.working = None
                    return
                part = self.working = self.queue.pop(0)
                build = self.build
            t0 = time.monotonic()
            try:
                res = self.work(part)
                res = {"part": part, "seconds": round(time.monotonic() - t0, 1),
                       "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": res}
                with self.lock:
                    if build == self.build:
                        self.done[part] = res
                        self._store()
            except Exception as exc:  # noqa: BLE001 - shown on the page
                log.warning("forecast scores %s failed: %s", part, exc)
                with self.lock:
                    self.failed[part] = f"{type(exc).__name__}: {exc}"

    def work(self, part: str):
        q, version = self.q, self.version()
        names = {r["e"]: r["n"] for r in q("SELECT entity_id AS e, coalesce(short_name, name) AS n FROM entities")}
        s = self.settings() if self.settings else {}
        if part == "disease":
            return disease_backtest(q, int(s.get("forecast_backtest_years", 3)), names)
        if part.startswith("stat:"):
            return stat_backtest(q, part[5:], names)
        if part == "nowcast":
            return nowcast_backtest(q, version, names)
        if part == "recession":
            return recession_backtest(q, version, names)
        if part == "live":
            return live(q, version, self.build or "", names, bool(s.get("forecast_scores_keep", True)))
        raise ValueError(f"no part {part}")


SCORES = Scores()


def start(q: Q, build_id: Callable[[], str], version: Callable[[], str], settings: Callable[[], dict], every: int = 600) -> None:
    """Work the scores out after each new build: now (after a pause for the app to settle) and on a timer."""
    SCORES.configure(q, build_id, version, settings)

    def loop() -> None:
        time.sleep(90)
        while True:
            try:
                SCORES.kick()
            except Exception as exc:  # noqa: BLE001 - no warehouse yet, say
                log.info("forecast scores waiting: %s", exc)
            time.sleep(every)

    threading.Thread(target=loop, name="forecast-scores-timer", daemon=True).start()
