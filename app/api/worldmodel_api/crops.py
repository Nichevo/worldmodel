"""Top crops: the crop on the most land in each country, US state or county, or New Zealand region,
for Land > Top crops. Each function takes `q`, the API's rows(sql, params) helper.

Countries: FAOSTAT area harvested (crop_area_ha, breakdown crop=<id>). US states and counties: USDA NASS
Census of Agriculture acres (usreg_crop_area_ha, in hectares). New Zealand's regions: Stats NZ
horticulture by regional council (nzreg_hort_<crop>_ha), which leaves out grain and grass.
"""

from __future__ import annotations

import re
from typing import Callable

from worldmodel_contract.crops import NZ_HORT, colour, name

Q = Callable[[str, list], list[dict]]

LEVELS = {
    "world": {"label": "Countries", "indicator": "crop_area_ha", "source": "FAOSTAT (FAO), area harvested",
              "note": "Hectares harvested in the year; land cropped twice counts twice. Grass and fodder are not counted."},
    "us_state": {"label": "US states", "indicator": "usreg_crop_area_ha", "parent": "USA", "level": "state",
                 "source": "USDA NASS, Census of Agriculture",
                 "note": "Acres harvested at each Census of Agriculture (orchards and vineyards by bearing and non-bearing acres), "
                         "shown in hectares. Hay and alfalfa count as a crop."},
    "us_county": {"label": "US counties", "indicator": "usreg_crop_area_ha", "parent": "USA", "level": "county",
                  "source": "USDA NASS, Census of Agriculture",
                  "note": "Acres harvested at each Census of Agriculture, shown in hectares. Counties whose figures NASS "
                          "withholds to keep farms private show the next crop down or none."},
    "nz_region": {"label": "New Zealand regions", "parent": "NZL", "level": "region",
                  "source": "Stats NZ, Agricultural Production Statistics (horticulture by regional council)",
                  "note": "Stats NZ gives regions' hectares for eight horticultural crops only (apples, kiwifruit, avocados, "
                          "wine grapes, olives, onions, potatoes, squash); grain, maize and pasture are not in it."},
}
TOP_N = 5


def _has_series(q: Q) -> bool:
    try:
        return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'series'", []))
    except Exception:  # noqa: BLE001
        return False


def _places(q: Q, level: str) -> dict[str, str]:
    """entity id -> name for the places at a level."""
    spec = LEVELS[level]
    try:
        if level == "world":
            got = q("SELECT entity_id, short_name AS name FROM entities WHERE type = 'country' AND valid_to IS NULL", [])
        elif spec["level"] == "county":
            got = q("""SELECT c.entity_id, e.short_name AS name FROM subdivisions s JOIN subdivisions c ON c.parent_id = s.entity_id
                       JOIN entities e ON e.entity_id = c.entity_id WHERE s.parent_id = ? AND c.level = 'county'""", [spec["parent"]])
        else:
            got = q("""SELECT d.entity_id, e.short_name AS name FROM subdivisions d JOIN entities e USING (entity_id)
                       WHERE d.parent_id = ? AND d.level = ?""", [spec["parent"], spec["level"]])
    except Exception:  # noqa: BLE001 - a warehouse without subdivisions
        return {}
    return {r["entity_id"]: r["name"] for r in got}


def _rows(q: Q, level: str, year: int | None) -> list[dict]:
    """(entity_id, y, crop, ha) for a level, one year or all of them."""
    where_year, params = ("AND year(s.period_start) = ?", [year]) if year is not None else ("", [])
    if level == "nz_region":
        got = q(f"""SELECT s.entity_id, year(s.period_start) AS y, s.indicator_id, s.value AS ha FROM series s
                    WHERE s.indicator_id LIKE 'nzreg_hort_%' AND s.entity_id LIKE 'NZ-%' AND s.breakdown = ''
                    AND s.variant = 'central' AND s.freq = 'A' AND s.value > 0 {where_year}""", params)
        out = []
        for r in got:
            m = re.fullmatch(r"nzreg_hort_(.+)_ha", r["indicator_id"])
            if m and m.group(1) in NZ_HORT:
                out.append({"entity_id": r["entity_id"], "y": r["y"], "crop": NZ_HORT[m.group(1)], "ha": r["ha"]})
        return out
    return q(f"""SELECT s.entity_id, year(s.period_start) AS y, substr(s.breakdown, 6) AS crop, s.value AS ha FROM series s
                 WHERE s.indicator_id = ? AND s.breakdown LIKE 'crop=%' AND s.variant = 'central' AND s.freq = 'A'
                 AND s.value > 0 {where_year}""", [LEVELS[level]["indicator"], *params])


