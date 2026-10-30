"""World Bank World Development Indicators, from the bulk download.

    https://databank.worldbank.org/data/download/WDI_CSV.zip

One zip of every WDI series (about 1,500) for every economy and year, with
these files inside (names as in the zip; older zips call the data WDIData.csv):

* WDICSV.csv      Country Name, Country Code, Indicator Name, Indicator Code, 1960 .. <last year>
* WDISeries.csv   Series Code, Topic, Indicator Name, Short definition, Long definition,
                  Unit of measure, Aggregation method, Source, ... (one row per series)
* WDICountry.csv  Country Code, Short Name, Region, Income Group, ... (Region is blank
                  for aggregates such as WLD or HIC)

What is stored:

* Series the indicator catalogue maps (population, GDP, inflation and so on) under
  the catalogue's ids, as a second source beside the UN and the IMF, for the
  source comparison.
* Every other series under an id of its own, `wdi_<code>` (SP.URB.TOTL.IN.ZS is
  wdi_sp_urb_totl_in_zs), or a plain name for the main ones in MAIN below.
  They are listed in indicators.json beside the vintage, with the World Bank's
  own names and definitions; the build adds them to the indicator table. The
  ones in MAIN start switched on; the rest start switched off and can be
  switched on on the Indicators page.
* Countries (codes with a region), plus the World and the four income groups.
  The World Bank's other aggregates (its regions, the EU as now composed for every
  year, and so on) are left out: worldmodel builds its own group values from
  members as they were in each year.
* Each country's income group from WDICountry.csv, as memberships of the income
  group entities (memberships.json beside the vintage). This is the current
  classification, applied to every year, as the World Bank does for its own
  aggregates.

All values are the World Bank's estimates (status E); WDI has no projections.
A copy of the zip, or a folder holding the CSV files, can be given instead:
worldmodel-data fetch world_bank_wdi --from PATH.
"""

from __future__ import annotations

import csv
import logging
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str

log = logging.getLogger(__name__)

URL = "https://databank.worldbank.org/data/download/WDI_CSV.zip"
FILE = "WDI_CSV.zip"
DATA_FILE = re.compile(r"^WDI(CSV|Data)\.csv$", re.I)
SERIES_FILE = re.compile(r"^WDISeries\.csv$", re.I)
COUNTRY_FILE = re.compile(r"^WDICountry\.csv$", re.I)

# WDI aggregate codes kept, and the entities they are (scheme `wdi` in the crosswalk).
AGGREGATES = ("WLD", "HIC", "UMC", "LMC", "LIC")
INCOME_GROUPS = {"high income": "income-high", "upper middle income": "income-upper-middle",
                 "lower middle income": "income-lower-middle", "low income": "income-low"}

