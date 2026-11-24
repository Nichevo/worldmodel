"""Indicators that sit under another one, so the indicator drop-downs can nest them:
Male population and Population aged 65 and over under Population, life expectancy for
women and men under Life expectancy, and so on.

Each child has a parent and a kind:
  part    a piece of the parent; the pieces add up to it (men + women = everyone)
  sex     the parent's figure for women or men only (a rate, not a piece of a total)
  share   a piece of the parent as a share of it (% of the population aged 65 and over)

`PARENTS` lists them by hand. Indicators a source lists itself (every World Bank series)
are matched by their series codes: a WDI code with a .MA. (male) or .FE. (female) part
sits under the same code without it, when that indicator is loaded too.
"""
from __future__ import annotations

PARENTS: dict[str, tuple[str, str]] = {
    "pop_male": ("pop_total", "part"),
    "pop_female": ("pop_total", "part"),
    "pop_age_0_14": ("pop_total", "part"),
    "pop_age_15_64": ("pop_total", "part"),
    "pop_age_65_plus": ("pop_total", "part"),
    "pop_by_age_sex": ("pop_total", "part"),
    "urban_population": ("pop_total", "part"),
    "wdi_sp_rur_totl": ("pop_total", "part"),
    "pop_share_0_14": ("pop_total", "share"),
    "pop_share_65_plus": ("pop_total", "share"),
    "urban_share": ("pop_total", "share"),
    "life_expectancy_male": ("life_expectancy", "sex"),
    "life_expectancy_female": ("life_expectancy", "sex"),
    "wic_mys_male": ("wic_mys", "sex"),
    "wic_mys_female": ("wic_mys", "sex"),
}

KIND_TEXT = {"part": "a part of", "sex": "women's or men's figure for", "share": "a share of"}


def _sex_free(code: str) -> str | None:
    """A WDI series code with its male/female part taken out (SE.PRM.CMPT.MA.ZS -> SE.PRM.CMPT.ZS);
    None when the code has no such part."""
    parts = code.split(".")
    kept = [p for p in parts if p.upper() not in ("MA", "FE")]
    return ".".join(kept) if len(kept) < len(parts) else None


def parents(indicators: list[dict]) -> dict[str, dict[str, str]]:
    """{child id: {"parent": id, "kind": part|sex|share}} for the indicators given (each a dict
    with indicator_id and sources [{source_id, series}]). Only pairs where both are present."""
    ids = {i["indicator_id"] for i in indicators}
    out = {c: {"parent": p, "kind": k} for c, (p, k) in PARENTS.items() if c in ids and p in ids}
    by_code: dict[str, str] = {}
    for i in indicators:
        for s in i.get("sources") or []:
            if str(s.get("source_id", "")).startswith("wdi") and s.get("series"):
                by_code.setdefault(str(s["series"]).upper(), i["indicator_id"])
    for i in indicators:
        if i["indicator_id"] in out:
            continue
        for s in i.get("sources") or []:
            if not str(s.get("source_id", "")).startswith("wdi") or not s.get("series"):
                continue
            base = _sex_free(str(s["series"]).upper())
            parent = by_code.get(base) if base else None
            if parent and parent != i["indicator_id"]:
                out[i["indicator_id"]] = {"parent": parent, "kind": "sex"}
                break
    return out
