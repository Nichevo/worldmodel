"""Located fighting and unrest: every event with a place, a date and a death count.

ucdp_ged
    UCDP's Georeferenced Event Dataset (Uppsala Conflict Data Program), yearly: every event
    of organised violence with at least one death since 1989, about 400,000 rows, each with
    coordinates and UCDP's best, low and high estimate of deaths.
        https://ucdp.uu.se/downloads/  ->  ged/ged<version>-csv.zip
    The newest version is found from the downloads page (else this year's and last year's
    names are tried). Free with the citation on the downloads page.
ucdp_candidate
    UCDP Candidate Events: the same, month by month since the last yearly release, about a
    month behind (candidateged/GEDEvent_v<yy>_0_<month>.csv). Files already fetched are kept,
    so each refresh only adds the new months. The build drops candidate events dated on or
    before the last day the yearly dataset covers.
acled
    ACLED (Armed Conflict Location & Event Data): battles, explosions and remote violence,
    violence against civilians, protests, riots and strategic developments, every country,
    week by week. Needs a free myACLED account: ACLED_EMAIL and ACLED_PASSWORD in .env (or
    Settings > Keys). Read through ACLED's API a year at a time (5,000 events a page) from
    the year in Settings (acled_from_year); years already complete are kept, not read again.
    ACLED changed what free accounts can read in 2025: an account may get only older or
    less detailed data, and the app shows whatever comes back. A CSV exported from ACLED's
    Data Export Tool, saved in var\\manual\\acled, loads the same way.

All three write conflict_events (one row per event), and yearly series by country:
fighting_deaths (both UCDP and ACLED, shown side by side), civilians_killed (UCDP), and
from ACLED acled_violence_events, acled_protests and acled_riots. A year still under way is
left out of the yearly series (the monthly chart on the country page has it).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_contract import osint
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import country_by_name
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, num

log = logging.getLogger(__name__)

UCDP_PAGE = "https://ucdp.uu.se/downloads/"
GED_URL = "https://ucdp.uu.se/downloads/ged/ged{v}-csv.zip"
GED_LINK = re.compile(r"ged/ged(\d+)-csv\.zip", re.I)
CANDIDATE_BASE = "https://ucdp.uu.se/downloads/candidateged/"
CANDIDATE_LINK = re.compile(r"candidateged/(GEDEvent_v(\d+)_0_(\d+)\.(?:csv|zip))", re.I)

ACLED_TOKEN = "https://acleddata.com/oauth/token"
ACLED_READ = "https://acleddata.com/api/acled/read"
ACLED_FIELDS = ("event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2|iso|country|admin1|location|"
                "latitude|longitude|geo_precision|fatalities|notes")
ACLED_PAGE = 5000
NOTE_CHARS = 300

EVENT_TABLE = ("event_id VARCHAR, country_code VARCHAR, day DATE, end_day DATE, kind VARCHAR, subkind VARCHAR, "
               "deaths DOUBLE, deaths_low DOUBLE, deaths_high DOUBLE, civilians DOUBLE, lat DOUBLE, lon DOUBLE, "
               "place VARCHAR, admin1 VARCHAR, actors VARCHAR, note VARCHAR, geo_precision INTEGER")
N_COLS = 17


def _settings() -> dict:
    try:
        from worldmodel_contract.local import load_settings
        from worldmodel_data.config import paths
        return load_settings(paths().home)
    except Exception:  # noqa: BLE001 - settings unreadable: defaults
        return {}


def _day(v) -> date | None:
    s = str(v or "").strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%d %B %Y", None), ("%d/%m/%Y", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(s[:n] if n else s, fmt).date()
        except ValueError:
            continue
    return None


_COUNTRY_CACHE: dict[str, str | None] = {}


def _country(name: str | None, iso_numeric=None) -> str | None:
    """ISO alpha-3 of a country from its numeric code (ACLED) or its name."""
    if iso_numeric not in (None, ""):
        ent = entity_for("m49", str(iso_numeric).split(".")[0])
        if ent:
            return ent
    key = (name or "").strip()
    if key not in _COUNTRY_CACHE:
        _COUNTRY_CACHE[key] = country_by_name(re.sub(r"\s*\(.*\)$", "", key)) if key else None
    return _COUNTRY_CACHE[key]


def stage_conflict_events(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> str:
    con.execute(f"CREATE TABLE ce ({EVENT_TABLE})")
    if rows:
        con.executemany(f"INSERT INTO ce VALUES ({', '.join('?' * N_COLS)})", rows)
    return "SELECT DISTINCT ON (event_id) * FROM ce"


def _yearly(rows: list[tuple], complete_before: int, by_kind: dict[str, set[str]], source_id: str) -> Rows:
    """Yearly sums by country: indicator -> kinds whose events (counted) or deaths (fighting_deaths, civilians_killed) add up."""
    sums: dict[tuple[str, str, int], float] = defaultdict(float)
    for r in rows:
        code, day, kind, deaths = r[1], r[2], r[4], r[6]
        if not code or not day or day.year >= complete_before:
            continue
        for ind, kinds in by_kind.items():
            if kind in kinds:
                sums[(code, ind, day.year)] += (deaths or 0) if ind in ("fighting_deaths", "civilians_killed") else 1
    obs = Rows()
    for (code, ind, year), v in sums.items():
        obs.add("iso3", code, ind, year, v)
    return obs


def _death_indicators(source_id: str, who: str) -> list[dict]:
    return [indicator(
        "fighting_deaths", "Deaths in fighting",
        "People killed in organised violence where it happened, counted event by event: battles, shelling and strikes, "
        f"and killings of civilians. {who}", "deaths", "conflict", source_id, f"{source_id}:deaths",
        decimals=0, aggregation={"method": "sum"})]


# ----------------------------------------------------------------------------- UCDP
def ged_rows(text: str, prefix: str) -> list[tuple]:
    """conflict_events rows from a UCDP GED (or Candidate) CSV."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        day = _day(r.get("date_start"))
        if not day:
            continue
        kind = osint.UCDP_TYPES.get(str(r.get("type_of_violence") or "").strip().split(".")[0], "state")
        code = _country(r.get("country"))
        sides = " vs ".join(x for x in ((r.get("side_a") or "").strip(), (r.get("side_b") or "").strip()) if x)
        out.append((f"{prefix}:{r.get('id')}", code, day, _day(r.get("date_end")), kind,
                    (r.get("conflict_name") or "").strip() or None, num(r.get("best")), num(r.get("low")),
                    num(r.get("high")), num(r.get("deaths_civilians")), num(r.get("latitude")), num(r.get("longitude")),
                    (r.get("where_coordinates") or "").strip() or None, (r.get("adm_1") or "").strip() or None,
                    sides or None, (r.get("source_headline") or "").strip()[:NOTE_CHARS] or None,
                    int(num(r.get("where_prec")) or 0) or None))
    return out


