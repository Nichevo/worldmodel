"""Energy flow (Sankey) from an energy balance: where a country's energy comes from,
what is turned into electricity, and which sectors use it.

The balance is stored as indicator energy_balance_pj with breakdown
flow=<balance row>|fuel=<fuel>: MBIE's energy balance tables for New Zealand, and for every
country the UN Statistics Division's energy statistics, turned into the same rows by
`unsd_rows()` (fuels already grouped). `flow()` turns one year of it into nodes and links:

    fuel group (primary supply)  ->  sector that uses it directly
    fuel group                   ->  Electricity generation  ->  Electricity  ->  sector
    Electricity generation       ->  Heat (district and CHP heat sold)  ->  sector
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
    # the group names themselves, as unsd_rows() writes them
    "coal": "Coal", "oil": "Oil", "nuclear": "Nuclear", "bioenergy": "Bioenergy", "waste": "Waste", "heat": "Heat",
    "other": "Other",
}
GROUP_ORDER = ["Coal", "Oil", "Natural gas", "Nuclear", "Hydro", "Geothermal", "Wind", "Solar", "Bioenergy", "Waste",
               "Waste heat", "Other"]
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
    "industry": "Industry",  # unsd_rows() writes industry as one row
}
SECTOR_IDS = {"Agriculture, forestry and fishing": "agriculture", "Industry": "industry", "Commercial": "commercial",
              "Transport": "transport", "Residential": "residential", "Non-energy use": "non_energy"}
GEN, ELEC, HEAT, CONV, LOSS = "Electricity generation", "Electricity", "Heat", "Conversion losses", "Losses and own use"


def group_of(fuel: str) -> str:
    return FUEL_GROUP.get(_key(fuel), "Other")


def flow(rows: list[tuple[str, str, float]], min_value: float = 0.05) -> dict:
    """One year of balance rows (flow, fuel, value in PJ) as {nodes, links, totals}."""
    links: dict[tuple[str, str], float] = {}
    supply: dict[str, float] = {}
    transform: dict[str, float] = {}
    gen_in = gen_out = heat_out = 0.0

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
            elif g == HEAT:
                heat_out += max(v, 0.0)
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
        if g not in (ELEC, HEAT):
            add(g, LOSS, -v)
    add(GEN, ELEC, gen_out)
    add(GEN, HEAT, heat_out)
    add(GEN, CONV, gen_in - gen_out - heat_out)
    kept = {k: round(v, 3) for k, v in links.items() if v >= min_value}
    names = {n for k in kept for n in k}
    kind = lambda n: ("source" if n in GROUP_ORDER else "electricity" if n in (GEN, ELEC, HEAT)  # noqa: E731
                      else "loss" if n in (CONV, LOSS) else "use")
    order = GROUP_ORDER + [GEN, ELEC, HEAT] + list(SECTOR_IDS) + [LOSS, CONV]
    nodes = [{"name": n, "kind": kind(n)} for n in sorted(names, key=lambda n: order.index(n) if n in order else 99)]
    return {
        "nodes": nodes,
        "links": [{"source": a, "target": b, "value": v} for (a, b), v in sorted(kept.items(), key=lambda kv: -kv[1])],
        "totals": {"primary_supply": round(sum(supply.values()), 3),
                   "supply_by_group": {g: round(v, 3) for g, v in supply.items() if abs(v) >= min_value},
                   "electricity_generated": round(gen_out, 3),
                   "heat_generated": round(heat_out, 3),
                   "use_by_sector": {s: round(sum(v for (a, b), v in links.items() if b == s), 3) for s in SECTOR_IDS}},
    }


# ----------------------------------------------------------------------------- UN energy statistics
# The UN Statistics Division's energy statistics (dataflow DF_UNDATA_ENERGY) give each commodity's
# transactions in its own unit with a factor to terajoules. unsd_rows() turns one country-year
# into balance rows like MBIE's, with the fuel already a group, so flow() draws them the same way.
UN_GROUP = {
    "01": "Coal", "02": "Coal", "03": "Coal", "11": "Coal", "12": "Coal", "20": "Oil", "30": "Natural gas",
    "41": "Oil", "42": "Oil", "43": "Oil", "44": "Oil", "45": "Oil", "46": "Oil", "GR": "Oil",
    "51": "Bioenergy", "52": "Bioenergy", "53": "Bioenergy", "61": "Waste", "62": "Waste",
    "70": "Electricity", "80": "Heat", "DG": "Geothermal", "DS": "Solar",
}
# Commodities made from others (coke, refined oil products, charcoal, manufactured gases): what is
# made counts as transformation output, not as the country's own primary production.
UN_SECONDARY = ("03", "12", "43", "44", "46", "GR", "5160")
UN_AGGREGATE = {"0100": ("0110", "0121", "0129"), "0200": ("0210", "0220")}  # totals over their parts
UN_SKIP = {"5212", "5222", "5232", "8000T", "7000T", "9101", "EC", "WF"}  # "of which" lines, capacity, uranium
# Electricity counted at its output (hydro, wind, solar, tide) or at the heat behind it: nuclear at
# 33% and geothermal at 10% efficiency, as the UN's own balances do, when no heat input is given.
UN_PRIMARY_POWER = {"7000H": ("Hydro", 1.0), "7000W": ("Wind", 1.0), "7000S": ("Solar", 1.0), "7000O": ("Hydro", 1.0),
                    "7000N": ("Nuclear", 1 / 0.33), "7000G": ("Geothermal", 1 / 0.10)}
UN_SUPPLY = {"03": "Imports", "04": "Exports", "051": "International transport", "052": "International transport",
             "06": "Stock change"}
UN_LOSS = ("09", "101", "103", "104", "105")
UN_SECTOR = {"11": "Non-energy use", "121": "Industry", "122": "Transport", "1231": "Residential", "1232": "Agriculture",
             "1235": "Commercial", "1234": "Commercial"}
UN_TRANSACTIONS = ["01", "03", "04", "051", "052", "06", "08", "088", "09", "101", "103", "104", "105", "11", "121",
                   "122", "123", "1231", "1232", "1234", "1235"]


def un_group(commodity: str) -> str | None:
    c = str(commodity)
    if c in UN_SKIP or c in UN_PRIMARY_POWER:
        return None
    return UN_GROUP.get(c[:2]) or UN_GROUP.get(c)


def unsd_rows(cells: dict[tuple[str, str], float]) -> list[tuple[str, str, float]]:
    """One country-year of UN energy statistics, {(commodity, transaction): terajoules}, as balance
    rows (flow, fuel group, PJ) for flow(). Signs follow MBIE's: inputs to transformation and losses
    negative, everything else as published (exports and stock building subtract from supply)."""
    cells = dict(cells)
    for total, parts in UN_AGGREGATE.items():  # use the parts where given, the total for the rest
        for t in {t for (c, t) in cells if c == total}:
            if any((p, t) in cells for p in parts):
                cells.pop((total, t))
    out: dict[tuple[str, str], float] = {}

    def put(flow_name: str, group: str, tj: float) -> None:
        if tj:
            out[(flow_name, group)] = out.get((flow_name, group), 0.0) + tj / 1000

    commodities = {c for c, _ in cells}
    geo_heat = ("DG", "088") in cells
    for c in commodities:
        g = un_group(c)
        get = lambda t: cells.get((c, t), 0.0)  # noqa: E731
        if c in UN_PRIMARY_POWER:
            if c == "7000G" and geo_heat:
                continue  # the heat behind it is given as DG into power plants
            group, factor = UN_PRIMARY_POWER[c]
            put("Indigenous production", group, get("01") * factor)
            put("Electricity generation", group, -get("01") * factor)
            continue
        if g is None:
            continue
        if g in ("Electricity", "Heat"):
            put("Electricity generation", g, get("01"))
        elif c.startswith(UN_SECONDARY) or c in UN_SECONDARY:
            put("Other transformation", g, get("01"))
        elif c in ("DG", "DS") and (c, "01") not in cells:  # heat used directly, often given by use only
            put("Indigenous production", g, sum(get(t) for t in ("08", "09", "11", "121", "122", "123")))
        else:
            put("Indigenous production", g, get("01"))
        for t, name in UN_SUPPLY.items():
            put(name, g, get(t))
        put("Electricity generation", g, -get("088"))
        if (c, "08") in cells:
            put("Other transformation", g, -(get("08") - get("088")))
        put("Losses and own use", g, -sum(get(t) for t in UN_LOSS))
        for t, name in UN_SECTOR.items():
            put(name, g, get(t))
        rest = get("123") - sum(get(t) for t in ("1231", "1232", "1234", "1235"))
        if rest > 0.5:
            put("Commercial", g, rest)
    return [(f, g, round(v, 4)) for (f, g), v in sorted(out.items()) if abs(v) >= 0.0005]