# The main series: switched on by default, under a plain id. Where the World Bank
# has renamed a series, the codes are listed newest first and the first one found
# gets the id.
MAIN: dict[str, tuple[str, ...]] = {
    # economy
    "gni_per_capita_atlas": ("NY.GNP.PCAP.CD",),
    "gni_per_capita_ppp": ("NY.GNP.PCAP.PP.CD",),
    "gdp_per_capita_growth": ("NY.GDP.PCAP.KD.ZG",),
    "gdp_per_capita_constant_usd": ("NY.GDP.PCAP.KD",),
    "gdp_per_worker": ("SL.GDP.PCAP.EM.KD",),
    "gdp_deflator_inflation": ("NY.GDP.DEFL.KD.ZG",),
    "agriculture_share_gdp": ("NV.AGR.TOTL.ZS",),
    "industry_share_gdp": ("NV.IND.TOTL.ZS",),
    "manufacturing_share_gdp": ("NV.IND.MANF.ZS",),
    "services_share_gdp": ("NV.SRV.TOTL.ZS",),
    "investment_share_gdp": ("NE.GDI.TOTL.ZS",),
    "gross_savings_share_gdp": ("NY.GNS.ICTR.ZS",),
    "household_consumption_share_gdp": ("NE.CON.PRVT.ZS",),
    "govt_consumption_share_gdp": ("NE.CON.GOVT.ZS",),
    "natural_resource_rents_gdp": ("NY.GDP.TOTL.RT.ZS",),
    "oil_rents_gdp": ("NY.GDP.PETR.RT.ZS",),
    "gas_rents_gdp": ("NY.GDP.NGAS.RT.ZS",),
    "coal_rents_gdp": ("NY.GDP.COAL.RT.ZS",),
    "mineral_rents_gdp": ("NY.GDP.MINR.RT.ZS",),
    # prices and rates
    "price_level_ratio": ("PA.NUS.PPPC.RF",),
    "ppp_conversion_factor": ("PA.NUS.PPP",),
    "exchange_rate_usd": ("PA.NUS.FCRF",),
    "lending_rate": ("FR.INR.LEND",),
    "deposit_rate": ("FR.INR.DPST",),
    "real_interest_rate": ("FR.INR.RINR",),
    # trade
    "exports_share_gdp": ("NE.EXP.GNFS.ZS",),
    "imports_share_gdp": ("NE.IMP.GNFS.ZS",),
    "trade_share_gdp": ("NE.TRD.GNFS.ZS",),
    "fuel_share_exports": ("TX.VAL.FUEL.ZS.UN",),
    "ores_metals_share_exports": ("TX.VAL.MMTL.ZS.UN",),
    "high_tech_share_exports": ("TX.VAL.TECH.MF.ZS",),
    "tariff_rate_weighted": ("TM.TAX.MRCH.WM.AR.ZS",),
    "fdi_inflows_gdp": ("BX.KLT.DINV.WD.GD.ZS",),
    "remittances_received_gdp": ("BX.TRF.PWKR.DT.GD.ZS",),
    "current_account_gdp": ("BN.CAB.XOKA.GD.ZS",),
    "tourist_arrivals": ("ST.INT.ARVL",),
    # government and finance
    "central_govt_debt_gdp": ("GC.DOD.TOTL.GD.ZS",),
    "tax_revenue_gdp": ("GC.TAX.TOTL.GD.ZS",),
    "govt_revenue_gdp": ("GC.REV.XGRT.GD.ZS",),
    "govt_expense_gdp": ("GC.XPN.TOTL.GD.ZS",),
    "govt_net_lending_gdp": ("GC.NLD.TOTL.GD.ZS",),
    "broad_money_gdp": ("FM.LBL.BMNY.GD.ZS",),
    "private_credit_gdp": ("FS.AST.PRVT.GD.ZS",),
    "market_cap_gdp": ("CM.MKT.LCAP.GD.ZS",),
    "reserves_months_imports": ("FI.RES.TOTL.MO",),
    "reserves_usd": ("FI.RES.TOTL.CD",),
    "external_debt_gni": ("DT.DOD.DECT.GN.ZS",),
    "aid_received_gni": ("DT.ODA.ODAT.GN.ZS",),
    # military (SIPRI, through WDI)
    "military_spending_gdp": ("MS.MIL.XPND.GD.ZS",),
    "military_spending_usd": ("MS.MIL.XPND.CD",),
    "military_spending_govt_share": ("MS.MIL.XPND.ZS",),
    "armed_forces": ("MS.MIL.TOTL.P1",),
    "armed_forces_labour_share": ("MS.MIL.TOTL.TF.ZS",),
    "arms_exports": ("MS.MIL.XPRT.KD",),
    "arms_imports": ("MS.MIL.MPRT.KD",),
    # labour
    "unemployment": ("SL.UEM.TOTL.ZS",),
    "youth_unemployment": ("SL.UEM.1524.ZS",),
    "labour_participation": ("SL.TLF.CACT.ZS",),
    "labour_participation_female": ("SL.TLF.CACT.FE.ZS",),
    "labour_force": ("SL.TLF.TOTL.IN",),
    "employment_agriculture_share": ("SL.AGR.EMPL.ZS",),
    "employment_industry_share": ("SL.IND.EMPL.ZS",),
    "employment_services_share": ("SL.SRV.EMPL.ZS",),
    "vulnerable_employment": ("SL.EMP.VULN.ZS",),
    # poverty and inequality
    "gini": ("SI.POV.GINI",),
    "poverty_extreme": ("SI.POV.DDAY",),
    "poverty_lower_middle_line": ("SI.POV.LMIC",),
    "income_share_top10": ("SI.DST.10TH.10",),
    "income_share_bottom20": ("SI.DST.FRST.20",),
    # health
    "under5_mortality": ("SH.DYN.MORT",),
    "maternal_mortality": ("SH.STA.MMRT",),
    "adolescent_fertility": ("SP.ADO.TFRT",),
    "health_spending_gdp": ("SH.XPD.CHEX.GD.ZS",),
    "health_spending_per_capita": ("SH.XPD.CHEX.PC.CD",),
    "physicians_per_1000": ("SH.MED.PHYS.ZS",),
    "hospital_beds_per_1000": ("SH.MED.BEDS.ZS",),
    "measles_immunisation": ("SH.IMM.MEAS",),
    "child_stunting": ("SH.STA.STNT.ZS",),
    "undernourishment": ("SN.ITK.DEFC.ZS",),
    "safe_drinking_water": ("SH.H2O.SMDW.ZS",),
    "hiv_prevalence": ("SH.DYN.AIDS.ZS",),
    "diabetes_prevalence": ("SH.STA.DIAB.ZS",),
    "suicide_rate": ("SH.STA.SUIC.P5",),
    "road_deaths_rate": ("SH.STA.TRAF.P5",),
    "homicide_rate": ("VC.IHR.PSRC.P5",),
    # education and science
    "literacy_rate": ("SE.ADT.LITR.ZS",),
    "primary_enrolment": ("SE.PRM.ENRR",),
    "secondary_enrolment": ("SE.SEC.ENRR",),
    "tertiary_enrolment": ("SE.TER.ENRR",),
    "primary_completion": ("SE.PRM.CMPT.ZS",),
    "education_spending_gdp": ("SE.XPD.TOTL.GD.ZS",),
    "rd_spending_gdp": ("GB.XPD.RSDV.GD.ZS",),
    "researchers_per_million": ("SP.POP.SCIE.RD.P6",),
    "patent_applications_resident": ("IP.PAT.RESD",),
    # people and places
    "urban_share": ("SP.URB.TOTL.IN.ZS",),
    "urban_population": ("SP.URB.TOTL",),
    "largest_city_share_urban": ("EN.URB.LCTY.UR.ZS",),
    "migrant_stock": ("SM.POP.TOTL",),
    "migrant_stock_share": ("SM.POP.TOTL.ZS",),
    "refugees_hosted": ("SM.POP.REFG",),
    "refugees_by_origin": ("SM.POP.REFG.OR",),
    "women_in_parliament": ("SG.GEN.PARL.ZS",),
    # infrastructure and technology
    "electricity_access": ("EG.ELC.ACCS.ZS",),
    "internet_users_share": ("IT.NET.USER.ZS",),
    "mobile_subscriptions_per_100": ("IT.CEL.SETS.P2",),
    "air_passengers": ("IS.AIR.PSGR",),
    # land, environment and energy
    "land_area": ("AG.LND.TOTL.K2",),
    "surface_area": ("AG.SRF.TOTL.K2",),
    "forest_share_land": ("AG.LND.FRST.ZS",),
    "arable_land_share": ("AG.LND.ARBL.ZS",),
    "cereal_yield": ("AG.YLD.CREL.KG",),
    "pm25_exposure": ("EN.ATM.PM25.MC.M3",),
    "freshwater_withdrawal_share": ("ER.H2O.FWTL.ZS",),
    "ghg_emissions_total": ("EN.GHG.ALL.MT.CE.AR5", "EN.ATM.GHGT.KT.CE"),
    "co2_emissions_total": ("EN.GHG.CO2.MT.CE.AR5", "EN.ATM.CO2E.KT"),
    "co2_per_capita": ("EN.GHG.CO2.PC.CE.AR5", "EN.ATM.CO2E.PC"),
    "energy_use_per_capita": ("EG.USE.PCAP.KG.OE",),
    "electricity_use_per_capita": ("EG.USE.ELEC.KH.PC",),
    "renewable_share_final_energy": ("EG.FEC.RNEW.ZS",),
    "energy_imports_net_share": ("EG.IMP.CONS.ZS",),
}

