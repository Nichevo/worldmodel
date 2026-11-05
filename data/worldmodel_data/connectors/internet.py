"""Internet speeds by country from Ookla's open Speedtest data.

    https://ookla-open-data.s3.amazonaws.com/parquet/performance/type=<fixed|mobile>/year=<Y>/quarter=<Q>/<date>_performance_<type>_tiles.parquet

Ookla publishes every quarter since 2019, fixed broadband and mobile separately. Each
file is one row per map tile of about 600 m (zoom 16) with the mean download, upload
and latency of the tests run there, and how many tests and devices (licence CC BY-NC-SA
4.0: fine for a personal tool, credited on every chart). There are no countries in the
files, so each quarter is summed here:

* every tile goes into a 0.05 degree cell (about 5 km), its speeds weighted by its tests;
* each cell goes to the country whose land holds its centre (Natural Earth 1:50m), or,
  for a cell just off the coast, the country within three cells (about 15 km);
* each country's speed is the mean of its tiles weighted by tests, as in Ookla's own
  guide. This is not the median that Ookla's Speedtest Global Index shows, so figures
  run higher than those.

A file is 200 to 400 MB. It is read, summed and deleted, and only the country sums
are kept (one small CSV per quarter, `ookla_<type>_<year>q<quarter>.csv`), carried from
vintage to vintage. A refresh gets the newest quarters first and then older ones back
to the year chosen in Settings, a few files at a time. Parquet files put in the source's
manual folder (or given with --from) are summed the same way when staged.

Stored per year (the mean of its quarters, weighted by tests; the latest year can hold
fewer than four quarters) and per quarter for download speeds.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import indicator, sql_str

log = logging.getLogger(__name__)

BUCKET = "https://ookla-open-data.s3.amazonaws.com/"
PREFIX = "parquet/performance/type={kind}/"
COUNTRIES_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
COUNTRIES_FILE = "ne_50m_admin_0_countries.geojson"
KINDS = ("fixed", "mobile")
CELL = 0.05  # degrees
REACH = 3    # cells off the coast still given to the nearest country
# Natural Earth units without an ISO code of their own.
NE_CODES = {"SOL": "SOM", "CYN": "CYP", "KOS": "XKX", "KAS": "IND"}
CSV_COLUMNS = ("iso3", "tests", "devices", "down_mbps", "up_mbps", "latency_ms")
LABEL = {"fixed": "Fixed broadband", "mobile": "Mobile"}


def _settings() -> dict:
    from worldmodel_contract.local import load_settings
    from worldmodel_data.config import paths
    return load_settings(paths().home)


def quarter_name(kind: str, year: int, q: int) -> str:
    return f"ookla_{kind}_{year}q{q}.csv"


def quarter_of(name: str) -> tuple[str, int, int] | None:
    m = re.fullmatch(r"ookla_(fixed|mobile)_(\d{4})q([1-4])\.csv", name)
    return (m[1], int(m[2]), int(m[3])) if m else None


def parquet_quarter(name: str) -> tuple[str, int, int] | None:
    """(kind, year, quarter) from Ookla's file name, 2024-04-01_performance_fixed_tiles.parquet."""
    m = re.search(r"(\d{4})-(\d{2})-01_performance_(fixed|mobile)_tiles\.parquet$", name)
    return (m[3], int(m[1]), (int(m[2]) - 1) // 3 + 1) if m else None


# ----------------------------------------------------------------------------- countries as a grid
def country_grid(geojson: Path, cell: float = CELL, reach: int = REACH) -> tuple[np.ndarray, list[str]]:
    """A grid of country numbers (0 = none, n = codes[n - 1]) at `cell` degrees, filled
    from the polygons by scanlines (even-odd, so lakes and enclaves stay holes), then
    grown `reach` cells into the sea so coastal tiles are not lost."""
    rows, cols = int(round(180 / cell)), int(round(360 / cell))
    grid = np.zeros((rows, cols), dtype=np.uint16)
    codes: list[str] = []
    feats = json.loads(geojson.read_text(encoding="utf-8"))["features"]
    for f in feats:
        p = f.get("properties") or {}
        code = next((c for c in (p.get("ISO_A3_EH"), p.get("ISO_A3"), p.get("ADM0_A3")) if c and c != "-99"), None)
        code = NE_CODES.get(p.get("ADM0_A3"), code)
        g = f.get("geometry") or {}
        if not code or g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        if code not in codes:
            codes.append(code)
        n = codes.index(code) + 1
        for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            if not _fill(grid, poly, n, cell):  # smaller than a cell (Monaco, Tuvalu, small islands): the cell its middle is in
                pts = np.asarray(poly[0], dtype=float)[:, :2]
                lon, lat = (pts.min(0) + pts.max(0)) / 2
                r = min(rows - 1, max(0, int((90 - lat) / cell)))
                c = min(cols - 1, max(0, int((lon + 180) / cell)))
                grid[r, c] = n  # over a neighbour's cell too: Monaco's tests are Monaco's
    for _ in range(reach):
        empty = grid == 0
        if not empty.any():
            break
        grown = grid.copy()
        for shifted in (np.roll(grid, 1, 0), np.roll(grid, -1, 0), np.roll(grid, 1, 1), np.roll(grid, -1, 1)):
            take = empty & (grown == 0) & (shifted > 0)
            grown[take] = shifted[take]
        grid = grown
    return grid, codes


def _fill(grid: np.ndarray, rings: list, n: int, cell: float) -> int:
    """Fill one polygon (outer ring and holes) with n; the number of cells filled."""
    edges = []
    for ring in rings:
        a = np.asarray(ring, dtype=float)[:, :2]
        if len(a) < 3:
            continue
        b = np.roll(a, -1, axis=0)
        edges.append(np.hstack([a, b]))
    if not edges:
        return 0
    e = np.vstack(edges)
    e = e[e[:, 1] != e[:, 3]]  # flat edges never cross a scanline
    if not len(e):
        return 0
    x1, y1, x2, y2 = e.T
    top, bottom = max(y1.max(), y2.max()), min(y1.min(), y2.min())
    r0 = max(0, int((90 - top) / cell))
    r1 = min(grid.shape[0] - 1, int((90 - bottom) / cell))
    filled = 0
    for r in range(r0, r1 + 1):
        lat = 90 - (r + 0.5) * cell
        hit = ((y1 <= lat) & (lat < y2)) | ((y2 <= lat) & (lat < y1))
        if not hit.any():
            continue
        xs = np.sort(x1[hit] + (lat - y1[hit]) * (x2[hit] - x1[hit]) / (y2[hit] - y1[hit]))
        for a, b in zip(xs[0::2], xs[1::2]):
            c0 = max(0, int(np.ceil((a + 180) / cell - 0.5)))
            c1 = min(grid.shape[1] - 1, int(np.floor((b + 180) / cell - 0.5)))
            if c1 >= c0:
                grid[r, c0:c1 + 1] = n
                filled += c1 - c0 + 1
    return filled


# ----------------------------------------------------------------------------- one quarter's tiles to countries
def sum_tiles(parquet: Path, grid: np.ndarray, codes: list[str], cell: float = CELL) -> list[dict]:
    """Country sums of one Ookla tiles file: tests, devices and test-weighted means."""
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    # The tile's first corner is its north-west one; a fraction of a tile in is its middle.
    cells = con.execute(f"""
        WITH t AS (
          SELECT tests, devices, avg_d_kbps, avg_u_kbps, avg_lat_ms,
                 CAST(regexp_extract(tile, '\\(\\((-?[0-9.]+) ', 1) AS DOUBLE) + 0.0027 AS lon,
                 CAST(regexp_extract(tile, '\\(\\(-?[0-9.]+ (-?[0-9.]+)', 1) AS DOUBLE) - 0.001 AS lat
          FROM read_parquet(?) WHERE tests > 0)
        SELECT LEAST({grid.shape[0] - 1}, GREATEST(0, CAST(floor((90 - lat) / {cell}) AS INTEGER))) AS r,
               LEAST({grid.shape[1] - 1}, GREATEST(0, CAST(floor((lon + 180) / {cell}) AS INTEGER))) AS c,
               sum(tests)::DOUBLE, sum(devices)::DOUBLE, sum(avg_d_kbps * tests)::DOUBLE,
               sum(avg_u_kbps * tests)::DOUBLE, sum(avg_lat_ms * tests)::DOUBLE
        FROM t WHERE lon IS NOT NULL AND lat IS NOT NULL GROUP BY 1, 2""", [str(parquet)]).fetchnumpy()
    con.close()
    if not len(cells["r"]):
        return []
    who = grid[cells["r"], cells["c"]].astype(np.int64)
    keys = list(cells)
    sums = [np.bincount(who, weights=cells[k], minlength=len(codes) + 1) for k in keys[2:]]
    lost = sums[0][0] / max(1.0, sums[0].sum())
    if lost > 0.02:
        log.info("ookla: %.1f%% of tests in %s fell outside every country (sea, or a place Natural Earth leaves out)",
                 100 * lost, parquet.name)
    out = []
    for i, code in enumerate(codes, 1):
        tests = sums[0][i]
        if tests <= 0:
            continue
        out.append({"iso3": code, "tests": int(tests), "devices": int(sums[1][i]), "down_mbps": sums[2][i] / tests / 1000,
                    "up_mbps": sums[3][i] / tests / 1000, "latency_ms": sums[4][i] / tests})
    return out


def write_sums(rows: list[dict], dest: Path) -> None:
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 3) if isinstance(r[k], float) else r[k]) for k in CSV_COLUMNS})


