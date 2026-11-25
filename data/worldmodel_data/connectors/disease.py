"""Flu, COVID, RSV, measles and other infections, week by week and year by year.

who_flunet
    WHO FluNet: flu and RSV tests and positives by country and week since 1997, from WHO's open
    OData API, one CSV per year (years already complete are kept). Sentinel and other labs are
    added together; the UK's four nations are added into the UK.
nz_wastewater
    PHF Science (formerly ESR): SARS-CoV-2 in New Zealand's wastewater by week, nationally and by
    region, and the sites with their latest week as a map layer, from its GitHub repository.
ukhsa
    UK Health Security Agency data dashboard API: England's weekly flu and RSV hospital admission
    rates, COVID test positivity and deaths, measles and norovirus cases.
delphi_fluview
    The US CDC's ILINet (share of doctor visits for flu-like illness), nationally since 1997 and
    by state since 2010, through Carnegie Mellon's Delphi Epidata API.
cdc_nhsn
    US CDC National Healthcare Safety Network: weekly hospital admissions with flu, COVID and RSV
    per 100,000, for the US and each state.
cdc_nndss
    US CDC National Notifiable Diseases Surveillance System weekly tables: measles, whooping cough,
    mpox, mumps and dengue cases, US totals, since 2022.
ecdc_erviss
    ECDC's European Respiratory Virus Surveillance Summary: GP consultations for flu-like and acute
    respiratory illness per 100,000, by EU country and week.
owid_covid
    Our World in Data's COVID-19 dataset: cases, deaths, excess mortality and vaccination, summed
    or averaged to weeks.
who_gho_disease
    WHO Global Health Observatory: reported cases a year of measles, whooping cough, mumps, rubella,
    diphtheria, polio and cholera since 1974, and TB and malaria incidence.
opendengue
    OpenDengue: dengue cases by country and year (and week where reported), back to 1990 in places.
hmd_stmf
    Human Mortality Database Short-Term Mortality Fluctuations: deaths from all causes by week.
    The site needs a free login, so the file (stmf.csv) is saved by hand.
who_don
    WHO Disease Outbreak News since 1996, as dated events (kind epidemic) on the countries named.

Weekly values are stored as daily rows on the Monday that starts the week (indicator frequency W).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import unicodedata
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import duckdb
from worldmodel_contract import catalogue

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import country_by_name
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, stage_events
from worldmodel_data.connectors.markets import DatedRows, parse_day
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, num

log = logging.getLogger(__name__)

SWITCH = "disease_fetch"


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def mmwr_start(year: int, week: int) -> date:
    """The Sunday an MMWR (US CDC) week starts on: week 1 holds 4 January."""
    jan4 = date(year, 1, 4)
    return jan4 - timedelta(days=(jan4.weekday() + 1) % 7) + timedelta(weeks=week - 1)


def mmwr_monday(year: int, week: int) -> date:
    """The Monday in an MMWR week, so it lines up with the ISO week of the same days."""
    return mmwr_start(year, week) + timedelta(days=1)


# Descriptions of the indicators more than one source fills (the first source's text is kept).
SHARED = {
    "flu_admissions_per_100k": "People admitted to hospital with confirmed flu in the week, per 100,000 people: England's "
                               "figures for the UK (UK Health Security Agency), the US and each state (US CDC NHSN).",
    "rsv_admissions_per_100k": "People admitted to hospital with confirmed RSV in the week, per 100,000 people: England's "
                               "figures for the UK (UK Health Security Agency), the US and each state (US CDC NHSN).",
    "measles_cases_weekly": "Measles cases by week: England by week of onset for the UK (UK Health Security Agency), US "
                            "totals notified (US CDC NNDSS, provisional).",
    "dengue_cases_weekly": "Dengue cases reported in the week, where a country reports by week (OpenDengue), and US cases "
                           "notified (US CDC NNDSS).",
}


def _weekly(id: str, name: str, description: str, unit: str, source_id: str, series: str, *, decimals: int = 1,
            bounds: tuple[float, float] = (0, 1e9)) -> dict:
    return indicator(id, name, SHARED.get(id, description), unit, "health", source_id, series, decimals=decimals,
                     default_on=False, bounds=bounds, frequency="W", aggregation={"method": "none"})


def _yearly(id: str, name: str, description: str, unit: str, source_id: str, series: str, *, decimals: int = 0,
            agg: str = "sum", bounds: tuple[float, float] = (0, 1e10)) -> dict:
    return indicator(id, name, description, unit, "health", source_id, series, decimals=decimals, default_on=False,
                     bounds=bounds, aggregation={"method": agg})


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


# ------------------------------------------------------------------------------------------ FluNet
FLUNET = "https://xmart-api-public.who.int/FLUMART/VIW_FNT"
FLUNET_FIELDS = ("COUNTRY_CODE,ISO_WEEKSTARTDATE,ORIGIN_SOURCE,SPEC_PROCESSED_NB,INF_A,INF_B,INF_ALL,INF_NEGATIVE,"
                 "AH1N12009,AH3,BVIC_NODEL,BVIC_2DEL,BVIC_3DEL,BVIC_DELUNK,BYAM,RSV,RSV_PROCESSED")
FLUNET_FIRST = 1997
UK_NATIONS = {"X09", "X10", "X11", "X12"}  # England, Wales, Northern Ireland, Scotland
MIN_TESTS = 10  # a week's share positive needs at least this many tests


def flunet_rows(text: str) -> DatedRows:
    """Weekly sums by country from FluNet CSV rows, then the shares positive."""
    sums: dict[tuple[str, date], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in csv.DictReader(io.StringIO(text)):
        code = (r.get("COUNTRY_CODE") or "").strip()
        ent = "GBR" if code in UK_NATIONS else entity_for("iso3", code)
        d = parse_day(r.get("ISO_WEEKSTARTDATE"))
        if not ent or not d:
            continue
        s = sums[(ent, d)]
        a, b, all_ = num(r.get("INF_A")), num(r.get("INF_B")), num(r.get("INF_ALL"))
        pos = all_ if all_ is not None else ((a or 0) + (b or 0) if a is not None or b is not None else None)
        tests = num(r.get("SPEC_PROCESSED_NB"))
        if tests is None and pos is not None and num(r.get("INF_NEGATIVE")) is not None:
            tests = pos + num(r.get("INF_NEGATIVE"))
        if pos is not None and tests:
            s["tests"] += tests
            s["pos"] += pos
            s["a"] += a or 0
            s["b"] += b or 0
            s["h1"] += num(r.get("AH1N12009")) or 0
            s["h3"] += num(r.get("AH3")) or 0
        rsv, rsv_n = num(r.get("RSV")), num(r.get("RSV_PROCESSED"))
        if rsv is not None:
            s["rsv"] += rsv
            if rsv_n:
                s["rsv_n"] += rsv_n
                s["rsv_with_n"] += rsv
    rows = DatedRows()
    for (ent, d), s in sums.items():
        if s.get("tests"):
            rows.add("iso3", ent, "flu_tests", d, s["tests"])
            rows.add("iso3", ent, "flu_positive", d, s["pos"])
            rows.add("iso3", ent, "flu_a_positive", d, s["a"])
            rows.add("iso3", ent, "flu_b_positive", d, s["b"])
            rows.add("iso3", ent, "flu_a_h1n1_positive", d, s["h1"])
            rows.add("iso3", ent, "flu_a_h3_positive", d, s["h3"])
            if s["tests"] >= MIN_TESTS:
                rows.add("iso3", ent, "flu_pct_positive", d, min(100.0, 100 * s["pos"] / s["tests"]))
        if "rsv" in s:
            rows.add("iso3", ent, "rsv_positive", d, s["rsv"])
        if s.get("rsv_n", 0) >= MIN_TESTS:
            rows.add("iso3", ent, "rsv_pct_positive", d, min(100.0, 100 * s["rsv_with_n"] / s["rsv_n"]))
    return rows


FLUNET_INDICATORS = [
    _weekly("flu_pct_positive", "Flu: share of tests positive",
            "Share of respiratory samples tested for influenza in the week that were positive, all labs (sentinel and "
            "others) added together; weeks with fewer than 10 tests left out. The usual way to compare flu between "
            "countries, since it does not depend on how many people get tested. WHO FluNet.", "%", "who_flunet",
            "flunet:pct", bounds=(0, 100)),
    _weekly("flu_tests", "Flu: samples tested", "Respiratory samples tested for influenza in the week. WHO FluNet.",
            "samples", "who_flunet", "flunet:tests", decimals=0),
    _weekly("flu_positive", "Flu: positive samples", "Samples positive for influenza A or B in the week. WHO FluNet.",
            "samples", "who_flunet", "flunet:pos", decimals=0),
    _weekly("flu_a_positive", "Flu A: positive samples", "Samples positive for influenza A. WHO FluNet.", "samples",
            "who_flunet", "flunet:a", decimals=0),
    _weekly("flu_b_positive", "Flu B: positive samples", "Samples positive for influenza B. WHO FluNet.", "samples",
            "who_flunet", "flunet:b", decimals=0),
    _weekly("flu_a_h1n1_positive", "Flu A(H1N1)pdm09: positive samples",
            "Samples positive for the H1N1 strain that caused the 2009 pandemic. WHO FluNet.", "samples", "who_flunet",
            "flunet:h1", decimals=0),
    _weekly("flu_a_h3_positive", "Flu A(H3): positive samples", "Samples positive for influenza A(H3N2). WHO FluNet.",
            "samples", "who_flunet", "flunet:h3", decimals=0),
    _weekly("rsv_positive", "RSV: positive samples", "Samples positive for RSV in the week, where reported. WHO FluNet.",
            "samples", "who_flunet", "flunet:rsv", decimals=0),
    _weekly("rsv_pct_positive", "RSV: share of tests positive",
            "Share of samples tested for RSV that were positive, where the number tested is reported; weeks with fewer "
            "than 10 tests left out. WHO FluNet.", "%", "who_flunet", "flunet:rsv_pct", bounds=(0, 100)),
]


class WHOFluNet(Connector):
    source_id = "who_flunet"
    switch = SWITCH
    fetch_every_days = 3
    keeps_files = True
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        this = date.today().year
        last = self.last_vintage_dir(raw_dir)
        have = {p.name for p in last.iterdir()} if last else set()
        n = 0
        for y in range(FLUNET_FIRST, this + 1):
            name = f"flunet_{y}.csv"
            if name in have and y < this - 1:  # late reports reach the last year too
                continue
            if n:
                time.sleep(self.pause_seconds)
            self.get(f"{FLUNET}?$filter=ISO_YEAR%20eq%20{y}&$format=csv&$select={FLUNET_FIELDS}", raw_dir / name, cached=False)
            n += 1
        return FLUNET

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        text = ""
        for f in sorted(raw_dir.glob("*.csv")):
            t = f.read_text(encoding="utf-8-sig")
            text += t if not text else t.split("\n", 1)[1] if "\n" in t else ""
        rows = flunet_rows(text)
        if not len(rows):
            raise ConnectorError(f"who_flunet: no weeks read from {raw_dir}")
        self.listed_indicators = FLUNET_INDICATORS
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------- NZ COVID in wastewater
NZWW = "https://raw.githubusercontent.com/ESR-NZ/covid_in_wastewater/main/data/"
NZWW_FILES = ("ww_national.csv", "ww_regional.csv", "ww_site.csv", "cases_national.csv", "sites.csv")


@lru_cache(maxsize=256)
def nz_region(name: str) -> str | None:
    """A New Zealand region's entity id from its name ("Hawke's Bay", "Manawatū-Whanganui")."""
    key = _plain(name)
    for e in catalogue.entities().values():
        if e.entity_id.startswith("NZ-") and key and key in {_plain(n) for n in (e.name, e.short_name, *e.synonyms.split("|")) if n}:
            return e.entity_id
    for e in catalogue.entities().values():  # "Manawatu-Whanganui Region" and the like
        if e.entity_id.startswith("NZ-") and key and (_plain(e.short_name or e.name).startswith(key) or key.startswith(_plain(e.short_name or e.name))):
            return e.entity_id
    return None


