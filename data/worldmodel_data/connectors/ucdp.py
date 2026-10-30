"""Armed conflicts since 1946: the UCDP/PRIO Armed Conflict Dataset.

    https://ucdp.uu.se/downloads/  ->  ucdpprio/ucdp-prio-acd-<version>-csv.zip

One row per conflict and year with at least 25 battle-related deaths. Rows are
joined into episodes (a conflict's run of active years, from start_date2 to
ep_end_date) and each episode becomes an event for every country in `location`
(the state(s) whose government is a party to the incompatibility). The size is
the highest intensity in the episode: 1 minor (25 to 999 deaths a year), 2 war
(1,000 or more). The type is extrasystemic, interstate, intrastate or
internationalised intrastate. The newest version is found from the downloads
page; if that cannot be read, the versions from this year back are tried.
UCDP data are free to use with the citation given on the downloads page.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, country, stage_events

log = logging.getLogger(__name__)

PAGE = "https://ucdp.uu.se/downloads/"
URL = "https://ucdp.uu.se/downloads/ucdpprio/ucdp-prio-acd-{v}-csv.zip"
LINK = re.compile(r"ucdpprio/ucdp-prio-acd-(\d+)-csv\.zip", re.I)
TYPES = {"1": "extrasystemic", "2": "interstate", "3": "intrastate", "4": "internationalised intrastate"}


class UCDPConflicts(Connector):
    source_id = "ucdp_acd"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        m = next((re.search(r"acd-(\d+)", f.name) for f in files if re.search(r"acd-(\d+)", f.name)), None)
        return f"{m.group(1)[:2]}.{m.group(1)[2:]}" if m else None

    def download(self, raw_dir: Path, release: str) -> str:
        versions = self.versions()
        tried = []
        for v in versions:
            url = URL.format(v=v)
            try:
                self.get(url, raw_dir / f"ucdp-prio-acd-{v}-csv.zip")
                return url
            except ConnectorError as exc:
                tried.append(str(exc))
                (raw_dir / f"ucdp-prio-acd-{v}-csv.zip").unlink(missing_ok=True)
        raise ConnectorError("ucdp_acd: no Armed Conflict Dataset found; tried:\n  " + "\n  ".join(tried))

    def versions(self) -> list[str]:
        """Versions to try, newest first: those linked on the downloads page, else this year's back."""
        try:
            r = self.client.get(PAGE)
            found = sorted(set(LINK.findall(r.text)), reverse=True) if r.status_code == 200 else []
        except httpx.HTTPError:
            found = []
        if found:
            return found
        y = date.today().year % 100
        return [f"{yy}{n}" for yy in (y, y - 1, y - 2) for n in (1,)]

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".zip", ".csv"))
        if not files:
            raise ConnectorError(f"ucdp_acd: no file in {raw_dir}")
        rows, unmatched = read(_csv_text(files[-1]))
        if not rows:
            raise ConnectorError(f"ucdp_acd: no conflicts read from {files[-1].name}; the layout may have changed")
        self.events_query = stage_events(con, self.source_id, vintage, rows, unmatched)
        return EMPTY_OBSERVATIONS


def _csv_text(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if not name:
                raise ConnectorError(f"ucdp_acd: no CSV inside {path.name}")
            return z.read(name).decode("utf-8-sig", errors="replace")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v[:10], fmt).date()
        except ValueError:
            continue
    return None


def read(text: str) -> tuple[list[tuple], set[str]]:
    """Episodes of each conflict, one event row per country in its location."""
    episodes: dict[tuple[str, date], dict] = {}
    for r in csv.DictReader(io.StringIO(text)):
        start = _date(r.get("start_date2")) or _date(r.get("start_date"))
        year = int(float(r.get("year") or 0))
        if not start or not year:
            continue
        key = (r["conflict_id"], start)
        ep = episodes.setdefault(key, {"row": r, "start": start, "years": [], "intensity": 0, "end": None})
        ep["years"].append(year)
        ep["intensity"] = max(ep["intensity"], int(float(r.get("intensity_level") or 0)))
        if (r.get("ep_end") or "").strip() == "1":
            ep["end"] = _date(r.get("ep_end_date")) or date(year, 12, 31)
    rows, unmatched = [], set()
    for (cid, start), ep in episodes.items():
        r = ep["row"]
        last = max(ep["years"])
        end = ep["end"]  # still going if the episode has not ended
        kind = TYPES.get((r.get("type_of_conflict") or "").strip(), "armed conflict")
        title = f"{r.get('side_a', '').strip()} vs {r.get('side_b', '').strip()}"
        if r.get("territory_name"):
            title += f" ({r['territory_name'].strip()})"
        names = [n.strip() for n in re.split(r",(?![^()]*\))", r.get("location") or "") if n.strip()]
        for name in names:
            entity = country(name, start, unmatched)
            if entity is None:
                continue
            rows.append((entity, f"{cid}:{start.isoformat()}:{entity}", "conflict", kind, title, start, end, "day",
                         float(ep["intensity"]), "intensity (1 minor, 2 war)", None, None, None,
                         r.get("territory_name") or None, f"https://ucdp.uu.se/conflict/{cid}",
                         f"UCDP conflict {cid}, active {min(ep['years'])}-{last}; "
                         f"{'war' if ep['intensity'] == 2 else 'minor'} at its most intense."))
    return rows, unmatched
