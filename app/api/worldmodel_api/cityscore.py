"""Scores made from several city figures (contract city_scores.yaml), such as City stress.

For each part, every city with a figure is ranked against the others on its latest year (or
the latest within five years of a chosen year); the rank becomes 0 to 10, with 10 the most
stressful, so a part where higher is better is turned round. A city's score is the weighted
mean of the parts it has, if it has at least min_parts of them. A score is relative: it says
how a city stands among the cities with figures, not against a fixed yardstick.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from worldmodel_contract import catalogue
from worldmodel_contract.cities import CITY_INDICATORS

WINDOW = 5  # a part's figure counts for a chosen year if it is from that year or the five before


def config(score_id: str) -> dict | None:
    return catalogue.city_scores().get(score_id)


def scaled(values: dict[str, float], worse_when: str) -> dict[str, float]:
    """Each city's place among the others, 0 (best) to 10 (worst); ties share their place."""
    if not values:
        return {}
    order = sorted(values.values())
    n = len(order)
    first: dict[float, int] = {}
    count: dict[float, int] = defaultdict(int)
    for i, v in enumerate(order):
        first.setdefault(v, i)
        count[v] += 1
    out = {}
    for city, v in values.items():
        pos = first[v] + (count[v] - 1) / 2  # the middle of a tie
        x = 5.0 if n == 1 else 10 * pos / (n - 1)
        out[city] = round(10 - x if worse_when == "lower" else x, 2)
    return out


def years(rows: Callable, score_id: str) -> list[int]:
    """Years for which any part has figures."""
    cfg = config(score_id)
    if not cfg:
        return []
    inds = [p["indicator"] for p in cfg["parts"]]
    got = rows(f"""SELECT DISTINCT year(period_start) AS y FROM city_series
                   WHERE indicator_id IN ({', '.join('?' * len(inds))}) ORDER BY 1""", inds)
    return [r["y"] for r in got]


def compute(rows: Callable, score_id: str, year: int | None = None) -> dict:
    """Every city's score, best placed first by default order of most stressful, with its parts."""
    cfg = config(score_id)
    if not cfg:
        return {"rows": [], "parts": [], "note": f"no score {score_id}"}
    parts = cfg["parts"]
    inds = [p["indicator"] for p in parts]
    marks = ", ".join("?" * len(inds))
    when, params = "", list(inds)
    if year is not None:
        when = "AND year(period_start) BETWEEN ? AND ?"
        params += [year - WINDOW, year]
    data = rows(f"""SELECT city_id, indicator_id, max_by(value, period_start) AS v, year(max(period_start)) AS y
                    FROM city_series WHERE indicator_id IN ({marks}) AND value IS NOT NULL {when}
                    GROUP BY 1, 2""", params)
    raw: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
    for r in data:
        raw[r["indicator_id"]][r["city_id"]] = (r["v"], r["y"])
    places = {p["indicator"]: scaled({c: v for c, (v, _) in raw[p["indicator"]].items()}, p.get("worse_when", "higher"))
              for p in parts}
    need = int(cfg.get("min_parts", 1))
    scores: dict[str, dict] = {}
    for city in {c for got in raw.values() for c in got}:
        have = [p for p in parts if city in places[p["indicator"]]]
        if len(have) < need:
            continue
        w = sum(float(p.get("weight", 1)) for p in have)
        s = sum(float(p.get("weight", 1)) * places[p["indicator"]][city] for p in have) / w
        scores[city] = {
            "score": round(s, 2), "n_parts": len(have),
            "parts": {p["indicator"]: {"value": raw[p["indicator"]][city][0], "year": raw[p["indicator"]][city][1],
                                       "points": places[p["indicator"]][city]} for p in have}}
    meta = rows("""SELECT c.city_id, c.name, c.country_id, e.short_name AS country, c.lat, c.lon, c.population
                   FROM cities c LEFT JOIN entities e ON e.entity_id = c.country_id""") if scores else []
    out = []
    for m in meta:
        if (s := scores.get(m["city_id"])):
            out.append({**m, **s})
    out.sort(key=lambda r: (-r["score"], r["name"]))
    for i, r in enumerate(out):
        r["rank"] = i + 1
    part_meta = []
    for p in parts:
        ind = CITY_INDICATORS.get(p["indicator"], (p["indicator"], "", 1, "", ""))
        part_meta.append({"indicator": p["indicator"], "name": p.get("name") or ind[0], "full_name": ind[0],
                          "unit": ind[1], "decimals": ind[2], "description": ind[3], "source_id": ind[4],
                          "worse_when": p.get("worse_when", "higher"), "weight": float(p.get("weight", 1)),
                          "cities": len(raw[p["indicator"]])})
    published = cfg.get("published") or {}
    by_key = {(r["name"].lower(), r["country_id"]): r for r in out}
    pub_rows = []
    for c in published.get("cities", []):
        ours = by_key.get((c["name"].lower(), c["country"]))
        pub_rows.append({**c, "city_id": ours["city_id"] if ours else None,
                         "ours": ours["score"] if ours else None, "our_rank": ours["rank"] if ours else None})
    missing = [pm["name"] for pm in part_meta if not pm["cities"]]
    note = None
    if not out:
        note = ("No city has enough parts yet: load the Numbeo cost of living, crime and health care pages, the "
                "TomTom ranking (both saved by hand) and the WHO air quality file (refresh.bat).")
    return {"id": score_id, "name": cfg["name"], "about": cfg.get("about", ""), "unit": cfg.get("unit", ""),
            "high_is": cfg.get("high_is", ""), "min_parts": need, "year": year, "parts": part_meta, "rows": out,
            "missing_parts": missing,
            "published": {k: v for k, v in published.items() if k != "cities"} | {"cities": pub_rows} if published else None,
            "how": (f"Each part ranks the cities that have it, on their latest figure{'' if year is None else f' from {year - WINDOW} to {year}'}, "
                    "from 0 (best placed) to 10 (worst); the score is the mean of the parts a city has "
                    f"(at least {need} of {len(parts)}). It compares cities with each other, so a city's score moves "
                    "when cities are added."),
            "note": note}


def for_city(rows: Callable, cached: Callable, city_id: str) -> list[dict]:
    """Each score for one city, with its rank and how it changed over the years."""
    out = []
    for sid in catalogue.city_scores():
        now = cached(sid, None)
        hit = next((r for r in now["rows"] if r["city_id"] == city_id), None)
        if not hit:
            continue
        history = []
        for y in years(rows, sid):
            got = cached(sid, y)
            h = next((r for r in got["rows"] if r["city_id"] == city_id), None)
            if h:
                history.append({"year": y, "score": h["score"], "rank": h["rank"], "of": len(got["rows"])})
        out.append({"id": sid, "name": now["name"], "about": now["about"], "score": hit["score"], "rank": hit["rank"],
                    "of": len(now["rows"]), "parts": [{**p, **hit["parts"][p["indicator"]]} for p in now["parts"]
                                                       if p["indicator"] in hit["parts"]],
                    "how": now["how"], "history": history if len(history) > 1 else []})
    return out