def _csv(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))) if path.is_file() else []


def nz_wastewater(raw_dir: Path) -> tuple[DatedRows, dict | None]:
    rows = DatedRows()
    week = lambda r: monday(parse_day(r.get("week_end_date")) - timedelta(days=6)) if parse_day(r.get("week_end_date")) else None
    for r in _csv(raw_dir / "ww_national.csv"):
        if (d := week(r)):
            rows.add("iso3", "NZL", "covid_wastewater", d, num(r.get("copies_per_day_per_person") or r.get("copies_per_person_per_day")))
    for r in _csv(raw_dir / "ww_regional.csv"):
        if (d := week(r)) and (ent := nz_region(r.get("Region", ""))):
            rows.add("iso3", ent, "covid_wastewater", d, num(r.get("copies_per_day_per_person") or r.get("copies_per_person_per_day")))
    for r in _csv(raw_dir / "cases_national.csv"):
        if (d := week(r)):
            rows.add("iso3", "NZL", "covid_cases_7d", d, num(r.get("case_7d_avg")))
    # The sites, with their last few weeks, for the map.
    by_site: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in _csv(raw_dir / "ww_site.csv"):
        v = num(r.get("copies_per_day_per_person") or r.get("copies_per_person_per_day"))
        if (d := parse_day(r.get("week_end_date"))) and v is not None:
            by_site[r.get("SampleLocation", "")].append((d, v))
    feats = []
    for s in _csv(raw_dir / "sites.csv"):
        lat, lon = num(s.get("Latitude")), num(s.get("Longitude"))
        pts = sorted(by_site.get(s.get("SampleLocation", ""), []))
        if lat is None or lon is None or not pts:
            continue
        last_day, last = pts[-1]
        before = [v for d, v in pts if last_day - timedelta(days=35) <= d < last_day - timedelta(days=6)]
        prev = sum(before) / len(before) if before else None
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                      "properties": {"name": s.get("DisplayName") or s.get("SampleLocation"), "region": s.get("Region"),
                                     "population": num(s.get("Population")), "week": last_day.isoformat(), "value": round(last),
                                     "change": round(100 * (last / prev - 1)) if prev else None,
                                     "recent": last_day >= max(p[-1][0] for p in by_site.values() if p) - timedelta(days=21)}})
    layer = {"layer_id": "nz_wastewater", "name": "COVID in wastewater (New Zealand)",
             "description": "Wastewater sites tested for SARS-CoV-2, sized by people served, coloured by the latest week (PHF Science)",
             "kind": "point", "feature_count": len(feats),
             "geojson": json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))} if feats else None
    return rows, layer


