"""Sanctions in force today: who is listed, by whom, from OpenSanctions.

opensanctions
    OpenSanctions merges more than 300 official sanctions lists every day, among them New
    Zealand's Russia Sanctions Register, Australia's DFAT consolidated list, the UK's OFSI
    list, the US OFAC lists, the EU's and the UN Security Council's. Its bulk data are free
    for non-commercial use (CC BY-NC 4.0). The "sanctions" collection's simple CSV is read
    once a week (about 100 MB); only these are kept:

    * sanction_counts: for each country a listed person, company, ship or aircraft is linked
      to, and each authority listing it, how many it lists and how many it added in the last
      365 days;
    * sanction_listings: each listing's name, kind, countries, authorities, when it first
      appeared and last changed, and for ships and aircraft their IMO and MMSI numbers (so
      "Ships now" can mark sanctioned ships).

Which authority a list belongs to comes from its name (worldmodel_contract.osint.authority).
The Global Sanctions Database (gsdb) stays the source for sanctions history before 2024.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from worldmodel_contract import osint
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import entity_for

log = logging.getLogger(__name__)

URL = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"
FILE = "targets.simple.csv"
KEEP_IDENTIFIERS = {"Vessel", "Airplane"}


def _day(v) -> date | None:
    try:
        return datetime.fromisoformat(str(v)[:10]).date() if v else None
    except ValueError:
        return None


def _targets(countries: str) -> list[str]:
    out = []
    for c in re.split(r"[;,]", countries or ""):
        ent = entity_for("iso2", c.strip().upper()) if len(c.strip()) == 2 else None
        if ent and ent not in out:
            out.append(ent)
    return out


def read_targets(path: Path, today: date | None = None) -> tuple[list[tuple], list[tuple]]:
    """(sanction_counts rows, sanction_listings rows) from targets.simple.csv."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    counts: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    listings = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
    seen = [d for r in rows if (d := _day(r.get("first_seen")))]
    ref = today or (max(seen) if seen else date.today())
    for r in rows:
        schema = (r.get("schema") or "").strip() or "Thing"
        auths = sorted({osint.authority(t) for t in re.split(r";", r.get("dataset") or r.get("datasets") or "") if t.strip()})
        targets = _targets(r.get("countries") or "")
        first = _day(r.get("first_seen"))
        recent = bool(first and first >= ref - timedelta(days=365))
        for t in targets or ["none"]:
            for a in auths or ["other"]:
                c = counts[(t, a, schema)]
                c[0] += 1
                c[1] += recent
        ids = ""
        if schema in KEEP_IDENTIFIERS:
            ids = ",".join(sorted({x for x in re.findall(r"\b\d{7}\b|\b\d{9}\b", r.get("identifiers") or "")}))
        listings.append((r.get("id"), (r.get("name") or "").strip()[:200], schema, ",".join(targets), ",".join(auths), first,
                         _day(r.get("last_change")), ids or None))
    return [(t, a, s, n, rec) for (t, a, s), (n, rec) in counts.items()], listings


class OpenSanctions(Connector):
    source_id = "opensanctions"
    switch = "sanctions_now_fetch"
    fetch_every_days = 7

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(URL, raw_dir / FILE)
        return URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        f = next((p for p in raw_dir.iterdir() if p.suffix.lower() == ".csv"), None)
        if not f:
            raise ConnectorError(f"opensanctions: no targets.simple.csv in {raw_dir}")
        counts, listings = read_targets(f)
        if not listings:
            raise ConnectorError(f"opensanctions: nothing read from {f.name}; the layout may have changed")
        con.execute("CREATE TABLE sc (target VARCHAR, authority VARCHAR, schema VARCHAR, listed INTEGER, added_365 INTEGER)")
        con.executemany("INSERT INTO sc VALUES (?, ?, ?, ?, ?)", counts)
        con.execute("CREATE TABLE sl (os_id VARCHAR, name VARCHAR, schema VARCHAR, targets VARCHAR, authorities VARCHAR, "
                    "first_seen DATE, last_change DATE, identifiers VARCHAR)")
        con.executemany("INSERT INTO sl VALUES (?, ?, ?, ?, ?, ?, ?, ?)", listings)
        self.history_queries = {"sanction_counts": "SELECT * FROM sc",
                                "sanction_listings": "SELECT DISTINCT ON (os_id) * FROM sl WHERE os_id IS NOT NULL"}
        log.info("opensanctions: %s listings", f"{len(listings):,}")
        return EMPTY_OBSERVATIONS