def _texts(path: Path) -> list[str]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            return [z.read(n).decode("utf-8-sig", errors="replace") for n in z.namelist() if n.lower().endswith(".csv")]
    return [path.read_text(encoding="utf-8-sig", errors="replace")]


class _UCDP(Connector):
    def _page(self) -> str:
        try:
            r = self.client.get(UCDP_PAGE)
            return r.text if r.status_code == 200 else ""
        except httpx.HTTPError:
            return ""


class UCDPGED(_UCDP):
    source_id = "ucdp_ged"
    switch = "conflict_events_fetch"
    fetch_every_days = 60  # a new version each June
    stage_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        m = next((re.search(r"ged(\d{2})(\d)", f.name, re.I) for f in files if re.search(r"ged\d{3}", f.name, re.I)), None)
        return f"{m.group(1)}.{m.group(2)}" if m else None

    def download(self, raw_dir: Path, release: str) -> str:
        found = sorted(set(GED_LINK.findall(self._page())), reverse=True)
        y = date.today().year % 100
        tried = []
        for v in found or [f"{y}1", f"{y - 1}1"]:
            url = GED_URL.format(v=v)
            try:
                self.get(url, raw_dir / f"ged{v}-csv.zip")
                return url
            except ConnectorError as exc:
                tried.append(str(exc))
                (raw_dir / f"ged{v}-csv.zip").unlink(missing_ok=True)
        raise ConnectorError("ucdp_ged: no Georeferenced Event Dataset found; tried:\n  " + "\n  ".join(tried))

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".zip", ".csv"))
        if not files:
            raise ConnectorError(f"ucdp_ged: no file in {raw_dir}")
        rows = [r for t in _texts(files[-1]) for r in ged_rows(t, "ged")]
        if not rows:
            raise ConnectorError(f"ucdp_ged: no events read from {files[-1].name}; the layout may have changed")
        self.history_queries = {"conflict_events": stage_conflict_events(con, rows)}
        last_year = max(r[2] for r in rows).year
        obs = _yearly(rows, last_year + 1, {"fighting_deaths": osint.VIOLENCE, "civilians_killed": {"onesided"}}, self.source_id)
        self.listed_indicators = _death_indicators(self.source_id, "UCDP's best estimate (Georeferenced Event Dataset).") + [
            indicator("civilians_killed", "Civilians killed by armed groups or states",
                      "Deliberate killings of civilians by an armed group or a government (UCDP one-sided violence), "
                      "where it happened.", "deaths", "conflict", self.source_id, "ucdp_ged:onesided", decimals=0,
                      aggregation={"method": "sum"})]
        log.info("ucdp_ged: %s events to %s", f"{len(rows):,}", last_year)
        return obs.stage(con, self.source_id, vintage) if len(obs) else EMPTY_OBSERVATIONS


