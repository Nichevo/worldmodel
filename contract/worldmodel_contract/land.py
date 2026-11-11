"""Land, cities and trees: the class lists and fixed figures shared by the data side
(connectors/land.py) and the app (the Land page, city pages and sector Land cards).

LCDB_CLASSES
    New Zealand's Land Cover Database (Manaaki Whenua): each class code with its name, the
    middle level it belongs to and the top level. LCDB publishes the 33 or so classes; the two
    coarser levels here follow its own groupings (the top level has seven groups).
WORLDCOVER
    ESA WorldCover classes with the colour each has in the published map pictures, so a
    picture can be read back into shares of tree cover, crops, built-up land and so on.
LAND_CARDS
    For each land-based sector, the figures its Land card draws.
WHERE_LAND_GOES
    Fixed figures for the "where the land goes" breakdown that no yearly source gives.
"""

from __future__ import annotations

# code -> (name, middle level, top level)
LCDB_CLASSES: dict[int, tuple[str, str, str]] = {
    1: ("Built-up area (settlement)", "Built-up and transport", "Artificial surfaces"),
    2: ("Urban parkland and open space", "Urban parkland", "Artificial surfaces"),
    5: ("Transport infrastructure", "Built-up and transport", "Artificial surfaces"),
    6: ("Surface mine or dump", "Mines and dumps", "Artificial surfaces"),
    10: ("Sand or gravel", "Bare ground", "Bare or lightly vegetated"),
    12: ("Landslide", "Bare ground", "Bare or lightly vegetated"),
    14: ("Permanent snow and ice", "Snow and ice", "Bare or lightly vegetated"),
    15: ("Alpine grass and herbfield", "Alpine vegetation", "Bare or lightly vegetated"),
    16: ("Gravel or rock", "Bare ground", "Bare or lightly vegetated"),
    20: ("Lake or pond", "Water", "Water bodies"),
    21: ("River", "Water", "Water bodies"),
    22: ("Estuarine open water", "Water", "Water bodies"),
    30: ("Short-rotation cropland", "Cropland", "Cropland"),
    33: ("Orchard, vineyard or other perennial crop", "Orchards and vineyards", "Cropland"),
    40: ("High producing exotic grassland", "Exotic grassland", "Grassland, sedge and saltmarsh"),
    41: ("Low producing grassland", "Exotic grassland", "Grassland, sedge and saltmarsh"),
    43: ("Tall tussock grassland", "Tussock grassland", "Grassland, sedge and saltmarsh"),
    44: ("Depleted grassland", "Tussock grassland", "Grassland, sedge and saltmarsh"),
    45: ("Herbaceous freshwater vegetation", "Wetland", "Grassland, sedge and saltmarsh"),
    46: ("Herbaceous saline vegetation", "Wetland", "Grassland, sedge and saltmarsh"),
    47: ("Flaxland", "Wetland", "Grassland, sedge and saltmarsh"),
    50: ("Fernland", "Native scrub", "Scrub and shrubland"),
    51: ("Gorse and/or broom", "Exotic scrub", "Scrub and shrubland"),
    52: ("Mānuka and/or kānuka", "Native scrub", "Scrub and shrubland"),
    54: ("Broadleaved indigenous hardwoods", "Native scrub", "Scrub and shrubland"),
    55: ("Sub alpine shrubland", "Native scrub", "Scrub and shrubland"),
    56: ("Mixed exotic shrubland", "Exotic scrub", "Scrub and shrubland"),
    58: ("Matagouri or grey scrub", "Native scrub", "Scrub and shrubland"),
    64: ("Forest, harvested", "Exotic forest", "Forest"),
    68: ("Deciduous hardwoods", "Exotic forest", "Forest"),
    69: ("Indigenous forest", "Native forest", "Forest"),
    70: ("Mangrove", "Native forest", "Forest"),
    71: ("Exotic forest", "Exotic forest", "Forest"),
    80: ("Peat shrubland (Chatham Islands)", "Native scrub", "Scrub and shrubland"),
    81: ("Dune shrubland (Chatham Islands)", "Native scrub", "Scrub and shrubland"),
}
LCDB_LEVELS = {1: "7 groups", 2: "16 kinds", 3: "every class"}
# Regional council names (as Stats NZ's boundary files spell them) -> entity id.
NZ_REGION_NAMES: dict[str, str] = {
    "northland": "NZ-NTL", "auckland": "NZ-AUK", "waikato": "NZ-WKO", "bay of plenty": "NZ-BOP", "gisborne": "NZ-GIS",
    "hawke's bay": "NZ-HKB", "hawkes bay": "NZ-HKB", "taranaki": "NZ-TKI", "manawatu-whanganui": "NZ-MWT",
    "manawatū-whanganui": "NZ-MWT", "wellington": "NZ-WGN", "west coast": "NZ-WTC", "canterbury": "NZ-CAN",
    "otago": "NZ-OTA", "southland": "NZ-STL", "tasman": "NZ-TAS", "nelson": "NZ-NSN", "marlborough": "NZ-MBH",
}


