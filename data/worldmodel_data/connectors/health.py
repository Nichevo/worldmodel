"""Hospitals from more lists than Wikidata, to fill the Hospitals map layer where Wikidata
knows only the famous ones (China, India, Indonesia, Brazil...). Each source stores its own
map layer (hospitals_<source>); the build merges them with Wikidata's into the one Hospitals
layer (worldmodel_data.hospitals), counting a hospital once where two lists have it.

healthsites_osm
    OpenStreetMap's hospitals (amenity=hospital or healthcare=hospital), as packaged by
    healthsites.io on the Humanitarian Data Exchange: one GeoJSON or CSV per country, keyless,
    ODbL. Every country HDX has a "<country>-healthsites" dataset for; beds where mapped.
overture_hospitals
    Overture Maps places whose category is hospital (CDLA Permissive 2.0 / ODbL), read straight
    from Overture's public GeoParquet files: only the parts of the files that cover the countries
    in Settings (hospitals_overture_countries) and only the columns needed. The files are sorted by
    place, so a country costs the parts of them that cover its box: South and East Asia together
    about 1.5 GB (tried November 2026: 49,000 hospitals in India, but only 1,300 in China).
    Everything read inside the boxes is kept, neighbours included. Places below the confidence in
    Settings are left out (the hospital category also holds clinics and offices in hospitals).
national_hospitals
    Official lists with locations: Brazil's CNES register (hospitals only), Canada's Open
    Database of Healthcare Facilities (hospitals only), the WHO's list of public health
    facilities in sub-Saharan Africa (hospitals only), and any CSV you save in
    var/manual/national_hospitals/ with name, lat and lon columns (beds and country if known),
    for lists such as a province's top-grade hospitals.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_contract import health as spec
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.layers import collection

log = logging.getLogger(__name__)


def _settings() -> dict:
    from worldmodel_contract.local import load_settings
    from worldmodel_data.config import paths
    try:
        return load_settings(paths().home)
    except Exception:  # noqa: BLE001 - tests and first runs: the defaults
        from worldmodel_contract.local import DEFAULT_SETTINGS
        return dict(DEFAULT_SETTINGS)


UNNAMED = "Hospital (no name given)"


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return x if x == x else None


def hospital_feature(name: str, lat: float, lon: float, **props) -> dict | None:
    """One dot of a source's hospitals layer: name, then whatever else is known (country as
    ISO3 or ISO2, beds, kind, link)."""
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    name = re.sub(r"\s+", " ", str(name or "")).strip() or UNNAMED
    beds = _num(props.pop("beds", None))
    if beds is not None and 0 < beds < 20_000:
        props["beds"] = int(beds)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
            "properties": {"name": name, **{k: v for k, v in props.items() if v not in (None, "")}}}


def layer_of(source: str, feats: list[dict]) -> dict:
    s = spec.SOURCES[source]
    return {"layer_id": spec.layer_id(source), "name": f"Hospitals ({s['short']})",
            "description": f"Hospitals listed by {s['short']}; merged into the Hospitals layer by the build.",
            "kind": "point", "feature_count": len(feats), "geojson": collection(feats)}


# ----------------------------------------------------------------------------- Overture
OVERTURE = "https://overturemaps-us-west-2.s3.amazonaws.com"
OVERTURE_COLUMNS = ("names", "bbox")  # read only for row groups with a hospital in them


class HttpRange(io.RawIOBase):
    """A remote file read with HTTP Range requests, so pyarrow fetches only the footer and the
    column chunks it needs."""

    def __init__(self, client: httpx.Client, url: str, size: int):
        self.client, self.url, self.size, self.pos, self.fetched = client, url, size, 0, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, b) -> int:
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        for attempt in range(4):
            try:
                r = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"}, timeout=120)
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        data = r.content[:n]
        b[:len(data)] = data
        self.pos += len(data)
        self.fetched += len(data)
        return len(data)


def _s3_list(client: httpx.Client, prefix: str, delimiter: bool) -> tuple[list[str], list[tuple[str, int]]]:
    r = client.get(f"{OVERTURE}/", params={"list-type": "2", "prefix": prefix, **({"delimiter": "/"} if delimiter else {})},
                   timeout=60)
    r.raise_for_status()
    prefixes = re.findall(r"<Prefix>([^<]+)</Prefix>", r.text)[1:] if delimiter else []
    files = [(k, int(s)) for k, s in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", r.text)]
    return prefixes, files


def overture_release(client: httpx.Client) -> str:
    prefixes, _ = _s3_list(client, "release/", True)
    found = sorted(p.split("/")[1] for p in prefixes if re.fullmatch(r"release/\d{4}-\d{2}-\d{2}\.\d+/", p))
    if not found:
        raise ConnectorError("overture_hospitals: no Overture release listed")
    return found[-1]


def country_boxes(countries_geojson: Path, iso3s: set[str], min_deg2: float = 0.05) -> dict[str, list[tuple[float, ...]]]:
    """(west, south, east, north) of each sizeable polygon of each country, so Russia and Fiji
    across the date line give two boxes rather than one round the world."""
    data = json.loads(countries_geojson.read_text(encoding="utf-8"))
    out: dict[str, list[tuple[float, ...]]] = {}
    for f in data.get("features", []):
        p = f.get("properties") or {}
        iso = next((p.get(k) for k in ("ISO_A3", "ADM0_A3", "ISO_A3_EH") if p.get(k) in iso3s), None)
        if not iso:
            continue
        g = f.get("geometry") or {}
        polys = g.get("coordinates") or []
        if g.get("type") == "Polygon":
            polys = [polys]
        for poly in polys:
            xs = [pt[0] for pt in poly[0]]
            ys = [pt[1] for pt in poly[0]]
            box = (min(xs), min(ys), max(xs), max(ys))
            if (box[2] - box[0]) * (box[3] - box[1]) >= min_deg2:
                out.setdefault(iso, []).append(box)
    return out


def _overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def overture_rows(client: httpx.Client, release: str, boxes: list[tuple[float, ...]], min_conf: float) -> tuple[list[dict], int]:
    """Overture's hospital places inside any of the boxes: (rows, bytes fetched)."""
    import pyarrow.parquet as pq

    _, files = _s3_list(client, f"release/{release}/theme=places/type=place/", False)
    files = [(k, s) for k, s in files if k.endswith(".parquet")]
    if not files:
        raise ConnectorError(f"overture_hospitals: no place files in Overture release {release}")
    rows: list[dict] = []
    fetched = 0
    for key, size in files:
        src = HttpRange(client, f"{OVERTURE}/{key}", size)
        pf = pq.ParquetFile(io.BufferedReader(src, buffer_size=1 << 20))
        md = pf.metadata
        names = [md.row_group(0).column(j).path_in_schema for j in range(md.row_group(0).num_columns)]
        ix = {n: j for j, n in enumerate(names)}
        for g in range(md.num_row_groups):
            rg = md.row_group(g)
            try:
                st = [rg.column(ix[f"bbox.{k}"]).statistics for k in ("xmin", "ymin", "xmax", "ymax")]
                box = (st[0].min, st[1].min, st[2].max, st[3].max)
            except (KeyError, AttributeError):
                box = (-180, -90, 180, 90)
            if not any(_overlaps(box, b) for b in boxes):
                continue
            head = pf.read_row_group(g, columns=["basic_category", "confidence"]).to_pydict()
            hits = [i for i, (c, conf) in enumerate(zip(head["basic_category"], head["confidence"]))
                    if c == "hospital" and (conf or 0) >= min_conf]
            if not hits:
                continue
            t = pf.read_row_group(g, columns=list(OVERTURE_COLUMNS)).take(hits).to_pylist()
            for i, r in zip(hits, t):
                bb = r.get("bbox") or {}
                if bb.get("xmin") is None:
                    continue
                lon, lat = (bb["xmin"] + bb["xmax"]) / 2, (bb["ymin"] + bb["ymax"]) / 2
                if not any(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for b in boxes):
                    continue
                rows.append({"name": ((r.get("names") or {}).get("primary") or ""), "lat": round(lat, 6), "lon": round(lon, 6),
                             "confidence": round(head["confidence"][i] or 0, 3)})
        fetched += src.fetched
        log.info("overture_hospitals: %s read (%.0f MB so far), %s hospitals so far", key.rsplit("/", 1)[-1][:14],
                 fetched / 1e6, len(rows))
    return rows, fetched


