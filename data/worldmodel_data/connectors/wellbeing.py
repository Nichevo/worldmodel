"""Life in a country: the figures the Scorecard page needs that no other source carries.

ilostat_hours
    ILOSTAT: mean weekly hours actually worked per employed person (HOW_TEMP_SEX_NB_A), from
    the ILO's bulk files (the same addresses as ilostat_earnings, tried in turn). Total, women
    and men. If ILOSTAT refuses the refresh, save the bulk file, or a table from its data
    explorer, in var\\manual\\ilostat_hours.

walkfree_gsi
    Walk Free's Global Slavery Index (2023 edition: estimates for 2021): people in modern
    slavery (forced labour and forced marriage) per 1,000 people, the number of people, and the
    vulnerability and government response scores. The data file sits behind a short form, so it
    is saved by hand in var\\manual\\walkfree_gsi. The year stored is the year the estimates are
    for: the edition's year less two (the 2023 edition estimates 2021, the 2018 edition 2016).

wid_gender
    The World Inequality Database's female labour income share: women's share of all income
    from work (wages plus 70% of self-employment income). WID's download is chosen on its site,
    so the file is saved by hand in var\\manual\\wid_gender. Either a WID download (semicolon
    separated, one column per country or one row per country and year) or any CSV or Excel
    table with a country, a year and a value column is read.

remote_lwb
    Remote's Global Life-Work Balance Index (60 biggest economies, yearly since 2023): the
    overall score and the parts it is built from (leave, sick pay, maternity leave and pay,
    minimum wage, happiness, hours, LGBTQ+ inclusivity, Global Peace Index), read from the data
    inside Remote's index page. The year stored is the edition's.

natixis_gri
    Natixis' Global Retirement Index (about 44 countries, yearly each September): the overall
    score and its four sub-indices, read from the full rankings at the back of the report PDF.
    The year stored is the report's.
"""

from __future__ import annotations

import csv
import json
import io
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import ILO_URLS, _ilo_rows, _ilo_sex, country_by_name
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)


def _country(code_or_name: str) -> str | None:
    """An entity id from an ISO alpha-3 or alpha-2 code, or a country's name."""
    s = str(code_or_name or "").strip()
    if not s:
        return None
    if re.fullmatch(r"[A-Z]{3}", s):
        return entity_for("iso3", s) or s
    if re.fullmatch(r"[A-Z]{2}", s):
        return entity_for("iso2", s)
    return country_by_name(s)


# ----------------------------------------------------------------------------------------- ILOSTAT hours
HOURS_SERIES = "HOW_TEMP_SEX_NB_A"
HOURS_IDS = {"": "weekly_hours_worked", "_women": "weekly_hours_worked_women", "_men": "weekly_hours_worked_men"}


class ILOHours(Connector):
    source_id = "ilostat_hours"
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        last = None
        for pattern in ILO_URLS:
            url = pattern.format(id=HOURS_SERIES)
            try:
                self.get(url, raw_dir / (f"{HOURS_SERIES}.rds" if url.endswith(".rds") else f"{HOURS_SERIES}.csv.gz"))
                return url
            except ConnectorError as exc:
                last = exc
        raise ConnectorError(f"ilostat_hours: {HOURS_SERIES} could not be downloaded ({last}); save it in "
                             "var\\manual\\ilostat_hours")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() not in (".csv", ".gz", ".xlsx", ".rds"):
                continue
            for r in hours_rows(f):
                sex = _ilo_sex(str(r.get("sex", "") or r.get("sex.label", "") or "SEX_T"))
                y = re.match(r"(\d{4})", str(r.get("time", "")))
                if sex is None or not y:
                    continue
                # Some tables split by a classification as well (age, status): only the totals.
                c1 = str(r.get("classif1", "") or r.get("classif1.label", "") or "")
                if c1 and not re.search(r"(_TOTAL|_TOT|total)$", c1, re.I) and not c1.lower().endswith("total"):
                    continue
                ent = _country(str(r.get("ref_area", "") or "")) or _country(str(r.get("ref_area.label", "") or ""))
                if ent:
                    rows.add("iso3", ent, HOURS_IDS[sex], int(y.group(1)), num(r.get("obs_value")))
        if not len(rows):
            raise ConnectorError(f"ilostat_hours: nothing read from {raw_dir}")
        self.listed_indicators = [
            indicator(ind, f"Weekly hours worked{who}",
                      f"Mean weekly hours actually worked per employed person{who.replace(', ', ' (') + ')' if who else ''}, "
                      "in all jobs. ILOSTAT (HOW_TEMP_SEX_NB_A), mostly from labour force surveys.",
                      "hours a week", "labour", self.source_id, f"{HOURS_SERIES}:{sex or 'total'}", decimals=1,
                      default_on=not sex, bounds=(1, 90))
            for sex, ind, who in (("", HOURS_IDS[""], ""), ("_women", HOURS_IDS["_women"], ", women"),
                                  ("_men", HOURS_IDS["_men"], ", men"))]
        return rows.stage(con, self.source_id, vintage)


