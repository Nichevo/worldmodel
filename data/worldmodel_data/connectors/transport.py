"""Transport: ports, shipping, chokepoints, airports and accidents (version 4, PR 4).

portwatch
    IMF PortWatch (CC BY 4.0) through its public ArcGIS services: about 1,700 ports
    with their traffic, about 28 chokepoints (Suez, Panama, Hormuz, Malacca, Cook
    Strait ...), daily transits through each chokepoint and monthly port calls and
    estimated import and export tonnes for each port. Files are kept per year, so a
    weekly refresh fetches only this year and last. Port calls and tonnes add up to
    country figures; a month when transits through a chokepoint fall by 40% or more
    against the two years before becomes an event.
world_port_index
    NGA World Port Index (Pub. 150, public domain): about 3,800 ports, with harbour
    size and type, as a map layer of every port.
shipping_lanes
    Global Shipping Lanes (Benden 2022, CC BY 4.0, GitHub): major, middle and minor
    sea routes as lines.
ourairports
    OurAirports (public domain, GitHub mirror): large and medium airports with
    scheduled flights, as a map layer.
airport_traffic
    Passengers and freight airport by airport: EU airports from Eurostat (avia_paoa,
    avia_gooa), and files saved by hand for New Zealand, Australia (BITRE), the UK
    (CAA) and the US (BTS) in var/manual/airport_traffic: any CSV or Excel table with
    an airport code (IATA or ICAO) or name, a year and passengers (freight optional).
eurostat_waterways
    Freight carried on rivers and canals by country (Eurostat iww_go_atygo), in
    thousand tonnes.
taic_inquiries
    New Zealand's Transport Accident Investigation Commission inquiries, from a list
    saved by hand (date, title, mode; link and deaths if there): events of kind
    transport for New Zealand.
transport_curated
    Hand-checked infrastructure events in transport.yaml: undersea cable cuts,
    pipeline damage, canal blockages and chokepoint attacks, each with a link.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, make_date, stage_events
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows

log = logging.getLogger(__name__)
NO_ROWS = EMPTY_OBSERVATIONS
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def read_table(path: Path) -> list[list]:
    """A CSV or the first sheet of an Excel file as rows of cells."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return xlsx_rows(path)
    if path.suffix.lower() in (".csv", ".txt"):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t") if text.strip() else csv.excel
        return list(csv.reader(io.StringIO(text), dialect))
    return []


def header_rows(table: list[list], need: tuple[str, ...]) -> list[dict]:
    """Rows as dicts keyed by normalised header, the header being the first row that has
    a cell holding each word in `need` (normalised with key())."""
    for i, row in enumerate(table[:40]):
        keys = [key(c) if c is not None else "" for c in row]
        if all(any(n in k for k in keys) for n in need):
            out = []
            for r in table[i + 1:]:
                if r and any(c not in (None, "") for c in r):
                    out.append({keys[j]: r[j] for j in range(min(len(keys), len(r))) if keys[j]})
            return out
    return []


def pick(row: dict, *names: str):
    """The first value among the normalised column names (exact, then starting with)."""
    for n in names:
        if row.get(n) not in (None, ""):
            return row[n]
    for n in names:
        for k, v in row.items():
            if k.startswith(n) and v not in (None, ""):
                return v
    return None


def iso3_of(name_or_code) -> str | None:
    """An entity id for a country code (ISO3 or ISO2) or an English country name."""
    if name_or_code in (None, ""):
        return None
    s = str(name_or_code).strip()
    if re.fullmatch(r"[A-Z]{3}", s):
        return entity_for("iso3", s)
    if re.fullmatch(r"[A-Z]{2}", s):
        return entity_for("iso2", s)
    from worldmodel_data.connectors.events_common import country
    return country(s, None, set())


