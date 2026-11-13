"""The local data folder, as both sides see it: user settings, disk use and the refresh log.

The pipeline writes raw downloads, vintages, builds and the refresh log; the app
writes only user files (settings, layouts, history) under user/. Both need the
same answers to "where is everything, how big is it, what are the limits", so
those live here rather than in either side.

    <home>/raw/        source files as downloaded         (pipeline)
    <home>/vintages/   normalised Parquet per vintage     (pipeline)
    <home>/warehouse/  builds, reports, refresh_log.jsonl (pipeline)
    <home>/media/      pictures and page caches           (app: Wikipedia pages fetched on demand)
    <home>/user/       settings, layouts, history         (app)

home is WORLDMODEL_HOME, else a WORLDMODEL_WAREHOUSE that names a folder, else ./var.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

GB = 1024 ** 3

# Every user setting with its default. The app's Settings page edits these; the
# pipeline reads the storage limits. Unknown keys in the file are ignored.
SETTINGS: dict[str, object] = {
    "click_mode": "popup",          # "popup": click opens a popup, shift-click selects; "select": click selects, double-click opens
    "hover_sparkline": True,         # small trend line in the map tooltip
    "popup_tabs": True,              # popups get a tab per indicator shown in the panels
    "side_panel": True,              # the pinboard down the right of the map page
    "disk_limit_gb": 100.0,          # the whole data folder
    "pictures_limit_gb": 2.0,        # media/ (pictures, cached pages)
    "basemap_limit_gb": 20.0,        # basemap/ (the local map files)
    "map_centre": "pacific",         # world maps open centred on the Pacific (New Zealand near the middle) or on "atlantic" (Europe and Africa)
    "base_map": "online",            # map detail under the colours: "online" (OpenFreeMap), "local" (map files on this PC) or "plain"
    "basemap_regions": "nzl",        # countries the local map file holds in full detail (street level)
    "basemap_world_zoom": 8,         # how far the local world file goes (6 big towns and motorways ... 10 small towns and most roads)
    "basemap_region_zoom": 15,       # how far the full-detail countries go (15 = every street and building)
    "numbeo_daily": 20,              # single-page Numbeo fetches per day, all countries together
    "wikipedia_countries_daily": 20,
    "wikipedia_cities_daily": 10,
    "wikipedia_empires_daily": 20,   # Long history: Wikipedia pages for empires, dynasties and voyages, fetched when opened
    "wikipedia_background": True,    # fetch pages not yet opened, a few an hour, within half the daily limit
    "history_paused": False,
    "history_retention_days": 0,     # 0 keeps history forever
    "problem_banner": True,          # a banner on every page while a refresh problem is open
    "events_on_charts": True,        # dated events as lines and bands on line charts of up to three countries
    "profile_charts": "",            # indicator ids charted on country pages, in order ("" = the standard set)
    "profile_cards_hidden": "",      # country page cards switched off (debt, housing, cities...)
    "profile_saved": {},             # named country page set-ups: name -> {charts, hidden}
    "profile_average": "",           # a group (oecd, g20, world...) whose average joins a country page's rate charts
    "projections_on_charts": True,   # years after the last estimate (UN projections and the like) on charts
    "chart_end_labels": True,        # line charts name each line at its end, with its latest value, instead of a legend
    "chart_values": True,            # bar charts write their values on the bars
    "chart_findings": True,          # chart titles lead with what the chart shows ("lowest since 1960")
    "event_labels": True,            # event bands carry their name on the chart, not only on hover
    "event_kinds": "recession,crisis,coup,conflict,disaster,sport,notable,user",  # kinds shown on charts
    "disaster_min_deaths": 100,      # smaller disasters and epidemics stay off the charts (still listed)
    "transport_min_deaths": 10,      # air, sea and rail accidents with fewer deaths stay off the charts and Events page
    "party_colours": False,          # country page charts coloured by the party in government
    "party_office": "government",    # whose party: the head of "government" (a prime minister) or of "state"
    "ranks_top_n": 10,               # Ranks panels show this many lines unless the panel says otherwise (0 = all)
    "forecast_horizon": 10,          # years the Forecast button on charts looks ahead
    "forecast_ranges": "80+95",      # ranges drawn around a forecast: "80+95", "80" or "none"
    "forecast_official": True,       # with Forecast on, also draw each forecaster's own projections (IMF, OECD, World Bank)
    "places_fetch": True,            # refresh fetches metro and rail, universities and companies from Wikidata (every 4 weeks)
    "map_hospital_beds": 200,        # the Hospitals map layer shows hospitals with at least this many beds
    "map_hospitals_unsized": False,  # ... and also well-known hospitals with no bed count in Wikidata
    # Long history
    "history_borders_fetch": True,   # refresh fetches Cliopatria's borders of states and empires (46 MB, twice a year)
    "history_series_fetch": True,    # refresh fetches long-run figures through Our World in Data (every three months)
    "history_events_fetch": True,    # refresh fetches wars, battles, epidemics... (Wikidata, monthly) and NOAA's hazards
    "history_event_min_links": 5,    # events shown: those with articles in at least this many Wikipedias
    "history_events_on_charts": True,  # events far back as marks on the long charts
    "map_history_year": 1700,        # the year the Map's "World in year" layer shows (it has its own slider)
    "pack_nz": True,                 # refresh fetches the New Zealand pack (RBNZ, MBIE energy, elections, justice)
    "holidays_fetch": True,          # refresh reads public holidays from Nager.Date (about 240 small requests every 90 days)
    "crisiswatch_fetch": True,       # refresh reads CrisisWatch (one month's page at a time, a few seconds apart)
    "crisiswatch_backfill": 12,      # older CrisisWatch months filled in per refresh, back to 2003 (0 = only the latest)
    "scrape_gap_seconds": 6,         # seconds between web pages read by the scraping tools; longer runs wait longer (see worldmodel_data.scrape)
    "voting_compare": "USA,CHN,RUS,eu",  # who a country's UN votes are compared with on its Voting card
    # Relationship scan (after each refresh): which figures move together, which comes first
    "relations_scan": True,          # look for relationships after each refresh (and once after update.bat)
    "relations_only_new": True,      # skip the scan when no figure it reads has changed since the last one
    "relations_indicators": "on",    # "on": the indicators switched on (about 120, some 7,000 pairs); "all": every one (overnight)
    "relations_min_countries": 30,   # a pair needs this many countries with data for both
    "relations_min_years": 10,       # and this many years of changes in each of those countries
    "relations_max_minutes": 15,     # stop and keep what is done after this long
    "relations_fdr": 0.05,           # share of reported pairs allowed to be chance finds (false discovery rate)
    # Sectors: one industry across the globe (trade from CEPII BACI, about 2 GB a year)
    "sectors_trade_fetch": True,     # refresh downloads BACI trade by product (every four months)
    "sectors_trade_from": 2005,      # first year of trade kept (BACI starts in 1995; earlier years make the warehouse bigger)
    "sectors_hidden": "",            # sectors left off the Sectors page, comma-separated ids
    # Climate
    "climate_fetch": True,           # refresh fetches the climate sources (temperatures, gases, storms, alerts, projections)
    "climate_storms_from": 1980,     # first year of storm tracks kept on the map (IBTrACS starts in 1980 in this file)
    "climate_live_map": True,        # the Climate page's storms map asks GDACS for the storms, floods and fires happening now
    "hazards_live": True,            # the map's fires, heatwave and coral bleaching layers read NASA, Open-Meteo and NOAA when on
    # Nature and pollution (connectors/nature.py)
    "nature_zones_fetch": True,          # refresh reads the Köppen-Geiger climate zones once (a 1 GB zip, about 20 MB kept)
    "nature_climate_extras_fetch": True,  # Berkeley Earth temperatures, PSMSL tide gauges, ND-GAIN adaptation index
    "nature_pollution_fetch": True,      # UN SDG water, wastewater and protected key areas (every three months)
    "nature_species_fetch": True,        # invasive species (GRIIS), IUCN Red List and EPPO pests (the last two need keys)
    "nature_protected_fetch": True,      # WDPA protected areas (900 MB twice a year, about 150 MB kept)
    # Transport, tourism and networks (connectors/transport.py, tourism.py, networks.py)
    "transport_ports_fetch": True,       # IMF PortWatch ports, chokepoints and port calls (weekly), World Port Index, shipping lanes
    "transport_air_fetch": True,         # OurAirports and Eurostat airport passengers and freight
    "transport_waterways_fetch": True,   # inland waterways (US network, OpenStreetMap for Europe and big rivers) and Eurostat river freight
    "tourism_fetch": True,               # UNESCO World Heritage sites
    "rivers_fetch": True,                # HydroRIVERS rivers and HydroBASINS basins (about 700 MB once, about 100 MB kept)
    "cables_fetch": True,                # TeleGeography undersea cables (each cable's details read a few at a time)
    "power_fetch": True,                 # WRI power plants (a 10 MB file twice a year) and gridfinder power lines (700 MB once)
    "outlook_fetch": True,               # OECD leading indicators and quarterly GDP (weekly), US yield curve and GDPNow from FRED
    "attention_on": True,                # Wikipedia page views per country (one request per country page opened, one a day for the Briefing)
    "calendar_live": True,               # release dates from the ONS (UK) and ABS (Australia) sites, once a day
    "energy_infrastructure_fetch": True,  # Global Energy Monitor pipelines and LNG terminals (files saved by hand)
    "live_planes": True,                 # the map's Planes now layer asks OpenSky for planes in view (when the layer is on)
    "live_ships": True,                  # the map's Ships now layer listens to aisstream.io (needs AISSTREAM_API_KEY)
    # Land, cities and trees (connectors/land.py; FAOSTAT land use comes with the sectors' FAOSTAT files)
    "land_history_fetch": True,          # HYDE cropland and grazing land by country back to 1700 (via Our World in Data, once a year)
    "land_cities_fetch": True,           # GHSL urban centres: people, built-up area and outlines of about 11,000 cities (300 MB once a year)
    "land_trees_fetch": True,            # Global Forest Watch tree cover and loss by country; council tree lists (Auckland)
    "land_nz_fetch": True,               # read the NZ Land Cover Database and MPI forestry files you save by hand
    "land_city_cover": True,             # city land cover worked out from the WorldCover map pictures (on request, a few dozen tiles a city)
    "land_cover_year": "2021",           # WorldCover year for the land cover background and city shares: "2021" or "2020"
    # Predictions and crowd forecasts (connectors/crowd.py; your log in predictions.json)
    "crowd_polymarket": True,            # read Polymarket's questions and prices at each refresh (no account)
    "crowd_metaculus": True,             # read Metaculus questions and the community forecast (needs METACULUS_TOKEN in .env)
    "crowd_manifold": True,              # read Manifold's questions and chances (no account)
    "crowd_comments": True,              # read Metaculus comments on followed and much-discussed questions
    "crowd_mine": True,                  # import your own Metaculus forecasts (and a bot's, with METACULUS_BOT_TOKEN)
    "crowd_categories": "politics,economics,geopolitics,climate,science",  # which questions are read
    "crowd_move_points": 10,             # a move this big (percentage points in a week) counts as a big move and an alert
    "crowd_score_days": 7,               # crowd sites are scored on their chance this many days before a question closed
    "views_fetch": True,                 # ViEWS conflict forecasts by country (monthly, about 5 MB)
    "predictions_on_charts": True,       # your predictions as dots on the charts of the indicator they are about
    "watchlist_on": True,                # check the watchlist after each refresh and show its alerts on the Briefing
    # Maps (Settings > Maps)
    "map_look": "plain",                 # under the country colours: "plain", "relief" (shaded heights and sea depths), "satellite", "night" (night lights) or "landcover" (ESA WorldCover)
    "relief_style": "classic",           # "classic" (height colours + shading), "grey" (shading only) or "satellite" (shading over the satellite picture)
    "relief_shading": 0.6,               # how strong the hill shading is (0 to 1)
    "map_colours_over": 0.55,            # how solid the country colours are over relief, satellite or night lights (0 to 1)
    "night_year": "2016",                # night lights: "2016" or "2012" (NASA Black Marble), or "latest" (last night's VIIRS picture)
    "map_3d": False,                     # tilt the map and raise the land (right-drag or Ctrl-drag to tilt)
    "map_3d_exaggeration": 1.5,          # how much the land is raised in 3D
    "map_tiles": "local_first",          # relief, satellite and night pictures: "local_first" (saved copies, online for the rest) or "online"
    "map_tiles_starter": True,           # download the starter copies once: world relief to zoom 6, NZ relief, satellite and land cover closer, newest night lights
    "map_true_size": True,               # Map shapes page: true size, equal-area view and cartograms
    "space_fetch": True,                 # Solar system page: asteroids (JPL), mission paths (JPL Horizons), about 50 MB
    "space_values": False,               # Solar system page: Asterank's guessed dollar values for asteroids
    "zones_scenario": "ssp245",          # the emissions path the climate zone maps and city twins use for future periods
    # Internet speeds
    "internet_speeds_fetch": True,     # refresh fetches Ookla's open Speedtest files (quarterly, 200-400 MB each, summed by country then deleted)
    "internet_speeds_from": 2019,      # first year of internet speeds kept (Ookla's open data starts in 2019)
    "internet_speeds_per_refresh": 8,  # Ookla files read in one refresh at most (newest first; older quarters follow at later refreshes)
    # Local AI (Ollama on this PC or another; the app's server talks to it)
    "ai_enabled": True,              # Ask AI buttons, the AI notes page and the highlight menu's Ask AI
    "ollama_url": "http://localhost:11434",
    "ai_model": "",                  # default model; "" = the first one installed
    "ai_model_compare": "",          # the model offered for side-by-side answers; "" = none
    "ai_compare_default": False,     # each question goes to both models unless you take the second off
    "ai_temperature": 0.3,
    "ai_context_tokens": 16384,      # Ollama num_ctx: how much text the model reads at once
    "ai_context_default": "data,description,events,highlight",  # context parts ticked by default
    "ai_search_engine": "brave",     # "brave" (needs BRAVE_API_KEY; can cost money), "searxng" (free, local) or "off"
    "searxng_url": "http://localhost:8080",
    "ai_search_results": 5,          # web results given to the model per question
    "ai_search_default": True,       # Search the web is ticked when the Ask AI box opens
    "brave_daily_limit": 30,         # Brave searches a day; 0 = no limit
    "brave_monthly_limit": 0,        # Brave searches a month; 0 = no limit
    "brave_free_monthly": 1000,      # searches the monthly credit covers ($5 at $5 per 1,000)
    "brave_price_per_1000": 5.0,     # US dollars per 1,000 searches past the credit
    "highlight_menu": True,          # selecting text on a page shows Ask AI / Save highlight
    # Indicator quality (grades A to D; see worldmodel_contract.quality)
    "quality_show": "B",             # indicator drop-downs list grades up to this: "A", "B", "C", "all" or "starred" (starred ones always show)
    "quality_type": "",              # and only this measure type ("" = all): level, per_person, rate, index, money, count, projection
    "quality_on_titles": False,      # the grade beside each chart's title
    # Markets: exchange rates and storage
    "markets_daily": True,           # refresh fetches daily data (ECB and Fed exchange rates, European gas storage)
    "storage_chart": "clock",        # the Storage page draws a year as a "clock" (round) or as one line per year
    "storage_years": 5,              # years in the band (lowest to highest) and average the current year is set against
    "fx_partners": {},               # country id -> currencies' countries on its Currency card (else its top trading partners)
    # Discover: interesting finds after each refresh, and major news
    "discover_on": True,             # look for finds after each refresh (and once after update.bat)
    "discover_checks": "record,mover,turning,overtake,outlier,disagree,forecast,together,after,revised,opposite",
    "discover_keep": 500,            # finds kept per build, best first
    "discover_key_countries": "NZL,AUS,GBR,USA",  # boosted, and the ones checked for overtakes, revisions and forecasts
    "discover_key_boost": 1.5,       # how much a key country's finds are lifted (1 = not at all)
    "discover_merge": True,          # the same find in several countries shown once, as lines against the world (off: one card per country)
    "discover_tune": True,           # your Interesting / Not interesting ratings lift or sink kinds, categories and tags
    "discover_ai": False,            # a "Why might this be?" button on each card, answered by your local AI (marked as its guess)
    "discover_better": {},           # indicator id -> "higher", "lower" or "neither": your own "better when" for a find's tone
    "news_on": True,                 # the News tab fetches major news (no key needed)
    "news_sources": "wikipedia,gdelt,feeds",  # wikipedia (Current events), gdelt (news counts and spikes), feeds (headlines), reliefweb
    "news_feeds": "rnz,stuff,abc,bbc,guardian",
    "news_reliefweb_app": "",        # ReliefWeb only answers app names it has approved (free: apidoc.reliefweb.int); blank = off
    "news_keep_days": 730,           # how far back news is kept
    "news_every_hours": 6,           # news is fetched again when the News tab is opened this long after the last time
    # Briefing, the map's events and the Layers panel
    "start_page": "briefing_after_refresh",  # what the Map link and the app open on: "briefing_after_refresh", "briefing" or "map"
    "briefing_days": 7,              # the Briefing's "Happening" lane looks back this many days
    "map_open_layers": "wen",        # layers the opening map turns on (letters, see the Layers panel): w CrisisWatch, e events, n news watch words
    "map_window": "30d",             # time window for timed map layers (events, earthquakes, storms, news): 7d, 30d, 90d or 1y
    "map_layer_sets": {},            # your own quick sets in the Layers panel: name -> layer letters
    "news_watch_words": "assassination,assassinated,coup,protest,protests,riot,riots,uprising,martial law,state of emergency,"
                        "ceasefire,invasion,airstrike,air strike,massacre,hostage,blockade,sanctions,default,impeachment,resigns,"
                        "tsunami,eruption,famine,outbreak",  # news naming one of these words is put on the map, hollow until a dataset confirms it
    "news_watch_outlets": 1,         # how many outlets must report it before a watch-word item shows on the map
    # WORLD Policy Analysis Center on Harvard Dataverse: its guestbook asks who is downloading
    "world_dataverse_fetch": True,   # refresh downloads WORLD's data files every 90 days once the guestbook is filled in
    "world_dataverse_name": "",      # the guestbook answers, sent with each download (kept on this PC only)
    "world_dataverse_email": "",
    "world_dataverse_institution": "",
    "world_dataverse_position": "",
    "world_dataverse_purpose": "Personal, non-commercial research",
    "world_dataverse_datasets": "",  # words or DOIs picking datasets (comma-separated); blank = every dataset with a data file
    "flags_on": True,                # small flags beside country names (in pickers, headings, tables and cards)
    # Looking after the sources (To do page, inbox, backups, scheduled refresh)
    "inbox_downloads": True,         # also file recent downloads from your Downloads folder whose source is certain (copied, never moved)
    "inbox_downloads_days": 14,      # how far back in Downloads to look
    "inbox_downloads_folder": "",    # blank: your own Downloads folder
    "sources_off": "",               # sources switched off on Data status: never fetched, never on the To do list
    "schedule_on": False,            # Windows runs refresh.bat on its own
    "schedule_often": "weekly",
    "schedule_day": "sun",
    "schedule_time": "03:00",
    "backup_on_update": True,        # update.bat backs up your saved files, settings and keys first (once a day at most)
    "backup_folder": "",             # blank: worldmodel-backups beside the worldmodel folder
    "backup_keep": 10,               # backups kept; older ones the app made are removed
    "backup_big_mb": 200,            # files bigger than this (big downloads the site can give again) are left out; 0 keeps all
    # The public API (/api/public/v1) for scripts, the Python client, Excel and AI assistants (Settings > API access)
    "api_public_on": False,          # off: nothing outside the app itself can read the data through the public API
    "api_daily_limit": 2000,         # calls a day for each key (calls from this PC need no key and are not limited)
    # The weekly digest (Briefing > Week)
    "digest_on": True,               # make each week's digest on the first visit after Monday, and keep it
}
CHOICES = {"click_mode": ("popup", "select"), "party_office": ("government", "state"),
           "forecast_ranges": ("80+95", "80", "none"), "ai_search_engine": ("brave", "searxng", "off"),
           "base_map": ("online", "local", "plain"),
           "map_look": ("plain", "relief", "satellite", "night", "landcover"), "relief_style": ("classic", "grey", "satellite"),
           "night_year": ("2016", "2012", "latest"), "land_cover_year": ("2021", "2020"), "map_tiles": ("local_first", "online"), "map_centre": ("pacific", "atlantic"),
           "relations_indicators": ("on", "all"), "storage_chart": ("clock", "lines"), "quality_show": ("A", "B", "C", "all", "starred"),
           "quality_type": ("", "level", "per_person", "rate", "index", "money", "count", "projection"),
           "start_page": ("briefing_after_refresh", "briefing", "map"), "map_window": ("7d", "30d", "90d", "1y"),
           "schedule_often": ("weekly", "daily"), "schedule_day": ("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
           "schedule_time": tuple(f"{h:02d}:{m}" for h in range(24) for m in ("00", "30"))}
# Free text settings (addresses and model names), kept to one line.
TEXTS = {"ollama_url", "ai_model", "ai_model_compare", "searxng_url", "news_reliefweb_app", "world_dataverse_name",
         "world_dataverse_email", "world_dataverse_institution", "world_dataverse_position", "world_dataverse_purpose",
         "world_dataverse_datasets", "inbox_downloads_folder", "backup_folder"}
URLS = {"ollama_url", "searxng_url"}
IDS = {"profile_average"}
IDLISTS = {"profile_charts", "profile_cards_hidden", "voting_compare", "sectors_hidden", "discover_key_countries", "sources_off"}  # comma-separated ids, order kept
PARTNERS = {"fx_partners"}  # entity id -> idlist, at most 300
LETTERS = {"map_open_layers"}  # map layer letters, each once
LAYERSETS = {"map_layer_sets"}  # name -> layer letters, at most 30
PHRASES = {"news_watch_words"}  # comma-separated words or short phrases, lower case
BETTER = {"discover_better"}  # indicator id -> "higher" | "lower" | "neither", at most 5,000
PROFILES = {"profile_saved"}  # name -> {"charts": idlist, "hidden": idlist}, at most 30
RANGES = {"disk_limit_gb": (1, 10_000), "pictures_limit_gb": (0.1, 1_000), "basemap_limit_gb": (0.1, 5_000),
          "basemap_world_zoom": (4, 15), "basemap_region_zoom": (8, 15), "numbeo_daily": (0, 200),
          "wikipedia_countries_daily": (0, 500), "wikipedia_cities_daily": (0, 500), "wikipedia_empires_daily": (0, 500),
          "history_event_min_links": (5, 200), "map_history_year": (-3400, 2024),
          "history_retention_days": (0, 36_500), "disaster_min_deaths": (0, 1_000_000),
          "transport_min_deaths": (0, 100_000), "relief_shading": (0, 1), "map_colours_over": (0, 1),
          "map_3d_exaggeration": (1, 5),
          "ranks_top_n": (0, 300), "crisiswatch_backfill": (0, 300), "scrape_gap_seconds": (2, 120), "forecast_horizon": (1, 50),
          "relations_min_countries": (5, 200), "relations_min_years": (5, 60), "relations_max_minutes": (1, 1440),
          "relations_fdr": (0.001, 0.25), "sectors_trade_from": (1995, 2030), "climate_storms_from": (1980, 2030), "map_hospital_beds": (0, 10_000), "internet_speeds_from": (2019, 2030), "internet_speeds_per_refresh": (1, 60), "ai_temperature": (0, 2),
          "ai_context_tokens": (1024, 1_048_576), "ai_search_results": (1, 20), "brave_daily_limit": (0, 1_000_000),
          "brave_monthly_limit": (0, 10_000_000), "brave_free_monthly": (0, 10_000_000), "brave_price_per_1000": (0, 1_000),
          "storage_years": (2, 15), "discover_keep": (50, 5000), "discover_key_boost": (1, 5), "news_keep_days": (7, 36_500),
          "news_every_hours": (1, 720),
          "briefing_days": (1, 90), "news_watch_outlets": (1, 5), "crowd_move_points": (1, 50), "crowd_score_days": (0, 365),
          "inbox_downloads_days": (1, 365), "backup_keep": (1, 100), "backup_big_mb": (0, 100_000),
          "api_daily_limit": (10, 1_000_000)}
WARN_AT, CRITICAL_AT = 0.80, 0.95

# Disk categories, in display order. "pictures" is media/ and has its own limit.
CATEGORIES = [("raw", "Raw downloads"), ("vintages", "Vintages (Parquet)"), ("builds", "Warehouse builds"),
              ("reports", "Reports and logs"), ("pictures", "Pictures and pages"), ("basemap", "Map files"), ("user", "Your files"),
              ("other", "Other")]


def home() -> Path:
    if os.environ.get("WORLDMODEL_HOME"):
        return Path(os.environ["WORLDMODEL_HOME"]).expanduser()
    wh = os.environ.get("WORLDMODEL_WAREHOUSE", "")
    if wh and Path(wh).expanduser().is_dir():
        return Path(wh).expanduser()
    return Path.cwd() / "var"


def user_dir() -> Path:
    """WORLDMODEL_USER_DIR, else WORLDMODEL_HOME/user, else ./var/user (where layouts have always been)."""
    if os.environ.get("WORLDMODEL_USER_DIR"):
        return Path(os.environ["WORLDMODEL_USER_DIR"]).expanduser()
    h = os.environ.get("WORLDMODEL_HOME")
    return (Path(h).expanduser() if h else Path.cwd() / "var") / "user"


def refresh_log_path(root: Path | None = None) -> Path:
    return (root or home()) / "warehouse" / "refresh_log.jsonl"


def scrape_log_path(root: Path | None = None) -> Path:
    return (root or home()) / "warehouse" / "scrape_log.json"


def read_scrape_log(root: Path | None = None) -> dict[str, dict]:
    """The last run of each source that reads web pages: source_id -> {at, planned, read,
    stopped (why it stopped early, or None), url, gap_seconds}. Written by worldmodel_data.scrape."""
    try:
        data = json.loads(scrape_log_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ----------------------------------------------------------------------------- settings
def _idlist(v) -> str:
    """Comma-separated ids, each checked, repeats dropped, order kept."""
    ids = [w.strip() for w in str(v or "").split(",")]
    return ",".join(dict.fromkeys(w for w in ids if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", w)))[:8000]


def _letters(v) -> str:
    """Map layer letters, each once, in the order given."""
    return "".join(dict.fromkeys(c for c in str(v or "") if "a" <= c <= "z" or "A" <= c <= "Z"))[:52]


def clean_settings(data: dict, base: dict | None = None) -> dict:
    """The known settings from data, each checked and held to its range; the rest
    (and anything invalid) come from base, else the defaults."""
    out = dict(base or SETTINGS)
    for key, default in SETTINGS.items():
        if key not in data:
            continue
        v = data[key]
        if isinstance(default, bool):
            out[key] = bool(v)
        elif key in PROFILES:
            if isinstance(v, str):
                try:
                    v = json.loads(v or "{}")
                except ValueError:
                    continue
            if not isinstance(v, dict):
                continue
            out[key] = {" ".join(str(name).split())[:40]: {f: _idlist(p.get(f)) for f in ("charts", "hidden")}
                        for name, p in list(v.items())[:30] if str(name).strip() and isinstance(p, dict)}
        elif key in PARTNERS:
            if isinstance(v, str):
                try:
                    v = json.loads(v or "{}")
                except ValueError:
                    continue
            if not isinstance(v, dict):
                continue
            out[key] = {str(k)[:40]: _idlist(x) for k, x in list(v.items())[:300]
                        if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(k)) and _idlist(x)}
        elif key in BETTER:
            if isinstance(v, str):
                try:
                    v = json.loads(v or "{}")
                except ValueError:
                    continue
            if not isinstance(v, dict):
                continue
            out[key] = {str(k)[:80]: x for k, x in list(v.items())[:5000]
                        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", str(k)) and x in ("higher", "lower", "neither")}
        elif key in LAYERSETS:
            if isinstance(v, str):
                try:
                    v = json.loads(v or "{}")
                except ValueError:
                    continue
            if not isinstance(v, dict):
                continue
            out[key] = {" ".join(str(name).split())[:40]: _letters(x) for name, x in list(v.items())[:30]
                        if str(name).strip() and _letters(x)}
        elif key in LETTERS:
            out[key] = _letters(v)
        elif key in PHRASES:
            words = [" ".join(w.lower().split()) for w in str(v or "").split(",")]
            words = [w for w in words if re.fullmatch(r"[a-z][a-z' -]{0,39}", w)]
            out[key] = ",".join(dict.fromkeys(words))[:1500]
        elif key in CHOICES:
            if v in CHOICES[key]:
                out[key] = v
        elif key in IDLISTS:
            out[key] = _idlist(v)
        elif key in IDS:  # one entity id such as g20 or NZL, or "" for none
            t = str(v or "").strip()
            if re.fullmatch(r"[A-Za-z0-9_]{0,40}", t):
                out[key] = t
        elif key in TEXTS:
            t = " ".join(str(v or "").split())[:200]
            if key in URLS:
                t = t.rstrip("/")
                if not re.fullmatch(r"https?://[^\s/$.?#][^\s]*", t):
                    continue
            out[key] = t
        elif isinstance(default, str):  # a comma-separated list of words
            out[key] = ",".join(w for w in (x.strip().lower() for x in str(v).split(",")) if re.fullmatch(r"[a-z_]{1,30}", w))[:400]
        elif isinstance(default, (int, float)):
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            lo, hi = RANGES[key]
            num = min(hi, max(lo, num))
            out[key] = int(num) if isinstance(default, int) else round(num, 4)
    return out


def load_settings(root: Path | None = None) -> dict:
    """Settings from the user folder (or root/user when given and no WORLDMODEL_USER_DIR)."""
    base = root / "user" if root and not os.environ.get("WORLDMODEL_USER_DIR") else user_dir()
    path = base / "settings.json"
    try:
        return clean_settings(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(SETTINGS)


# ----------------------------------------------------------------------------- disk use
def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def disk_usage(root: Path | None = None) -> dict[str, int]:
    """Bytes per category, plus "total"."""
    root = root or home()
    out = {k: 0 for k, _ in CATEGORIES}
    if not root.exists():
        return {**out, "total": 0}
    for child in root.iterdir():
        name = child.name
        if name == "warehouse":
            for sub in child.iterdir():
                out["builds" if sub.name == "builds" else "reports"] += _size(sub)
        elif name == "media":
            out["pictures"] += _size(child)
        elif name in out:
            out[name] += _size(child)
        else:
            out["other"] += _size(child)
    out["total"] = sum(out.values())
    return out


def level(used: float, limit: float) -> str:
    share = used / limit if limit else 0
    return "full" if share >= 1 else "critical" if share >= CRITICAL_AT else "warn" if share >= WARN_AT else "ok"


def storage(root: Path | None = None) -> dict:
    """Disk use against the limits in settings, with a warning level for each limit."""
    s = load_settings(root)
    root = root or home()
    use = disk_usage(root)
    disk, pics = s["disk_limit_gb"] * GB, s["pictures_limit_gb"] * GB
    limits = [
        {"key": "disk", "label": "Whole data folder", "used": use["total"], "limit": disk, "level": level(use["total"], disk)},
        {"key": "pictures", "label": "Pictures and pages", "used": use["pictures"], "limit": pics,
         "level": level(use["pictures"], pics)},
        {"key": "basemap", "label": "Map files", "used": use["basemap"], "limit": s["basemap_limit_gb"] * GB,
         "level": level(use["basemap"], s["basemap_limit_gb"] * GB)},
    ]
    order = ["ok", "warn", "critical", "full"]
    worst = max((lim["level"] for lim in limits), key=order.index)
    return {"home": str(root), "categories": [{"key": k, "label": label, "bytes": use[k]} for k, label in CATEGORIES],
            "total": use["total"], "limits": limits, "level": worst, "warn_at": WARN_AT, "critical_at": CRITICAL_AT,
            "freeable": sum(f["bytes"] for f in freeable_raw(root))}


def pictures_room(root: Path | None = None) -> int:
    """Bytes media/ may still grow by before the pictures limit in Settings."""
    limit = load_settings(root)["pictures_limit_gb"] * GB
    media = (root or home()) / "media"
    return int(limit - (_size(media) if media.exists() else 0))


# ----------------------------------------------------------------------------- freeing space
STAMP = re.compile(r"^\d{8}T\d{6}Z$")


def freeable_raw(root: Path | None = None, keep: int = 2) -> list[dict]:
    """Old raw downloads that can go: per source, all but the newest `keep` fetches,
    never one the download cache still points at. Vintages (the normalised data
    every build reads) are never offered."""
    root = root or home()
    raw = root / "raw"
    if not raw.exists():
        return []
    out = []
    for source in sorted(p for p in raw.iterdir() if p.is_dir()):
        try:
            cached = {Path(e["file"]).parent.as_posix() for e in
                      json.loads((source / "http_cache.json").read_text(encoding="utf-8")).values() if e.get("file")}
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            cached = set()
        fetches = sorted((d for d in source.glob("*/*") if d.is_dir() and STAMP.match(d.name)
                          and d.parent.name != "_incoming"), key=lambda d: d.name)
        for d in fetches[:-keep] if keep else fetches:
            rel = d.relative_to(root).as_posix()
            if rel in cached:
                continue
            out.append({"source_id": source.name, "path": rel, "fetched": d.name, "bytes": _size(d)})
    return out


def free_raw(root: Path | None = None, keep: int = 2) -> dict:
    """Delete the old raw downloads listed by freeable_raw. Only ever on request."""
    root = root or home()
    removed, freed = [], 0
    for f in freeable_raw(root, keep):
        shutil.rmtree(root / f["path"], ignore_errors=True)
        if not (root / f["path"]).exists():
            removed.append(f["path"])
            freed += f["bytes"]
            try:  # drop the release folder too once it is empty
                (root / f["path"]).parent.rmdir()
            except OSError:
                pass
    return {"removed": removed, "freed_bytes": freed}


# ----------------------------------------------------------------------------- refresh log
def read_refresh_log(root: Path | None = None) -> list[dict]:
    """One record per refresh or build, oldest first. Builds from before the log
    existed are filled in from their reports and the stored vintages."""
    root = root or home()
    logged: list[dict] = []
    try:
        for line in refresh_log_path(root).read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    logged.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    known = {r.get("build_id") for r in logged}
    backfill = [r for r in _from_reports(root) if r["build_id"] not in known]
    return sorted(logged + backfill, key=lambda r: r.get("started_at") or "")


def _from_reports(root: Path) -> list[dict]:
    reports = root / "warehouse" / "reports"
    if not reports.exists():
        return []
    manifests = []
    for m in (root / "vintages").glob("*/*/manifest.json"):
        try:
            manifests.append(json.loads(m.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    out = []
    previous = ""
    for rep in sorted(reports.glob("*.md")):
        build_id = rep.stem
        try:
            started = datetime.strptime(build_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            text = rep.read_text(encoding="utf-8")
        except (ValueError, OSError):
            continue
        counts = {s: 0 for s in ("pass", "warn", "fail", "skip")}
        for line in text.splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 5 and cells[3] in counts:
                counts[cells[3]] += 1
        # Vintages fetched since the previous build were what this build brought in.
        new = [m for m in manifests if previous < m.get("retrieved_at", "") <= started]
        out.append({
            "build_id": build_id, "kind": "build", "started_at": started, "finished_at": None, "backfilled": True,
            "status": "failed" if "FAILED" in text.split("\n", 3)[2] else "ok", "checks": counts,
            "sources": [{"source_id": m["source_id"], "status": "new", "vintage": m["vintage"], "rows": m.get("row_count"),
                         "download_bytes": sum(f.get("bytes", 0) for f in m.get("files", []))} for m in new],
            "disk": None,
        })
        previous = started
    return out


# ----------------------------------------------------------------------------- problems
# What a failed check means, by check id prefix (first match wins): title, what happened.
CHECK_MEANINGS = (
    ("dbt:unique_combination", "Duplicate rows",
     "A source gave two values for the same country, indicator and year, so the build stopped rather than pick one."),
    ("dbt:within_indicator_bounds", "Values outside the plausible range",
     "Some values are far outside the range set for their indicator, usually a slip or a change of units in the source."),
    ("dbt:not_null", "Required values missing", "Some rows lack a value the warehouse needs, such as a country or indicator."),
    ("dbt:relationships", "Rows that point at nothing",
     "Some rows name a country, indicator or source that the catalogue does not know."),
    ("dbt:accepted_values", "Unexpected codes", "Some rows carry a code (frequency, status, variant, type) that is not allowed."),
    ("dbt:assert_age_groups", "Age groups do not add up", "Population by age does not add up to the total population."),
    ("dbt:assert_", "Totals do not add up", "Totals for the world, continents or groups do not match their parts."),
    ("dbt:", "A warehouse step failed", "One of the steps that builds the warehouse tables stopped with an error."),
    ("coverage:", "Too few countries", "An indicator covers far fewer countries than expected."),
    ("shrinkage", "A source lost many rows",
     "Compared with the last good build, a source or indicator lost a large share of its rows; often a download "
     "cut short or a file whose layout changed."),
    ("spot:", "Known value does not match", "A value checked against its published figure no longer matches."),
    ("whatif:", "Population model check failed", "The population what-if model no longer reproduces the UN figures."),
)
AFTER_FAILED_BUILD = ("Nothing changed in the app: it keeps the last good data. Copy the details and send them "
                      "in the project thread to get it fixed.")
AFTER_FAILED_FETCH = ("The source kept its previous data and the rest of the refresh went ahead. If it keeps "
                      "happening, copy the details and send them in the project thread.")


def _meaning(check_id: str) -> tuple[str, str]:
    for prefix, title, explain in CHECK_MEANINGS:
        if check_id.startswith(prefix):
            return title, explain
    return check_id, "A validation check failed."


def _report_failures(root: Path, build_id: str | None) -> list[dict]:
    """The failed checks of a build from its report, for runs logged before failures were recorded."""
    if not build_id:
        return []
    try:
        text = (root / "warehouse" / "reports" / f"{build_id}.md").read_text(encoding="utf-8")
    except OSError:
        return []
    out, by_id, current = [], {}, None
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 6 and cells[3] == "fail":
            by_id[cells[1]] = {"check_id": cells[1], "kind": cells[2], "detail": cells[4], "examples": []}
            out.append(by_id[cells[1]])
        elif line.startswith("## "):
            m = re.match(r"## Failing rows: (.+)$", line)
            current = by_id.get(m.group(1).strip()) if m else None
        elif current is not None and line.startswith("- ") and len(current["examples"]) < 12:
            current["examples"].append(line[2:])
    return out


def problems(root: Path | None = None) -> list[dict]:
    """Each distinct failure in the refresh log (a failed check, a source that could not be
    downloaded, a build that stopped), with how often it happened, when first and last,
    and whether it is still open (no successful run since). Open ones first, newest first."""
    root = root or home()
    try:
        from worldmodel_contract import catalogue
        names = {s.id: s.name for s in catalogue.sources().values()}
    except Exception:  # noqa: BLE001 - names are a nicety
        names = {}
    runs = read_refresh_log(root)
    found: dict[str, dict] = {}

    def note(key: str, when: str, run: dict, **info) -> None:
        p = found.setdefault(key, {"key": key, "times": 0, "first_seen": when, "in_a_row": 0, "runs": [], **info})
        p.update({k: v for k, v in info.items() if v not in (None, "", [])})
        p["times"] += 1
        p["last_seen"] = when
        p["build_id"] = run.get("build_id")
        p["runs"].append(when)

    builds: list[tuple[str, set[str] | None]] = []  # (when, failing check keys); None when not known
    fetches: dict[str, list[tuple[str, bool]]] = {}  # source -> (when, fetched ok)
    for run in runs:
        when = run.get("started_at") or ""
        for s in run.get("sources") or []:
            sid = s.get("source_id")
            if s.get("status") == "error":
                note(f"fetch:{sid}", when, run, kind="fetch", source_id=sid,
                     title=f"Download failed: {names.get(sid, sid)}",
                     explain="The source could not be fetched.", todo=AFTER_FAILED_FETCH,
                     summary=s.get("error") or "", examples=[])
            if s.get("status") in ("new", "unchanged", "error") or s.get("settled"):  # settled: skipped on purpose, nothing to fix
                fetches.setdefault(sid, []).append((when, s.get("status") != "error"))
        if run.get("kind") == "load":  # files loaded by hand: they clear a refused download, but are not a build
            continue
        if run.get("status") == "ok":
            builds.append((when, set()))
            continue
        if run.get("status") != "failed":
            continue
        failures = run.get("failures")
        if failures is None:
            failures = _report_failures(root, run.get("build_id"))
        keys: set[str] | None = set()
        if not failures:
            error = run.get("error") or "the build stopped"
            key = "build:" + re.sub(r"\d+", "#", error.split(":")[0])[:80]
            note(key, when, run, kind="build", title="The build stopped", explain=error, todo=AFTER_FAILED_BUILD,
                 summary=error, examples=[])
            keys = None if "validation gate" in error else {key}  # gates failed but not recorded: unknown which
        for f in failures:
            cid = f.get("check_id", "?")
            title, explain = _meaning(cid)
            note(f"check:{cid}", when, run, kind="check", check_id=cid, title=title, explain=explain,
                 todo=AFTER_FAILED_BUILD, summary=f.get("detail") or "", examples=f.get("examples") or [])
            keys.add(f"check:{cid}")
        builds.append((when, keys))

    for p in found.values():
        # Each later attempt either shows the problem again or shows it gone; a build stops
        # on every failing check at once, so one failing on something else still clears it.
        if p["kind"] == "fetch":
            attempts = [(w, not ok) for w, ok in fetches.get(p["source_id"], [])]
        else:
            attempts = [(w, p["key"] in k) for w, k in builds if k is not None]
        p["fixed_at"] = next((w for w, hit in attempts if w > p["last_seen"] and not hit), None)
        p["open"] = p["fixed_at"] is None
        n = 0
        for w, hit in reversed([a for a in attempts if a[0] <= p["last_seen"]]):  # failures in a row up to the latest
            if not hit:
                break
            n += 1
        p["in_a_row"] = n
        p.pop("runs")
    out = sorted(found.values(), key=lambda p: p["last_seen"], reverse=True)
    return sorted(out, key=lambda p: not p["open"])
