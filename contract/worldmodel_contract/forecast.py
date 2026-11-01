"""Statistical forecasts for any yearly series, in plain Python (no numpy).

A handful of simple, well-understood models are fitted to a series' estimates, each
is scored by a rolling back-test (refit on the data up to each of the last few
years, forecast the years after, compare with what happened), and the model that
missed least is used (or a simpler one within 5% of it). The ranges come from the same back-test: the 80% and 95%
bands are the chosen model's typical miss at each horizon, so a series that has
been hard to forecast gets wide bands. Past the horizons the back-test reaches,
the miss is assumed to grow with the square root of the horizon.

Models:
    naive      the last value carries on (a random walk)
    drift      the average yearly change of the last 20 years carries on
    trend      a straight line fitted to the last 30 years
    damped     Holt's linear trend with the trend fading out (exponential smoothing)
    mean       drifts back towards the series' own long-run average (AR(1)), for
               rates such as growth and inflation that swing around a level

Level series that are always above zero (population, GDP, prices) are modelled on
the log scale, so they grow by percentages rather than by fixed amounts and the
ranges cannot fall below zero.

Used by the API's /forecast endpoint; kept in the contract so other consumers of
the data streams (the MCP server) give the same answers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

Z80, Z95 = 1.2816, 1.9600
MIN_POINTS = 8
MODEL_NAMES = {
    "naive": "Last value carries on",
    "drift": "Recent average change carries on",
    "trend": "Straight-line trend",
    "damped": "Fading trend (exponential smoothing)",
    "mean": "Back towards the long-run average",
}


@dataclass
class Fitted:
    model: str
    predict: Callable[[int], float]  # h (1, 2, ...) -> forecast, on the modelling scale


# ----------------------------------------------------------------------------- models
def _naive(y: list[float]) -> Fitted:
    last = y[-1]
    return Fitted("naive", lambda h: last)


def _drift(y: list[float]) -> Fitted:
    w = y[-21:]
    step = (w[-1] - w[0]) / (len(w) - 1) if len(w) > 1 else 0.0
    last = y[-1]
    return Fitted("drift", lambda h: last + h * step)


def _trend(y: list[float]) -> Fitted:
    w = y[-30:]
    n = len(w)
    xs = range(n)
    mx, my = (n - 1) / 2, sum(w) / n
    sxx = sum((x - mx) ** 2 for x in xs) or 1.0
    b = sum((x - mx) * (v - my) for x, v in zip(xs, w)) / sxx
    a = my - b * mx
    return Fitted("trend", lambda h: a + b * (n - 1 + h))


def _holt(y: list[float], alpha: float, beta: float, phi: float) -> tuple[float, float, float]:
    """One-step squared error, final level and trend of damped Holt smoothing."""
    level, trend = y[0], y[1] - y[0]
    sse = 0.0
    for v in y[1:]:
        f = level + phi * trend
        sse += (v - f) ** 2
        new_level = alpha * v + (1 - alpha) * f
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return sse, level, trend


def _damped(y: list[float]) -> Fitted:
    best = None
    for alpha in (0.2, 0.4, 0.6, 0.8, 0.95):
        for beta in (0.05, 0.15, 0.3):
            for phi in (0.8, 0.9, 0.98):
                sse, level, trend = _holt(y, alpha, beta, phi)
                if best is None or sse < best[0]:
                    best = (sse, level, trend, phi)
    _, level, trend, phi = best

    def predict(h: int) -> float:
        return level + trend * sum(phi ** i for i in range(1, h + 1))
    return Fitted("damped", predict)


def _mean(y: list[float]) -> Fitted:
    w = y[-30:]
    mu = sum(w) / len(w)
    num = sum((w[i] - mu) * (w[i - 1] - mu) for i in range(1, len(w)))
    den = sum((w[i - 1] - mu) ** 2 for i in range(1, len(w))) or 1.0
    rho = max(0.0, min(0.98, num / den))
    last = y[-1]
    return Fitted("mean", lambda h: mu + (rho ** h) * (last - mu))


SIMPLEST_FIRST = ("naive", "mean", "drift", "damped", "trend")
MODELS = {"naive": _naive, "drift": _drift, "trend": _trend, "damped": _damped, "mean": _mean}


# ----------------------------------------------------------------------------- helpers
def recent_run(years: list[int], values: list[float]) -> tuple[list[int], list[float]]:
    """The latest unbroken run of yearly values (a gap of a year or more starts a new run)."""
    pairs = sorted((int(y), float(v)) for y, v in zip(years, values) if v is not None and math.isfinite(v))
    if not pairs:
        return [], []
    run = [pairs[-1]]
    for y, v in reversed(pairs[:-1]):
        if run[0][0] - y != 1:
            break
        run.insert(0, (y, v))
    return [y for y, _ in run], [v for _, v in run]


def use_log(values: list[float], unit: str | None) -> bool:
    """Model on the log scale: always above zero, and a level rather than a rate or share."""
    u = (unit or "").lower()
    if any(k in u for k in ("percent", "%", "rate", "per 100", "ratio", "index, world", "points", "years")):
        return False
    return bool(values) and min(values) > 0


def _backtest(y: list[float], model: str, origins: int, depth: int,
              back: Callable[[float], float]) -> tuple[dict[int, list[float]], list[float]]:
    """Refit at each of the last `origins` points and forecast `depth` years on. Returns
    the errors (forecast minus outcome, modelling scale) by horizon, and every miss in
    the series' own units (so models on the log scale compare fairly with the rest)."""
    errors: dict[int, list[float]] = {h: [] for h in range(1, depth + 1)}
    misses: list[float] = []
    n = len(y)
    for cut in range(n - origins, n):
        if cut < MIN_POINTS - 2:
            continue
        fit = MODELS[model](y[:cut])
        for h in range(1, depth + 1):
            if cut + h - 1 < n:
                f, actual = fit.predict(h), y[cut + h - 1]
                errors[h].append(f - actual)
                misses.append(abs(back(f) - back(actual)))
    return errors, misses