def hours_rows(path: Path) -> list[dict]:
    """Rows of an ILOSTAT hours file: the bulk file, or a table from the data explorer."""
    got = _ilo_rows(path)
    if got and "obs_value" not in got[0]:  # the newer explorer's wide table: Area, Year, Total, Male, Female
        out = []
        for r in got:
            for col, sex in (("Total", "SEX_T"), ("Male", "SEX_M"), ("Female", "SEX_F")):
                if str(r.get(col, "") or "").strip():
                    out.append({"ref_area.label": r.get("Area", ""), "time": r.get("Year", ""), "sex": sex,
                                "obs_value": r[col]})
        return out
    if got and got[0].get("indicator") and not str(got[0].get("indicator")).startswith("HOW_"):
        log.warning("ilostat_hours: %s holds %s, not %s; read anyway", path.name, got[0]["indicator"], HOURS_SERIES)
    return got


# ----------------------------------------------------------------------------------------- Global Slavery Index
GSI_COLUMNS = (  # (header pattern, indicator, name, unit, decimals, description)
    (r"prevalence.*1,?000|per1000|prevalence", "modern_slavery_per_1000", "People in modern slavery per 1,000",
     "per 1,000 people", 1, "Estimated people in modern slavery (forced labour, including forced commercial sexual "
     "exploitation, and forced marriage) per 1,000 people."),
    (r"estimated number|number of people", "modern_slavery_people", "People in modern slavery", "people", 0,
     "Estimated number of people living in modern slavery."),
    (r"vulnerability", "slavery_vulnerability", "Vulnerability to modern slavery", "score (0-100)", 0,
     "Walk Free's score of how vulnerable people are to modern slavery (governance, lack of basic needs, "
     "inequality, disenfranchised groups, conflict); higher is more vulnerable."),
    (r"government response", "slavery_government_response", "Government response to modern slavery", "score (0-100)", 0,
     "Walk Free's score of how well a government is responding to modern slavery; higher is stronger."),
)


class WalkFreeGSI(Connector):
    source_id = "walkfree_gsi"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            if m := re.search(r"(20\d\d)", f.name):
                return m.group(1)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("walkfree_gsi: saved by hand (get.bat opens Walk Free's download page)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(f for f in raw_dir.iterdir() if f.suffix.lower() in (".xlsx", ".xlsm", ".csv"))
        if not files:
            raise ConnectorError(f"walkfree_gsi: no Excel or CSV file in {raw_dir}")
        f = files[-1]
        m = re.search(r"(20\d\d)", f.name)
        edition = int(m.group(1)) if m else int(str(release)[:4])
        tables = ([read_csv_table(f)] if f.suffix.lower() == ".csv"
                  else [xlsx_rows(f, n) for n in sorted(xlsx_sheet_names(f), key=lambda n: "summary" not in n.lower())])
        found: dict[str, dict[str, float]] = {}
        for table in tables:
            found = gsi_rows(table)
            if found:
                break
        if not found:
            raise ConnectorError(f"walkfree_gsi: no table with a country and a prevalence per 1,000 column in {f.name}")
        rows = Rows()
        for ent, vals in found.items():
            for ind, v in vals.items():
                rows.add("iso3", ent, ind, edition - 2, v)
        self.listed_indicators = [
            indicator(ind, name, desc + f" Walk Free, Global Slavery Index (the {edition} edition estimates {edition - 2}).",
                      unit, "society", self.source_id, f"gsi:{ind}", decimals=dec,
                      aggregation={"method": "sum"} if unit == "people" else None)
            for _, ind, name, unit, dec, desc in GSI_COLUMNS]
        return rows.stage(con, self.source_id, vintage)


def read_csv_table(path: Path) -> list[list]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    sep = ";" if text.count(";") > text.count(",") else ","
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=sep)]


