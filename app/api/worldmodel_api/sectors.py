"""Sectors: one industry across the globe, stage by stage, and one country's trade by sector.

Definitions come from the contract (sectors.yaml); figures from the warehouse: trade
from CEPII BACI (sx_/sm_ per stage, tgx_/tgm_ per HS chapter), production from FAOSTAT,
USGS, World Mining Data or an indicator already in the catalogue, prices from the World
Bank Pink Sheet. Each function takes `q`, the API's rows(sql, params) helper.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from worldmodel_contract import sectors as sec

Q = Callable[[str, list], list[dict]]
ROUTES = 40          # routes kept per stage
RANKED = 40          # countries listed per ranking
HIGH_HHI = 2500      # Herfindahl-Hirschman index above which supply counts as highly concentrated
EV_COUNTRIES = ["world", "NZL", "AUS", "CHN", "USA", "eu", "NOR", "GBR", "JPN"]


def _yearly(q: Q, inds: list[str], entity: str | None = None) -> list[dict]:
    """Yearly country values of some indicators, the best-ranked source each country has."""
    if not inds:
        return []
    ph = ", ".join("?" for _ in inds)
    params = list(inds)
    where = ""
    if entity:
        where, params = " AND s.entity_id = ?", params + [entity]
    return q(f"""
        SELECT s.indicator_id AS ind, s.entity_id AS e, year(s.period_start) AS y, s.value AS v
        FROM series s
        JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
        JOIN entities en ON en.entity_id = s.entity_id
        WHERE s.indicator_id IN ({ph}) AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A'
          AND s.status = 'E' AND s.value IS NOT NULL AND en.type IN ('country', 'historical_country'){where}
        QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.entity_id, s.period_start ORDER BY r.rank) = 1""", params)


def _names(q: Q) -> dict[str, str]:
    return {r["entity_id"]: r["short_name"] or r["name"] for r in q("SELECT entity_id, name, short_name FROM entities", [])}


def _stage_inds(st: dict) -> dict[str, str | None]:
    sid = st["id"]
    return {"exports": f"sx_{sid}", "imports": f"sm_{sid}", "exports_t": f"sxq_{sid}", "imports_t": f"smq_{sid}",
            "production": sec.production_indicator(st), "reserves": f"sr_{sid}" if (st.get("production") or {}).get("usgs") else None}


def _by(data: list[dict]) -> dict[str, dict[int, dict[str, float]]]:
    """indicator -> year -> entity -> value."""
    out: dict = defaultdict(lambda: defaultdict(dict))
    for r in data:
        out[r["ind"]][r["y"]][r["e"]] = r["v"]
    return out


def _ranking(year_vals: dict[str, float], names: dict[str, str], n: int = RANKED) -> list[dict]:
    total = sum(v for v in year_vals.values() if v and v > 0)
    ranked = sorted(((e, v) for e, v in year_vals.items() if v and v > 0), key=lambda kv: -kv[1])
    return [{"entity_id": e, "name": names.get(e, e), "value": v, "share": round(100 * v / total, 2) if total else None}
            for e, v in ranked[:n]]


def _measure(series: dict[int, dict[str, float]], names: dict[str, str], year: int | None) -> dict | None:
    """One measure of one stage: the chosen year's ranking, world total and concentration each year."""
    if not series:
        return None
    years = sorted(series)
    y = max((x for x in years if year is None or x <= year), default=years[0])
    return {"year": y, "years": years, "rows": _ranking(series[y], names),
            "total": [[x, sum(v for v in series[x].values() if v and v > 0)] for x in years],
            "concentration": [[x, *(lambda c: [c["top3"], c["hhi"], c["n"]])(sec.concentration(list(series[x].values())))] for x in years],
            "countries": len([v for v in series[y].values() if v and v > 0])}


