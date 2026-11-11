"""Countries like this one, countries that move alike, and the synthetic comparison.

All three use data already held: each indicator's main source (its first-ranked one),
yearly, estimates only (no projections), countries only.

Countries like this one: each indicator is put on one scale across countries for the year
(logged first when it spans more than a hundredfold, such as GDP), and countries are
ranked by their average distance over the indicators both have.

Move alike: year-on-year changes of one indicator, compared country by country (correlation),
then grouped (k-means on those correlations) into a few groups whose lines rise and fall together.

Synthetic comparison (synthetic control, Abadie and Gardeazabal 2003): the weighted mix of
other countries (weights 0 to 1, adding up to 1) that tracked the country best before the
event year; after it, the gap between the country and its mix is the event's apparent effect.
A placebo run treats each pool country as if it had the event; if the real country's gap is
not unusual among them, the event may not have mattered.
"""

from __future__ import annotations

import math
import warnings
from typing import Callable

import numpy as np

PRESETS: dict[str, tuple[str, list[str]]] = {
    "economy": ("Economy", ["gdp_ppp_per_capita", "gdp_growth", "inflation", "unemployment", "exports_share_gdp",
                            "govt_revenue_gdp", "central_govt_debt_gdp", "industry_share_gdp", "agriculture_share_gdp",
                            "private_credit_gdp"]),
    "people": ("People", ["life_expectancy", "tfr", "median_age", "urban_share", "pop_growth_rate", "infant_mortality",
                          "wic_mys", "net_migration_rate", "pop_density"]),
    "government": ("Government", ["tax_revenue_gdp", "govt_expense_gdp", "military_spending_gdp", "women_in_parliament",
                                  "education_spending_gdp", "homicide_rate"]),
    "energy": ("Energy and climate", ["co2_per_capita", "energy_per_capita", "renewables_share_energy", "low_carbon_share_elec"]),
}
PRESETS["everything"] = ("Everything above", list(dict.fromkeys(i for _, ids in PRESETS.values() for i in ids)))

Rows = Callable[..., list[dict]]

_SQL = """
WITH first AS (SELECT indicator_id, arg_min(source_id, rank) AS src FROM indicator_sources GROUP BY 1)
SELECT s.entity_id, s.indicator_id, year(s.period_start) AS y, avg(s.value) AS v
FROM series s
JOIN first f ON f.indicator_id = s.indicator_id AND s.source_id = f.src
JOIN entities e ON e.entity_id = s.entity_id AND e.type = 'country'
WHERE s.indicator_id IN (SELECT unnest(?)) AND s.variant = 'central' AND s.breakdown = '' AND s.status = 'E'
  AND s.value IS NOT NULL {extra}
GROUP BY 1, 2, 3
"""


def _values(rows: Rows, indicators: list[str], lo: int | None = None, hi: int | None = None) -> dict[str, dict[str, dict[int, float]]]:
    """indicator -> entity -> year -> value."""
    extra, params = "", [indicators]
    if lo is not None:
        extra += " AND year(s.period_start) >= ?"
        params.append(lo)
    if hi is not None:
        extra += " AND year(s.period_start) <= ?"
        params.append(hi)
    out: dict[str, dict[str, dict[int, float]]] = {}
    for r in rows(_SQL.format(extra=extra), params):
        if r["v"] is None or not math.isfinite(r["v"]):
            continue
        out.setdefault(r["indicator_id"], {}).setdefault(r["entity_id"], {})[int(r["y"])] = float(r["v"])
    return out


def _at(by_year: dict[int, float], year: int, window: int = 4) -> float | None:
    """The value for the year, or the nearest earlier one within the window (figures come late)."""
    for y in range(year, year - window - 1, -1):
        if y in by_year:
            return by_year[y]
    return None


