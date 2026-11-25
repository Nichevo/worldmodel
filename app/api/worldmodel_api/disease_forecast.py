"""Forecasts of the flu and RSV season, from a country's own past seasons and from how big the
latest season was in the other hemisphere.

How it works
    Every earlier season of the country (up to ten, leaving out 2020 and 2021) is a possible path
    for the season being forecast. Each is scaled so its peak matches the country's usual peak
    (the median of its past peaks) times a size signal from the other hemisphere: how the latest
    finished season there compared with each country's own usual peak (the median across
    countries), pulled half way back towards "as usual" because the link between hemispheres is
    loose. Once the season has started, each path is also slid up to four weeks earlier or later
    and rescaled to fit the weeks already seen; the more weeks seen, the more the fit counts
    against the hemisphere signal. The forecast is the weighted median of the paths week by week
    (paths that fit the weeks seen better weigh more); the shaded range is their 10th to 90th
    percentile.
Which season
    The season under way; once it is all but over (46 weeks in), the next one.
How good it has been
    The same forecast made before each of the country's last five finished seasons, using only
    what was known then, against the peak that came: the typical miss, and the miss of simply
    expecting the usual peak, so the hemisphere signal can be judged.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median

from worldmodel_contract import disease as D

from worldmodel_api.disease import Q, by_season, season_start, split_week, weekly

# Measure -> the measure the other-hemisphere signal is read from (FluNet covers both hemispheres).
SIGNAL = {"flu_pct_positive": "flu_pct_positive", "flu_admissions_per_100k": "flu_pct_positive", "ili_pct_visits": "flu_pct_positive",
          "ili_rate_per_100k": "flu_pct_positive", "rsv_pct_positive": "rsv_pct_positive", "rsv_admissions_per_100k": "rsv_pct_positive"}
MAX_PAST = 10
MIN_PAST = 3
SHIFTS = range(-4, 5)
SHRINK = 0.5  # how much of the other hemisphere's signal is used (0 none, 1 all)
SEASON_WEEKS = 52
NEXT_AFTER = 46  # weeks into a season after which the next season is forecast

Points = list[tuple[date, float]]


def _curves(points: Points, split: int) -> dict[int, dict[int, float]]:
    return {s: {x: v for x, _d, v in p} for s, p in by_season(points, split).items()}


def _past(curves: dict[int, dict[int, float]], before: int) -> list[int]:
    return [s for s in sorted(curves) if s < before and s not in D.SKIP_YEARS and len(curves[s]) >= 40][-MAX_PAST:]


def _wquant(vals: list[tuple[float, float]], q: float) -> float:
    """Weighted quantile of (value, weight) pairs."""
    vals = sorted(vals)
    tot = sum(w for _v, w in vals) or 1.0
    acc = 0.0
    for v, w in vals:
        acc += w
        if acc >= q * tot:
            return v
    return vals[-1][0]


def season_size(points: Points, cutoff: date) -> dict | None:
    """How big a country's latest finished season (before the cutoff) was against its usual peak."""
    pts = [p for p in points if p[0] < cutoff]
    if len(pts) < 52 * 4:
        return None
    split = split_week(pts)
    curves = _curves(pts, split)
    for s in sorted(curves, reverse=True):
        c = curves[s]
        if s in D.SKIP_YEARS or not c:
            continue
        earlier = _past(curves, s)
        if len(earlier) < MIN_PAST:
            return None
        usual_x = median(max(curves[e], key=curves[e].get) for e in earlier)
        if max(c) < usual_x + 4:  # its peak may still be to come
            continue
        last = season_start(s, split) + timedelta(weeks=max(c))
        if last < cutoff - timedelta(days=430):  # too old to say anything about now
            return None
        normal = median(max(curves[e].values()) for e in earlier[-8:])
        if normal <= 0:
            return None
        return {"season": s, "label": D.season_label(s, split), "peak": max(c.values()), "normal": normal,
                "ratio": max(c.values()) / normal, "south": split == 1}
    return None


