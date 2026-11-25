"""Map layer details: which map layers can be counted by country, and what each item's size
and category are. Shared by the data side (layer_tables.py: the layer_items table and the
map_layers indicators) and the app (the Details page behind every map layer).

Only figures the layer's source carries are used. A layer with no size figure says so
(size is None), and its page shows counts and categories only.

kind:
  stored  a dot layer in the warehouse's layers table: the build lists every item in layer_items,
          with a country from the item itself or, where the source gives none, from where it sits
  lines   a geo_features layer (cables, pipelines): each line lists the countries it touches
  trees   street trees (geo_features), counted by council instead of by country
  live    worked out when the page is opened (fires, heatwaves, City stress), not kept
  events  located fighting and unrest (conflict_events), over the last twelve months"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SOURCE_ID = "map_layers"  # the source of the layers' indicators (worked out by the build)


@dataclass(frozen=True)
class Size:
    prop: str            # the item's property holding the figure
    label: str           # "Beds"
    unit: str            # "beds"
    decimals: int = 0
    total: Literal["sum", "mean", "max"] = "sum"  # how a country's items add up
    bands: tuple[float, ...] = ()  # edges of the Sizes tab's bands; empty: no bands


@dataclass(frozen=True)
class Official:
    """An official total to compare the layer with, to show how complete it is."""
    indicator: str
    label: str
    # how the official figure becomes the same thing the layer adds up:
    # per1000 / per100k: per 1,000 or 100,000 people (times population); kw_to_mw: kilowatts; count: as is
    as_total: Literal["per1000", "per100k", "kw_to_mw", "count"]
    of: Literal["size", "count"]  # compared with the layer's size total, or its count
    coverage: bool = True  # False: shown beside as a reference only (it counts something wider)


@dataclass(frozen=True)
class LayerDetail:
    id: str
    one: str                     # "hospital"
    many: str                    # "hospitals"
    kind: Literal["stored", "lines", "trees", "live", "events"]
    domain: str
    size: Size | None = None
    category: tuple[str, str] | None = None   # (prop, label)
    fields: tuple[tuple[str, str], ...] = ()  # more columns for the item list: (prop, label)
    official: tuple[Official, ...] = ()
    note: str = ""               # what the source leaves out, shown at the top of the page
    country_from: str = "item"   # "item": the source says; "place": worked out from where it sits; "mixed"
    indicators: bool = True      # count, per million people and the size total as indicators
    by_country: bool = True      # False: listed only (chokepoints)


BEDS = Size("beds", "Beds", "beds", bands=(200, 500, 1000, 2000))
LAYERS: tuple[LayerDetail, ...] = (
    LayerDetail("hospitals", "hospital", "hospitals", "stored", "health", BEDS, ("found", "Listed by"),
                (("kind", "Kind"), ("list", "Official list")),
                official=(Official("hospitals_official", "Official hospitals (national statistics)", "count", "count"),
                          Official("who_hospitals_per_100k", "Official hospitals (WHO, 2013)", "per100k", "count"),
                          Official("hospital_beds_per_1000", "Official beds (World Bank)", "per1000", "size")),
                note="Hospitals from Wikidata, OpenStreetMap, Overture (chosen countries) and official lists, each counted "
                     "once where lists share it. Many have no bed count, so bed totals are what is listed, not every bed "
                     "in the country; compare the hospital counts instead."),
    LayerDetail("military_bases", "base", "military bases", "stored", "military", None, ("type", "Kind"),
                (("operator", "Run by"),),
                note="No size figure: Wikidata gives each base's kind and who runs it, and has the well-known bases only."),
    LayerDetail("ports", "port", "ports (by ship calls)", "stored", "transport",
                Size("calls", "Ship calls a year", "calls", bands=(500, 2000, 5000, 20000)), ("top", "Main trade"),
                (("imp_share", "Share of sea imports"), ("exp_share", "Share of sea exports"), ("year", "Year")),
                (Official("gfp_ports", "Ports and terminals (Global Firepower)", "count", "count", coverage=False),)),
    LayerDetail("ports_all", "port", "ports (World Port Index)", "stored", "transport", None, ("size", "Harbour size"),
                (("type", "Harbour type"), ("depth", "Channel depth (m)"), ("locode", "UN code")),
                (Official("gfp_ports", "Ports and terminals (Global Firepower)", "count", "count", coverage=False),),
                note="Harbour size is the World Port Index's grade (very small to large), not a measured figure."),
    LayerDetail("airports", "airport", "airports", "stored", "transport", None, ("size", "Size"),
                (("iata", "IATA"), ("city", "City")),
                (Official("gfp_airports", "All airports (Global Firepower)", "count", "count", coverage=False),),
                note="Large and medium airports with scheduled flights only (OurAirports grades them; no passenger figures "
                     "on the map)."),
    LayerDetail("power_plants", "power plant", "power plants", "stored", "energy",
                Size("mw", "Capacity", "MW", 0, bands=(10, 100, 500, 1000)), ("fuel", "Fuel"),
                (("year", "Built"), ("owner", "Owner")),
                (Official("fb_elec_capacity", "Generating capacity (Factbook)", "kw_to_mw", "size"),),
                note="WRI's Global Power Plant Database, last updated 2021: newer plants are missing."),
    LayerDetail("lng_terminals", "LNG terminal", "LNG terminals", "stored", "energy",
                Size("capacity", "Capacity", "Mt a year", 1, bands=(1, 5, 10, 20)), ("status", "Status"),
                (("facility", "Import or export"), ("owner", "Owner"), ("start", "Start"))),
    LayerDetail("universities", "university", "universities", "stored", "education",
                Size("students", "Students", "students", bands=(5000, 20000, 50000, 100000)),
                country_from="place", note="Universities with articles in three or more Wikipedias; students where given."),
    LayerDetail("companies", "company", "big company head offices", "stored", "economy",
                Size("revenue_usd", "Revenue", "US$", bands=(1e9, 1e10, 5e10, 1e11)), ("industry", "Industry"),
                country_from="place", note="Revenue in US dollars at that year's exchange rate."),
    LayerDetail("major_cities", "city", "cities of a million or more", "stored", "population",
                Size("population", "People", "people", bands=(1e6, 2e6, 5e6, 1e7)), ("capital", "Capital"),
                country_from="place"),
    LayerDetail("transit_stations", "station", "metro and rail stations", "stored", "transport", None, ("system", "System"),
                country_from="place", note="No size figure for stations."),
    LayerDetail("heritage_sites", "site", "World Heritage sites", "stored", "culture", None, ("type", "Type"),
                (("year", "Listed"), ("danger", "In danger")),
                (Official("heritage_sites", "UNESCO's own count", "count", "count"),),
                note="A site shared by several countries counts once for each."),
    LayerDetail("visited_sites", "place", "most visited places", "stored", "culture",
                Size("visitors", "Visitors a year", "visitors", bands=(2e6, 5e6, 1e7, 2e7)), fields=(("year", "Year"),)),
    LayerDetail("volcanoes", "volcano", "volcanoes", "stored", "hazards", None, ("type", "Type"),
                (("last", "Last eruption"), ("elevation", "Height (m)"))),
    LayerDetail("earthquakes", "earthquake", "earthquakes of magnitude 6 or more", "stored", "hazards",
                Size("mag", "Magnitude", "", 1, "max", (6.5, 7, 7.5, 8)), fields=(("date", "Date"), ("depth", "Depth (km)")),
                country_from="place", note="Since 1900. Offshore quakes count for the nearest country within about 20 km; "
                                           "the rest are listed as at sea."),
    LayerDetail("tide_gauges", "tide gauge", "tide gauges", "stored", "climate",
                Size("trend", "Sea level trend", "mm a year", 1, "mean"), fields=(("trend30", "Last 30 years"), ("years", "Years"))),
    LayerDetail("antarctic_stations", "station", "Antarctic research stations", "stored", "polar", None,
                fields=(("operator", "Run by"), ("opened", "Opened")), note="Counted by the country that runs each station."),
    LayerDetail("cable_landings", "landing point", "cable landing points", "stored", "transport", None,
                note="No size figure for landing points."),
    LayerDetail("chokepoints", "chokepoint", "shipping chokepoints", "stored", "transport",
                Size("daily", "Ships a day", "ships", 0), fields=(("year", "Year"),), indicators=False, by_country=False),
    LayerDetail("cables", "cable", "undersea cables", "lines", "transport", Size("length_km", "Length", "km"),
                fields=(("rfs", "Ready"), ("owners", "Owners")), indicators=False,
                note="A cable counts for every country it lands in; its full length is shown, not the part near each country."),
    LayerDetail("gas_pipelines", "pipeline", "gas pipelines", "lines", "energy", Size("length_km", "Length", "km"),
                ("status", "Status"), (("capacity", "Capacity"), ("capacity_unit", "Unit"), ("owner", "Owner")), indicators=False,
                note="A pipeline counts for every country it crosses; its full length is shown."),
    LayerDetail("oil_pipelines", "pipeline", "oil pipelines", "lines", "energy", Size("length_km", "Length", "km"),
                ("status", "Status"), (("capacity", "Capacity"), ("capacity_unit", "Unit"), ("owner", "Owner")), indicators=False,
                note="A pipeline counts for every country it crosses; its full length is shown."),
    LayerDetail("street_trees", "tree", "street trees", "trees", "nature", Size("height", "Height", "m", 1, "mean"),
                ("common", "Kind"), (("species", "Species"), ("planted", "Planted")), indicators=False,
                note="Counted by council, from the councils' own tree lists."),
    LayerDetail("fires_now", "fire", "fires in the last 24 hours", "live", "hazards",
                Size("frp", "Fire power", "MW", 0), indicators=False, country_from="place",
                note="Worked out when you open this page from NASA FIRMS; nearby fires are grouped into one dot."),
    LayerDetail("fires_week", "fire", "fires in the last 7 days", "live", "hazards",
                Size("frp", "Fire power", "MW", 0), indicators=False, country_from="place",
                note="Worked out when you open this page from NASA FIRMS; nearby fires are grouped into one dot."),
    LayerDetail("heat_now", "city", "cities facing a heatwave", "live", "climate",
                Size("peak", "Hottest day", "°C", 1, "max"), indicators=False, country_from="place"),
    LayerDetail("city_stress", "city", "cities with a stress score", "live", "population",
                Size("score", "Stress score", "0 to 10", 1, "mean"), indicators=False),
    LayerDetail("conflict_events", "event", "fighting and unrest events (last 12 months)", "events", "conflict",
                Size("deaths", "Deaths", "deaths", bands=(1, 10, 100, 1000)), ("kind", "Kind"), (("day", "Date"), ("place", "Place")),
                indicators=False, note="UCDP and ACLED events of the last twelve months; War trackers has the full history."),
)
BY_ID = {d.id: d for d in LAYERS}
NOT_COUNTED = {
    "live_planes": "Planes are fetched only for the area in view, so they can't be counted by country.",
    "live_ships": "Ships are fetched only for the area in view, so they can't be counted by country.",
    "live_military": "Military planes are fetched only for the area in view, so they can't be counted by country.",
}


def indicator_ids(d: LayerDetail) -> dict[str, str]:
    """The indicators a layer gives: count, per million people and, if it has one, its size total."""
    if not d.indicators or d.kind != "stored":
        return {}
    out = {"count": f"map_{d.id}_count", "per_m": f"map_{d.id}_per_m"}
    if d.size and d.size.total == "sum":
        out["size"] = f"map_{d.id}_{d.size.prop}"
    return out


def indicators(found: set[str] | None = None) -> list[dict]:
    """Catalogue-shaped indicators for the layers in `found` (all if None)."""
    out = []
    for d in LAYERS:
        if found is not None and d.id not in found:
            continue
        ids = indicator_ids(d)
        if not ids:
            continue
        many = d.many[0].upper() + d.many[1:]
        listed = "as listed on the map (only what the map layer's source has, so lower than the real total where it is patchy)"
        out.append(_ind(ids["count"], f"{many} on the map", f"Number of {d.many} in the country {listed}.",
                        d.many, d.domain, {"method": "sum"}, 0, (0, 1e7)))
        out.append(_ind(ids["per_m"], f"{many} on the map per million people", f"Number of {d.many} per million people, {listed}.",
                        "per million people", d.domain,
                        {"method": "ratio", "numerator": ids["count"], "denominator": "pop_total", "multiplier": 1e6}, 2, (0, 1e6)))
        if "size" in ids:
            s = d.size
            out.append(_ind(ids["size"], f"{s.label} of {d.many} on the map", f"{s.label} ({s.unit}) of all {d.many} {listed}.",
                            s.unit, d.domain, {"method": "sum"}, s.decimals, (0, 1e15)))
    return out


def _ind(id: str, name: str, description: str, unit: str, domain: str, agg: dict, decimals: int, bounds) -> dict:
    return {"id": id, "name": name, "description": description, "domain": domain, "unit": unit, "decimals": decimals,
            "frequency": "A", "aggregation": agg, "bounds": list(bounds), "breakdowns": [], "synonyms": ["map layer"],
            "sources": [{"source_id": SOURCE_ID, "series": id, "scale": 1.0, "notes": ""}], "default_on": True,
            "definition": "exploratory"}