def stage_geo(con: duckdb.DuckDBPyConnection, rows: list[tuple], table: str = "geo") -> str:
    """Rows (layer_id, feature_id, name, rank, props dict, countries list, geometry) into a
    table and the history query for geo_features."""
    out = []
    for layer, fid, name, rank, props, countries, geom in rows:
        if not geom or not geom.get("coordinates"):
            continue
        b = bounds(geom)
        if b is None:
            continue
        out.append((layer, str(fid), name, rank, json.dumps(props, separators=(",", ":"), ensure_ascii=False),
                    ",".join(sorted(set(c for c in countries if c))), *b, json.dumps(geom, separators=(",", ":"))))
    con.execute(f"CREATE TABLE {table} (layer_id VARCHAR, feature_id VARCHAR, name VARCHAR, rank INTEGER, props VARCHAR, "
                "countries VARCHAR, west DOUBLE, south DOUBLE, east DOUBLE, north DOUBLE, geojson VARCHAR)")
    if out:
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * 11)})", out)
    return f"SELECT DISTINCT ON (layer_id, feature_id) * FROM {table}"


def bounds(geom: dict) -> tuple[float, float, float, float] | None:
    xs, ys = [], []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(geom.get("coordinates") or [])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def simplify_line(points: list, places: int = 3, keep_every: int = 1) -> list:
    """Coordinates rounded, repeated points dropped, every `keep_every`th kept (ends always)."""
    out = []
    for i, p in enumerate(points):
        q = [round(float(p[0]), places), round(float(p[1]), places)]
        if out and q == out[-1]:
            continue
        if keep_every > 1 and 0 < i < len(points) - 1 and i % keep_every:
            continue
        out.append(q)
    return out


# ----------------------------------------------------------------------------- IMF PortWatch
PORTWATCH = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
PW_PAGE = 2000


def shore_key(name: str) -> str:
    """A chokepoint name without its kind words, so "Strait of Hormuz" and "Hormuz Strait" match."""
    words = re.findall(r"[a-z]+", str(name or "").lower().replace("ø", "o"))
    return " ".join(w for w in words if w not in {"strait", "straits", "of", "the", "canal", "channel", "passage", "el"})


def chokepoint_countries() -> dict[str, list[str]]:
    """Chokepoint name (by shore_key) -> countries on its shores (transport.yaml)."""
    return {shore_key(k): v for k, v in (catalogue.transport().get("chokepoints") or {}).items()}