def hemisphere_signal(everyone: dict[str, Points], south: bool, cutoff: date, names: dict[str, str] | None = None) -> dict:
    """The median size of the latest finished season among countries in the given hemisphere."""
    rows = []
    for e, pts in everyone.items():
        got = season_size(pts, cutoff)
        if got and got["south"] == south:
            rows.append({"entity": e, "name": (names or {}).get(e, e), "season": got["label"], "ratio": round(got["ratio"], 2)})
    rows.sort(key=lambda r: (r["entity"] not in D.KEY, -r["ratio"]))
    ratio = median(r["ratio"] for r in rows) if len(rows) >= 2 else None
    return {"hemisphere": "southern" if south else "northern", "ratio": ratio, "countries": rows}


def forecast(points: Points, signal_ratio: float | None, today: date, target: int | None = None) -> dict | None:
    """The forecast for one country's season under way (or the next one), or None without enough past seasons."""
    if not points:
        return None
    split = split_week(points)
    curves = _curves(points, split)
    latest = max(curves)
    if target is None:
        cur = curves[latest]
        target = latest + 1 if cur and max(cur) >= NEXT_AFTER else latest
    obs = {x: v for x, v in curves.get(target, {}).items()}
    past = _past(curves, target)
    if len(past) < MIN_PAST:
        return None
    peaks = {s: max(curves[s].values()) for s in past}
    normal = median(peaks[s] for s in past[-8:])
    if normal <= 0:
        return None
    r = 1.0 if signal_ratio is None else min(2.0, max(0.5, 1 + SHRINK * (signal_ratio - 1)))
    t = max(obs) if obs else 0
    started = [x for x, v in obs.items() if v >= 0.3 * normal]
    fit_weight = min(0.85, len(started) / 8) if len(obs) >= 3 and started else 0.0
    paths = []
    for s in past:
        c = curves[s]
        a0 = normal / peaks[s] * r if peaks[s] > 0 else r
        a, k, err = a0, 0, 0.0
        if fit_weight:
            best = None
            for shift in SHIFTS:
                pairs = [(o, c[x - shift]) for x, o in obs.items() if x - shift in c]
                den = sum(cv * cv for _o, cv in pairs)
                if len(pairs) < 3 or den <= 0:
                    continue
                af = sum(o * cv for o, cv in pairs) / den
                e = sum(abs(o - af * cv) for o, cv in pairs) / (sum(o for o, _ in pairs) or 1)
                if best is None or e < best[2]:
                    best = (af, shift, e)
            if best and best[0] > 0:
                a = math.exp(fit_weight * math.log(best[0]) + (1 - fit_weight) * math.log(a0))
                k, err = best[1], best[2]
        path = {x: a * c[x - k] for x in range(1, SEASON_WEEKS + 1) if x - k in c}
        whole = {**path, **obs}
        pk_x = max(whole, key=whole.get)
        paths.append({"season": s, "path": path, "peak": whole[pk_x], "peak_x": pk_x, "w": math.exp(-err / 0.25)})
    out = []
    for x in range(t + 1, SEASON_WEEKS + 1):
        vals = [(p["path"][x], p["w"]) for p in paths if x in p["path"]]
        if len(vals) >= 2:
            d = season_start(target, split) + timedelta(weeks=x - 1)
            out.append([x, d.isoformat(), _wquant(vals, 0.5), _wquant(vals, 0.1), _wquant(vals, 0.9)])
    if not out:
        return None
    pk = [(p["peak"], p["w"]) for p in paths]
    pk_x = round(_wquant([(p["peak_x"], p["w"]) for p in paths], 0.5))
    peak_passed = bool(obs) and max(obs, key=obs.get) < t - 3 and max(obs.values()) >= _wquant(pk, 0.5)
    return {
        "season": target, "label": D.season_label(target, split), "split_week": split, "weeks_seen": len(obs),
        "points": out, "peak": _wquant(pk, 0.5), "peak_lo": _wquant(pk, 0.1), "peak_hi": _wquant(pk, 0.9),
        "peak_week": (season_start(target, split) + timedelta(weeks=pk_x - 1)).isoformat(), "peak_x": pk_x,
        "peak_passed": peak_passed, "normal_peak": normal, "vs_normal": _wquant(pk, 0.5) / normal,
        "signal_used": None if signal_ratio is None else round(r, 2), "fit_weight": round(fit_weight, 2),
        "from_seasons": [D.season_label(s, split) for s in past],
    }