def _reliance(by: dict, inds: dict, y: int | None, names: dict[str, str]) -> list[dict]:
    """How much of each country's use of a stage comes from imports, in tonnes:
    (imports - exports) / (production + imports - exports)."""
    if y is None or not inds["production"]:
        return []
    prod = by.get(inds["production"], {}).get(y, {})
    imp, exp = by.get(inds["imports_t"], {}).get(y, {}), by.get(inds["exports_t"], {}).get(y, {})
    out = []
    for e in set(prod) | set(imp):
        p, i, x = prod.get(e) or 0, imp.get(e) or 0, exp.get(e) or 0
        use = p + i - x
        if use <= 0 or (i == 0 and p == 0):
            continue
        out.append({"entity_id": e, "name": names.get(e, e), "production": p, "imports": i, "exports": x, "use": use,
                    "reliance": round(max(0.0, min(100.0, 100 * (i - x) / use)), 1)})
    out.sort(key=lambda r: -r["use"])
    return out[:RANKED]


def _routes(q: Q, stage_id: str, y: int | None, names: dict[str, str]) -> list[dict]:
    if y is None:
        return []
    got = q(f"""SELECT entity_id AS e, substr(breakdown, {len(sec.PARTNER) + 1}) AS p, value AS v FROM series
                WHERE indicator_id = ? AND breakdown LIKE '{sec.PARTNER}%' AND period_start = make_date(?, 1, 1)
                  AND freq = 'A' AND variant = 'central' ORDER BY value DESC LIMIT {ROUTES}""", [f"sx_{stage_id}", y])
    return [{"from": r["e"], "from_name": names.get(r["e"], r["e"]), "to": r["p"], "to_name": names.get(r["p"], r["p"]),
             "value": r["v"]} for r in got]


def listing(q: Q, hidden: list[str]) -> dict:
    """Every sector with its stages and, for each stage, the latest world exports and the
    top exporter and producer: enough for the Sectors page's cards."""
    names = _names(q)
    latest = q("""
        WITH t AS (
            SELECT indicator_id, entity_id, year(period_start) AS y, value FROM series
            WHERE (indicator_id LIKE 'sx\\_%' ESCAPE '\\' OR indicator_id LIKE 'sp\\_%' ESCAPE '\\') AND breakdown = ''
              AND variant = 'central' AND freq = 'A' AND value > 0),
        m AS (SELECT indicator_id, max(y) AS y FROM t GROUP BY 1)
        SELECT t.indicator_id AS ind, t.y, sum(t.value) AS total, arg_max(t.entity_id, t.value) AS top,
               max(t.value) / sum(t.value) * 100 AS top_share
        FROM t JOIN m USING (indicator_id, y) GROUP BY 1, 2""", [])
    found = {r["ind"]: r for r in latest}
    out = []
    for s in sec.sectors():
        stages = []
        for st in s["stages"]:
            x, p = found.get(f"sx_{st['id']}"), found.get(sec.production_indicator(st) or "")
            stages.append({"id": st["id"], "name": st["name"], "unit": sec.stage_unit(st),
                           "exports": x and {"year": x["y"], "total": x["total"], "top": x["top"], "top_name": names.get(x["top"], x["top"]),
                                             "top_share": round(x["top_share"], 1)},
                           "production": p and {"year": p["y"], "total": p["total"], "top": p["top"], "top_name": names.get(p["top"], p["top"]),
                                                "top_share": round(p["top_share"], 1)}})
        out.append({"id": s["id"], "name": s["name"], "group": s["group"], "kind": s.get("kind", "chain"),
                    "feeds": s.get("feeds", ""), "hidden": s["id"] in hidden, "stages": stages,
                    "nz": any(c.get("nz") for c in s.get("companies", []))})
    return {"groups": sec.groups(), "sectors": out, "has_trade": any(k.startswith("sx_") for k in found)}


