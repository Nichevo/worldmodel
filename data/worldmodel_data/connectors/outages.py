"""Internet outages and shutdowns, as dated events on each country (kind "outage").

ioda
    IODA (Internet Outage Detection and Analysis, Georgia Tech): outages it detects for
    every country from three signals (BGP routes, active probing, darknet traffic). Read
    through its open API, a month at a time from the year in Settings (ioda_from_year);
    months already complete are kept. Outages shorter than an hour are left out.
cloudflare_radar
    Cloudflare Radar's outage centre: outages its staff have checked, with a cause
    (government order, cable cut, power, weather, war ...) and scope. Needs a free Cloudflare
    API token with Radar read access (CLOUDFLARE_API_TOKEN). Read a year at a time.
keepiton
    Access Now's #KeepItOn shutdown tracker: government-ordered shutdowns since 2016, one row
    each with dates, type and stated reason. Saved by hand (get.bat opens the page); a CSV
    or Excel export is read, whatever its exact column names.

Each outage is an event (kind outage, subkind its cause where known); IODA's score is the size.
Yearly series by country: internet_outage_hours (IODA) and internet_shutdowns (KeepItOn).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import country_by_name
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, stage_events
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, num, xlsx_rows

log = logging.getLogger(__name__)

IODA_URL = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events"
IODA_MIN_SECONDS = 3600
CLOUDFLARE = "https://api.cloudflare.com/client/v4/radar/annotations/outages"


def _settings() -> dict:
    try:
        from worldmodel_contract.local import load_settings
        from worldmodel_data.config import paths
        return load_settings(paths().home)
    except Exception:  # noqa: BLE001 - settings unreadable: defaults
        return {}


def _iso2(code) -> str | None:
    c = str(code or "").strip().upper()
    return entity_for("iso2", c) if len(c) == 2 else None


def _months(first_year: int, today: date) -> list[date]:
    out, d = [], date(first_year, 1, 1)
    while d <= today:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


# ----------------------------------------------------------------------------- IODA
def ioda_events(records: list[dict]) -> tuple[list[tuple], Rows]:
    rows, hours = [], defaultdict(float)
    for r in records:
        loc = r.get("location") or ""
        code = loc.split("/")[-1] if isinstance(loc, str) else (loc.get("code") if isinstance(loc, dict) else None)
        ent = _iso2(code) or country_by_name(r.get("location_name"))
        start, dur = num(r.get("start")), num(r.get("duration"))
        if not ent or start is None or not dur or dur < IODA_MIN_SECONDS:
            continue
        s = datetime.fromtimestamp(start, timezone.utc)
        e = s + timedelta(seconds=dur)
        h = dur / 3600
        hours[(ent, s.year)] += h
        rows.append((ent, f"ioda:{ent}:{int(start)}", "outage", "detected", f"Internet outage ({h:,.0f} hours)", s.date(),
                     e.date() if e.date() != s.date() else None, "day", num(r.get("score")), "IODA score", None, None, None,
                     r.get("location_name"), f"https://ioda.inetintel.cc.gatech.edu/country/{code}?from={int(start) - 86400}&until={int(start + dur) + 86400}",
                     f"Detected by IODA from internet routing, probing and background traffic; lasted about {h:,.1f} hours."))
    obs = Rows()
    this = date.today().year
    for (ent, year), h in hours.items():
        if year < this:
            obs.add("iso3", ent, "internet_outage_hours", year, round(h, 1))
    return rows, obs


class IODA(Connector):
    source_id = "ioda"
    switch = "outages_fetch"
    fetch_every_days = 2
    keeps_files = True
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        today = date.today()
        last = self.last_vintage_dir(raw_dir)
        have = {p.name for p in last.iterdir()} if last else set()
        recent = date(today.year, today.month, 1) - timedelta(days=40)
        n = 0
        for m in _months(int(_settings().get("ioda_from_year", 2022)), today):
            name = f"ioda_{m:%Y-%m}.json"
            if name in have and m < recent:
                continue
            end = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            if n:
                time.sleep(self.pause_seconds)
            self.get(f"{IODA_URL}?entityType=country&from={_ts(m)}&until={_ts(end)}&limit=5000", raw_dir / name, cached=False)
            n += 1
        return IODA_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        recs = []
        for f in sorted(raw_dir.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            recs += d.get("data") or [] if isinstance(d, dict) else d
        rows, obs = ioda_events(recs)
        if not rows:
            raise ConnectorError(f"ioda: no outages read from {raw_dir}")
        self.events_query = stage_events(con, self.source_id, vintage, rows, set())
        self.listed_indicators = [indicator(
            "internet_outage_hours", "Internet outages, hours",
            "Hours a year of country-wide internet outages detected by IODA (Georgia Tech), from routing, probing and "
            "background traffic; outages under an hour left out. Overlapping outages count once each.", "hours",
            "internet", self.source_id, "ioda:hours", decimals=0, aggregation={"method": "sum"})]
        return obs.stage(con, self.source_id, vintage) if len(obs) else EMPTY_OBSERVATIONS


def _ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# ----------------------------------------------------------------------------- Cloudflare Radar
CAUSES = {"government_directed": "government order", "cable_cut": "cable cut", "power_outage": "power cut",
          "weather": "weather", "military_action": "war", "technical_problem": "technical fault", "maintenance": "maintenance",
          "earthquake": "earthquake", "fire": "fire"}


def cloudflare_events(annotations: list[dict]) -> list[tuple]:
    rows = []
    for a in annotations:
        s = _date(a.get("startDate"))
        if not s:
            continue
        e = _date(a.get("endDate"))
        cause_raw = ((a.get("outage") or {}).get("outageCause") or "").lower()
        cause = CAUSES.get(cause_raw, cause_raw.replace("_", " ") or "unknown")
        kind = ((a.get("outage") or {}).get("outageType") or "").lower()
        codes = [d.get("code") for d in a.get("locationsDetails") or []] or list(a.get("locations") or [])
        for code in codes:
            ent = _iso2(code)
            if not ent:
                continue
            rows.append((ent, f"cfr:{a.get('id')}:{ent}", "outage", cause, f"Internet outage: {cause}", s,
                         e if e and e != s else None, "day", None, None, None, None, None, a.get("scope") or None,
                         a.get("linkedUrl") or "https://radar.cloudflare.com/outage-center",
                         " ".join(x for x in ((a.get("description") or "").strip(), f"({kind} outage)" if kind else "") if x)))
    return rows


def _date(v) -> date | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date() if v else None
    except ValueError:
        return None


class CloudflareRadar(Connector):
    source_id = "cloudflare_radar"
    switch = "outages_fetch"
    needs_env = ("CLOUDFLARE_API_TOKEN",)
    fetch_every_days = 2
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        head = {"Authorization": f"Bearer {self.env('CLOUDFLARE_API_TOKEN')}"}
        this = date.today().year
        last = self.last_vintage_dir(raw_dir)
        have = {p.name for p in last.iterdir()} if last else set()
        for year in range(int(_settings().get("ioda_from_year", 2022)), this + 1):
            name = f"cloudflare_{year}.json"
            if name in have and year < this:
                continue
            self.get(f"{CLOUDFLARE}?dateStart={year}-01-01T00:00:00Z&dateEnd={year}-12-31T23:59:59Z&limit=1000&format=json",
                     raw_dir / name, headers=head, cached=False)
        return CLOUDFLARE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        ann = []
        for f in sorted(raw_dir.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            ann += ((d.get("result") or {}).get("annotations") or []) if isinstance(d, dict) else d
        rows = cloudflare_events(ann)
        if not rows:
            raise ConnectorError(f"cloudflare_radar: no outages read from {raw_dir}")
        self.events_query = stage_events(con, self.source_id, vintage, rows, set())
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- KeepItOn
def _table(path: Path) -> list[list]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return xlsx_rows(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def _pick(cells: list[str], *words: str) -> int | None:
    for w in words:
        for j, c in enumerate(cells):
            if w in c:
                return j
    return None


def _any_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    return None


def keepiton_events(table: list[list]) -> list[tuple]:
    head = None
    for i, row in enumerate(table[:15]):
        cells = [str(c or "").strip().lower() for c in row]
        if _pick(cells, "country") is not None and _pick(cells, "start") is not None:
            head = i, cells
            break
    if not head:
        return []
    i, cells = head
    c_country, c_start = _pick(cells, "country"), _pick(cells, "start")
    c_end = _pick(cells, "end date", "end")
    c_type = _pick(cells, "shutdown type", "type")
    c_why = _pick(cells, "actual cause", "official justification", "justification", "cause", "reason")
    c_area = _pick(cells, "area name", "geographic", "area", "region")
    c_link = _pick(cells, "link", "source", "url")
    rows = []
    for n, row in enumerate(table[i + 1:]):
        def cell(j):
            return row[j] if j is not None and j < len(row) else None
        ent = country_by_name(str(cell(c_country) or "").strip())
        s = _any_date(cell(c_start))
        if not ent or not s:
            continue
        e = _any_date(cell(c_end))
        kind = str(cell(c_type) or "").strip()
        why = str(cell(c_why) or "").strip()
        rows.append((ent, f"keepiton:{ent}:{s.isoformat()}:{n}", "outage", "government order",
                     f"Internet shutdown ordered{': ' + kind.lower() if kind else ''}", s, e if e and e != s else None, "day",
                     None, None, None, None, None, str(cell(c_area) or "").strip() or None,
                     str(cell(c_link) or "").strip() if str(cell(c_link) or "").startswith("http") else
                     "https://www.accessnow.org/keepiton/", why[:400] or None))
    return rows


class KeepItOn(Connector):
    source_id = "keepiton"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("keepiton: saved by hand (get.bat opens Access Now's #KeepItOn page)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = []
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() in (".csv", ".xlsx", ".xlsm"):
                rows += keepiton_events(_table(f))
        if not rows:
            raise ConnectorError(f"keepiton: no shutdowns read from {raw_dir}; is it the #KeepItOn data export?")
        self.events_query = stage_events(con, self.source_id, vintage, rows, set())
        per = defaultdict(int)
        for r in rows:
            per[(r[0], r[5].year)] += 1
        obs = Rows()
        for (ent, year), n in per.items():
            obs.add("iso3", ent, "internet_shutdowns", year, n)
        self.listed_indicators = [indicator(
            "internet_shutdowns", "Internet shutdowns ordered by government",
            "Shutdowns of the internet or of mobile data or social media ordered by a government, as counted by Access "
            "Now's #KeepItOn coalition.", "shutdowns", "internet", self.source_id, "keepiton:count", decimals=0,
            aggregation={"method": "sum"})]
        return obs.stage(con, self.source_id, vintage)
