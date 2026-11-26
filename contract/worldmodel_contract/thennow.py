"""Then and now: sharper pictures and pictures from the past (Spotting page, part 2).

Where the pictures come from, and what each may be used for:

    LINZ aerial photos    New Zealand, 5 cm to 0.5 m, from the 1930s to now, one survey per region and year.
                          CC BY 4.0 (anything, including AI). The list of surveys and where each covers is
                          read from LINZ's public catalogue on AWS (nz-imagery); the pictures come from
                          LINZ Basemaps, which needs a free key (LINZ_BASEMAPS_API_KEY).
    Esri World Imagery    The world, about 0.3-1 m, and its Wayback archive (each version since 2014).
                          Free to look at in the browser; Esri's terms do not allow saving copies or feeding
                          them to AI, so the app never fetches these pictures itself: the browser shows them.
    EOX cloudless         The world at 10 m, one cloud-free picture a year (2016, 2018-2024).
    Landsat               The world at 30 m, every year since 1984 (Microsoft Planetary Computer), for the
                          timelapse and its water, green and built-up chart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ----------------------------------------------------------------------------- LINZ
LINZ_CATALOG = "https://nz-imagery.s3.ap-southeast-2.amazonaws.com/catalog.json"
LINZ_BASE = "https://nz-imagery.s3.ap-southeast-2.amazonaws.com/"
# "aerial" is LINZ's best picture everywhere in New Zealand; any survey's own name (see linz_layer) gives that survey.
LINZ_TILES = "https://basemaps.linz.govt.nz/v1/tiles/{layer}/WebMercatorQuad/{z}/{x}/{y}.webp?api={key}"
LINZ_KEY_ENV = "LINZ_BASEMAPS_API_KEY"
LINZ_MAXZOOM = 21
LINZ_ATTRIBUTION = "Aerial photos: Toitū Te Whenua LINZ (CC BY 4.0)"
NZ_BOX = (165.8, -47.5, 178.9, -34.0)    # main islands and close ones; LINZ also covers the Chathams
NZ_BOXES = (NZ_BOX, (-177.0, -44.5, -175.8, -43.5))  # ... which sit across the date line


# Boxes (west, south, east, north) for the places the Then and now tab, timelapses and aerial scans offer first.
NZ_PLACES: dict[str, tuple[float, float, float, float]] = {
    "Auckland": (174.60, -37.05, 174.95, -36.75),
    "Hamilton": (175.20, -37.84, 175.36, -37.71),
    "Tauranga": (176.05, -37.76, 176.35, -37.60),
    "Wellington": (174.70, -41.35, 174.95, -41.10),
    "Christchurch": (172.50, -43.62, 172.78, -43.42),
    "Rolleston and Lincoln": (172.33, -43.66, 172.50, -43.57),
    "Queenstown": (168.60, -45.06, 168.78, -44.97),
    "Dunedin": (170.42, -45.92, 170.56, -45.84),
}


def linz_layer(slug: str) -> str:
    """LINZ Basemaps' name for a survey: its catalogue slug with _ as - (christchurch_2023_0.075m ->
    christchurch-2023-0.075m)."""
    return slug.replace("_", "-")


def layer_ok(name: str) -> bool:
    """A name safe to put in a picture address (aerial, or a survey's name)."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9.\-]{1,80}", name or ""))


def in_nz(lon: float, lat: float) -> bool:
    return any(w <= lon <= e and s <= lat <= n for w, s, e, n in NZ_BOXES)


# ----------------------------------------------------------------------------- Esri (looking only)
ESRI_NOW = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
WAYBACK_CONFIG = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
WAYBACK_TILE = ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/"
                "MapServer/tile/{release}/{z}/{y}/{x}")
# Which version a tile really comes from: {"data": [1], "select": [release]} (select missing: this one).
WAYBACK_TILEMAP = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap/{release}/{z}/{y}/{x}"
WAYBACK_ZOOM = 16  # the zoom at which a place's own picture changes are looked for
ESRI_MAXZOOM = 19
ESRI_ATTRIBUTION = "Imagery: Esri, Maxar, Earthstar Geographics and others (World Imagery; for looking only)"

# ----------------------------------------------------------------------------- EOX yearly
EOX_YEARS = {"2016": "s2cloudless_3857", **{str(y): f"s2cloudless-{y}_3857" for y in range(2018, 2025)}}
EOX_TILES = "https://tiles.maps.eox.at/wmts/1.0.0/{layer}/default/g/{z}/{y}/{x}.jpg"
EOX_ATTRIBUTION = "Sentinel-2 cloudless by EOX (Copernicus Sentinel data; 2016 CC BY 4.0, later years CC BY-NC-SA 4.0)"


