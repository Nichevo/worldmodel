"""Big cycles: the Long history page's Big cycles tab and the country page's debt cycle card.

* Rise and decline: each power's eight-factor index, split into rise, top and decline where the
  index turns, with big wars (history_events) and financial crises (crisis_history) marked.
* Stage over time: the same rules as today's placing (longhistory.place), run on each decade's figures.
* Long-term debt cycle: government debt since 1800 (IMF historical public debt, then the WEO),
  crises, big wars, and real interest rates where known.
* Short-term debt cycle: a clock with six phases placed by simple rules on growth, the OECD leading
  indicator, the central bank rate, inflation and credit, with the reasons.

A copy of Ray Dalio's ideas rebuilt from free data: a reading to argue with, not a forecast.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Callable

from worldmodel_contract import catalogue

from worldmodel_api import longhistory
from worldmodel_api.episodes import annual, sub_annual

Q = Callable[[str, list], list[dict]]

TOP_SHARE = 0.9  # the top: the years the index is within 90% of its peak
PHASES = ["Early recovery", "Expansion", "Late expansion", "Slowdown", "Recession", "Easing"]
PHASE_ABOUT = {
    "Early recovery": "Output picks up from a low; interest rates are low or still falling.",
    "Expansion": "Steady growth; inflation and rates moderate.",
    "Late expansion": "Growth strong, but inflation, credit or rates are rising: borrowing runs ahead of income.",
    "Slowdown": "Rates have gone up and growth and the leading indicator are turning down.",
    "Recession": "Output falling.",
    "Easing": "Rates being cut to revive weak growth.",
}
CRISIS_NAMES = {"banking": "banking crisis", "systemic": "systemic banking crisis", "default_external": "default on foreign debt",
                "default_domestic": "default on domestic debt", "currency": "currency crash", "inflation": "inflation crisis",
                "stock_crash": "share market crash"}
NOTE = ("Rebuilt from free data: a copy of Ray Dalio's ideas on big cycles and debt cycles, not his own figures "
        "or placings. Something to argue with, not a forecast.")


def _names() -> dict[str, str]:
    return {e.entity_id: e.short_name or e.name for e in catalogue.entities().values()}


# ----------------------------------------------------------------------------- shared pieces
def crisis_years(q: Q, entities: list[str], start: int = 1500) -> dict[str, list[dict]]:
    """Reinhart and Rogoff's crisis years per country, merged into spells per kind."""
    ids = [f"crisis_{k}" for k in CRISIS_NAMES]
    try:
        got = q("""SELECT entity_id AS e, substr(indicator_id, 8) AS k, year(period_start) AS y FROM series
                   WHERE source_id = 'crisis_history' AND indicator_id IN (SELECT unnest(?)) AND value > 0
                     AND entity_id IN (SELECT unnest(?)) AND year(period_start) >= ? ORDER BY 1, 2, 3""", [ids, entities, start])
    except Exception:  # noqa: BLE001 - nothing loaded yet
        return {}
    out: dict[str, list[dict]] = defaultdict(list)
    for r in got:
        spells = out[r["e"]]
        last = next((s for s in reversed(spells) if s["kind"] == r["k"]), None)
        if last and r["y"] - last["to"] <= 1:
            last["to"] = r["y"]
        else:
            spells.append({"kind": r["k"], "name": CRISIS_NAMES.get(r["k"], r["k"]), "from": r["y"], "to": r["y"]})
    for spells in out.values():
        spells.sort(key=lambda s: s["from"])
    return out


def wars(q: Q, entities: list[str], start: int = 1500, min_links: int = 40, most: int = 12) -> dict[str, list[dict]]:
    """The best-known wars each country fought (by how many Wikipedias have an article)."""
    out: dict[str, list[dict]] = {}
    for ent in entities:
        try:
            got = longhistory.events(q, start, None, ["war"], min_links, entity=ent, limit=most)
        except Exception:  # noqa: BLE001 - no history_events table
            return {}
        out[ent] = [{"title": w["title"], "from": w["year"], "to": w["end_year"] or w["year"]} for w in got if w["year"] is not None]
    return out


