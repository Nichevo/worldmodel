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
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

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