def _years(q: Q, level: str, places: dict[str, str]) -> dict[int, int]:
    """year -> how many places have crop figures that year."""
    if level == "nz_region":
        got = q("""SELECT year(period_start) AS y, count(DISTINCT entity_id) AS n FROM series
                   WHERE indicator_id LIKE 'nzreg_hort_%' AND entity_id LIKE 'NZ-%' AND variant = 'central' GROUP BY 1""", [])
    else:
        ids = list(places)
        if not ids:
            return {}
        got = q("""SELECT year(period_start) AS y, count(DISTINCT entity_id) AS n FROM series
                   WHERE indicator_id = ? AND breakdown LIKE 'crop=%' AND variant = 'central' AND entity_id IN (SELECT unnest(?))
                   GROUP BY 1""", [LEVELS[level]["indicator"], ids])
    return {int(r["y"]): int(r["n"]) for r in got if r["y"] is not None}


def levels(q: Q) -> list[dict]:
    """Which levels have crop figures, with their places and years."""
    out = []
    if not _has_series(q):
        return out
    for lv, spec in LEVELS.items():
        places = _places(q, lv)
        years = _years(q, lv, places) if places else {}
        if years:
            out.append({"level": lv, "label": spec["label"], "places": max(years.values()), "years": sorted(years),
                        "source": spec["source"]})
    return out


def default_year(years: dict[int, int]) -> int | None:
    """The latest year with at least two thirds as many places as the best-covered year."""
    if not years:
        return None
    most = max(years.values())
    return max(y for y, n in years.items() if n >= most * 2 / 3)


def _table(q: Q, level: str, year: int | None) -> dict:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {', '.join(LEVELS)}")
    places = _places(q, level)
    years = _years(q, level, places) if places else {}
    y = year if year in years else default_year(years)
    by: dict[str, dict[str, float]] = {}
    if y is not None:
        for r in _rows(q, level, y):
            if r["entity_id"] in places:
                d = by.setdefault(r["entity_id"], {})
                d[r["crop"]] = d.get(r["crop"], 0.0) + float(r["ha"])
    return {"places": places, "years": years, "year": y, "by": by}


def top(q: Q, level: str = "world", year: int | None = None) -> dict:
    """Each place's largest crops (top five with hectares and share of its crop land), and each crop that
    is the largest somewhere with how many places and its land at this level."""
    t = _table(q, level, year)
    spec = LEVELS[level]
    rows, tally, land = [], {}, {}
    for e, crops in t["by"].items():
        total = sum(crops.values())
        ranked = sorted(crops.items(), key=lambda kv: -kv[1])
        rows.append({"id": e, "name": t["places"][e], "total_ha": total,
                     "top": [{"crop": c, "ha": v, "share": v / total * 100 if total else None} for c, v in ranked[:TOP_N]]})
        tally[ranked[0][0]] = tally.get(ranked[0][0], 0) + 1
        for c, v in crops.items():
            land[c] = land.get(c, 0.0) + v
    rows.sort(key=lambda r: r["name"])
    crops = [{"id": c, "name": name(c), "color": colour(c), "top_in": tally.get(c, 0), "ha": land[c]}
             for c in sorted(land, key=lambda c: (-tally.get(c, 0), -land[c]))]
    return {"level": level, "label": spec["label"], "year": t["year"], "years": sorted(t["years"]), "unit": "ha",
            "source": spec["source"], "note": spec["note"], "places": rows, "crops": crops[:80]}


def crop_where(q: Q, crop: str, level: str = "world", year: int | None = None) -> dict:
    """One crop's hectares in every place at a level, and its share of each place's crop land."""
    t = _table(q, level, year)
    out = {}
    for e, crops in t["by"].items():
        v = crops.get(crop)
        if v:
            total = sum(crops.values())
            out[e] = {"ha": v, "share": v / total * 100 if total else None,
                      "rank": 1 + sum(1 for x in crops.values() if x > v)}
    return {"crop": crop, "name": name(crop), "color": colour(crop), "level": level, "year": t["year"], "values": out}


def entity_crops(q: Q, entity: str, year: int | None = None) -> dict:
    """One place's crops by land over the years held (for a country page or a region): {years, crops: [{id, name, color, ha: {year: v}}]}."""
    if entity.startswith("NZ-"):
        lv = "nz_region"
    elif entity.startswith("US-"):
        lv = "us_county" if re.fullmatch(r"US-\d{5}", entity) else "us_state"
    else:
        lv = "world"
    if lv == "nz_region":
        got = [r for r in _rows(q, lv, None) if r["entity_id"] == entity]
    else:
        got = q("""SELECT year(period_start) AS y, substr(breakdown, 6) AS crop, value AS ha FROM series
                   WHERE entity_id = ? AND indicator_id = ? AND breakdown LIKE 'crop=%' AND variant = 'central' AND freq = 'A'
                   AND value > 0""", [entity, LEVELS[lv]["indicator"]])
    by: dict[str, dict[int, float]] = {}
    for r in got:
        by.setdefault(r["crop"], {})[int(r["y"])] = float(r["ha"])
    years = sorted({y for d in by.values() for y in d})
    last = years[-1] if years else None
    order = sorted(by, key=lambda c: -by[c].get(last, 0.0))
    return {"entity_id": entity, "level": lv, "years": years, "source": LEVELS[lv]["source"],
            "crops": [{"id": c, "name": name(c), "color": colour(c), "ha": {str(y): v for y, v in sorted(by[c].items())}}
                      for c in order[:40]]}