# ----------------------------------------------------------------------------- rise and decline
def phases(points: list[list]) -> dict:
    """Rise, top and decline from one index line: the top is the run of years around the peak
    within 90% of it; before is the rise and after the decline (none if it is still at the top)."""
    pts = [(y, v) for y, v in points if v is not None]
    if len(pts) < 3:
        return {"peak": None, "phases": []}
    i = max(range(len(pts)), key=lambda k: pts[k][1])
    py, pv = pts[i]
    a = i
    while a > 0 and pts[a - 1][1] >= TOP_SHARE * pv:
        a -= 1
    b = i
    while b < len(pts) - 1 and pts[b + 1][1] >= TOP_SHARE * pv:
        b += 1
    out = []
    if a > 0:
        out.append({"phase": "rise", "from": pts[0][0], "to": pts[a][0]})
    out.append({"phase": "top", "from": pts[a][0], "to": pts[b][0]})
    if b < len(pts) - 1:
        out.append({"phase": "decline", "from": pts[b][0], "to": pts[-1][0]})
    now = "decline" if b < len(pts) - 1 else "top"
    return {"peak": [py, round(pv, 4)], "phases": out, "now": now}


def arcs(q: Q, start: int = 1500) -> dict:
    f = longhistory.factors(q, start, 10)
    ents = [line["entity"] for line in f["index"]]
    crises = crisis_years(q, ents, start)
    fought = wars(q, ents, start)
    lines = []
    for line in f["index"]:
        ph = phases(line["points"])
        lines.append({**line, **ph, "crises": crises.get(line["entity"], []), "wars": fought.get(line["entity"], [])})
    return {"lines": lines, "note": f.get("note") or NOTE,
            "how": ("The line is the eight-factor index (each country's share of the ten powers' total, averaged over the "
                    "factors it has). The top is the run of years within 90% of the peak; before it the rise, after it "
                    "the decline. Ticks mark crises (Reinhart and Rogoff) and the best-known wars (Wikidata).")}


# ----------------------------------------------------------------------------- stage over time
def figures_at(series: dict[str, dict[int, float]], year: int) -> dict[str, dict]:
    """The figures longhistory.place() reads, as they stood at the end of a year: the latest value
    within five years, the five-year average and the value ten years before."""
    figs = {}
    for key, d in series.items():
        ys = sorted(y for y in d if y <= year)
        if not ys or year - ys[-1] > 5:
            continue
        last = ys[-1]
        five = [d[y] for y in ys[-5:]]
        figs[key] = {"latest": d[last], "year": last, "avg5": sum(five) / len(five), "ten_ago": d.get(last - 10)}
    return figs


def stages_over_time(q: Q, entities: list[str], start: int = 1950, this_year: int | None = None) -> dict:
    this_year = this_year or date.today().year
    h = catalogue.history()["cycle"]
    names = _names()
    inds = list(longhistory.CYCLE_INDICATORS.values())
    data = annual(q, entities, inds, start - 15, this_year)
    decades = list(range(start, this_year, 10))
    if not decades or decades[-1] != this_year:
        decades.append(this_year)
    out = []
    for ent in entities:
        series = {k: data.get((ent, ind), {}) for k, ind in longhistory.CYCLE_INDICATORS.items()}
        began = h["order_began"].get(ent)
        cells = []
        for y in decades:
            figs = figures_at(series, y)
            if not figs:
                cells.append({"year": y, "stage": None, "reasons": ["No figures for this decade."]})
                continue
            age = (y - began) if began and y >= began else None
            stage, reasons = longhistory.place(figs, age)
            cells.append({"year": y, "stage": stage, "reasons": reasons})
        out.append({"entity": ent, "name": names.get(ent, ent), "cells": cells})
    return {"years": decades, "stages": h["stages"], "countries": out,
            "how": ("The same rules as today's placing on the Cycle tab, run on the figures as they stood at each decade: "
                    "heavy and rising government debt, slow growth, high inflation and a wide income gap push towards "
                    "the later stages; a young order sits early. Before about 1990 many countries lack some of the figures.")}


