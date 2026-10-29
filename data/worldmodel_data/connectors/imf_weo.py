"""IMF World Economic Outlook connector, through the IMF DataMapper API.

    GET https://www.imf.org/external/datamapper/api/v1/<INDICATOR>
    -> {"values": {"<INDICATOR>": {"<COUNTRY>": {"<YEAR>": value, ...}, ...}}}

The API always serves the latest WEO release and does not name it, so the
release is worked out from the fetch date (WEO comes out in mid April and
mid October) unless given with --release. Years from the release year on are
IMF projections (status P). Country codes are ISO alpha-3 except a few
(Kosovo is UVK, West Bank and Gaza is WBG), handled by the `imf` scheme in
the crosswalk.

A local folder can stand in for the API: one <INDICATOR>.json file per series
in the same shape, plus an optional release.txt naming the release.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError

log = logging.getLogger(__name__)

API = "https://www.imf.org/external/datamapper/api/v1/"


class IMFWEO(Connector):
    source_id = "imf_weo"
    pause_seconds = 1.0  # between requests; the API has no published limit, so stay polite

    def default_release(self, fetched_at: datetime) -> str:
        md = (fetched_at.month, fetched_at.day)
        if md >= (10, 15):
            return f"{fetched_at.year}-10"
        if md >= (4, 15):
            return f"{fetched_at.year}-04"
        return f"{fetched_at.year - 1}-10"

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            if f.name == "release.txt":
                return f.read_text().strip()
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        urls = []
        for i, code in enumerate(sorted(self.series_map())):
            if i:
                time.sleep(self.pause_seconds)
            url = API + code
            self.get(url, raw_dir / f"{code}.json")
            urls.append(url)
        (raw_dir / "release.txt").write_text(release + "\n")
        return " ".join(urls)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        try:
            first_projection_year = int(release[:4])
        except ValueError:
            raise ConnectorError(f"imf_weo: release {release!r} should start with a year, like 2025-10")
        known = self.known_codes("imf")
        rows = []
        for code, (indicator, scale) in self.series_map().items():
            path = raw_dir / f"{code}.json"
            if not path.exists():
                log.warning("imf_weo: %s missing from %s", path.name, raw_dir)
                continue
            payload = json.loads(path.read_text())
            by_country = payload.get("values", {}).get(code, {})
            for country, years in by_country.items():
                # Keep mapped codes and anything shaped like a country code, so
                # unmapped countries show up in the build report; skip IMF groups.
                if country not in known and not (len(country) == 3 and country.isalpha() and country.isupper()):
                    continue
                for year, value in years.items():
                    if value is None:
                        continue
                    y = int(year)
                    rows.append((country, indicator, f"{y}-01-01", float(value) * scale,
                                 "P" if y >= first_projection_year else "E"))
        if not rows:
            raise ConnectorError(f"imf_weo: no values found in {raw_dir}")
        con.execute("CREATE TABLE imf (source_code VARCHAR, indicator_id VARCHAR, period_start DATE, "
                    "value DOUBLE, status VARCHAR)")
        con.executemany("INSERT INTO imf VALUES (?, ?, ?, ?, ?)", rows)
        return (f"SELECT 'imf_weo' AS source_id, '{vintage}' AS vintage, 'imf' AS scheme, source_code, "
                f"indicator_id, period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, value, status "
                f"FROM imf")