def gsi_rows(table: list[list]) -> dict[str, dict[str, float]]:
    """{country: {indicator: value}} from a Global Slavery Index sheet: the header row is the
    first with a Country column and a prevalence column."""
    for hi, row in enumerate(table[:30]):
        head = [str(c or "").strip().lower() for c in row]
        if not any(h == "country" or h.startswith("country") for h in head):
            continue
        cols: dict[int, str] = {}
        for pat, ind, *_ in GSI_COLUMNS:
            i = next((i for i, h in enumerate(head) if i not in cols and re.search(pat, h)), None)
            if i is not None:
                cols[i] = ind
        if "modern_slavery_per_1000" not in cols.values():
            continue
        ci = next(i for i, h in enumerate(head) if h == "country" or h.startswith("country"))
        iso = next((i for i, h in enumerate(head) if key(h) in ("iso", "iso3", "isocode", "iso3code")), None)
        out: dict[str, dict[str, float]] = {}
        for r in table[hi + 1:]:
            if len(r) <= ci or not str(r[ci] or "").strip():
                continue
            ent = (_country(str(r[iso] or "")) if iso is not None and iso < len(r) else None) or _country(str(r[ci]))
            if not ent:
                continue
            vals = {ind: v for i, ind in cols.items() if i < len(r) and (v := num(r[i])) is not None}
            if vals:
                out[ent] = vals
        return out
    return {}


# ----------------------------------------------------------------------------------------- WID female labour share
WID_ID = "female_labour_income_share"


