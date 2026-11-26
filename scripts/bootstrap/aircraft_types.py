"""Write app/api/worldmodel_api/aircraft_types.py from a checkout of Virtual Radar Server's standing
data (CC0): git clone --depth 1 https://github.com/vradarserver/standing-data, then
python scripts/bootstrap/aircraft_types.py <that folder>."""

from __future__ import annotations

import collections
import csv
import re
import sys
from pathlib import Path

SPECIAL = {"GLID": "glider", "BALL": "glider", "SHIP": "glider", "ULAC": "light", "GYRO": "helicopter", "PARA": "glider"}
OUT = Path(__file__).resolve().parents[2] / "app" / "api" / "worldmodel_api" / "aircraft_types.py"
HEADER = '''"""Aircraft type designators (ICAO Doc 8643 codes such as B738, A320, EC45) with each one's maker,
model and how the map draws it, and the ICAO 24-bit address blocks each country hands out (which also
mark military blocks). Built from Virtual Radar Server's standing data (CC0),
https://github.com/vradarserver/standing-data (model-type and code-blocks), by
scripts/bootstrap/aircraft_types.py. Types change slowly, so it is rebuilt only now and then.
"""

from __future__ import annotations

'''


def group(r: dict) -> str:
    """airliner (big jets and airliners, wake M or heavier), light, helicopter, glider, fast (one jet engine)."""
    if r["ICAO"] in SPECIAL:
        return SPECIAL[r["ICAO"]]
    sp, et, wt = r["SpeciesCode"], r["EngineTypeCode"], r["WakeTurbulenceCode"]
    n = int(r["Engines"]) if r["Engines"].isdigit() else 0
    if sp in ("H", "G", "T"):
        return "helicopter"
    if et == "J" and n == 1:
        return "fast"
    if wt in ("H", "J", "M") or (et == "J" and n >= 3):
        return "airliner"
    if wt in ("L", "L/M"):
        return "light"
    return "unknown"


def main(folder: Path) -> None:
    by: dict[str, list[dict]] = collections.defaultdict(list)
    for f in sorted((folder / "model-type" / "schema-01").glob("*.csv")):
        for r in csv.DictReader(f.open(encoding="utf-8-sig")):
            if r["ICAO"] and r["ICAO"] != "-":
                by[r["ICAO"]].append(r)
    types = {}
    for code, rows in by.items():
        # the most typical name: the active model whose words are most common among the type's names
        # (so 'Boeing 737-800', not a military or VIP variant), from its most usual maker
        words = [set(re.findall(r"[a-z0-9]+", r["Model"].lower())) for r in rows]
        pool = [i for i, r in enumerate(rows) if r["IsActive"] == "1"] or list(range(len(rows)))
        share = collections.Counter(x for w in words for x in w)
        best = max(pool, key=lambda i: (sum(share[x] for x in words[i]) / max(1, len(words[i])), -len(rows[i]["Model"])))
        model = rows[best]["Model"]
        maker = collections.Counter(r["Manufacturer"] for r in rows if r["Model"] == model).most_common(1)[0][0]
        types[code] = (group(rows[best]), " ".join(x for x in (maker, model) if x).strip())
    blocks = [b for b in csv.DictReader((folder / "code-blocks" / "schema-01" / "code-blocks.csv").open(encoding="utf-8-sig"))
              if not (b["CountryISO2"] == "ZZ" and b["IsMilitary"] == "0")]
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER)
        f.write("# designator: (map group, maker and model)\nTYPES: dict[str, tuple[str, str]] = {\n")
        for k in sorted(types):
            f.write(f"    {k!r}: {types[k]!r},\n")
        f.write("}\n\n# (first address, last address, ISO two-letter country or ZZ, military block)\nBLOCKS: list[tuple[int, int, str, bool]] = [\n")
        for b in blocks:
            f.write(f"    (0x{b['Start']}, 0x{b['Finish']}, {b['CountryISO2']!r}, {b['IsMilitary'] == '1'}),\n")
        f.write("]\n")
    print(f"{len(types)} types, {len(blocks)} address blocks -> {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