# WDI's top-level topics, as worldmodel's menu groups.
TOPIC_DOMAIN = {
    "agriculture & rural development": "agriculture", "aid effectiveness": "aid", "climate change": "environment",
    "economy & growth": "economy", "economic policy & debt": "economy", "education": "education",
    "energy & mining": "energy", "environment": "environment", "external debt": "debt",
    "financial sector": "finance", "gender": "gender", "health": "health", "infrastructure": "infrastructure",
    "poverty": "poverty", "private sector": "business", "private sector & trade": "trade",
    "public sector": "government", "science & technology": "science", "social development": "society",
    "social protection & labor": "labour", "trade": "trade", "urban development": "cities",
}
CODE_DOMAIN = (("MS.MIL.", "military"), ("SP.POP.", "population"), ("SP.DYN.", "population"),
               ("SM.POP.", "migration"), ("PA.NUS.", "prices"), ("FR.INR.", "prices"))
SUM_METHODS = ("sum", "gap-filled total")
UNIT_HINT = re.compile(r"%|\$|US\$|LCU|per |number|km|kg|kt|mt|hectares|tonnes|kwh|years|days|index|ratio|people|persons", re.I)


def indicator_id(code: str) -> str:
    return "wdi_" + re.sub(r"[^a-z0-9]+", "_", code.lower()).strip("_")