def backtest(points: Points, everyone: dict[str, Points], n: int = 5) -> dict:
    """The forecast made just before each of the last n finished seasons, against what came."""
    split = split_week(points)
    curves = _curves(points, split)
    rows = []
    for s in [s for s in _past(curves, max(curves) + 1) if s not in D.SKIP_YEARS][-n:]:
        start = season_start(s, split)
        before = [p for p in points if p[0] < start]
        sig = hemisphere_signal(everyone, split != 1, start)["ratio"]
        f = forecast(before, sig, start, target=s)
        plain = forecast(before, None, start, target=s)
        if not f or not plain:
            continue
        actual = max(curves[s].values())
        rows.append({"season": D.season_label(s, split), "actual": actual, "forecast": f["peak"], "plain": plain["peak"],
                     "lo": f["peak_lo"], "hi": f["peak_hi"], "signal": sig})
    if not rows:
        return {"rows": []}
    miss = median(abs(r["forecast"] / r["actual"] - 1) for r in rows if r["actual"] > 0)
    plain_miss = median(abs(r["plain"] / r["actual"] - 1) for r in rows if r["actual"] > 0)
    inside = sum(1 for r in rows if r["lo"] <= r["actual"] <= r["hi"])
    return {"rows": rows, "miss": miss, "plain_miss": plain_miss, "inside": inside, "of": len(rows)}


def _names(q: Q, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    got = q(f"SELECT entity_id AS e, coalesce(short_name, name) AS n FROM entities WHERE entity_id IN ({', '.join('?' * len(ids))})", ids)
    return {r["e"]: r["n"] for r in got}


def forecast_view(q: Q, entity: str, measure: str, today: date | None = None) -> dict:
    today = today or date.today()
    m = D.MEASURE.get(measure) or {"id": measure, "label": measure, "unit": "", "kind": "rate"}
    if measure not in SIGNAL:
        return {"entity": entity, "measure": m, "forecast": None, "note": "Forecasts are made for flu and RSV measures only."}
    pts = weekly(q, measure, [entity]).get(entity, [])
    everyone = weekly(q, SIGNAL[measure])
    names = _names(q, list(everyone))
    if not pts:
        return {"entity": entity, "measure": m, "forecast": None, "note": "No weekly figures for this country yet."}
    south = split_week(pts) == 1
    sig = hemisphere_signal(everyone, not south, today, names)
    f = forecast(pts, sig["ratio"], today)
    return {"entity": entity, "measure": m, "forecast": f, "signal": sig, "skill": backtest(pts, everyone) if f else None,
            "note": None if f else "Not enough earlier seasons (three or more, not counting 2020 and 2021) to forecast from."}


def forecast_map(q: Q, measure: str, today: date | None = None) -> dict:
    """Every country's forecast peak for its season under way or next, against its usual peak."""
    today = today or date.today()
    m = D.MEASURE.get(measure) or {"id": measure, "label": measure, "unit": "", "kind": "rate"}
    if measure not in SIGNAL:
        return {"measure": m, "rows": []}
    everyone = weekly(q, SIGNAL[measure])
    own = everyone if SIGNAL[measure] == measure else weekly(q, measure)
    names = _names(q, list(own))
    sig = {s: hemisphere_signal(everyone, s, today, names) for s in (True, False)}
    rows = []
    for e, pts in own.items():
        if not pts or pts[-1][0] < today - timedelta(days=120):
            continue
        south = split_week(pts) == 1
        f = forecast(pts, sig[not south]["ratio"], today)
        if f:
            rows.append({"entity": e, "name": names.get(e, e), "season": f["label"], "peak": f["peak"], "peak_lo": f["peak_lo"],
                         "peak_hi": f["peak_hi"], "peak_week": f["peak_week"], "vs_normal": round(f["vs_normal"], 2),
                         "peak_passed": f["peak_passed"], "weeks_seen": f["weeks_seen"]})
    rows.sort(key=lambda r: -r["vs_normal"])
    return {"measure": m, "rows": rows, "signals": {k: {"ratio": v["ratio"], "n": len(v["countries"])} for k, v in
                                                     (("southern", sig[True]), ("northern", sig[False]))}}
