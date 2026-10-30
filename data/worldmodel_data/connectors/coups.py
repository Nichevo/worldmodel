"""Coups d'état since 1950: the Powell and Thyne dataset.

    https://www.uky.edu/~clthyn2/coup_data/powell_thyne_coups_final.txt

One line per coup attempt: country, Correlates of War code(s), year, month, day,
coup (1 failed, 2 successful) and the dataset version. Columns are separated by
tabs, with the codes sometimes left blank, so a line is read from both ends: the
quoted country name first, then year, month, day, coup and version as its last
five values. Countries are matched by name on the coup's date. Free to use with
the citation: Powell, Jonathan M. and Clayton L. Thyne (2011), "Global instances
of coups from 1950 to 2010: A new dataset", Journal of Peace Research 48(2).
"""

from __future__ import annotations

import logging
import shlex
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, country, make_date, stage_events

log = logging.getLogger(__name__)

URL = "https://www.uky.edu/~clthyn2/coup_data/powell_thyne_coups_final.txt"
FILE = "powell_thyne_coups_final.txt"


class Coups(Connector):
    source_id = "powell_thyne"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(URL, raw_dir / FILE)
        return URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = [p for p in raw_dir.iterdir() if p.suffix.lower() in (".txt", ".tsv", ".csv")]
        if not files:
            raise ConnectorError(f"powell_thyne: no data file in {raw_dir}")
        rows, unmatched = read(files[0].read_text(encoding="utf-8", errors="replace"))
        if not rows:
            raise ConnectorError(f"powell_thyne: no coups read from {files[0].name}; the layout may have changed")
        self.events_query = stage_events(con, self.source_id, vintage, rows, unmatched)
        return EMPTY_OBSERVATIONS


def read(text: str) -> tuple[list[tuple], set[str]]:
    rows, unmatched, seen = [], set(), {}
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        try:
            parts = [p for p in shlex.split(line.replace("\t", " ")) if p != ""]
        except ValueError:
            continue
        if len(parts) < 6:
            continue
        name = parts[0]
        year, month, day, coup = parts[-5], parts[-4], parts[-3], parts[-2]
        d, prec = make_date(year, month, day)
        if d is None or coup not in ("1", "2"):
            continue
        entity = country(name, d, unmatched)
        if entity is None:
            continue
        n = seen[(entity, d)] = seen.get((entity, d), 0) + 1
        ok = coup == "2"
        rows.append((entity, f"{entity}:{d.isoformat()}:{n}", "coup", "successful" if ok else "failed",
                     f"{'Successful' if ok else 'Failed'} coup attempt", d, None, prec, None, None, None, None, None,
                     None, None, f"Powell and Thyne coup data, {name}."))
    return rows, unmatched
