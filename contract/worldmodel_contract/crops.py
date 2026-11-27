"""Crops by the land they take: one list of crops shared by the sources that give crop areas
(FAOSTAT for every country, USDA NASS for US states and counties, Stats NZ for New Zealand's
regions), so the same crop has the same name and colour on every "Top crop" map.

A source's own name for a crop is turned into the crop's id with `fao_crop`, `nass_crop` and
`NZ_HORT`; a crop not in the list keeps its own name (made into an id) and a quiet grey-ish
colour, so nothing is dropped.
"""

from __future__ import annotations

import hashlib
import re

ACRE_HA = 0.40468564224  # hectares in an acre

# id -> (name, colour). The colours follow the usual "top crop" maps: corn pink, soybeans purple,
# wheat gold, hay green, cotton light blue, rice brown, sorghum teal, peanuts orange, sugarcane red.
CROPS: dict[str, tuple[str, str]] = {
    "maize": ("Maize (corn)", "#e8478b"),
    "soybeans": ("Soybeans", "#7b61e8"),
    "wheat": ("Wheat", "#f2b705"),
    "hay": ("Hay and alfalfa", "#34a853"),
    "cotton": ("Cotton", "#4fb3f0"),
    "rice": ("Rice", "#8c5a2e"),
    "sorghum": ("Sorghum", "#12a594"),
    "groundnuts": ("Peanuts (groundnuts)", "#f57c1f"),
    "sugar_cane": ("Sugarcane", "#b3202a"),
    "barley": ("Barley", "#c9a26b"),
    "oats": ("Oats", "#e6d3a3"),
    "rye": ("Rye", "#9e8a5c"),
    "millet": ("Millet", "#a3c94f"),
    "rapeseed": ("Rapeseed (canola)", "#ffe14d"),
    "sunflower": ("Sunflower seed", "#e0a000"),
    "sugar_beet": ("Sugar beet", "#d65f80"),
    "potatoes": ("Potatoes", "#b8a07a"),
    "cassava": ("Cassava", "#9b3fb5"),
    "sweet_potatoes": ("Sweet potatoes", "#c0568a"),
    "yams": ("Yams", "#7d4a8c"),
    "beans": ("Beans, dry", "#5c8f1d"),
    "chickpeas": ("Chickpeas", "#c4b35a"),
    "lentils": ("Lentils", "#8a7a2a"),
    "cowpeas": ("Cowpeas", "#6e8b3d"),
    "peas": ("Peas, dry", "#8fbf6a"),
    "pigeon_peas": ("Pigeon peas", "#557a35"),
    "oil_palm": ("Oil palm", "#1f6b3a"),
    "coconuts": ("Coconuts", "#1f8fbf"),
    "olives": ("Olives", "#6b7d2e"),
    "coffee": ("Coffee", "#6b4423"),
    "cocoa": ("Cocoa", "#4d2b1f"),
    "tea": ("Tea", "#3d7a4f"),
    "rubber": ("Natural rubber", "#5d6670"),
    "tobacco": ("Tobacco", "#a1662f"),
    "sesame": ("Sesame", "#d9c38a"),
    "cashews": ("Cashew nuts", "#c97b4a"),
    "almonds": ("Almonds", "#d9a88f"),
    "grapes": ("Grapes", "#7a2a8c"),
    "apples": ("Apples", "#d93636"),
    "kiwifruit": ("Kiwifruit", "#7cbf2a"),
    "avocados": ("Avocados", "#2e7d32"),
    "bananas": ("Bananas", "#f5d000"),
    "plantains": ("Plantains", "#c9b200"),
    "onions": ("Onions", "#c78fb3"),
    "squash": ("Squash and pumpkins", "#e0892b"),
    "vegetables": ("Vegetables", "#64a68a"),
    "pulses": ("Other pulses", "#7a8f3d"),
    "fruit": ("Other fruit", "#e377c2"),
    "dates": ("Dates", "#c68642"),
    "pepper": ("Pepper", "#4a4a4a"),
    "plums": ("Plums", "#5e3c99"),
}

