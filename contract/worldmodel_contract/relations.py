"""The relationship scan's shared terms: how figures are turned into yearly changes,
the evidence labels, the country groups it checks, and where its results live.

The scan itself (data/worldmodel_data/relations.py) runs after each refresh on the
new warehouse and writes three files per build into <home>/warehouse/relationships/:

    <build_id>.pairs.parquet    one row per pair of indicators tested
    <build_id>.events.parquet   one row per event kind and indicator (before and after events)
    <build_id>.json             what was tested, with which settings, how long it took

Any consumer (the app, an MCP server, a notebook) can read them; nothing here needs
the pipeline. The scan never calls anything cause and effect: each pair carries the
labels its evidence earns, and a note on likely common causes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# Evidence labels, weakest first. A pair can earn several.
LABELS = {
    "together": "Move together",
    "first": "One tends to come first",
    "holds": "Holds after allowing for income and time",
}
EVENT_LABEL = "Before and after events"

# Country groups whose own correlation is stored for each pair (the list can be
# filtered by them). Membership comes from the warehouse's memberships table.
GROUPS = {
    "income-high": "High income", "income-upper-middle": "Upper middle income",
    "income-lower-middle": "Lower middle income", "income-low": "Low income",
    "oecd": "OECD", "eu": "European Union",
    "africa": "Africa", "americas": "Americas", "asia": "Asia", "europe": "Europe", "oceania": "Oceania",
}

# Event kinds looked at for "before and after", with the indicator id prefixes an
# episode rule derives the event from (a recession "lowering GDP" is built in, not a finding).
EVENT_KINDS: dict[str, tuple[str, ...]] = {
    "recession": ("gdp_", "gni_"), "boom": ("gdp_", "gni_", "investment_share", "private_credit"),
    "inflation": ("inflation", "gdp_deflator"), "debt": ("central_govt_debt", "govt_debt"),
    "crisis": (), "coup": (), "conflict": (), "election": (), "leader": (), "law": (),
    "sanction": (), "disaster": (), "epidemic": (),
}


def built_in(kind: str, indicator_id: str) -> bool:
    return any(indicator_id.startswith(p) for p in EVENT_KINDS.get(kind, ()))


EVENT_YEARS = 5          # years after the event that are compared
MAX_LAG = 5              # the lag chart runs from Y leading by 5 years to X leading by 5
CONTROL = "gdp_per_capita_growth"  # the "income" control: real growth of GDP per person
YES_NO = "yes/no"


def change_kind(unit: str | None, all_positive: bool) -> str:
    """How an indicator's yearly change is measured: "diff" (points) for percentages
    and shares, "pct" (percent change, from logs) for levels that are never below
    zero (and almost always above it), "diff" for anything else."""
    u = (unit or "").lower()
    if "%" in u or "percent" in u:
        return "diff"
    return "pct" if all_positive else "diff"


def change_unit(unit: str | None, kind: str) -> str:
    if kind == "pct":
        return "% change"
    u = (unit or "").strip()
    if u in ("%", "percent", "annual %"):
        return "change in percentage points"
    if "%" in u or "percent" in u:
        return f"change in points ({u})"
    return f"change in {u}" if u else "change"


def results_dir(home: Path) -> Path:
    return Path(home) / "warehouse" / "relationships"


def latest(home: Path, build_id: str | None = None) -> dict | None:
    """The newest scan's summary (for build_id when given and present, else the newest),
    with the paths of its files; None when there is no scan yet."""
    d = results_dir(home)
    if not d.is_dir():
        return None
    metas = sorted(d.glob("*.json"))
    if build_id and (d / f"{build_id}.json").is_file():
        pick = d / f"{build_id}.json"
    elif metas:
        pick = metas[-1]
    else:
        return None
    try:
        meta = json.loads(pick.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stem = pick.stem
    meta["pairs_path"] = str(d / f"{stem}.pairs.parquet")
    meta["events_path"] = str(d / f"{stem}.events.parquet")
    meta["build_id"] = meta.get("build_id") or stem
    return meta


# ----------------------------------------------------------------------------- p-values (no scipy)
def _tiny(v: float) -> float:
    return v if abs(v) > 1e-300 else 1e-300


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes 6.4)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 / _tiny(1.0 - qab * x / qap)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 / _tiny(1.0 + aa * d)
        c = _tiny(1.0 + aa / c)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 / _tiny(1.0 + aa * d)
        c = _tiny(1.0 + aa / c)
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_pvalue(t: float, df: float) -> float:
    """Two-sided p-value of a t statistic."""
    if not math.isfinite(t) or df <= 0:
        return 1.0
    return betainc(df / 2, 0.5, df / (df + t * t))


def f_pvalue(f: float, d1: float, d2: float) -> float:
    """Upper-tail p-value of an F statistic."""
    if not math.isfinite(f) or f <= 0 or d1 <= 0 or d2 <= 0:
        return 1.0
    return betainc(d2 / 2, d1 / 2, d2 / (d2 + d1 * f))


def bh_qvalues(p: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), in the input's order."""
    n = len(p)
    if not n:
        return []
    order = sorted(range(n), key=lambda i: p[i])
    q = [1.0] * n
    running = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * n / rank)
        q[i] = min(1.0, running)
    return q
