"""Goods by port (table port_goods): what goes in and out of each port, by kind of goods and by
partner country, from national statistics. Each function takes `q`, the API's rows(sql, params)
helper. The table is absent before schema 1.17.0; every function then answers empty."""

from __future__ import annotations

from collections.abc import Callable

Q = Callable[[str, list], list[dict]]

SOURCE_NAMES = {"statsnz_port_trade": "Stats NZ", "eurostat_port_goods": "Eurostat", "dft_port_freight": "UK Department for Transport",
                "census_port_trade": "US Census Bureau", "bitre_sea_freight": "BITRE (Australia)"}
# How many periods make a year, by frequency.
PER_YEAR = {"M": 12, "Q": 4, "A": 1, "FY": 1}


def _has(q: Q) -> bool:
    try:
        q("SELECT 1 FROM port_goods LIMIT 1", [])
        return True
    except Exception:  # noqa: BLE001 - warehouses before 1.17.0
        return False


def _r(v, n=0):
    return None if v is None else round(v, n)


# The last year of figures for each port: the 12 latest months, 4 latest quarters or latest year.
WINDOW = """(SELECT port_key, max(period) AS last_p, any_value(freq) AS freq,
                    CAST(CASE any_value(freq) WHEN 'M' THEN max(period) - INTERVAL 11 MONTH
                                              WHEN 'Q' THEN max(period) - INTERVAL 9 MONTH ELSE max(period) END AS DATE) AS first_p
             FROM port_goods GROUP BY port_key)"""
# Rows that add up to a port's total: kinds of goods, or (where a source has no kinds) its totals.
GOODS_ROWS = """(partner_id = '' AND (goods <> 'TOTAL' OR NOT EXISTS (
                    SELECT 1 FROM port_goods g2 WHERE g2.port_key = g.port_key AND g2.partner_id = '' AND g2.goods <> 'TOTAL')))"""


def countries(q: Q) -> list[dict]:
    """Countries with goods by port: how many ports, from which sources, up to when."""
    if not _has(q):
        return []
    return [{"entity_id": r["entity_id"], "name": r["name"], "ports": r["ports"],
             "sources": [SOURCE_NAMES.get(s, s) for s in (r["sources"] or [])], "last": r["last"].isoformat()}
            for r in q("""SELECT g.entity_id, coalesce(any_value(e.short_name), g.entity_id) AS name,
                                 count(DISTINCT g.port_key) AS ports, list(DISTINCT g.source_id) AS sources, max(g.period) AS last
                          FROM port_goods g LEFT JOIN entities e USING (entity_id)
                          WHERE g.entity_id IS NOT NULL GROUP BY g.entity_id ORDER BY ports DESC""", [])]


def ports_of(q: Q, entity: str) -> list[dict]:
    """A country's ports with the last year of goods in and out (tonnes and value), busiest first."""
    if not _has(q):
        return []
    got = q(f"""SELECT g.port_key, any_value(g.port_name) AS name, any_value(g.port_id) AS port_id, any_value(g.kind) AS kind,
                       any_value(g.source_id) AS source_id, any_value(g.currency) AS currency, w.freq, w.first_p, w.last_p,
                       sum(CASE WHEN g.direction = 'in' THEN g.tonnes END) AS in_t,
                       sum(CASE WHEN g.direction = 'out' THEN g.tonnes END) AS out_t,
                       sum(CASE WHEN g.direction = 'in' THEN g.value END) AS in_v,
                       sum(CASE WHEN g.direction = 'out' THEN g.value END) AS out_v
                FROM port_goods g JOIN {WINDOW} w USING (port_key)
                WHERE g.entity_id = ? AND g.period BETWEEN w.first_p AND w.last_p AND {GOODS_ROWS}
                GROUP BY g.port_key, w.freq, w.first_p, w.last_p""", [entity])
    out = [{"key": r["port_key"], "name": r["name"], "port_id": r["port_id"], "kind": r["kind"],
            "source": SOURCE_NAMES.get(r["source_id"], r["source_id"]), "freq": r["freq"], "currency": r["currency"],
            "from": r["first_p"].isoformat(), "to": r["last_p"].isoformat(),
            "in_t": _r(r["in_t"]), "out_t": _r(r["out_t"]), "in_v": _r(r["in_v"]), "out_v": _r(r["out_v"])} for r in got]
    out.sort(key=lambda p: -((p["in_t"] or 0) + (p["out_t"] or 0) or (p["in_v"] or 0) + (p["out_v"] or 0)))
    return out


def for_port_id(q: Q, port_id: str) -> list[str]:
    """The goods-by-port keys tied to a PortWatch port."""
    if not _has(q):
        return []
    return [r["port_key"] for r in q("SELECT DISTINCT port_key FROM port_goods WHERE port_id = ?", [port_id])]


