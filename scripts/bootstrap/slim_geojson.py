"""Make the country outlines the web app ships, from Natural Earth (public domain).

Keeps two properties (iso3, name) and rounds coordinates to 0.01 degrees.
Natural Earth leaves ISO_A3 as -99 for a few countries, so ISO_A3_EH and
ADM0_A3 fill the gaps; Kosovo becomes XKX to match the crosswalk.

Usage:
  python scripts/bootstrap/slim_geojson.py ne_50m_admin_0_countries.geojson app/web/public/geo/countries.json
"""

import json
import sys

FIXES = {"KOS": "XKX", "SDS": "SSD", "SAH": "ESH", "PSX": "PSE"}


def rnd(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 2), round(coords[1], 2)]
    return [rnd(c) for c in coords]


def main(src: str, dest: str) -> None:
    data = json.load(open(src, encoding="utf-8"))
    out = []
    for f in data["features"]:
        p = f["properties"]
        iso3 = next((c for c in (p.get("ISO_A3"), p.get("ISO_A3_EH"), p.get("ADM0_A3")) if c and c != "-99"), None)
        iso3 = FIXES.get(iso3, iso3)
        geom = f["geometry"]
        geom = {"type": geom["type"], "coordinates": rnd(geom["coordinates"])}
        out.append({"type": "Feature", "properties": {"iso3": iso3, "name": p.get("NAME")}, "geometry": geom})
    json.dump({"type": "FeatureCollection", "features": out}, open(dest, "w", encoding="utf-8"),
              separators=(",", ":"))
    print(f"{len(out)} features -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
