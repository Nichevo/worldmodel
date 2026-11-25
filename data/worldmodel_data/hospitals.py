"""One Hospitals map layer from several lists (worldmodel_contract.health): Wikidata's
'hospitals' layer and each list's 'hospitals_<list>' layer in src.raw_layers become one
'hospitals' layer, with a hospital two lists share kept once. Runs while the build loads its
sources, before the layer details (layer_tables.prepare) count the dots by country.

A dot is the same hospital as one already kept when it is within MATCH_M metres and the
names are alike, or within SAME_M metres whatever the names. Points are looked up in a grid
of about 300 m squares, so millions of comparisons are never made."""

from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from collections import defaultdict

import duckdb

from worldmodel_contract import health as spec

log = logging.getLogger(__name__)

STOP = {"hospital", "hospitals", "the", "of", "and", "de", "del", "la", "le", "el", "general", "hospitalar", "hospital's",
        "medical", "center", "centre", "clinic", "university", "hôpital", "hopital", "krankenhaus", "ospedale", "hospitalario"}
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _words(name: str) -> set[str]:
    """Name words without the common ones; for Chinese, Japanese and Korean names, two-character pieces."""
    s = unicodedata.normalize("NFKC", name or "").lower()
    if CJK.search(s):
        s = re.sub(r"(医院|病院|병원|人民|市|县|区|第)", "", re.sub(r"\s+", "", s))
        return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())
    return {w for w in re.findall(r"\w+", s) if w not in STOP and len(w) > 1}


def similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= spec.NAME_SIMILAR


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6_371_000 * math.hypot(x, math.radians(lat2 - lat1))


def merge(layers: dict[str, list[dict]]) -> list[dict]:
    """The features of each list's layer (keyed by contract SOURCES key), merged in SOURCES order."""
    cell = spec.MATCH_M / 111_000  # degrees of latitude
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    kept: list[dict] = []
    unnamed = "Hospital (no name given)"
    for src in spec.SOURCES:
        short = spec.SOURCES[src]["short"]
        for f in layers.get(src) or []:
            c = (f.get("geometry") or {}).get("coordinates") or []
            if len(c) < 2:
                continue
            lon, lat = float(c[0]), float(c[1])
            p = f.get("properties") or {}
            name = str(p.get("name") or unnamed)
            gy, gx = int(lat // cell), int(lon // (cell / max(0.2, math.cos(math.radians(lat)))))
            match = None
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for i in grid.get((gy + dy, gx + dx), ()):
                        k = kept[i]
                        d = _metres(lat, lon, k["lat"], k["lon"])
                        if d <= spec.SAME_M or (d <= spec.MATCH_M and (name == unnamed or k["name"] == unnamed
                                                                       or similar(name, k["name"]))):
                            if match is None or d < match[1]:
                                match = (i, d)
            if match is not None:
                k = kept[match[0]]
                if short not in k["found"]:
                    k["found"].append(short)
                if k["name"] == unnamed and name != unnamed:
                    k["name"] = name
                for key in ("beds",):
                    if isinstance(p.get(key), (int, float)) and (k["props"].get(key) is None or p[key] > k["props"][key]):
                        k["props"][key] = p[key]
                for key in ("country", "url", "id"):
                    if p.get(key) and not k["props"].get(key):
                        k["props"][key] = p[key]
                continue
            grid[(gy, gx)].append(len(kept))
            kept.append({"lat": lat, "lon": lon, "name": name, "found": [short],
                         "props": {k: v for k, v in p.items() if k in ("country", "beds", "id", "url", "kind", "list")}})
    out = []
    for n, k in enumerate(kept):
        props = {"name": k["name"], **k["props"], "found": " + ".join(k["found"])}
        props.setdefault("id", f"h{n}")
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(k["lon"], 5), round(k["lat"], 5)]},
                    "properties": props})
    return out


def prepare(con: duckdb.DuckDBPyConnection) -> int:
    """Replace the hospitals layers in src.raw_layers with the one merged layer. Returns its dots."""
    ids = [s["layer"] for s in spec.SOURCES.values()]
    rows = con.execute(f"""SELECT layer_id, geojson, source_id, vintage, name, description FROM src.raw_layers
                           WHERE layer_id IN ({', '.join('?' * len(ids))})
                           QUALIFY row_number() OVER (PARTITION BY layer_id ORDER BY vintage DESC) = 1""", ids).fetchall()
    if not rows:
        return 0
    layers, base = {}, None
    for layer_id, geojson, source_id, vintage, name, description in rows:
        try:
            layers[spec.source_of_layer(layer_id)] = json.loads(geojson or "{}").get("features") or []
        except json.JSONDecodeError:
            log.warning("hospitals: %s is not GeoJSON; left out", layer_id)
        if layer_id == "hospitals" or base is None:
            base = (source_id, vintage)
    feats = merge(layers)
    con.execute(f"DELETE FROM src.raw_layers WHERE layer_id IN ({', '.join('?' * len(ids))})", ids)
    if not feats:
        return 0
    lists = [spec.SOURCES[k]["short"] for k in spec.SOURCES if layers.get(k)]
    cols = [c[0] for c in con.execute("SELECT * FROM src.raw_layers LIMIT 0").description]
    vals = {"layer_id": "hospitals", "name": "Hospitals", "kind": "point", "feature_count": len(feats),
            "description": f"Hospitals from {', '.join(lists)}, each counted once where lists share it; "
                           "Settings > Places says which are shown.",
            "source_id": "wikidata_places" if layers.get("wikidata") else spec.SOURCES[next(k for k in spec.SOURCES if layers.get(k))]["source_id"],
            "vintage": base[1] if base else None,
            "geojson": json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"), ensure_ascii=False)}
    con.execute(f"INSERT INTO src.raw_layers ({', '.join(c for c in cols if c in vals)}) VALUES ({', '.join('?' * len([c for c in cols if c in vals]))})",
                [vals[c] for c in cols if c in vals])
    log.info("hospitals: %s dots from %s", len(feats), ", ".join(f"{spec.SOURCES[k]['short']} {len(v)}" for k, v in layers.items() if k))
    return len(feats)
