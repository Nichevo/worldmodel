"""Planes' positions saved from every OpenSky answer the map gets, so planes that have landed or
left the view can still be seen, replayed and tracked, and what was looked up about a plane
(route, aircraft details, path) is kept on disk and not asked again.

Files live in <home>/live/planes like the ships' (shipstore.py): today's positions in
YYYY-MM-DD.csv, earlier days as YYYY-MM-DD.parquet, days older than the kept number deleted.
Each plane is written at most once every SAVE_EVERY seconds. Look-ups go in lookups.json.
"""

from __future__ import annotations

import csv
import json
import logging
import threading
import time
from pathlib import Path

from worldmodel_api.shipstore import _day, _list, _q

log = logging.getLogger(__name__)

SAVE_EVERY = 4 * 60   # seconds between saved positions of one plane (OpenSky is asked every 1 to 3 minutes)
LOOK_BACK = 10 * 60   # how far before a time to look for a plane's last position
FLIGHT_GAP = 3 * 3600  # a gap longer than this always starts a new flight
LANDED_GAP = 20 * 60   # ... and a gap longer than this does when the plane was low before and after (landed, took off)
LOW_M = 2000           # metres: low enough to be landing or taking off
COLUMNS = ("ts BIGINT, icao VARCHAR, lat DOUBLE, lon DOUBLE, alt DOUBLE, speed DOUBLE, heading DOUBLE, "
           "callsign VARCHAR, grp VARCHAR, country VARCHAR")


def _cols() -> str:
    return "{" + ", ".join(f"'{c.split()[0]}': '{c.split()[1]}'" for c in COLUMNS.split(", ")) + "}"


class PlaneStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.lock = threading.Lock()
        self.written: dict[str, float] = {}
        self._lookups: dict | None = None

    # ------------------------------------------------------------------ positions
    def add_many(self, features: list[dict], now: float | None = None) -> int:
        """Save the planes of one OpenSky answer that are due a position; returns how many."""
        now = now or time.time()
        rows = []
        for f in features:
            p = f.get("properties") or {}
            icao = p.get("id")
            if not icao or now - self.written.get(icao, 0) < SAVE_EVERY:
                continue
            lon, lat = f["geometry"]["coordinates"]
            rows.append([int(now), icao, lat, lon, _blank(p.get("altitude_m")), _blank(p.get("speed_kmh")), _blank(p.get("heading")),
                         p.get("callsign") or "", p.get("group") or "", p.get("country") or ""])
            self.written[icao] = now
        if not rows:
            return 0
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / f"{_day(now)}.csv").open("a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
            if len(self.written) > 200_000:  # forget planes not seen for a day
                self.written = {k: v for k, v in self.written.items() if now - v < 86400}
        return len(rows)

    def tidy(self, keep_days: int, now: float | None = None) -> None:
        now = now or time.time()
        if not self.folder.exists():
            return
        import duckdb

        today = _day(now)
        # Compacting runs without the lock (map requests keep saving planes); only the swap holds it.
        for f in sorted(self.folder.glob("*.csv")):
            if f.stem >= today:
                continue
            tmp = f.with_suffix(".parquet.tmp")
            try:
                con = duckdb.connect()
                con.execute(f"COPY (SELECT * FROM read_csv(?, header=false, columns={_cols()}, ignore_errors=true) ORDER BY icao, ts) "
                            f"TO '{_q(tmp)}' (FORMAT parquet, COMPRESSION zstd)", [str(f)])
                con.close()
                with self.lock:
                    tmp.replace(f.with_suffix(".parquet"))
                    f.unlink()
            except Exception as exc:  # noqa: BLE001 - tried again next hour
                tmp.unlink(missing_ok=True)
                log.warning("plane store: could not compact %s: %s", f.name, exc)
        with self.lock:
            cutoff = _day(now - keep_days * 86400)
            for f in list(self.folder.glob("*.parquet")) + list(self.folder.glob("*.csv")):
                if f.stem < cutoff:
                    f.unlink(missing_ok=True)

    def _query(self, start: float, end: float, sql: str, params: list) -> list[tuple]:
        if not self.folder.exists():
            return []
        lo, hi = _day(start), _day(end)
        files = [str(f) for f in sorted(self.folder.iterdir()) if f.suffix in (".csv", ".parquet") and lo <= f.stem <= hi]
        if not files:
            return []
        import duckdb

        parts = []
        csvs, pqs = [f for f in files if f.endswith(".csv")], [f for f in files if f.endswith(".parquet")]
        if csvs:
            parts.append(f"SELECT * FROM read_csv({_list(csvs)}, header=false, columns={_cols()}, ignore_errors=true)")
        if pqs:
            parts.append(f"SELECT * FROM read_parquet({_list(pqs)})")
        con = duckdb.connect()
        try:
            return con.execute(f"WITH p AS ({' UNION ALL '.join(parts)}) {sql}", params).fetchall()
        finally:
            con.close()

    def at(self, when: float, boxes: list[tuple[float, float, float, float]], back: float = LOOK_BACK) -> list[dict]:
        """Each plane's last saved position in the `back` seconds before `when`, inside the boxes."""
        where = " OR ".join("(lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?)" for _ in boxes) or "true"
        rows = self._query(when - back, when, f"""
            SELECT icao, arg_max(lat, ts), arg_max(lon, ts), arg_max(alt, ts), arg_max(speed, ts), arg_max(heading, ts),
                   arg_max(callsign, ts), arg_max(grp, ts), arg_max(country, ts), max(ts)
            FROM p WHERE ts BETWEEN ? AND ? AND ({where}) GROUP BY icao""",
            [when - back, when] + [v for w, s, e, n in boxes for v in (w, e, s, n)])
        return [{"id": r[0], "lat": r[1], "lon": r[2], "altitude_m": r[3], "speed_kmh": r[4], "heading": r[5] or 0,
                 "callsign": r[6] or None, "group": r[7] or "unknown", "country": r[8] or None, "seen": r[9]} for r in rows]

    def track(self, icao: str, start: float, end: float) -> list[tuple[int, float, float]]:
        """One plane's saved positions between two times, oldest first: (ts, lon, lat)."""
        return [(int(r[0]), r[1], r[2]) for r in self._query(
            start, end, "SELECT ts, lon, lat FROM p WHERE icao = ? AND ts BETWEEN ? AND ? ORDER BY ts", [icao, start, end])]

    def flights(self, start: float, end: float, icao: str | None = None, callsign: str | None = None) -> list[dict]:
        """Saved positions of one aircraft (or every aircraft that flew a callsign) cut into flights,
        newest first. A new flight starts when the callsign changes, after a gap of more than
        FLIGHT_GAP, or after a gap of more than LANDED_GAP with the plane low on both sides (it
        landed and took off again: positions are only kept while in the air)."""
        if not (icao or callsign):
            return []
        where, params = ("icao = ?", [icao.lower()]) if icao else ("callsign = ?", [callsign.strip().upper()])
        rows = self._query(start, end, f"SELECT icao, ts, lon, lat, alt, callsign FROM p WHERE {where} AND ts BETWEEN ? AND ? ORDER BY icao, ts",
                           params + [start, end])
        out: list[dict] = []
        cur: dict | None = None
        for hex_, ts, lon, lat, alt, cs in rows:
            cs = (cs or "").strip() or None
            if cur and cur["icao"] == hex_:
                gap = ts - cur["end"]
                low = alt is not None and alt < LOW_M and cur["_alt"] is not None and cur["_alt"] < LOW_M
                same = (cs == cur["callsign"] or not cs or not cur["callsign"]) and gap <= FLIGHT_GAP and not (gap > LANDED_GAP and low)
            else:
                same = False
            if not same:
                cur = {"icao": hex_, "callsign": cs, "start": int(ts), "end": int(ts), "first": [lon, lat], "last": [lon, lat],
                       "points": 0, "top_m": None, "_alt": alt}
                out.append(cur)
            cur["callsign"] = cur["callsign"] or cs
            cur["end"], cur["last"], cur["_alt"] = int(ts), [lon, lat], alt
            cur["points"] += 1
            if alt is not None and (cur["top_m"] is None or alt > cur["top_m"]):
                cur["top_m"] = round(alt)
        for f in out:
            f.pop("_alt", None)
            f["minutes"] = round((f["end"] - f["start"]) / 60)
        return sorted(out, key=lambda f: f["start"], reverse=True)

    def status(self) -> dict:
        files = [f for f in sorted(self.folder.glob("*")) if f.suffix in (".csv", ".parquet")] if self.folder.exists() else []
        out = {"days": len({f.stem for f in files}), "bytes": sum(f.stat().st_size for f in files), "first": None, "last": None}
        if files:
            try:
                got = self._query(0, time.time() + 86400, "SELECT min(ts), max(ts), count(DISTINCT icao) FROM p", [])
                if got:
                    out.update(first=got[0][0], last=got[0][1], planes=got[0][2])
            except Exception as exc:  # noqa: BLE001 - the counts are a nicety
                log.warning("plane store: status failed: %s", exc)
        return out

    # ------------------------------------------------------------------ look-ups kept on disk
    def _lookups_load(self) -> dict:
        if self._lookups is None:
            try:
                self._lookups = json.loads((self.folder / "lookups.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._lookups = {}
        return self._lookups

    def lookup(self, kind: str, key: str, max_age: float):
        """A kept look-up (route, aircraft, path) no older than max_age seconds: (value, when) or None."""
        with self.lock:
            hit = self._lookups_load().get(kind, {}).get(key)
        if hit and time.time() - hit[0] < max_age:
            return hit[1], hit[0]
        return None

    def keep(self, kind: str, key: str, value, drop_after: float) -> None:
        """Keep a look-up; entries of this kind older than drop_after are dropped when saving."""
        self.keep_many(kind, {key: value}, drop_after)

    def keep_many(self, kind: str, values: dict, drop_after: float) -> None:
        now = time.time()
        with self.lock:
            data = self._lookups_load()
            part = data.setdefault(kind, {})
            for key, value in values.items():
                part[key] = [now, value]
            for k in [k for k, v in part.items() if now - v[0] > drop_after]:
                part.pop(k, None)
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                tmp = self.folder / "lookups.json.tmp"
                tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
                tmp.replace(self.folder / "lookups.json")
            except OSError as exc:
                log.warning("plane store: could not save look-ups: %s", exc)


def _blank(v):
    return "" if v is None else v