class NZWastewater(Connector):
    source_id = "nz_wastewater"
    switch = SWITCH
    fetch_every_days = 3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for f in NZWW_FILES:
            self.get(NZWW + f, raw_dir / f)
        return NZWW

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, layer = nz_wastewater(raw_dir)
        if not len(rows):
            raise ConnectorError(f"nz_wastewater: no weeks read from {raw_dir}")
        self.layers = [layer] if layer else []
        self.listed_indicators = [
            _weekly("covid_wastewater", "COVID in wastewater", "SARS-CoV-2 genome copies per person per day in wastewater, the "
                    "week's average, weighted by the people each site serves. Follows infections whether or not people get "
                    "tested. PHF Science (formerly ESR), New Zealand.", "copies per person per day", self.source_id,
                    "ww:copies", decimals=0),
            _weekly("covid_cases_7d", "COVID: reported cases a day (7-day average)", "New COVID-19 cases reported to the "
                    "Ministry of Health a day, averaged over the week. Far below true infections since testing fell away. "
                    "PHF Science.", "cases a day", self.source_id, "ww:cases", decimals=0),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------------- UKHSA
UKHSA_API = "https://api.ukhsa-dashboard.data.gov.uk/themes/infectious_disease/sub_themes/"
# (sub-theme, topic, metric, indicator, daily: averaged to weeks)
UKHSA_METRICS = (
    ("respiratory", "Influenza", "influenza_healthcare_hospitalAdmissionRateByWeek", "flu_admissions_per_100k", False),
    ("respiratory", "RSV", "RSV_healthcare_admissionRateByWeek", "rsv_admissions_per_100k", False),
    ("respiratory", "COVID-19", "COVID-19_testing_positivity7DayRolling", "covid_pct_positive", True),
    ("respiratory", "COVID-19", "COVID-19_deaths_ONSRegByWeek", "covid_deaths_weekly", False),
    ("vaccine_preventable", "Measles", "measles_cases_casesByOnsetWeek", "measles_cases_weekly", False),
    ("gastrointestinal", "norovirus", "norovirus_cases_count", "norovirus_cases_weekly", False),
)


def ukhsa_rows(pages: dict[str, list[dict]]) -> DatedRows:
    rows = DatedRows()
    for _sub, _topic, metric, ind, daily in UKHSA_METRICS:
        weeks: dict[date, list[float]] = defaultdict(list)
        for r in pages.get(metric, []):
            if (r.get("age") or "all") != "all" or (r.get("sex") or "all") != "all" or (r.get("stratum") or "default") != "default":
                continue
            d, v = parse_day(r.get("date")), num(r.get("metric_value"))
            if d and v is not None:
                weeks[monday(d)].append(v)
        for d, vs in weeks.items():
            rows.add("iso3", "GBR", ind, d, sum(vs) / len(vs) if daily or ind.endswith("per_100k") else sum(vs))
    return rows


class UKHSA(Connector):
    source_id = "ukhsa"
    switch = SWITCH
    fetch_every_days = 3
    pause_seconds = 0.5

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for sub, topic, metric, _ind, _d in UKHSA_METRICS:
            url = (f"{UKHSA_API}{sub}/topics/{topic}/geography_types/Nation/geographies/England/metrics/{metric}"
                   "?page_size=365&format=json")
            out: list[dict] = []
            for _ in range(40):
                p = raw_dir / f"_{metric}.json"
                self.get(url, p, cached=False)
                d = json.loads(p.read_text(encoding="utf-8"))
                p.unlink()
                out += d.get("results") or []
                url = d.get("next")
                if not url:
                    break
                time.sleep(self.pause_seconds)
            (raw_dir / f"{metric}.json").write_text(json.dumps(out), encoding="utf-8")
        return UKHSA_API

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pages = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in raw_dir.glob("*.json")}
        rows = ukhsa_rows(pages)
        if not len(rows):
            raise ConnectorError(f"ukhsa: no weeks read from {raw_dir}")
        eng = " England's figures, standing for the UK. UK Health Security Agency."
        self.listed_indicators = [
            _weekly("flu_admissions_per_100k", "Flu: hospital admissions per 100,000",
                    "People admitted to hospital with confirmed flu in the week, per 100,000 people." + eng, "per 100,000",
                    self.source_id, "ukhsa:flu_adm", decimals=2),
            _weekly("rsv_admissions_per_100k", "RSV: hospital admissions per 100,000",
                    "People admitted to hospital with confirmed RSV in the week, per 100,000 people." + eng, "per 100,000",
                    self.source_id, "ukhsa:rsv_adm", decimals=2),
            _weekly("covid_pct_positive", "COVID: share of tests positive", "Share of COVID-19 PCR tests positive, the week's "
                    "average of the 7-day rolling figure." + eng, "%", self.source_id, "ukhsa:covid_pos", bounds=(0, 100)),
            _weekly("covid_deaths_weekly", "COVID: deaths registered in the week", "Deaths with COVID-19 on the death "
                    "certificate, registered in the week (ONS)." + eng, "deaths", self.source_id, "ukhsa:covid_deaths", decimals=0),
            _weekly("measles_cases_weekly", "Measles: cases by week", "Confirmed measles cases by week of onset.", "cases",
                    self.source_id, "ukhsa:measles", decimals=0),
            _weekly("norovirus_cases_weekly", "Norovirus: lab reports by week", "Laboratory reports of norovirus." + eng,
                    "cases", self.source_id, "ukhsa:noro", decimals=0),
        ]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- US ILINet (Delphi)
