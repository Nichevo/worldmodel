"""Inventions over time: the typed-in list (contract inventions.yaml), each with charts of how it
spread and of the changes seen around the same time, extra inventions from Wikidata (history_events
kind 'invention'), and the inventions as dated events for chart chips.

The charts show what changed around an invention, never that it caused the change: many things
change at once. Everything is read from series already loaded: no downloads of its own.
"""

from __future__ import annotations

from typing import Callable

from worldmodel_contract import catalogue
from worldmodel_api.episodes import annual, indicator_meta, long_annual

Q = Callable[[str, list], list[dict]]

KEY = ("world", "NZL", "AUS", "GBR", "USA")
CAUTION = ("These moved around the same time. Many other things changed too, so this does not show the "
           "invention caused it.")
EARLIEST = -12000  # long-run series start at 10,000 BC (population)


def _names(q: Q) -> dict[str, str]:
    try:
        return {r["entity_id"]: r["short_name"] or r["name"] for r in q("SELECT entity_id, name, short_name FROM entities", [])}
    except Exception:  # noqa: BLE001 - no warehouse yet
        return {}


def wiki_url(article: str | None) -> str | None:
    return f"https://en.wikipedia.org/wiki/{article}" if article else None


def by_id(iid: str) -> dict | None:
    return next((i for i in catalogue.inventions()["inventions"] if i["id"] == iid), None)


def measure_meta(q: Q, ids: list[str]) -> dict[str, dict]:
    """Name, unit and source of each series id ("long:x" or an indicator id)."""
    cat = catalogue.inventions()["measures"]
    hist = catalogue.history().get("series", {})
    plain = [s for s in ids if not s.startswith("long:")]
    meta = indicator_meta(q, plain)
    out: dict[str, dict] = {}
    for s in ids:
        if s.startswith("long:"):
            sid = s[5:]
            m = cat.get(sid) or hist.get(sid) or {}
            source = m.get("source") or ("Comin and Hobijn and others (through Our World in Data)" if sid.startswith("us_") else "Our World in Data")
            out[s] = {"name": m.get("name", sid.replace("_", " ")), "unit": m.get("unit", ""), "source": source, "decimals": 1,
                      "us_only": sid.startswith("us_"), "long": True}
        else:
            m = meta.get(s)
            out[s] = {"name": m["name"] if m else s.replace("_", " "), "unit": (m or {}).get("unit") or "", "source": None,
                      "decimals": (m or {}).get("decimals", 1) if m else 1, "us_only": False, "long": False, "missing": m is None}
    return out


def chart(q: Q, series: str, entities: list[str], names: dict[str, str], meta: dict) -> dict:
    """One series for the entities asked for (US household series: the US only)."""
    ents = ["USA"] if meta.get("us_only") else entities
    lines = []
    if series.startswith("long:"):
        got = long_annual(q, ents, series[5:], EARLIEST, 3000)
        for e in ents:
            pts = sorted(got.get(e, {}).items())
            if pts:
                lines.append({"entity": e, "name": names.get(e, "World" if e == "world" else e), "points": [[y, round(v, 4)] for y, v in pts]})
    else:
        got = annual(q, ents, [series], 1800, 3000)
        for e in ents:
            pts = sorted(got.get((e, series), {}).items())
            if pts:
                lines.append({"entity": e, "name": names.get(e, "World" if e == "world" else e), "points": [[y, round(v, 4)] for y, v in pts]})
    return {"series": series, "name": meta["name"], "unit": meta["unit"], "source": meta.get("source"), "lines": lines}


def _public(i: dict, cats: dict[str, str]) -> dict:
    return {**{k: i.get(k) for k in ("id", "name", "year", "approx", "category", "place", "where", "who", "what", "link")},
            "category_name": cats.get(i["category"], i["category"]), "wiki": wiki_url(i.get("wiki")),
            "spread": i["spread"], "related": i["related"]}