class WIDGender(Connector):
    source_id = "wid_gender"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("wid_gender: saved by hand (get.bat opens the World Inequality Database)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() == ".csv":
                tables = [read_csv_table(f)]
            elif f.suffix.lower() in (".xlsx", ".xlsm"):
                tables = [xlsx_rows(f, n) for n in xlsx_sheet_names(f)]
            else:
                continue
            for t in tables:
                for ent, year, v in wid_values(t):
                    rows.add("iso3", ent, WID_ID, year, v * 100 if v <= 1 else v)
        if not len(rows):
            raise ConnectorError(f"wid_gender: no country, year and value read from {raw_dir}")
        self.listed_indicators = [indicator(
            WID_ID, "Women's share of income from work",
            "Women's share of all labour income (wages plus 70% of self-employment income), %. World Inequality "
            "Database, female labour income share (50% would be equal).", "%", "inequality", self.source_id,
            "wid:female_labour_income_share", decimals=1, bounds=(0, 100))]
        return rows.stage(con, self.source_id, vintage)


def wid_values(table: list[list]) -> list[tuple[str, int, float]]:
    """(country, year, value) from a table saved from WID, in any of three shapes:
    long (a country or code column, a year column, a value column), WID's own long download
    (Country; Variable; Percentile; Year; Value), or wide (Year in the first column, one column
    per country, the country named or coded somewhere in its header cell)."""
    for hi, row in enumerate(table[:15]):
        head = [str(c or "").strip() for c in row]
        keys = [key(h) for h in head]
        if "year" not in keys:
            continue
        yi = keys.index("year")
        ci = next((i for i, k in enumerate(keys) if k in ("country", "countryname", "iso", "iso3", "iso2", "code",
                                                         "countrycode", "entity", "area")), None)
        vi = next((i for i, k in enumerate(keys) if k in ("value", "obsvalue", "share", "femalelaborincomeshare",
                                                         "femalelabourincomeshare")), None)
        if ci is not None and vi is not None:  # long
            out = []
            for r in table[hi + 1:]:
                if max(ci, yi, vi) >= len(r):
                    continue
                y, v = re.match(r"(\d{4})", str(r[yi] or "")), num(r[vi])
                ent = _country(str(r[ci] or ""))
                if ent and y and v is not None:
                    out.append((ent, int(y.group(1)), v))
            return out
        cols = {}
        for i, h in enumerate(head):  # wide: each other column's header names a country
            if i == yi or not h:
                continue
            for part in re.split(r"[\n\r|;,]+|\s{2,}", h):
                part = part.strip()
                if ent := (_country(part) if not re.fullmatch(r"[a-z]{4,}\d*[a-z]?", part) else None):
                    cols[i] = ent
                    break
        out = []
        for r in table[hi + 1:]:
            y = re.match(r"(\d{4})", str(r[yi] if yi < len(r) else ""))
            if not y:
                continue
            for i, ent in cols.items():
                if i < len(r) and (v := num(r[i])) is not None:
                    out.append((ent, int(y.group(1)), v))
        return out
    return []


# ----------------------------------------------------------------------------------------- Remote life-work balance
LWB_PAGE = "https://remote.com/resources/research/global-life-work-balance-index"
# (indicator, name, unit, decimals, bounds, default_on, description)
LWB_SERIES = (
    ("lwb_score", "Life-work balance score", "score (0-100)", 2, (0, 100), True,
     "Remote's overall life-work balance score out of 100 (higher is better), from statutory leave, sick pay, "
     "maternity leave and pay, minimum wage, health system, happiness, hours worked, LGBTQ+ inclusivity and "
     "safety, weighted by Remote. The 60 biggest economies only."),
    ("lwb_paid_leave_days", "Paid leave and public holidays", "days a year", 0, (0, 80), True,
     "Statutory paid annual leave plus paid public holidays, in days (the minimum where a range is given)."),
    ("lwb_annual_leave_days", "Statutory annual leave", "days a year", 0, (0, 60), False,
     "Statutory paid annual leave, in days, not counting public holidays (the minimum where a range is given)."),
    ("lwb_public_holidays", "Paid public holidays", "days a year", 0, (0, 40), False,
     "Paid public holidays a year, as Remote counts them."),
    ("lwb_sick_pay_pct", "Minimum statutory sick pay", "% of wage", 0, (0, 100), False,
     "The lowest statutory sick pay as a share of wages (the bottom of the band Remote gives: 80 for '80 - 100%'); "
     "blank where it is a flat amount, 'less than 60%' or none."),
    ("lwb_maternity_weeks", "Paid maternity leave", "weeks", 1, (0, 120), True,
     "Statutory paid maternity leave, in weeks."),
    ("lwb_maternity_pay_pct", "Maternity leave pay rate", "% of wage", 0, (0, 100), False,
     "Statutory maternity pay as a share of wages; blank where it is a flat amount or the minimum wage."),
    ("lwb_min_wage_usd", "Minimum wage (US$ an hour)", "US$ an hour", 2, (0, 60), False,
     "The national minimum wage in US dollars an hour, as Remote converted it; blank where there is no "
     "statutory national minimum (Remote scores those as 0)."),
    ("lwb_happiness", "Happiness (Remote's figure)", "score (0-10)", 2, (0, 10), False,
     "The happiness score Remote used (World Happiness Report life ladder, 0-10)."),
    ("lwb_hours_week", "Hours a week per worker (Remote's figure)", "hours a week", 1, (1, 90), False,
     "Average hours worked a week per employed person, as Remote used it."),
    ("lwb_lgbtq_inclusivity", "LGBTQ+ inclusivity", "score (0-100)", 0, (0, 100), False,
     "LGBTQ+ inclusivity, 0-100 (higher is more inclusive): Equaldex's legal and public opinion index, as Remote used it."),
    ("lwb_peace_index", "Global Peace Index score (Remote's figure)", "score (1-5)", 2, (1, 5), False,
     "Global Peace Index score as Remote used it: lower is safer."),
)
LWB_FIELDS = {  # Remote's own column -> how it is read
    "index_score_100": ("lwb_score",),
    "statutory_annual_leave": ("lwb_annual_leave_days", "lwb_public_holidays"),
    "minimum_statutory_sick_pay_percentage": ("lwb_sick_pay_pct",),
    "paid_maternity_leave_and_payment_rate": ("lwb_maternity_weeks", "lwb_maternity_pay_pct"),
    "minimum_wage": ("lwb_min_wage_usd",),
    "happiness_index": ("lwb_happiness",),
    "average_hours_per_week_per_employed_person": ("lwb_hours_week",),
    "lgbtq_inclusivity": ("lwb_lgbtq_inclusivity",),
    "safety_global_peace_index_ranking": ("lwb_peace_index",),
}


class RemoteLifeWork(Connector):
    """Remote's Global Life-Work Balance Index: the table on its web page (all 60 countries are
    in the page's own data, though only ten show at first). A page saved by hand (Save as,
    'Webpage, complete' or 'HTML only') in var\\manual\\remote_lwb is read the same way, as is a
    CSV with Remote's column names."""
    source_id = "remote_lwb"
    fetch_every_days = 30
    keeps_files = True  # older editions saved by hand stay

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        dest = raw_dir / "global-life-work-balance-index.html"
        self.get(LWB_PAGE, dest, headers={"Accept": "text/html"})
        if not lwb_rows(dest.read_text(encoding="utf-8", errors="replace")):
            raise ConnectorError("remote_lwb: Remote's page no longer carries the index table; save the page "
                                 "in var\\manual\\remote_lwb (or tell us its new layout)")
        return LWB_PAGE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        seen: dict[int, str] = {}
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() not in (".html", ".htm", ".csv", ".txt"):
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            got = lwb_rows(text) if f.suffix.lower() != ".csv" else lwb_csv_rows(f)
            if not got:
                log.warning("remote_lwb: no index table in %s", f.name)
                continue
            year = lwb_edition(f.name, text) or int(str(release)[:4])
            if year in seen:
                log.info("remote_lwb: %s edition already read from %s; %s skipped", year, seen[year], f.name)
                continue
            seen[year] = f.name
            for ent, vals in got.items():
                for ind, v in vals.items():
                    rows.add("iso3", ent, ind, year, v)
        if not len(rows):
            raise ConnectorError(f"remote_lwb: nothing read from {raw_dir}")
        self.listed_indicators = [
            indicator(ind, name, desc + " Remote, Global Life-Work Balance Index (the year is the edition's).",
                      unit, "labour", self.source_id, f"lwb:{ind}", decimals=dec, bounds=bounds, default_on=on)
            for ind, name, unit, dec, bounds, on, desc in LWB_SERIES]
        return rows.stage(con, self.source_id, vintage)


def lwb_edition(name: str, text: str) -> int | None:
    m = re.search(r"Life-Work Balance Index\s*(20\d\d)", text[:20000]) or re.search(r"(20\d\d)", name)
    return int(m.group(1)) if m else None


def lwb_values(raw: dict) -> dict[str, float]:
    """{indicator: value} from one row of Remote's table (its own column names)."""
    out: dict[str, float] = {}
    for col, inds in LWB_FIELDS.items():
        cell = str(raw.get(col, "") or "").strip()
        if not cell or cell in ("-", "–"):
            continue
        if col == "minimum_statutory_sick_pay_percentage":
            # "80 - 100%" -> 80; "50.00" -> 50; "Less than 60% of wages", "£99.35 per week" -> nothing
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:-\s*\d+(?:\.\d+)?)?\s*%?", cell)
            if m:
                out[inds[0]] = float(m.group(1))
            continue
        if len(inds) == 2:  # two figures in one cell, one per line: days and holidays, weeks and pay rate
            parts = [p.strip() for p in re.split(r"[\n\r]+|\s{2,}|\s(?=\d)", cell) if p.strip()]
            for ind, p in zip(inds, parts):
                if (v := num(p)) is not None and re.fullmatch(r"[\d.,]+\s*%?", p):
                    out[ind] = v
            continue
        v = num(cell)
        if v is None:
            continue
        if inds[0] == "lwb_min_wage_usd" and v <= 0:  # no statutory minimum: Remote writes 0
            continue
        out[inds[0]] = v
    if "lwb_annual_leave_days" in out and "lwb_public_holidays" in out:
        out["lwb_paid_leave_days"] = out["lwb_annual_leave_days"] + out["lwb_public_holidays"]
    return out