def _epoch_day(v) -> date | None:
    if isinstance(v, (int, float)):
        return (EPOCH + timedelta(milliseconds=v)).date()
    s = str(v or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def pw_features(paths: list[Path]) -> list[dict]:
    """The attributes of every feature in saved ArcGIS query pages (JSON or GeoJSON)."""
    out = []
    for p in paths:
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("portwatch: %s is not JSON; skipped", p.name)
            continue
        for f in body.get("features") or []:
            out.append(f.get("attributes") or f.get("properties") or {})
    return out


def chokepoint_events(daily: list[tuple[str, str, date, float]], drop: float = 0.4) -> list[tuple]:
    """Months when a chokepoint's transits fell by `drop` or more against the same month
    in the two years before, joined into one event per run of months.
    daily: (chokepoint id, name, day, transits). Returns (id, name, first month, last month, fall %)."""
    monthly: dict[tuple[str, int, int], list[float]] = defaultdict(list)
    names = {}
    for cid, name, d, n in daily:
        monthly[(cid, d.year, d.month)].append(n)
        names[cid] = name
    mean = {k: sum(v) / len(v) for k, v in monthly.items() if len(v) >= 20}
    low: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for (cid, y, m), v in sorted(mean.items()):
        before = [mean.get((cid, y - k, m)) for k in (1, 2)]
        before = [b for b in before if b]
        if len(before) < 2:
            continue
        base = sum(before) / 2
        if base >= 1 and v <= base * (1 - drop):
            low[cid].append((date(y, m, 1), 100 * (1 - v / base)))
    out = []
    for cid, months in low.items():
        run = [months[0]]
        for d, f in months[1:]:
            prev = run[-1][0]
            if (d.year * 12 + d.month) - (prev.year * 12 + prev.month) == 1:
                run.append((d, f))
            else:
                out.append((cid, names[cid], run[0][0], run[-1][0], max(x[1] for x in run)))
                run = [(d, f)]
        out.append((cid, names[cid], run[0][0], run[-1][0], max(x[1] for x in run)))
    return out


class PortWatch(Connector):
    source_id = "portwatch"
    switch = "transport_ports_fetch"
    fetch_every_days = 7
    keeps_files = True  # last year's files stay; only this year and last are fetched again
    gap = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def _pages(self, service: str, params: dict, stem: Path) -> int:
        """Save every page of an ArcGIS query as <stem>_<n>.json; the number of features."""
        n, offset, page = 0, 0, 0
        while page < 400:
            q = {"f": "json", "resultOffset": offset, "resultRecordCount": PW_PAGE, **params}
            url = f"{PORTWATCH}/{service}/FeatureServer/0/query?{urlencode(q)}"
            dest = stem.parent / f"{stem.name}_{page:03d}.json"
            self.get(url, dest, cached=False)
            body = json.loads(dest.read_text(encoding="utf-8"))
            if "error" in body:
                dest.unlink(missing_ok=True)
                raise ConnectorError(f"portwatch: {service} answered {body['error'].get('message') or body['error']}")
            got = len(body.get("features") or [])
            n += got
            if got < PW_PAGE and not body.get("exceededTransferLimit"):
                break
            offset += got
            page += 1
            time.sleep(self.gap)
        return n

    def download(self, raw_dir: Path, release: str) -> str:
        today = date.today()
        self._pages("PortWatch_ports_database", {"where": "1=1", "outFields": "*"}, raw_dir / "ports_db")
        self._pages("PortWatch_chokepoints_database", {"where": "1=1", "outFields": "*"}, raw_dir / "chokepoints_db")
        prev = self.last_vintage_dir(raw_dir)
        for year in range(2019, today.year + 1):
            have = prev and list(prev.glob(f"chokepoints_{year}_*.json")) and list(prev.glob(f"ports_{year}_*.json"))
            if have and year < today.year - 1:
                continue  # an earlier year already stored: keeps_files carries it over
            self._pages("Daily_Chokepoints_Data", {"where": f"year={year}",
                                                    "outFields": "date,portid,portname,n_total,n_tanker,n_container,n_dry_bulk,n_cargo,capacity",
                                                    "orderByFields": "ObjectId"}, raw_dir / f"chokepoints_{year}")
            stats = [{"statisticType": "sum", "onStatisticField": f, "outStatisticFieldName": o}
                     for f, o in (("portcalls", "calls"), ("import", "imports"), ("export", "exports"))]
            self._pages("Daily_Ports_Data", {"where": f"year={year}", "groupByFieldsForStatistics": "portid,ISO3,year,month",
                                             "outStatistics": json.dumps(stats), "orderByFields": "portid,month"},
                        raw_dir / f"ports_{year}")
        return PORTWATCH

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        ports = pw_features(sorted(raw_dir.glob("ports_db_*.json")))
        chokes = pw_features(sorted(raw_dir.glob("chokepoints_db_*.json")))
        if not ports and not chokes:
            raise ConnectorError(f"portwatch: no ports_db or chokepoints_db pages in {raw_dir}")
        # Daily transits through each chokepoint
        daily: dict[tuple[str, date], tuple] = {}
        for f in sorted(raw_dir.glob("chokepoints_2*.json")):
            for a in pw_features([f]):
                d = _epoch_day(a.get("date"))
                cid = a.get("portid")
                if d and cid and num(a.get("n_total")) is not None:
                    daily[(cid, d)] = (cid, a.get("portname"), d, num(a.get("n_total")), num(a.get("n_tanker")),
                                       num(a.get("n_container")), num(a.get("n_dry_bulk")), num(a.get("n_cargo")),
                                       num(a.get("capacity")))
        con.execute("CREATE TABLE ck (chokepoint_id VARCHAR, name VARCHAR, day DATE, transits DOUBLE, tankers DOUBLE, "
                    "container DOUBLE, dry_bulk DOUBLE, cargo DOUBLE, capacity DOUBLE)")
        if daily:
            con.executemany("INSERT INTO ck VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", list(daily.values()))
        # Monthly port calls and tonnes
        monthly: dict[tuple[str, int, int], tuple] = {}
        for f in sorted(raw_dir.glob("ports_2*.json")):
            for a in pw_features([f]):
                y, m, pid = num(a.get("year")), num(a.get("month")), a.get("portid")
                if y and m and pid:
                    monthly[(pid, int(y), int(m))] = (pid, (a.get("ISO3") or "").upper(), int(y), int(m),
                                                      num(a.get("calls")), num(a.get("imports")), num(a.get("exports")))
        con.execute("CREATE TABLE pt (port_id VARCHAR, country_code VARCHAR, year INTEGER, month INTEGER, calls DOUBLE, "
                    "import_t DOUBLE, export_t DOUBLE)")
        if monthly:
            con.executemany("INSERT INTO pt VALUES (?, ?, ?, ?, ?, ?, ?)", list(monthly.values()))
        self.history_queries = {"chokepoint_traffic": "SELECT * FROM ck", "port_traffic": "SELECT * FROM pt"}
        # Layers: ports sized by ships a year, chokepoints by transits
        per_port = defaultdict(float)
        last_full = max((y for (_, y, _m) in monthly), default=0)
        months_in = defaultdict(set)
        for (pid, y, m), r in monthly.items():
            months_in[y].add(m)
        full_year = max((y for y, ms in months_in.items() if len(ms) == 12), default=last_full)
        for (pid, y, m), r in monthly.items():
            if y == full_year and r[4]:
                per_port[pid] += r[4]
        pfeats = []
        for a in ports:
            lat, lon = num(a.get("lat")), num(a.get("lon"))
            if lat is None or lon is None:
                continue
            pfeats.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                "id": a.get("portid"), "name": a.get("portname") or "Port", "country": (a.get("ISO3") or "").upper() or None,
                "calls": round(per_port.get(a.get("portid"), 0)) or num(a.get("vessel_count_total")),
                "year": full_year or None, "top": a.get("industry_top1"),
                "imp_share": num(a.get("share_country_maritime_import")),
                "exp_share": num(a.get("share_country_maritime_export"))}))
        n_by_choke: dict[str, list[float]] = defaultdict(list)
        for (cid, d), r in daily.items():
            if d.year == full_year:
                n_by_choke[cid].append(r[3])
        cfeats = []
        for a in chokes:
            lat, lon = num(a.get("lat")), num(a.get("lon"))
            if lat is None or lon is None:
                continue
            vals = n_by_choke.get(a.get("portid")) or []
            cfeats.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                "id": a.get("portid"), "name": a.get("portname") or "Chokepoint",
                "daily": round(sum(vals) / len(vals), 1) if vals else num(a.get("vessel_count_total")),
                "year": full_year or None}))
        if pfeats:
            self.layers.append({"layer_id": "ports", "name": "Ports (IMF PortWatch)", "kind": "point",
                                "description": "About 1,700 ports, sized by ship calls in the last full year (IMF PortWatch, from satellite ship tracking).",
                                "feature_count": len(pfeats), "geojson": collection(pfeats)})
        if cfeats:
            self.layers.append({"layer_id": "chokepoints", "name": "Shipping chokepoints", "kind": "point",
                                "description": "Straits and canals most sea trade passes through, sized by ships a day (IMF PortWatch).",
                                "feature_count": len(cfeats), "geojson": collection(cfeats)})
        # Country figures: calls and tonnes a year, full years only
        rows = Rows()
        sums: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for (pid, y, m), r in monthly.items():
            if len(months_in[y]) < 12 or not r[1]:
                continue
            s = sums[(r[1], y)]
            s[0] += r[4] or 0
            s[1] += r[5] or 0
            s[2] += r[6] or 0
        for (iso, y), (c, i, e) in sums.items():
            ent = entity_for("iso3", iso)
            if not ent:
                continue
            rows.add("iso3", ent, "port_calls", y, c)
            rows.add("iso3", ent, "seaborne_imports_t", y, i)
            rows.add("iso3", ent, "seaborne_exports_t", y, e)
        self.listed_indicators = [
            indicator("port_calls", "Port calls by ships", "Ship calls at the country's ports in the year, counted from "
                      "satellite ship tracking (IMF PortWatch).", "calls", "trade", self.source_id, "portcalls", decimals=0,
                      bounds=(0, 1e8), aggregation={"method": "sum"}),
            indicator("seaborne_imports_t", "Goods arriving by sea (estimated tonnes)", "Tonnes of goods unloaded at the "
                      "country's ports, estimated from ship tracking (IMF PortWatch).", "tonnes", "trade", self.source_id,
                      "import", decimals=0, bounds=(0, 1e11), aggregation={"method": "sum"}),
            indicator("seaborne_exports_t", "Goods leaving by sea (estimated tonnes)", "Tonnes of goods loaded at the "
                      "country's ports, estimated from ship tracking (IMF PortWatch).", "tonnes", "trade", self.source_id,
                      "export", decimals=0, bounds=(0, 1e11), aggregation={"method": "sum"}),
        ]
        # Events: big falls in transits
        shores = chokepoint_countries()
        events = []
        for cid, name, first, last, fall in chokepoint_events([(r[0], r[1], r[2], r[3]) for r in daily.values()]):
            countries = shores.get(shore_key(name)) or []
            end_day = date(last.year + (last.month == 12), last.month % 12 + 1, 1) - timedelta(days=1)
            for ent in countries:
                events.append((ent, f"portwatch:{cid}:{first:%Y-%m}:{ent}", "infrastructure", "chokepoint",
                               f"Ships through {name} down {fall:.0f}%", first, end_day,
                               "month", None, None, None, None, None, name,
                               "https://portwatch.imf.org/pages/chokepoints",
                               f"Transits a month at their lowest {fall:.0f}% below the same months of the two years before "
                               "(IMF PortWatch)."))
        self.events_query = stage_events(con, self.source_id, vintage, events, set())
        log.info("portwatch: %s ports, %s chokepoints, %s chokepoint days, %s port months, %s events",
                 len(pfeats), len(cfeats), len(daily), len(monthly), len(events))
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- World Port Index
WPI_URL = "https://msi.nga.mil/api/publications/download?type=view&key=16920959/SFH00000/UpdatedPub150.csv"
HARBOR_SIZE = {"L": "large", "M": "medium", "S": "small", "V": "very small"}