def page(q: Q, sector_id: str, year: int | None = None, country: str = "NZL") -> dict | None:
    s = sec.sector(sector_id)
    if s is None:
        return None
    names = _names(q)
    inds = {st["id"]: _stage_inds(st) for st in s["stages"]}
    wanted = sorted({i for d in inds.values() for i in d.values() if i})
    by = _by(_yearly(q, wanted))
    units = {r["indicator_id"]: r["unit"] for r in q(f"SELECT indicator_id, unit FROM indicators WHERE indicator_id IN ({', '.join('?' for _ in wanted)})", wanted)} if wanted else {}
    stages = []
    for st in s["stages"]:
        d = inds[st["id"]]
        exp, prod = _measure(by.get(d["exports"], {}), names, year), _measure(by.get(d["production"] or "", {}), names, year)
        imp = _measure(by.get(d["imports"], {}), names, year)
        res = _measure(by.get(d["reserves"] or "", {}), names, None)
        exp_t = by.get(d["exports_t"], {})
        mine = {k: [[y, v[country]] for y, v in sorted(by.get(i, {}).items()) if country in v] for k, i in d.items() if i}
        rank = {}
        for k, m in (("exports", exp), ("imports", imp), ("production", prod)):
            if m:
                ids = [r["entity_id"] for r in m["rows"]]
                full = sorted(((e, v) for e, v in by[d[k]][m["year"]].items() if v and v > 0), key=lambda kv: -kv[1])
                pos = next((i + 1 for i, (e, _) in enumerate(full) if e == country), None)
                rank[k] = {"rank": pos, "of": len(full), "listed": country in ids}
        stages.append({
            "id": st["id"], "name": st["name"], "unit": sec.stage_unit(st), "hs": [str(c) for c in st.get("hs", [])],
            "how": st.get("how"), "production_indicator": d["production"],
            "production_unit": units.get(d["production"] or "", sec.stage_unit(st)),
            "exports": exp, "imports": imp, "production": prod, "reserves": res,
            "exports_tonnes": [[y, sum(v for v in vals.values() if v and v > 0)] for y, vals in sorted(exp_t.items())],
            "unit_value": _unit_value(by.get(d["exports"], {}), exp_t),
            "reliance": _reliance(by, d, imp["year"] if imp else None, names) if sec.stage_unit(st) == "tonnes" else [],
            "routes": _routes(q, st["id"], exp["year"] if exp else None, names),
            "country": {"entity_id": country, "name": names.get(country, country), "series": mine, "rank": rank},
        })
    out = {"id": s["id"], "name": s["name"], "group": s["group"], "group_name": sec.groups().get(s["group"], s["group"]),
           "kind": s.get("kind", "chain"), "feeds": s.get("feeds", ""), "sources": s.get("sources", ""),
           "stages": stages, "prices": _prices(q, s.get("prices", [])),
           "companies": [{"nz": False, "note": "", **c, "country_name": names.get(c["country"], c["country"]),
                          "step_name": next((st["name"] for st in s["stages"] if st["id"] == c["step"]), c["step"])}
                         for c in s.get("companies", [])],
           "high_hhi": HIGH_HHI}
    if s["id"] == "cars":
        out["electric"] = electric(q, names)
    if s.get("kind") == "batteries":
        out["battery"] = battery(q, names)
    return out


def _unit_value(exp: dict[int, dict[str, float]], exp_t: dict[int, dict[str, float]]) -> list[list]:
    """World exports' average value per tonne each year (US$ / tonne): a price the trade itself shows."""
    out = []
    for y in sorted(set(exp) & set(exp_t)):
        both = [(v, exp_t[y].get(e)) for e, v in exp[y].items() if v and exp_t[y].get(e)]
        usd, t = sum(a for a, _ in both), sum(b for _, b in both)
        if t > 0:
            out.append([y, round(usd / t, 2)])
    return out


