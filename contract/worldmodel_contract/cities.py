"""Cities: the figures kept about each city (table city_series), and how names are compared.

The city list comes from GeoNames (every place of 15,000 people or more). Other
sources name their cities their own way; the build matches each to a GeoNames city
by country and name, or by location where the source gives one (see
worldmodel_data.cities).
"""

from __future__ import annotations

import re
import unicodedata

# indicator_id -> (name, unit, decimals, description, source_id)
CITY_INDICATORS: dict[str, tuple[str, str, int, str, str]] = {
    "city_population": (
        "Population (urban agglomeration)", "persons", 0,
        "People living in the city and its built-up surroundings (the urban agglomeration), UN estimates every five "
        "years from 1950 and projections to 2035 (World Urbanization Prospects 2018).", "un_wup"),
    "ghsl_population": (
        "People in the urban centre (GHSL)", "persons", 0,
        "People living in the urban centre: the contiguous built-up area of 1,500 people per km² or more around the "
        "city, as the European Commission's Global Human Settlement Layer draws it (1975 to 2025, 2030 projected).",
        "ghsl_ucdb"),
    "ghsl_built_km2": (
        "Built-up area (GHSL)", "km²", 1,
        "Land covered by buildings in the urban centre, from satellite pictures (GHSL), 1975 to 2025.", "ghsl_ucdb"),
    "ghsl_density": (
        "People per km² built up (GHSL)", "people/km²", 0,
        "People in the urban centre for each km² of built-up land (GHSL): how tightly the city is packed.", "ghsl_ucdb"),
    "wn_city_cost_index": (
        "Cost of living index (WhereNext)", "index", 0,
        "WhereNext's cost of living index for the city, anchored on World Bank price levels (higher is dearer).",
        "wherenext"),
    "wn_city_monthly_cost_usd": (
        "Monthly cost for one person (WhereNext)", "US$", 0,
        "WhereNext's estimate of a single person's monthly living costs in the city, rent included, in US dollars.",
        "wherenext"),
    "wn_city_quality_score": (
        "Quality of life score (WhereNext)", "score", 1,
        "Equal-weight mean of WhereNext's safety, healthcare, education, city transport and career scores (0 to 100).",
        "wherenext"),
    "wn_city_value_score": (
        "Value for money (WhereNext)", "points", 1,
        "Quality percentile minus cost percentile among WhereNext's cities: above zero, more quality than the cost "
        "suggests.", "wherenext"),
    "numbeo_cost_of_living": (
        "Cost of living index, excluding rent (Numbeo)", "index (New York = 100)", 1,
        "Numbeo's consumer prices index, rent excluded, relative to New York City (100). Crowd-sourced prices.",
        "numbeo"),
    "numbeo_rent": (
        "Rent index (Numbeo)", "index (New York = 100)", 1,
        "Numbeo's index of apartment rents relative to New York City (100).", "numbeo"),
    "numbeo_cost_plus_rent": (
        "Cost of living plus rent index (Numbeo)", "index (New York = 100)", 1,
        "Numbeo's consumer prices including rent, relative to New York City (100).", "numbeo"),
    "numbeo_groceries": (
        "Groceries index (Numbeo)", "index (New York = 100)", 1,
        "Numbeo's grocery prices relative to New York City (100).", "numbeo"),
    "numbeo_restaurants": (
        "Restaurant price index (Numbeo)", "index (New York = 100)", 1,
        "Numbeo's prices of meals and drinks in restaurants and bars relative to New York City (100).", "numbeo"),
    "numbeo_purchasing_power": (
        "Local purchasing power (Numbeo)", "index (New York = 100)", 1,
        "How much the average net salary buys of goods and services in the city, relative to New York City (100).",
        "numbeo"),
}

# Numbeo's table headings, compared loosely, and the indicator each one gives.
NUMBEO_COLUMNS = {
    "costoflivingindex": "numbeo_cost_of_living",
    "rentindex": "numbeo_rent",
    "costoflivingplusrentindex": "numbeo_cost_plus_rent",
    "groceriesindex": "numbeo_groceries",
    "restaurantpriceindex": "numbeo_restaurants",
    "localpurchasingpowerindex": "numbeo_purchasing_power",
}


def norm_name(s: str | None) -> str:
    """A place name compared loosely: no accents, lower case, letters and digits only,
    and without words such as "city" that sources add or leave out."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(city of|city|municipality|metropolitan area|metro)\b", " ", s)
    s = s.replace("saint ", "st ").replace("sainte ", "ste ")
    return re.sub(r"[^a-z0-9]", "", s)