class WorldPortIndex(Connector):
    source_id = "world_port_index"
    switch = "transport_ports_fetch"
    fetch_every_days = 182

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(WPI_URL, raw_dir / "UpdatedPub150.csv")
        return WPI_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        feats = []
        for p in sorted(raw_dir.iterdir()):
            for r in header_rows(read_table(p), ("latitude", "longitude")):
                lat, lon = num(pick(r, "latitude")), num(pick(r, "longitude"))
                name = pick(r, "mainportname", "portname")
                if lat is None or lon is None or not name:
                    continue
                size = str(pick(r, "harborsize", "harboursize") or "").strip()
                feats.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                    "name": str(name).title() if str(name).isupper() else name,
                    "country": pick(r, "countrycode", "country"), "size": HARBOR_SIZE.get(size[:1].upper(), size.lower() or None),
                    "type": pick(r, "harbortype", "harbourtype"), "locode": pick(r, "unlocode"),
                    "depth": num(pick(r, "channeldepthm", "channeldepth"))}))
        if not feats:
            raise ConnectorError(f"world_port_index: no ports read from {raw_dir}")
        self.layers = [{"layer_id": "ports_all", "name": "Every port (World Port Index)", "kind": "point",
                        "description": "About 3,800 ports with their harbour size and type (NGA World Port Index).",
                        "feature_count": len(feats), "geojson": collection(feats)}]
        return NO_ROWS


