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


# Council street and park tree lists (source council_trees). The id is the start of each
# file's name in var/raw/council_trees (and of lists saved by hand: london_trees.csv), so it
# has no spaces, dashes or dots. how: "hub" searches the council's ArcGIS open data for a tree
# layer; "layer" reads that ArcGIS layer; "socrata" and "ods" are New York's and Melbourne's
# open data APIs; "manual" is read only from a saved file. city/country find the population
# for trees per person (GeoNames city, else the figure here). note: what the list holds.
COUNCILS: dict[str, dict] = {
    # Auckland Council's open data has only notable trees (checked Nov 2026), so its list is
    # read only from a file saved by hand (auckland_trees.csv), for example from a council request.
    "auckland": {"name": "Auckland", "country": "NZL", "city": "Auckland", "how": "manual",
                 "url": "https://data-aucklandcouncil.opendata.arcgis.com/search?q=trees",
                 "note": "Street and park trees (saved by hand: auckland_trees.csv)"},
    "wellington": {"name": "Wellington", "country": "NZL", "city": "Wellington", "how": "layer",
                   "url": "https://gis.wcc.govt.nz/arcgis/rest/services/Parks/Parks/MapServer/53",
                   "note": "Trees the Parks, Sport and Recreation unit looks after"},
    "christchurch": {"name": "Christchurch", "country": "NZL", "city": "Christchurch", "how": "layer",
                     "url": "https://gis.ccc.govt.nz/server/rest/services/OpenData/Tree/FeatureServer/0",
                     "note": "Big trees only (6 m or more, trunk 25 cm or more)"},
    "palmerstonnorth": {"name": "Palmerston North", "country": "NZL", "city": "Palmerston North", "how": "layer",
                        "url": "https://geosite.pncc.govt.nz/arcgis/rest/services/Public/WEB_Open_Data/MapServer/18",
                        "note": "Street and park trees"},
    "hastings": {"name": "Hastings", "country": "NZL", "city": "Hastings", "how": "layer", "population": 90_000,
                 "url": "https://services1.arcgis.com/8L3DQUzjrkgEmDpQ/arcgis/rest/services/Hastings_DC_Trees/FeatureServer/0",
                 "note": "Road side and park trees (whole district)"},
    "newplymouth": {"name": "New Plymouth", "country": "NZL", "city": "New Plymouth", "how": "layer", "population": 89_000,
                    "url": "https://services2.arcgis.com/JthOmqz8HxPqljUO/arcgis/rest/services/OpenData_Infrastructure_Parks/FeatureServer/12",
                    "note": "Park trees (whole district)"},
    "waipa": {"name": "Waipā (Cambridge, Te Awamutu)", "country": "NZL", "city": None, "how": "layer", "population": 60_000,
              "url": "https://services9.arcgis.com/OsxSXqmTWVTZQ9ie/arcgis/rest/services/Parks_and_Community_Asset_Tree_Points/FeatureServer/0",
              "note": "Park and reserve trees (whole district)"},
    "sydney": {"name": "Sydney (City of Sydney)", "country": "AUS", "city": None, "how": "hub", "population": 230_000, "overseas": True,
               "url": "https://data.cityofsydney.nsw.gov.au/api/search/v1/collections/dataset/items?q=trees&limit=10",
               "note": "Street and park trees in the City of Sydney council area (not all of Sydney)"},
    "melbourne": {"name": "Melbourne (City of Melbourne)", "country": "AUS", "city": None, "how": "ods", "population": 180_000, "overseas": True,
                  "url": "https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets/trees-with-species-and-dimensions-urban-forest/exports/csv?delimiter=%2C",
                  "note": "Urban forest in the City of Melbourne council area (not all of Melbourne)"},
    "newyork": {"name": "New York", "country": "USA", "city": "New York City", "how": "socrata", "overseas": True,
                "url": "https://data.cityofnewyork.us/resource/uvpi-gqnh.json",
                "note": "Street trees only (2015 street tree census, living trees)"},
    "london": {"name": "London", "country": "GBR", "city": "London", "how": "manual", "overseas": True,
               "url": "https://data.london.gov.uk/dataset/local-authority-maintained-trees",
               "note": "Trees the boroughs look after (saved by hand: london_trees.csv)"},
}


# ESA CCI / C3S land cover classes (1992-2020, 300 m) with the colour Microsoft Planetary
# Computer draws each in (its esa-cci-lc colour map), and the broad kind of cover each belongs
# to (the Land page's kinds: trees, crops, grass, shrub, bare, snow, built, water).
CCI_CLASSES: dict[int, tuple[str, str, str]] = {
    10: ("Cropland, rainfed", "#ffff64", "crops"), 11: ("Cropland, herbaceous", "#ffff64", "crops"),
    12: ("Cropland, tree or shrub", "#ffff00", "crops"), 20: ("Cropland, irrigated", "#aaf0f0", "crops"),
    30: ("Mostly cropland, some natural plants", "#dcf064", "crops"), 40: ("Mostly natural plants, some cropland", "#c8c864", "shrub"),
    50: ("Broadleaved evergreen trees", "#006400", "trees"), 60: ("Broadleaved deciduous trees", "#00a000", "trees"),
    62: ("Broadleaved deciduous trees, open", "#aac800", "trees"), 70: ("Needleleaved evergreen trees", "#003c00", "trees"),
    72: ("Needleleaved evergreen trees, open", "#005000", "trees"), 80: ("Needleleaved deciduous trees", "#285000", "trees"),
    82: ("Needleleaved deciduous trees, open", "#286400", "trees"), 90: ("Mixed trees", "#788200", "trees"),
    100: ("Trees and shrubs with some grass", "#8ca000", "trees"), 110: ("Grass with some trees and shrubs", "#be9600", "grass"),
    120: ("Shrubland", "#966400", "shrub"), 130: ("Grassland", "#ffb432", "grass"), 140: ("Lichens and mosses", "#ffdcd2", "bare"),
    150: ("Sparse plants", "#ffebaf", "bare"), 151: ("Sparse trees", "#ffc864", "bare"), 152: ("Sparse shrubs", "#ffd278", "bare"),
    160: ("Flooded trees, fresh water", "#00785a", "trees"), 170: ("Flooded trees, salt water (mangroves)", "#009678", "trees"),
    180: ("Flooded shrubs or grass", "#00dc82", "shrub"), 190: ("Urban areas", "#c31400", "built"),
    200: ("Bare areas", "#fff5d7", "bare"), 201: ("Bare rock", "#dcdcdc", "bare"), 210: ("Water", "#0046c8", "water"),
    220: ("Permanent snow and ice", "#ffffff", "snow"),
}