def _lwb_country(cell: str) -> str | None:
    """'New Zealand, Wellington^https://remote.com/country-explorer/new-zealand' -> NZL."""
    cell = str(cell or "")
    name, _, link = cell.partition("^")
    if ent := _country(re.split(r",|\n", name)[0].strip()):
        return ent
    if m := re.search(r"country-explorer/([a-z-]+)", link):
        return _country(m.group(1).replace("-", " ").title())
    return _country(name.strip())


def lwb_rows(text: str) -> dict[str, dict[str, float]]:
    """{country: {indicator: value}} from Remote's index page. Next.js writes the table's rows into
    the page as JSON inside a script string, each {"id": "1", "values": {"rank": ..., "country_capital_city": ...}};
    in the page's own source the quotes are escaped (\\"), in a copy saved after it ran they may not be."""
    out: dict[str, dict[str, float]] = {}
    for pat, escaped in ((r'\{\\"id\\":\\"\d+\\",\\"values\\":\{\\"rank\\".*?\}\}', True),
                         (r'\{"id":"\d+","values":\{"rank".*?\}\}', False)):
        for m in re.finditer(pat, text, re.S):
            raw = m.group(0)
            try:
                obj = json.loads(json.loads(f'"{raw}"') if escaped else raw)
            except (ValueError, TypeError):
                continue
            vals = obj.get("values") or {}
            if "index_score_100" not in vals:
                continue
            ent = _lwb_country(vals.get("country_capital_city", ""))
            if ent and (got := lwb_values(vals)):
                out.setdefault(ent, got)
        if out:
            return out
    return out