# FAOSTAT item (lower case) -> crop id; anything else becomes an id of its own.
FAO_ITEMS = {
    "maize (corn)": "maize", "soya beans": "soybeans", "wheat": "wheat", "seed cotton, unginned": "cotton", "rice": "rice",
    "sorghum": "sorghum", "groundnuts, excluding shelled": "groundnuts", "sugar cane": "sugar_cane", "barley": "barley",
    "oats": "oats", "rye": "rye", "millet": "millet", "rape or colza seed": "rapeseed", "sunflower seed": "sunflower",
    "sugar beet": "sugar_beet", "potatoes": "potatoes", "cassava, fresh": "cassava", "sweet potatoes": "sweet_potatoes",
    "yams": "yams", "beans, dry": "beans", "chick peas, dry": "chickpeas", "lentils, dry": "lentils", "cow peas, dry": "cowpeas",
    "peas, dry": "peas", "pigeon peas, dry": "pigeon_peas", "oil palm fruit": "oil_palm", "coconuts, in shell": "coconuts",
    "olives": "olives", "coffee, green": "coffee", "cocoa beans": "cocoa", "tea leaves": "tea",
    "natural rubber in primary forms": "rubber", "unmanufactured tobacco": "tobacco", "sesame seed": "sesame",
    "cashew nuts, in shell": "cashews", "almonds, in shell": "almonds", "grapes": "grapes", "apples": "apples",
    "kiwi fruit": "kiwifruit", "avocados": "avocados", "bananas": "bananas", "plantains and cooking bananas": "plantains",
    "onions and shallots, dry (excluding dehydrated)": "onions", "pumpkins, squash and gourds": "squash",
    "other vegetables, fresh n.e.c.": "vegetables", "other pulses n.e.c.": "pulses", "other fruits, n.e.c.": "fruit",
    "other tropical fruits, n.e.c.": "fruit", "dates": "dates", "pepper (piper spp.), raw": "pepper", "plums and sloes": "plums",
}
# FAOSTAT item codes from here up are groups ("Cereals, primary", "Fruit Primary", "Oilcrops, Oil Equivalent"),
# which would count the same land twice.
FAO_GROUP_CODES = 1700

# USDA NASS Quick Stats commodity -> crop id. Hay, haylage and "hay & haylage" are one crop (the largest
# figure is kept, as "hay & haylage" holds the other two).
NASS_COMMODITIES = {
    "CORN": "maize", "SOYBEANS": "soybeans", "WHEAT": "wheat", "HAY": "hay", "HAYLAGE": "hay", "HAY & HAYLAGE": "hay",
    "COTTON": "cotton", "RICE": "rice", "SORGHUM": "sorghum", "PEANUTS": "groundnuts", "SUGARCANE": "sugar_cane",
    "BARLEY": "barley", "OATS": "oats", "RYE": "rye", "MILLET, PROSO": "millet", "MILLET": "millet", "CANOLA": "rapeseed",
    "SUNFLOWER": "sunflower", "SUGARBEETS": "sugar_beet", "POTATOES": "potatoes", "SWEET POTATOES": "sweet_potatoes",
    "BEANS": "beans", "CHICKPEAS": "chickpeas", "LENTILS": "lentils", "PEAS": "peas", "TOBACCO": "tobacco",
    "ALMONDS": "almonds", "GRAPES": "grapes", "APPLES": "apples", "KIWIFRUIT": "kiwifruit", "AVOCADOS": "avocados",
    "OLIVES": "olives", "ONIONS": "onions", "SQUASH": "squash", "PUMPKINS": "squash", "COFFEE": "coffee",
}
# Quick Stats commodities that are sums of others, or catch-alls: left out so land is not counted twice.
NASS_SKIP = {"FIELD CROPS", "ORCHARDS", "CROPLAND", "AG LAND", "PRACTICES", "BERRIES", "VEGETABLES", "NON-CITRUS", "CITRUS",
             "TREE NUTS", "FRUIT & TREE NUTS", "HORTICULTURE", "GRAIN", "FIELD CROPS, OTHER", "CROPS, OTHER"}
# Qualifiers that pick out a part of a crop's land (irrigated, organic): never added to the whole.
NASS_PART = re.compile(r"\b(IRRIGATED|ORGANIC|NON-IRRIGATED)\b")

# Stats NZ horticulture by regional council (AGR_AGR_002): measure id suffix -> crop id.
NZ_HORT = {"apples": "apples", "kiwifruit": "kiwifruit", "avocados": "avocados", "wine_grapes": "grapes", "olives": "olives",
           "onions": "onions", "potatoes": "potatoes", "squash": "squash"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48] or "crop"


def fao_crop(item: str) -> str:
    """A FAOSTAT item's crop id ("Maize (corn)" -> maize; "Lettuce and chicory" -> lettuce_and_chicory)."""
    it = item.strip().lower()
    return FAO_ITEMS.get(it) or slug(it)


def nass_skip(commodity: str) -> bool:
    c = commodity.strip().upper()
    return c in NASS_SKIP or "TOTAL" in c or c.endswith(", OTHER") or c.startswith("OTHER")


def nass_crop(commodity: str) -> str:
    c = commodity.strip().upper()
    return NASS_COMMODITIES.get(c) or slug(c)


def name(crop: str) -> str:
    if crop in CROPS:
        return CROPS[crop][0]
    words = re.sub(r"\b(n e c|raw)\b", "", crop.replace("_", " ")).strip()
    return words[:1].upper() + words[1:]


def colour(crop: str) -> str:
    """The crop's colour; a crop outside the list gets a muted one of its own (the same every time)."""
    if crop in CROPS:
        return CROPS[crop][1]
    h = int(hashlib.md5(crop.encode()).hexdigest()[:6], 16)
    hue, light = h % 360, 52 + (h >> 9) % 14
    return _hsl(hue, 22, light)


def _hsl(h: float, s: float, l: float) -> str:
    s, l = s / 100, l / 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return "#" + "".join(f"{round((v + m) * 255):02x}" for v in (r, g, b))
