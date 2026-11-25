"""Make the finer country outlines the world map switches to when you zoom in.

From Natural Earth 1:10m admin-0 countries (public domain). The outlines are
simplified together (shapely.coverage_simplify), so neighbours keep sharing one
border with no gaps or overlaps, then rounded to 0.001 degrees (about 100 m).
Codes follow slim_geojson.py; pieces sharing a code (Baikonur, Clipperton...) are
joined into one shape so each country is one feature.

Usage (needs shapely 2.1+):
  python scripts/bootstrap/fine_geojson.py ne_10m_admin_0_countries.geojson app/web/public/geo/countries_fine.json
"""

import json
import re
import sys

import shapely
from shapely.geometry import mapping, shape

from slim_geojson import FIXES

TOLERANCE = 0.01


def main(src: str, dest: str) -> None:
    data = json.load(open(src, encoding="utf-8"))
    codes, names, geoms = [], [], []
    for f in data["features"]:
        p = f["properties"]
        iso3 = next((c for c in (p.get("ISO_A3"), p.get("ISO_A3_EH"), p.get("ADM0_A3")) if c and c != "-99"), None)
        codes.append(FIXES.get(iso3, iso3))
        names.append(p.get("NAME"))
        geoms.append(shape(f["geometry"]))
    simple = shapely.coverage_simplify(geoms, TOLERANCE, simplify_boundary=True)
    joined: dict[str, tuple[str, list]] = {}
    for code, name, g in zip(codes, names, simple):
        if g.is_empty:
            continue
        if code in joined:
            joined[code][1].append(g)
        else:
            joined[code] = (name, [g])
    out = []
    for code, (name, parts) in joined.items():
        g = parts[0] if len(parts) == 1 else shapely.union_all(parts)
        out.append({"type": "Feature", "properties": {"iso3": code, "name": name}, "geometry": mapping(g)})
    text = json.dumps({"type": "FeatureCollection", "features": out}, separators=(",", ":"))
    text = re.sub(r"(-?\d+\.\d{3})\d+", r"\1", text)
    open(dest, "w", encoding="utf-8").write(text)
    print(f"{len(out)} features, {len(text) / 1e6:.1f} MB -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
