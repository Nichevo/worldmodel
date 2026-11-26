"""Ships' positions saved as they arrive from aisstream.io, so the map can show ships at once and
where they were at any time since collecting began.

Files live in <home>/live/ships: today's positions in YYYY-MM-DD.csv (appended as they come),
earlier days turned into YYYY-MM-DD.parquet (about a fifth of the size). Each ship is written at
most once every 10 minutes while moving and once an hour while still, which is enough for a
track on the map and keeps a month of the South Pacific to tens of megabytes. Days older than
the kept number of days are deleted.
"""

from __future__ import annotations

import csv
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MOVING_EVERY = 10 * 60   # seconds between saved positions of a moving ship
STILL_EVERY = 60 * 60    # ... and of one at anchor or alongside
STILL_KNOTS = 0.5
LOOK_BACK = STILL_EVERY + 5 * 60  # how far before a time to look for a ship's last position
COLUMNS = "ts BIGINT, mmsi BIGINT, lat DOUBLE, lon DOUBLE, sog DOUBLE, heading DOUBLE, name VARCHAR, kind INTEGER"


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


class ShipStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.lock = threading.Lock()
        self.written: dict[int, float] = {}  # mmsi -> when last saved
        self.names: dict[int, str] = {}
        self.kinds: dict[int, int] = {}  # AIS ship type code (70-79 cargo, 80-89 tanker ...)
        self.details: dict[int, dict] = {}  # mmsi -> what the ship says about itself, and where it was last
        self.details_dirty = False
        self._load_details()

    # ------------------------------------------------------------------ writing
    def add(self, mmsi: int, lat: float, lon: float, sog, heading, name: str | None, now: float | None = None,
            kind: int | None = None) -> bool:
        """Save one position if the ship is due one; True when saved."""
        now = now or time.time()
        if name:
            self.names[mmsi] = name
        if kind:
            self.kinds[mmsi] = kind
        moving = isinstance(sog, (int, float)) and sog >= STILL_KNOTS
        last = self.written.get(mmsi)
        if last is not None and now - last < (MOVING_EVERY if moving else STILL_EVERY):
            return False
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / f"{_day(now)}.csv").open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([int(now), mmsi, lat, lon, "" if sog is None else sog,
                                        "" if heading is None else heading, self.names.get(mmsi, ""), self.kinds.get(mmsi, "")])
            self.written[mmsi] = now
        return True

    def tidy(self, keep_days: int, now: float | None = None) -> None:
        """Turn finished days into Parquet and delete days older than keep_days. Run about hourly."""
        now = now or time.time()
        today = _day(now)
        if not self.folder.exists():
            return
        import duckdb

        with self.lock:
            for f in sorted(self.folder.glob("*.csv")):
                if f.stem >= today:
                    continue
                out = f.with_suffix(".parquet")
                try:
                    con = duckdb.connect()
                    con.execute(f"COPY (SELECT * FROM read_csv(?, header=false, columns={_cols()}, ignore_errors=true) ORDER BY mmsi, ts) "
                                f"TO '{_q(out)}' (FORMAT parquet, COMPRESSION zstd)", [str(f)])
                    con.close()
                    f.unlink()
                except Exception as exc:  # noqa: BLE001 - tried again next hour
                    log.warning("ship store: could not compact %s: %s", f.name, exc)
            cutoff = _day(now - keep_days * 86400)
            for f in list(self.folder.glob("*.parquet")) + list(self.folder.glob("*.csv")):
                if f.stem < cutoff:
                    f.unlink(missing_ok=True)

    # ------------------------------------------------------------------ ship details
    def _load_details(self) -> None:
        try:
            got = json.loads((self.folder / "ships.json").read_text(encoding="utf-8"))
            self.details = {int(k): v for k, v in got.items()}
            for k, v in self.details.items():
                if v.get("name"):
                    self.names[k] = v["name"]
                if v.get("kind"):
                    self.kinds[k] = v["kind"]
        except (OSError, ValueError):
            self.details = {}

    def note(self, mmsi: int, now: float | None = None, **fields) -> None:
        """Merge what a ship reported (name, call sign, type, size, destination, position...)."""
        now = int(now or time.time())
        with self.lock:
            d = self.details.setdefault(mmsi, {"first_seen": now})
            for k, v in fields.items():
                if v not in (None, "", 0) or (v is not None and k in ("speed_kn", "status", "heading")):
                    d[k] = v
            d["last_seen"] = now
            self.details_dirty = True

    def save_details(self, keep_days: int, now: float | None = None) -> None:
        """Write the details file (every few minutes), leaving out ships not seen in keep_days."""
        if not self.details_dirty:
            return
        now = now or time.time()
        with self.lock:
            self.details = {k: v for k, v in self.details.items() if now - v.get("last_seen", now) <= keep_days * 86400}
            data = json.dumps({str(k): v for k, v in self.details.items()}, separators=(",", ":"))
            self.details_dirty = False
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / "ships.json.tmp"
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(self.folder / "ships.json")

    # ------------------------------------------------------------------ reading
    def _files(self, start: float, end: float) -> list[str]:
        if not self.folder.exists():
            return []
        lo, hi = _day(start), _day(end)
        return [str(f) for f in sorted(self.folder.iterdir()) if f.suffix in (".csv", ".parquet") and lo <= f.stem <= hi]

    def _query(self, start: float, end: float, sql: str, params: list) -> list[tuple]:
        files = self._files(start, end)
        if not files:
            return []
        import duckdb

        csvs = [f for f in files if f.endswith(".csv")]
        pqs = [f for f in files if f.endswith(".parquet")]
        parts = []
        if csvs:
            parts.append(f"SELECT * FROM read_csv({_list(csvs)}, header=false, columns={_cols()}, ignore_errors=true)")
        if pqs:
            parts.append(f"SELECT * FROM read_parquet({_list(pqs)})")
        con = duckdb.connect()
        try:
            return con.execute(f"WITH p AS ({' UNION ALL '.join(parts)}) {sql}", params).fetchall()
        finally:
            con.close()

    def at(self, when: float, boxes: list[tuple[float, float, float, float]], area: list | None = None,
           far_back: float = 0) -> list[dict]:
        """Each ship's last saved position in the hour or so before `when`, inside the boxes. Outside
        `area` (the part collected all the time) it looks `far_back` seconds instead, as the
        whole-world snapshots come only every few hours."""
        where = " OR ".join("(lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?)" for _ in boxes) or "true"
        back = max(LOOK_BACK, far_back) if area else LOOK_BACK
        in_area = " OR ".join("(lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?)" for _ in area or []) or "true"
        params = ([when - back, when] + [v for w, s, e, n in boxes for v in (w, e, s, n)]
                  + [v for w, s, e, n in area or [] for v in (w, e, s, n)] + [when - LOOK_BACK])
        rows = self._query(when - back, when, f"""
            SELECT mmsi, arg_max(lat, ts), arg_max(lon, ts), arg_max(sog, ts), arg_max(heading, ts),
                   arg_max(nullif(name, ''), CASE WHEN coalesce(name, '') = '' THEN 0 ELSE ts END), max(ts),
                   arg_max(kind, CASE WHEN kind IS NULL THEN 0 ELSE ts END)
            FROM p WHERE ts BETWEEN ? AND ? AND ({where}) GROUP BY mmsi
            HAVING NOT (arg_max({_in(in_area)}, ts)) OR max(ts) >= ?""", params)
        return [{"id": r[0], "lat": r[1], "lon": r[2], "speed_kn": r[3], "heading": r[4], "name": r[5], "seen": r[6], "kind": r[7]} for r in rows]

    def track(self, mmsi: int, start: float, end: float) -> list[tuple[int, float, float, float | None]]:
        """One ship's saved positions between two times, oldest first: (ts, lon, lat, sog)."""
        return [(int(r[0]), r[1], r[2], r[3]) for r in self._query(
            start, end, "SELECT ts, lon, lat, sog FROM p WHERE mmsi = ? AND ts BETWEEN ? AND ? ORDER BY ts", [mmsi, start, end])]

    def recent(self, seconds: float, now: float | None = None) -> list[dict]:
        """The last position of every ship saved in the last `seconds` (to fill the map after a restart)."""
        now = now or time.time()
        found = self.at(now, [])
        return [s for s in found if now - s["seen"] <= seconds]

    def status(self) -> dict:
        files = [f for f in sorted(self.folder.glob("*")) if f.suffix in (".csv", ".parquet")] if self.folder.exists() else []
        out = {"days": len({f.stem for f in files}), "bytes": sum(f.stat().st_size for f in files), "first": None, "last": None}
        if files:
            try:
                got = self._query(0, time.time() + 86400, "SELECT min(ts), max(ts), count(DISTINCT mmsi) FROM p", [])
                if got:
                    out.update(first=got[0][0], last=got[0][1], ships=got[0][2])
            except Exception as exc:  # noqa: BLE001 - the counts are a nicety
                log.warning("ship store: status failed: %s", exc)
        return out


def _in(cond: str) -> str:
    return f"({cond})"


def _cols() -> str:
    return "{" + ", ".join(f"'{c.split()[0]}': '{c.split()[1]}'" for c in COLUMNS.split(", ")) + "}"


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _list(files: list[str]) -> str:
    return "[" + ", ".join(f"'{f.replace(chr(39), chr(39) * 2)}'" for f in files) + "]"