class UCDPCandidate(_UCDP):
    source_id = "ucdp_candidate"
    switch = "conflict_events_fetch"
    fetch_every_days = 14
    keeps_files = True  # months already fetched are carried from vintage to vintage

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        names = sorted({m[0] for m in CANDIDATE_LINK.findall(self._page())})
        last = self.last_vintage_dir(raw_dir)
        have = {p.name for p in last.iterdir()} if last else set()
        y = date.today().year % 100
        if not names:  # the page could not be read: this year's months, by name
            names = [f"GEDEvent_v{y}_0_{m}.csv" for m in range(1, date.today().month + 1)]
        recent = [n for n in names if int(CANDIDATE_LINK.search("candidateged/" + n).group(2)) >= y - 1]
        # New months, and always the newest (it is sometimes put out again with fixes).
        wanted = [n for n in recent if n not in have or n == recent[-1]]
        got = []
        for n in wanted:
            try:
                self.get(CANDIDATE_BASE + n, raw_dir / n)
                got.append(n)
            except ConnectorError as exc:
                log.info("ucdp_candidate: %s not there (%s)", n, exc)
                (raw_dir / n).unlink(missing_ok=True)
        if not got:
            raise ConnectorError("ucdp_candidate: no monthly candidate files could be read from the UCDP downloads page")
        return CANDIDATE_BASE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".zip", ".csv"))
        rows = [r for f in files for t in _texts(f) for r in ged_rows(t, "ged")]
        if not rows:
            raise ConnectorError(f"ucdp_candidate: no events read from {raw_dir}")
        self.history_queries = {"conflict_events": stage_conflict_events(con, rows)}
        log.info("ucdp_candidate: %s events from %s files", f"{len(rows):,}", len(files))
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- ACLED
def acled_rows(records: list[dict]) -> list[tuple]:
    out = []
    for r in records:
        day = _day(r.get("event_date"))
        if not day:
            continue
        kind = osint.acled_kind(r.get("event_type") or "")
        actors = " vs ".join(x for x in ((r.get("actor1") or "").strip(), (r.get("actor2") or "").strip()) if x)
        out.append((f"acled:{r.get('event_id_cnty')}", _country(r.get("country"), r.get("iso")), day, None, kind,
                    (r.get("sub_event_type") or "").strip() or None, num(r.get("fatalities")), None, None, None,
                    num(r.get("latitude")), num(r.get("longitude")), (r.get("location") or "").strip() or None,
                    (r.get("admin1") or "").strip() or None, actors or None,
                    (r.get("notes") or "").strip()[:NOTE_CHARS] or None, int(num(r.get("geo_precision")) or 0) or None))
    return out