def ai_ok(source: str) -> bool:
    """Whether a picture source may be sent to the local AI (Esri's may not)."""
    return source.split(":", 1)[0] in ("linz", "eox", "sat")


# ----------------------------------------------------------------------------- Landsat timelapse
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_ITEM_TILE = ("https://planetarycomputer.microsoft.com/api/data/v1/item/tiles/WebMercatorQuad/{z}/{x}/{y}@1x"
                "?collection=landsat-c2-l2&item={item}&{query}")
LANDSAT_FIRST = 1984
# Landsat 5 to 2011, 8 and 9 from 2013; 7 only for 2012 (its pictures have stripes after 2003).
LANDSAT_PLATFORMS = {"old": ["landsat-5"], "gap": ["landsat-7"], "new": ["landsat-8", "landsat-9"]}
# Surface reflectance is stored as whole numbers: reflectance = value * 0.0000275 - 0.2, so a value
# of about 7273 is zero. The index expressions take that off before dividing.
_Z = 7272.7
LANDSAT_RGB = "assets=red&assets=green&assets=blue&nodata=0&color_formula=gamma+RGB+2.7,+saturation+1.5,+sigmoidal+RGB+15+0.55"
LANDSAT_INDEX = ("expression=" + ";".join([
    f"(green-nir08)/(green%2Bnir08-{2 * _Z:.0f})",     # water: NDWI above 0
    f"(nir08-red)/(nir08%2Bred-{2 * _Z:.0f})",         # green: NDVI above 0.3
    f"(swir16-nir08)/(swir16%2Bnir08-{2 * _Z:.0f})",   # built-up and bare: NDBI above 0
]) + "&asset_as_band=true&nodata=0&rescale=-1,1&rescale=-1,1&rescale=-1,1&format=png")
TIMELAPSE_MAX_TILES = 16      # per year: the box is read at the closest zoom that fits in 4 x 4 tiles
TIMELAPSE_MAX_KM = 120        # a box at most this wide
TIMELAPSE_ATTRIBUTION = "Landsat 5, 7, 8 and 9 (USGS / NASA), Microsoft Planetary Computer"


def landsat_platforms(year: int) -> list[str]:
    return LANDSAT_PLATFORMS["old"] if year <= 2011 else LANDSAT_PLATFORMS["gap"] if year == 2012 else LANDSAT_PLATFORMS["new"]


def summer_months(lat: float) -> tuple[int, int]:
    """The summer months (first, last) for a latitude: December to March south, June to September north."""
    return (12, 3) if lat < 0 else (6, 9)


def classify_index(water: int, green: int, built: int) -> str:
    """One pixel's cover from its three index bytes (0-255 for -1..1)."""
    if water > 140:               # NDWI > 0.1
        return "water"
    if green > 166:               # NDVI > 0.3
        return "green"
    if built > 127 and green < 153:  # NDBI > 0, NDVI < 0.2
        return "built"
    return "other"


# ----------------------------------------------------------------------------- NZ aerial scans
@dataclass(frozen=True)
class AerialTag:
    id: str
    label: str
    looks: str      # what it looks like from above at about 0.3-0.5 m a pixel
    colour: str
    ticked: bool    # ticked when you open the form
    needs_before: bool = False


AERIAL_TAGS: tuple[AerialTag, ...] = (
    AerialTag("solar_roof", "Rooftop solar", "dark blue or black rectangles in neat rows on a roof", "#f59f00", True),
    AerialTag("pool", "Swimming pool", "a small bright blue or turquoise rectangle or kidney shape in a back yard", "#1c7ed6", True),
    AerialTag("new_house", "New house (not in the older photo)", "a house roof in the newer picture where the older one shows "
              "bare ground, grass or a building site", "#c92a2a", True, needs_before=True),
    AerialTag("empty_section", "Empty section in a subdivision", "a bare or grassed lot with no house, between houses on a new street", "#a0522d", True),
    AerialTag("car", "Cars in car parks", "small rectangles in rows on a car park", "#495057", False),
    AerialTag("boat", "Boats in marinas", "white boat shapes beside jetties or on moorings", "#0b7285", False),
    AerialTag("trampoline", "Trampolines", "a small dark circle with a light rim in a back yard", "#862e9c", False),
    AerialTag("damaged_roof", "Damaged roof", "a roof with holes, missing sheets, blue tarpaulins or debris round it", "#e03131", False),
)
AERIAL_SCAN_ZOOM = 17       # one square = one zoom-17 tile (about 220 m across in New Zealand)
AERIAL_PICTURE_ZOOM = 18    # its picture is put together from four zoom-18 aerial tiles (512 x 512, about 0.45 m a pixel)
AERIAL_TOWN_KM = 15         # finds are counted under the nearest town within this distance