def nz_region(name: str | None) -> str | None:
    """The entity id for a regional council name ("Waikato Region", "Manawatū-Whanganui")."""
    if not name:
        return None
    s = str(name).lower().replace(" region", "").replace("'", "'").strip()
    return NZ_REGION_NAMES.get(s)


def lcdb_level(code: int, level: int) -> str:
    """The class's name at level 3, its middle group at 2 and its top group at 1."""
    name, mid, top = LCDB_CLASSES.get(int(code), (f"Class {code}", "Other", "Other"))
    return {3: name, 2: mid, 1: top}.get(level, name)


# value -> (name, colour in the WorldCover map pictures)
WORLDCOVER: dict[int, tuple[str, str]] = {
    10: ("Tree cover", "#006400"),
    20: ("Shrubland", "#ffbb22"),
    30: ("Grassland", "#ffff4c"),
    40: ("Cropland", "#f096ff"),
    50: ("Built-up", "#fa0000"),
    60: ("Bare or sparse vegetation", "#b4b4b4"),
    70: ("Snow and ice", "#f0f0f0"),
    80: ("Permanent water", "#0064c8"),
    90: ("Herbaceous wetland", "#0096a0"),
    95: ("Mangroves", "#00cf75"),
    100: ("Moss and lichen", "#fae6a0"),
}
# Trees per hectare of tree cover in a city: street and park trees have crowns of 50 to 100 m²
# each, so a hectare of canopy is very roughly 100 to 200 trees. The middle is used, and every
# count worked out from it is shown as an estimate.
TREES_PER_HA_CANOPY = 150

