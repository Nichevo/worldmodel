"""Laws and society: rules as country values by year, public holidays, crime and prisons.

nager_holidays
    Public holidays from Nager.Date's free API (about 120 countries), this year and next:
        https://date.nager.at/api/v3/AvailableCountries
        https://date.nager.at/api/v3/PublicHolidays/<year>/<CC>
    Each holiday is a "holiday" event (subkind national, or regional when only some
    states keep it); public_holidays counts the national ones each year. Files of
    earlier years are kept, so the years build up.

wbl
    The World Bank's Women, Business and the Law panel (190 economies, laws since 1970):
    one row per economy and report year, a column per question. A report year describes
    the laws in force on 1 October of the year before, so values are stored on that year.
    Each listed question becomes an indicator (yes = 1, no = 0, or a number of days or
    years), and a change from one year to the next becomes a "law" event.

unodc_crime
    UNODC's crime and criminal justice statistics (data_cts_*.xlsx, about 150 countries
    since 2003): offences recorded by the police, grouped into broad types (violent,
    sexual, property, fraud and corruption, drugs), victims of homicide, and people held
    in prison (all, awaiting trial, women), as counts and per 100,000 people.

rules_curated
    Hand-checked lists where no free dataset gives the year a law changed: same-sex
    marriage (the year it became legal nationwide).

world_policy
    WORLD Policy Analysis Center's datasets on Harvard Dataverse
    (https://dataverse.harvard.edu/dataverse/WORLD), fetched through the Dataverse API
    every 90 days once the guestbook in Settings is filled in: the collection's datasets
    (and those of its sub-collections), each one's data files (CSV, Excel, or tables
    Dataverse ingested, fetched in their original format), a few seconds apart. Files
    whose checksum has not changed since the last fetch are carried over, not fetched
    again. A file behind a guestbook is asked for again with the guestbook answers
    (POST, Dataverse 6), which gives the file or a signed address to fetch it from.

gunpolicy, world_prison_brief
    Files you download yourself (GunPolicy.org and World Prison Brief have no download).

All three read any table with a country column, a year column and value columns; each
value column becomes an indicator.
"""

from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import stage_events
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows

log = logging.getLogger(__name__)

YES_NO = "yes/no"  # the unit of a rule stored as yes = 1, no = 0; the app shows Yes and No


def _entity(code: str | None = None, name: str | None = None, on: date | None = None) -> str | None:
    c = str(code or "").strip().upper()
    if len(c) == 3:
        e = entity_for("iso3", c)
        if e:
            return e
    if len(c) == 2:
        e = entity_for("iso2", c)
        if e:
            return e
    return catalogue.country_by_name(str(name or "").strip(), on) if name else None


