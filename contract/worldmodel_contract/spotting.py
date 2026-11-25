"""Spotting things in the satellite pictures and maps: layers the app works out itself.

Shared by the app's server (worldmodel_api/spotting.py) and the web app (the Spotting page and
map layers 8 Land change, 9 Water gained and lost, 0 Spotted by AI).

    Land change    two years of land cover compared pixel by pixel (Esri 10 m 2017-2025, or ESA
                   CCI 300 m 1992-2020); a change counts only where it still holds the year before
                   the end year too, and specks smaller than a few pixels are dropped.
    Water          the EU Joint Research Centre's Global Surface Water "transitions" map: every
                   30 m pixel's water in 1984-1999 against 2000-2021, from Landsat.
    Ask the picture  the satellite picture of a place, what the land cover says and the layer items
                   nearby, sent to a local model in Ollama that can see pictures.
    Area scan      an area cut into squares about 5 km across, each sent to a local model with a list of
                   things to look for; what it reports becomes the "Spotted by AI" layer, with
                   your yes / no marks kept so each thing's hit rate shows.
"""

from __future__ import annotations

from dataclasses import dataclass

# ----------------------------------------------------------------------------- land change
# The kinds of cover a land cover picture is read into (the Land page's kinds).
KINDS = ("trees", "crops", "grass", "shrub", "bare", "snow", "built", "water")

# Esri Land Cover 10 m (Impact Observatory) as its "Cartographic Renderer" draws it: colour -> kind.
# Clouds are left out (no reading for that pixel that year).
LC10_COLOURS: dict[str, tuple[str, str | None]] = {
    "Water": ("#419bdf", "water"), "Trees": ("#397d49", "trees"), "Flooded plants": ("#7a87c6", "shrub"),
    "Crops": ("#e49635", "crops"), "Built area": ("#c4281b", "built"), "Bare ground": ("#a59b8f", "bare"),
    "Snow and ice": ("#a8ebff", "snow"), "Clouds": ("#616161", None), "Rangeland": ("#e3e2c3", "grass"),
}


@dataclass(frozen=True)
class ChangeKind:
    id: str
    label: str
    colour: str
    hint: str


# In drawing order: where a pixel fits more than one, the first wins.
CHANGES: tuple[ChangeKind, ...] = (
    ChangeKind("built", "Built on", "#c92a2a", "Became built-up land: new suburbs, roads, factories"),
    ChangeKind("bare", "New bare ground", "#862e9c", "Became bare: mines, quarries, building sites, slips, clear-felled land not yet replanted"),
    ChangeKind("cleared", "Trees cleared", "#e8590c", "Trees became crops, grass or shrubs: forest harvest or clearing for farms"),
    ChangeKind("crops", "New farmland", "#f2c200", "Grass or shrubs became crops"),
    ChangeKind("trees", "Trees grown", "#2b8a3e", "Became trees: planting or regrowth"),
    ChangeKind("water_gain", "Became water", "#1c7ed6", "New lakes and reservoirs, flooding that stayed, rivers moving"),
    ChangeKind("water_loss", "Water became land", "#a0522d", "Lakes shrinking, reservoirs drained, rivers moving"),
)
CHANGE_IDS = tuple(c.id for c in CHANGES)


def change_kind(a: str, b: str) -> str | None:
    """The kind of change from cover a to cover b (kinds from KINDS), or None for no change that counts."""
    if a == b:
        return None
    if b == "built":
        return "built"
    if b == "bare" and a not in ("snow",):
        return "bare"
    if a == "trees" and b in ("crops", "grass", "shrub"):
        return "cleared"
    if b == "crops" and a in ("grass", "shrub"):
        return "crops"
    if b == "trees" and a in ("crops", "grass", "shrub", "bare"):
        return "trees"
    if b == "water" and a != "snow":
        return "water_gain"
    if a == "water" and b != "snow":
        return "water_loss"
    return None


CHANGE_SOURCES = {
    "lc10": {"label": "Esri 10 m (2017-2025)", "years": (2017, 2025), "maxzoom": 14},
    "lcyears": {"label": "ESA 300 m (1992-2020)", "years": (1992, 2020), "maxzoom": 9},
}
CHANGE_MIN_PIXELS = 4  # a changed pixel is kept when at least this many of the 3x3 around it (itself too) changed the same way

# ----------------------------------------------------------------------------- water
@dataclass(frozen=True)
class WaterClass:
    code: int
    label: str
    colour: str     # as JRC's tiles draw it
    group: str      # "same", "gained", "lost", "changed" (seasonal <-> permanent), "brief"
    draw: str       # the colour this app draws it in


