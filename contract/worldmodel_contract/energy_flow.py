"""Energy flow (Sankey) from an energy balance: where a country's energy comes from,
what is turned into electricity, and which sectors use it.

The balance is stored as indicator energy_balance_pj with breakdown
flow=<balance row>|fuel=<fuel> (MBIE's energy balance tables for New Zealand; other
countries' balances can use the same rows later). `flow()` turns one year of it into
nodes and links:

    fuel group (primary supply)  ->  sector that uses it directly
    fuel group                   ->  Electricity generation  ->  Electricity  ->  sector
    Electricity generation       ->  Conversion losses (fuel in less electricity out)
    fuel group / Electricity     ->  Losses and own use (refining, transmission, own use)

Supply is primary energy supply: production and imports less exports, stock building
and international transport, so exports do not appear. Kept in the contract so the
data side (the totals it stores) and the API (the chart) group fuels the same way.
"""

from __future__ import annotations

import re


def _key(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


FUEL_GROUP = {
    "bituminous": "Coal", "subbituminous": "Coal", "lignite": "Coal",
    "crudesfeedstocksngl": "Oil", "lpg": "Oil", "petrol": "Oil", "diesel": "Oil", "fueloil": "Oil",
    "avfuelkero": "Oil", "others": "Oil",
    "naturalgas": "Natural gas", "hydro": "Hydro", "geothermal": "Geothermal", "solar": "Solar", "wind": "Wind",
    "liquidbiofuels": "Bioenergy", "biogas": "Bioenergy", "solidbiofuels": "Bioenergy",
    "electricity": "Electricity", "wasteheat": "Waste heat",
}
GROUP_ORDER = ["Coal", "Oil", "Natural gas", "Hydro", "Geothermal", "Wind", "Solar", "Bioenergy", "Waste heat", "Other"]
RENEWABLE = {"Hydro", "Geothermal", "Solar", "Wind", "Bioenergy"}
SUPPLY_SIGN = {"indigenousproduction": 1, "imports": 1, "exports": -1, "stockchange": -1, "internationaltransport": -1}
GENERATION = {"electricitygeneration", "cogeneration"}
OTHER_TRANSFORM = {"fuelproduction", "othertransformation"}
LOSSES = {"lossesandownuse"}
SECTOR = {
    "agriculture": "Agriculture, forestry and fishing", "forestryandlogging": "Agriculture, forestry and fishing",
    "fishing": "Agriculture, forestry and fishing",
    "mining": "Industry", "foodprocessing": "Industry", "textiles": "Industry", "woodpulppaperandprinting": "Industry",
    "chemicals": "Industry", "nonmetallicminerals": "Industry", "basicmetals": "Industry",
    "mechanicalelectricalequipment": "Industry", "buildingandconstruction": "Industry", "unallocated": "Industry",
    "commercial": "Commercial", "transport": "Transport", "residential": "Residential", "nonenergyuse": "Non-energy use",
}
SECTOR_IDS = {"Agriculture, forestry and fishing": "agriculture", "Industry": "industry", "Commercial": "commercial",
              "Transport": "transport", "Residential": "residential", "Non-energy use": "non_energy"}
GEN, ELEC, CONV, LOSS = "Electricity generation", "Electricity", "Conversion losses", "Losses and own use"


def group_of(fuel: str) -> str:
    return FUEL_GROUP.get(_key(fuel), "Other")


def flow(rows: list[tuple[str, str, float]], min_value: float = 0.05) -> dict:
    """One year of balance rows (flow, fuel, value in PJ) as {nodes, links, totals}."""
    links: dict[tuple[str, str], float] = {}
    supply: dict[str, float] = {}
    transform: dict[str, float] = {}
    gen_in = gen_out = 0.0

    def add(a: str, b: str, v: float) -> None:
        if v > 0:
            links[(a, b)] = links.get((a, b), 0.0) + v

    for entry, fuel, v in rows:
        e, g = _key(entry), group_of(fuel)
        if e in SUPPLY_SIGN:
            supply[g] = supply.get(g, 0.0) + SUPPLY_SIGN[e] * v
        elif e in GENERATION:
            if g == ELEC:
                gen_out += max(v, 0.0)
            elif v < 0:
                add(g, GEN, -v)
                gen_in += -v
        elif e in OTHER_TRANSFORM:
            transform[g] = transform.get(g, 0.0) + v
        elif e in LOSSES:
            add(g, LOSS, -v)
        elif e in SECTOR:
            add(g, SECTOR[e], v)
    for g, v in transform.items():  # refining and other conversions: what is lost within a fuel group
        if g != ELEC:
            add(g, LOSS, -v)
    add(GEN, ELEC, gen_out)
    add(GEN, CONV, gen_in - gen_out)
    kept = {k: round(v, 3) for k, v in links.items() if v >= min_value}
    names = {n for k in kept for n in k}
    kind = lambda n: ("source" if n in GROUP_ORDER else "electricity" if n in (GEN, ELEC)  # noqa: E731
                      else "loss" if n in (CONV, LOSS) else "use")
    order = GROUP_ORDER + [GEN, ELEC] + list(SECTOR_IDS) + [LOSS, CONV]
    nodes = [{"name": n, "kind": kind(n)} for n in sorted(names, key=lambda n: order.index(n) if n in order else 99)]
    return {
        "nodes": nodes,
        "links": [{"source": a, "target": b, "value": v} for (a, b), v in sorted(kept.items(), key=lambda kv: -kv[1])],
        "totals": {"primary_supply": round(sum(supply.values()), 3),
                   "supply_by_group": {g: round(v, 3) for g, v in supply.items() if abs(v) >= min_value},
                   "electricity_generated": round(gen_out, 3),
                   "use_by_sector": {s: round(sum(v for (a, b), v in links.items() if b == s), 3) for s in SECTOR_IDS}},
    }