# ----------------------------------------------------------------------------- long-term debt cycle
def debt_cycle(q: Q, entity: str, this_year: int | None = None) -> dict:
    this_year = this_year or date.today().year
    names = _names()
    data = annual(q, [entity], ["govt_debt_gdp_long", "govt_debt_gdp", "real_interest_rate", "inflation", "private_credit_gdp"],
                  1700, this_year)
    long_ = data.get((entity, "govt_debt_gdp_long"), {})
    weo = data.get((entity, "govt_debt_gdp"), {})
    debt = dict(long_)
    for y, v in weo.items():
        if y not in debt:
            debt[y] = v
    since = min(debt) if debt else None
    crises = crisis_years(q, [entity], 1700).get(entity, [])
    fought = wars(q, [entity], 1700, min_links=30, most=15).get(entity, [])
    pts = lambda d: [[y, round(v, 1)] for y, v in sorted(d.items())]  # noqa: E731
    big = sorted(debt.items(), key=lambda kv: -kv[1])[:1]
    return {"entity": entity, "name": names.get(entity, entity), "since": since,
            "debt": pts(debt), "debt_from_long": bool(long_),
            "real_rate": pts(data.get((entity, "real_interest_rate"), {})),
            "inflation": pts({y: v for y, v in data.get((entity, "inflation"), {}).items()}),
            "private_credit": pts(data.get((entity, "private_credit_gdp"), {})),
            "crises": crises, "wars": fought,
            "peak": {"year": big[0][0], "value": round(big[0][1])} if big else None,
            "latest": {"year": max(debt), "value": round(debt[max(debt)], 1)} if debt else None,
            "how": ("Government debt as a share of GDP: the IMF's historical public debt figures (back to 1800 where "
                    "records allow), then the IMF World Economic Outlook for years they do not cover. Debt usually rises "
                    "in wars and depressions and is worked off by growth, inflation or default. Shaded: the best-known "
                    "wars; ticks: crises (Reinhart and Rogoff)."), "note": NOTE}


# ----------------------------------------------------------------------------- short-term debt cycle
def clock_place(f: dict) -> tuple[str | None, list[str]]:
    """The phase from the latest figures: growth (g, and g_prev a year before), the quarter's growth
    (q_last, q_prev), the leading indicator's 6-month change (cli_chg), the rate and its 12-month
    change (rate, rate_chg), inflation (infl) and the 3-year rise in private credit (credit_chg)."""
    reasons: list[str] = []
    g, gp = f.get("g"), f.get("g_prev")
    ql, qp = f.get("q_last"), f.get("q_prev")
    cli, rate, rchg, infl, cr = f.get("cli_chg"), f.get("rate"), f.get("rate_chg"), f.get("infl"), f.get("credit_chg")
    if g is None and ql is None:
        return None, ["No recent growth figures."]
    if g is not None:
        reasons.append(f"Growth {g:+.1f}% over the latest year" + (f" ({gp:+.1f}% the year before)." if gp is not None else "."))
    if ql is not None:
        reasons.append(f"Latest quarter {ql:+.1f}%" + (f", the one before {qp:+.1f}%." if qp is not None else "."))
    if rate is not None and rchg is not None:
        reasons.append(f"Central bank rate {rate:.2f}%, {'up' if rchg > 0 else 'down' if rchg < 0 else 'unchanged'}"
                       f"{f' {abs(rchg):.2f} points' if rchg else ''} on a year ago.")
    if cli is not None:
        reasons.append(f"OECD leading indicator {'rising' if cli > 0.1 else 'falling' if cli < -0.1 else 'flat'} over six months ({cli:+.1f}).")
    if infl is not None:
        reasons.append(f"Inflation {infl:.1f}%.")
    if cr is not None:
        reasons.append(f"Private credit {'up' if cr >= 0 else 'down'} {abs(cr):.0f} points of GDP over three years.")
    falling = (ql is not None and qp is not None and ql < 0 and qp < 0) or (g is not None and g < 0)
    weak = (g is not None and g < 1.5) or (ql is not None and ql < 0.3)
    if falling:
        return "Recession", reasons
    if rchg is not None and rchg <= -0.5 and (weak or (cli is not None and cli < 0)):
        if g is not None and gp is not None and g > gp and gp < 1:
            return "Early recovery", reasons
        return "Easing", reasons
    if g is not None and gp is not None and gp < 1 and g > gp:
        return "Early recovery", reasons
    if rchg is not None and rchg >= 0 and (rate or 0) >= 3 and ((cli is not None and cli < -0.1) or (g is not None and gp is not None and g < gp - 0.5)):
        return "Slowdown", reasons
    hot = (infl is not None and infl > 3.5) or (cr is not None and cr >= 8) or (rchg is not None and rchg >= 0.75)
    if not weak and hot:
        return "Late expansion", reasons
    if not weak:
        return "Expansion", reasons
    if cli is not None and cli < -0.1:
        return "Slowdown", reasons
    return "Expansion" if g is not None and g > 0.5 else "Slowdown", reasons


