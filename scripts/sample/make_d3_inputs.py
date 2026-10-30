"""Inputs for house prices, migration and education, in the shapes their connectors read,
from copies of the real data kept on GitHub (for the sample warehouse and the tests).

  python scripts/sample/make_d3_inputs.py OUT_DIR \
      --house-prices house-prices-global/data      # github.com/datasets/house-prices-global (BIS)
      --wic wcde-data/wcde-v3-batch/2              # github.com/guyabel/wcde-data (Wittgenstein v3, SSP2)
      --unhcr refugees/data/population.rda         # github.com/PopulationStatistics/refugees (UNHCR)
      --ims unhcrdatapackage/data/migrants.RData   # github.com/unhcr/unhcrdatapackage (UN DESA 2020 edition;
                                                   # its origin and destination columns are swapped back)
      [--countries NZL,AUS,GBR,USA]                # cut to a few countries (tests)

Needs pandas, rdata and openpyxl. What each gives:
  bis/spp_{nominal,real}_index.csv        as the BIS connector reads its GitHub fallback
  wittgenstein/{bmys,bprop}.csv           the .rds tables as CSV (ages 25+ only)
  unhcr/population_NNN.json               pages shaped like the UNHCR API's answers
  un_ims/undesa_pd_2020_ims_stock_by_sex_destination_and_origin.xlsx
                                          "Table 1" laid out like the UN's file (the 2020
                                          edition: 1990 to 2020), with World totals added
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import rdata

from worldmodel_contract import catalogue

warnings.simplefilter("ignore")


def codes(countries: list[str] | None) -> tuple[set[str] | None, set[str] | None, set[int] | None]:
    if not countries:
        return None, None, None
    ents = catalogue.entities()
    iso2 = {ents[c].iso2 for c in countries if ents[c].iso2}
    m49 = {int(ents[c].m49) for c in countries if ents[c].m49}
    return set(countries), iso2, m49


def bis(src: Path, out: Path, iso2: set[str] | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("nominal_index.csv", "real_index.csv"):
        lines = (src / name).read_text(encoding="utf-8").splitlines()
        keep = [lines[0]] + [ln for ln in lines[1:] if iso2 is None or ln.split(",")[1] in iso2]
        (out / f"spp_{name}").write_text("\n".join(keep) + "\n", encoding="utf-8")


def wittgenstein(src: Path, out: Path, m49: set[int] | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("bmys", "bprop"):
        df = rdata.read_rds(str(src / f"{name}.rds"))
        df = df[df["age"] == "25+"]
        if m49:
            df = df[df["country_code"].astype(int).isin(m49 | {900})]
        df.to_csv(out / f"{name}.csv", index=False)


def unhcr(src: Path, out: Path, iso3: set[str] | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    df = rdata.read_rda(str(src))["population"]
    if iso3:
        df = df[df["coa_iso"].isin(iso3) | df["coo_iso"].isin(iso3)]
    cols = ["year", "coo_iso", "coa_iso", "refugees", "asylum_seekers", "idps", "stateless", "ooc", "oip", "hst"]
    items = [{k: (None if v != v else (int(v) if k == "year" else v)) for k, v in zip(cols, r)}
             for r in df[cols].itertuples(index=False)]
    size = 10000
    pages = max(1, -(-len(items) // size))
    for p in range(pages):
        body = {"page": p + 1, "maxPages": pages, "total": len(items), "items": items[p * size:(p + 1) * size]}
        (out / f"population_{p + 1:03d}.json").write_text(json.dumps(body), encoding="utf-8")


def ims(src: Path, out: Path, m49: set[int] | None) -> None:
    from openpyxl import Workbook

    out.mkdir(parents=True, exist_ok=True)
    df = rdata.read_rda(str(src))["migrants"]
    df = df.dropna(subset=["Value"])
    # This copy has origin and destination the wrong way round (it lists 611,000 people born in
    # Australia living in New Zealand; the UN's own file has them as New Zealanders in Australia).
    df["o"] = df["CountryDestinationM49"].astype(int)
    df["d"] = df["CountryOriginM49"].astype(int)
    years = sorted(df["Year"].astype(int).unique())
    sexes = ("all", "male", "female")
    ents = catalogue.entities()
    countries = {int(e.m49) for e in ents.values() if e.m49 and not e.is_group} | {2003}  # 2003: "Other"
    cell: dict[tuple[int, int], dict[tuple[str, int], float]] = {}
    names: dict[int, str] = {900: "WORLD"}
    for o, d, on, dn, y, g, v in zip(df["o"], df["d"], df["CountryDestinationName"], df["CountryOriginName"],
                                     df["Year"].astype(int), df["Gender"], df["Value"]):
        names[o], names[d] = str(on).rstrip("*"), str(dn).rstrip("*")
        # The pair itself, the destination's total and the origin's total; region rows (Polynesia) repeat
        # their countries, so they count towards no total.
        for pair in ((d, o), *([(d, 900), (900, o)] if o in countries and d in countries else [])):
            cell.setdefault(pair, {})
            cell[pair][(g, y)] = cell[pair].get((g, y), 0) + v
    wb = Workbook()
    ws = wb.active
    ws.title = "Table 1"
    for i in range(9):
        ws.append(["International migrant stock at mid-year by sex and by region, country or area of destination "
                   "and origin, 1990-2020" if i == 0 else None])
    ws.append(["Index", "Region, development group, country or area of destination", "Notes of destination",
               "Location code of destination", "Type of data of destination",
               "Region, development group, country or area of origin", "Location code of origin",
               *years, *years, *years])
    for n, ((d, o), vals) in enumerate(sorted(cell.items()), start=1):
        if m49 and not (d in m49 or (d == 900 and o in m49)):
            continue
        ws.append([n, names.get(d, str(d)), None, d, "B", names.get(o, str(o)), o,
                   *[vals.get((g, y)) for g in sexes for y in years]])
    wb.save(out / "undesa_pd_2020_ims_stock_by_sex_destination_and_origin.xlsx")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--house-prices", type=Path)
    ap.add_argument("--wic", type=Path)
    ap.add_argument("--unhcr", type=Path)
    ap.add_argument("--ims", type=Path)
    ap.add_argument("--countries", type=lambda s: s.upper().split(","))
    a = ap.parse_args()
    iso3, iso2, m49 = codes(a.countries)
    if a.house_prices:
        bis(a.house_prices, a.out / "bis", iso2)
    if a.wic:
        wittgenstein(a.wic, a.out / "wittgenstein", m49)
    if a.unhcr:
        unhcr(a.unhcr, a.out / "unhcr", iso3)
    if a.ims:
        ims(a.ims, a.out / "un_ims", m49)


if __name__ == "__main__":
    main()
