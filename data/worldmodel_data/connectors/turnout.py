"""Voter turnout: International IDEA Voter Turnout Database.

    https://www.idea.int/data-tools/data/voter-turnout-database  ->  World, Export

One row per national election since 1945: country, election type (parliamentary,
presidential, EU parliament), year (or date), voter turnout (% of registered
voters), total vote, registration, VAP turnout (% of the voting-age population),
voting-age population, population, invalid votes and whether voting is compulsory.
A refresh asks for the export once; if IDEA answers with a page instead of the
file, download it by hand and load it with
    worldmodel-data fetch idea_turnout --from <the .xlsx or .csv>
Headers are matched loosely. Each value sits on the election's year; where a
country held two elections of one type in a year, the later one counts.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows

log = logging.getLogger(__name__)

EXPORT = "https://www.idea.int/data-tools/export?type=region_only&themeId=293&world=all&loc=home"
FIELDS = {
    "country": ("country",),
    "iso3": ("iso3", "isocode", "iso"),
    "type": ("electiontype", "type"),
    "year": ("year", "date", "electiondate"),
    "turnout": ("voterturnout", "turnout"),
    "vap_turnout": ("vapturnout",),
    "registration": ("registration", "registeredvoters"),
    "total_vote": ("totalvote", "votescast"),
    "compulsory": ("compulsoryvoting",),
}
TYPES = {"parliamentary": "parliamentary", "presidential": "presidential"}  # EU Parliament elections are left out


def columns(header: list) -> dict[str, int]:
    keys = [key(h) for h in header]
    out = {}
    for field, names in FIELDS.items():
        i = next((i for i, k in enumerate(keys) if k in names), None)
        if i is not None:
            out[field] = i
    return out


class IDEATurnout(Connector):
    source_id = "idea_turnout"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        dest = raw_dir / "idea_turnout.xlsx"
        self.get(EXPORT, dest)
        head = dest.read_bytes()[:512]
        if head.startswith(b"PK"):
            return EXPORT
        if b"<html" in head.lower() or b"<!doctype" in head.lower():
            dest.unlink()
            raise ConnectorError("idea_turnout: IDEA answered with a web page, not the export. Open "
                                 "https://www.idea.int/data-tools/data/voter-turnout-database, choose World, Export, and "
                                 "load the file with: worldmodel-data fetch idea_turnout --from <file>")
        dest.rename(raw_dir / "idea_turnout.csv")
        return EXPORT

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv"))
        if not files:
            raise ConnectorError(f"idea_turnout: no .xlsx or .csv file in {raw_dir}")
        table = (list(csv.reader(io.StringIO(files[0].read_text(encoding="utf-8-sig", errors="replace"))))
                 if files[0].suffix.lower() == ".csv" else xlsx_rows(files[0]))
        start = next((i for i, r in enumerate(table[:20]) if {"type", "year", "turnout"} <= set(columns(r))), None)
        if start is None:
            raise ConnectorError(f"idea_turnout: {files[0].name} has no header with election type, year and turnout")
        col = columns(table[start])
        get = lambda r, f: r[col[f]] if f in col and col[f] < len(r) else None  # noqa: E731
        latest: dict[tuple[str, str, int], tuple[str, dict]] = {}
        unmatched: set[str] = set()
        for r in table[start + 1:]:
            kind = TYPES.get(key(get(r, "type")))
            when = str(get(r, "year") or "").strip()
            m = re.match(r"(\d{4})", when) or re.search(r"(\d{4})$", when)
            if not kind or not m:
                continue
            iso = str(get(r, "iso3") or "").strip().upper()
            name = str(get(r, "country") or "").strip()
            entity = entity_for("iso3", iso) if re.fullmatch(r"[A-Z]{3}", iso) else None
            entity = entity or catalogue.country_by_name(name)
            if not entity:
                unmatched.add(name)
                continue
            k = (entity, kind, int(m.group(1)))
            if k not in latest or when >= latest[k][0]:
                latest[k] = (when, {f: get(r, f) for f in ("turnout", "vap_turnout", "registration", "total_vote")})
        if unmatched:
            log.warning("idea_turnout: %s country names not matched: %s", len(unmatched), ", ".join(sorted(unmatched)[:30]))
        rows = Rows()
        for (entity, kind, y), (_, v) in latest.items():
            rows.add("iso3", entity, f"turnout_{kind}", y, num(v["turnout"]))
            rows.add("iso3", entity, f"vap_turnout_{kind}", y, num(v["vap_turnout"]))
            if kind == "parliamentary":
                rows.add("iso3", entity, "registered_voters", y, num(v["registration"]))
                rows.add("iso3", entity, "votes_cast", y, num(v["total_vote"]))
        if not len(rows):
            raise ConnectorError(f"idea_turnout: no elections read from {files[0].name}")
        self.listed_indicators = INDICATORS
        return rows.stage(con, self.source_id, vintage)


NOTE = "International IDEA Voter Turnout Database; the value sits on the election's year."
INDICATORS = [
    indicator("turnout_parliamentary", "Voter turnout, parliamentary elections",
              "Votes cast as a share of registered voters at national parliamentary (lower house) elections. " + NOTE,
              "% of registered voters", "politics", "idea_turnout", "Voter Turnout: Parliamentary", bounds=(0, 150)),
    indicator("turnout_presidential", "Voter turnout, presidential elections",
              "Votes cast as a share of registered voters at presidential elections. " + NOTE,
              "% of registered voters", "politics", "idea_turnout", "Voter Turnout: Presidential", bounds=(0, 150)),
    indicator("vap_turnout_parliamentary", "Turnout of voting-age population, parliamentary",
              "Votes cast at parliamentary elections as a share of everyone of voting age, registered or not "
              "(lower where many are unregistered or not citizens). " + NOTE,
              "% of voting-age population", "politics", "idea_turnout", "VAP Turnout: Parliamentary", bounds=(0, 150)),
    indicator("vap_turnout_presidential", "Turnout of voting-age population, presidential",
              "Votes cast at presidential elections as a share of everyone of voting age. " + NOTE,
              "% of voting-age population", "politics", "idea_turnout", "VAP Turnout: Presidential", bounds=(0, 150)),
    indicator("registered_voters", "Registered voters", "People on the electoral roll at parliamentary elections. " + NOTE,
              "persons", "politics", "idea_turnout", "Registration: Parliamentary", decimals=0, default_on=False),
    indicator("votes_cast", "Votes cast", "Total votes cast at parliamentary elections. " + NOTE,
              "persons", "politics", "idea_turnout", "Total vote: Parliamentary", decimals=0, default_on=False),
]