# ----------------------------------------------------------------------------- main
def forecast(years: list[int], values: list[float], horizon: int = 10, unit: str | None = None,
             bounds: tuple[float, float] | None = None, model: str | None = None) -> dict:
    """Forecast a yearly series `horizon` years past its last value.

    Returns model (the one used), models (each with its back-test typical miss),
    transform ('log' or 'none'), history_end, points (year, mean, lo80, hi80, lo95,
    hi95) and backtest (the chosen model's one-year-ahead forecasts in the past, for
    a track record). `model` forces one model instead of the best. Raises
    ValueError when the series is too short."""
    ys, vs = recent_run(years, values)
    if len(vs) < MIN_POINTS:
        raise ValueError(f"needs at least {MIN_POINTS} years in a row of figures; has {len(vs)}")
    log = use_log(vs, unit)
    y = [math.log(v) for v in vs] if log else list(vs)
    back = (lambda v: math.exp(v)) if log else (lambda v: v)
    n = len(y)
    origins = max(3, min(12, n - MIN_POINTS + 2))
    depth = max(1, min(5, horizon, n // 4))

    scored = []
    for name in MODELS:
        errs, miss = _backtest(y, name, origins, depth, back)
        scored.append({"id": name, "name": MODEL_NAMES[name], "mae": sum(miss) / len(miss) if miss else None,
                       "n": len(miss), "_errs": errs})
    ranked = sorted((s for s in scored if s["mae"] is not None), key=lambda s: s["mae"])
    if model and model in MODELS:
        chosen = next(s for s in scored if s["id"] == model)
    else:
        # The simplest model within 5% of the best: a small edge in a short back-test is
        # more likely luck than skill, and simple models go wrong more gently.
        best = ranked[0]["mae"] if ranked else None
        chosen = next((s for name in SIMPLEST_FIRST for s in ranked
                       if s["id"] == name and s["mae"] <= best * 1.05 + 1e-12), None) \
            or next(s for s in scored if s["id"] == "naive")

    # The typical miss at each horizon, on the modelling scale, never shrinking with distance.
    errs = chosen["_errs"]
    sig: dict[int, float] = {}
    for h in range(1, depth + 1):
        es = errs.get(h, [])
        if len(es) >= 3:
            sig[h] = math.sqrt(sum(e * e for e in es) / len(es))
    if 1 not in sig:  # too short a back-test: the one-step changes stand in
        d = [y[i] - y[i - 1] for i in range(1, n)]
        sig[1] = math.sqrt(sum(v * v for v in d) / len(d)) if d else 0.0
    last_h = 1
    for h in range(1, horizon + 1):
        if h in sig:
            sig[h] = max(sig[h], sig[last_h])
            last_h = h
        else:
            sig[h] = sig[last_h] * math.sqrt(h / last_h)

    lo_b, hi_b = bounds if bounds else (-math.inf, math.inf)
    clip = lambda v: max(lo_b, min(hi_b, v))  # noqa: E731
    fit = MODELS[chosen["id"]](y)
    points = []
    for h in range(1, horizon + 1):
        m, s = fit.predict(h), sig[h]
        points.append({"year": ys[-1] + h, "mean": clip(back(m)),
                       "lo80": clip(back(m - Z80 * s)), "hi80": clip(back(m + Z80 * s)),
                       "lo95": clip(back(m - Z95 * s)), "hi95": clip(back(m + Z95 * s))})

    # Forecasts the chosen model would have made in the past, one and two years past
    # the last figure it had (origin), against what happened.
    backtest = []
    for cut in range(max(MIN_POINTS - 2, n - 20), n):
        past = MODELS[chosen["id"]](y[:cut])
        row = {"origin": ys[cut - 1], "year": ys[cut], "forecast": back(past.predict(1)), "actual": vs[cut],
               "forecast_1": back(past.predict(1)), "actual_1": vs[cut], "forecast_2": None, "actual_2": None}
        if cut + 1 < n:
            row["forecast_2"], row["actual_2"] = back(past.predict(2)), vs[cut + 1]
        backtest.append(row)

    return {
        "model": chosen["id"], "model_name": chosen["name"], "transform": "log" if log else "none",
        "history_start": ys[0], "history_end": ys[-1], "last_value": vs[-1],
        "models": [{k: v for k, v in s.items() if k != "_errs"} for s in sorted(
            scored, key=lambda s: (s["mae"] is None, s["mae"] or 0))],
        "backtest_origins": origins, "backtest_depth": depth,
        "points": points, "backtest": backtest,
    }