def _prices(q: Q, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    inds = [f"price_{p}" for p in ids]
    ph = ", ".join("?" for _ in inds)
    meta = {r["indicator_id"]: r for r in q(f"SELECT indicator_id, name, unit FROM indicators WHERE indicator_id IN ({ph})", inds)}
    pts = q(f"""SELECT indicator_id AS i, strftime(period_start, '%Y-%m') AS d, value AS v FROM series
                WHERE indicator_id IN ({ph}) AND entity_id = 'world' AND breakdown = '' AND variant = 'central'
                ORDER BY period_start""", inds)
    by: dict = defaultdict(list)
    for p in pts:
        by[p["i"]].append([p["d"], p["v"]])
    return [{"id": i, "name": meta[i]["name"], "unit": meta[i]["unit"], "points": by[i]} for i in inds if i in meta and by[i]]


def electric(q: Q, names: dict[str, str]) -> dict:
    """The shift to electric cars: share of new car sales by country (IEA)."""
    rows = q("""SELECT indicator_id AS ind, entity_id AS e, year(period_start) AS y, value AS v FROM series
                WHERE indicator_id IN ('ev_sales_share', 'ev_stock_share') AND breakdown = '' AND variant = 'central'
                ORDER BY y""", [])
    series: dict = defaultdict(lambda: defaultdict(list))
    latest: dict = {}
    for r in rows:
        if r["e"] in EV_COUNTRIES:
            series[r["ind"]][r["e"]].append([r["y"], r["v"]])
        if r["ind"] == "ev_sales_share" and r["e"] not in ("world", "eu"):
            if r["e"] not in latest or latest[r["e"]][0] < r["y"]:
                latest[r["e"]] = (r["y"], r["v"])
    ranked = sorted(({"entity_id": e, "name": names.get(e, e), "year": y, "value": v} for e, (y, v) in latest.items()),
                    key=lambda r: -r["value"])
    return {"sales_share": {e: series["ev_sales_share"][e] for e in EV_COUNTRIES if e in series["ev_sales_share"]},
            "stock_share": {e: series["ev_stock_share"][e] for e in EV_COUNTRIES if e in series["ev_stock_share"]},
            "names": {e: names.get(e, e) for e in EV_COUNTRIES}, "ranking": ranked[:RANKED]}


def battery(q: Q, names: dict[str, str]) -> dict:
    """What goes into a battery pack and how concentrated each material's mining and
    refining is, with the export limits and rules that bear on them."""
    b = sec.battery()
    mats = []
    for mat, sid in b["sectors"].items():
        s = sec.sector(sid)
        if s is None:
            continue
        steps = []
        for st in s["stages"]:
            pi = sec.production_indicator(st)
            if not pi:
                continue
            by = _by(_yearly(q, [pi]))
            m = _measure(by.get(pi, {}), names, None)
            if m and m["rows"]:
                c = m["concentration"][-1]
                steps.append({"stage": st["id"], "name": st["name"], "year": m["year"], "top": m["rows"][:3],
                              "top3": c[1], "hhi": c[2], "high": (c[2] or 0) > HIGH_HHI})
        mats.append({"material": mat, "sector": sid, "name": s["name"], "steps": steps})
    return {"chemistries": b["materials"], "materials": mats,
            "rules": [{**r, "name": names.get(r["country"], r["country"])} for r in b["rules"]], "high_hhi": HIGH_HHI}


def by_country(q: Q, country: str, year: int | None = None, since: int | None = None) -> dict:
    """One country's trade by HS chapter (exports, imports, the balance, change since a
    year, top partners) and where it stands in each sector stage."""
    names = _names(q)
    chapters = sec.chapters()
    inds = [f"tg{d}_{cc}" for cc in chapters for d in ("x", "m")]
    by = _by(_yearly(q, inds, country))
    years = sorted({y for i in by.values() for y in i})
    y = max((x for x in years if year is None or x <= year), default=None)
    s_year = since if since in years else (max((x for x in years if y and x <= y - 5), default=years[0]) if years else None)
    partners = defaultdict(list)
    if y:
        for r in q(f"""SELECT indicator_id AS i, substr(breakdown, {len(sec.PARTNER) + 1}) AS p, value AS v FROM series
                      WHERE entity_id = ? AND (indicator_id LIKE 'tgx\\_%' ESCAPE '\\' OR indicator_id LIKE 'tgm\\_%' ESCAPE '\\')
                        AND breakdown LIKE '{sec.PARTNER}%' AND period_start = make_date(?, 1, 1) AND variant = 'central'
                      ORDER BY value DESC""", [country, y]):
            partners[r["i"]].append({"entity_id": r["p"], "name": names.get(r["p"], r["p"]), "value": r["v"]})
    rows = []
    for cc, name in chapters.items():
        x, m = by.get(f"tgx_{cc}", {}), by.get(f"tgm_{cc}", {})
        xv, mv = (x.get(y) or {}).get(country), (m.get(y) or {}).get(country)
        if xv is None and mv is None:
            continue
        xs, ms = (x.get(s_year) or {}).get(country), (m.get(s_year) or {}).get(country)
        rows.append({"chapter": cc, "name": name, "exports": xv, "imports": mv, "balance": (xv or 0) - (mv or 0),
                     "exports_since": xs, "imports_since": ms,
                     "exports_change": round(100 * (xv / xs - 1), 1) if xv and xs else None,
                     "imports_change": round(100 * (mv / ms - 1), 1) if mv and ms else None,
                     "export_partners": partners.get(f"tgx_{cc}", [])[:5], "import_partners": partners.get(f"tgm_{cc}", [])[:5]})
    totals = [[yr, sum((by.get(f"tgx_{cc}", {}).get(yr) or {}).get(country) or 0 for cc in chapters),
               sum((by.get(f"tgm_{cc}", {}).get(yr) or {}).get(country) or 0 for cc in chapters)] for yr in years]
    return {"country": country, "name": names.get(country, country), "year": y, "since": s_year, "years": years,
            "chapters": rows, "totals": totals, "stages": _country_stages(q, country, y, names),
            "economy": _economy(q, country)}


def _country_stages(q: Q, country: str, y: int | None, names: dict[str, str]) -> list[dict]:
    """The country's exports, imports and production in each sector stage, with its world rank."""
    want = {}
    for s, st in sec.stages():
        for k, i in (("exports", f"sx_{st['id']}"), ("imports", f"sm_{st['id']}"), ("production", sec.production_indicator(st))):
            if i:
                want[i] = (s, st, k)
    if not want:
        return []
    ph = ", ".join("?" for _ in want)
    got = q(f"""
        WITH t AS (
            SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.value
            FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
            JOIN entities en ON en.entity_id = s.entity_id
            WHERE s.indicator_id IN ({ph}) AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A' AND s.value > 0
              AND en.type IN ('country', 'historical_country')
            QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.entity_id, s.period_start ORDER BY r.rank) = 1),
        latest AS (SELECT indicator_id, max(y) AS y FROM t WHERE entity_id = ? GROUP BY 1),
        ranked AS (SELECT t.*, rank() OVER (PARTITION BY t.indicator_id ORDER BY t.value DESC) AS pos,
                          count(*) OVER (PARTITION BY t.indicator_id) AS n, sum(t.value) OVER (PARTITION BY t.indicator_id) AS total
                   FROM t JOIN latest USING (indicator_id, y))
        SELECT indicator_id AS i, y, value AS v, pos, n, total FROM ranked WHERE entity_id = ?""", list(want) + [country, country])
    out: dict = {}
    for r in got:
        s, st, k = want[r["i"]]
        row = out.setdefault(st["id"], {"sector": s["id"], "sector_name": s["name"], "group": s["group"], "stage": st["id"],
                                        "name": st["name"], "unit": sec.stage_unit(st)})
        row[k] = {"year": r["y"], "value": r["v"], "rank": r["pos"], "of": r["n"], "share": round(100 * r["v"] / r["total"], 2) if r["total"] else None}
    return sorted(out.values(), key=lambda r: -max((r.get(k) or {}).get("share") or 0 for k in ("exports", "production", "imports")))


ECONOMY = [("agriculture_share_gdp", "Farming, forestry and fishing"), ("industry_share_gdp", "Industry (with building)"),
           ("manufacturing_share_gdp", "Manufacturing"), ("services_share_gdp", "Services")]


def _economy(q: Q, country: str) -> list[dict]:
    """The economy at home: value added by broad sector, % of GDP (World Bank)."""
    ids = [i for i, _ in ECONOMY]
    got = _yearly(q, ids, country)
    out = []
    for i, label in ECONOMY:
        pts = sorted([r["y"], r["v"]] for r in got if r["ind"] == i)
        if pts:
            out.append({"id": i, "name": label, "points": pts})
    return out