class WorldBankWDI(Connector):
    source_id = "world_bank_wdi"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")  # the file has no release name of its own

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(URL, raw_dir / FILE)
        return URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        tmp = Path(tempfile.mkdtemp(prefix="wdi-"))
        try:
            files = _unpack(raw_dir, tmp)
            series = _read_rows(files["series"]) if "series" in files else []
            countries = _read_rows(files["country"]) if "country" in files else []
            con.execute("SET preserve_insertion_order = false")
            con.execute(f"CREATE TABLE wdi_raw AS SELECT * FROM read_csv({sql_str(files['data'].as_posix())}, "
                        f"header = true, all_varchar = true)")
            cols = [r[0] for r in con.execute("DESCRIBE wdi_raw").fetchall()]
            code_col = _column(cols, "country code")
            series_col = _column(cols, "indicator code")
            name_col = _column(cols, "indicator name")
            years = [c for c in cols if re.fullmatch(r"\s*(19|20)\d\d\s*", c)]
            if not (code_col and series_col and years):
                raise ConnectorError(f"world_bank_wdi: {files['data'].name} does not have the expected columns "
                                     f"(Country Code, Indicator Code, one per year); found {cols[:8]}")
            names = dict(con.execute(f'SELECT DISTINCT "{series_col}", "{name_col}" FROM wdi_raw').fetchall()) \
                if name_col else {}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        country_codes = {r.get("country code", "").strip() for r in countries if r.get("region", "").strip()}
        if not country_codes:  # no country file: the codes the crosswalk knows as countries
            country_codes = self.known_codes("iso3")
        keep = sorted(country_codes | set(AGGREGATES))

        mapped = self.series_map()
        meta = {r.get("series code", "").strip(): r for r in series if r.get("series code", "").strip()}
        present = set(names) | set(meta)
        main = {}
        for ind, codes in MAIN.items():
            found = next((c for c in codes if c in present), None)
            if found and found not in mapped:
                main[found] = ind
        con.execute("CREATE TABLE wdi_map (series VARCHAR, indicator_id VARCHAR, scale DOUBLE)")
        rows = []
        for code in sorted(present):
            if code in mapped:
                rows.append((code, mapped[code][0], mapped[code][1]))
            else:
                rows.append((code, main.get(code) or indicator_id(code), 1.0))
        con.executemany("INSERT INTO wdi_map VALUES (?, ?, ?)", rows)
        con.execute("CREATE TABLE wdi_keep (code VARCHAR)")
        con.executemany("INSERT INTO wdi_keep VALUES (?)", [(c,) for c in keep])

        year_list = ", ".join(f'"{y}"' for y in years)
        con.execute(f"""
            CREATE TABLE wdi AS
            SELECT trim(u."{code_col}") AS source_code, m.indicator_id, make_date(CAST(trim(u.year) AS INTEGER), 1, 1) AS period_start,
                TRY_CAST(u.value AS DOUBLE) * m.scale AS value
            FROM (UNPIVOT wdi_raw ON {year_list} INTO NAME year VALUE value) u
            JOIN wdi_map m ON m.series = trim(u."{series_col}")
            JOIN wdi_keep k ON k.code = trim(u."{code_col}")
            WHERE TRY_CAST(u.value AS DOUBLE) IS NOT NULL""")
        con.execute("DROP TABLE wdi_raw")

        self.listed_indicators = [_indicator(code, ind, meta.get(code, {}), names.get(code, code), ind in MAIN)
                                  for code, ind, _ in rows if code not in mapped]
        self.listed_memberships = [
            {"group_id": INCOME_GROUPS[g], "member_id": r["country code"].strip(), "source": "World Bank WDI "
             "(WDICountry.csv, Income Group): latest classification", "verified": "yes"}
            for r in countries if (g := r.get("income group", "").strip().lower()) in INCOME_GROUPS]
        log.info("world_bank_wdi: %s series (%s mapped to the catalogue, %s main), %s economies, %s income-group members",
                 len(rows), len(rows) - len(self.listed_indicators), len(main), len(country_codes),
                 len(self.listed_memberships))

        aggs = ", ".join(sql_str(a) for a in AGGREGATES)
        return (f"SELECT 'world_bank_wdi' AS source_id, {sql_str(vintage)} AS vintage, "
                f"CASE WHEN source_code IN ({aggs}) THEN 'wdi' ELSE 'iso3' END AS scheme, source_code, indicator_id, "
                f"period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, value, 'E' AS status FROM wdi")


