"""Forecast accuracy: the cities whose forecasts are recorded and scored (app/api forecast_skill.py).

Each city is scored at its main airport, against the airport's own weather reports (METAR) where
it sends them, and against Open-Meteo's analysis of what happened where it does not (or for hours
it missed). icao None: no reports used, the analysis only.
"""

from __future__ import annotations

from typing import NamedTuple


class SkillCity(NamedTuple):
    id: str
    name: str
    country: str      # ISO3
    region: str
    icao: str | None  # the airport whose reports are the truth
    lat: float        # the city, until the airport's own place is known from its reports
    lon: float


REGIONS = ("Oceania", "East Asia", "South and Southeast Asia", "Middle East", "Europe", "Africa", "North America",
           "South America")

CITIES: tuple[SkillCity, ...] = (
    # Oceania (New Zealand first)
    SkillCity("auckland", "Auckland", "NZL", "Oceania", "NZAA", -36.85, 174.76),
    SkillCity("wellington", "Wellington", "NZL", "Oceania", "NZWN", -41.29, 174.78),
    SkillCity("christchurch", "Christchurch", "NZL", "Oceania", "NZCH", -43.53, 172.64),
    SkillCity("queenstown", "Queenstown", "NZL", "Oceania", "NZQN", -45.03, 168.66),
    SkillCity("dunedin", "Dunedin", "NZL", "Oceania", "NZDN", -45.87, 170.50),
    SkillCity("sydney", "Sydney", "AUS", "Oceania", "YSSY", -33.87, 151.21),
    SkillCity("melbourne", "Melbourne", "AUS", "Oceania", "YMML", -37.81, 144.96),
    SkillCity("brisbane", "Brisbane", "AUS", "Oceania", "YBBN", -27.47, 153.03),
    SkillCity("perth", "Perth", "AUS", "Oceania", "YPPH", -31.95, 115.86),
    SkillCity("adelaide", "Adelaide", "AUS", "Oceania", "YPAD", -34.93, 138.60),
    SkillCity("darwin", "Darwin", "AUS", "Oceania", "YPDN", -12.46, 130.84),
    SkillCity("nadi", "Nadi", "FJI", "Oceania", "NFFN", -17.76, 177.44),
    SkillCity("noumea", "Nouméa", "NCL", "Oceania", "NWWW", -22.27, 166.44),
    SkillCity("honolulu", "Honolulu", "USA", "Oceania", "PHNL", 21.31, -157.86),
    # East Asia
    SkillCity("tokyo", "Tokyo", "JPN", "East Asia", "RJTT", 35.68, 139.69),
    SkillCity("osaka", "Osaka", "JPN", "East Asia", "RJBB", 34.69, 135.50),
    SkillCity("seoul", "Seoul", "KOR", "East Asia", "RKSI", 37.57, 126.98),
    SkillCity("beijing", "Beijing", "CHN", "East Asia", "ZBAA", 39.90, 116.41),
    SkillCity("shanghai", "Shanghai", "CHN", "East Asia", "ZSPD", 31.23, 121.47),
    SkillCity("hong_kong", "Hong Kong", "HKG", "East Asia", "VHHH", 22.32, 114.17),
    SkillCity("taipei", "Taipei", "TWN", "East Asia", "RCTP", 25.03, 121.57),
    # South and Southeast Asia
    SkillCity("singapore", "Singapore", "SGP", "South and Southeast Asia", "WSSS", 1.35, 103.82),
    SkillCity("bangkok", "Bangkok", "THA", "South and Southeast Asia", "VTBS", 13.76, 100.50),
    SkillCity("jakarta", "Jakarta", "IDN", "South and Southeast Asia", "WIII", -6.21, 106.85),
    SkillCity("manila", "Manila", "PHL", "South and Southeast Asia", "RPLL", 14.60, 120.98),
    SkillCity("ho_chi_minh", "Ho Chi Minh City", "VNM", "South and Southeast Asia", "VVTS", 10.82, 106.63),
    SkillCity("kuala_lumpur", "Kuala Lumpur", "MYS", "South and Southeast Asia", "WMKK", 3.14, 101.69),
    SkillCity("delhi", "Delhi", "IND", "South and Southeast Asia", "VIDP", 28.61, 77.21),
    SkillCity("mumbai", "Mumbai", "IND", "South and Southeast Asia", "VABB", 19.08, 72.88),
    SkillCity("bengaluru", "Bengaluru", "IND", "South and Southeast Asia", "VOBL", 12.97, 77.59),
    SkillCity("dhaka", "Dhaka", "BGD", "South and Southeast Asia", "VGHS", 23.81, 90.41),
    SkillCity("karachi", "Karachi", "PAK", "South and Southeast Asia", "OPKC", 24.86, 67.01),
    # Middle East
    SkillCity("dubai", "Dubai", "ARE", "Middle East", "OMDB", 25.20, 55.27),
    SkillCity("riyadh", "Riyadh", "SAU", "Middle East", "OERK", 24.71, 46.68),
    SkillCity("tel_aviv", "Tel Aviv", "ISR", "Middle East", "LLBG", 32.09, 34.78),
    SkillCity("istanbul", "Istanbul", "TUR", "Middle East", "LTFM", 41.01, 28.98),
    SkillCity("tehran", "Tehran", "IRN", "Middle East", "OIII", 35.69, 51.39),
    # Europe
    SkillCity("london", "London", "GBR", "Europe", "EGLL", 51.51, -0.13),
    SkillCity("manchester", "Manchester", "GBR", "Europe", "EGCC", 53.48, -2.24),
    SkillCity("edinburgh", "Edinburgh", "GBR", "Europe", "EGPH", 55.95, -3.19),
    SkillCity("dublin", "Dublin", "IRL", "Europe", "EIDW", 53.35, -6.26),
    SkillCity("paris", "Paris", "FRA", "Europe", "LFPG", 48.86, 2.35),
    SkillCity("berlin", "Berlin", "DEU", "Europe", "EDDB", 52.52, 13.40),
    SkillCity("amsterdam", "Amsterdam", "NLD", "Europe", "EHAM", 52.37, 4.90),
    SkillCity("madrid", "Madrid", "ESP", "Europe", "LEMD", 40.42, -3.70),
    SkillCity("rome", "Rome", "ITA", "Europe", "LIRF", 41.90, 12.50),
    SkillCity("stockholm", "Stockholm", "SWE", "Europe", "ESSA", 59.33, 18.07),
    SkillCity("oslo", "Oslo", "NOR", "Europe", "ENGM", 59.91, 10.75),
    SkillCity("warsaw", "Warsaw", "POL", "Europe", "EPWA", 52.23, 21.01),
    SkillCity("athens", "Athens", "GRC", "Europe", "LGAV", 37.98, 23.73),
    SkillCity("moscow", "Moscow", "RUS", "Europe", "UUEE", 55.76, 37.62),
    SkillCity("kyiv", "Kyiv", "UKR", "Europe", None, 50.45, 30.52),  # airports closed: analysis only
    # Africa
    SkillCity("cape_town", "Cape Town", "ZAF", "Africa", "FACT", -33.92, 18.42),
    SkillCity("johannesburg", "Johannesburg", "ZAF", "Africa", "FAOR", -26.20, 28.05),
    SkillCity("nairobi", "Nairobi", "KEN", "Africa", "HKJK", -1.29, 36.82),
    SkillCity("lagos", "Lagos", "NGA", "Africa", "DNMM", 6.52, 3.38),
    SkillCity("cairo", "Cairo", "EGY", "Africa", "HECA", 30.04, 31.24),
    SkillCity("casablanca", "Casablanca", "MAR", "Africa", "GMMN", 33.57, -7.59),
    SkillCity("addis_ababa", "Addis Ababa", "ETH", "Africa", "HAAB", 9.03, 38.74),
    # North America
    SkillCity("new_york", "New York", "USA", "North America", "KJFK", 40.71, -74.01),
    SkillCity("los_angeles", "Los Angeles", "USA", "North America", "KLAX", 34.05, -118.24),
    SkillCity("chicago", "Chicago", "USA", "North America", "KORD", 41.88, -87.63),
    SkillCity("houston", "Houston", "USA", "North America", "KIAH", 29.76, -95.37),
    SkillCity("miami", "Miami", "USA", "North America", "KMIA", 25.76, -80.19),
    SkillCity("seattle", "Seattle", "USA", "North America", "KSEA", 47.61, -122.33),
    SkillCity("denver", "Denver", "USA", "North America", "KDEN", 39.74, -104.99),
    SkillCity("atlanta", "Atlanta", "USA", "North America", "KATL", 33.75, -84.39),
    SkillCity("san_francisco", "San Francisco", "USA", "North America", "KSFO", 37.77, -122.42),
    SkillCity("toronto", "Toronto", "CAN", "North America", "CYYZ", 43.65, -79.38),
    SkillCity("vancouver", "Vancouver", "CAN", "North America", "CYVR", 49.28, -123.12),
    SkillCity("mexico_city", "Mexico City", "MEX", "North America", "MMMX", 19.43, -99.13),
    # South America
    SkillCity("sao_paulo", "São Paulo", "BRA", "South America", "SBGR", -23.55, -46.63),
    SkillCity("rio", "Rio de Janeiro", "BRA", "South America", "SBGL", -22.91, -43.17),
    SkillCity("buenos_aires", "Buenos Aires", "ARG", "South America", "SAEZ", -34.60, -58.38),
    SkillCity("santiago", "Santiago", "CHL", "South America", "SCEL", -33.45, -70.67),
    SkillCity("lima", "Lima", "PER", "South America", "SPJC", -12.05, -77.04),
    SkillCity("bogota", "Bogotá", "COL", "South America", "SKBO", 4.71, -74.07),
)
BY_ID = {c.id: c for c in CITIES}

# Open-Meteo model key -> name for people
MODELS = {"best_match": "Open-Meteo best match", "ecmwf_ifs025": "ECMWF", "gfs_seamless": "GFS", "icon_seamless": "ICON",
          "ukmo_seamless": "UK Met Office", "gem_seamless": "GEM (Canada)", "jma_seamless": "JMA (Japan)",
          "meteofrance_seamless": "Météo-France"}