WATER_CLASSES: tuple[WaterClass, ...] = (
    WaterClass(1, "Water all along", "#0000dd", "same", "#a5c8e8"),
    WaterClass(2, "New water all year", "#22b14c", "gained", "#1c7ed6"),
    WaterClass(3, "Water all year, now gone", "#d12d3e", "lost", "#c92a2a"),
    WaterClass(4, "Seasonal water all along", "#99d9ea", "same", "#d0e6f5"),
    WaterClass(5, "New seasonal water", "#b5e61d", "gained", "#74c0fc"),
    WaterClass(6, "Seasonal water, now gone", "#e6a1aa", "lost", "#ffa8a8"),
    WaterClass(7, "Seasonal water now all year", "#ff7f27", "changed", "#3b5bdb"),
    WaterClass(8, "Water all year now only seasonal", "#ffc90e", "changed", "#f59f00"),
    WaterClass(9, "Water for a while, now gone", "#7f7f7f", "brief", "#adb5bd"),
    WaterClass(10, "Seasonal water for a while, now gone", "#c3c3c3", "brief", "#dee2e6"),
)
WATER_TILES = "https://storage.googleapis.com/global-surface-water/tiles2021/transitions/{z}/{x}/{y}.png"
WATER_MAXZOOM = 13
WATER_ATTRIBUTION = "Water: EC JRC / Google, Global Surface Water 1984-2021 (Pekel et al. 2016)"

# ----------------------------------------------------------------------------- area scan
@dataclass(frozen=True)
class ScanTag:
    id: str
    label: str
    looks: str   # what it looks like from above at 10 m a pixel, for the model
    colour: str


SCAN_TAGS: tuple[ScanTag, ...] = (
    ScanTag("open_pit_mine", "Open-pit mine or quarry", "a terraced pit or large bare scar of rock or earth, often with haul roads and spoil heaps", "#862e9c"),
    ScanTag("solar_farm", "Solar farm", "a block of evenly spaced dark rows or a dark grey rectangle on farmland", "#f59f00"),
    ScanTag("airport", "Airport or airstrip", "a long straight runway, often with taxiways and an apron", "#1971c2"),
    ScanTag("port", "Port or harbour", "docks, wharves, breakwaters or container stacks at the shore", "#0b7285"),
    ScanTag("dam", "Dam or reservoir", "a straight or curved wall across a valley holding back a lake", "#1c7ed6"),
    ScanTag("greenhouses", "Greenhouse cluster", "many bright white or pale grey long roofs packed together", "#adb5bd"),
    ScanTag("clearfell", "Fresh forest clearing", "a bare or brown patch with sharp straight edges inside dark forest", "#e8590c"),
    ScanTag("new_housing", "New housing being built", "a grid of new streets and small lots, much bare ground, at the edge of a town", "#c92a2a"),
    ScanTag("industrial", "Large industrial site", "big rectangular roofs, storage tanks, stockpiles or a large plant", "#495057"),
    ScanTag("pivot_irrigation", "Circle irrigation", "green or brown circles of crops in a regular pattern", "#2b8a3e"),
    ScanTag("burn_scar", "Burn scar", "a large black, dark brown or grey patch of burnt land with uneven edges", "#343a40"),
    ScanTag("oil_gas", "Oil or gas field", "many small square bare pads joined by tracks, in a grid, sometimes with flares", "#5c3d2e"),
)
SCAN_ZOOM = 13          # one square = one zoom-13 tile (about 4.9 km at the equator, 3.8 km in New Zealand)
SCAN_PICTURE_ZOOM = 14  # each square's picture is put together from four zoom-14 satellite tiles (512 x 512)
WHERE_CELLS = ("top left", "top", "top right", "left", "centre", "right", "bottom left", "bottom", "bottom right")

# Map layers whose items "Check the map's places" can look at, and what one looks like from above.
CHECKABLE: dict[str, str] = {
    "power_plants": "a power plant (by its fuel: a dam and lake for hydro, turbines and pads for wind, panels for solar, "
                    "buildings, chimneys and cooling towers for coal, gas or nuclear)",
    "airports": "an airport with at least one runway",
    "ports": "a port: wharves, docks or container yards at the shore",
    "military_bases": "a military base: runways, barracks, hangars or a fenced compound",
    "lng_terminals": "an LNG terminal: large round storage tanks beside a jetty",
    "universities": "a university campus: a group of large buildings with sports fields",
    "hospitals": "a hospital: a large building complex in a town",
}