def _unpack(raw_dir: Path, dest: Path) -> dict[str, Path]:
    """The data, series and country CSV files, from the zip or lying in raw_dir."""
    found: dict[str, Path] = {}
    patterns = {"data": DATA_FILE, "series": SERIES_FILE, "country": COUNTRY_FILE}
    for p in sorted(raw_dir.iterdir()):
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    name = Path(info.filename).name
                    for kind, pat in patterns.items():
                        if pat.match(name) and kind not in found:
                            out = dest / name
                            with z.open(info) as src, out.open("wb") as dst:
                                shutil.copyfileobj(src, dst, 1 << 20)
                            found[kind] = out
        else:
            for kind, pat in patterns.items():
                if pat.match(p.name) and kind not in found:
                    found[kind] = p
    if "data" not in found:
        raise ConnectorError(f"world_bank_wdi: no WDICSV.csv (or WDIData.csv) in {raw_dir}")
    for kind in ("series", "country"):
        if kind not in found:
            log.warning("world_bank_wdi: no %s file; names, definitions and income groups will be missing",
                        "WDISeries.csv" if kind == "series" else "WDICountry.csv")
    return found


def _read_rows(path: Path) -> list[dict[str, str]]:
    """A CSV file as dicts with lower-case, trimmed column names."""
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        return [{(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in csv.DictReader(f)]


def _column(cols: list[str], name: str) -> str | None:
    return next((c for c in cols if c.replace("﻿", "").strip().lower() == name), None)


def _indicator(code: str, ind: str, meta: dict[str, str], name: str, main: bool) -> dict:
    """A catalogue-shaped indicator for one WDI series, from the World Bank's own metadata."""
    name = (meta.get("indicator name") or name).strip()
    topic = meta.get("topic", "")
    domain = next((d for p, d in CODE_DOMAIN if code.startswith(p)), None) \
        or TOPIC_DOMAIN.get(topic.split(":")[0].strip().lower()) \
        or (re.sub(r"[^a-z]+", "_", topic.split(":")[0].strip().lower()).strip("_") or "other")
    unit = meta.get("unit of measure", "").strip() or _unit(name)
    description = (meta.get("short definition") or meta.get("long definition") or name).strip()
    if len(description) > 1200:
        description = description[:1200].rsplit(" ", 1)[0] + " …"
    method = meta.get("aggregation method", "").strip().lower()
    notes = re.sub(r"\s+", " ", meta.get("source", "")).strip()[:500]
    return {
        "id": ind, "name": name, "description": description, "synonyms": [code],
        "domain": domain, "unit": unit, "decimals": _decimals(unit),
        "aggregation": {"method": "sum" if method in SUM_METHODS else "none"},
        "bounds": [-1e18, 1e18],  # the World Bank's values as published; only NaN and infinity fail
        "sources": [{"source_id": "world_bank_wdi", "series": code, "scale": 1.0, "notes": notes}],
        "default_on": main,
    }


def _unit(name: str) -> str:
    """The unit from the series name: its first bracketed part that reads like a unit."""
    parts = re.findall(r"\(([^()]*)\)", name)
    return next((p for p in parts if UNIT_HINT.search(p)), "")


def _decimals(unit: str) -> int:
    u = unit.lower()
    if "%" in u or "per " in u or "index" in u or "ratio" in u or "years" in u:
        return 1
    if "$" in u or "lcu" in u or "number" in u or "people" in u:
        return 0
    return 2
