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
from worldmodel_data.stepcache import OFF, StepCache, key, rows_hash

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


# Likely hospital or likely clinic, from what the lists say. Words are matched in lower case
# anywhere in the name, so the CJK ones need no spaces round them.
CLINIC_WORDS = (
    "clinic", "clínica", "clinica", "clinique", "polyclinic", "poliklinik", "policlínica", "dispensary", "dispensaire",
    "health centre", "health center", "healthcentre", "health post", "health station", "health unit", "centro de salud",
    "centro de saúde", "posto de saúde", "unidade básica", "ubs ", "puskesmas", "klinik pratama", "trạm y tế", "phòng khám",
    "physiotherapy", "maternity home", "birthing", "medical centre",
    "诊所", "卫生所", "卫生室", "卫生院", "卫生服务", "门诊", "医务室", "保健站", "诊疗", "診療所", "クリニック", "의원", "보건소",
)
# A place in or beside a hospital, or a service on its own: never a hospital, whatever else the name says.
NOT_A_HOSPITAL = ("dental", "dentist", "dialysis", "eye care", "optical", "pharmacy", "pharmacie", "laboratory", "diagnostic",
                  "imaging", "x-ray", "office", "cafeteria", "parking", "car park", "blood bank", "血液中心")
HOSPITAL_WORDS = (
    "hospital", "hôpital", "hopital", "ospedale", "krankenhaus", "klinikum", "ziekenhuis", "sjukhus", "sykehus", "sairaala",
    "szpital", "nemocnice", "kórház", "spital", "bolnica", "больница", "лікарня", "госпиталь", "rumah sakit", "bệnh viện",
    "โรงพยาบาล", "hastane", "مستشفى", "बेड", "अस्पताल", "医院", "病院", "병원", "infirmary", "medical college",
)
BIG_BEDS, SMALL_BEDS = 50, 20


def tier(p: dict) -> str:
    """'hospital' (likely a full hospital), 'clinic' (likely a clinic, health post or something
    inside a hospital) or 'unsure'. Beds decide first; then the kind a list gives; then words in
    the name (a clinic word counts only without a hospital word: Hospital das Clínicas); then the list
    (Wikidata's and official lists' hospitals, and emergency departments, count as hospitals)."""
    beds = p.get("beds")
    if isinstance(beds, (int, float)) and beds >= BIG_BEDS:
        return "hospital"
    if isinstance(beds, (int, float)) and 0 < beds < SMALL_BEDS:
        return "clinic"
    name = f" {str(p.get('name') or '').lower().replace('hospital (no name given)', '')} "
    kind = str(p.get("kind") or "").lower()
    if kind in ("day hospital", "mixed unit") or any(w in kind for w in ("health centre", "health center", "dispensary", "post", "clinic")):
        return "clinic"
    if "hospital" in kind:
        return "hospital"
    if any(w in name for w in NOT_A_HOSPITAL):
        return "clinic"
    has_hospital_word = any(w in name for w in HOSPITAL_WORDS)
    if any(w in name for w in CLINIC_WORDS) and not has_hospital_word:
        return "clinic"
    found = str(p.get("found") or "")
    if has_hospital_word:
        return "hospital"
    if "Wikidata" in found or "Official lists" in found or str(p.get("emergency") or "").lower() == "yes":
        return "hospital"
    return "unsure"


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
                for key in ("country", "url", "id", "kind", "emergency"):
                    if p.get(key) and not k["props"].get(key):
                        k["props"][key] = p[key]
                continue
            grid[(gy, gx)].append(len(kept))
            kept.append({"lat": lat, "lon": lon, "name": name, "found": [short],
                         "props": {k: v for k, v in p.items() if k in ("country", "beds", "id", "url", "kind", "list", "emergency")}})
    out = []
    for n, k in enumerate(kept):
        props = {"name": k["name"], **k["props"], "found": " + ".join(k["found"])}
        props["tier"] = tier(props)
        props.setdefault("id", f"h{n}")
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(k["lon"], 5), round(k["lat"], 5)]},
                    "properties": props})
    return out


STEP = "hospitals"


def prepare(con: duckdb.DuckDBPyConnection, cache: StepCache = OFF) -> int:
    """Replace the hospitals layers in src.raw_layers with the one merged layer. Returns its dots.
    When the lists are the same as at the last build, the merged layer saved then is used."""
    ids = [s["layer"] for s in spec.SOURCES.values()]
    marks = ', '.join('?' * len(ids))
    latest = f"""SELECT layer_id, geojson, source_id, vintage, name, description FROM src.raw_layers
                 WHERE layer_id IN ({marks})
                 QUALIFY row_number() OVER (PARTITION BY layer_id ORDER BY vintage DESC) = 1"""
    ck = key(STEP, rows_hash(con, latest, ids))
    if cache.load(con, STEP, ck, {"layer": "src.raw_layers"}, first=[(f"DELETE FROM src.raw_layers WHERE layer_id IN ({marks})", ids)]):
        n = con.execute("SELECT coalesce(max(feature_count), 0) FROM src.raw_layers WHERE layer_id = 'hospitals'").fetchone()[0]
        log.info("hospitals: lists unchanged since the last build; reused the %s merged dots", n)
        return n
    rows = con.execute(latest, ids).fetchall()
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
    cache.note_worked(STEP)
    cache.save(con, STEP, ck, {"layer": "SELECT * FROM src.raw_layers WHERE layer_id = 'hospitals'"})
    return len(feats)