def _table(path: Path) -> list[list]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return xlsx_rows(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t") if text.strip() else csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _header(table: list[list], *needed: str, scan: int = 30) -> int | None:
    """The row (within the first `scan`) whose cells include every needed word (compared loosely)."""
    want = [key(n) for n in needed]
    for i, r in enumerate(table[:scan]):
        keys = [key(c) for c in r]
        if all(any(w == k or w in k for k in keys) for w in want):
            return i
    return None


def _col(header: list, *names: str, exact: bool = False) -> int | None:
    keys = [key(h) for h in header]
    for n in names:
        k = key(n)
        for i, h in enumerate(keys):
            if h == k or (not exact and k in h):
                return i
    return None


# ---------------------------------------------------------------- public holidays
NAGER = "https://date.nager.at/api/v3"


class NagerHolidays(Connector):
    source_id = "nager_holidays"
    switch = "holidays_fetch"
    keeps_files = True
    fetch_every_days = 90
    pause_seconds = 0.4

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        r = self.client.get(f"{NAGER}/AvailableCountries")
        if r.status_code != 200:
            raise ConnectorError(f"nager_holidays: the country list answered HTTP {r.status_code}")
        codes = [c.get("countryCode") for c in r.json() if c.get("countryCode")]
        this = date.today().year
        got = 0
        for i, cc in enumerate(codes):
            for y in (this, this + 1):
                if got:
                    time.sleep(self.pause_seconds)
                try:
                    self.get(f"{NAGER}/PublicHolidays/{y}/{cc}", raw_dir / f"holidays_{y}_{cc}.json")
                    got += 1
                except ConnectorError as exc:
                    log.info("nager_holidays: %s %s skipped (%s)", cc, y, exc)
        if not got:
            raise ConnectorError("nager_holidays: no country's holidays could be read")
        return f"{NAGER} ({len(codes)} countries)"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        events, counts = [], defaultdict(set)
        for p in sorted(raw_dir.glob("*.json")):
            try:
                found = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("nager_holidays: %s is not JSON; skipped", p.name)
                continue
            events += holiday_events(found if isinstance(found, list) else [], counts)
        if not events:
            raise ConnectorError(f"nager_holidays: no holidays read from {raw_dir}")
        uniq = {e[1]: e for e in events}
        self.events_query = stage_events(con, self.source_id, vintage, list(uniq.values()), set())
        rows = Rows()
        for (ent, y), days in counts.items():
            rows.add("iso3", ent, "public_holidays", y, len(days))
        self.listed_indicators = [indicator(
            "public_holidays", "Public holidays (national)", "Public holidays kept across the whole country that year "
            "(days on which a holiday falls; a holiday moved to a Monday counts once).", "days", "society",
            self.source_id, "count", decimals=0, bounds=(0, 60), notes="Nager.Date; holidays kept only in some states are left out of the count.")]
        return rows.stage(con, self.source_id, vintage)


def holiday_events(found: list[dict], counts: dict) -> list[tuple]:
    out = []
    n = defaultdict(int)
    for h in found:
        try:
            d = date.fromisoformat(str(h.get("date", ""))[:10])
        except ValueError:
            continue
        ent = _entity(h.get("countryCode"))
        if not ent:
            continue
        national = h.get("global", True) is not False
        types = [t for t in (h.get("types") or []) if t]
        if national and (not types or "Public" in types):
            counts[(ent, d.year)].add(d)
        n[(ent, d)] += 1
        name = h.get("name") or h.get("localName") or "Holiday"
        local = h.get("localName")
        place = ", ".join(c.split("-", 1)[-1] for c in (h.get("counties") or [])[:20]) or None
        detail = "; ".join(filter(None, [f"Local name: {local}" if local and local != name else "",
                                         f"Kind: {', '.join(types)}" if types and types != ["Public"] else "",
                                         f"Since {h['launchYear']}" if h.get("launchYear") else ""])) or None
        out.append((ent, f"hol:{ent}:{d.isoformat()}:{n[(ent, d)]}", "holiday", "national" if national else "regional",
                    name, d, None, "day", None, None, None, None, None, place, None, detail))
    return out


# ---------------------------------------------------------------- Women, Business and the Law
WBL_PAGE = "https://wbl.worldbank.org/en/wbl-data"
WBL_FILES = (
    "https://wbl.worldbank.org/content/dam/sites/wbl/documents/2024/WBL-1971-2024-Dataset.xlsx",
    "https://wbl.worldbank.org/content/dam/sites/wbl/documents/2024/WBL2024-1-0-Historical-Panel-Data.xlsx",
)
# (indicator id, name, words that find the column, kind, unit)
WBL_RULES = (
    ("wbl_index", "Women, Business and the Law index", ("wbl index",), "number", "index (0-100)"),
    ("law_women_job_same", "Women can get a job in the same way as men", ("can a woman get a job in the same way as a man",), "yesno", YES_NO),
    ("law_equal_pay", "Equal pay for work of equal value is law", ("equal remuneration for work of equal value",), "yesno", YES_NO),
    ("law_sexual_harassment", "Law against sexual harassment at work", ("legislation on sexual harassment in employment",), "yesno", YES_NO),
    ("law_domestic_violence", "Law against domestic violence", ("legislation specifically addressing domestic violence",), "yesno", YES_NO),
    ("law_women_night_work", "Women can work at night like men", ("can a woman work at night in the same way as a man",), "yesno", YES_NO),
    ("law_pregnant_dismissal_banned", "Dismissing pregnant workers is banned", ("dismissal of pregnant workers prohibited",), "yesno", YES_NO),
    ("law_women_head_household", "Women can be head of household like men", ("can a woman be head of household in the same way as a man",), "yesno", YES_NO),
    ("law_divorce_equal", "Women can get a divorce like men", ("can a woman obtain a judgment of divorce in the same way as a man",), "yesno", YES_NO),
    ("law_equal_property", "Equal property rights for men and women", ("equal ownership rights to immovable property",), "yesno", YES_NO),
    ("law_equal_inheritance", "Sons and daughters inherit equally", ("sons and daughters have equal rights to inherit",), "yesno", YES_NO),
    ("leave_maternity_days", "Paid maternity leave", ("length of paid maternity leave",), "number", "days"),
    ("leave_paternity_days", "Paid paternity leave", ("length of paid paternity leave",), "number", "days"),
    ("leave_parental_days", "Paid parental leave (shared)", ("length of paid parental leave", "shared days"), "number", "days"),
    ("retirement_age_men", "Retirement age with full pension: men", ("age at which men can retire with full pension",), "number", "years"),
    ("retirement_age_women", "Retirement age with full pension: women", ("age at which women can retire with full pension",), "number", "years"),
)
WBL_NOTE = ("World Bank, Women, Business and the Law; the laws in force on 1 October of the year (the report of the next year).")


class WBL(Connector):
    source_id = "wbl"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"(19|20)\d\d-((19|20)\d\d)", f.name)
            if m:
                return m.group(2)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        links = list(WBL_FILES)
        try:
            r = self.client.get(WBL_PAGE)
            if r.status_code == 200:
                found = [l for l in re.findall(r'href="([^"]+\.xlsx)"', r.text, re.I) if re.search(r"panel|dataset|1971", l, re.I)]
                links = [l if l.startswith("http") else "https://wbl.worldbank.org" + l for l in found] + links
        except Exception as exc:  # noqa: BLE001 - the known addresses next
            log.info("wbl: data page not read (%s)", exc)
        for url in dict.fromkeys(links):
            try:
                self.get(url, raw_dir / url.rsplit("/", 1)[-1])
                return url
            except ConnectorError as exc:
                log.info("wbl: %s skipped (%s)", url, exc)
        raise ConnectorError("wbl: the Women, Business and the Law panel could not be downloaded")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv"))
        if not files:
            raise ConnectorError(f"wbl: no .xlsx or .csv file in {raw_dir}")
        values: dict[tuple[str, str], dict[int, float]] = {}
        for f in files:
            if f.suffix.lower() == ".xlsx":
                from openpyxl import load_workbook
                with open(f, "rb") as fh:
                    names = load_workbook(fh, read_only=True).sheetnames
                tables = [xlsx_rows(f, n) for n in names]
            else:
                tables = [_table(f)]
            for t in tables:
                values.update(wbl_values(t))
        if not values:
            raise ConnectorError("wbl: no answers read; the file's columns may have changed")
        rows, events = Rows(), []
        meta = {r[0]: r for r in WBL_RULES}
        for (ent, rule), by_year in values.items():
            for y, v in by_year.items():
                rows.add("iso3", ent, rule, y, v)
            events += change_events(ent, rule, meta[rule][1], meta[rule][4], by_year, self.source_id, "https://wbl.worldbank.org/")
        self.events_query = stage_events(con, self.source_id, vintage, events, set())
        self.listed_indicators = [indicator(i, n, f"{n} ({'yes or no' if u == YES_NO else u}).", u, "laws", self.source_id, i,
                                            decimals=0, bounds=(0, 1) if u == YES_NO else (0, 2000), notes=WBL_NOTE)
                                  for i, n, _, _, u in WBL_RULES if any(r == i for _, r in values)]
        return rows.stage(con, self.source_id, vintage)


