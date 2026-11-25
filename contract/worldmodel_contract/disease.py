"""Flu, COVID, RSV, measles and other infections over time: the measures the Disease page,
the country card and the API offer, which indicator each reads, and the pandemics drawn
as bands on the long view. Shared by the data side (which indicators its sources stage)
and the app (how each is labelled and compared).

Weekly measures are stored as daily rows on the Monday that starts the week (ISO weeks), so
the same week lines up across sources that count weeks from Sunday (the US) or end them on
Saturday or Sunday.
"""

from __future__ import annotations

# Years whose seasons make the "normal range": the five before COVID, which emptied the 2020
# and 2021 flu seasons and moved RSV's.
BASELINE = (2015, 2019)
# Years left out when no baseline years exist and the range falls back to every earlier year.
SKIP_YEARS = (2020, 2021)

# Diseases in the order the page lists them.
DISEASES: list[dict] = [
    {"key": "flu", "name": "Flu", "about": "Influenza A and B, the seasonal flu."},
    {"key": "rsv", "name": "RSV", "about": "Respiratory syncytial virus: colds in adults, a serious chest infection for babies and the old."},
    {"key": "covid", "name": "COVID-19", "about": "SARS-CoV-2."},
    {"key": "measles", "name": "Measles", "about": "Very catching; kept away only where nearly everyone is vaccinated."},
    {"key": "pertussis", "name": "Whooping cough", "about": "Pertussis: comes back every three to five years."},
    {"key": "dengue", "name": "Dengue", "about": "Spread by mosquitoes in the tropics; spreading as they do."},
    {"key": "norovirus", "name": "Norovirus", "about": "The winter vomiting bug."},
    {"key": "mpox", "name": "Mpox", "about": "Formerly monkeypox."},
    {"key": "deaths", "name": "Deaths from all causes", "about": "Every death by week, the measure flu winters and pandemics show up in."},
]

# Weekly measures. kind: pct (a share, 0-100), rate (per 100,000 or per million), count.
# better: always "lower". sources names the publishers, for captions.
MEASURES: list[dict] = [
    {"id": "flu_pct_positive", "disease": "flu", "label": "Flu: share of tests positive", "unit": "%", "kind": "pct",
     "sources": "WHO FluNet", "main": True},
    {"id": "flu_admissions_per_100k", "disease": "flu", "label": "Flu: hospital admissions per 100,000", "unit": "per 100,000", "kind": "rate",
     "sources": "UKHSA (England), CDC NHSN (US)"},
    {"id": "ili_pct_visits", "disease": "flu", "label": "Flu-like illness: share of doctor visits (US)", "unit": "%", "kind": "pct",
     "sources": "CDC ILINet through Delphi"},
    {"id": "ili_rate_per_100k", "disease": "flu", "label": "Flu-like illness: GP visits per 100,000 (Europe)", "unit": "per 100,000", "kind": "rate",
     "sources": "ECDC ERVISS"},
    {"id": "rsv_pct_positive", "disease": "rsv", "label": "RSV: share of tests positive", "unit": "%", "kind": "pct",
     "sources": "WHO FluNet", "main": True},
    {"id": "rsv_admissions_per_100k", "disease": "rsv", "label": "RSV: hospital admissions per 100,000", "unit": "per 100,000", "kind": "rate",
     "sources": "UKHSA (England), CDC NHSN (US)"},
    {"id": "covid_wastewater", "disease": "covid", "label": "COVID in wastewater (copies per person per day)", "unit": "copies per person per day",
     "kind": "rate", "sources": "PHF Science (New Zealand)", "main": True},
    {"id": "covid_cases_weekly_per_million", "disease": "covid", "label": "COVID: cases reported per million", "unit": "per million", "kind": "rate",
     "sources": "Our World in Data"},
    {"id": "covid_deaths_weekly_per_million", "disease": "covid", "label": "COVID: deaths per million", "unit": "per million", "kind": "rate",
     "sources": "Our World in Data"},
    {"id": "covid_pct_positive", "disease": "covid", "label": "COVID: share of tests positive (England)", "unit": "%", "kind": "pct",
     "sources": "UKHSA"},
    {"id": "covid_admissions_per_100k", "disease": "covid", "label": "COVID: hospital admissions per 100,000 (US)", "unit": "per 100,000", "kind": "rate",
     "sources": "CDC NHSN"},
    {"id": "measles_cases_weekly", "disease": "measles", "label": "Measles: cases by week", "unit": "cases", "kind": "count",
     "sources": "UKHSA (England), CDC NNDSS (US)", "main": True},
    {"id": "pertussis_cases_weekly", "disease": "pertussis", "label": "Whooping cough: cases by week (US)", "unit": "cases", "kind": "count",
     "sources": "CDC NNDSS", "main": True},
    {"id": "dengue_cases_weekly", "disease": "dengue", "label": "Dengue: cases by week", "unit": "cases", "kind": "count",
     "sources": "OpenDengue", "main": True},
    {"id": "norovirus_cases_weekly", "disease": "norovirus", "label": "Norovirus: lab reports by week (England)", "unit": "cases", "kind": "count",
     "sources": "UKHSA", "main": True},
    {"id": "mpox_cases_weekly", "disease": "mpox", "label": "Mpox: cases by week (US)", "unit": "cases", "kind": "count",
     "sources": "CDC NNDSS", "main": True},
    {"id": "deaths_weekly", "disease": "deaths", "label": "Deaths from all causes by week", "unit": "deaths", "kind": "count",
     "sources": "Human Mortality Database (saved by hand)", "main": True},
]
MEASURE = {m["id"]: m for m in MEASURES}