def clock_figures(q: Q, entity: str, this_year: int) -> dict:
    a = annual(q, [entity], ["gdp_growth", "inflation", "private_credit_gdp"], this_year - 8, this_year)
    gq = sub_annual(q, [entity], "gdp_growth_q", this_year - 3, this_year).get(entity, [])
    rate = sub_annual(q, [entity], "bis_policy_rate_m", this_year - 3, this_year).get(entity, [])
    cli = sub_annual(q, [entity], "oecd_cli", this_year - 2, this_year).get(entity, [])
    f: dict = {}
    g = a.get((entity, "gdp_growth"), {})
    if len(gq) >= 4:
        f["q_last"], f["q_prev"] = gq[-1][1], gq[-2][1]
        f["g"] = sum(v for _, v in gq[-4:])
        if len(gq) >= 8:
            f["g_prev"] = sum(v for _, v in gq[-8:-4])
        f["as_of"] = gq[-1][0]
    if "g" not in f and g:
        ly = max(g)
        f["g"], f["g_prev"], f["as_of"] = g[ly], g.get(ly - 1), ly
    elif "g_prev" not in f and g:
        f["g_prev"] = g.get(max(g) - 1) if len(g) > 1 else None
    infl = a.get((entity, "inflation"), {})
    if infl:
        f["infl"] = infl[max(infl)]
    cr = a.get((entity, "private_credit_gdp"), {})
    if cr and (max(cr) - 3) in cr:
        f["credit_chg"] = cr[max(cr)] - cr[max(cr) - 3]
    if len(rate) >= 13:
        f["rate"], f["rate_chg"] = rate[-1][1], rate[-1][1] - rate[-13][1]
    if len(cli) >= 7:
        f["cli_chg"] = cli[-1][1] - cli[-7][1]
    return f


def clock(q: Q, entities: list[str], this_year: int | None = None) -> dict:
    this_year = this_year or date.today().year
    names = _names()
    out = []
    for ent in entities:
        f = clock_figures(q, ent, this_year)
        phase, reasons = clock_place(f)
        out.append({"entity": ent, "name": names.get(ent, ent), "phase": phase,
                    "angle": None if phase is None else PHASES.index(phase) * 60, "reasons": reasons,
                    "as_of": f.get("as_of"), "figures": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in f.items()}})
    return {"phases": [{"name": p, "about": PHASE_ABOUT[p]} for p in PHASES], "countries": out,
            "how": ("Placed by simple rules: falling output is recession; rates cut by half a point or more with weak growth "
                    "is easing (early recovery once growth picks up from below 1%); rates up and growth or the leading "
                    "indicator turning down is a slowdown; good growth with inflation over 3.5%, credit up 8 points of GDP "
                    "in three years or rates rising is late expansion; otherwise expansion."), "note": NOTE}


def short_cycle(q: Q, entity: str, start: int = 1960, this_year: int | None = None) -> dict:
    """Credit, the central bank rate, growth and recessions since 1960 for one country."""
    this_year = this_year or date.today().year
    a = annual(q, [entity], ["gdp_growth", "private_credit_gdp"], start, this_year)
    rate = sub_annual(q, [entity], "bis_policy_rate_m", start, this_year).get(entity, [])
    try:
        rec = q("""SELECT start_date, end_date FROM events WHERE entity_id = ? AND kind = 'recession' AND year(start_date) >= ?
                   ORDER BY start_date""", [entity, start])
    except Exception:  # noqa: BLE001
        rec = []
    pts = lambda d: [[y, round(v, 2)] for y, v in sorted(d.items())]  # noqa: E731
    return {"entity": entity, "growth": pts(a.get((entity, "gdp_growth"), {})),
            "credit": pts(a.get((entity, "private_credit_gdp"), {})),
            "rate": [[x, round(v, 2)] for x, v in rate],
            "recessions": [[r["start_date"].isoformat(), (r["end_date"] or r["start_date"]).isoformat()] for r in rec]}