def _answer(v, kind: str) -> float | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if kind == "yesno":
        return 1.0 if s in ("yes", "1", "1.0", "y", "true") else 0.0 if s in ("no", "0", "0.0", "n", "false") else None
    return num(v)


def wbl_values(table: list[list]) -> dict[tuple[str, str], dict[int, float]]:
    h = _header(table, "economy", "year")
    if h is None:
        return {}
    head = table[h]
    c_iso = _col(head, "iso code", "economy code", "iso3", "code")
    c_name = _col(head, "economy", exact=True)
    c_year = _col(head, "wbl report year", "report year", "year")
    if c_year is None or (c_iso is None and c_name is None):
        return {}
    cols = []
    for rid, _, words, kind, _ in WBL_RULES:
        i = next((j for w in words for j, c in enumerate(head) if key(w) in key(c)), None)
        if i is not None:
            cols.append((rid, i, kind))
    out: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for r in table[h + 1:]:
        y = num(r[c_year]) if c_year < len(r) else None
        if not y:
            continue
        year = int(y) - 1  # report year 2024: the laws on 1 October 2023
        ent = _entity(r[c_iso] if c_iso is not None and c_iso < len(r) else None,
                      r[c_name] if c_name is not None and c_name < len(r) else None, date(year, 10, 1))
        if not ent:
            continue
        for rid, i, kind in cols:
            v = _answer(r[i] if i < len(r) else None, kind)
            if v is not None:
                out[(ent, rid)][year] = v
    return dict(out)


def change_events(ent: str, rule: str, name: str, unit: str, by_year: dict[int, float], source: str, url: str | None) -> list[tuple]:
    """A "law" event for each year a rule's value differs from the year before."""
    out, prev = [], None
    for y in sorted(by_year):
        v = by_year[y]
        if prev is not None and v != prev:
            if unit == YES_NO:
                title = f"{name}: {'now law' if v else 'no longer law'}"
            else:
                title = f"{name}: {prev:g} to {v:g} {unit}"
            out.append((ent, f"law:{source}:{rule}:{ent}:{y}", "law", rule, title, date(y, 1, 1), None, "year", None, None,
                        None, None, None, None, url, None))
        prev = v
    return out


# ---------------------------------------------------------------- UNODC crime and prisons
UNODC = "https://dataunodc.un.org/sites/dataunodc.un.org/files/"
UNODC_FILES = ("data_cts_intentional_homicide.xlsx", "data_cts_violent_and_sexual_crime.xlsx",
               "data_cts_corruption_and_economic_crime.xlsx", "data_cts_access_and_functioning_of_justice.xlsx",
               "data_cts_prisons_and_prisoners.xlsx")
