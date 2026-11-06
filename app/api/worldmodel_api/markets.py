"""Markets and regions: a country's currency against its partners, storage levels set
against past years, and New Zealand's regions.

Exchange rates are stored as units of each country's currency per US dollar, day by day
(fx_usd_d: the ECB first, the Federal Reserve H.10 for older years and other currencies);
any pair is worked out from two of them. Each function takes `q`, the API's rows(sql,
params) helper.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from worldmodel_contract import catalogue

Q = Callable[[str, list], list[dict]]
DEFAULT_PARTNERS = ["USA", "eu", "CHN", "JPN", "AUS", "GBR"]
EVENT_KINDS = ("conflict", "sanction", "disaster", "crisis", "recession")


# ----------------------------------------------------------------------------------- currency
def currency_of(entity: str, on: date | None = None) -> str | None:
    on = on or date.today()
    for r in catalogue.currencies():
        if r["entity_id"] != entity:
            continue
        f = date.fromisoformat(r["valid_from"]) if r.get("valid_from") else None
        t = date.fromisoformat(r["valid_to"]) if r.get("valid_to") else None
        if (f is None or on >= f) and (t is None or on <= t):
            return r["currency"]
    return None


def currency_name(code: str) -> str:
    return next((r["name"] for r in catalogue.currencies() if r["currency"] == code), code)


def top_partners(q: Q, entity: str, n: int = 5) -> list[str]:
    """The country's biggest trading partners (exports plus imports, latest year of BACI's
    chapter partners), one per currency, else a standard list."""
    got = q("""SELECT substr(breakdown, 9) AS p, sum(value) AS v FROM series
               WHERE entity_id = ? AND breakdown LIKE 'partner=%' AND (indicator_id LIKE 'tgx_%' OR indicator_id LIKE 'tgm_%')
                 AND freq = 'A' AND period_start = (SELECT max(period_start) FROM series WHERE entity_id = ?
                     AND breakdown LIKE 'partner=%' AND indicator_id LIKE 'tgx_%')
               GROUP BY 1 ORDER BY 2 DESC LIMIT 40""", [entity, entity])
    out, seen = [], {currency_of(entity)}
    for p in [r["p"] for r in got] + DEFAULT_PARTNERS:
        c = currency_of(p)
        if c == "EUR":
            p = "eu"
        if c and c not in seen and p != entity:
            seen.add(c)
            out.append(p)
        if len(out) >= n:
            break
    return out


def _step(start: date, end: date) -> str:
    days = (end - start).days
    return "day" if days <= 3 * 366 else "week" if days <= 15 * 366 else "month"


def fx(q: Q, entity: str, partners: list[str] | None, start: int | None, end: int | None,
       mode: str = "rate", saved: list[str] | None = None) -> dict:
    """The country's currency against each partner's: how many units of the partner's currency one
    unit of its own buys (mode rate), or that indexed to 100 on the first day shown (mode index);
    and the BIS trade-weighted index each month (mode twi)."""
    own = currency_of(entity)
    chosen = partners or saved or top_partners(q, entity)
    span = q("""SELECT min(period_start) AS a, max(period_start) AS b FROM series
                WHERE indicator_id = 'fx_usd_d' AND entity_id = ?""", [entity])
    first, last = (span[0]["a"], span[0]["b"]) if span and span[0]["a"] else (None, None)
    available = [r["entity_id"] for r in q("""SELECT DISTINCT entity_id FROM series WHERE indicator_id = 'fx_usd_d'""", [])]
    names = {r["entity_id"]: r["short_name"] for r in q("SELECT entity_id, short_name FROM entities", [])}
    have, first_user = set(available), {}
    for r in catalogue.currencies():  # one country per currency: the first listed (the euro: "eu")
        if r["entity_id"] in have and currency_of(r["entity_id"]) == r["currency"]:
            first_user.setdefault(r["currency"], r["entity_id"])
    choices = sorted((c, e) for c, e in first_user.items())
    out = {"entity": entity, "currency": own, "currency_name": currency_name(own) if own else None,
           "partners": [], "mode": mode, "first_year": first.year if first else None, "last_date": last,
           "default_partners": not partners and not saved, "twi": [],
           "choices": [{"entity_id": e, "currency": c, "name": names.get(e, e), "currency_name": currency_name(c)}
                       for c, e in choices if e != entity and c != own]}
    if not own or not first:
        return out
    y0 = start or max(first.year, last.year - 9)
    y1 = end or last.year
    d0, d1 = date(y0, 1, 1), date(y1, 12, 31)
    step = _step(d0, d1)
    bucket = {"day": "period_start", "week": "date_trunc('week', period_start)",
              "month": "date_trunc('month', period_start)"}[step]
    ids = [entity, *chosen]
    marks = ", ".join("?" * len(ids))
    data = q(f"""
        WITH r AS (
            SELECT s.entity_id, s.period_start, arg_min(s.value, i.rank) AS v
            FROM series s JOIN indicator_sources i ON i.indicator_id = s.indicator_id AND i.source_id = s.source_id
            WHERE s.indicator_id = 'fx_usd_d' AND s.entity_id IN ({marks}) AND s.period_start BETWEEN ? AND ?
            GROUP BY 1, 2)
        SELECT entity_id, CAST({bucket} AS DATE) AS d, arg_max(v, period_start) AS v FROM r GROUP BY 1, 2 ORDER BY 2""",
             [*ids, d0, d1])
    by: dict[str, dict] = {}
    for r in data:
        by.setdefault(r["entity_id"], {})[r["d"]] = r["v"]
    home = by.get(entity, {})
    for p in chosen:
        pts = [[d.isoformat(), v / home[d]] for d, v in sorted(by.get(p, {}).items()) if home.get(d)]
        if mode == "index" and pts:
            b = pts[0][1]
            pts = [[d, 100 * v / b] for d, v in pts]
        c = currency_of(p)
        out["partners"].append({"entity_id": p, "name": names.get(p, p), "currency": c,
                                "currency_name": currency_name(c) if c else None, "points": pts})
    out["step"], out["start"], out["end"] = step, y0, y1
    for ind, label in (("bis_eer_nominal_m", "Nominal"), ("bis_eer_real_m", "Real")):
        pts = q("""SELECT strftime(period_start, '%Y-%m-%d') AS d, value AS v FROM series
                   WHERE indicator_id = ? AND entity_id = ? AND period_start BETWEEN ? AND ? ORDER BY 1""",
                [ind, entity, d0, d1])
        if pts:
            out["twi"].append({"name": label, "points": [[r["d"], r["v"]] for r in pts]})
    return out


# ----------------------------------------------------------------------------------- storage
STORAGE = [  # (indicator, group, short name, how to read it)
    ("gas_storage_fill", "Gas storage (Europe, daily)", "Gas storage fill", "share of working capacity"),
    ("gas_storage_twh", "Gas storage (Europe, daily)", "Gas in storage", "TWh"),
    ("lng_stock", "LNG terminals (daily)", "LNG in terminal tanks", ""),
    ("us_gas_storage", "United States (weekly)", "Working gas in storage", ""),
    ("us_crude_stocks", "United States (weekly)", "Commercial crude oil stocks", ""),
    ("us_spr_stocks", "United States (weekly)", "Strategic Petroleum Reserve", ""),
    ("us_gasoline_stocks", "United States (weekly)", "Motor gasoline stocks", ""),
    ("us_distillate_stocks", "United States (weekly)", "Distillate (diesel) stocks", ""),
    ("us_jet_stocks", "United States (weekly)", "Jet fuel stocks", ""),
    ("jodi_product_days", "Oil and gas by country (monthly)", "Oil product stocks, days of demand", ""),
    ("jodi_product_stocks", "Oil and gas by country (monthly)", "Oil product stocks", ""),
    ("jodi_crude_stocks", "Oil and gas by country (monthly)", "Crude oil stocks", ""),
    ("jodi_gas_stocks", "Oil and gas by country (monthly)", "Natural gas stocks", ""),
]


def storage_list(q: Q) -> list[dict]:
    ids = [s[0] for s in STORAGE]
    marks = ", ".join("?" * len(ids))
    got = q(f"""SELECT s.indicator_id, s.entity_id, e.short_name AS name, max(s.period_start) AS last, count(*) AS n
                FROM series s JOIN entities e USING (entity_id)
                WHERE s.indicator_id IN ({marks}) AND s.breakdown = '' GROUP BY ALL""", ids)
    meta = {s[0]: s for s in STORAGE}
    inds = {r["indicator_id"]: r for r in q(f"SELECT indicator_id, name, unit, decimals, frequency FROM indicators "
                                            f"WHERE indicator_id IN ({marks})", ids)}
    out = []
    for r in got:
        m, i = meta[r["indicator_id"]], inds.get(r["indicator_id"], {})
        out.append({"indicator_id": r["indicator_id"], "entity_id": r["entity_id"], "entity_name": r["name"],
                    "group": m[1], "name": m[2], "unit": i.get("unit"), "decimals": i.get("decimals"),
                    "frequency": i.get("frequency"), "last": r["last"], "points": r["n"]})
    order = {s[0]: n for n, s in enumerate(STORAGE)}
    out.sort(key=lambda x: (order[x["indicator_id"]], x["entity_id"] != "eu", x["entity_id"] != "NZL", x["entity_name"]))
    return out


def storage(q: Q, indicator: str, entity: str, years: int = 5) -> dict | None:
    """This year's values day by day (or week, or month), the years before it, and the band
    (lowest to highest) and average of the `years` full years before this one, by week of the
    year (month for monthly figures); events in this year on the rim."""
    meta = next((s for s in STORAGE if s[0] == indicator), None)
    if not meta:
        return None
    ind = q("SELECT name, unit, decimals, frequency FROM indicators WHERE indicator_id = ?", [indicator])
    pts = q("""SELECT period_start AS d, value AS v FROM series WHERE indicator_id = ? AND entity_id = ? AND breakdown = ''
               AND variant = 'central' ORDER BY 1""", [indicator, entity])
    if not ind or not pts:
        return None
    monthly = ind[0]["frequency"] == "M"
    last = pts[-1]["d"]
    this = last.year
    by_year: dict[int, list] = {}
    for r in pts:
        by_year.setdefault(r["d"].year, []).append([doy(r["d"], monthly), r["v"], r["d"].isoformat()])

    def slot(d: int) -> int:
        return d if monthly else min(52, (d - 1) // 7)
    band: dict[int, list[float]] = {}
    past = [y for y in sorted(by_year) if this - years <= y < this]
    for y in past:
        for d, v, _ in by_year[y]:
            band.setdefault(slot(d), []).append(v)
    rows = [{"day": (k if monthly else k * 7 + 4), "low": min(v), "high": max(v), "mean": sum(v) / len(v)}
            for k, v in sorted(band.items()) if len(v) >= max(1, len(past) // 2)]
    latest = pts[-1]
    same = [v for d, v, _ in (x for y in past for x in by_year[y]) if slot(d) == slot(doy(last, monthly))]
    avg = sum(same) / len(same) if same else None
    year_ago = next((x[1] for x in reversed(by_year.get(this - 1, [])) if x[0] <= doy(last, monthly)), None)
    events = q(f"""SELECT title, kind, start_date FROM events WHERE entity_id IN (?, 'world') AND kind IN ({', '.join('?' * len(EVENT_KINDS))})
                   AND year(start_date) = ? ORDER BY start_date LIMIT 20""", [entity, *EVENT_KINDS, this])
    name = q("SELECT short_name FROM entities WHERE entity_id = ?", [entity])
    return {
        "indicator_id": indicator, "entity_id": entity, "entity_name": name[0]["short_name"] if name else entity,
        "name": meta[2], "unit": ind[0]["unit"], "decimals": ind[0]["decimals"], "frequency": ind[0]["frequency"],
        "year": this, "years_back": past, "band": rows,
        "years": {str(y): v for y, v in by_year.items() if y >= this - max(years, 5)},
        "latest": {"date": latest["d"].isoformat(), "value": latest["v"], "average": avg, "year_ago": year_ago},
        "events": [{"title": e["title"], "kind": e["kind"], "date": e["start_date"].isoformat(),
                    "day": doy(e["start_date"], False)} for e in events],
    }


def doy(d: date, monthly: bool) -> int:
    """Day of the year (1 to 366); the middle of the month for monthly figures."""
    n = d.timetuple().tm_yday
    return n + 14 if monthly else n


# ----------------------------------------------------------------------------------- regions
def regions(q: Q, country: str) -> dict:
    """The country's regions with every figure held for them, by year."""
    try:
        subs = q("""SELECT d.entity_id, e.short_name AS name, d.code FROM subdivisions d JOIN entities e USING (entity_id)
                    WHERE d.parent_id = ? ORDER BY e.short_name""", [country])
    except Exception:  # noqa: BLE001 - a warehouse built before 1.7.0 has no subdivisions table
        subs = []
    out = {"country": country, "regions": subs, "measures": []}
    if not subs:
        return out
    ids = [s["entity_id"] for s in subs]
    marks = ", ".join("?" * len(ids))
    data = q(f"""SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.value, s.source_id
                 FROM series s WHERE s.entity_id IN ({marks}) AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A'
                 ORDER BY 1, 3""", ids)
    if not data:
        return out
    inds = sorted({r["indicator_id"] for r in data})
    meta = {r["indicator_id"]: r for r in q(f"""SELECT i.indicator_id, i.name, i.unit, i.decimals, i.domain, s.name AS source
        FROM indicators i LEFT JOIN indicator_sources x ON x.indicator_id = i.indicator_id AND x.rank = 1
        LEFT JOIN sources s ON s.source_id = x.source_id WHERE i.indicator_id IN ({', '.join('?' * len(inds))})""", inds)}
    by: dict[str, dict[str, dict[int, float]]] = {}
    for r in data:
        by.setdefault(r["indicator_id"], {}).setdefault(r["entity_id"], {})[r["y"]] = r["value"]
    for i in inds:
        m = meta.get(i, {})
        years = sorted({y for v in by[i].values() for y in v})
        out["measures"].append({"indicator_id": i, "name": m.get("name", i), "unit": m.get("unit"), "decimals": m.get("decimals"),
                                "source": m.get("source"), "years": years,
                                "values": {e: {str(y): v for y, v in ys.items()} for e, ys in by[i].items()}})
    return out
