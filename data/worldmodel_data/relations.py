"""The relationship scan: which figures move together, and which may drive which.

Run after each refresh on the new warehouse (and by `worldmodel-data scan`). It goes
through pairs of yearly indicators, country by country, and keeps the pairs whose
evidence earns at least one label (see worldmodel_contract.relations.LABELS):

  Move together     the yearly changes of the two go together across countries and
                    years. Changes, not levels: two figures that both rise over time
                    look related even when they are not. Each country's own average
                    change is taken out first.
  One comes first   X's changes one to three years earlier help predict Y's changes
                    beyond what Y's own past says (a pooled Granger test with country
                    and year effects), and the lag chart shows at which lag. For the
                    strongest pairs the same test is run country by country.
  Holds after       the same-year link survives taking out growth of GDP per person,
  income and time   the year (world-wide swings) and fixed differences between countries.

Separately, "before and after events" compares each indicator in countries after an
event (a recession, coup, election, law change...) with countries in the same income
group that had no such event in those years.

Every test's p-value uses standard errors clustered by country, and each family of
tests gets a false discovery rate correction (Benjamini-Hochberg), so with thousands
of pairs only a small, known share of what is reported should be chance.

Plain numpy; results go to <home>/warehouse/relationships/ (see the contract module).
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

from worldmodel_contract import catalogue, local
from worldmodel_contract import relations as rel

log = logging.getLogger(__name__)

FIRST_YEAR = 1960
KEEP_SCANS = 3
SHORTLIST = 400      # pairs given the country-by-country test
GRANGER_LAGS = 3
MIN_ABS_R = 0.1      # "move together" also needs a correlation at least this big
NEAR_SAME = 0.9


@dataclass
class Series:
    id: str
    name: str
    domain: str
    unit: str
    source: str
    kind: str                  # "pct" or "diff"
    level: np.ndarray          # countries x years, NaN where missing
    change: np.ndarray         # yearly change, winsorised
    two_way: np.ndarray        # change less country and year averages (own data)


@dataclass
class Panel:
    entities: list[str]
    years: list[int]
    series: dict[str, Series] = field(default_factory=dict)
    groups: dict[str, np.ndarray] = field(default_factory=dict)   # group id -> row mask
    income: np.ndarray | None = None                                # income group index per row (-1 unknown)


# ----------------------------------------------------------------------------- loading
def chosen_indicators(con: duckdb.DuckDBPyConnection, which: str, user_dir: Path | None = None) -> list[str]:
    """The indicators scanned: those switched on (the default, with the Indicators
    page's own switches), or every yearly one."""
    rows = con.execute("SELECT indicator_id, default_on, unit FROM indicators WHERE frequency = 'A'").fetchall()
    over: dict[str, bool] = {}
    if which != "all":
        path = (user_dir or local.user_dir()) / "indicators.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            over = {k: bool(v) for k, v in (data.get("enabled") or {}).items()}
        except (OSError, ValueError, AttributeError):
            over = {}
    return sorted(i for i, on, unit in rows
                  if unit != rel.YES_NO and (which == "all" or over.get(i, bool(on))))


def load(con: duckdb.DuckDBPyConnection, ids: list[str], last_year: int | None = None) -> Panel:
    last_year = last_year or date.today().year
    con.execute("CREATE OR REPLACE TEMP TABLE scan_ids (indicator_id VARCHAR)")
    con.executemany("INSERT INTO scan_ids VALUES (?)", [(i,) for i in ids])
    data = con.execute("""
        SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.value
        FROM series s
        JOIN scan_ids k ON k.indicator_id = s.indicator_id
        JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id AND r.rank = 1
        JOIN entities e ON e.entity_id = s.entity_id
        WHERE s.status = 'E' AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A'
          AND e.type = 'country' AND year(s.period_start) BETWEEN ? AND ? AND s.value IS NOT NULL""",
                       [FIRST_YEAR, last_year]).fetchall()
    meta = {r[0]: r[1:] for r in con.execute("""
        SELECT i.indicator_id, i.name, i.domain, i.unit, coalesce(r.source_id, '')
        FROM indicators i JOIN scan_ids k USING (indicator_id)
        LEFT JOIN indicator_sources r ON r.indicator_id = i.indicator_id AND r.rank = 1""").fetchall()}
    entities = sorted({d[1] for d in data})
    years = list(range(FIRST_YEAR, last_year + 1))
    ei = {e: n for n, e in enumerate(entities)}
    panel = Panel(entities, years)
    by_ind: dict[str, list] = {}
    for ind, ent, y, v in data:
        by_ind.setdefault(ind, []).append((ei[ent], y - FIRST_YEAR, v))
    for ind, pts in by_ind.items():
        lv = np.full((len(entities), len(years)), np.nan)
        rows, cols, vals = zip(*pts)
        lv[list(rows), list(cols)] = vals
        name, domain, unit, source = meta.get(ind, (ind, "", "", ""))
        finite = lv[np.isfinite(lv)]
        kind = rel.change_kind(unit, bool(finite.size) and bool((finite >= 0).all()) and float((finite > 0).mean()) >= 0.95)
        ch = _change(lv, kind)
        panel.series[ind] = Series(ind, name, domain or "", unit or "", source, kind, lv, ch, two_way(ch))
    members = con.execute("SELECT group_id, member_id FROM memberships").fetchall()
    for gid in rel.GROUPS:
        mask = np.zeros(len(entities), bool)
        for g, m in members:
            if g == gid and m in ei:
                mask[ei[m]] = True
        if mask.any():
            panel.groups[gid] = mask
    income = np.full(len(entities), -1)
    for n, gid in enumerate(("income-high", "income-upper-middle", "income-lower-middle", "income-low")):
        for g, m in members:
            if g == gid and m in ei:
                income[ei[m]] = n
    panel.income = income
    return panel


def _change(level: np.ndarray, kind: str) -> np.ndarray:
    out = np.full_like(level, np.nan)
    if kind == "pct":
        with np.errstate(invalid="ignore", divide="ignore"):
            lg = np.where(level > 0, np.log(np.where(level > 0, level, 1.0)), np.nan)
        out[:, 1:] = 100.0 * (lg[:, 1:] - lg[:, :-1])
    else:
        out[:, 1:] = level[:, 1:] - level[:, :-1]
    vals = out[np.isfinite(out)]
    if vals.size >= 50:  # a few wild years (a redenomination, a war) should not decide a correlation
        lo, hi = np.percentile(vals, [1, 99])
        out = np.where(np.isfinite(out), np.clip(out, lo, hi), np.nan)
    return out


def two_way(x: np.ndarray, mask: np.ndarray | None = None, rounds: int = 8) -> np.ndarray:
    """x less its country (row) and year (column) averages, over the cells in mask."""
    m = np.isfinite(x) if mask is None else (mask & np.isfinite(x))
    z = np.where(m, x, 0.0)
    rn = np.maximum(m.sum(1, keepdims=True), 1)
    cn = np.maximum(m.sum(0, keepdims=True), 1)
    for _ in range(rounds):
        z = np.where(m, z - z.sum(1, keepdims=True) / rn, 0.0)
        z = np.where(m, z - z.sum(0, keepdims=True) / cn, 0.0)
    return np.where(m, z, np.nan)


def _row_demean(x: np.ndarray, m: np.ndarray) -> np.ndarray:
    z = np.where(m, x, 0.0)
    n = np.maximum(m.sum(1, keepdims=True), 1)
    return np.where(m, z - z.sum(1, keepdims=True) / n, 0.0)


# ----------------------------------------------------------------------------- statistics
def cluster_ols(y: np.ndarray, X: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """OLS coefficients and their covariance clustered by group (rows of X are observations)."""
    xtx = X.T @ X
    try:
        inv = np.linalg.inv(xtx)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(xtx)
    b = inv @ (X.T @ y)
    u = y - X @ b
    uniq, gi = np.unique(groups, return_inverse=True)
    s = np.zeros((len(uniq), X.shape[1]))
    np.add.at(s, gi, X * u[:, None])
    g = len(uniq)
    n, k = X.shape
    adj = (g / max(g - 1, 1)) * ((n - 1) / max(n - k, 1))
    return b, adj * inv @ (s.T @ s) @ inv, g


def corr_cluster(x: np.ndarray, y: np.ndarray, rows: np.ndarray) -> tuple[float, float, int]:
    """Correlation of two already centred vectors, with a cluster-robust p-value."""
    sx, sy = math.sqrt(float(x @ x)), math.sqrt(float(y @ y))
    if sx == 0 or sy == 0:
        return 0.0, 1.0, 0
    xs, ys = x / sx, y / sy
    r = float(xs @ ys)
    u = ys - r * xs
    uniq, gi = np.unique(rows, return_inverse=True)
    s = np.zeros(len(uniq))
    np.add.at(s, gi, xs * u)
    g = len(uniq)
    var = float(s @ s) * g / max(g - 1, 1)
    t = r / math.sqrt(var) if var > 0 else math.inf
    return r, rel.t_pvalue(t, g - 1), g


def wald_p(b: np.ndarray, v: np.ndarray, idx: list[int], g: int) -> float:
    bb, vv = b[idx], v[np.ix_(idx, idx)]
    try:
        w = float(bb @ np.linalg.solve(vv, bb))
    except np.linalg.LinAlgError:
        return 1.0
    return rel.f_pvalue(w / len(idx), len(idx), max(g - 1, 1))


def _lag(a: np.ndarray, k: int) -> np.ndarray:
    """a shifted k years later (value at t is a[t - k])."""
    out = np.full_like(a, np.nan)
    if k > 0:
        out[:, k:] = a[:, :-k]
    elif k < 0:
        out[:, :k] = a[:, -k:]
    else:
        out[:] = a
    return out


def granger(x: Series, y: Series, ok_rows: np.ndarray) -> tuple[float, int]:
    """Do X's past changes help predict Y's, beyond Y's own past? Pooled, with country
    and year effects taken out; p-value of the X lags together, and the rows used."""
    yt = y.two_way
    cols = [_lag(yt, 1), _lag(yt, 2)] + [_lag(x.two_way, k) for k in range(1, GRANGER_LAGS + 1)]
    m = np.isfinite(yt) & ok_rows[:, None]
    for c in cols:
        m &= np.isfinite(c)
    n = int(m.sum())
    if n < 60:
        return 1.0, n
    X = np.column_stack([c[m] for c in cols])
    rows = np.nonzero(m)[0]
    b, v, g = cluster_ols(yt[m], X, rows)
    return wald_p(b, v, list(range(2, 2 + GRANGER_LAGS)), g), n


def granger_by_country(x: Series, y: Series, ok_rows: np.ndarray, min_obs: int = 15) -> tuple[int, int]:
    """The same test in each country on its own: (countries where X's past helps at the
    10% level, countries tested). By chance alone about 1 in 10 would pass."""
    passed = tested = 0
    for i in np.nonzero(ok_rows)[0]:
        yy = y.change[i]
        cols = [_lag(yy[None, :], 1)[0]] + [_lag(x.change[i][None, :], k)[0] for k in range(1, GRANGER_LAGS + 1)]
        m = np.isfinite(yy)
        for c in cols:
            m &= np.isfinite(c)
        n = int(m.sum())
        if n < min_obs:
            continue
        one = np.ones(n)
        full = np.column_stack([one] + [c[m] for c in cols])
        small = np.column_stack([one, cols[0][m]])
        target = yy[m]
        ssr_f = float(np.sum((target - full @ np.linalg.lstsq(full, target, rcond=None)[0]) ** 2))
        ssr_r = float(np.sum((target - small @ np.linalg.lstsq(small, target, rcond=None)[0]) ** 2))
        d2 = n - full.shape[1]
        if d2 <= 0 or ssr_f <= 0:
            continue
        tested += 1
        f = ((ssr_r - ssr_f) / GRANGER_LAGS) / (ssr_f / d2)
        passed += rel.f_pvalue(f, GRANGER_LAGS, d2) < 0.10
    return passed, tested


def lag_profile(x: Series, y: Series, ok_rows: np.ndarray) -> list[float | None]:
    """Correlation of X's change k years earlier with Y's change, k = -MAX_LAG..MAX_LAG
    (positive k: X comes first), country and year effects taken out."""
    out: list[float | None] = []
    for k in range(-rel.MAX_LAG, rel.MAX_LAG + 1):
        a = _lag(x.two_way, k)
        m = np.isfinite(a) & np.isfinite(y.two_way) & ok_rows[:, None]
        if m.sum() < 50:
            out.append(None)
            continue
        av, bv = a[m] - a[m].mean(), y.two_way[m] - y.two_way[m].mean()
        d = math.sqrt(float(av @ av) * float(bv @ bv))
        out.append(round(float(av @ bv) / d, 4) if d else None)
    return out


# ----------------------------------------------------------------------------- one pair
def pair(x: Series, y: Series, panel: Panel, min_countries: int, min_years: int, control: Series | None) -> dict | None:
    both = np.isfinite(x.change) & np.isfinite(y.change)
    per = both.sum(1)
    ok = per >= min_years
    if ok.sum() < min_countries:
        return None
    m = both & ok[:, None]
    rows = np.nonzero(m)[0]
    cx, cy = _row_demean(x.change, m)[m], _row_demean(y.change, m)[m]
    r, p_together, g = corr_cluster(cx, cy, rows)
    tx, ty = two_way(x.change, m), two_way(y.change, m)
    r_tw, _, _ = corr_cluster(tx[m], ty[m], rows)
    # holds after income and time
    use_control = control is not None and control.id not in (x.id, y.id) and {x.id, y.id}.isdisjoint({"gdp_growth"})
    mc = m & np.isfinite(control.level) if use_control else m  # the control is a growth rate already
    beta = p_holds = slope = None
    if mc.sum() >= 60:
        rows_c = np.nonzero(mc)[0]
        ux, uy = two_way(x.change, mc)[mc], two_way(y.change, mc)[mc]
        sx, sy = float(np.std(ux)), float(np.std(uy))
        if sx > 0 and sy > 0:
            cols = [ux / sx]
            if use_control:
                uc = two_way(control.level, mc)[mc]
                sc = float(np.std(uc))
                if sc > 0:
                    cols.append(uc / sc)
            b, v, gg = cluster_ols(uy / sy, np.column_stack(cols), rows_c)
            beta = float(b[0])
            se = math.sqrt(max(float(v[0, 0]), 0.0))
            p_holds = rel.t_pvalue(beta / se, gg - 1) if se > 0 else 1.0
            slope = beta * sy / sx
    p_xy, n_xy = granger(x, y, ok)
    p_yx, _ = granger(y, x, ok)
    yrs = np.nonzero(m.any(0))[0]
    groups = {}
    for gid, gm in panel.groups.items():
        sel = gm[rows]
        if len(np.unique(rows[sel])) >= 8:
            gr, gp, gn = corr_cluster(cx[sel], cy[sel], rows[sel])
            groups[gid] = [round(gr, 3), gn, round(gp, 5)]
    return {
        "x": x.id, "y": y.id, "n_obs": int(m.sum()), "n_countries": g,
        "year_from": panel.years[int(yrs[0])], "year_to": panel.years[int(yrs[-1])],
        "r": round(r, 4), "r_two_way": round(r_tw, 4), "p_together": p_together,
        "beta": None if beta is None else round(beta, 4), "slope": None if slope is None else float(f"{slope:.4g}"),
        "p_holds": p_holds, "control_used": bool(use_control),
        "p_x_first": p_xy, "p_y_first": p_yx, "lags": lag_profile(x, y, ok),
        "groups": json.dumps(groups), "_ok": ok,
    }


# ----------------------------------------------------------------------------- the scan
def scan(warehouse: Path, home: Path, build_id: str | None = None, settings: dict | None = None,
         log_line=print) -> dict:
    """Scan the warehouse and write the results; returns the summary written."""
    s = settings or local.load_settings(home)
    started = time.monotonic()
    budget = float(s["relations_max_minutes"]) * 60
    fdr = float(s["relations_fdr"])
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        build_id = build_id or dict(con.execute("SELECT key, value FROM meta").fetchall()).get("build_id") or warehouse.stem
        ids = chosen_indicators(con, s["relations_indicators"], home / "user" if (home / "user").is_dir() else None)
        if rel.CONTROL not in ids:
            ids.append(rel.CONTROL)
        panel = load(con, ids)
        events = con.execute("""
            SELECT ev.kind, ev.entity_id, year(ev.start_date) FROM events ev JOIN entities e USING (entity_id)
            WHERE e.type = 'country' AND ev.start_date IS NOT NULL""").fetchall()
    finally:
        con.close()
    control = panel.series.get(rel.CONTROL)
    usable = [sid for sid, sr in panel.series.items()
              if (np.isfinite(sr.change).sum(1) >= s["relations_min_years"]).sum() >= s["relations_min_countries"]]
    usable.sort()
    drivers = {(l["from"], l["to"]) for l in catalogue.driver_graph().get("links", [])}
    total = len(usable) * (len(usable) - 1) // 2
    log_line(f"Relationship scan: {len(usable)} indicators with enough data, {total:,} pairs to test")
    results, tested, thin, partial = [], 0, 0, False
    for a in range(len(usable)):
        for b in range(a + 1, len(usable)):
            if time.monotonic() - started > budget:
                partial = True
                break
            tested += 1
            out = pair(panel.series[usable[a]], panel.series[usable[b]], panel,
                       s["relations_min_countries"], s["relations_min_years"], control)
            if out is None:
                thin += 1
            else:
                results.append(out)
        if partial:
            break
    _label(results, panel, drivers, fdr)
    # country-by-country lead test for the strongest pairs that earned "comes first"
    shortlist = sorted((r for r in results if r["first"]), key=lambda r: -abs(r["r_two_way"]))[:SHORTLIST]
    for r in shortlist:
        if time.monotonic() - started > budget * 1.1:
            partial = True
            break
        xs, ys = panel.series[r["x"]], panel.series[r["y"]]
        if r["first"] in ("x", "both"):
            r["countries_x_first"], r["countries_tested"] = granger_by_country(xs, ys, r["_ok"])
        if r["first"] in ("y", "both"):
            r["countries_y_first"], r["countries_tested"] = granger_by_country(ys, xs, r["_ok"])
    event_rows = event_study(panel, events, [i for i in usable], fdr)
    seconds = round(time.monotonic() - started, 1)
    kept = [r for r in results if r["labels"]]
    summary = {
        "build_id": build_id, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": seconds, "partial": partial, "indicators": len(usable), "indicators_chosen": len(ids),
        "pairs_possible": total, "pairs_tested": tested, "pairs_thin": thin, "pairs_scored": len(results),
        "pairs_kept": len(kept), "label_counts": {k: sum(k in r["labels"] for r in kept) for k in rel.LABELS},
        "events_tested": len(event_rows),
        "events_kept": sum(e["significant"] and not e["built_in"] and not e["diverging_before"] for e in event_rows),
        "settings": {k: s[k] for k in ("relations_indicators", "relations_min_countries", "relations_min_years",
                                       "relations_max_minutes", "relations_fdr")},
        "names": {sid: {"name": sr.name, "domain": sr.domain, "unit": sr.unit, "kind": sr.kind, "source": sr.source}
                  for sid, sr in panel.series.items()},
    }
    write(home, build_id, kept, event_rows, summary)
    log_line(f"Relationship scan: {len(kept):,} pairs kept of {tested:,} tested "
             f"({', '.join(f'{n} {rel.LABELS[k].lower()}' for k, n in summary['label_counts'].items())}); "
             f"{summary['events_kept']} event links; {seconds:.0f} s" + (" (stopped at the time limit)" if partial else ""))
    return summary


def _label(results: list[dict], panel: Panel, drivers: set, fdr: float) -> None:
    q_t = rel.bh_qvalues([r["p_together"] for r in results])
    q_h = rel.bh_qvalues([r["p_holds"] if r["p_holds"] is not None else 1.0 for r in results])
    q_g = rel.bh_qvalues([r["p_x_first"] for r in results] + [r["p_y_first"] for r in results])
    n = len(results)
    for i, r in enumerate(results):
        r["q_together"], r["q_holds"] = q_t[i], q_h[i]
        r["q_x_first"], r["q_y_first"] = q_g[i], q_g[n + i]
        labels = []
        if q_t[i] < fdr and abs(r["r"]) >= MIN_ABS_R:
            labels.append("together")
        lags = r["lags"]
        lead_x = max((abs(v) for v in lags[rel.MAX_LAG + 1:] if v is not None), default=0)
        lead_y = max((abs(v) for v in lags[:rel.MAX_LAG] if v is not None), default=0)
        fx, fy = q_g[i] < fdr and lead_x >= 0.05, q_g[n + i] < fdr and lead_y >= 0.05
        r["first"] = "both" if fx and fy else "x" if fx else "y" if fy else None
        if r["first"]:
            labels.append("first")
        if r["beta"] is not None and q_h[i] < fdr and abs(r["beta"]) >= MIN_ABS_R / 2 and math.copysign(1, r["beta"]) == math.copysign(1, r["r"]):
            labels.append("holds")
        r["labels"] = labels
        side = lags[rel.MAX_LAG + 1:] if r["first"] in ("x", "both") else lags[:rel.MAX_LAG][::-1] if r["first"] == "y" else []
        best = max(((abs(v), k + 1) for k, v in enumerate(side) if v is not None), default=None)
        r["best_lag"] = best[1] if best else None
        r["in_drivers"] = (r["x"], r["y"]) in drivers or (r["y"], r["x"]) in drivers
        r["note"] = common_causes(r, panel)
        x, y = panel.series[r["x"]], panel.series[r["y"]]
        r["near_same"] = abs(r["r"]) >= NEAR_SAME
        r["same_source"] = bool(x.source) and x.source == y.source and x.domain == y.domain
        r["score"] = round(len(labels) + abs(r["r_two_way"]) - (2 if r["near_same"] else 0) - (0.5 if r["same_source"] else 0), 4)


def common_causes(r: dict, panel: Panel) -> str:
    """A plain note on what else could explain the link."""
    x, y = panel.series[r["x"]], panel.series[r["y"]]
    notes = []
    if abs(r["r"]) >= NEAR_SAME:
        notes.append("Nearly the same figure: one may be worked out from the other.")
    if abs(r["r"]) >= 0.2 and abs(r["r_two_way"]) < 0.5 * abs(r["r"]):
        notes.append("Much of it is world-wide swings that hit every country in the same years (such as 2009 and 2020).")
    if "together" in r["labels"] and "holds" not in r["labels"] and r["control_used"]:
        notes.append("Both follow the economy: the link fades once growth of GDP per person and the year are allowed for.")
    if x.source and x.source == y.source and x.domain == y.domain:
        notes.append("Both come from the same source and topic, so they may share inputs or definitions.")
    if not notes:
        notes.append("Something else could drive both; check the lag chart and which countries carry the link.")
    return " ".join(notes)


# ----------------------------------------------------------------------------- before and after events
def event_study(panel: Panel, events: list[tuple], ids: list[str], fdr: float, min_events: int = 10) -> list[dict]:
    """For each event kind and indicator: the change in the indicator from the year
    before the event to h years after (h = -3..EVENT_YEARS), less the same change in
    countries of the same income group with no such event in those years."""
    ei = {e: n for n, e in enumerate(panel.entities)}
    ny = len(panel.years)
    hs = list(range(-3, rel.EVENT_YEARS + 1))
    out: list[dict] = []
    for kind in rel.EVENT_KINDS:
        hits = np.zeros((len(panel.entities), ny), bool)
        for k, ent, y in events:
            if k == kind and ent in ei and FIRST_YEAR <= y < FIRST_YEAR + ny:
                hits[ei[ent], y - FIRST_YEAR] = True
        if hits.sum() < min_events:
            continue
        # no event of this kind from 3 years before to EVENT_YEARS after
        quiet = _window_none(hits, 3, rel.EVENT_YEARS)
        # first event in a run only (a 3-year recession is one event)
        starts = hits & ~_shift_bool(hits, 1)
        ev_rows, ev_cols = np.nonzero(starts)
        for sid in ids:
            sr = panel.series[sid]
            lv = sr.level
            base = _lag(lv, 1)  # level in the year before, at column e
            path, ses, ns = [], [], []
            for h in hs:
                ahead = _lag(lv, -h)
                if sr.kind == "pct":
                    with np.errstate(invalid="ignore", divide="ignore"):
                        o = 100 * (np.log(np.where(ahead > 0, ahead, np.nan)) - np.log(np.where(base > 0, base, np.nan)))
                else:
                    o = ahead - base
                if h == -1:
                    path.append(0.0), ses.append(0.0), ns.append(len(ev_rows))
                    continue
                diffs = []
                ctrl = np.where(quiet, o, np.nan)
                for rr, cc in zip(ev_rows, ev_cols):
                    t = o[rr, cc]
                    if not np.isfinite(t):
                        continue
                    grp = panel.income[rr] if panel.income is not None else -1
                    pool = ctrl[:, cc] if grp < 0 else ctrl[panel.income == grp, cc]
                    pool = pool[np.isfinite(pool)]
                    if len(pool) >= 5:
                        diffs.append(t - float(pool.mean()))
                n = len(diffs)
                ns.append(n)
                if n >= 2:
                    d = np.array(diffs)
                    path.append(round(float(d.mean()), 4))
                    ses.append(round(float(d.std(ddof=1) / math.sqrt(n)), 4))
                else:
                    path.append(None), ses.append(None)
            k3 = hs.index(3)
            n3 = ns[k3]
            if n3 < min_events or path[k3] is None:
                continue
            t = path[k3] / ses[k3] if ses[k3] else 0.0
            out.append({"kind": kind, "indicator_id": sid, "n_events": int(n3), "h": hs, "effect": path, "se": ses,
                        "n": [int(v) for v in ns], "effect_3": path[k3], "p": rel.t_pvalue(t, n3 - 1),
                        "built_in": rel.built_in(kind, sid),
                        "diverging_before": path[0] is not None and abs(path[0]) >= 0.5 * abs(path[k3]),
                        "pre_trend": path[0], "unit": rel.change_unit(sr.unit, sr.kind)})
    q = rel.bh_qvalues([e["p"] for e in out])
    for e, qq in zip(out, q):
        e["q"] = qq
        e["significant"] = qq < fdr
    return out


def _window_none(hits: np.ndarray, before: int, after: int) -> np.ndarray:
    """True at (country, year) when the country has no hit from `before` years earlier to `after` years later."""
    c = np.concatenate([np.zeros((hits.shape[0], 1)), np.cumsum(hits, 1)], 1)
    ny = hits.shape[1]
    lo = np.clip(np.arange(ny) - before, 0, ny)
    hi = np.clip(np.arange(ny) + after + 1, 0, ny)
    return (c[:, hi] - c[:, lo]) == 0


def _shift_bool(a: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros_like(a)
    out[:, k:] = a[:, :-k]
    return out


# ----------------------------------------------------------------------------- files
PAIR_COLUMNS = [
    ("x", "VARCHAR"), ("y", "VARCHAR"), ("labels", "VARCHAR[]"), ("score", "DOUBLE"), ("n_obs", "INTEGER"),
    ("n_countries", "INTEGER"), ("year_from", "INTEGER"), ("year_to", "INTEGER"), ("r", "DOUBLE"),
    ("r_two_way", "DOUBLE"), ("p_together", "DOUBLE"), ("q_together", "DOUBLE"), ("beta", "DOUBLE"),
    ("slope", "DOUBLE"), ("p_holds", "DOUBLE"), ("q_holds", "DOUBLE"), ("control_used", "BOOLEAN"),
    ("first", "VARCHAR"), ("best_lag", "INTEGER"), ("p_x_first", "DOUBLE"), ("q_x_first", "DOUBLE"),
    ("p_y_first", "DOUBLE"), ("q_y_first", "DOUBLE"), ("countries_x_first", "INTEGER"),
    ("countries_y_first", "INTEGER"), ("countries_tested", "INTEGER"), ("lags", "DOUBLE[]"),
    ("groups", "VARCHAR"), ("in_drivers", "BOOLEAN"), ("near_same", "BOOLEAN"), ("same_source", "BOOLEAN"), ("note", "VARCHAR"),
]
EVENT_COLUMNS = [
    ("kind", "VARCHAR"), ("indicator_id", "VARCHAR"), ("n_events", "INTEGER"), ("h", "INTEGER[]"),
    ("effect", "DOUBLE[]"), ("se", "DOUBLE[]"), ("n", "INTEGER[]"), ("effect_3", "DOUBLE"), ("p", "DOUBLE"),
    ("q", "DOUBLE"), ("significant", "BOOLEAN"), ("built_in", "BOOLEAN"), ("diverging_before", "BOOLEAN"), ("pre_trend", "DOUBLE"), ("unit", "VARCHAR"),
]


def write(home: Path, build_id: str, pairs: list[dict], event_rows: list[dict], summary: dict) -> Path:
    d = rel.results_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        for table, cols, rows, suffix in (("pairs", PAIR_COLUMNS, pairs, "pairs"), ("events", EVENT_COLUMNS, event_rows, "events")):
            con.execute(f"CREATE TABLE {table} ({', '.join(f'{c} {t}' for c, t in cols)})")
            if rows:
                con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
                                [tuple(_clean(r.get(c)) for c, _ in cols) for r in rows])
            tmp = d / f"{build_id}.{suffix}.parquet.tmp"
            con.execute(f"COPY {table} TO '{tmp.as_posix()}' (FORMAT parquet)")
            tmp.replace(d / f"{build_id}.{suffix}.parquet")
    finally:
        con.close()
    meta = d / f"{build_id}.json"
    meta.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    _prune(d)
    return meta


def _clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _prune(d: Path) -> None:
    metas = sorted(d.glob("*.json"))
    for old in metas[:-KEEP_SCANS]:
        for f in d.glob(f"{old.stem}.*"):
            f.unlink(missing_ok=True)