# Offence categories (top level only, so sub-types are not counted twice) -> broad type.
CRIME_TYPES = (
    ("sexual", ("sexual violence", "sexual exploitation")),
    ("violent", ("serious assault", "kidnapping", "robbery", "acts intended to induce fear")),
    ("property", ("burglary", "theft")),
    ("fraud", ("fraud", "corruption", "bribery", "money laundering", "embezzlement")),
    ("drugs", ("drug",)),
)
CRIME_NAMES = {"violent": "violent crime (assault, kidnapping, robbery)", "sexual": "sexual violence",
               "property": "property crime (burglary, theft)", "fraud": "fraud and corruption", "drugs": "drug offences"}


class UNODCCrime(Connector):
    source_id = "unodc_crime"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for name in UNODC_FILES:
            try:
                self.get(UNODC + name, raw_dir / name)
                got.append(name)
            except ConnectorError as exc:
                log.info("unodc_crime: %s skipped (%s)", name, exc)
        if not got:
            raise ConnectorError("unodc_crime: none of the UNODC files could be downloaded")
        return f"{UNODC} ({', '.join(got)})"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv"))
        rows = Rows()
        for f in files:
            unodc_rows(_table(f), rows)
        if not rows:
            raise ConnectorError(f"unodc_crime: nothing read from {raw_dir}; the files' columns may have changed")
        rows.finish_periods()
        self.listed_indicators = UNODC_INDICATORS
        return rows.stage(con, self.source_id, vintage)


def _unodc_target(ind: str, dim: str, cat: str, sex: str, age: str) -> str | None:
    i, d, c = ind.lower(), dim.lower(), cat.lower()
    total = lambda s: s.lower() in ("total", "", "all")  # noqa: E731
    if "homicide" in i and total(d) and total(c) and total(sex) and total(age):
        return "homicide"
    if "persons held" in i or "prison" in i:
        if not total(age):
            return "prisoners_young" if "juvenile" in age.lower() or "minor" in age.lower() else None
        if sex.lower() == "female" and total(c):
            return "prisoners_women"
        if not total(sex):
            return None
        if total(c) and (total(d) or "sentenc" not in d):
            return "prisoners"
        if "unsentenced" in c or "unsentenced" in d:
            return "prisoners_unsentenced"
        return None
    if i.startswith("offences") or i.startswith("crimes") or "offences" in i:
        if ":" in c or not total(sex) or not total(age):
            return None
        for broad, words in CRIME_TYPES:
            if any(w in c for w in words):
                return f"crime_{broad}"
    return None


def unodc_rows(table: list[list], rows: Rows) -> None:
    h = _header(table, "iso3", "indicator", "value")
    if h is None:
        return
    head = table[h]
    c = {n: _col(head, *names) for n, names in {
        "iso": ("iso3_code", "iso3"), "country": ("country",), "indicator": ("indicator",), "dimension": ("dimension",),
        "category": ("category",), "sex": ("sex",), "age": ("age",), "year": ("year",), "unit": ("unit of measurement", "unit"),
        "value": ("value",)}.items()}
    if c["value"] is None or c["year"] is None or c["indicator"] is None:
        return
    get = lambda r, n: (str(r[c[n]]).strip() if c[n] is not None and c[n] < len(r) and r[c[n]] is not None else "")  # noqa: E731
    sums: dict[tuple, float] = defaultdict(float)
    for r in table[h + 1:]:
        target = _unodc_target(get(r, "indicator"), get(r, "dimension"), get(r, "category"), get(r, "sex"), get(r, "age"))
        if not target:
            continue
        unit = get(r, "unit").lower()
        per = "rate" in unit or "100" in unit
        if not per and "count" not in unit:
            continue
        y, v = num(get(r, "year")), num(get(r, "value"))
        if y is None or v is None:
            continue
        ent = _entity(get(r, "iso"), get(r, "country"), date(int(y), 7, 1))
        if not ent:
            continue
        sums[(ent, f"{target}{'_rate' if per else ''}", int(y))] += v
    for (ent, ind, y), v in sums.items():
        rows.add("iso3", ent, ind, y, round(v, 3))


UNODC_NOTE = "UNODC crime and criminal justice statistics, as reported by each country; definitions differ between countries."
UNODC_INDICATORS = [indicator(f"{base}{'_rate' if rate else ''}", f"{name}{' per 100,000 people' if rate else ''}",
                              f"{about} {'Per 100,000 people.' if rate else 'Number.'}", "per 100,000 people" if rate else "count",
                              "crime", "unodc_crime", f"{base}{'_rate' if rate else ''}", decimals=1 if rate else 0,
                              bounds=(0, 1e8), notes=UNODC_NOTE, aggregation=None if rate else {"method": "sum"})
                    for base, name, about in (
                        [("homicide", "Victims of homicide", "Victims of intentional homicide that year.")]
                        + [(f"crime_{k}", f"Recorded {v}", f"Offences of {v} recorded by the police that year, adding up the "
                            "top-level offence types UNODC lists.") for k, v in CRIME_NAMES.items()]
                        + [("prisoners", "People in prison", "People held in prisons and other places of detention on a given day."),
                           ("prisoners_unsentenced", "People in prison awaiting trial or sentence", "People held who have not been sentenced."),
                           ("prisoners_women", "Women in prison", "Women held in prisons."),
                           ("prisoners_young", "Young people in prison", "Juveniles held in prisons.")])
                    for rate in (False, True)]