# ----------------------------------------------------------------------------- shipping lanes
LANES_URL = "https://raw.githubusercontent.com/newzealandpaul/Shipping-Lanes/main/data/Shipping_Lanes_v1.geojson"
LANE_RANK = {"major": 1, "middle": 2, "minor": 3}


class ShippingLanes(Connector):
    source_id = "shipping_lanes"
    switch = "transport_ports_fetch"
    fetch_every_days = 365

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(LANES_URL, raw_dir / "Shipping_Lanes_v1.geojson")
        return LANES_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.geojson")) + sorted(raw_dir.glob("*.json"))
        if not files:
            raise ConnectorError(f"shipping_lanes: no GeoJSON in {raw_dir}")
        feats = []
        for f in json.loads(files[0].read_text(encoding="utf-8")).get("features", []):
            g, p = f.get("geometry"), f.get("properties") or {}
            if not g or not g.get("coordinates"):
                continue
            t = str(p.get("Type") or p.get("type") or "").strip().lower()
            feats.append(feature(g, {"name": f"{t.title() or 'Shipping'} lane", "rank": LANE_RANK.get(t, 3)}))
        self.layers = [{"layer_id": "shipping_lanes", "name": "Shipping lanes", "kind": "line",
                        "description": "The main sea routes, major to minor (Benden 2022, from the CIA's map of the world's oceans).",
                        "feature_count": len(feats), "geojson": collection(feats)}]
        return NO_ROWS


# ----------------------------------------------------------------------------- airports
AIRPORTS_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"


class OurAirports(Connector):
    source_id = "ourairports"
    switch = "transport_air_fetch"
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(AIRPORTS_URL, raw_dir / "airports.csv")
        return AIRPORTS_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "airports.csv"
        if not p.exists():
            raise ConnectorError(f"ourairports: no airports.csv in {raw_dir}")
        feats = []
        with p.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("type") not in ("large_airport", "medium_airport") or r.get("scheduled_service") != "yes":
                    continue
                lat, lon = num(r.get("latitude_deg")), num(r.get("longitude_deg"))
                if lat is None or lon is None:
                    continue
                feats.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                    "name": r.get("name"), "iata": r.get("iata_code") or None, "icao": r.get("gps_code") or r.get("ident"),
                    "size": "large" if r["type"] == "large_airport" else "medium", "city": r.get("municipality") or None,
                    "country": entity_for("iso2", r.get("iso_country")) or r.get("iso_country"),
                    "wiki": r.get("wikipedia_link") or None}))
        if not feats:
            raise ConnectorError("ourairports: no large or medium airports with scheduled flights in airports.csv")
        self.layers = [{"layer_id": "airports", "name": "Airports", "kind": "point",
                        "description": "Large and medium airports with scheduled flights (OurAirports); passengers where published.",
                        "feature_count": len(feats), "geojson": collection(feats)}]
        log.info("ourairports: %s airports", len(feats))
        return NO_ROWS


# ----------------------------------------------------------------------------- Eurostat (JSON-stat)
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}?{query}"


def jsonstat_rows(body: dict) -> list[tuple[dict, float]]:
    """(labels by dimension id, value) for every cell of a Eurostat JSON-stat 2.0 answer."""
    ids, sizes = body.get("id") or [], body.get("size") or []
    dims = body.get("dimension") or {}
    codes = []
    for d in ids:
        index = (dims.get(d) or {}).get("category", {}).get("index") or {}
        order = sorted(index, key=index.get) if isinstance(index, dict) else list(index)
        codes.append(order)
    values = body.get("value") or {}
    items = values.items() if isinstance(values, dict) else enumerate(values)
    out = []
    for flat, v in items:
        if v is None:
            continue
        flat, cell = int(flat), {}
        for d, size, order in zip(reversed(ids), reversed(sizes), reversed(codes)):
            cell[d] = order[flat % size] if order else None
            flat //= size
        out.append((cell, float(v)))
    return out


