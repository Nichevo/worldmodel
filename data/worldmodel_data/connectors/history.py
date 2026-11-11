"""The long view: borders over time, figures over centuries, and dated events far back.

Four sources, each switchable in Settings > Long history:

* cliopatria: Seshat's Cliopatria, the borders of 1,600-odd states and empires from
  3400 BC to 2024, one shape for each stretch of years with unchanged borders (CC BY 4.0).
  One zip from GitHub, about 46 MB, checked twice a year:

      https://github.com/Seshat-Global-History-Databank/cliopatria

  The shapes are made smaller before they are stored (Douglas-Peucker to about 2 km,
  coordinates to 0.01 degree, tiny islands dropped): 173 MB of GeoJSON become about a
  fifth of that, which is plenty for a world map. Names in brackets, "(British Empire)",
  are composites joining a power's parts (Components); a part names its whole in MemberOf.
  Coverage is thin before 500 BC and the Pacific starts in the 1870s.

* owid_longrun: long-run series through Our World in Data's chart files (the same
  grapher CSVs as owid_grapher): population since 10,000 BC (HYDE, Gapminder, UN),
  GDP per person (Maddison Project), literacy, life expectancy, years of schooling,
  merchandise exports, military spending and personnel, the urban share. Years before
  AD 1 are negative, so these go into long_series rather than the dated observations.
  A chart OWID has renamed is tried under its other names, then skipped with a warning.

* wikidata_history: wars, battles, sieges, epidemics, famines, revolutions and treaties
  from Wikidata with articles in five or more Wikipedias, with dates (BC too), a place,
  deaths where given and the English article. One query per kind, once a month.

* noaa_hazel: NOAA's significant earthquakes, volcanic eruptions and tsunamis since
  antiquity (the Natural Hazards database's own API, HazEL), paged 200 at a time with a
  pause between pages, every three months. US government work, public domain.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import duckdb
import httpx
import numpy as np

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.wikidata import ENDPOINT, _qid, _val

log = logging.getLogger(__name__)

NO_ROWS = ("SELECT NULL AS source_id, NULL AS vintage, NULL AS scheme, NULL AS source_code, NULL AS indicator_id, "
           "NULL AS period_start, NULL AS freq, NULL AS breakdown, NULL AS variant, NULL AS value, NULL AS status WHERE false")


# ----------------------------------------------------------------------------- shapes
TOLERANCE = 0.02     # degrees (about 2 km): how far a simplified border may stray
DECIMALS = 2         # coordinates kept to 0.01 degree
MIN_RING_AREA = 0.0004  # square degrees (about 5 km²): smaller islands and holes are dropped


def _dp(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker on one ring or line (n x 2), keeping the first and last points."""
    n = len(pts)
    if n < 4:
        return pts
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[a + 1:b]
        p, q = pts[a], pts[b]
        d = q - p
        norm = math.hypot(d[0], d[1])
        if norm == 0:
            dist = np.hypot(seg[:, 0] - p[0], seg[:, 1] - p[1])
        else:
            dist = np.abs(d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])) / norm
        i = int(np.argmax(dist))
        if dist[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack.append((a, m))
            stack.append((m, b))
    return pts[keep]


def _ring_area(r: np.ndarray) -> float:
    x, y = r[:, 0], r[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def simplify(geometry: dict, tol: float = TOLERANCE) -> dict | None:
    """A smaller Polygon or MultiPolygon: rings simplified, rounded, tiny ones dropped.
    None if nothing is left."""
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    out = []
    for poly in polys:
        rings = []
        for k, ring in enumerate(poly):
            r = np.asarray(ring, dtype=float)
            if r.ndim != 2 or len(r) < 4 or _ring_area(r) < MIN_RING_AREA:
                if k == 0:
                    break  # the outer ring is too small: drop the whole polygon
                continue
            s = np.round(_dp(r, tol), DECIMALS)
            s = s[np.r_[True, np.any(np.diff(s, axis=0) != 0, axis=1)]]  # repeats after rounding
            if len(s) < 4:
                if k == 0:
                    break
                continue
            if not np.array_equal(s[0], s[-1]):
                s = np.vstack([s, s[:1]])
            rings.append(s.tolist())
        if rings:
            out.append(rings)
    if not out:
        return None
    return {"type": "Polygon", "coordinates": out[0]} if len(out) == 1 else {"type": "MultiPolygon", "coordinates": out}


def _bounds_and_centre(geometry: dict) -> tuple[float, float, float, float, float, float]:
    """(west, south, east, north, lat, lon): the box, and the centre of the largest ring's points."""
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    rings = [np.asarray(p[0], dtype=float) for p in polys]
    allp = np.vstack(rings)
    big = max(rings, key=_ring_area)
    # The centre of the area-weighted triangles of the largest ring (its centroid).
    x, y = big[:, 0], big[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = cross.sum() / 2
    if abs(a) > 1e-9:
        cx = float(((x + np.roll(x, -1)) * cross).sum() / (6 * a))
        cy = float(((y + np.roll(y, -1)) * cross).sum() / (6 * a))
    else:
        cx, cy = float(x.mean()), float(y.mean())
    return (float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()), float(allp[:, 1].max()),
            round(cy, 3), round(cx, 3))


class Cliopatria(Connector):
    source_id = "cliopatria"
    switch = "history_borders_fetch"
    fetch_every_days = 182
    tolerance = TOLERANCE
    URL = "https://raw.githubusercontent.com/Seshat-Global-History-Databank/cliopatria/main/cliopatria.geojson.zip"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(self.URL, raw_dir / "cliopatria.geojson.zip")
        return self.URL

    def _features(self, raw_dir: Path) -> list[dict]:
        found = sorted(raw_dir.glob("*.zip")) + sorted(raw_dir.glob("*.geojson")) + sorted(raw_dir.glob("*.json"))
        for path in found:
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as z:
                    names = [n for n in z.namelist() if n.lower().endswith((".geojson", ".json")) and "polit" in n.lower()]
                    names = names or [n for n in z.namelist() if n.lower().endswith((".geojson", ".json"))]
                    if not names:
                        continue
                    with z.open(names[0]) as f:
                        return json.load(f)["features"]
            elif path.name != "http_cache.json":
                return json.loads(path.read_text(encoding="utf-8"))["features"]
        raise ConnectorError(f"cliopatria: no GeoJSON (or zip holding one) in {raw_dir}")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        feats = self._features(raw_dir)
        rows, dropped = [], 0
        while feats:
            f = feats.pop()  # frees each feature's full-size shape as it goes
            p, g = f.get("properties") or {}, f.get("geometry")
            name = (p.get("Name") or "").strip()
            if not name or not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                dropped += 1
                continue
            try:
                frm, to = int(p["FromYear"]), int(p["ToYear"])
            except (KeyError, TypeError, ValueError):
                dropped += 1
                continue
            small = simplify(g, self.tolerance)
            if small is None:
                small = simplify(g, tol=0)  # a very small state: keep its shape unsimplified rather than lose it
            if small is None:
                dropped += 1
                continue
            west, south, east, north, lat, lon = _bounds_and_centre(small)
            rows.append((f"{name}|{frm}", name, frm, to, p.get("Area"), name.startswith("("),
                         p.get("Components") or None, p.get("MemberOf") or None, p.get("Wikipedia") or None,
                         p.get("Wikidata") or None, lat, lon, west, south, east, north,
                         json.dumps(small, separators=(",", ":"))))
        if not rows:
            raise ConnectorError(f"cliopatria: no shapes read from {raw_dir}")
        con.execute("CREATE TABLE clio (polity_key VARCHAR, name VARCHAR, from_year INTEGER, to_year INTEGER, area_km2 DOUBLE, "
                    "composite BOOLEAN, components VARCHAR, member_of VARCHAR, wikipedia VARCHAR, wikidata VARCHAR, lat DOUBLE, "
                    "lon DOUBLE, west DOUBLE, south DOUBLE, east DOUBLE, north DOUBLE, geojson VARCHAR)")
        con.executemany(f"INSERT INTO clio VALUES ({', '.join('?' * 17)})", rows)
        log.info("cliopatria: %s shapes of %s states and empires (%s skipped)", len(rows), len({r[1] for r in rows}), dropped)
        self.history_queries = {"polities": "SELECT DISTINCT ON (polity_key) * FROM clio"}
        return NO_ROWS


# ----------------------------------------------------------------------------- long-run series
GRAPHER = "https://ourworldindata.org/grapher/"
GRAPHER_QUERY = "?v=1&csvType=full&useColumnShortNames=true"
# (series id, chart slugs to try in turn, column pattern to prefer). The units and sources
# shown with each series are in the contract (history.yaml: series).
LONG_CHARTS = (
    ("population", ("population",), r"^population(_historical)?$"),
    ("gdp_per_capita", ("gdp-per-capita-maddison", "gdp-per-capita-maddison-project-database", "gdp-per-capita-maddison-2020"), r"gdp"),
    ("literacy", ("cross-country-literacy-rates", "literacy-rate-adults", "literacy-rate"), r"literacy"),
    ("life_expectancy", ("life-expectancy",), r"life_expectancy"),
    ("schooling_years", ("mean-years-of-schooling-long-run", "average-years-of-schooling"), r"school"),
    ("exports_share_gdp", ("merchandise-exports-gdp-cepii",), r"export"),
    ("military_spending", ("military-expenditure-total", "military-spending-sipri"), r"milit|expend"),
    ("military_personnel", ("military-personnel", "armed-forces-personnel"), r"personnel|milit|armed"),
    ("urban_share", ("urbanization-last-500-years", "share-of-population-urban"), r"urban"),
)


class OWIDLongRun(Connector):
    source_id = "owid_longrun"
    switch = "history_series_fetch"
    fetch_every_days = 90
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for series, slugs, _ in LONG_CHARTS:
            for slug in slugs:
                if got:
                    time.sleep(self.pause_seconds)
                try:
                    self.get(f"{GRAPHER}{slug}.csv{GRAPHER_QUERY}", raw_dir / f"{series}__{slug}.csv")
                    got.append(slug)
                    break
                except ConnectorError as exc:
                    log.warning("owid_longrun: chart %s not found (%s)", slug, exc)
                    (raw_dir / f"{series}__{slug}.csv").unlink(missing_ok=True)
            else:
                log.warning("owid_longrun: %s skipped: none of its charts (%s) could be downloaded", series, ", ".join(slugs))
        if not got:
            raise ConnectorError("owid_longrun: none of the charts could be downloaded")
        return " ".join(f"{GRAPHER}{s}" for s in got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        known = {s for s, *_ in LONG_CHARTS}
        prefer = {s: p for s, _, p in LONG_CHARTS}
        rows: list[tuple] = []
        for path in sorted(raw_dir.glob("*.csv")):
            series = path.stem.split("__")[0]
            if series not in known:
                continue
            rows += long_rows(path.read_text(encoding="utf-8-sig"), series, prefer[series])
        if not rows:
            raise ConnectorError(f"owid_longrun: no long-run figures read from {raw_dir}")
        con.execute("CREATE TABLE lr (source_code VARCHAR, scheme VARCHAR, series_id VARCHAR, year INTEGER, value DOUBLE)")
        con.executemany("INSERT INTO lr VALUES (?, ?, ?, ?, ?)", rows)
        log.info("owid_longrun: %s figures in %s series", len(rows), len({r[2] for r in rows}))
        self.history_queries = {"long_series": "SELECT * FROM lr"}
        return NO_ROWS


def long_rows(text: str, series: str, prefer: str) -> list[tuple]:
    """(code, scheme, series, year, value) from one grapher CSV: countries by ISO3, the
    World by name; other OWID regions are left out (the app adds up its own)."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return []
    low = [h.lower() for h in header]
    if "entity" not in low or "year" not in low:
        log.warning("owid_longrun: %s has no Entity and Year columns; skipped", series)
        return []
    ie, iy = low.index("entity"), low.index("year")
    ic = low.index("code") if "code" in low else None
    values = [i for i, h in enumerate(low) if i not in (ie, iy, ic) and "annotation" not in h and "projection" not in h]
    pick = [i for i in values if re.search(prefer, low[i])] or values
    if not pick:
        return []
    col = pick[0]
    out = []
    for r in reader:
        if len(r) <= col:
            continue
        code = (r[ic] if ic is not None else "").strip()
        ent = r[ie].strip()
        if re.fullmatch(r"[A-Z]{3}", code):
            key, scheme = code, "iso3"
        elif ent == "World":
            key, scheme = "World", "name"
        else:
            continue
        try:
            year, value = int(r[iy]), float(r[col])
        except ValueError:
            continue
        if math.isfinite(value):
            out.append((key, scheme, series, year, value))
    return out


# ----------------------------------------------------------------------------- events
# kind -> Wikidata classes (an item that is an instance of one, or of a direct subclass of one)
EVENT_CLASSES = {
    "war": ("Q198",),
    "battle": ("Q178561",),
    "siege": ("Q188055",),
    "epidemic": ("Q44512", "Q12184"),
    "famine": ("Q168247",),
    "revolution": ("Q10931",),
    "treaty": ("Q131569", "Q625298"),
}
MIN_LINKS = 5  # articles in at least this many Wikipedias; Settings can ask for more on screen

EVENT_QUERY = """
SELECT ?e ?eLabel ?start ?pit ?end ?coord ?placeCoord ?placeLabel ?iso3 ?deaths ?links ?article WHERE {
  VALUES ?class { %s }
  ?e wdt:P31/wdt:P279? ?class ; wikibase:sitelinks ?links .
  FILTER(?links >= %d)
  OPTIONAL { ?e wdt:P580 ?start }
  OPTIONAL { ?e wdt:P585 ?pit }
  OPTIONAL { ?e wdt:P582 ?end }
  OPTIONAL { ?e wdt:P625 ?coord }
  OPTIONAL { ?e wdt:P276 ?place . ?place wdt:P625 ?placeCoord }
  OPTIONAL { ?e wdt:P17 ?c . ?c wdt:P298 ?iso3 }
  OPTIONAL { ?e wdt:P1120 ?deaths }
  OPTIONAL { ?article schema:about ?e ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""

POINT = re.compile(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)")
WD_TIME = re.compile(r"^([+-]?)(\d+)-(\d\d)-(\d\d)")


def wd_year(v: str | None) -> tuple[int | None, int | None, int | None]:
    """(year, month, day) from a Wikidata time; BC years negative with no year 0
    (Wikidata's "-0215" is 216 BC). Month and day are None when given as 00."""
    m = WD_TIME.match(v or "")
    if not m:
        return None, None, None
    y = int(m.group(2))
    if m.group(1) == "-":
        y = -y - 1
    elif y == 0:
        y = -1
    mo, d = int(m.group(3)) or None, int(m.group(4)) or None
    return y, mo, d


def _point(v: str | None) -> tuple[float | None, float | None]:
    m = POINT.search(v or "")
    if not m:
        return None, None
    lon, lat = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else (None, None)


def event_rows(kind: str, bindings: list[dict]) -> list[tuple]:
    """One row per item (the first value of each field where Wikidata has several)."""
    seen: dict[str, tuple] = {}
    for b in bindings:
        q = _qid(_val(b, "e"))
        title = _val(b, "eLabel")
        if not q or not title or title == q or q in seen:
            continue
        year, month, day = wd_year(_val(b, "start") or _val(b, "pit"))
        if year is None:
            continue
        end = wd_year(_val(b, "end"))[0]
        lat, lon = _point(_val(b, "coord"))
        if lat is None:
            lat, lon = _point(_val(b, "placeCoord"))
        try:
            deaths = float(_val(b, "deaths")) if _val(b, "deaths") else None
        except ValueError:
            deaths = None
        try:
            links = int(_val(b, "links") or 0)
        except ValueError:
            links = 0
        seen[q] = (f"wd:{q}", kind, title, year, end if end is not None and end >= year else None, month, day, lat, lon,
                   _val(b, "placeLabel"), _val(b, "iso3"), deaths, None, None, links,
                   _val(b, "article") or f"https://www.wikidata.org/wiki/{q}")
    return list(seen.values())


HISTORY_EVENT_COLUMNS = ("event_key VARCHAR, kind VARCHAR, title VARCHAR, year INTEGER, end_year INTEGER, month INTEGER, "
                         "day INTEGER, lat DOUBLE, lon DOUBLE, place VARCHAR, country_code VARCHAR, deaths DOUBLE, "
                         "size DOUBLE, size_unit VARCHAR, links INTEGER, url VARCHAR")


def _event_table(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.execute(f"CREATE TABLE hev ({HISTORY_EVENT_COLUMNS})")
    if rows:
        con.executemany(f"INSERT INTO hev VALUES ({', '.join('?' * 16)})", rows)


class WikidataHistory(Connector):
    source_id = "wikidata_history"
    switch = "history_events_fetch"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for kind, classes in EVENT_CLASSES.items():
            q = EVENT_QUERY % (" ".join(f"wd:{c}" for c in classes), MIN_LINKS)
            try:
                self.get(f"{ENDPOINT}?format=json&query={quote(q)}", raw_dir / f"history_{kind}.json")
                got += 1
            except (ConnectorError, httpx.HTTPError) as exc:
                log.warning("wikidata_history: %s query skipped (%s)", kind, exc)
            time.sleep(2)
        if not got:
            raise ConnectorError("wikidata_history: every query failed; the query service may be busy, try again later")
        return ENDPOINT

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows: list[tuple] = []
        for kind in EVENT_CLASSES:
            path = raw_dir / f"history_{kind}.json"
            if path.exists():
                try:
                    bindings = json.loads(path.read_text(encoding="utf-8"))["results"]["bindings"]
                except (json.JSONDecodeError, KeyError):
                    log.warning("wikidata_history: %s is not a query result; skipped", path.name)
                    continue
                rows += event_rows(kind, bindings)
        # An item found as two kinds (a battle that is also a siege) is kept once, as the first kind.
        rows = list({r[0]: r for r in reversed(rows)}.values())
        if not rows:
            raise ConnectorError(f"wikidata_history: nothing read from {raw_dir}")
        _event_table(con, rows)
        log.info("wikidata_history: %s events (%s)", len(rows),
                 ", ".join(f"{k} {sum(r[1] == k for r in rows)}" for k in EVENT_CLASSES))
        self.history_queries = {"history_events": "SELECT * FROM hev"}
        return NO_ROWS


HAZEL = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/"
HAZARDS = (("earthquake", "earthquakes"), ("volcano", "volcanoes"), ("tsunami", "tsunamis/events"))
MAX_PAGES = 80  # a safety stop: the earthquake list is about 35 pages of 200


class NOAAHazards(Connector):
    source_id = "noaa_hazel"
    switch = "history_events_fetch"
    fetch_every_days = 91
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for kind, path in HAZARDS:
            page, pages = 1, 1
            try:
                while page <= min(pages, MAX_PAGES):
                    dest = raw_dir / f"{kind}_{page:03d}.json"
                    self.get(f"{HAZEL}{path}?itemsPerPage=200&page={page}", dest)
                    data = json.loads(dest.read_text(encoding="utf-8"))
                    pages = int(data.get("totalPages") or 1)
                    page += 1
                    time.sleep(self.pause_seconds)
                got += 1
            except (ConnectorError, httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                log.warning("noaa_hazel: %s stopped at page %s (%s)", kind, page, exc)
        if not got:
            raise ConnectorError("noaa_hazel: NOAA's hazards service could not be read; try again later")
        return HAZEL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows: list[tuple] = []
        for kind, _ in HAZARDS:
            for path in sorted(raw_dir.glob(f"{kind}_*.json")):
                try:
                    items = json.loads(path.read_text(encoding="utf-8")).get("items") or []
                except json.JSONDecodeError:
                    log.warning("noaa_hazel: %s is not JSON; skipped", path.name)
                    continue
                rows += hazard_rows(kind, items)
        rows = list({r[0]: r for r in rows}.values())
        if not rows:
            raise ConnectorError(f"noaa_hazel: nothing read from {raw_dir}")
        _event_table(con, rows)
        log.info("noaa_hazel: %s earthquakes, eruptions and tsunamis", len(rows))
        self.history_queries = {"history_events": "SELECT * FROM hev"}
        return NO_ROWS


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def hazard_rows(kind: str, items: list[dict]) -> list[tuple]:
    out = []
    for it in items:
        try:
            year = int(it["year"])
        except (KeyError, TypeError, ValueError):
            continue
        if year == 0:
            year = -1
        lat, lon = _f(it.get("latitude")), _f(it.get("longitude"))
        place = it.get("locationName") or it.get("location") or it.get("country") or ""
        place = re.sub(r"\s+", " ", place.title() if place.isupper() else place).strip()
        deaths = _f(it.get("deathsTotal")) or _f(it.get("deaths"))
        if kind == "volcano":
            vol = it.get("volcano")
            name = it.get("name") or (vol.get("name") if isinstance(vol, dict) else None)
            title, size, unit = f"Eruption of {name or place or 'a volcano'}", _f(it.get("vei")), "VEI"
        elif kind == "earthquake":
            title, size, unit = f"Earthquake: {place}" if place else "Earthquake", _f(it.get("eqMagnitude")), "magnitude"
        else:
            title, size, unit = f"Tsunami: {place}" if place else "Tsunami", _f(it.get("maxWaterHeight")), "metres"
        month, day = it.get("month"), it.get("day")
        out.append((f"noaa:{kind}:{it.get('id')}", kind, title, year, None, int(month) if month else None,
                    int(day) if day else None, lat, lon, place or None, None, deaths, size, unit, None,
                    f"https://www.ngdc.noaa.gov/hazel/view/hazards/{kind}/event-more-info/{it.get('id')}"))
    return out