# ---------------------------------------------------------------- hand-checked rules
# Same-sex marriage legal nationwide (year it took effect). Countries not listed: not legal.
SAME_SEX_MARRIAGE = {
    "NLD": 2001, "BEL": 2003, "ESP": 2005, "CAN": 2005, "ZAF": 2006, "NOR": 2009, "SWE": 2009, "PRT": 2010, "ISL": 2010,
    "ARG": 2010, "DNK": 2012, "BRA": 2013, "FRA": 2013, "URY": 2013, "NZL": 2013, "GBR": 2014, "LUX": 2015, "USA": 2015,
    "IRL": 2015, "COL": 2016, "FIN": 2017, "MLT": 2017, "DEU": 2017, "AUS": 2017, "AUT": 2019, "TWN": 2019, "ECU": 2019,
    "CRI": 2020, "CHL": 2022, "CHE": 2022, "SVN": 2022, "CUB": 2022, "MEX": 2022, "AND": 2023, "EST": 2024, "GRC": 2024,
    "THA": 2025, "LIE": 2025,
}
CURATED_UNTIL = 2025


class RulesCurated(Connector):
    source_id = "rules_curated"
    frozen = True

    def default_release(self, fetched_at: datetime) -> str:
        return f"{CURATED_UNTIL}"

    def release_from_files(self, files: list[Path]) -> str | None:
        return f"{CURATED_UNTIL}"

    def download(self, raw_dir: Path, release: str) -> str:
        (raw_dir / "same_sex_marriage.json").write_text(json.dumps(SAME_SEX_MARRIAGE, indent=1), encoding="utf-8")
        return "hand-checked lists in worldmodel_data.connectors.laws"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        f = raw_dir / "same_sex_marriage.json"
        legal = json.loads(f.read_text(encoding="utf-8")) if f.exists() else SAME_SEX_MARRIAGE
        rows, events = Rows(), []
        countries = [e.entity_id for e in catalogue.entities().values() if e.type == "country"]
        for ent in countries:
            since = legal.get(ent)
            by_year = {y: 1.0 if since and y >= since else 0.0 for y in range(2000, CURATED_UNTIL + 1)}
            for y, v in by_year.items():
                rows.add("iso3", ent, "law_same_sex_marriage", y, v)
            events += change_events(ent, "law_same_sex_marriage", "Same-sex marriage", YES_NO, by_year, self.source_id, None)
        self.events_query = stage_events(con, self.source_id, vintage, events, set())
        self.listed_indicators = [indicator(
            "law_same_sex_marriage", "Same-sex marriage is legal", "Whether same-sex couples can marry nationwide (yes or no).",
            YES_NO, "laws", self.source_id, "same_sex_marriage", decimals=0, bounds=(0, 1),
            notes=f"Hand-checked list to {CURATED_UNTIL}; the year the law took effect nationwide.")]
        return rows.stage(con, self.source_id, vintage)


# ---------------------------------------------------------------- tables you download yourself
class _RuleTable(Connector):
    """Any table with a country column, a year column and value columns; each value column
    becomes an indicator <prefix>_<column>. Text answers Yes/No become 1/0."""
    manual = True
    prefix = ""
    domain = "laws"
    label = ""

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError(f"{self.source_id}: this source has no download; save its table in manual\\{self.source_id} "
                             f"and run .\\load.bat {self.source_id}")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv", ".tab", ".tsv"))
        if not files:
            raise ConnectorError(f"{self.source_id}: no .xlsx or .csv file in {raw_dir}")
        rows, names = Rows(), {}
        for f in files:
            rule_table(_table(f), self.prefix, rows, names, datetime.now().year)
        if not rows:
            raise ConnectorError(f"{self.source_id}: no country and year columns with values found in {', '.join(f.name for f in files)}")
        self.listed_indicators = [indicator(i, f"{n} ({self.label})", f"{n}, from {self.label}.", u, self.domain, self.source_id, i,
                                            decimals=0 if u == YES_NO else 1) for i, (n, u) in names.items()]
        return rows.stage(con, self.source_id, vintage)