class OvertureHospitals(Connector):
    source_id = "overture_hospitals"
    switch = "hospitals_overture_fetch"
    fetch_every_days = 180  # Overture puts out a release every month; hospitals change slowly and a read costs 1-2 GB

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_data.connectors.networks import countries_file, get_countries

        s = _settings()
        wanted = {c.strip().upper() for c in str(s.get("hospitals_overture_countries") or spec.OVERTURE_DEFAULT).split(",")
                  if c.strip()}
        if not wanted:
            raise ConnectorError("overture_hospitals: no countries chosen in Settings > Places (Overture hospitals: countries)")
        get_countries(raw_dir, self)
        cf = countries_file(raw_dir, self)
        if cf is None:
            raise ConnectorError("overture_hospitals: could not get Natural Earth's countries to find each country's box")
        by_country = country_boxes(cf, wanted)
        missing = sorted(wanted - set(by_country))
        if missing:
            log.warning("overture_hospitals: no outline for %s; left out", ", ".join(missing))
        ov = overture_release(self.client)
        rows, fetched = overture_rows(self.client, ov, [b for bs in by_country.values() for b in bs],
                                      float(s.get("hospitals_overture_confidence", 0.7)))
        self.downloaded_bytes += fetched
        with (raw_dir / "overture_hospitals.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["name", "lat", "lon", "confidence"])
            w.writeheader()
            w.writerows(rows)
        (raw_dir / "overture_release.txt").write_text(f"{ov}\n{','.join(sorted(by_country))}\n", encoding="utf-8")
        log.info("overture_hospitals: %s hospitals in %s countries from release %s (%.0f MB read)",
                 len(rows), len(by_country), ov, fetched / 1e6)
        return f"{OVERTURE}/release/{ov}/theme=places/type=place/"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        from worldmodel_data.connectors.networks import Grids, countries_file

        path = raw_dir / "overture_hospitals.csv"
        if not path.exists():
            raise ConnectorError(f"overture_hospitals: overture_hospitals.csv missing from {raw_dir}")
        cf = countries_file(raw_dir, self)
        grid = Grids(cf) if cf else None
        feats = []
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                lat, lon = _num(r.get("lat")), _num(r.get("lon"))
                if lat is None or lon is None:
                    continue
                # Every hospital read is kept, those of neighbours inside a chosen country's box too:
                # their part of the files was read anyway.
                f = hospital_feature(r.get("name"), lat, lon, country=grid.at(lon, lat) if grid else None,
                                     conf=_num(r.get("confidence")))
                if f:
                    feats.append(f)
        if not feats:
            raise ConnectorError("overture_hospitals: no hospitals read")
        self.layers = [layer_of("overture", feats)]
        log.info("overture_hospitals: %s hospitals", len(feats))
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- OpenStreetMap (healthsites.io on HDX)
HDX = "https://data.humdata.org/api/3/action"
HDX_ORG = "healthsites"
OSM_HOSPITAL = {"hospital"}


def hdx_country_files(client: httpx.Client) -> list[tuple[str, str, str]]:
    """(iso3, dataset name, CSV link) for every healthsites.io country dataset on HDX."""
    out, start = [], 0
    while True:
        r = client.get(f"{HDX}/package_search", params={"fq": f"organization:{HDX_ORG}", "rows": 500, "start": start}, timeout=120)
        r.raise_for_status()
        res = r.json().get("result") or {}
        got = res.get("results") or []
        for p in got:
            iso = next((g.get("name", "").upper() for g in p.get("groups") or [] if len(g.get("name", "")) == 3), "")
            csvs = [x for x in p.get("resources") or [] if str(x.get("format", "")).upper() == "CSV" and x.get("download_url")]
            if iso and csvs:
                out.append((iso, p.get("name", ""), csvs[0]["download_url"]))
        start += len(got)
        if not got or start >= int(res.get("count") or 0):
            return out


def osm_hospital_rows(path: Path) -> list[dict]:
    """Hospitals in one healthsites.io country CSV: amenity or healthcare is hospital."""
    out = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if not ({str(r.get("amenity") or "").strip().lower(), str(r.get("healthcare") or "").strip().lower()} & OSM_HOSPITAL):
                continue
            lon, lat = _num(r.get("X")), _num(r.get("Y"))
            if lon is None or lat is None:
                continue
            osm = f"{r.get('osm_type') or 'node'}/{str(r.get('osm_id') or '').strip(chr(34))}"
            out.append({"name": r.get("name"), "lat": lat, "lon": lon, "beds": r.get("beds"),
                        "id": f"osm:{osm}" if r.get("osm_id") else None,
                        "url": f"https://www.openstreetmap.org/{osm}" if r.get("osm_id") else None,
                        "operator": (r.get("operator_type") or "").strip() or None, "emergency": (r.get("emergency") or "").strip() or None})
    return out


class HealthsitesOSM(Connector):
    source_id = "healthsites_osm"
    switch = "hospitals_osm_fetch"
    fetch_every_days = 90  # healthsites.io refreshes its HDX files every three months

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        files = hdx_country_files(self.client)
        if not files:
            raise ConnectorError("healthsites_osm: no healthsites.io country files listed on HDX")
        got = 0
        for iso, name, url in files:
            try:
                self.get(url, raw_dir / f"{iso}.csv")
                got += 1
            except (ConnectorError, httpx.HTTPError) as exc:
                log.warning("healthsites_osm: %s skipped (%s)", name, exc)
        if not got:
            raise ConnectorError("healthsites_osm: every country file failed")
        log.info("healthsites_osm: %s of %s country files", got, len(files))
        return f"{HDX}/package_search?fq=organization:{HDX_ORG}"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        feats = []
        for f in sorted(raw_dir.glob("*.csv")):
            iso = f.stem.upper()
            if not re.fullmatch(r"[A-Z]{3}", iso):
                continue
            for r in osm_hospital_rows(f):
                ft = hospital_feature(r.pop("name"), r.pop("lat"), r.pop("lon"), country=iso, **r)
                if ft:
                    feats.append(ft)
        if not feats:
            raise ConnectorError(f"healthsites_osm: no hospitals read from {raw_dir}")
        self.layers = [layer_of("osm", feats)]
        log.info("healthsites_osm: %s hospitals", len(feats))
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- official national lists
CNES_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos.zip"
CNES_HOSPITAL_TYPES = {"5", "7", "15", "62"}  # general, specialised, mixed unit, day hospital
CNES_KINDS = {"5": "general hospital", "7": "specialised hospital", "15": "mixed unit", "62": "day hospital"}
AFRICA_URL = ("https://data.humdata.org/dataset/eb1ba830-9464-43c8-9370-28cee0c99f5d/resource/"
              "758d5c17-88f4-42b2-9d4b-4bfe32d4acf7/download/sub-saharan_health_facilities.xlsx")
AFRICA_FILE = "sub-saharan_health_facilities.xlsx"


def cnes_rows(zp: Path) -> list[dict]:
    """Brazil's hospitals (CNES unit types 5, 7, 15, 62) that are open and have a location."""
    out = []
    with zipfile.ZipFile(zp) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
        if name is None:
            return []
        with z.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
            for r in csv.DictReader(text, delimiter=";"):
                if str(r.get("TP_UNIDADE") or "").strip().lstrip("0") not in CNES_HOSPITAL_TYPES or (r.get("CO_MOTIVO_DESAB") or "").strip():
                    continue
                lat, lon = _num(r.get("NU_LATITUDE")), _num(r.get("NU_LONGITUDE"))
                if lat is None or lon is None:
                    continue
                out.append({"name": (r.get("NO_FANTASIA") or r.get("NO_RAZAO_SOCIAL") or "").title(), "lat": lat, "lon": lon,
                            "country": "BRA", "id": f"cnes:{(r.get('CO_CNES') or '').strip()}", "list": "CNES (Brazil)",
                            "kind": CNES_KINDS.get(str(r.get("TP_UNIDADE") or "").strip().lstrip("0"))})
    return out


def africa_rows(path: Path) -> list[dict]:
    """Hospitals in the sub-Saharan Africa public health facilities list (Maina et al. 2019)."""
    from worldmodel_data.connectors.transport import header_rows, pick, read_table

    out = []
    for r in header_rows(read_table(path), ("lat", "long")):
        kind = str(pick(r, "facilitytype", "type") or "")
        if "hospital" not in kind.lower():
            continue
        lat, lon = _num(pick(r, "lat", "latitude")), _num(pick(r, "long", "longitude", "lon"))
        out.append({"name": pick(r, "facilityname", "name"), "lat": lat, "lon": lon, "country": pick(r, "country"),
                    "kind": kind.strip(), "list": "WHO sub-Saharan Africa facilities"})
    return out


def own_list_rows(path: Path) -> list[dict]:
    """A list saved by hand: a CSV or Excel sheet with name, latitude and longitude columns
    (beds and country if known; the file name, for example 'CHN guangdong 3A.csv', can give
    the country as its first word)."""
    from worldmodel_data.connectors.transport import header_rows, pick, read_table

    first = re.split(r"[\s_\-]+", path.stem)[0].upper()
    out = []
    for r in header_rows(read_table(path), ("lat",)):
        lat = _num(pick(r, "lat", "latitude", "y"))
        lon = _num(pick(r, "lon", "lng", "long", "longitude", "x"))
        out.append({"name": pick(r, "name", "hospital", "facility", "title"), "lat": lat, "lon": lon,
                    "country": pick(r, "country", "iso3", "iso") or (first if re.fullmatch(r"[A-Z]{3}", first) else None),
                    "beds": pick(r, "beds", "bedcount"), "list": f"Your list ({path.name})"})
    return out


class NationalHospitals(Connector):
    """Brazil's CNES register and the WHO's sub-Saharan Africa list, fetched; any list you save
    in var/manual/national_hospitals is read as well (and kept from one fetch to the next)."""
    source_id = "national_hospitals"
    switch = "hospitals_national_fetch"
    fetch_every_days = 90
    keeps_files = True
    stage_version = 2  # 2: Brazil's unit type kept as the hospital's kind

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for url, name in ((CNES_URL, "cnes_estabelecimentos.zip"), (AFRICA_URL, AFRICA_FILE)):
            try:
                self.get(url, raw_dir / name)
                got += 1
            except (ConnectorError, httpx.HTTPError) as exc:
                log.warning("national_hospitals: %s skipped (%s)", name, exc)
        if not got:
            raise ConnectorError("national_hospitals: both lists failed to download")
        return "CNES (Brazil's health ministry) and the WHO sub-Saharan Africa list on HDX"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows: list[dict] = []
        for f in sorted(raw_dir.iterdir()):
            low = f.name.lower()
            try:
                if low == "cnes_estabelecimentos.zip":
                    rows += cnes_rows(f)
                elif low == AFRICA_FILE:
                    rows += africa_rows(f)
                elif f.suffix.lower() in (".csv", ".xlsx", ".txt") and low != "http_cache.json":
                    got = own_list_rows(f)
                    log.info("national_hospitals: %s hospitals in your list %s", len(got), f.name)
                    rows += got
            except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
                log.warning("national_hospitals: could not read %s (%s)", f.name, exc)
        feats = [ft for ft in (hospital_feature(r.pop("name"), r.pop("lat"), r.pop("lon"), **r) for r in rows) if ft]
        if not feats:
            raise ConnectorError(f"national_hospitals: no hospitals read from {raw_dir}")
        self.layers = [layer_of("national", feats)]
        log.info("national_hospitals: %s hospitals", len(feats))
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- official counts
WHO_GHO = "https://ghoapi.azureedge.net/api/DEVICES00"  # Total density per 100 000 population: Hospitals


class HospitalCounts(Connector):
    """How many hospitals each country has, to check the map layer against: the WHO's density
    of hospitals per 100,000 people (its 2013 survey) and counts typed in from national
    statistics (contract health.py OFFICIAL_COUNTS)."""
    source_id = "hospital_counts"
    switch = "hospitals_osm_fetch"
    fetch_every_days = 365

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        try:
            self.get(WHO_GHO, raw_dir / "who_devices00.json")
        except (ConnectorError, httpx.HTTPError) as exc:
            log.warning("hospital_counts: WHO figures skipped (%s); the typed-in counts are kept", exc)
        (raw_dir / "official_counts.json").write_text(json.dumps(spec.OFFICIAL_COUNTS), encoding="utf-8")
        return WHO_GHO

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        from worldmodel_data.connectors.base import sql_str
        from worldmodel_data.connectors.tabular import indicator

        rows: list[tuple] = []
        p = raw_dir / "who_devices00.json"
        if p.exists():
            for v in json.loads(p.read_text(encoding="utf-8")).get("value") or []:
                if v.get("SpatialDimType") == "COUNTRY" and v.get("NumericValue") is not None and v.get("TimeDim"):
                    rows.append(("who_hospitals_per_100k", v["SpatialDim"], f"{int(v['TimeDim'])}-01-01", float(v["NumericValue"])))
        counts = raw_dir / "official_counts.json"
        for iso, year, n, *_ in (json.loads(counts.read_text(encoding="utf-8")) if counts.exists() else spec.OFFICIAL_COUNTS):
            rows.append(("hospitals_official", iso, f"{year}-01-01", float(n)))
        if not rows:
            raise ConnectorError("hospital_counts: no figures read")
        con.execute("CREATE TABLE hosp_counts (ind VARCHAR, iso VARCHAR, d DATE, v DOUBLE)")
        con.executemany("INSERT INTO hosp_counts VALUES (?, ?, ?, ?)", rows)
        typed = "; ".join(f"{iso} {year}: {pub}" for iso, year, _, pub, _ in spec.OFFICIAL_COUNTS)
        self.listed_indicators = [
            indicator("who_hospitals_per_100k", "Hospitals per 100,000 people (WHO)",
                      "Density of hospitals per 100,000 people, from the WHO's 2013 survey of medical devices and facilities.",
                      "per 100,000 people", "health", self.source_id, "who_hospitals_per_100k", decimals=2, bounds=(0, 1000),
                      default_on=False),
            indicator("hospitals_official", "Hospitals (national statistics)",
                      f"Number of hospitals as counted by national statistics, typed in ({typed}).",
                      "hospitals", "health", self.source_id, "hospitals_official", decimals=0, bounds=(0, 1e6),
                      aggregation={"method": "sum"}, default_on=False)]
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, iso AS source_code, "
                "ind AS indicator_id, d AS period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, v AS value, 'E' AS status "
                "FROM hosp_counts")