def read_acled_file(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("data") or [] if isinstance(d, dict) else d
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sep = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=sep))


class ACLED(Connector):
    source_id = "acled"
    switch = "acled_on"
    needs_env = ("ACLED_EMAIL", "ACLED_PASSWORD")
    fetch_every_days = 7
    keeps_files = True
    pause_seconds = 2.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def _token(self) -> str:
        r = self.client.post(ACLED_TOKEN, data={"username": self.env("ACLED_EMAIL"), "password": self.env("ACLED_PASSWORD"),
                                                "grant_type": "password", "client_id": "acled"})
        if r.status_code in (400, 401, 403):
            raise ConnectorError("acled: ACLED refused the sign-in (check ACLED_EMAIL and ACLED_PASSWORD; the account "
                                 "must be confirmed at acleddata.com)")
        r.raise_for_status()
        return r.json()["access_token"]

    def download(self, raw_dir: Path, release: str) -> str:
        this = date.today().year
        first = int(_settings().get("acled_from_year", this - 2))
        last = self.last_vintage_dir(raw_dir)
        have = {p.name for p in last.iterdir()} if last else set()
        head = {"Authorization": f"Bearer {self._token()}"}
        got = 0
        for year in range(first, this + 1):
            name = f"acled_{year}.json"
            if name in have and year < this - 1:  # complete and kept
                continue
            data: list[dict] = []
            for page in range(1, 400):
                if page > 1 or got:
                    time.sleep(self.pause_seconds)
                r = self.client.get(ACLED_READ, headers=head, params={
                    "_format": "json", "limit": ACLED_PAGE, "page": page, "fields": ACLED_FIELDS,
                    "event_date": f"{year}-01-01|{year}-12-31", "event_date_where": "BETWEEN"})
                if r.status_code in (401, 403):
                    raise ConnectorError(f"acled: ACLED would not give {year}'s events to this account (HTTP {r.status_code}); "
                                         "free accounts may only see some years. Change Settings > ACLED from year, or "
                                         "save an export from ACLED's Data Export Tool in var\\manual\\acled.")
                r.raise_for_status()
                body = r.json()
                chunk = body.get("data") or []
                data += chunk
                got += 1
                if len(chunk) < ACLED_PAGE:
                    break
            (raw_dir / name).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            log.info("acled: %s events in %s", f"{len(data):,}", year)
        return ACLED_READ

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".json", ".csv"))
        rows = [r for f in files for r in acled_rows(read_acled_file(f))]
        if not rows:
            raise ConnectorError(f"acled: no events read from {raw_dir}")
        self.history_queries = {"conflict_events": stage_conflict_events(con, rows)}
        this = date.today().year
        obs = _yearly(rows, this, {"fighting_deaths": osint.VIOLENCE, "acled_violence_events": osint.VIOLENCE,
                                   "acled_protests": {"protest"}, "acled_riots": {"riot"}}, self.source_id)
        counted = "ACLED; counts follow how much local and national media report, so they rise with better coverage."
        self.listed_indicators = _death_indicators(self.source_id, "ACLED's reported fatalities.") + [
            indicator("acled_violence_events", "Political violence events",
                      f"Battles, shelling, air and drone strikes, and attacks on civilians, as events. {counted}", "events",
                      "conflict", self.source_id, "acled:violence", decimals=0, aggregation={"method": "sum"}),
            indicator("acled_protests", "Protests", f"Peaceful and other protests, as events. {counted}", "events",
                      "conflict", self.source_id, "acled:protests", decimals=0, aggregation={"method": "sum"}),
            indicator("acled_riots", "Riots", f"Violent demonstrations and mob violence, as events. {counted}", "events",
                      "conflict", self.source_id, "acled:riots", decimals=0, aggregation={"method": "sum"}),
        ]
        log.info("acled: %s events", f"{len(rows):,}")
        return obs.stage(con, self.source_id, vintage) if len(obs) else EMPTY_OBSERVATIONS