EU_GEO = {"EL": "GRC", "UK": "GBR", "XK": "XKX"}


def eu_entity(code: str) -> str | None:
    return entity_for("iso3", EU_GEO[code]) if code in EU_GEO else entity_for("iso2", code)


class AirportTraffic(Connector):
    source_id = "airport_traffic"
    switch = "transport_air_fetch"
    fetch_every_days = 90
    keeps_files = True  # files saved by hand for NZ, Australia, the UK and the US stay beside Eurostat's

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for code, query in (("avia_paoa", {"freq": "A", "unit": "PAS", "tra_meas": "PAS_CRD"}),
                            ("avia_gooa", {"freq": "A", "unit": "T", "tra_meas": "FRM_LD_NLD"})):
            url = EUROSTAT.format(code=code, query=urlencode({"format": "JSON", "lang": "EN", **query, "sinceTimePeriod": "2005"}))
            self.get(url, raw_dir / f"eurostat_{code}.json")
            time.sleep(1)
        return EUROSTAT.format(code="avia_paoa", query="...")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows: dict[tuple[str, int], list] = {}
        for code, field in (("avia_paoa", 4), ("avia_gooa", 5)):
            p = raw_dir / f"eurostat_{code}.json"
            if not p.exists():
                continue
            for cell, v in jsonstat_rows(json.loads(p.read_text(encoding="utf-8"))):
                airp, year = cell.get("rep_airp") or "", num(cell.get("time"))
                m = re.fullmatch(r"([A-Z]{2})_([A-Z0-9]{4})", airp)
                if not m or year is None:
                    continue
                r = rows.setdefault((m[2], int(year)), [m[2], None, eu_entity(m[1]), int(year), None, None])
                r[field] = v
        for p in sorted(raw_dir.iterdir()):
            if p.name.startswith("eurostat_") or p.suffix.lower() not in (".csv", ".xlsx", ".xlsm", ".txt"):
                continue
            for r in header_rows(read_table(p), ("year",)):
                code = str(pick(r, "icao", "iata", "airportcode", "code", "airport") or "").strip()
                year, pax = num(pick(r, "year")), num(pick(r, "passengers", "totalpassengers", "pax"))
                if not code or year is None or pax is None:
                    continue
                k = (code.upper() if re.fullmatch(r"[A-Za-z0-9]{3,4}", code) else code, int(year))
                rows[k] = [k[0], pick(r, "airportname", "name"), iso3_of(pick(r, "country")), int(year), pax,
                           num(pick(r, "freight", "freighttonnes", "cargo"))]
        con.execute("CREATE TABLE apt (airport VARCHAR, name VARCHAR, country_code VARCHAR, year INTEGER, passengers DOUBLE, "
                    "freight_t DOUBLE)")
        if rows:
            con.executemany("INSERT INTO apt VALUES (?, ?, ?, ?, ?, ?)", [tuple(r) for r in rows.values()])
        else:
            raise ConnectorError(f"airport_traffic: no airport figures in {raw_dir}")
        self.history_queries = {"airport_traffic": "SELECT * FROM apt"}
        log.info("airport_traffic: %s airport-years", len(rows))
        return NO_ROWS