DELPHI = "https://api.delphi.cmu.edu/epidata/fluview/"
US_STATES = ["ak", "al", "ar", "az", "ca", "co", "ct", "dc", "de", "fl", "ga", "hi", "ia", "id", "il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo", "ms", "mt", "nc", "nd", "ne", "nh", "nj", "nm", "nv", "ny", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa", "wi", "wv", "wy"]


def delphi_rows(payloads: list[dict]) -> DatedRows:
    rows = DatedRows()
    for p in payloads:
        for r in p.get("epidata") or []:
            ew = int(r.get("epiweek") or 0)
            reg = str(r.get("region") or "")
            if not ew:
                continue
            d = mmwr_monday(ew // 100, ew % 100)
            v = num(r.get("wili")) if num(r.get("wili")) is not None else num(r.get("ili"))
            if reg == "nat":
                rows.add("iso3", "USA", "ili_pct_visits", d, v)
            elif (ent := entity_for("us_state", reg.upper())):
                rows.add("iso3", ent, "ili_pct_visits", d, v)
    return rows


class DelphiFluView(Connector):
    source_id = "delphi_fluview"
    switch = SWITCH
    fetch_every_days = 3
    pause_seconds = 0.5

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        end = date.today().year * 100 + 53
        for i, reg in enumerate(["nat", *US_STATES]):
            first = 199740 if reg == "nat" else 201001
            if i:
                time.sleep(self.pause_seconds)
            self.get(f"{DELPHI}?regions={reg}&epiweeks={first}-{end}", raw_dir / f"fluview_{reg}.json", cached=False)
        return DELPHI

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = delphi_rows([json.loads(f.read_text(encoding="utf-8")) for f in sorted(raw_dir.glob("*.json"))])
        if not len(rows):
            raise ConnectorError(f"delphi_fluview: no weeks read from {raw_dir}")
        self.listed_indicators = [_weekly(
            "ili_pct_visits", "Flu-like illness: share of doctor visits", "Share of visits to the US CDC's ILINet doctors "
            "that were for flu-like illness (fever with a cough or sore throat); weighted by state population for the US "
            "as a whole. US CDC ILINet, through Carnegie Mellon's Delphi Epidata.", "%", self.source_id, "ilinet:wili",
            decimals=2, bounds=(0, 100))]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------- CDC NHSN
NHSN = "https://data.cdc.gov/resource/ua7e-t2fy.csv"
NHSN_COLS = {"totalconfflunewadmper100k": "flu_admissions_per_100k", "totalconfc19newadmper100k": "covid_admissions_per_100k",
             "totalconfrsvnewadmper100k": "rsv_admissions_per_100k"}


def nhsn_rows(text: str) -> DatedRows:
    rows = DatedRows()
    for r in csv.DictReader(io.StringIO(text)):
        end = parse_day(r.get("weekendingdate"))
        j = (r.get("jurisdiction") or "").strip().upper()
        ent = "USA" if j == "USA" else entity_for("us_state", j)
        if not end or not ent:
            continue
        for col, ind in NHSN_COLS.items():
            rows.add("iso3", ent, ind, monday(end), num(r.get(col)))
    return rows


class CDCNHSN(Connector):
    source_id = "cdc_nhsn"
    switch = SWITCH
    fetch_every_days = 3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        sel = ",".join(["weekendingdate", "jurisdiction", *NHSN_COLS])
        self.get(f"{NHSN}?$select={sel}&$limit=100000&$order=weekendingdate", raw_dir / "nhsn.csv", cached=False)
        return NHSN

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = nhsn_rows((raw_dir / "nhsn.csv").read_text(encoding="utf-8-sig"))
        if not len(rows):
            raise ConnectorError(f"cdc_nhsn: no weeks read from {raw_dir}")
        us = " US CDC National Healthcare Safety Network (NHSN), every hospital reporting since November 2024."
        self.listed_indicators = [
            _weekly("flu_admissions_per_100k", "Flu: hospital admissions per 100,000",
                    "People admitted to hospital with confirmed flu in the week, per 100,000 people." + us, "per 100,000",
                    self.source_id, "nhsn:flu", decimals=2),
            _weekly("covid_admissions_per_100k", "COVID: hospital admissions per 100,000",
                    "People admitted to hospital with confirmed COVID-19 in the week, per 100,000 people." + us, "per 100,000",
                    self.source_id, "nhsn:covid", decimals=2),
            _weekly("rsv_admissions_per_100k", "RSV: hospital admissions per 100,000",
                    "People admitted to hospital with confirmed RSV in the week, per 100,000 people." + us, "per 100,000",
                    self.source_id, "nhsn:rsv", decimals=2),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------ CDC NNDSS
NNDSS = "https://data.cdc.gov/resource/x9gk-5huc.csv"
NNDSS_LABELS = {
    "Measles, Indigenous": "measles_cases_weekly", "Measles, Imported": "measles_cases_weekly",
    "Pertussis": "pertussis_cases_weekly", "Mpox": "mpox_cases_weekly", "Mumps": "mumps_cases_weekly",
    "Dengue virus infections, Dengue": "dengue_cases_weekly",
}


def nndss_rows(text: str) -> DatedRows:
    sums: dict[tuple[str, date], float] = defaultdict(float)
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("states") or "").strip().lower() not in ("total", "us residents", "u.s. residents"):
            continue
        ind = NNDSS_LABELS.get((r.get("label") or "").strip())
        y, w = num(r.get("year")), num(r.get("week"))
        if not ind or not y or not w:
            continue
        sums[(ind, mmwr_monday(int(y), int(w)))] += num(r.get("m1")) or 0
    rows = DatedRows()
    for (ind, d), v in sums.items():
        rows.add("iso3", "USA", ind, d, v)
    return rows


class CDCNNDSS(Connector):
    source_id = "cdc_nndss"
    switch = SWITCH
    fetch_every_days = 3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        labels = ",".join("'" + lab.replace("'", "''") + "'" for lab in NNDSS_LABELS)
        self.get(f"{NNDSS}?$select=states,year,week,label,m1&$where=states='Total' AND label in({labels})&$limit=100000",
                 raw_dir / "nndss.csv", cached=False)
        return NNDSS

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = nndss_rows((raw_dir / "nndss.csv").read_text(encoding="utf-8-sig"))
        if not len(rows):
            raise ConnectorError(f"cdc_nndss: no weeks read from {raw_dir}")
        us = " US totals, provisional, by MMWR week. US CDC National Notifiable Diseases Surveillance System."
        self.listed_indicators = [
            _weekly("measles_cases_weekly", "Measles: cases by week", "Measles cases notified in the week (local and "
                    "imported)." + us, "cases", self.source_id, "nndss:measles", decimals=0),
            _weekly("pertussis_cases_weekly", "Whooping cough: cases by week", "Pertussis cases notified in the week." + us,
                    "cases", self.source_id, "nndss:pertussis", decimals=0),
            _weekly("mpox_cases_weekly", "Mpox: cases by week", "Mpox cases notified in the week." + us, "cases",
                    self.source_id, "nndss:mpox", decimals=0),
            _weekly("mumps_cases_weekly", "Mumps: cases by week", "Mumps cases notified in the week." + us, "cases",
                    self.source_id, "nndss:mumps", decimals=0),
            _weekly("dengue_cases_weekly", "Dengue: cases by week", "Dengue cases notified in the week." + us, "cases",
                    self.source_id, "nndss:dengue", decimals=0),
        ]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------------- ECDC ERVISS
ERVISS = "https://raw.githubusercontent.com/EU-ECDC/Respiratory_viruses_weekly_data/main/data/ILIARIRates.csv"


def erviss_rows(text: str) -> DatedRows:
    rows = DatedRows()
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("age") or "").strip().lower() != "total":
            continue
        m = re.fullmatch(r"(\d{4})-W(\d{1,2})", (r.get("yearweek") or "").strip())
        ind = {"iliconsultationrate": "ili_rate_per_100k", "ariconsultationrate": "ari_rate_per_100k"}.get(
            (r.get("indicator") or "").strip().lower())
        ent = country_by_name(r.get("countryname"))
        if not m or not ind or not ent:
            continue
        try:
            d = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            continue
        rows.add("iso3", ent, ind, d, num(r.get("value")))
    return rows


class ECDCERVISS(Connector):
    source_id = "ecdc_erviss"
    switch = SWITCH
    fetch_every_days = 3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(ERVISS, raw_dir / "ILIARIRates.csv")
        return ERVISS

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        f = next(iter(sorted(raw_dir.glob("*.csv"))), None)
        rows = erviss_rows(f.read_text(encoding="utf-8-sig")) if f else DatedRows()
        if not len(rows):
            raise ConnectorError(f"ecdc_erviss: no weeks read from {raw_dir}")
        eu = " Primary care sentinel surveillance, all ages. ECDC ERVISS."
        self.listed_indicators = [
            _weekly("ili_rate_per_100k", "Flu-like illness: GP visits per 100,000", "Visits to family doctors for flu-like "
                    "illness in the week, per 100,000 people." + eu, "per 100,000", self.source_id, "erviss:ili"),
            _weekly("ari_rate_per_100k", "Acute respiratory illness: GP visits per 100,000", "Visits to family doctors for "
                    "any acute respiratory infection in the week, per 100,000 people." + eu, "per 100,000", self.source_id,
                    "erviss:ari"),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------ OWID COVID
OWID_COVID = "https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv"


class OWIDCovid(Connector):
    source_id = "owid_covid"
    switch = SWITCH
    fetch_every_days = 14

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(OWID_COVID, raw_dir / "compact.csv")
        return OWID_COVID

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        f = raw_dir / "compact.csv"
        if not f.is_file():
            raise ConnectorError(f"owid_covid: compact.csv missing from {raw_dir}")
        cols = {c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{f.as_posix()}', sample_size=-1)").fetchall()}

        def c(name: str) -> str:
            return f"TRY_CAST({name} AS DOUBLE)" if name in cols else "NULL"
        con.execute(f"""CREATE TABLE owid_w AS
            SELECT code, date_trunc('week', CAST(date AS DATE)) AS wk,
                   sum({c('new_cases_per_million')}) AS cases, sum({c('new_deaths_per_million')}) AS deaths,
                   avg({c('excess_mortality')}) AS excess, max({c('people_vaccinated_per_hundred')}) AS vacc,
                   count({c('new_cases_per_million')}) AS n_cases, count({c('new_deaths_per_million')}) AS n_deaths
            FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
            WHERE code IS NOT NULL AND length(code) = 3 GROUP BY 1, 2""")
        rows = DatedRows()
        for code, wk, cases, deaths, excess, vacc, n_c, n_d in con.execute("SELECT * FROM owid_w").fetchall():
            ent = entity_for("iso3", code)
            if not ent:
                continue
            d = wk if isinstance(wk, date) else parse_day(wk)
            if n_c:
                rows.add("iso3", ent, "covid_cases_weekly_per_million", d, cases)
            if n_d:
                rows.add("iso3", ent, "covid_deaths_weekly_per_million", d, deaths)
            rows.add("iso3", ent, "excess_deaths_pct", d, excess)
            rows.add("iso3", ent, "covid_vaccinated_pct", d, vacc)
        if not len(rows):
            raise ConnectorError(f"owid_covid: no weeks read from {raw_dir}")
        o = " Our World in Data COVID-19 dataset (from WHO, national figures and the Human Mortality Database)."
        self.listed_indicators = [
            _weekly("covid_cases_weekly_per_million", "COVID: cases reported per million", "New COVID-19 cases reported in "
                    "the week, per million people. Testing differs a lot between countries and fell away from 2022." + o,
                    "per million", self.source_id, "owid:cases"),
            _weekly("covid_deaths_weekly_per_million", "COVID: deaths per million", "COVID-19 deaths reported in the week, "
                    "per million people." + o, "per million", self.source_id, "owid:deaths", decimals=2),
            _weekly("excess_deaths_pct", "Excess deaths", "Deaths from all causes against the number expected from earlier "
                    "years, as a percentage (P-score); weekly or monthly as each country reports." + o, "%", self.source_id,
                    "owid:excess", bounds=(-100, 1000)),
            _weekly("covid_vaccinated_pct", "COVID: share given at least one vaccine dose", "Share of people who have had at "
                    "least one dose of a COVID-19 vaccine." + o, "%", self.source_id, "owid:vacc", bounds=(0, 130)),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------ WHO GHO
GHO = "https://ghoapi.azureedge.net/api/"
# GHO code -> (indicator, name, unit, description, aggregation)
GHO_SERIES = {
    "WHS3_62": ("measles_cases", "Measles: reported cases", "cases", "Measles cases reported to WHO in the year.", "sum"),
    "WHS3_43": ("pertussis_cases", "Whooping cough: reported cases", "cases", "Pertussis cases reported to WHO in the year.", "sum"),
    "WHS3_53": ("mumps_cases", "Mumps: reported cases", "cases", "Mumps cases reported to WHO in the year.", "sum"),
    "WHS3_57": ("rubella_cases", "Rubella: reported cases", "cases", "Rubella cases reported to WHO in the year.", "sum"),
    "WHS3_41": ("diphtheria_cases", "Diphtheria: reported cases", "cases", "Diphtheria cases reported to WHO in the year.", "sum"),
    "WHS3_49": ("polio_cases", "Polio: reported cases", "cases", "Poliomyelitis cases reported to WHO in the year.", "sum"),
    "CHOLERA_0000000001": ("cholera_cases", "Cholera: reported cases", "cases", "Cholera cases reported to WHO in the year.", "sum"),
    "MDG_0000000020": ("tb_incidence", "Tuberculosis: new cases per 100,000", "per 100,000",
                       "WHO's estimate of new and relapsed tuberculosis cases a year per 100,000 people.", "none"),
    "MALARIA_EST_INCIDENCE": ("malaria_incidence", "Malaria: cases per 1,000 people at risk", "per 1,000 at risk",
                              "WHO's estimate of malaria cases a year per 1,000 people living where it spreads.", "none"),
    "MALARIA_EST_CASES": ("malaria_cases", "Malaria: estimated cases", "cases", "WHO's estimate of malaria cases in the year.", "sum"),
}


def gho_rows(payloads: dict[str, dict]) -> Rows:
    rows = Rows()
    for code, d in payloads.items():
        if code not in GHO_SERIES:
            continue
        ind = GHO_SERIES[code][0]
        for r in d.get("value") or []:
            if r.get("SpatialDimType") not in (None, "COUNTRY") or r.get("Dim1") not in (None, "", "SEX_BTSX", "BTSX"):
                continue
            ent = entity_for("iso3", r.get("SpatialDim"))
            y = num(r.get("TimeDim"))
            if ent and y:
                rows.add("iso3", ent, ind, int(y), num(r.get("NumericValue")))
    return rows


class WHOGHODisease(Connector):
    source_id = "who_gho_disease"
    switch = SWITCH
    fetch_every_days = 30
    pause_seconds = 0.5

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for i, code in enumerate(GHO_SERIES):
            if i:
                time.sleep(self.pause_seconds)
            self.get(f"{GHO}{code}?$filter=SpatialDimType%20eq%20'COUNTRY'", raw_dir / f"{code}.json", cached=False)
        return GHO

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = gho_rows({f.stem: json.loads(f.read_text(encoding="utf-8")) for f in raw_dir.glob("*.json")})
        if not len(rows):
            raise ConnectorError(f"who_gho_disease: no values read from {raw_dir}")
        self.listed_indicators = [_yearly(ind, name, desc + " WHO Global Health Observatory.", unit, self.source_id, code,
                                          decimals=0 if agg == "sum" else 1, agg=agg)
                                  for code, (ind, name, unit, desc, agg) in GHO_SERIES.items()]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------ OpenDengue
OPENDENGUE_PAGE = "https://opendengue.org/data.html"
OPENDENGUE_ZIP = "https://github.com/OpenDengue/master-repo/raw/main/data/releases/V1.3.1/National_extract_V1_3_1.zip"


def dengue_rows(text: str) -> tuple[Rows, DatedRows]:
    """Yearly cases (the year's own figure, else its weeks, else its months added up) and weekly cases."""
    by_year: dict[tuple[str, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    weekly = DatedRows()
    for r in csv.DictReader(io.StringIO(text)):
        ent = entity_for("iso3", (r.get("ISO_A0") or "").strip()) or country_by_name(r.get("adm_0_name"))
        v, start = num(r.get("dengue_total")), parse_day(r.get("calendar_start_date"))
        res = (r.get("T_res") or "").strip().lower()
        if not ent or v is None or not start or res not in ("year", "month", "week"):
            continue
        by_year[(ent, start.year)][res] += v
        if res == "week":
            weekly.add("iso3", ent, "dengue_cases_weekly", monday(start + timedelta(days=3)), v)
    yearly = Rows()
    for (ent, y), parts in by_year.items():
        v = parts.get("year") or parts.get("week") or parts.get("month")
        yearly.add("iso3", ent, "dengue_cases", y, v)
    return yearly, weekly


class OpenDengue(Connector):
    source_id = "opendengue"
    switch = SWITCH
    fetch_every_days = 60

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = OPENDENGUE_ZIP
        try:  # the newest release, as the data page links it
            self.get(OPENDENGUE_PAGE, raw_dir / "_page.html", cached=False)
            m = re.search(r'href="([^"]+National_extract[^"]+\.zip)"', (raw_dir / "_page.html").read_text(encoding="utf-8", errors="ignore"))
            if m:
                url = m.group(1)
        except Exception as exc:
            log.info("opendengue: could not read the data page (%s); using %s", exc, url)
        (raw_dir / "_page.html").unlink(missing_ok=True)
        self.get(url, raw_dir / "national_extract.zip")
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        text = ""
        for f in raw_dir.iterdir():
            if f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as z:
                    for n in z.namelist():
                        if n.lower().endswith(".csv"):
                            text = z.read(n).decode("utf-8-sig")
            elif f.suffix.lower() == ".csv":
                text = f.read_text(encoding="utf-8-sig")
        yearly, weekly = dengue_rows(text)
        if not len(yearly):
            raise ConnectorError(f"opendengue: no cases read from {raw_dir}")
        od = " OpenDengue (national figures from health ministries and WHO regional offices; suspected and confirmed cases)."
        self.listed_indicators = [
            _yearly("dengue_cases", "Dengue: cases", "Dengue cases reported in the year." + od, "cases", self.source_id,
                    "opendengue:year"),
            _weekly("dengue_cases_weekly", "Dengue: cases by week", "Dengue cases reported in the week, where a country "
                    "reports by week." + od, "cases", self.source_id, "opendengue:week", decimals=0),
        ]
        a = yearly.stage(con, self.source_id, vintage, "dy")
        b = weekly.stage(con, self.source_id, vintage, "dw")
        return f"{a} UNION ALL {b}"


# --------------------------------------------------------------------------------- HMD STMF (manual)
# HMD country codes -> entity; the UK comes as three parts added together when all three report.
HMD_CODES = {"DEUTNP": "DEU", "FRATNP": "FRA", "NZL_NP": "NZL", "GBRTENW": "GBR:ENW", "GBR_SCO": "GBR:SCO", "GBR_NIR": "GBR:NIR",
             "USA": "USA", "AUS": "AUS"}


def stmf_text(raw_dir: Path) -> str:
    # stmf.csv as it is, or the zip it comes in (saved without unzipping). Only CSVs in the STMF layout
    # (a CountryCode,Year,Week,Sex... header) are read, so the input-data files some zips also hold are passed over.
    texts: list[str] = []
    for f in sorted(raw_dir.iterdir()):
        if f.suffix.lower() == ".csv":
            texts.append(f.read_text(encoding="utf-8-sig", errors="replace"))
        elif f.suffix.lower() == ".zip":
            with zipfile.ZipFile(f) as z:
                texts += [z.read(n).decode("utf-8-sig", errors="replace") for n in z.namelist() if n.lower().endswith(".csv")]
    text = ""
    for t in texts:
        lines = t.splitlines()
        at = next((i for i, ln in enumerate(lines[:20]) if ln.replace('"', "").startswith("CountryCode,")), None)
        if at is None:
            continue
        text += "\n".join(lines[at if not text else at + 1:]) + "\n"
    return text


def stmf_rows(text: str) -> DatedRows:
    deaths: dict[tuple[str, date], float] = {}
    rates: dict[tuple[str, date], float] = {}
    uk: dict[date, dict[str, float]] = defaultdict(dict)
    head: list[str] | None = None
    for line in csv.reader(io.StringIO(text)):
        if not line:
            continue
        if head is None:
            if "CountryCode" in line[0] or "Country" in line[0]:
                head = [h.strip() for h in line]
            continue
        r = dict(zip(head, line))
        if (r.get("Sex") or "").strip().lower() != "b":
            continue
        code = (r.get("CountryCode") or "").strip()
        ent = HMD_CODES.get(code) or entity_for("iso3", code)
        y, w = num(r.get("Year")), num(r.get("Week"))
        if not ent or not y or not w:
            continue
        try:
            d = date.fromisocalendar(int(y), int(w), 1)
        except ValueError:
            continue
        dt, rt = num(r.get("DTotal")), num(r.get("RTotal"))
        if ent.startswith("GBR:"):
            if dt is not None:
                uk[d][ent] = dt
            continue
        if dt is not None:
            deaths[(ent, d)] = dt
        if rt is not None:
            rates[(ent, d)] = rt * 1000
    for d, parts in uk.items():
        if len(parts) == 3 and ("GBR", d) not in deaths:
            deaths[("GBR", d)] = sum(parts.values())
    rows = DatedRows()
    for (ent, d), v in deaths.items():
        rows.add("iso3", ent, "deaths_weekly", d, v)
    for (ent, d), v in rates.items():
        rows.add("iso3", ent, "death_rate_weekly", d, v)
    return rows


class HMDSTMF(Connector):
    source_id = "hmd_stmf"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("hmd_stmf: saved by hand (the Human Mortality Database needs a free login; get.bat opens the page)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        text = stmf_text(raw_dir)
        rows = stmf_rows(text)
        if not len(rows):
            raise ConnectorError(f"hmd_stmf: no weeks read from {raw_dir}; is it stmf.csv from mortality.org?")
        h = " Human Mortality Database, Short-Term Mortality Fluctuations series."
        self.listed_indicators = [
            _weekly("deaths_weekly", "Deaths from all causes by week", "Deaths from every cause in the ISO week; the UK is "
                    "England and Wales, Scotland and Northern Ireland added together." + h, "deaths", self.source_id,
                    "stmf:DTotal", decimals=0),
            _weekly("death_rate_weekly", "Death rate by week", "Deaths in the week per 1,000 people a year (the week's rate "
                    "scaled to a year)." + h, "per 1,000 a year", self.source_id, "stmf:RTotal", decimals=2),
        ]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------- WHO Disease Outbreak News
DON = "https://www.who.int/api/news/diseaseoutbreaknews"
DON_PAGE = 100


def _text(html: str | None) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    return re.sub(r"\s+", " ", t).strip()


def don_countries(place: str) -> list[str]:
    """Countries named after the dash in a DON title ("Cholera - Angola", "Mpox – Uganda and Kenya")."""
    out = []
    for part in re.split(r",| and |;|/", place):
        p = re.sub(r"\(.*?\)", "", part).strip()
        if p and (ent := country_by_name(p)):
            out.append(ent)
    whole = country_by_name(re.sub(r"\(.*?\)", "", place).strip())
    return [whole] if whole else out


def don_events(items: list[dict]) -> tuple[list[tuple], set[str]]:
    rows, unmatched = [], set()
    for it in items:
        title = (it.get("OverrideTitle") if it.get("UseOverrideTitle") else None) or it.get("Title") or ""
        m = re.split(r"\s+[–—-]\s+", title, maxsplit=1)
        disease, place = (m[0].strip(), m[1].strip()) if len(m) == 2 else (title.strip(), "")
        day = parse_day(it.get("PublicationDateAndTime") or it.get("PublicationDate"))
        if not day or not place:
            continue
        ents = don_countries(place)
        if not ents:
            unmatched.add(place)
            continue
        url = it.get("ItemDefaultUrl") or ""
        url = f"https://www.who.int/emergencies/disease-outbreak-news/item{url}" if url.startswith("/") else (
            f"https://www.who.int/emergencies/disease-outbreak-news/item/{it.get('UrlName')}" if it.get("UrlName") else None)
        detail = _text(it.get("Summary") or it.get("Overview"))[:500] or None
        sub = re.sub(r"[^a-z0-9]+", "_", disease.lower()).strip("_")[:40] or "outbreak"
        for ent in ents:
            rows.append((ent, f"don:{it.get('DonId') or it.get('UrlName') or title}:{ent}", "epidemic", sub, f"{disease} (WHO outbreak news)",
                         day, None, "day", None, None, None, None, None, place, url, detail))
    return rows, unmatched


class WHODON(Connector):
    source_id = "who_don"
    switch = SWITCH
    fetch_every_days = 3
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        sel = "Title,OverrideTitle,UseOverrideTitle,PublicationDate,PublicationDateAndTime,UrlName,ItemDefaultUrl,Summary,DonId"
        items: list[dict] = []
        for page in range(100):
            if page:
                time.sleep(self.pause_seconds)
            p = raw_dir / "_page.json"
            self.get(f"{DON}?$orderby=PublicationDate%20desc&$top={DON_PAGE}&$skip={page * DON_PAGE}&$select={sel}", p, cached=False)
            got = json.loads(p.read_text(encoding="utf-8")).get("value") or []
            p.unlink()
            items += got
            if len(got) < DON_PAGE:
                break
        (raw_dir / "don.json").write_text(json.dumps(items), encoding="utf-8")
        return DON

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        items = json.loads((raw_dir / "don.json").read_text(encoding="utf-8"))
        rows, unmatched = don_events(items)
        if not rows:
            raise ConnectorError(f"who_don: no outbreaks read from {raw_dir}")
        self.events_query = stage_events(con, self.source_id, vintage, rows, unmatched)
        return EMPTY_OBSERVATIONS