def rule_table(table: list[list], prefix: str, rows: Rows, names: dict, this_year: int) -> None:
    h = next((i for i, r in enumerate(table[:30]) if _col(r, "country", "economy", "iso3", "iso code", "nation") is not None), None)
    if h is None:
        return
    head = [str(c or "").strip() for c in table[h]]
    c_iso = _col(head, "iso3", "iso code", "iso", "code")
    c_name = _col(head, "country", "economy", "nation")
    c_year = _col(head, "year")
    skip = {c_iso, c_name, c_year}
    value_cols = [i for i, n in enumerate(head) if i not in skip and n and not re.search(r"region|source|note|url|comment", n, re.I)]
    for r in table[h + 1:]:
        y = num(r[c_year]) if c_year is not None and c_year < len(r) else this_year
        if not y:
            continue
        ent = _entity(r[c_iso] if c_iso is not None and c_iso < len(r) else None,
                      r[c_name] if c_name is not None and c_name < len(r) else None, date(int(y), 7, 1))
        if not ent:
            continue
        for i in value_cols:
            if i >= len(r):
                continue
            yes_no = _answer(r[i], "yesno")
            v = yes_no if yes_no is not None else num(r[i])
            if v is None:
                continue
            ind = f"{prefix}_{re.sub(r'[^a-z0-9]+', '_', head[i].lower()).strip('_')[:50]}"
            names.setdefault(ind, (head[i][:120], YES_NO if yes_no is not None else ""))
            rows.add("iso3", ent, ind, int(y), v)


DATAVERSE = "https://dataverse.harvard.edu"
WORLD_COLLECTION = "WORLD"
DATA_EXT = (".csv", ".xlsx", ".tab", ".tsv")
DATAVERSE_PAUSE = 3.0


class WorldPolicy(_RuleTable):
    source_id, prefix, label = "world_policy", "world", "WORLD Policy Analysis Center"
    manual = False  # downloaded from Harvard Dataverse once the guestbook is filled in; files saved by hand still load
    keeps_files = True  # files not fetched again (unchanged checksum) are carried into the new vintage
    fetch_every_days = 90
    needs_settings = ("world_dataverse_name", "world_dataverse_email")
    pause_seconds = DATAVERSE_PAUSE

    def _api(self, path: str, **params) -> dict:
        r = self.client.get(f"{DATAVERSE}/api/{path}", params=params or None)
        if r.status_code != 200:
            raise ConnectorError(f"world_policy: Dataverse answered HTTP {r.status_code} for /api/{path}")
        return r.json().get("data") or {}

    def datasets(self, collection: str = WORLD_COLLECTION, depth: int = 0) -> list[str]:
        """The persistent ids (doi:...) of the collection's datasets, and of its sub-collections' (two levels)."""
        out: list[str] = []
        for item in self._api(f"dataverses/{collection}/contents") or []:
            if item.get("type") == "dataset" and item.get("identifier"):
                out.append(f"{item.get('protocol', 'doi')}:{item.get('authority')}/{item['identifier']}")
            elif item.get("type") == "dataverse" and depth < 2 and item.get("id"):
                time.sleep(self.pause_seconds)
                out += self.datasets(str(item["id"]), depth + 1)
        return out

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_contract.local import load_settings

        from worldmodel_data.config import paths

        s = load_settings(paths().home)
        if not s.get("world_dataverse_fetch", True):
            raise ConnectorError("world_policy: downloading is switched off in Settings > The world beyond borders")
        who = {k: str(s.get(f"world_dataverse_{k}") or "").strip() for k in ("name", "email", "institution", "position", "purpose")}
        if not who["name"] or not who["email"]:
            raise ConnectorError("world_policy: fill in the WORLD Policy guestbook in Settings > The world beyond borders")
        wanted = [w.strip().lower() for w in str(s.get("world_dataverse_datasets") or "").split(",") if w.strip()]
        # raw/world_policy/checksums.json (beside http_cache.json) remembers each file's checksum
        # from the last fetch, so unchanged files are not fetched again: they are carried over.
        sums_path = raw_dir.parent.parent / "checksums.json"
        known = _read_json(sums_path)
        sums: dict[str, str] = {}
        got, kept, ids = [], 0, self.datasets()
        if not ids:
            raise ConnectorError("world_policy: the WORLD collection on Dataverse lists no datasets")
        listing = []
        for pid in ids:
            time.sleep(self.pause_seconds)
            ds = self._api("datasets/:persistentId/", persistentId=pid)
            ver = ds.get("latestVersion") or {}
            title = next((f.get("value") for f in ((ver.get("metadataBlocks") or {}).get("citation") or {}).get("fields", [])
                          if f.get("typeName") == "title"), "") or pid
            if wanted and not any(w in str(title).lower() or w in pid.lower() for w in wanted):
                continue
            guestbook = ds.get("guestbookId") or ver.get("guestbookId")
            for f in ver.get("files") or []:
                df = f.get("dataFile") or {}
                name = df.get("originalFileName") or df.get("filename") or ""
                if not df.get("id") or not name.lower().endswith(DATA_EXT) or f.get("restricted"):
                    continue
                dest = raw_dir / f"{df['id']}_{_safe(name)}"
                md5 = str((df.get("checksum") or {}).get("value") or df.get("md5") or "")
                listing.append({"dataset": pid, "title": title, "file": dest.name, "checksum": md5})
                if md5 and known.get(dest.name) == md5:
                    kept += 1
                    sums[dest.name] = md5
                    continue
                time.sleep(self.pause_seconds)
                self._fetch_file(df["id"], dest, guestbook, who)
                got.append(dest.name)
                if md5:
                    sums[dest.name] = md5
        if not listing:
            raise ConnectorError("world_policy: no data files (CSV, Excel or tables) in the chosen WORLD datasets")
        # Always written, so a fetch with nothing new is still a fetch; the same list gives the same vintage.
        (raw_dir / "datasets.json").write_text(json.dumps(sorted(listing, key=lambda x: x["file"]), indent=1), encoding="utf-8")
        sums_path.write_text(json.dumps(sums, indent=1), encoding="utf-8")
        log.info("world_policy: %s files fetched, %s unchanged", len(got), kept)
        return f"{DATAVERSE}/dataverse/{WORLD_COLLECTION}"

    def _fetch_file(self, file_id: int, dest: Path, guestbook, who: dict[str, str]) -> None:
        url = f"{DATAVERSE}/api/access/datafile/{file_id}"
        r = self.client.get(url, params={"format": "original"})
        if r.status_code == 200:
            dest.write_bytes(r.content)
            return
        if r.status_code not in (400, 401, 403):
            raise ConnectorError(f"world_policy: file {file_id} answered HTTP {r.status_code}")
        # Behind a guestbook: answer it (custom questions get the purpose) and fetch again.
        answers = []
        if guestbook:
            try:
                book = self._api(f"guestbooks/{guestbook}")
                answers = [{"id": q.get("id"), "value": who["purpose"] or "Research"}
                           for q in book.get("customQuestions") or [] if q.get("id")]
            except (ConnectorError, ValueError):
                answers = []
        body = {"guestbookResponse": {"name": who["name"], "email": who["email"], "institution": who["institution"],
                                      "position": who["position"], "answers": answers}}
        r = self.client.post(url, params={"format": "original"}, json=body)
        if r.status_code != 200:
            raise ConnectorError(f"world_policy: file {file_id} refused the guestbook answers (HTTP {r.status_code}); "
                                 "check the form in Settings, or save the file by hand")
        if "json" in r.headers.get("content-type", ""):
            signed = _find_url(r.json())
            if not signed:
                raise ConnectorError(f"world_policy: file {file_id}: Dataverse answered without a download address")
            r = self.client.get(signed)
            if r.status_code != 200:
                raise ConnectorError(f"world_policy: file {file_id}: the signed address answered HTTP {r.status_code}")
        dest.write_bytes(r.content)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def _find_url(obj) -> str | None:
    """The first http(s) address anywhere in a JSON answer (the signed download URL)."""
    if isinstance(obj, str):
        return obj if obj.startswith("http") else None
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            if (u := _find_url(v)):
                return u
    return None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return {}


