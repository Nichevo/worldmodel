"""Map overlays for understanding disasters: where the plates meet, the active faults,
volcanoes and large earthquakes. Each source stores one layer (layers.parquet), its
features as one GeoJSON FeatureCollection with coordinates rounded to about 100 m
and only the properties the map shows.

plates_bird
    Peter Bird's 2003 plate boundary model (PB2002), as GeoJSON from the
    fraxen/tectonicplates conversion on GitHub. 241 boundary lines.
gem_faults
    GEM Global Active Faults Database (harmonized GeoJSON, GitHub): about 13,700
    fault traces with their name, slip type and slip rate (mm a year).
gvp_volcanoes
    Smithsonian Global Volcanism Program, Volcanoes of the World: the Holocene
    volcanoes from its web feature service (GeoJSON), with type, last eruption
    and elevation. A CSV with the same columns (volcano_name, latitude, ...) can
    be loaded instead: worldmodel-data fetch gvp_volcanoes --from <file>.
usgs_earthquakes
    USGS earthquake catalogue (ComCat) through its FDSN event service: every
    earthquake of magnitude 6 or more since 1900, and those of 4.5 to 6 since
    SMALL_FROM (a file a year), with place, date and depth. Around New Zealand the
    smaller ones come from GeoNet's own catalogue instead (FDSN text, magnitude 3 to
    6, a file a year), which sees far more of them. Years before last year are kept
    from the previous vintage rather than fetched again.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import key, num

log = logging.getLogger(__name__)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _round(coords, places: int = 3):
    """Coordinates rounded, with repeated points along a line dropped."""
    if coords and isinstance(coords[0], (int, float)):
        return [round(c, places) for c in coords[:2]]
    out = [_round(c, places) for c in coords]
    if out and isinstance(out[0], list) and out[0] and isinstance(out[0][0], (int, float)):
        out = [p for i, p in enumerate(out) if i == 0 or p != out[i - 1]]
    return out


def feature(geometry: dict, props: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": geometry["type"], "coordinates": _round(geometry["coordinates"])},
            "properties": {k: v for k, v in props.items() if v not in (None, "")}}


def collection(features: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"), ensure_ascii=False)


def read_geojson(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [f for f in data.get("features", []) if f.get("geometry") and f["geometry"].get("coordinates")]


class _Layer(Connector):
    layer_id = ""
    layer_name = ""
    layer_description = ""
    kind = "line"
    url = ""
    file = ""

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(self.url, raw_dir / self.file)
        return self.url

    def features(self, raw_dir: Path) -> list[dict]:
        raise NotImplementedError

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        feats = self.features(raw_dir)
        if not feats:
            raise ConnectorError(f"{self.source_id}: no features read from {raw_dir}")
        self.layers = [{"layer_id": self.layer_id, "name": self.layer_name, "description": self.layer_description,
                        "kind": self.kind, "feature_count": len(feats), "geojson": collection(feats)}]
        return EMPTY_OBSERVATIONS


class PlatesBird(_Layer):
    source_id = "plates_bird"
    frozen = True  # a 2003 model
    layer_id, kind = "plate_boundaries", "line"
    layer_name = "Tectonic plate boundaries"
    layer_description = "Where the Earth's plates meet (Bird 2003): most large earthquakes and many volcanoes lie along them."
    url = "https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_boundaries.json"
    file = "PB2002_boundaries.json"

    def features(self, raw_dir: Path) -> list[dict]:
        files = sorted(raw_dir.glob("*.json")) + sorted(raw_dir.glob("*.geojson"))
        if not files:
            return []
        out = []
        for f in read_geojson(files[0]):
            p = f.get("properties") or {}
            name = p.get("Name") or ""
            out.append(feature(f["geometry"], {"name": f"Plate boundary {name}".strip(), "type": p.get("Type") or None}))
        return out


class GEMFaults(_Layer):
    source_id = "gem_faults"
    fetch_every_days = 180
    layer_id, kind = "active_faults", "line"
    layer_name = "Active faults"
    layer_description = "Faults that have moved in the last few hundred thousand years (GEM Global Active Faults Database)."
    url = "https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/master/geojson/gem_active_faults_harmonized.geojson"
    file = "gem_active_faults_harmonized.geojson"

    def features(self, raw_dir: Path) -> list[dict]:
        files = sorted(raw_dir.glob("*.geojson")) + sorted(raw_dir.glob("*.json"))
        if not files:
            return []
        out = []
        for f in read_geojson(files[0]):
            p = f.get("properties") or {}
            rate = re.match(r"\(?\s*(-?\d+(?:\.\d+)?)", str(p.get("net_slip_rate") or ""))
            out.append(feature(f["geometry"], {"name": p.get("name") or "Unnamed fault", "slip": p.get("slip_type"),
                                               "rate": float(rate.group(1)) if rate else None}))
        return out


class GVPVolcanoes(_Layer):
    source_id = "gvp_volcanoes"
    fetch_every_days = 90
    layer_id, kind = "volcanoes", "point"
    layer_name = "Volcanoes"
    layer_description = "Volcanoes active in the last 12,000 years, with their last known eruption (Smithsonian Global Volcanism Program)."
    url = ("https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows?service=WFS&version=2.0.0&request=GetFeature"
           "&typeName=GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes&outputFormat=application%2Fjson")
    file = "holocene_volcanoes.geojson"

    def features(self, raw_dir: Path) -> list[dict]:
        out = []
        for path in sorted(raw_dir.iterdir()):
            if path.suffix.lower() in (".geojson", ".json"):
                rows = [{key(k): v for k, v in (f.get("properties") or {}).items()} | {"_geom": f["geometry"]}
                        for f in read_geojson(path)]
            elif path.suffix.lower() == ".csv":
                with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
                    rows = [{key(k): v for k, v in r.items()} for r in csv.DictReader(fh)]
            else:
                continue
            for r in rows:
                geom = r.get("_geom")
                if not geom:
                    lat, lon = num(r.get("latitude")), num(r.get("longitude"))
                    if lat is None or lon is None:
                        continue
                    geom = {"type": "Point", "coordinates": [lon, lat]}
                last = r.get("lasteruptionyear")
                last = int(num(last)) if num(last) is not None else None
                out.append(feature(geom, {
                    "name": r.get("volcanoname") or "Volcano", "country": r.get("country"),
                    "type": r.get("primaryvolcanotype"), "last": last, "elevation": num(r.get("elevation")),
                    "url": f"https://volcano.si.edu/volcano.cfm?vn={int(num(r['volcanonumber']))}"
                    if num(r.get("volcanonumber")) is not None else None,
                }))
        return out


SMALL_FROM = 2016  # quakes below magnitude 6 from this year on (about 8,000 a year worldwide)
# GeoNet's area: New Zealand and its seas out to the Kermadecs (longitudes past 180 wrap to -180).
NZ_BOX = (-52.0, -28.0, 160.0, -174.0)


def in_nz_box(lon: float, lat: float) -> bool:
    s, n, w, e = NZ_BOX
    return s <= lat <= n and (lon >= w or lon <= e)


class USGSEarthquakes(_Layer):
    source_id = "usgs_earthquakes"
    fetch_every_days = 7
    keeps_files = True  # the yearly files of years already over are carried from the last vintage
    fetch_version = 2   # yearly files of smaller quakes, and GeoNet's around New Zealand
    stage_version = 2
    layer_id, kind = "earthquakes", "point"
    layer_name = "Earthquakes"
    layer_description = (f"Every earthquake of magnitude 6 or more since 1900 and of 4.5 or more since {SMALL_FROM} (USGS "
                         f"catalogue); around New Zealand of 3 or more since {SMALL_FROM} (GeoNet). Sized by magnitude.")
    url = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=1900-01-01&minmagnitude=6"
           "&orderby=time-asc&limit=20000&eventtype=earthquake")
    file = "earthquakes_m6.geojson"
    small_url = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime={y}-01-01&endtime={y1}-01-01"
                 "&minmagnitude=4.5&maxmagnitude=5.99&orderby=time-asc&limit=20000&eventtype=earthquake")
    nz_url = ("https://service.geonet.org.nz/fdsnws/event/1/query?format=text&starttime={y}-01-01&endtime={y1}-01-01"
              "&minmagnitude=3&maxmagnitude=5.99&eventtype=earthquake")

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(self.url, raw_dir / self.file)
        prev = self.last_vintage_dir(raw_dir)
        this = datetime.now(timezone.utc).year
        for y in range(SMALL_FROM, this + 1):
            for name, url in ((f"usgs_m45_{y}.geojson", self.small_url), (f"geonet_m3_{y}.txt", self.nz_url)):
                if y < this - 1 and prev is not None and (prev / name).is_file():
                    continue  # a year long over: keeps_files carries the last copy
                try:
                    self.get(url.format(y=y, y1=y + 1), raw_dir / name)
                except Exception as e:  # noqa: BLE001 - the big quakes still load without one year of small ones
                    log.warning("%s: %s not fetched (%s); the map goes without it for now", self.source_id, name, e)
        return self.url

    def features(self, raw_dir: Path) -> list[dict]:
        big = raw_dir / self.file
        if not big.is_file():  # a file loaded by hand under another name
            files = [f for f in sorted(raw_dir.glob("*.geojson")) + sorted(raw_dir.glob("*.json")) if not f.name.startswith("usgs_m45_")]
            big = files[0] if files else None
        out = self._usgs(big, small=False) if big else []
        for f in sorted(raw_dir.glob("usgs_m45_*.geojson")):
            out += self._usgs(f, small=True)
        for f in sorted(raw_dir.glob("geonet_m3_*.txt")):
            out += self._geonet(f)
        return out

    def _usgs(self, path: Path, small: bool) -> list[dict]:
        out = []
        for f in read_geojson(path):
            p = f.get("properties") or {}
            coords = f["geometry"]["coordinates"]
            mag = num(p.get("mag"))
            if small and (mag is None or mag >= 6 or in_nz_box(coords[0], coords[1])):
                continue  # 6+ are in the big file; around New Zealand GeoNet's own list is used
            t = p.get("time")
            # Not fromtimestamp: on Windows it fails (Errno 22) for times before 1970.
            when = (EPOCH + timedelta(milliseconds=t)).date().isoformat() if isinstance(t, (int, float)) else None
            out.append(feature({"type": "Point", "coordinates": coords[:2]}, {
                "id": f.get("id"), "name": p.get("title") or p.get("place") or "Earthquake", "mag": mag, "date": when,
                "depth": round(coords[2]) if len(coords) > 2 and coords[2] is not None else None,
                "tsunami": 1 if p.get("tsunami") else None, "url": p.get("url"),
            }))
        return out

    def _geonet(self, path: Path) -> list[dict]:
        """GeoNet's FDSN text: #EventID|Time|Latitude|Longitude|Depth/km|...|MagType|Magnitude|MagAuthor|EventLocationName|EventType"""
        out = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            c = [x.strip() for x in line.split("|")]
            if len(c) < 13:
                continue
            lat, lon, mag, depth = num(c[2]), num(c[3]), num(c[10]), num(c[4])
            if lat is None or lon is None or mag is None or mag >= 6 or not in_nz_box(lon, lat):
                continue
            place = c[12] or "New Zealand"
            out.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                "id": c[0], "name": f"M {mag:.1f} - {place}", "mag": round(mag, 1), "date": c[1][:10],
                "depth": round(depth) if depth is not None else None, "src": "GeoNet",
                "url": f"https://www.geonet.org.nz/earthquake/{c[0]}",
            }))
        return out