def read_sums(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{"iso3": r["iso3"], **{k: float(r[k]) for k in CSV_COLUMNS[1:] if r.get(k) not in (None, "")}} for r in csv.DictReader(f)]


# ----------------------------------------------------------------------------- the connector
class OoklaSpeedtest(Connector):
    source_id = "ookla_speedtest"
    switch = "internet_speeds_fetch"
    keeps_files = True
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def stored(self) -> set[tuple[str, int, int]]:
        """Quarters already summed in any earlier vintage."""
        try:
            from worldmodel_data.config import paths
            root = paths().raw / self.source_id
        except Exception:  # noqa: BLE001
            return set()
        return {q for p in root.glob("**/ookla_*.csv") if (q := quarter_of(p.name))}

    def available(self) -> list[tuple[str, int, int, str]]:
        """(kind, year, quarter, key) for every tiles file in the bucket, newest first."""
        out = []
        for kind in KINDS:
            token = ""
            while True:
                url = f"{BUCKET}?list-type=2&prefix={PREFIX.format(kind=kind)}" + (f"&continuation-token={token}" if token else "")
                text = self.client.get(url).text
                for key in re.findall(r"<Key>([^<]+)</Key>", text):
                    if (q := parquet_quarter(key)) and q[0] == kind:
                        out.append((*q, key))
                m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
                if not m:
                    break
                token = m[1]
        return sorted(out, key=lambda x: (x[1], x[2], x[0]), reverse=True)

    def download(self, raw_dir: Path, release: str) -> str:
        s = _settings()
        first = int(s.get("internet_speeds_from", 2019))
        per_run = int(s.get("internet_speeds_per_refresh", 8))
        have = self.stored()
        files = [f for f in self.available() if f[1] >= first]
        if not files:
            raise ConnectorError("ookla: the bucket listed no tiles files; its layout may have changed")
        latest = {(f[0], f[1], f[2]) for f in files[:2]}  # the newest quarter of each kind is read again
        todo = [f for f in files if (f[0], f[1], f[2]) not in have or (f[0], f[1], f[2]) in latest][:max(1, per_run)]
        countries = raw_dir / COUNTRIES_FILE
        self.get(COUNTRIES_URL, countries)
        grid, codes = country_grid(countries)
        got = []
        for kind, year, q, key in todo:
            with tempfile.TemporaryDirectory() as tmp:
                pq = Path(tmp) / Path(key).name
                try:
                    self.get(BUCKET + key, pq)
                except ConnectorError as exc:
                    log.warning("ookla: %s skipped (%s)", key, exc)
                    continue
                rows = sum_tiles(pq, grid, codes)
            if rows:
                write_sums(rows, raw_dir / quarter_name(kind, year, q))
                got.append(f"{kind} {year} Q{q}")
        if not got:
            raise ConnectorError("ookla: no quarter could be read")
        left = len([f for f in files if (f[0], f[1], f[2]) not in have]) - len(got)
        if left > 0:
            log.info("ookla: %d older quarter files left for later refreshes", left)
        return f"{BUCKET}{PREFIX} ({', '.join(got)})"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        loose = sorted(raw_dir.glob("*.parquet"))
        if loose:  # tiles files loaded by hand: sum them here, once
            countries = raw_dir / COUNTRIES_FILE
            if not countries.exists():
                raise ConnectorError(f"ookla: {COUNTRIES_FILE} is needed beside the parquet files to find countries "
                                     f"(from {COUNTRIES_URL})")
            grid, codes = country_grid(countries)
            for pq in loose:
                q = parquet_quarter(pq.name)
                if not q:
                    log.warning("ookla: cannot tell the quarter of %s; skipped", pq.name)
                    continue
                write_sums(sum_tiles(pq, grid, codes), raw_dir / quarter_name(*q))
        by_q: dict[tuple[str, int, int], list[dict]] = {}
        for p in sorted(raw_dir.glob("ookla_*.csv")):
            if q := quarter_of(p.name):
                by_q[q] = read_sums(p)
        if not by_q:
            raise ConnectorError(f"ookla: no quarter sums or tiles files in {raw_dir}")
        rows = []
        year_sum: dict[tuple[str, int, str], list[float]] = defaultdict(lambda: [0.0] * 5)
        for (kind, year, q), recs in by_q.items():
            for r in recs:
                if r.get("tests", 0) <= 0:
                    continue
                rows.append((r["iso3"], f"internet_{kind}_down_mbps_q", date(year, 3 * q - 2, 1), "Q", r["down_mbps"]))
                a = year_sum[(kind, year, r["iso3"])]
                t = r["tests"]
                a[0] += t
                a[1] += r.get("devices", 0)
                a[2] += r["down_mbps"] * t
                a[3] += r["up_mbps"] * t
                a[4] += r["latency_ms"] * t
        for (kind, year, code), (t, dev, d, u, lat) in year_sum.items():
            day = date(year, 1, 1)
            rows += [(code, f"internet_{kind}_down_mbps", day, "A", d / t), (code, f"internet_{kind}_up_mbps", day, "A", u / t),
                     (code, f"internet_{kind}_latency_ms", day, "A", lat / t), (code, f"internet_{kind}_tests", day, "A", t)]
        con.execute("CREATE TABLE ookla (source_code VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, value DOUBLE)")
        con.executemany("INSERT INTO ookla VALUES (?, ?, ?, ?, ?)", rows)
        note = ("Ookla Speedtest open data (CC BY-NC-SA 4.0), map tiles summed by country here; the mean of tiles weighted by "
                "tests, which runs higher than the medians on Ookla's Speedtest Global Index.")
        out = []
        for kind in KINDS:
            lab = LABEL[kind]
            out += [
                indicator(f"internet_{kind}_down_mbps", f"{lab} download speed (Ookla)",
                          f"{lab} download speed in tests run on Speedtest by Ookla, megabits a second, the year's mean.",
                          "Mbps", "infrastructure", self.source_id, f"{kind} avg_d_kbps", notes=note),
                indicator(f"internet_{kind}_up_mbps", f"{lab} upload speed (Ookla)",
                          f"{lab} upload speed in Speedtest by Ookla tests, megabits a second, the year's mean.",
                          "Mbps", "infrastructure", self.source_id, f"{kind} avg_u_kbps", notes=note, default_on=False),
                indicator(f"internet_{kind}_latency_ms", f"{lab} latency (Ookla)",
                          f"Time for a message to go to the test server and back in {lab.lower()} Speedtest by Ookla tests, milliseconds.",
                          "ms", "infrastructure", self.source_id, f"{kind} avg_lat_ms", decimals=0, notes=note, default_on=False),
                indicator(f"internet_{kind}_tests", f"{lab} speed tests run (Ookla)",
                          f"How many {lab.lower()} Speedtest by Ookla tests the year's figures rest on.",
                          "tests", "infrastructure", self.source_id, f"{kind} tests", decimals=0, notes=note, default_on=False,
                          aggregation={"method": "sum"}),
                indicator(f"internet_{kind}_down_mbps_q", f"{lab} download speed, each quarter (Ookla)",
                          f"{lab} download speed in Speedtest by Ookla tests, megabits a second, each quarter.",
                          "Mbps", "infrastructure", self.source_id, f"{kind} avg_d_kbps quarterly", notes=note,
                          default_on=False, frequency="Q"),
            ]
        self.listed_indicators = out
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, source_code, "
                "indicator_id, period_start, freq, '' AS breakdown, 'central' AS variant, value, 'E' AS status FROM ookla")
