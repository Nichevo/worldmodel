"""Make the inputs for the sample warehouse that ships with the app.

The sample is built by the real pipeline (`worldmodel-data fetch --from` then
`build`), from real data, re-shaped into the files the connectors read:

* UN WPP 2024, from the UN Population Division's own R package
  (https://github.com/PPgp/wpp2024, data/*.rda), written out in the layout of
  the official WPP CSV files. Two differences from the official files:
  the R package gives population at the end of each year, so 1 July values
  here are the mean of the two year-ends around them (within about 0.1 percent
  of the official 1 July figures), and age groups are kept for every fifth
  year only, to keep the sample small. Median age, density, sex ratio, infant
  mortality and net migration counts are not in the R package and are left
  out of the sample; a real refresh fills them in.
* IMF WEO April 2015 (data to 2014, projections to 2020), from the
  datahub.io mirror (https://github.com/datasets/imf-weo, data/values.csv),
  written as DataMapper API JSON. It is an old vintage: use it to try the app,
  not for current numbers. A real refresh replaces it with the latest WEO.

Usage (needs `pip install rdata pandas`):
  python scripts/sample/make_sample_inputs.py RDA_DIR WEO_VALUES_CSV OUT_DIR
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import rdata

ROOT = Path(__file__).resolve().parents[2]
ENTITIES = ROOT / "contract" / "worldmodel_contract" / "catalogues" / "entities.csv"
AGGREGATES = {900: "World", 903: "Africa", 935: "Asia", 908: "Europe", 909: "Oceania"}
AGE_YEARS = set(range(1950, 2021, 5)) | {2023}
IMF_SERIES = ["NGDP_RPCH", "NGDPD", "NGDPDPC", "PPPGDP", "PPPPC", "PCPIPCH"]


def rda(path: Path) -> pd.DataFrame:
    return next(iter(rdata.read_rda(str(path)).values()))


def main(rda_dir: Path, weo_values: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ents = pd.read_csv(ENTITIES, dtype=str, keep_default_na=False)
    countries = ents[ents.type == "country"]
    loc = {int(r.m49): (r.iso3, 4, r.name) for r in countries.itertuples() if r.m49}
    loc.update({k: ("", 1 if k == 900 else 2, v) for k, v in AGGREGATES.items()})
    write_wpp(rda_dir, out, loc)
    write_weo(weo_values, out / "imf_weo")


def write_wpp(rda_dir: Path, out: Path, loc: dict) -> None:
    age1 = rda(rda_dir / "popAge1dt.rda")
    age1 = age1[age1.country_code.isin(loc)]
    # Five-year groups 0-4 ... 95-99 and 100+, at each year end.
    age1["grp"] = (age1.age // 5 * 5).clip(upper=100)
    end = age1.groupby(["country_code", "year", "grp"], as_index=False)[["popM", "popF", "pop"]].sum()
    end = end.sort_values(["country_code", "grp", "year"])
    # 1 July of year y = mean of the end of y-1 and the end of y.
    mid = end.copy()
    for c in ["popM", "popF", "pop"]:
        mid[c] = (end.groupby(["country_code", "grp"])[c].shift(1) + end[c]) / 2
    mid = mid[mid.year >= 1950].dropna()

    totals_est = mid.groupby(["country_code", "year"], as_index=False)[["popM", "popF", "pop"]].sum()
    proj = rda(rda_dir / "popproj1dt.rda")
    proj = proj[proj.country_code.isin(loc)][["country_code", "year", "popM", "popF"]]
    last_end = end[end.year == 2023].groupby("country_code", as_index=False)[["popM", "popF"]].sum()
    last_end["year"] = 2023
    ends = pd.concat([last_end, proj]).sort_values(["country_code", "year"])
    for c in ["popM", "popF"]:
        ends[c + "_mid"] = (ends.groupby("country_code")[c].shift(1) + ends[c]) / 2
    totals_proj = ends[ends.year >= 2024].rename(columns={"popM_mid": "m", "popF_mid": "f"})
    totals_proj = totals_proj.assign(popM=totals_proj.m, popF=totals_proj.f, pop=totals_proj.m + totals_proj.f)
    totals = pd.concat([totals_est, totals_proj[["country_code", "year", "popM", "popF", "pop"]]])

    tfr = pd.concat([rda(rda_dir / "tfr1dt.rda"), rda(rda_dir / "tfrproj1dt.rda")[["country_code", "year", "tfr"]]])
    e0 = rda(rda_dir / "e01dt.rda")
    misc = rda(rda_dir / "misc1dt.rda")
    df = (totals.merge(tfr, how="left", on=["country_code", "year"])
          .merge(e0, how="left", on=["country_code", "year"])
          .merge(misc, how="left", on=["country_code", "year"]))

    header = ["SortOrder", "LocID", "Notes", "ISO3_code", "ISO2_code", "SDMX_code", "LocTypeID", "LocTypeName",
              "ParentID", "Location", "VarID", "Variant", "Time", "TPopulation1July", "TPopulationMale1July",
              "TPopulationFemale1July", "PopGrowthRate", "Births", "CBR", "TFR", "Deaths", "CDR", "LEx", "LExMale",
              "LExFemale", "CNMR"]
    path = out / "un_wpp" / "WPP2024_Demographic_Indicators_Medium.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, r in enumerate(df.sort_values(["country_code", "year"]).itertuples(), 1):
            iso3, ltype, name = loc[r.country_code]
            w.writerow([i, r.country_code, "", iso3, "", "", ltype, "", "", name, 2, "Medium", r.year,
                        f(r.pop), f(r.popM), f(r.popF), f(r.growthrate), f(r.births), f(r.cbr), f(r.tfr),
                        f(r.deaths), f(r.cdr), f(r.e0B), f(r.e0M), f(r.e0F), f(r.cnmr)])

    path = out / "un_wpp" / "WPP2024_PopulationByAge5GroupSex_Medium.csv.gz"
    header = ["SortOrder", "LocID", "Notes", "ISO3_code", "ISO2_code", "SDMX_code", "LocTypeID", "LocTypeName",
              "ParentID", "Location", "VarID", "Variant", "Time", "MidPeriod", "AgeGrp", "AgeGrpStart", "AgeGrpSpan",
              "PopMale", "PopFemale", "PopTotal"]
    ages = mid[mid.year.isin(AGE_YEARS)].sort_values(["country_code", "year", "grp"])
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, r in enumerate(ages.itertuples(), 1):
            iso3, ltype, name = loc[r.country_code]
            g = int(r.grp)
            label, span = ("100+", -1) if g == 100 else (f"{g}-{g + 4}", 5)
            w.writerow([i, r.country_code, "", iso3, "", "", ltype, "", "", name, 2, "Medium", r.year, r.year + 0.5,
                        label, g, span, f(r.popM), f(r.popF), f(r.pop)])
    print(f"WPP: {len(df):,} location-years, {len(ages):,} age rows")


def write_weo(values_csv: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    data: dict[str, dict] = defaultdict(lambda: defaultdict(dict))
    with values_csv.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["Indicator"] in IMF_SERIES:
                try:
                    v = float(r["Value"].replace(",", ""))
                except ValueError:
                    continue
                data[r["Indicator"]][r["Country"]][r["Year"]] = v
    for code in IMF_SERIES:
        (out / f"{code}.json").write_text(json.dumps({"values": {code: data[code]}}))
    (out / "release.txt").write_text("2015-04\n")
    print(f"WEO: {sum(len(v) for v in data.values())} country-series")


def f(x) -> str:
    return "" if pd.isna(x) else f"{x:.6g}" if abs(x) < 1000 else f"{x:.3f}"


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