def port(q: Q, key: str, top: int = 8) -> dict | None:
    """One port: its totals year by year, the last year's goods and partners in and out, and the
    biggest kinds of goods year by year (the rest summed as 'Everything else')."""
    if not _has(q):
        return None
    meta = q(f"""SELECT any_value(port_name) AS name, any_value(port_id) AS port_id, any_value(kind) AS kind,
                        any_value(entity_id) AS entity_id, any_value(source_id) AS source_id, any_value(currency) AS currency,
                        any_value(w.freq) AS freq, any_value(w.first_p) AS first_p, any_value(w.last_p) AS last_p
                 FROM port_goods JOIN {WINDOW} w USING (port_key) WHERE port_key = ?""", [key])
    if not meta or meta[0]["name"] is None:
        return None
    m = meta[0]
    per_year = PER_YEAR.get(m["freq"], 1)
    years = q(f"""SELECT year(period) AS y, count(DISTINCT period) AS n,
                         sum(CASE WHEN direction = 'in' THEN tonnes END) AS in_t, sum(CASE WHEN direction = 'out' THEN tonnes END) AS out_t,
                         sum(CASE WHEN direction = 'in' THEN value END) AS in_v, sum(CASE WHEN direction = 'out' THEN value END) AS out_v
                  FROM port_goods g WHERE port_key = ? AND {GOODS_ROWS} GROUP BY 1 ORDER BY 1""", [key])
    last = q(f"""SELECT goods, any_value(goods_name) AS name,
                        sum(CASE WHEN direction = 'in' THEN tonnes END) AS in_t, sum(CASE WHEN direction = 'out' THEN tonnes END) AS out_t,
                        sum(CASE WHEN direction = 'in' THEN value END) AS in_v, sum(CASE WHEN direction = 'out' THEN value END) AS out_v
                 FROM port_goods g JOIN {WINDOW} w USING (port_key)
                 WHERE port_key = ? AND period BETWEEN w.first_p AND w.last_p AND {GOODS_ROWS} GROUP BY goods""", [key])
    measure = "value" if any(r["in_v"] or r["out_v"] for r in last) else "tonnes"

    def size(r):
        return (r["in_v"] or 0) + (r["out_v"] or 0) if measure == "value" else (r["in_t"] or 0) + (r["out_t"] or 0)
    last.sort(key=lambda r: -size(r))
    partners = q("""SELECT partner_id, coalesce(any_value(e.short_name), partner_id) AS name,
                           sum(CASE WHEN direction = 'in' THEN tonnes END) AS in_t, sum(CASE WHEN direction = 'out' THEN tonnes END) AS out_t,
                           sum(CASE WHEN direction = 'in' THEN value END) AS in_v, sum(CASE WHEN direction = 'out' THEN value END) AS out_v
                    FROM port_goods g JOIN """ + WINDOW + """ w USING (port_key) LEFT JOIN entities e ON e.entity_id = g.partner_id
                    WHERE port_key = ? AND partner_id <> '' AND period BETWEEN w.first_p AND w.last_p GROUP BY partner_id""", [key])
    partners.sort(key=lambda r: -size(r))
    big = [r["goods"] for r in last if r["goods"] != "TOTAL"][:top]
    col = "value" if measure == "value" else "tonnes"
    mix = q(f"""SELECT year(period) AS y, CASE WHEN goods IN ({', '.join('?' * len(big)) or "''"}) THEN goods ELSE 'other' END AS k,
                       sum({col}) AS v
                FROM port_goods g WHERE port_key = ? AND partner_id = '' AND goods <> 'TOTAL' GROUP BY 1, 2 ORDER BY 1""",
            [*big, key])
    names = {r["goods"]: r["name"] for r in last}

    def row(r, k="goods", n="name"):
        return {"id": r[k], "name": r[n], "in_t": _r(r["in_t"]), "out_t": _r(r["out_t"]), "in_v": _r(r["in_v"]),
                "out_v": _r(r["out_v"])}
    return {"key": key, "name": m["name"], "port_id": m["port_id"], "kind": m["kind"], "entity_id": m["entity_id"],
            "source": SOURCE_NAMES.get(m["source_id"], m["source_id"]), "source_id": m["source_id"], "currency": m["currency"],
            "freq": m["freq"], "from": m["first_p"].isoformat(), "to": m["last_p"].isoformat(), "measure": measure,
            "years": [{"year": r["y"], "full": r["n"] >= per_year, "in_t": _r(r["in_t"]), "out_t": _r(r["out_t"]),
                       "in_v": _r(r["in_v"]), "out_v": _r(r["out_v"])} for r in years],
            "goods": [row(r) for r in last if r["goods"] != "TOTAL"],
            "partners": [row(r, "partner_id") for r in partners],
            "mix": {"keys": [{"id": g, "name": names.get(g, g)} for g in big] + ([{"id": "other", "name": "Everything else"}]
                                                                                if any(r["k"] == "other" for r in mix) else []),
                    "rows": [{"year": r["y"], "id": r["k"], "v": _r(r["v"])} for r in mix]}}