def lwb_csv_rows(path: Path) -> dict[str, dict[str, float]]:
    """A CSV made by hand: a country column and Remote's columns (headers compared loosely:
    'Index Score / 100', 'Statutory annual leave', ... as on the page)."""
    table = read_csv_table(path)
    if not table:
        return {}
    head = [key(h) for h in table[0]]
    wanted = {key(c): c for c in LWB_FIELDS} | {
        "indexscore100": "index_score_100", "indexscore": "index_score_100", "score": "index_score_100",
        "minimumstatutorysickpaypercentage": "minimum_statutory_sick_pay_percentage",
        "averagehoursperweekperemployedperson": "average_hours_per_week_per_employed_person",
        "lgbtqinclusivity": "lgbtq_inclusivity", "safetyglobalpeaceindexranking": "safety_global_peace_index_ranking",
        "minimumwage": "minimum_wage", "happinessindex": "happiness_index"}
    ci = next((i for i, h in enumerate(head) if h.startswith("country")), None)
    if ci is None:
        return {}
    out: dict[str, dict[str, float]] = {}
    for r in table[1:]:
        if ci >= len(r) or not (ent := _lwb_country(r[ci])):
            continue
        raw = {wanted[h]: r[i] for i, h in enumerate(head) if h in wanted and i < len(r)}
        if got := lwb_values(raw):
            out[ent] = got
    return out


# ----------------------------------------------------------------------------------------- Natixis retirement index
GRI_PDF = ("https://www.im.natixis.com/content/dam/natixis/website/insights/investor-sentiment/{y}/{y}-gri/"
           "{y}-natixis-global-retirement-index.pdf")
GRI_PAGE = "https://www.im.natixis.com/en-us/insights/investor-sentiment/{y}/global-retirement-index"
# (indicator, chart heading, name, description), in the order the full-rankings table gives them
GRI_SERIES = (
    ("gri_health", "Health", "Retirement index: health",
     "Natixis Global Retirement Index, Health sub-index: life expectancy, health spending per person and the "
     "share of it not paid out of pocket."),
    ("gri_finances", "Finances in Retirement", "Retirement index: finances in retirement",
     "Natixis Global Retirement Index, Finances in Retirement sub-index: old-age dependency, bad bank loans, "
     "inflation, real interest rates, tax burden, governance and government debt."),
    ("gri_quality_of_life", "Quality of Life", "Retirement index: quality of life",
     "Natixis Global Retirement Index, Quality of Life sub-index: happiness, air quality, water and sanitation, "
     "biodiversity and other environmental factors."),
    ("gri_material_wellbeing", "Material Wellbeing", "Retirement index: material wellbeing",
     "Natixis Global Retirement Index, Material Wellbeing sub-index: income per person, income equality and "
     "unemployment."),
    ("gri_score", None, "Global Retirement Index",
     "Natixis Global Retirement Index (with CoreData Research): overall score for retirement security, the "
     "geometric mean of the health, finances in retirement, quality of life and material wellbeing sub-indices. "
     "About 44 countries (IMF advanced economies, OECD members and the BRICs)."),
)
_SCALE = re.compile(r"\d{1,3}%\s*(?:-|–|and)\s*(?:\d{1,3}%|below|above)", re.I)