# Yearly counts for the long view; per_million: shown per million people (cases / population).
YEARLY: list[dict] = [
    {"id": "measles_cases", "disease": "measles", "label": "Measles cases", "per_million": True, "sources": "WHO"},
    {"id": "pertussis_cases", "disease": "pertussis", "label": "Whooping cough cases", "per_million": True, "sources": "WHO"},
    {"id": "mumps_cases", "disease": "mumps", "label": "Mumps cases", "per_million": True, "sources": "WHO"},
    {"id": "rubella_cases", "disease": "rubella", "label": "Rubella cases", "per_million": True, "sources": "WHO"},
    {"id": "diphtheria_cases", "disease": "diphtheria", "label": "Diphtheria cases", "per_million": True, "sources": "WHO"},
    {"id": "polio_cases", "disease": "polio", "label": "Polio cases", "per_million": False, "sources": "WHO"},
    {"id": "cholera_cases", "disease": "cholera", "label": "Cholera cases", "per_million": True, "sources": "WHO"},
    {"id": "dengue_cases", "disease": "dengue", "label": "Dengue cases", "per_million": True, "sources": "OpenDengue"},
    {"id": "tb_incidence", "disease": "tb", "label": "Tuberculosis, new cases per 100,000", "per_million": False, "sources": "WHO"},
    {"id": "malaria_incidence", "disease": "malaria", "label": "Malaria, cases per 1,000 people at risk", "per_million": False, "sources": "WHO"},
    {"id": "covid_cases_weekly_per_million", "disease": "covid", "label": "COVID cases per million (sum of weeks)", "per_million": False,
     "sources": "Our World in Data", "from_weekly": True},
]
YEARLY_IDS = {y["id"] for y in YEARLY}

# Pandemics and big epidemics, drawn as bands on the long view.
PANDEMICS: list[dict] = [
    {"name": "1918 flu", "start": 1918, "end": 1920},
    {"name": "Asian flu", "start": 1957, "end": 1958},
    {"name": "Hong Kong flu", "start": 1968, "end": 1969},
    {"name": "SARS", "start": 2003, "end": 2003},
    {"name": "Swine flu", "start": 2009, "end": 2010},
    {"name": "COVID-19", "start": 2020, "end": 2023},
]

# Countries the page opens on and compares by default.
KEY = ("NZL", "AUS", "GBR", "USA")


def season_of(year: int, week: int, split_week: int) -> int:
    """The season a week belongs to: the calendar year where the season peaks mid-year
    (split_week 1, southern winters), else the year the season starts in, with the season
    running from split_week to split_week - 1 of the next year (northern winters)."""
    return year if split_week <= 1 or week >= split_week else year - 1


def season_label(season: int, split_week: int) -> str:
    return str(season) if split_week <= 1 else f"{season}/{str(season + 1)[2:]}"