# ----------------------------------------------------------------------------- countries like this one
def like(rows: Rows, names: dict[str, str], entity: str, indicators: list[str], year: int, n: int = 10) -> dict:
    """The n countries nearest to entity in the year, on the indicators given."""
    vals = _values(rows, indicators, year - 4, year)
    used, scaled, raw = [], {}, {}
    for ind in indicators:
        by_ent = {e: _at(ys, year) for e, ys in vals.get(ind, {}).items()}
        by_ent = {e: v for e, v in by_ent.items() if v is not None}
        if len(by_ent) < 20 or entity not in by_ent:
            continue
        xs = np.array(list(by_ent.values()))
        logged = bool((xs > 0).all() and xs.max() / max(xs.min(), 1e-12) > 100)
        t = np.log10(xs) if logged else xs
        mu, sd = float(np.mean(t)), float(np.std(t))
        if sd == 0:
            continue
        used.append({"indicator_id": ind, "logged": logged, "countries": len(by_ent)})
        scaled[ind] = {e: ((math.log10(v) if logged else v) - mu) / sd for e, v in by_ent.items()}
        raw[ind] = by_ent
    if not used:
        return {"entity_id": entity, "year": year, "used": [], "nearest": [], "note": "Too few figures for this country and year."}
    me = {ind: scaled[ind][entity] for ind in scaled}
    out = []
    candidates = set().union(*(set(s) for s in scaled.values())) - {entity}
    need = max(2, math.ceil(0.6 * len(me)))
    for e in candidates:
        diffs = {ind: scaled[ind][e] - me[ind] for ind in me if e in scaled[ind]}
        if len(diffs) < need:
            continue
        d = math.sqrt(sum(x * x for x in diffs.values()) / len(diffs))
        close = sorted(diffs, key=lambda k: abs(diffs[k]))
        out.append({"entity_id": e, "name": names.get(e, e), "distance": round(d, 3),
                    "likeness": round(100 * math.exp(-d), 1), "shared": len(diffs),
                    "closest_on": close[:3], "furthest_on": close[::-1][:2],
                    "values": {ind: raw[ind].get(e) for ind in me}})
    out.sort(key=lambda r: r["distance"])
    return {"entity_id": entity, "name": names.get(entity, entity), "year": year, "used": used,
            "own": {ind: raw[ind][entity] for ind in me}, "nearest": out[:n]}


def like_by_decade(rows: Rows, names: dict[str, str], entity: str, indicators: list[str], years: list[int], n: int = 5) -> list[dict]:
    out = []
    for y in years:
        r = like(rows, names, entity, indicators, y, n)
        out.append({"year": y, "nearest": [{k: x[k] for k in ("entity_id", "name", "likeness")} for x in r["nearest"]],
                    "used": len(r["used"])})
    return out


# ----------------------------------------------------------------------------- move alike
def move_alike(rows: Rows, names: dict[str, str], indicator: str, start: int, end: int, groups: int = 6,
               min_years: int = 12) -> dict:
    """Groups of countries whose yearly changes in the indicator go together."""
    vals = _values(rows, [indicator], start, end).get(indicator, {})
    years = list(range(start + 1, end + 1))
    series: dict[str, np.ndarray] = {}
    for e, ys in vals.items():
        ch = [ys[y] - ys[y - 1] if y in ys and y - 1 in ys else np.nan for y in years]
        arr = np.array(ch, dtype=float)
        if np.isfinite(arr).sum() >= min_years and np.nanstd(arr) > 0:
            series[e] = arr
    ents = sorted(series)
    if len(ents) < groups * 2:
        return {"indicator_id": indicator, "groups": [], "members": {}, "note": "Too few countries with enough years."}
    m = np.array([series[e] for e in ents])
    m = (m - np.nanmean(m, axis=1, keepdims=True)) / np.nanstd(m, axis=1, keepdims=True)
    k = len(ents)
    corr = np.zeros((k, k))
    for i in range(k):
        for j in range(i, k):
            ok = np.isfinite(m[i]) & np.isfinite(m[j])
            c = float(np.mean(m[i][ok] * m[j][ok])) if ok.sum() >= min_years // 2 else 0.0
            corr[i, j] = corr[j, i] = c
    # k-means on each country's row of correlations (countries that move with the same others end up
    # together); average linkage leaves one huge group and a few strays, this gives usable groups
    clusters = _kmeans_groups(corr, groups)
    out_groups = []
    members: dict[str, int] = {}
    for gi, (_, idx) in enumerate(sorted(clusters.items(), key=lambda kv: -len(kv[1]))):
        sub = corr[np.ix_(idx, idx)]
        inner = float((sub.sum() - len(idx)) / max(1, len(idx) * (len(idx) - 1))) if len(idx) > 1 else 1.0
        ids = [ents[i] for i in idx]
        for e in ids:
            members[e] = gi
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            avg = np.nanmean(m[idx], axis=0)
        mean_line = [None if not np.isfinite(v) else round(float(v), 3) for v in avg]
        out_groups.append({"group": gi, "size": len(ids), "together": round(inner, 2),
                           "countries": sorted(ids, key=lambda e: names.get(e, e)), "line": mean_line})
    return {"indicator_id": indicator, "start": start, "end": end, "years": years, "groups": out_groups,
            "members": members, "names": {e: names.get(e, e) for e in ents}}


