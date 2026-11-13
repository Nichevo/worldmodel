"""Recession odds and nowcasts, worked out from the warehouse's monthly and quarterly series.

Recession odds
    The chance that a recession (two quarters running of falling real GDP) starts within
    the next twelve months. One logistic model is fitted across all countries at once on:
    the OECD leading indicator's gap from trend and its change over six months, the change
    in the central bank's rate over a year, and the latest quarter's growth. A country
    without a leading indicator gets the same model without it. The US also gets the
    New York Fed's yield-curve model (a probit on the 10-year less 3-month gap, with the
    coefficients the New York Fed publishes).

Nowcasts
    This quarter's growth before the official figure: last quarter's growth and the leading
    indicator's level and change over the months of the quarter already out, fitted per
    country. The range is from how far the same method was off over the last 20 quarters,
    each estimated only from what came before. The US also shows the Atlanta Fed's GDPNow.

Both are simple, explained models: something to set beside the news, not a forecast to
bet on. They are refitted when the warehouse changes.
"""

from __future__ import annotations

import json
import math
import threading
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Callable

import numpy as np

from worldmodel_contract import local

Q = Callable[[str, list], list[dict]]

KEY = ("NZL", "AUS", "GBR", "USA")
NYFED = (-0.5333, -0.6330)  # P(recession in 12 months) = Φ(a + b × spread)
FEATURES = {
    "cli_gap": "the leading indicator's gap from trend",
    "cli_chg": "the leading indicator's change over six months",
    "rate_chg": "the change in the central bank rate over a year",
    "g_last": "the latest quarter's growth",
}
UNITS = {"cli_gap": "points", "cli_chg": "points", "rate_chg": "percentage points", "g_last": "%"}
MODELS = (("full", ("cli_gap", "cli_chg", "rate_chg", "g_last")), ("no_cli", ("rate_chg", "g_last")), ("gdp", ("g_last",)))
_fit_cache: dict = {}
_log_lock = threading.Lock()


def mi(d: date) -> int:
    """A month as a number, for arithmetic."""
    return d.year * 12 + d.month - 1


