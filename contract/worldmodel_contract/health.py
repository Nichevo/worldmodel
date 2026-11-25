"""Hospitals from several lists: which lists feed the Hospitals map layer, how the build
merges them, and the official counts the layer is checked against.

Each list's connector stores its own map layer (hospitals_<list>); the build merges them with
Wikidata's 'hospitals' layer into one, keeping one dot where two lists have the same hospital:
a dot within MATCH_M metres of one already kept, with a similar name, or within SAME_M metres
whatever its name (a nameless OpenStreetMap point on a named hospital). The earlier list in
SOURCES wins the dot's name and position; beds are the largest figure any list gives; every
dot says which lists have it ('found')."""

from __future__ import annotations

# Order matters: the first list that has a hospital names and places it.
SOURCES: dict[str, dict] = {
    "wikidata": {"short": "Wikidata", "source_id": "wikidata_places", "layer": "hospitals"},
    "national": {"short": "Official lists", "source_id": "national_hospitals", "layer": "hospitals_national"},
    "osm": {"short": "OpenStreetMap", "source_id": "healthsites_osm", "layer": "hospitals_osm"},
    "overture": {"short": "Overture", "source_id": "overture_hospitals", "layer": "hospitals_overture"},
}
MATCH_M = 300          # a dot this close with a similar name is the same hospital
SAME_M = 60            # ... and this close, whatever the names
NAME_SIMILAR = 0.5     # share of name words (or, for names without spaces, two-letter pieces) in common


def layer_id(source: str) -> str:
    return SOURCES[source]["layer"]


def source_of_layer(layer: str) -> str | None:
    return next((k for k, s in SOURCES.items() if s["layer"] == layer), None)


# Countries Overture's places are read for by default: where Wikidata's hospitals covered under
# a third of official beds in November 2026 and Overture adds many (India 49,000 in a test read).
# China is left out: Overture had only 1,300 hospitals there, OpenStreetMap has 12,000. Countries
# near each other share the cost: South and East Asia together read about 1.5 GB.
OVERTURE_DEFAULT = "IND,IDN,BGD,PAK,VNM,PHL,THA,MYS,BRA,MEX,COL,PER,ARG,NGA,EGY,KEN,ZAF,TUR,IRN"

# Official hospital counts typed in from national statistics, for countries the WHO list lacks
# or has only an old figure for. (country, year, hospitals, publisher, link)
OFFICIAL_COUNTS: tuple[tuple[str, int, int, str, str], ...] = (
    ("CHN", 2023, 38355, "National Health Commission, Statistical Bulletin on Health Development 2023",
     "http://www.nhc.gov.cn/"),
    ("USA", 2022, 6120, "American Hospital Association, Fast Facts on US Hospitals 2024",
     "https://www.aha.org/statistics/fast-facts-us-hospitals"),
)

# Coverage grades: share of the official figure the map layer has.
GRADES = ((0.7, "good"), (0.3, "part"), (0.0, "thin"))
GAP_TOWN_PEOPLE = 100_000   # blank spots: towns this big ...
GAP_KM = 25                 # ... with no dot of the layer this close


def grade(coverage: float | None) -> str:
    if coverage is None:
        return "unknown"
    return next(g for cut, g in GRADES if coverage >= cut)