class NatixisGRI(Connector):
    """Natixis' Global Retirement Index, from the full rankings at the back of each year's report
    (a PDF). The newest report is downloaded; if Natixis refuses, save the report (or several years
    of them) in var\\manual\\natixis_gri. A CSV typed in by hand (Country, Overall, Health, Finances,
    Material, Quality) works too."""
    source_id = "natixis_gri"
    fetch_every_days = 30
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        years = [int(m.group(1)) for f in files if (m := re.search(r"(20\d\d)", f.name))]
        return str(max(years)) if years else None

    def download(self, raw_dir: Path, release: str) -> str:
        last = None
        y0 = int(str(release)[:4])
        for y in (y0, y0 - 1):
            dest = raw_dir / f"{y}-natixis-global-retirement-index.pdf"
            for url in (GRI_PDF.format(y=y), None):
                try:
                    if url is None:  # the PDF moved: look for it on the year's page
                        page = raw_dir / f"gri-{y}.html"
                        self.get(GRI_PAGE.format(y=y), page)
                        m = re.search(r'href="([^"]+global-retirement-index[^"]*\.pdf)"',
                                      page.read_text(encoding="utf-8", errors="replace"))
                        page.unlink(missing_ok=True)
                        if not m:
                            continue
                        url = m.group(1) if m.group(1).startswith("http") else "https://www.im.natixis.com" + m.group(1)
                    self.get(url, dest)
                    if dest.read_bytes()[:5] == b"%PDF-":
                        return url
                    dest.unlink(missing_ok=True)
                except ConnectorError as exc:
                    last = exc
                except httpx.HTTPError as exc:
                    last = exc
        raise ConnectorError(f"natixis_gri: the Global Retirement Index report could not be downloaded ({last}); "
                             "save it in var\\manual\\natixis_gri")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        seen: dict[int, str] = {}
        for f in sorted(raw_dir.iterdir(), reverse=True):
            if f.suffix.lower() == ".pdf":
                year, got = gri_pdf(f)
            elif f.suffix.lower() == ".csv":
                got = gri_csv(read_csv_table(f))
                m = re.search(r"(20\d\d)", f.name)
                year = int(m.group(1)) if m else int(str(release)[:4])
            else:
                continue
            year = year or int(str(release)[:4])
            if not got:
                log.warning("natixis_gri: no full rankings table found in %s", f.name)
                continue
            if year in seen:
                continue
            seen[year] = f.name
            for ent, vals in got.items():
                for ind, v in vals.items():
                    rows.add("iso3", ent, ind, year, v)
        if not len(rows):
            raise ConnectorError(f"natixis_gri: no full rankings read from {raw_dir}")
        self.listed_indicators = [
            indicator(ind, name, desc + " The year is the report's (it uses figures from one to two years before).",
                      "score (0-100%)", "society", self.source_id, f"gri:{ind}", decimals=0, bounds=(0, 100),
                      default_on=ind == "gri_score" or ind == "gri_health" or ind == "gri_finances")
            for ind, _, name, desc in GRI_SERIES]
        return rows.stage(con, self.source_id, vintage)


def gri_pdf(path: Path) -> tuple[int | None, dict[str, dict[str, float]]]:
    """(edition, {country: {indicator: score}}) from a Global Retirement Index report."""
    from pypdf import PdfReader

    r = PdfReader(str(path))
    texts: dict[int, str] = {}

    def page(i: int) -> str:
        if i not in texts:
            try:
                texts[i] = r.pages[i].extract_text() or ""
            except Exception as exc:  # a page pypdf cannot read: skip it
                log.warning("natixis_gri: page %s of %s unreadable (%s)", i + 1, path.name, exc)
                texts[i] = ""
        return texts[i]

    n = len(r.pages)
    full = next((page(i) for i in range(n - 1, -1, -1) if re.search(r"Full\s+Rankings", page(i))), None)
    if full is None:
        return None, {}
    tops = {}
    for i in range(n):
        t = page(i)
        if m := re.search(r"Top\s+25\s+Countries\s+in\s+(.+?)\s+Sub-?Index", t, re.S):
            tops[" ".join(m.group(1).split())] = t
    m = re.search(r"(20\d\d)\s+Natixis\s+Global\s+Retirement", page(0) + full) or re.search(r"(20\d\d)", path.name)
    return (int(m.group(1)) if m else None), gri_table(full, tops)