def extras(q: Q, typed_wiki: set[str], min_links: int = 25) -> list[dict]:
    """Inventions from Wikidata (time of discovery or invention) not already typed in."""
    try:
        found = q("""SELECT event_id, title, year, entity_id, links, url FROM history_events
                     WHERE kind = 'invention' AND coalesce(links, 0) >= ? ORDER BY year""", [min_links])
    except Exception:  # noqa: BLE001 - no history tables loaded yet
        return []
    out = []
    for r in found:
        url = r["url"] or ""
        if url.rsplit("/", 1)[-1].lower() in typed_wiki:
            continue
        out.append({"id": r["event_id"], "name": r["title"][:1].upper() + r["title"][1:], "year": r["year"], "where": r["entity_id"],
                    "links": r["links"], "url": url})
    return out


def listing(q: Q) -> dict:
    cat = catalogue.inventions()
    cats = {c["id"]: c["name"] for c in cat["categories"]}
    inv = [_public(i, cats) for i in cat["inventions"]]
    typed_wiki = {(i.get("wiki") or "").lower() for i in cat["inventions"]}
    every = sorted({s for i in cat["inventions"] for s in (*i["spread"], *i["related"])})
    meta = measure_meta(q, every)
    return {"categories": cat["categories"], "inventions": inv, "extras": extras(q, typed_wiki), "caution": CAUTION,
            "measures": [{"series": s, **{k: meta[s][k] for k in ("name", "unit", "source", "us_only", "long")}} for s in every
                         if not meta[s].get("missing")]}


def card(q: Q, iid: str, entities: list[str] | None = None) -> dict | None:
    i = by_id(iid)
    if i is None:
        return None
    cat = catalogue.inventions()
    cats = {c["id"]: c["name"] for c in cat["categories"]}
    names = _names(q)
    ents = list(dict.fromkeys([*(entities or KEY), *([i["where"]] if i.get("where") and not entities else [])]))
    ids = [*i["spread"], *[s for s in i["related"] if s not in i["spread"]]]
    meta = measure_meta(q, ids)
    charts = []
    for s in ids:
        c = chart(q, s, ents, names, meta[s])
        c["kind"] = "spread" if s in i["spread"] else "related"
        charts.append(c)
    same = [x for x in cat["inventions"] if x["category"] == i["category"]]
    k = next(n for n, x in enumerate(same) if x["id"] == iid)
    near = lambda x: {"id": x["id"], "name": x["name"], "year": x["year"]}  # noqa: E731
    # Other typed-in inventions sharing a chart, as chips on it
    sharing = {s: [{"id": x["id"], "name": x["name"], "year": x["year"], "category": x["category"]}
                   for x in cat["inventions"] if x["id"] != iid and s in (*x["spread"], *x["related"])] for s in ids}
    for c in charts:
        c["others"] = sharing.get(c["series"], [])
    return {"invention": _public(i, cats), "entities": ents, "charts": charts, "caution": CAUTION,
            "before": near(same[k - 1]) if k > 0 else None, "after": near(same[k + 1]) if k + 1 < len(same) else None}


def along(q: Q, series: str, entities: list[str] | None = None, categories: list[str] | None = None) -> dict:
    """One series with every typed-in invention (of the categories asked for) along it."""
    names = _names(q)
    meta = measure_meta(q, [series])[series]
    c = chart(q, series, list(entities or KEY), names, meta)
    cat = catalogue.inventions()
    cats = {x["id"]: x["name"] for x in cat["categories"]}
    inv = [{"id": x["id"], "name": x["name"], "year": x["year"], "category": x["category"], "category_name": cats.get(x["category"]),
            "linked": series in (*x["spread"], *x["related"])}
           for x in cat["inventions"] if not categories or x["category"] in categories]
    return {**c, "inventions": inv, "caution": CAUTION}


def as_events(entities: list[str] | None = None) -> list[dict]:
    """Each typed-in invention since 1700 as a dated event, for chart chips (off unless ticked).
    An invention belongs to everyone, so it comes once for each country asked for (the World
    when none is)."""
    out = []
    for i in catalogue.inventions()["inventions"]:
        if i["year"] < 1700:
            continue
        for e in entities or ["world"]:
            out.append({"event_id": f"invention:{i['id']}:{e}", "entity_id": e, "source_id": "inventions", "kind": "invention",
                        "subkind": i["category"], "title": i["name"], "start_date": f"{i['year']}-01-01", "end_date": None,
                        "precision": "year", "size": None, "size_unit": None, "deaths": None, "affected": None, "damage_usd": None,
                        "place": i.get("place"), "url": f"/inventions?id={i['id']}", "detail": i["what"], "color": None})
    return out
