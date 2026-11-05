"""Sectors: one industry across the globe, followed stage by stage (sectors.yaml).

Shared by the pipeline (which sums trade by stage and reads production) and the app
(which draws the pages). Indicator ids for a stage `s`:

    sx_<s>     exports, US$ (entity = exporter; breakdown "partner=<importer>" per route)
    sxq_<s>    exports, tonnes (the same shape)
    sm_<s>     imports, US$ (entity = importer; totals only)
    smq_<s>    imports, tonnes
    sp_<s>     production, in the stage's unit (FAOSTAT, World Mining Data, USGS)
    sr_<s>     reserves (USGS), for mined stages
    tgx_<cc>   exports of HS chapter cc, US$ (By country view); tgm_<cc> imports
    price_<p>  World Bank Pink Sheet price p (entity "world", monthly)
"""

from __future__ import annotations

from functools import lru_cache

from worldmodel_contract import catalogue

TRADE_UNIT = "US dollars"
PARTNER = "partner="


@lru_cache
def _data() -> dict:
    return catalogue._yaml("sectors.yaml")


def sectors() -> list[dict]:
    return _data()["sectors"]


def sector(sector_id: str) -> dict | None:
    return next((s for s in sectors() if s["id"] == sector_id), None)


def groups() -> dict[str, str]:
    return _data()["groups"]


def chapters() -> dict[str, str]:
    return {str(k).zfill(2): v for k, v in _data()["chapters"].items()}


def prices() -> dict[str, str]:
    """Pink Sheet price id -> the column heading it is read from."""
    return _data()["sector_prices"]


def battery() -> dict:
    d = _data()
    return {"materials": d["battery_materials"], "sectors": d["battery_material_sectors"], "rules": d["battery_rules"]}


def stages() -> list[tuple[dict, dict]]:
    """Every (sector, stage), in file order."""
    return [(s, st) for s in sectors() for st in s["stages"]]


def stage(stage_id: str) -> tuple[dict, dict] | None:
    return next(((s, st) for s, st in stages() if st["id"] == stage_id), None)


def stage_unit(st: dict) -> str:
    return st.get("unit") or "tonnes"


def production_indicator(st: dict) -> str | None:
    p = st.get("production") or {}
    if p.get("indicator"):
        return p["indicator"]
    return f"sp_{st['id']}" if p else None


def hs_stage(hs6: str) -> str | None:
    """The stage a 6-digit HS code belongs to (longest matching prefix), or None."""
    return _hs_index().get(hs6[:6]) or _hs_index().get(hs6[:4]) or _hs_index().get(hs6[:2])


@lru_cache
def _hs_index() -> dict[str, str]:
    out: dict[str, str] = {}
    for _, st in stages():
        for code in st.get("hs", []):
            out.setdefault(str(code), st["id"])
    return out


def hs_prefixes() -> list[tuple[str, str]]:
    """(HS prefix, stage id), longest prefixes first, for matching in SQL."""
    return sorted(_hs_index().items(), key=lambda kv: -len(kv[0]))


def concentration(values: list[float]) -> dict:
    """How concentrated supply is: the top-3 share and the Herfindahl-Hirschman index
    (sum of squared percentage shares: under 1,500 unconcentrated, over 2,500 highly)."""
    vals = sorted((v for v in values if v and v > 0), reverse=True)
    total = sum(vals)
    if not total:
        return {"top3": None, "hhi": None, "n": 0}
    shares = [100 * v / total for v in vals]
    return {"top3": round(sum(shares[:3]), 1), "hhi": round(sum(s * s for s in shares)), "n": len(vals)}


def validate() -> list[str]:
    problems = []
    seen: set[str] = set()
    ents = catalogue.entities()
    for s in sectors():
        if s["group"] not in groups():
            problems.append(f"sectors: {s['id']} group {s['group']} unknown")
        for p in s.get("prices", []):
            if p not in prices():
                problems.append(f"sectors: {s['id']} price {p} unknown")
        ids = {st["id"] for st in s["stages"]}
        for st in s["stages"]:
            if st["id"] in seen:
                problems.append(f"sectors: stage {st['id']} appears twice")
            seen.add(st["id"])
            for code in st.get("hs", []):
                if not str(code).isdigit() or len(str(code)) not in (2, 4, 6):
                    problems.append(f"sectors: {st['id']} HS code {code} must be 2, 4 or 6 digits")
        for c in s.get("companies", []):
            if c["step"] not in ids:
                problems.append(f"sectors: {s['id']} company {c['name']} step {c['step']} unknown")
            if c["country"] not in ents:
                problems.append(f"sectors: {s['id']} company {c['name']} country {c['country']} unknown")
    return problems