class GunPolicy(_RuleTable):
    source_id, prefix, label = "gunpolicy", "guns", "GunPolicy.org"


# The "Highest to Lowest" list that holds every measure for every country on one page
# (https://www.prisonstudies.org/world-prison-data/highest-lowest/highest-lowest-prison-population-total);
# "data up to selected year" is the field_date_collected_value[max] filter.
WPB_PAGE = "https://www.prisonstudies.org/world-prison-data/highest-lowest/highest-lowest-prison-population-total"
WPB_MEASURES = (  # how the page labels each figure -> column name (and so indicator id)
    ("prison population total", "Prison population total"),
    ("prison population rate", "Prison population rate per 100,000"),
    ("pre-trial", "Pre-trial detainees share"),
    ("female", "Female prisoners share"),
    ("juveniles", "Juveniles share"),
    ("foreign", "Foreign prisoners share"),
    ("occupancy", "Occupancy level"),
)


def wpb_url(year: int | None = None) -> str:
    if year is None:
        return WPB_PAGE
    return f"{WPB_PAGE}?field_date_collected_value%5Bmin%5D=0000-01-01&field_date_collected_value%5Bmax%5D={year}-12-31"


def wpb_table(text: str, year: int) -> list[list]:
    """The countries on a saved or fetched Highest to Lowest page as a table: ISO, Country,
    Year, then one column per measure. Parts of countries (England and Wales, Scotland,
    Northern Ireland and the like, flagged "gb-eng") are left out, so only whole countries count."""
    head = ["ISO", "Country", "Year"] + [c for _, c in WPB_MEASURES]
    out = [head]
    for block in re.split(r'<div class="country views-row">', text)[1:]:
        flag = re.search(r'class="fi fi-([a-z-]+)"', block)
        name = re.search(r'class="country-name"><a[^>]*>(.*?)</a>', block, re.S)
        if not name:
            continue
        code = flag.group(1) if flag else ""
        if "-" in code:
            continue
        row = [code.upper(), html.unescape(re.sub(r"<[^>]+>", "", name.group(1))).strip(), year] + [None] * len(WPB_MEASURES)
        for label, value in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", block, re.S):
            label = html.unescape(re.sub(r"<[^>]+>", "", label)).strip().lower()
            text_v = re.sub(r"<div[^>]*visually-hidden[^>]*>.*?</div>", "", value, flags=re.S)
            text_v = html.unescape(re.sub(r"<[^>]+>", "", text_v)).replace("c.", "").replace(",", "").replace("%", "").strip()
            for i, (key_, _) in enumerate(WPB_MEASURES):
                if label.startswith(key_) and re.fullmatch(r"-?\d+(\.\d+)?", text_v):
                    row[3 + i] = float(text_v)
                    break
        out.append(row)
    return _wpb_whole_countries(out)


