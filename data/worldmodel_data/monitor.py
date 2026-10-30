"""The refresh log: one JSON line per refresh or build, for the Data status page.

Each record says, per source, whether a new vintage came in, how much was
downloaded and how long it took, and how many rows the new build added, changed
or removed against the build before it; plus the checks and the disk use by
category afterwards. Kept at warehouse/refresh_log.jsonl and never rewritten,
only appended to.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb

from worldmodel_contract import local
from worldmodel_data.config import Paths

log = logging.getLogger(__name__)

KEY = "source_id, indicator_id, entity_id, period_start, freq, breakdown, variant"  # series holds one vintage per source


def diff_builds(new: Path, previous: Path | None) -> dict[str, dict]:
    """Rows added, changed and removed per source between two builds' series tables."""
    con = duckdb.connect(str(new), read_only=True)
    try:
        if previous is None or not previous.exists() or previous.resolve() == new.resolve():
            found = con.execute("SELECT source_id, count(*) FROM series GROUP BY 1").fetchall()
            return {s: {"rows": n, "added": n, "changed": 0, "removed": 0} for s, n in found}
        con.execute(f"ATTACH '{previous.as_posix()}' AS prev (READ_ONLY)")
        found = con.execute(f"""
            WITH a AS (SELECT {KEY}, value, true AS here FROM series),
                b AS (SELECT {KEY}, value, true AS here FROM prev.series)
            SELECT coalesce(a.source_id, b.source_id) AS source_id,
                count(a.here) AS rows,
                count(*) FILTER (WHERE a.here AND b.here IS NULL) AS added,
                -- aggregates are sums in parallel, so identical inputs can differ in the last bits
                count(*) FILTER (WHERE a.here AND b.here AND (a.value IS DISTINCT FROM b.value) AND
                    coalesce(abs(a.value - b.value) > 1e-9 * greatest(abs(a.value), abs(b.value)), true)) AS changed,
                count(*) FILTER (WHERE a.here IS NULL AND b.here) AS removed
            FROM a FULL JOIN b USING ({KEY}) GROUP BY 1""").fetchall()
        return {s: {"rows": r, "added": ad, "changed": ch, "removed": rm} for s, r, ad, ch, rm in found}
    except duckdb.Error as exc:
        log.warning("could not compare builds: %s", exc)
        return {}
    finally:
        con.close()


def append(paths: Paths, record: dict) -> None:
    path = local.refresh_log_path(paths.home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def storage_lines(paths: Paths) -> list[str]:
    """Plain-text storage summary for the refresh output and build report, with any warning."""
    st = local.storage(paths.home)
    lines = []
    for lim in st["limits"]:
        share = lim["used"] / lim["limit"] if lim["limit"] else 0
        note = {"warn": "WARNING: over 80% of the limit; review the limit or free up space.",
                "critical": "WARNING: over 95% of the limit; free up space or raise the limit in Settings.",
                "full": "LIMIT REACHED: large downloads are skipped until space is freed or the limit is raised."
                }.get(lim["level"], "")
        lines.append(f"{lim['label']}: {lim['used'] / local.GB:.2f} GB of {lim['limit'] / local.GB:.0f} GB "
                     f"({share:.0%}). {note}".rstrip())
    return lines