def _kmeans_groups(corr: np.ndarray, k: int, rounds: int = 8, iters: int = 50) -> dict[int, list[int]]:
    """k groups of rows of corr; the best of a few seeded starts (fixed seed, so the same each time)."""
    rng = np.random.default_rng(7)
    X = corr
    best, best_cost = None, np.inf
    for _ in range(rounds):
        centres = [X[rng.integers(len(X))]]
        for _ in range(1, k):  # k-means++ start
            d = np.min([((X - c) ** 2).sum(axis=1) for c in centres], axis=0)
            centres.append(X[rng.choice(len(X), p=d / d.sum())] if d.sum() > 0 else X[rng.integers(len(X))])
        C = np.array(centres)
        for _ in range(iters):
            lab = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(axis=2), axis=1)
            newc = np.array([X[lab == j].mean(axis=0) if (lab == j).any() else C[j] for j in range(k)])
            if np.allclose(newc, C):
                break
            C = newc
        cost = float(((X - C[lab]) ** 2).sum())
        if cost < best_cost:
            best, best_cost = lab, cost
    return {j: [i for i in range(len(X)) if best[i] == j] for j in range(k) if (best == j).any()}


# ----------------------------------------------------------------------------- synthetic comparison
def _simplex_weights(X: np.ndarray, y: np.ndarray, iters: int = 3000) -> np.ndarray:
    """Weights w >= 0 adding up to 1 that make X @ w closest to y (projected gradient)."""
    k = X.shape[1]
    w = np.full(k, 1.0 / k)
    L = float(np.linalg.norm(X, 2) ** 2) or 1.0
    step = 1.0 / L
    for _ in range(iters):
        g = X.T @ (X @ w - y)
        w = _project(w - step * g)
    return w