WPB_CODE_FIXES = {("VG", "(usa)"): "VI", ("KO", ""): "XK"}  # the site's flags for the US Virgin Islands and Kosovo


def _wpb_whole_countries(table: list[list]) -> list[list]:
    """Countries the site lists in parts ("United Kingdom: England and Wales", "...: Scotland",
    "Bosnia and Herzegovina: Federation") become one row: totals added up, the rate and the
    shares weighted by each part's prisoners, occupancy left out."""
    head, rows = table[0], []
    parts: dict[str, list[list]] = {}
    for r in table[1:]:
        for (code, hint), fixed in WPB_CODE_FIXES.items():
            if r[0] == code and hint in r[1].lower():
                r[0] = fixed
        if ":" in r[1]:
            parts.setdefault(r[0], []).append(r)
        else:
            rows.append(r)
    for code, ps in parts.items():
        tot = [p[3] for p in ps]
        whole = [code, ps[0][1].split(":")[0].strip(), ps[0][2]] + [None] * (len(head) - 3)
        if all(t is not None for t in tot):
            whole[3] = sum(tot)
            if all(p[4] for p in ps):
                people = sum(p[3] / p[4] * 1e5 for p in ps)
                whole[4] = round(whole[3] / people * 1e5)
            for j in range(5, len(head) - 1):  # the shares; occupancy (last) is left out
                if all(p[j] is not None for p in ps):
                    whole[j] = round(sum(p[j] * p[3] for p in ps) / whole[3], 1)
        rows.append(whole)
    return [head] + rows


def wpb_year(path: Path, text: str) -> int:
    """The year a page is "data up to": wpb_<year> in the file name, the page's own filter, or
    (a page saved by hand with no filter) the year the file was saved."""
    m = re.search(r"wpb_(\d{4})", path.name) or re.search(r'field_date_collected_value\[max\]" value="(\d{4})', text)
    return int(m.group(1)) if m else datetime.fromtimestamp(path.stat().st_mtime).year


class WorldPrisonBrief(_RuleTable):
    """World Prison Brief: tables saved by hand (a spreadsheet with Country, Year and value
    columns), or its Highest to Lowest page, saved from the browser or fetched by
    .\\scrape.bat prisons (one page a year, a few seconds apart)."""
    source_id, prefix, label, domain = "world_prison_brief", "wpb", "World Prison Brief", "crime"
    keeps_files = True  # one page per year; each adds to the ones before
    stage_version = 2  # 2: a figure repeated in a hand-saved page and a fetched one is kept once

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        # The scraper's pages (wpb_<year>.html) first: a page saved by hand for the same year
        # (dated by when it was saved) then adds nothing twice.
        files = sorted((p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv", ".htm", ".html")),
                       key=lambda p: (not re.match(r"wpb_\d{4}\.html?$", p.name), p.name))
        if not files:
            raise ConnectorError(f"{self.source_id}: no saved page, .xlsx or .csv file in {raw_dir}")
        rows, names = Rows(), {}
        for f in files:
            if f.suffix.lower() in (".htm", ".html"):
                text = f.read_text(encoding="utf-8", errors="replace")
                table = wpb_table(text, wpb_year(f, text))
            else:
                table = _table(f)
            rule_table(table, self.prefix, rows, names, datetime.now().year)
        seen, kept = set(), []
        for r in rows.rows:  # one figure per country, measure and year: the first file's
            k = (r[1], r[2], r[3], r[4])
            if k not in seen:
                seen.add(k)
                kept.append(r)
        if len(kept) < len(rows.rows):
            log.info("%s: %d figures repeated in more than one file; the first kept", self.source_id,
                     len(rows.rows) - len(kept))
        rows.rows = kept
        if not rows:
            raise ConnectorError(f"{self.source_id}: no countries with figures found in {', '.join(f.name for f in files)}")
        self.listed_indicators = []
        for i, (n, u) in names.items():
            share = n.endswith("share") or n.startswith("Occupancy")
            unit = "%" if share else "persons" if n.endswith("total") else "per 100,000" if "100,000" in n else u
            self.listed_indicators.append(indicator(
                i, f"{n.replace(' share', '')} ({self.label})", f"{n}, from {self.label}: for each year, the latest figure "
                "known up to that year.", unit, self.domain, self.source_id, i, decimals=1 if share else 0,
                default_on=i in ("wpb_prison_population_rate_per_100_000", "wpb_prison_population_total")))
        return rows.stage(con, self.source_id, vintage)