def _names_in(text: str) -> list[tuple[int, str]]:
    """(position, entity) of each country named in text, longest name first, not overlapping."""
    global _GRI_NAMES
    if _GRI_NAMES is None:
        from worldmodel_contract import catalogue

        names: dict[str, str] = {}
        for e in catalogue.entities().values():
            if e.is_group or e.valid_to:
                continue
            for nm in [e.name, e.short_name, *e.synonyms.split("|")]:
                if nm and len(nm) > 3:
                    names.setdefault(nm.strip(), e.entity_id)
        names.update({"Korea, Rep.": "KOR", "Korea Republic": "KOR", "Republic of Korea": "KOR", "South Korea": "KOR",
                      "Russian Federation": "RUS", "Slovak Republic": "SVK", "Czechia": "CZE", "Czech Republic": "CZE",
                      "Turkey": "TUR", "Türkiye": "TUR", "United States": "USA", "United Kingdom": "GBR",
                      "Hong Kong": "HKG", "Taiwan": "TWN"})
        _GRI_NAMES = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(k) for k in sorted(names, key=len, reverse=True))
                                + r")(?![A-Za-z])"), names
    pat, names = _GRI_NAMES
    return [(m.start(), names[m.group(1)]) for m in pat.finditer(text)]


_GRI_NAMES = None


def gri_table(full: str, tops: dict[str, str] | None = None) -> dict[str, dict[str, float]]:
    """The full rankings: the countries in rank order and five columns of percentages (four
    sub-indices and the overall index). The overall column is the one that never rises down the
    ranking; the sub-indices are told apart by each chart page's top country and score, or else
    taken in the order the report has used (health, finances, quality of life, material wellbeing)."""
    text = _SCALE.sub(" ", full)
    pcts = [float(x) for x in re.findall(r"(?<![\d.])(\d{1,3})\s*%", text)]
    ents: list[str] = []
    for _, e in _names_in(text):
        if e not in ents:
            ents.append(e)
    n = len(ents)
    if n < 10 or len(pcts) < 5 * n:
        return {}
    pcts = pcts[:5 * n] if len(pcts) == 5 * n else pcts[-5 * n:]
    for layout in ("columns", "rows"):
        cols = [pcts[k * n:(k + 1) * n] for k in range(5)] if layout == "columns" else [pcts[k::5] for k in range(5)]
        overall = [k for k, c in enumerate(cols) if all(a >= b for a, b in zip(c, c[1:]))]
        if len(overall) == 1:
            break
    else:
        log.warning("natixis_gri: could not tell which column is the overall index")
        return {}
    g = overall[0]
    subs = [k for k in range(5) if k != g]
    order = {GRI_SERIES[i][0]: k for i, k in enumerate(subs)}
    for ind, heading, *_ in GRI_SERIES[:4]:  # check against the chart pages where they are given
        page = next((t for h, t in (tops or {}).items() if h.lower() == heading.lower()), None)
        if not page:
            continue
        top = re.search(r"(?<![\d.])(\d{1,3})\s*%", _SCALE.sub(" ", page))
        after = page[page.find("Ranking change"):] if "Ranking change" in page else page
        who = _names_in(after)
        if not top or not who:
            continue
        score, ent = float(top.group(1)), who[0][1]
        hit = [k for k in subs if ent in ents and cols[k][ents.index(ent)] == score and score == max(cols[k])]
        if len(hit) == 1 and order[ind] != hit[0]:
            log.info("natixis_gri: %s is column %s, not %s, by its chart page", heading, hit[0] + 1, order[ind] + 1)
            other = next(i for i, k in order.items() if k == hit[0])
            order[other], order[ind] = order[ind], hit[0]
    order["gri_score"] = g
    return {e: {ind: cols[k][i] for ind, k in order.items()} for i, e in enumerate(ents)}


def gri_csv(table: list[list]) -> dict[str, dict[str, float]]:
    """A table typed in by hand: Country and columns whose headers name each part."""
    for hi, row in enumerate(table[:10]):
        head = [key(h) for h in row]
        ci = next((i for i, h in enumerate(head) if h.startswith("country")), None)
        if ci is None:
            continue
        cols = {}
        for i, h in enumerate(head):
            ind = ("gri_health" if "health" in h else "gri_finances" if "financ" in h else
                   "gri_quality_of_life" if "quality" in h else "gri_material_wellbeing" if "material" in h else
                   "gri_score" if h in ("gri", "overall", "score", "globalretirementindex", "index") else None)
            if ind:
                cols[i] = ind
        out = {}
        for r in table[hi + 1:]:
            if ci < len(r) and (ent := _country(str(r[ci] or "").strip())):
                vals = {ind: v * 100 if v <= 1 else v for i, ind in cols.items() if i < len(r) and (v := num(r[i])) is not None}
                if vals:
                    out[ent] = vals
        return out
    return {}