def md(i: int) -> date:
    return date(i // 12, i % 12 + 1, 1)


def qlabel(i: int) -> str:
    d = md(i)
    return f"{d.year} Q{(d.month - 1) // 3 + 1}"


def _monthly(q: Q, ind: str, entities: list[str] | None = None) -> dict[str, dict[int, float]]:
    where, params = "", [ind]
    if entities:
        where = f" AND entity_id IN ({', '.join('?' * len(entities))})"
        params += entities
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for r in q(f"""SELECT entity_id AS e, period_start AS d, avg(value) AS v FROM series
                   WHERE indicator_id = ? AND variant = 'central' AND breakdown = ''{where}
                   GROUP BY 1, 2""", params):
        out[r["e"]][mi(r["d"])] = r["v"]
    return out


def recessions(growth: dict[int, float]) -> list[tuple[int, int]]:
    """(first month, last month) of each run of two or more falling quarters."""
    qs = sorted(growth)
    out, run = [], []
    for m in qs:
        if growth[m] < 0 and (not run or m - run[-1] == 3):
            run.append(m)
        else:
            if len(run) >= 2:
                out.append((run[0], run[-1] + 2))
            run = [m] if growth[m] < 0 else []
    if len(run) >= 2:
        out.append((run[0], run[-1] + 2))
    return out


def _rows(cli: dict[int, float], rate: dict[int, float], growth: dict[int, float]) -> dict[int, dict]:
    """Each month's features (None where not known). Quarterly growth counts as known two
    months after its quarter ends."""
    if not growth:
        return {}
    months = set(cli) | set(rate)
    lo, hi = min(growth) + 5, max(months) if months else max(growth) + 5
    out = {}
    qs = sorted(growth)
    k = 0
    for m in range(lo, hi + 1):
        while k + 1 < len(qs) and qs[k + 1] + 5 <= m:
            k += 1
        f = {"g_last": growth[qs[k]] if qs[k] + 5 <= m else None,
             "cli_gap": cli[m] - 100 if m in cli else None,
             "cli_chg": cli[m] - cli[m - 6] if m in cli and m - 6 in cli else None,
             "rate_chg": rate[m] - rate[m - 12] if m in rate and m - 12 in rate else None}
        out[m] = f
    return out


def _label(m: int, recs: list[tuple[int, int]], last_q: int) -> int | None:
    """1 when a recession starts within the next 12 months, 0 when none does, None while
    in one or when GDP is not yet known that far ahead."""
    if any(a <= m <= b for a, b in recs):
        return None
    if m + 12 > last_q + 2:
        return None
    return int(any(m < a <= m + 12 for a, _ in recs))


def logit(X: np.ndarray, y: np.ndarray, ridge: float = 1e-2, steps: int = 50) -> np.ndarray:
    """Logistic regression by Newton steps, with a small ridge so it always settles."""
    w = np.zeros(X.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (p - y) + ridge * np.r_[0, w[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + ridge * np.diag(np.r_[0, np.ones(len(w) - 1)])
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def auc(p: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    ranks = np.argsort(np.argsort(np.r_[pos, neg])) + 1
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def fit(q: Q, version: str = "") -> dict:
    """The pooled models, fitted once per warehouse."""
    if version and _fit_cache.get("version") == version:
        return _fit_cache["fit"]
    cli, rate, gdp = _monthly(q, "oecd_cli"), _monthly(q, "bis_policy_rate_m"), _monthly(q, "gdp_growth_q")
    panel: dict[str, dict[int, dict]] = {}
    labels: dict[str, dict[int, int | None]] = {}
    recs: dict[str, list] = {}
    for e, g in gdp.items():
        panel[e] = _rows(cli.get(e, {}), rate.get(e, {}), g)
        recs[e] = recessions(g)
        labels[e] = {m: _label(m, recs[e], max(g)) for m in panel[e]}
    models = {}
    for name, feats in MODELS:
        X, y = [], []
        for e, rows in panel.items():
            for m, f in rows.items():
                lab = labels[e][m]
                if lab is None or any(f[k] is None for k in feats):
                    continue
                X.append([f[k] for k in feats])
                y.append(lab)
        if len(y) < 60 or sum(y) < 5:
            continue
        Xa = np.array(X, dtype=float)
        mu, sd = Xa.mean(0), Xa.std(0)
        sd[sd == 0] = 1
        Z = np.c_[np.ones(len(Xa)), (Xa - mu) / sd]
        ya = np.array(y, dtype=float)
        w = logit(Z, ya)
        p = 1 / (1 + np.exp(-Z @ w))
        models[name] = {"features": feats, "w": w.tolist(), "mu": mu.tolist(), "sd": sd.tolist(),
                        "n": len(y), "events": int(ya.sum()), "base": float(ya.mean()), "auc": auc(p, ya)}
    out = {"panel": panel, "recs": recs, "models": models, "gdp": gdp, "cli": cli}
    if version:
        _fit_cache.update(version=version, fit=out)
    return out


def _prob(model: dict, f: dict) -> tuple[float, list[dict]]:
    z = model["w"][0]
    parts = []
    for k, w, mu, sd in zip(model["features"], model["w"][1:], model["mu"], model["sd"]):
        c = w * (f[k] - mu) / sd
        z += c
        parts.append({"feature": k, "about": FEATURES[k], "value": round(f[k], 2), "unit": UNITS[k], "push": round(c, 2)})
    return 1 / (1 + math.exp(-max(-30, min(30, z)))), parts


def _pick(models: dict, f: dict) -> str | None:
    for name, feats in MODELS:
        if name in models and all(f.get(k) is not None for k in feats):
            return name
    return None


def nyfed(spread: float) -> float:
    a, b = NYFED
    return 0.5 * (1 + math.erf((a + b * spread) / math.sqrt(2)))


def recession_odds(q: Q, entities: list[str], version: str = "", history_from: int = 1990) -> dict:
    """Each country's odds now, the history of the odds, its recessions and what drives the latest reading."""
    F = fit(q, version)
    models = F["models"]
    spread = _monthly(q, "us_term_spread", ["USA"]).get("USA", {})
    out = []
    for e in entities:
        rows = F["panel"].get(e) or {}
        known = [m for m, f in sorted(rows.items()) if _pick(models, f)]
        item: dict = {"entity": e, "odds": None, "model": None, "history": [], "recessions": [], "drivers": [], "month": None,
                      "in_recession": False}
        if known:
            hist = []
            for m in known:
                if md(m).year < history_from:
                    continue
                p, _ = _prob(models[_pick(models, rows[m])], rows[m])
                hist.append([md(m).isoformat()[:7], round(100 * p, 1)])
            # The latest month, unless a month or three back has the fuller model (the leading
            # indicator often comes out a month after the central bank rate).
            last = known[-1]
            order = [n for n, _ in MODELS]
            best = min((_pick(models, rows[m]) for m in known[-4:]), key=order.index)
            last = max(m for m in known[-4:] if _pick(models, rows[m]) == best)
            name = best
            p, parts = _prob(models[name], rows[last])
            recs = F["recs"].get(e, [])
            item.update(odds=round(100 * p, 1), model=name, month=md(last).isoformat()[:7], history=hist,
                        recessions=[[md(a).isoformat()[:7], md(b).isoformat()[:7]] for a, b in recs if md(b).year >= history_from],
                        drivers=sorted(parts, key=lambda x: -abs(x["push"])),
                        in_recession=bool(recs and recs[-1][1] >= max(F["gdp"][e]) + 2))
        if e == "USA" and spread:
            ms = sorted(spread)
            item["yield_curve"] = {"odds": round(100 * nyfed(spread[ms[-1]]), 1), "spread": round(spread[ms[-1]], 2),
                                   "month": md(ms[-1]).isoformat()[:7],
                                   "history": [[md(m).isoformat()[:7], round(100 * nyfed(spread[m]), 1)]
                                               for m in ms if md(m).year >= history_from]}
        out.append(item)
    about = {k: {"months": v["n"], "recessions": v["events"], "base_rate": round(100 * v["base"], 1),
                 "auc": round(v["auc"], 2) if v["auc"] is not None else None, "features": [FEATURES[f] for f in v["features"]]}
             for k, v in models.items()}
    return {"countries": out, "models": about,
            "note": ("A recession here is two quarters running of falling real GDP. The odds are the chance one starts "
                     "within twelve months, from a model fitted across all countries; the lines before today are the "
                     "same model looking back, so they fit the past better than a reading at the time would have.")}


# ----------------------------------------------------------------------------- nowcasts
def _quarter_cli(cli: dict[int, float], qm: int, upto: int | None = None) -> tuple[float | None, int]:
    vals = [cli[m] for m in range(qm, qm + 3) if m in cli and (upto is None or m <= upto)]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def _design(g: dict[int, float], cli: dict[int, float], quarters: list[int], use_cli: bool):
    X, y = [], []
    for t in quarters:
        if t - 3 not in g:
            continue
        row = [1.0, g[t - 3]]
        if use_cli:
            c, _ = _quarter_cli(cli, t)
            c0, _ = _quarter_cli(cli, t - 3)
            if c is None or c0 is None:
                continue
            row += [c - 100, c - c0]
        X.append(row)
        y.append(g[t])
    return np.array(X), np.array(y)


def nowcast(q: Q, entity: str, version: str = "") -> dict:
    """This quarter's growth for one country, the method's track record and, for the US, GDPNow."""
    F = fit(q, version)
    g = F["gdp"].get(entity, {})
    cli = F["cli"].get(entity, {})
    out: dict = {"entity": entity, "quarter": None, "estimate": None}
    if len(g) < 24:
        out["note"] = "Not enough quarterly GDP figures for a nowcast."
        return out
    qs = sorted(g)
    target = qs[-1] + 3
    use_cli = sum(1 for m in cli if m >= target - 6) > 0 and len(cli) > 60
    X, y = _design(g, cli, qs, use_cli)
    if len(y) < 20:
        use_cli = False
        X, y = _design(g, cli, qs, False)
    w = _ols(X, y)
    # Track record: each of the last 20 quarters estimated from the quarters before it.
    track = []
    for t in qs[-20:]:
        before = [s for s in qs if s < t]
        Xb, yb = _design(g, cli, before, use_cli)
        Xt, _ = _design(g, cli, [t], use_cli)
        if len(yb) < 16 or not len(Xt):
            continue
        est = float(Xt[0] @ _ols(Xb, yb))
        track.append({"quarter": qlabel(t), "estimate": round(est, 2), "actual": round(g[t], 2)})
    errs = [t["actual"] - t["estimate"] for t in track]
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs)) if errs else None
    row = [1.0, g[qs[-1]]]
    months = 0
    if use_cli:
        c, months = _quarter_cli(cli, target)
        if c is None:  # no month of the quarter out yet: the latest month stands in
            last = max(cli)
            c = cli[last]
        prev_q = target - 3
        c0, _ = _quarter_cli(cli, prev_q)
        row += [c - 100, c - (c0 if c0 is not None else c)]
    est = float(np.array(row) @ w)
    official = g.get(target)
    out.update(quarter=qlabel(target), estimate=round(est, 2), months_used=months, uses_cli=use_cli,
               low=round(est - 1.28 * rmse, 2) if rmse else None, high=round(est + 1.28 * rmse, 2) if rmse else None,
               annualised=round(100 * ((1 + est / 100) ** 4 - 1), 1), typical_error=round(rmse, 2) if rmse else None,
               last_quarter=qlabel(qs[-1]), last_actual=round(g[qs[-1]], 2), official=official, track=track,
               note=("From last quarter's growth" + (" and the OECD leading indicator" + (f" ({months} of the quarter's 3 months out)" if months else " (latest month, none of the quarter yet)") if use_cli else "")
                     + ". The range covers about 8 in 10 of the method's past misses."))
    if entity == "USA":
        now = _monthly(q, "us_gdpnow", ["USA"]).get("USA", {})
        if now:
            m = max(now)
            out["gdpnow"] = {"quarter": qlabel(m), "annualised": round(now[m], 1),
                             "quarterly": round(100 * ((1 + now[m] / 100) ** 0.25 - 1), 2)}
    _remember(entity, out)
    return out


# ----------------------------------------------------------------------------- kept nowcasts
def _log_path():
    return local.home() / "outlook" / "nowcasts.json"


def remembered() -> dict:
    try:
        return json.loads(_log_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _remember(entity: str, n: dict) -> None:
    """Keep each quarter's latest nowcast made before the official figure, so the release calendar can say how far off it was."""
    if n.get("estimate") is None or n.get("official") is not None:
        return
    with _log_lock:
        try:
            log = remembered()
            if log.get(entity, {}).get(n["quarter"], {}).get("estimate") == n["estimate"]:
                return
            log.setdefault(entity, {})[n["quarter"]] = {"estimate": n["estimate"], "made": datetime.now(timezone.utc).isoformat()[:16]}
            p = _log_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(log, indent=1), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass
