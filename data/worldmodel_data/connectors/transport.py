"""Transport: ports, shipping, chokepoints, airports and accidents (version 4, PR 4).

portwatch
    IMF PortWatch (CC BY 4.0) through its public ArcGIS services: about 2,000 ports
    with their traffic, about 28 chokepoints (Suez, Panama, Hormuz, Malacca, Cook
    Strait ...), daily transits through each chokepoint, daily port calls by ship type
    and estimated import and export tonnes for each port (from 2019, days with calls
    only, about 3 million rows, kept as one gzipped CSV a year), the disasters PortWatch
    tracks with the ports they reached, the connections between ports (sailing days and
    capacity at risk) and a line about each big port. Files are kept per year, so a
    weekly refresh fetches only this year and last. Port calls and tonnes add up to
    country figures; a month when transits through a chokepoint fall by 40% or more
    against the two years before becomes an event.
nyfed_gscpi
    The New York Fed's Global Supply Chain Pressure Index, monthly from 1997 (one Excel
    file, sometimes in the old .xls format under an .xlsx name).
unctad_port_calls
    UNCTAD's port call statistics: median days ships spend in port, by country and kind
    of ship, yearly from 2018 (a .7z bulk download holding one CSV).
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
import gzip
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
from worldmodel_data.connectors.events_common import (
    EMPTY_OBSERVATIONS,
    make_date,
    stage_events,
)
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.tabular import (
    Rows,
    entity_for,
    indicator,
    key,
    num,
    xlsx_rows,
)

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


GEO_COLUMNS = (("layer_id", "VARCHAR"), ("feature_id", "VARCHAR"), ("name", "VARCHAR"), ("rank", "INTEGER"),
               ("props", "VARCHAR"), ("countries", "VARCHAR"), ("west", "DOUBLE"), ("south", "DOUBLE"),
               ("east", "DOUBLE"), ("north", "DOUBLE"), ("geojson", "VARCHAR"))


def insert_by_file(con: duckdb.DuckDBPyConnection, table: str, out: list[tuple]) -> None:
    """Rows into a geo table by way of a JSON lines file (executemany takes minutes for 100,000)."""
    import os
    import tempfile

    names = [c for c, _ in GEO_COLUMNS]
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="wm-geo-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(dict(zip(names, r)), ensure_ascii=False, separators=(",", ":")) + "\n")
        spec = "{" + ", ".join(f"'{c}': '{t}'" for c, t in GEO_COLUMNS) + "}"
        con.execute(f"INSERT INTO {table} SELECT * FROM read_json(?, format = 'newline_delimited', columns = {spec}, "
                    "maximum_object_size = 1073741824)", [path.replace("\\", "/")])
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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
    con.execute(f"CREATE TABLE {table} ({', '.join(f'{c} {t}' for c, t in GEO_COLUMNS)})")
    if len(out) > 2000:  # many rows (rivers): through a file, far quicker than one insert a row
        insert_by_file(con, table, out)
    elif out:
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


# Daily port fields kept, in order: PortWatch name -> our column
PORT_DAY_FIELDS = (("portcalls", "calls"), ("portcalls_container", "container"), ("portcalls_dry_bulk", "dry_bulk"),
                   ("portcalls_general_cargo", "general_cargo"), ("portcalls_roro", "roro"), ("portcalls_tanker", "tanker"),
                   ("import", "import_t"), ("export", "export_t"))
LINK_FIELDS = (("from_portid", "from_port"), ("to_portid", "to_port"), ("average_transit_days", "transit_days"),
               ("daily_capacity_at_risk", "capacity_at_risk"), ("relative_capacity_at_risk", "share_at_risk"))
HAZARDS = {"TC": "cyclone", "EQ": "earthquake", "FL": "flood", "DR": "drought", "VO": "volcano", "WF": "wildfire",
           "TS": "tsunami", "OT": "other"}
BIG_PAGE = 32000  # rows a page with resultType=standard (the services' standard limit)


def write_csv_gz(path: Path, header: list[str], rows) -> int:
    """Rows into a gzipped CSV; the number written."""
    n = 0
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])
            n += 1
    return n


def read_csv_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _day(v) -> date | None:
    return _epoch_day(int(v) if isinstance(v, str) and v.isdigit() else v)


class PortWatch(Connector):
    source_id = "portwatch"
    switch = "transport_ports_fetch"
    fetch_every_days = 7
    keeps_files = True  # earlier years stay; only this year and last are fetched again
    keep_vintages = 3   # each vintage carries every earlier year, so older ones are not needed
    gap = 1.0
    stage_version = 2
    fetch_version = 2   # daily calls at every port by ship type, disruptions, connections between ports

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def _query(self, service: str, q: dict, dest: Path) -> dict:
        url = f"{PORTWATCH}/{service}/FeatureServer/0/query?{urlencode(q)}"
        self.get(url, dest, cached=False)
        body = json.loads(dest.read_text(encoding="utf-8"))
        if "error" in body:
            dest.unlink(missing_ok=True)
            raise ConnectorError(f"portwatch: {service} answered {body['error'].get('message') or body['error']}")
        return body

    def _pages(self, service: str, params: dict, stem: Path, big: bool = False) -> int:
        """Save every page of an ArcGIS query as <stem>_<n>.json; the number of features.
        big: ask for the services' standard page of 32,000 rows (no shapes) instead of 1,000."""
        n, offset, page = 0, 0, 0
        size = BIG_PAGE if big else PW_PAGE
        while page < 400:
            q = {"f": "json", "resultOffset": offset, "resultRecordCount": size, **params}
            if big:
                q.update(resultType="standard", returnGeometry="false")
            dest = stem.parent / f"{stem.name}_{page:03d}.json"
            body = self._query(service, q, dest)
            got = len(body.get("features") or [])
            n += got
            if not got or (got < size and not body.get("exceededTransferLimit")):
                break
            offset += got
            page += 1
            time.sleep(self.gap)
        return n

    def _table(self, service: str, where: str, fields: tuple[tuple[str, str], ...], dest: Path, order: str = "ObjectId") -> int:
        """A big table fetched in pages of 32,000 rows straight into one gzipped CSV (the JSON pages
        are dropped once read): columns named by `fields` (theirs -> ours)."""
        tmp = dest.parent / f"_{dest.name.split('.')[0]}"
        n = self._pages(service, {"where": where, "outFields": ",".join(f for f, _ in fields), "orderByFields": order},
                        tmp, big=True)
        pages = sorted(dest.parent.glob(f"{tmp.name}_*.json"))
        written = write_csv_gz(dest, [o for _, o in fields],
                               ([a.get(f) for f, _ in fields] for a in pw_features(pages)))
        for p in pages:
            p.unlink(missing_ok=True)
        log.info("portwatch: %s rows of %s into %s", written, service, dest.name)
        return n

    def download(self, raw_dir: Path, release: str) -> str:
        today = date.today()
        self._pages("PortWatch_ports_database", {"where": "1=1", "outFields": "*"}, raw_dir / "ports_db")
        self._pages("PortWatch_chokepoints_database", {"where": "1=1", "outFields": "*"}, raw_dir / "chokepoints_db")
        self._pages("portsfacts", {"where": "1=1", "outFields": "portid,ISO3,portfact"}, raw_dir / "portfacts", big=True)
        self._pages("portwatch_disruptions_database", {
            "where": "1=1", "outFields": "eventid,eventtype,eventname,alertlevel,country,fromdate,todate,severitytext,lat,long,"
                                         "affectedports,n_affectedports", "returnGeometry": "false"}, raw_dir / "disruptions")
        self._pages("disruptions_with_ports", {"where": "1=1", "outFields": "portid,eventid,distance_km",
                                               "returnGeometry": "false"}, raw_dir / "disruption_ports")
        prev = self.last_vintage_dir(raw_dir)
        # Connections between ports change slowly: read again in the first week of each month.
        if not (prev and (prev / "port_links.csv.gz").exists()) or today.day <= 7:
            self._table("spillovers_port_level_impact", "1=1", LINK_FIELDS, raw_dir / "port_links.csv.gz")
        for year in range(2019, today.year + 1):
            done = year < today.year - 1
            if not (done and prev and list(prev.glob(f"chokepoints_{year}_*.json"))):
                self._pages("Daily_Chokepoints_Data", {"where": f"year={year}",
                                                        "outFields": "date,portid,portname,n_total,n_tanker,n_container,n_dry_bulk,n_cargo,capacity",
                                                        "orderByFields": "ObjectId"}, raw_dir / f"chokepoints_{year}")
            if not (done and prev and (prev / f"ports_daily_{year}.csv.gz").exists()):
                self._table("Daily_Ports_Data", f"year={year} AND portcalls>0", (("date", "day"), ("portid", "port_id"),
                                                                                  *PORT_DAY_FIELDS),
                            raw_dir / f"ports_daily_{year}.csv.gz")
        return PORTWATCH

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        ports = pw_features(sorted(raw_dir.glob("ports_db_*.json")))
        chokes = pw_features(sorted(raw_dir.glob("chokepoints_db_*.json")))
        if not ports and not chokes:
            raise ConnectorError(f"portwatch: no ports_db or chokepoints_db pages in {raw_dir}")
        iso_of = {a.get("portid"): (a.get("ISO3") or "").upper() for a in ports}
        # Daily transits through each chokepoint
        daily: dict[tuple[str, date], tuple] = {}
        for f in sorted(raw_dir.glob("chokepoints_2*.json")):
            for a in pw_features([f]):
                d = _day(a.get("date"))
                cid = a.get("portid")
                if d and cid and num(a.get("n_total")) is not None:
                    daily[(cid, d)] = (cid, a.get("portname"), d, num(a.get("n_total")), num(a.get("n_tanker")),
                                       num(a.get("n_container")), num(a.get("n_dry_bulk")), num(a.get("n_cargo")),
                                       num(a.get("capacity")))
        con.execute("CREATE TABLE ck (chokepoint_id VARCHAR, name VARCHAR, day DATE, transits DOUBLE, tankers DOUBLE, "
                    "container DOUBLE, dry_bulk DOUBLE, cargo DOUBLE, capacity DOUBLE)")
        if daily:
            con.executemany("INSERT INTO ck VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", list(daily.values()))
        # Daily calls at each port by ship type (years with a daily file), else the monthly sums
        # saved before daily files were kept. Read by DuckDB: there are millions of rows.
        con.execute("CREATE TABLE piso (port_id VARCHAR, country_code VARCHAR)")
        if iso_of:
            con.executemany("INSERT INTO piso VALUES (?, ?)", list(iso_of.items()))
        cols = ", ".join(f"{o} DOUBLE" for _, o in PORT_DAY_FIELDS)
        con.execute(f"CREATE TABLE pd (port_id VARCHAR, country_code VARCHAR, day DATE, {cols})")
        files = sorted(raw_dir.glob("ports_daily_*.csv.gz"))
        if files:
            types = {"day": "VARCHAR", "port_id": "VARCHAR", **{o: "DOUBLE" for _, o in PORT_DAY_FIELDS}}
            con.execute(f"""
                INSERT INTO pd
                SELECT r.port_id, coalesce(i.country_code, ''), r.d, {', '.join(f'r.{o}' for _, o in PORT_DAY_FIELDS)}
                FROM (SELECT *, try_cast(left(day, 10) AS DATE) AS d FROM read_csv(?, header = true, columns = {types!r},
                      filename = true)) r
                LEFT JOIN piso i USING (port_id)
                WHERE r.d IS NOT NULL AND r.port_id <> '' AND r.calls > 0
                QUALIFY row_number() OVER (PARTITION BY r.port_id, r.d ORDER BY r.filename DESC) = 1""",
                        [[f.as_posix() for f in files]])
        daily_years = {r[0] for r in con.execute("SELECT DISTINCT year(day) FROM pd").fetchall()}
        monthly: dict[tuple[str, int, int], list] = {
            (r[0], r[2], r[3]): list(r) for r in con.execute(
                "SELECT port_id, any_value(country_code), year(day)::INTEGER, month(day)::INTEGER, sum(calls), "
                "sum(import_t), sum(export_t) FROM pd GROUP BY port_id, year(day), month(day)").fetchall()}
        for f in sorted(raw_dir.glob("ports_2*.json")):
            for a in pw_features([f]):
                y, m, pid = num(a.get("year")), num(a.get("month")), a.get("portid")
                if y and m and pid and int(y) not in daily_years:
                    monthly[(pid, int(y), int(m))] = [pid, (a.get("ISO3") or "").upper(), int(y), int(m),
                                                      num(a.get("calls")), num(a.get("imports")), num(a.get("exports"))]
        con.execute("CREATE TABLE pt (port_id VARCHAR, country_code VARCHAR, year INTEGER, month INTEGER, calls DOUBLE, "
                    "import_t DOUBLE, export_t DOUBLE)")
        if monthly:
            con.executemany("INSERT INTO pt VALUES (?, ?, ?, ?, ?, ?, ?)", [tuple(v) for v in monthly.values()])
        # Connections between ports
        links = []
        lf = raw_dir / "port_links.csv.gz"
        if lf.exists():
            for r in read_csv_gz(lf):
                if r.get("from_port") and r.get("to_port"):
                    links.append((r["from_port"], r["to_port"], num(r.get("transit_days")), num(r.get("capacity_at_risk")),
                                  num(r.get("share_at_risk"))))
        con.execute("CREATE TABLE pl (from_port VARCHAR, to_port VARCHAR, transit_days DOUBLE, capacity_at_risk DOUBLE, "
                    "share_at_risk DOUBLE)")
        if links:
            con.executemany("INSERT INTO pl VALUES (?, ?, ?, ?, ?)", links)
        # Disruptions and the ports they reached
        reached: dict[str, list[tuple[str, float | None]]] = defaultdict(list)
        for a in pw_features(sorted(raw_dir.glob("disruption_ports_*.json"))):
            if a.get("eventid") is not None and a.get("portid"):
                reached[str(a["eventid"])].append((a["portid"], num(a.get("distance_km"))))
        dis = []
        for a in pw_features(sorted(raw_dir.glob("disruptions_*.json"))):
            eid = a.get("eventid")
            start = _day(a.get("fromdate"))
            if eid is None or not start:
                continue
            eid = str(eid)
            end = _day(a.get("todate")) or start
            ports_hit = reached.get(eid) or [(p.strip(), None) for p in str(a.get("affectedports") or "").split(";") if p.strip()]
            first_iso = next((iso_of.get(p) for p, _ in ports_hit if iso_of.get(p)), None)
            ent = iso3_of(first_iso) if first_iso else iso3_of(a.get("country"))
            base = (eid, a.get("eventname"), HAZARDS.get(str(a.get("eventtype") or "").upper(), "other"),
                    (a.get("alertlevel") or "").lower() or None, ent, start, max(end, start),
                    num(a.get("lat")), num(a.get("long")), a.get("severitytext"))
            for p, dist in ports_hit or [("", None)]:
                dis.append((base[0], p, *base[1:], dist))
        con.execute("CREATE TABLE pdis (event_id VARCHAR, port_id VARCHAR, name VARCHAR, hazard VARCHAR, alert VARCHAR, "
                    "country_code VARCHAR, start_date DATE, end_date DATE, lat DOUBLE, lon DOUBLE, severity VARCHAR, "
                    "distance_km DOUBLE)")
        if dis:
            con.executemany(f"INSERT INTO pdis VALUES ({', '.join('?' * 12)})", list({(d[0], d[1]): d for d in dis}.values()))
        self.history_queries = {"chokepoint_traffic": "SELECT * FROM ck", "port_traffic": "SELECT * FROM pt",
                                "port_daily": "SELECT * FROM pd", "port_links": "SELECT * FROM pl",
                                "port_disruptions": "SELECT * FROM pdis"}
        # Layers: ports sized by ships a year (with their ship types and a line about them), chokepoints by transits
        facts = {a.get("portid"): a.get("portfact") for a in pw_features(sorted(raw_dir.glob("portfacts_*.json")))
                 if a.get("portid") and a.get("portfact")}
        months_in = defaultdict(set)
        for (pid, y, m) in monthly:
            months_in[y].add(m)
        last_full = max((y for (_, y, _m) in monthly), default=0)
        full_year = max((y for y, ms in months_in.items() if len(ms) == 12), default=last_full)
        per_port = defaultdict(float)
        for (pid, y, m), r in monthly.items():
            if y == full_year and r[4]:
                per_port[pid] += r[4]
        types = {r[0]: list(r[1:]) for r in con.execute(
            "SELECT port_id, sum(container), sum(dry_bulk), sum(general_cargo), sum(roro), sum(tanker) FROM pd "
            "WHERE year(day) = ? GROUP BY 1", [full_year]).fetchall()}
        pfeats = []
        for a in ports:
            lat, lon = num(a.get("lat")), num(a.get("lon"))
            if lat is None or lon is None:
                continue
            pid = a.get("portid")
            props = {"id": pid, "name": a.get("portname") or "Port", "country": (a.get("ISO3") or "").upper() or None,
                     "calls": round(per_port.get(pid, 0)) or num(a.get("vessel_count_total")),
                     "year": full_year or None, "top": a.get("industry_top1"),
                     "imp_share": num(a.get("share_country_maritime_import")),
                     "exp_share": num(a.get("share_country_maritime_export"))}
            if facts.get(pid):
                props["fact"] = facts[pid]
            t = types.get(pid)
            if t and sum(x or 0 for x in t):
                t = [x or 0 for x in t]
                props["mix"] = {k: round(100 * v / sum(t)) for k, v in zip(("container", "dry_bulk", "general_cargo", "roro",
                                                                             "tanker"), t) if v}
            pfeats.append(feature({"type": "Point", "coordinates": [lon, lat]}, props))
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
        log.info("portwatch: %s ports, %s chokepoints, %s chokepoint days, %s port days, %s port months, %s links, "
                 "%s disruptions, %s events", len(pfeats), len(cfeats), len(daily),
                 con.execute("SELECT count(*) FROM pd").fetchone()[0], len(monthly), len(links), len(dis), len(events))
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- NY Fed supply chain pressure
GSCPI_URL = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"