class EurostatWaterways(Connector):
    source_id = "eurostat_waterways"
    switch = "transport_waterways_fetch"
    fetch_every_days = 182

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = EUROSTAT.format(code="iww_go_atygo", query=urlencode({"format": "JSON", "lang": "EN", "unit": "THS_T", "tra_cov": "TOTAL"}))
        self.get(url, raw_dir / "eurostat_iww_go_atygo.json")
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "eurostat_iww_go_atygo.json"
        if not p.exists():
            raise ConnectorError(f"eurostat_waterways: no eurostat_iww_go_atygo.json in {raw_dir}")
        rows = Rows()
        for cell, v in jsonstat_rows(json.loads(p.read_text(encoding="utf-8"))):
            ent, year = eu_entity(cell.get("geo") or ""), num(cell.get("time"))
            if ent and year is not None and (cell.get("tra_cov") in (None, "TOTAL")):
                rows.add("iso3", ent, "inland_waterway_freight", int(year), v * 1000)
        self.listed_indicators = [indicator(
            "inland_waterway_freight", "Freight carried on rivers and canals", "Tonnes of goods carried on the country's "
            "inland waterways in the year (Eurostat iww_go_atygo).", "tonnes", "trade", self.source_id, "iww_go_atygo",
            decimals=0, bounds=(0, 1e10), aggregation={"method": "sum"})]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- accidents and infrastructure events
class TAICInquiries(Connector):
    source_id = "taic_inquiries"
    manual = True
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("taic_inquiries: save TAIC's list of inquiries by hand (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        events, seen = [], set()
        for p in sorted(raw_dir.iterdir()):
            for r in header_rows(read_table(p), ("date",)):
                when = pick(r, "occurrencedate", "date", "dateofoccurrence")
                title = pick(r, "title", "inquiry", "name", "description")
                if not when or not title:
                    continue
                if isinstance(when, datetime):
                    d, prec = when.date(), "day"
                else:
                    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})|(\d{4})-(\d{2})-(\d{2})", str(when))
                    if not m:
                        continue
                    d = date(int(m[3]), int(m[2]), int(m[1])) if m[1] else date(int(m[4]), int(m[5]), int(m[6]))
                    prec = "day"
                mode = str(pick(r, "mode", "sector", "type") or "").lower()
                sub = "air" if "avia" in mode or "air" in mode else "sea" if "mari" in mode or "sea" in mode else \
                    "rail" if "rail" in mode else mode or None
                k = f"taic:{d}:{title}"[:200]
                if k in seen:
                    continue
                seen.add(k)
                events.append(("NZL", k, "transport", sub, str(title), d, None, prec, None, None,
                               num(pick(r, "fatalities", "deaths")), None, None, None, pick(r, "url", "link"), "TAIC inquiry"))
        if not events:
            raise ConnectorError(f"taic_inquiries: no dated inquiries read from {raw_dir}")
        self.events_query = stage_events(con, self.source_id, vintage, events, set())
        return NO_ROWS


class TransportCurated(Connector):
    source_id = "transport_curated"
    frozen = True
    stage_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return str(catalogue.transport().get("checked_until", fetched_at.year))

    def release_from_files(self, files: list[Path]) -> str | None:
        return self.default_release(datetime.now())

    def download(self, raw_dir: Path, release: str) -> str:
        (raw_dir / "transport_events.json").write_text(json.dumps(catalogue.transport().get("events", []), indent=1, default=str),
                                                       encoding="utf-8")
        return "hand-checked lists in worldmodel_contract transport.yaml"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "transport_events.json"
        items = json.loads(p.read_text(encoding="utf-8")) if p.exists() else catalogue.transport().get("events", [])
        events = []
        for i, e in enumerate(items):
            parts = [int(x) for x in str(e["start"]).split("-")]
            start, prec = make_date(*parts)
            end = None
            if e.get("end"):
                eparts = [int(x) for x in str(e["end"]).split("-")]
                end, _ = make_date(*eparts)
                if len(eparts) == 1:
                    end = date(eparts[0], 12, 31)
            for ent in e["countries"]:
                events.append((ent, f"transport:{i}:{ent}", e.get("kind", "infrastructure"), e.get("subkind"), e["title"],
                               start, end, prec, None, None, e.get("deaths"), None, None, e.get("place"), e.get("url"), e.get("detail")))
        self.events_query = stage_events(con, self.source_id, vintage, events, set())
        return NO_ROWS