# For each land-based sector, what its Land card draws (indicator ids; sp_ = production,
# sa_ = area harvested, both from FAOSTAT). ratios: (label, numerator, denominator, unit, scale).
COMPARE = ["NZL", "IRL", "NLD", "USA", "AUS"]
LAND_CARDS: dict[str, dict] = {
    "dairy": {"land": "land_pasture_ha", "land_label": "Permanent meadows and pastures",
              "output": "sp_milk", "output_label": "Raw milk",
              "ratios": [("Milk per cow", "sp_milk", "livestock_dairy_cows", "t a cow", 1),
                         ("Dairy cows per hectare of pasture", "livestock_dairy_cows", "land_pasture_ha", "cows/ha", 1),
                         ("Nitrogen fertiliser per hectare of cropland", "fert_n_per_ha", None, "kg/ha", 1)],
              "nz_regions": "nzreg_dairy_cattle", "nz_regions_label": "Dairy cattle by region (Stats NZ)"},
    "beef": {"land": "land_pasture_ha", "land_label": "Permanent meadows and pastures",
             "output": "sp_beef", "output_label": "Beef",
             "ratios": [("Cattle per hectare of pasture", "livestock_cattle_head", "land_pasture_ha", "head/ha", 1),
                        ("Beef per hectare of pasture", "sp_beef", "land_pasture_ha", "kg/ha", 1000)],
             "nz_regions": "nzreg_beef_cattle", "nz_regions_label": "Beef cattle by region (Stats NZ)"},
    "sheep": {"land": "land_pasture_ha", "land_label": "Permanent meadows and pastures",
              "output": "sp_sheep_meat", "output_label": "Lamb and mutton",
              "ratios": [("Sheep per hectare of pasture", "livestock_sheep_head", "land_pasture_ha", "head/ha", 1),
                         ("Wool per sheep", "sp_wool", "livestock_sheep_head", "kg a sheep", 1000)],
              "nz_regions": "nzreg_sheep", "nz_regions_label": "Sheep by region (Stats NZ)"},
    "wheat": {"land": "sa_wheat", "land_label": "Wheat harvested", "output": "sp_wheat", "output_label": "Wheat",
              "ratios": [("Yield", "sp_wheat", "sa_wheat", "t/ha", 1),
                         ("Nitrogen fertiliser per hectare of cropland", "fert_n_per_ha", None, "kg/ha", 1)]},
    "maize": {"land": "sa_maize", "land_label": "Maize harvested", "output": "sp_maize", "output_label": "Maize",
              "ratios": [("Yield", "sp_maize", "sa_maize", "t/ha", 1)]},
    "rice": {"land": "sa_rice", "land_label": "Rice harvested", "output": "sp_rice", "output_label": "Rice",
             "ratios": [("Yield", "sp_rice", "sa_rice", "t/ha", 1)]},
    "soybeans": {"land": "sa_soybeans", "land_label": "Soybeans harvested", "output": "sp_soybeans", "output_label": "Soybeans",
                 "ratios": [("Yield", "sp_soybeans", "sa_soybeans", "t/ha", 1)]},
    "forestry": {"land": "land_planted_forest_ha", "land_label": "Planted forest", "output": "sp_logs",
                 "output_label": "Logs (m³)",
                 "ratios": [("Logs per hectare of planted forest", "sp_logs", "land_planted_forest_ha", "m³/ha", 1),
                            ("Forest share of land", "land_forest_pct", None, "%", 1)],
                 "nz_regions": "nzreg_plantation_ha", "nz_regions_label": "Plantation forest by region (Stats NZ)"},
    "wine": {"land": "sa_grapes", "land_label": "Grapes harvested", "output": "sp_wine", "output_label": "Wine",
             "ratios": [("Grapes per hectare", "sp_grapes", "sa_grapes", "t/ha", 1),
                        ("Wine per hectare of grapes", "sp_wine", "sa_grapes", "t/ha", 1)]},
    "fruit": {"land": "sa_kiwifruit", "land_label": "Kiwifruit harvested", "output": "sp_kiwifruit",
              "output_label": "Kiwifruit",
              "ratios": [("Kiwifruit per hectare", "sp_kiwifruit", "sa_kiwifruit", "t/ha", 1),
                         ("Apples per hectare", "sp_apples", "sa_apples", "t/ha", 1)]},
}

# Where the land goes (Our World in Data's breakdown, after FAO and Poore and Nemecek 2018):
# Earth's surface, land, habitable land (land less glaciers and barren land), then farmland
# from FAOSTAT for the year chosen, and what share of calories and protein each kind of
# farmland gives (livestock and dairy against crops for people, Poore and Nemecek 2018).
WHERE_LAND_GOES = {
    "surface_km2": 510_000_000, "ocean_share": 0.71, "glacier_share_of_land": 0.10, "barren_share_of_land": 0.19,
    "livestock_calories_share": 0.18, "livestock_protein_share": 0.37,
    "about": ("Earth's surface, its ice-free and not barren land, and farmland for the year chosen (FAOSTAT). "
              "The shares of calories and protein from livestock (18% and 37%) are from Poore and Nemecek (2018), "
              "as Our World in Data shows them; they do not change with the year."),
}