def sheet_rows(path: Path) -> dict[str, list[list]]:
    """Every sheet of an Excel file as rows of cells, old .xls or new .xlsx (whatever its name says)."""
    head = path.read_bytes()[:8]
    if head.startswith(b"\xd0\xcf\x11\xe0"):  # the old binary format, even when named .xlsx
        import xlrd

        book = xlrd.open_workbook(str(path))
        out = {}
        for sh in book.sheets():
            rows = []
            for i in range(sh.nrows):
                row = []
                for c in sh.row(i):
                    if c.ctype == xlrd.XL_CELL_DATE:
                        try:
                            row.append(xlrd.xldate.xldate_as_datetime(c.value, book.datemode))
                        except Exception:  # noqa: BLE001
                            row.append(c.value)
                    else:
                        row.append(c.value)
                rows.append(row)
            out[sh.name] = rows
        return out
    from openpyxl import load_workbook

    with open(path, "rb") as fh:
        wb = load_workbook(fh, read_only=True, data_only=True)
        try:
            return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
        finally:
            wb.close()


def _month_of(v) -> date | None:
    if isinstance(v, datetime):
        return date(v.year, v.month, 1)
    if isinstance(v, date):
        return date(v.year, v.month, 1)
    s = str(v or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%b-%Y", "%b %Y", "%Y-%m"):
        try:
            d = datetime.strptime(s[:11].strip(), fmt)
            return date(d.year, d.month, 1)
        except ValueError:
            continue
    return None


def gscpi_points(path: Path) -> list[tuple[date, float]]:
    """Month and index value from the GSCPI download: the sheet with the most rows that hold
    a date and then a number (the monthly data sheet)."""
    best: list[tuple[date, float]] = []
    for rows in sheet_rows(path).values():
        got = {}
        for r in rows:
            cells = [c for c in r if c not in (None, "")]
            if len(cells) < 2:
                continue
            m = _month_of(cells[0])
            v = num(cells[1])
            if m and v is not None and -10 < v < 15 and 1990 <= m.year <= 2100:
                got[m] = v
        if len(got) > len(best):
            best = sorted(got.items())
    return best


class NYFedGSCPI(Connector):
    source_id = "nyfed_gscpi"
    switch = "transport_ports_fetch"
    fetch_every_days = 7

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(GSCPI_URL, raw_dir / "gscpi_data.xlsx")
        return GSCPI_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        from worldmodel_data.connectors.markets import DatedRows

        out = DatedRows()
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() in (".xlsx", ".xls"):
                for m, v in gscpi_points(f):
                    out.add("iso3", "world", "gscpi", m, round(v, 3), freq="M")
        if not len(out):
            raise ConnectorError(f"nyfed_gscpi: no monthly values found in {raw_dir}")
        self.listed_indicators = [
            indicator("gscpi", "Global supply chain pressure (NY Fed)",
                      "How stretched world supply chains are, in standard deviations from the average since 1997 "
                      "(0 is normal, above 1 is high). Built from shipping and air freight costs and delivery times, "
                      "backlogs and stocks in purchasing managers' surveys across seven big economies.",
                      "standard deviations", "trade", self.source_id, "GSCPI", decimals=2, frequency="M",
                      bounds=(-10, 15)),
        ]
        return out.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- UNCTAD time in port
UNCTAD_PORTCALLS = "https://unctadstat-api.unctad.org/bulkdownload/US.PortCalls/US_PortCalls"
PORT_TIME = {"all": ("port_time_days", "Time ships spend in port (median days)"),
             "container": ("port_time_container_days", "Time container ships spend in port (median days)"),
             "dry bulk": ("port_time_dry_bulk_days", "Time dry bulk ships spend in port (median days)"),
             "liquid bulk": ("port_time_liquid_bulk_days", "Time tankers spend in port (median days)")}


def unpack_7z(path: Path) -> dict[str, bytes]:
    """The files in a .7z archive (UNCTADstat bulk downloads), or the file itself if it is not one."""
    data = path.read_bytes()
    if not data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return {path.name: data}
    import tempfile

    import py7zr

    with tempfile.TemporaryDirectory() as tmp, py7zr.SevenZipFile(path, "r") as z:
        z.extractall(path=tmp)
        return {p.name: p.read_bytes() for p in Path(tmp).rglob("*") if p.is_file()}


def market_kind(label: str) -> str | None:
    s = str(label or "").lower()
    if s.startswith("all"):
        return "all"
    if "container" in s:
        return "container"
    if "dry bulk" in s:
        return "dry bulk"
    if "liquid bulk" in s:
        return "liquid bulk"
    return None


def port_time_rows(text: str) -> list[tuple[str, str, int, float]]:
    """(economy code, economy label, year, median days) by kind of ship, from UNCTAD's
    port calls table, wide (one column per measure) or long (Indicator and Value)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = [key(c) for c in rows[0]]

    def col(*names: str, exact: bool = False) -> int | None:
        for n in names:
            for i, h in enumerate(head):
                if (h == n) if exact else (n in h and "footnote" not in h and "missing" not in h):
                    return i
        return None
    y = col("year", exact=True)
    code = col("economy", exact=True)
    label = col("economylabel")
    market = col("commercialmarketlabel", "marketlabel")
    value = col("mediantimeinport")
    ind, val = col("indicatorlabel"), col("value", exact=True)
    out = []
    for r in rows[1:]:
        if y is None or market is None or len(r) < len(head):
            continue
        kind = market_kind(r[market])
        if kind is None:
            continue
        if value is not None:
            v = num(r[value])
        elif ind is not None and val is not None and "time in port" in r[ind].lower():
            v = num(r[val])
        else:
            continue
        yr = num(r[y])
        if v is None or yr is None:
            continue
        out.append((r[code] if code is not None else "", r[label] if label is not None else "", int(yr), v, kind))
    return out


class UNCTADPortCalls(Connector):
    source_id = "unctad_port_calls"
    switch = "transport_ports_fetch"
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(UNCTAD_PORTCALLS, raw_dir / "US_PortCalls.7z")
        return UNCTAD_PORTCALLS

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        missed: set[str] = set()
        for f in sorted(raw_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in (".7z", ".csv", ""):
                continue
            for name, data in unpack_7z(f).items():
                if not name.lower().endswith(".csv") and f.suffix:
                    continue
                for code, label, year, v, kind in port_time_rows(data.decode("utf-8-sig", errors="replace")):
                    ent = "world" if label.strip().lower() == "world" else (entity_for("m49", code) if code else None)
                    if not ent:
                        missed.add(label)
                        continue
                    rows.add("iso3", ent, PORT_TIME[kind][0], year, v)
        if not len(rows):
            raise ConnectorError(f"unctad_port_calls: no median time in port found in {raw_dir}")
        if missed:
            log.info("unctad_port_calls: %s groups or economies not matched (%s ...)", len(missed), ", ".join(sorted(missed)[:8]))
        self.listed_indicators = [
            indicator(iid, name, "Median time a ship of this kind spends in the country's ports on each call, in days "
                      "(UNCTAD, from MarineTraffic ship tracking). Longer stays usually mean slower handling or queues; "
                      "they also depend on the cargo and the ships.", "days", "trade", self.source_id, kind,
                      decimals=2, bounds=(0, 60))
            for kind, (iid, name) in PORT_TIME.items()]
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
    stage_version = 2  # 2: only the all-goods, all-packaging total (the table also splits by type of goods and container)

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = EUROSTAT.format(code="iww_go_atygo", query=urlencode({"format": "JSON", "lang": "EN", "unit": "THS_T", "tra_cov": "TOTAL",
                                                                  "nst07": "TOTAL", "typpack": "TOTAL"}))
        self.get(url, raw_dir / "eurostat_iww_go_atygo.json")
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "eurostat_iww_go_atygo.json"
        if not p.exists():
            raise ConnectorError(f"eurostat_waterways: no eurostat_iww_go_atygo.json in {raw_dir}")
        rows = Rows()
        for cell, v in jsonstat_rows(json.loads(p.read_text(encoding="utf-8"))):
            ent, year = eu_entity(cell.get("geo") or ""), num(cell.get("time"))
            # The table splits the total by type of goods (nst07) and by container (typpack), and
            # earlier downloads asked for every split: keep only the cell that is the total of each.
            if ent and year is not None and all(cell.get(d) in (None, "TOTAL") for d in ("tra_cov", "nst07", "typpack")):
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