def _project(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto the simplex (Duchi et al. 2008)."""
    u = np.sort(v)[::-1]
    css = np.cumsum(u)
    rho = np.nonzero(u * np.arange(1, len(v) + 1) > (css - 1))[0][-1]
    theta = (css[rho] - 1) / (rho + 1.0)
    return np.maximum(v - theta, 0)


def _fit(Y: np.ndarray, treated: int, donors: list[int], pre: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Weights, the synthetic line, and the pre- and post-event RMSPE."""
    X = Y[:, donors]
    w = _simplex_weights(X[pre], Y[pre, treated])
    synth = X @ w
    gap = Y[:, treated] - synth
    pre_rmspe = float(np.sqrt(np.mean(gap[pre] ** 2)))
    post_rmspe = float(np.sqrt(np.mean(gap[~pre] ** 2))) if (~pre).any() else 0.0
    return w, synth, pre_rmspe, post_rmspe


def synthetic(rows: Rows, names: dict[str, str], entity: str, indicator: str, event_year: int,
              pool: list[str] | None = None, start: int | None = None, end: int | None = None,
              placebos: bool = True, max_pool: int = 60) -> dict:
    """The synthetic comparison for entity on indicator around event_year."""
    start = start or event_year - 20
    vals = _values(rows, [indicator], start, end).get(indicator, {})
    if entity not in vals:
        return {"error": f"No yearly figures for {names.get(entity, entity)} on this indicator."}
    last = max(vals[entity])
    end = min(end or last, last)
    years = list(range(start, end + 1))
    if event_year <= start + 4 or event_year > end:
        return {"error": "The event year needs at least five years of figures before it and one after."}
    full = [e for e, ys in vals.items() if all(y in ys for y in years)]
    if entity not in full:
        missing = [y for y in years if y not in vals[entity]]
        return {"error": f"{names.get(entity, entity)} has gaps in {missing[:5]}; choose later start years or another indicator."}
    donors_all = [e for e in full if e != entity and (not pool or e in pool)]
    if len(donors_all) < 3:
        return {"error": "Fewer than three countries in the pool have every year; widen the pool or shorten the years."}
    # keep the pool to the countries most like the entity before the event, for speed and sense
    pre_years = [y for y in years if y < event_year]
    target = np.array([vals[entity][y] for y in pre_years])
    donors_all.sort(key=lambda e: float(np.mean((np.array([vals[e][y] for y in pre_years]) - target) ** 2)))
    donors_all = donors_all[:max_pool]
    ents = [entity, *donors_all]
    Y = np.array([[vals[e][y] for e in ents] for y in years], dtype=float)
    pre = np.array([y < event_year for y in years])
    donors = list(range(1, len(ents)))
    w, synth, pre_r, post_r = _fit(Y, 0, donors, pre)
    weights = sorted(({"entity_id": ents[d], "name": names.get(ents[d], ents[d]), "weight": round(float(x), 3)}
                      for d, x in zip(donors, w) if x >= 0.005), key=lambda r: -r["weight"])
    ratio = post_r / pre_r if pre_r > 0 else float("inf")
    placebo = []
    if placebos:
        for i in donors[:40]:
            others = [d for d in range(len(ents)) if d != i and d != 0]
            _, _, pr, po = _fit(Y, i, others, pre)
            gap = Y[:, i] - (Y[:, others] @ _simplex_weights(Y[pre][:, others], Y[pre, i]))
            placebo.append({"entity_id": ents[i], "ratio": round(po / pr, 2) if pr > 0 else None,
                            "pre_rmspe": round(pr, 4), "gap": [round(float(g), 4) for g in gap]})
    ratios = [p["ratio"] for p in placebo if p["ratio"] is not None]
    rank = 1 + sum(1 for r in ratios if r >= ratio) if ratios else None
    p_value = round(rank / (len(ratios) + 1), 3) if rank else None
    post_gap = float(np.mean((Y[:, 0] - synth)[~pre]))
    scale = float(np.mean(np.abs(Y[pre, 0]))) or 1.0
    if p_value is None:
        verdict = "No placebo run."
    elif p_value <= 0.1:
        verdict = (f"The gap after {event_year} is larger than for {len(ratios) + 1 - rank} of the {len(ratios)} other countries "
                   "run the same way: the event looks like it mattered.")
    else:
        verdict = (f"{rank - 1} of the {len(ratios)} other countries run the same way show as big a gap with no event: "
                   "the event may not have mattered, or the mix does not track well enough.")
    return {"entity_id": entity, "name": names.get(entity, entity), "indicator_id": indicator, "event_year": event_year,
            "years": years, "actual": [round(float(v), 4) for v in Y[:, 0]], "synthetic": [round(float(v), 4) for v in synth],
            "weights": weights, "pre_rmspe": round(pre_r, 4), "post_rmspe": round(post_r, 4),
            "fit_share": round(pre_r / scale, 4), "mean_gap_after": round(post_gap, 4), "ratio": round(ratio, 2) if math.isfinite(ratio) else None,
            "placebos": placebo, "rank": rank, "p_value": p_value, "verdict": verdict, "pool_size": len(donors_all)}
