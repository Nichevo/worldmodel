"""Make a WDI_CSV.zip in the World Bank's bulk layout, for the sample warehouse and tests.

The sample is built by the real pipeline, so it needs WDI in the layout the
connector reads (WDICSV.csv, WDISeries.csv, WDICountry.csv in one zip). The
source here is the datahub.io mirror of about 325 WDI series
(https://github.com/datasets/world-development-indicators, indicators/<code>/),
re-shaped into that layout. Two differences from the World Bank's own file:

* Fewer series (the mirror's selection), and only years from FIRST_YEAR on.
* Income groups are worked out from each country's latest GNI per person (Atlas
  method, NY.GNP.PCAP.CD) with the World Bank's fiscal-2026 thresholds, rather
  than read from the World Bank's classification. A few countries near a
  threshold may land in a neighbouring group. A real refresh replaces this.

Usage:
  python scripts/sample/make_wdi_inputs.py MIRROR_DIR OUT_ZIP [--series CODE,CODE] [--countries ISO,ISO]
         [--first-year 1990] [--last-year 2100]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTITIES = ROOT / "contract" / "worldmodel_contract" / "catalogues" / "entities.csv"
# Fiscal year 2026 thresholds, GNI per person in US dollars (Atlas method).
THRESHOLDS = ((1135, "Low income"), (4495, "Lower middle income"), (13935, "Upper middle income"))
AGGREGATES = {"WLD": "World", "HIC": "High income", "UMC": "Upper middle income", "LMC": "Lower middle income",
              "LIC": "Low income", "EUU": "European Union", "EAS": "East Asia & Pacific"}


def income_group(gni: float) -> str:
    return next((g for limit, g in THRESHOLDS if gni <= limit), "High income")


def main(mirror: Path, out: Path, series: list[str] | None, countries: list[str] | None,
         first_year: int, last_year: int) -> None:
    with ENTITIES.open(encoding="utf-8", newline="") as f:
        ents = {r["iso3"]: r for r in csv.DictReader(f) if r["type"] == "country" and r["iso3"]}
    keep = set(countries) if countries else set(ents)
    values: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    names, meta_rows = {}, []
    for d in sorted((mirror / "indicators").iterdir()):
        pkg = d / "datapackage.json"
        if not pkg.exists() or not (d / "data.csv").exists():
            continue
        code = d.name.upper()
        if series and code not in series:
            continue
        meta = json.loads(pkg.read_text(encoding="utf-8"))
        names[code] = meta.get("title", code)
        keywords = [k.strip() for k in meta.get("keywords", []) if k.strip()]
        meta_rows.append({"Series Code": code, "Topic": keywords[0] if keywords else "",
                          "Indicator Name": names[code], "Short definition": "",
                          "Long definition": meta.get("readme", ""), "Unit of measure": "",
                          "Aggregation method": "", "Source": "World Bank, World Development Indicators"})
        with (d / "data.csv").open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                c, y = r["Country Code"], int(r["Year"])
                if (c in keep or c in AGGREGATES) and first_year <= y <= last_year and r["Value"] != "":
                    values[(c, code)][y] = r["Value"]

    # Income groups from the latest GNI per person (all years, before cutting).
    gni = {}
    gni_csv = mirror / "indicators" / "ny.gnp.pcap.cd" / "data.csv"
    if gni_csv.exists():
        with gni_csv.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r["Value"]:
                    gni[r["Country Code"]] = float(r["Value"])  # rows are in year order: the last one wins

    years = list(range(first_year, min(last_year, max((y for v in values.values() for y in v), default=first_year)) + 1))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Country Name", "Country Code", "Indicator Name", "Indicator Code", *map(str, years)])
    for (c, code), by_year in sorted(values.items()):
        name = ents[c]["name"] if c in ents else AGGREGATES.get(c, c)
        w.writerow([name, c, names[code], code, *[by_year.get(y, "") for y in years]])

    cbuf = io.StringIO()
    cw = csv.DictWriter(cbuf, fieldnames=["Country Code", "Short Name", "Table Name", "Long Name", "2-alpha code",
                                          "Region", "Income Group"])
    cw.writeheader()
    for c in sorted({c for c, _ in values}):
        e = ents.get(c)
        cw.writerow({"Country Code": c, "Short Name": e["short_name"] if e else AGGREGATES.get(c, c),
                     "Table Name": e["name"] if e else AGGREGATES.get(c, c), "Long Name": e["name"] if e else "",
                     "2-alpha code": e["iso2"] if e else "", "Region": "sample" if e else "",
                     "Income Group": income_group(gni[c]) if e and c in gni else ""})

    sbuf = io.StringIO()
    sw = csv.DictWriter(sbuf, fieldnames=list(meta_rows[0]) if meta_rows else ["Series Code"])
    sw.writeheader()
    sw.writerows(meta_rows)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("WDICSV.csv", "﻿" + buf.getvalue())
        z.writestr("WDISeries.csv", "﻿" + sbuf.getvalue())
        z.writestr("WDICountry.csv", "﻿" + cbuf.getvalue())
    print(f"{out}: {len(meta_rows)} series, {len({c for c, _ in values})} economies, years {years[0]}-{years[-1]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mirror", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--series", type=lambda s: s.upper().split(","))
    ap.add_argument("--countries", type=lambda s: s.upper().split(","))
    ap.add_argument("--first-year", type=int, default=1990)
    ap.add_argument("--last-year", type=int, default=2100)
    a = ap.parse_args()
    main(a.mirror, a.out, a.series, a.countries, a.first_year, a.last_year)
