"""The IEA's free data files, saved by hand: monthly electricity, energy RD&D, coal,
fossil fuel subsidies, household energy spending, appliances, pump prices, energy per
value added, and the World Energy Outlook's free annex.

iea_data
    The IEA asks for a (free) sign-in to download most files, so they are saved by hand
    in var\\manual\\iea_data, keeping the names the site gives them. Each file is
    recognised by its name or its columns; files it does not know are left out with one
    line in the log, so a folder holding other IEA files is fine. Files loaded before
    stay in use until a newer copy of the same file is saved (keeps_files).

    SDMX CSVs from the IEA data explorer (zipped or not):
      MESGEN   Monthly Electricity Statistics, net production by fuel (GWh, monthly)
      MESBAL   Monthly Electricity Statistics, imports, exports, final use (GWh, monthly)
      RDDPUBLIC, RDDPRIVATE  Energy technology RD&D spending (million US$, constant)
      CST      Coal production by quarter (kt, summed to years of four quarters)
      CSTWORLDTRADE  Coal exports and imports by quarter (kt, summed likewise)
    Excel workbooks:
      Subsidies 2010-2024.xlsx                fossil fuel consumption subsidies
      Household Energy Expenditure database   household spending on energy per person
      Household Appliances database           share of homes with each appliance
      Energy_Prices_Monthly_Excerpt           pump prices of petrol and diesel (monthly)
      Energy_ValueAdded                       energy and carbon per unit of value added
    The World Energy Outlook's Annex A free dataset (CSV, world and regions): history, and
    the Stated Policies scenario as the projection, with the Current Policies and Net Zero
    scenarios as breakdowns (scenario=current, scenario=nze).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb
from worldmodel_contract import catalogue

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.tabular import (
    indicator,
    key,
    num,
    xlsx_rows,
    xlsx_sheet_names,
)

log = logging.getLogger(__name__)

SOURCE = "iea_data"
NOTE = "IEA (International Energy Agency), loaded from the file saved by hand."

# Regions the IEA names that are entities here; other regions (IEA Europe, OPEC+) are left out.
REGIONS = {"world": "world", "total": "world", "european union": "eu", "european union 27": "eu", "eu27": "eu",
           "africa": "africa"}


def entity(name) -> str | None:
    """An entity for an IEA country or region label (or ISO3 code)."""
    s = str(name or "").strip().rstrip("*").strip()
    if not s:
        return None
    if s.lower() in REGIONS:
        return REGIONS[s.lower()]
    if re.fullmatch(r"[A-Z]{3}", s) and s in catalogue.entities():
        return s
    s = s.replace("People's Republic of China", "China").replace("Chinese Taipei", "Taiwan").replace(", China", "")
    if s == "Taipei":
        s = "Taiwan"
    tries = [s, re.sub(r"^(United Republic|Republic|Kingdom) of (the )?", "", s),
             re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[a-z])(?=and[A-Z])", " ", s)]  # "SaudiArabia", "TrinidadandTobago"
    return next((e for t in tries for e in [catalogue.country_by_name(t)] if e), None)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


class Out:
    """Values with their period, frequency, breakdown and status."""

    def __init__(self) -> None:
        self.rows: list[tuple] = []
        self.seen: set[tuple] = set()  # the World and Regions files both hold some world series: the first counts
        self.unknown: set[str] = set()
        self.found: set[str] = set()

    def add(self, place, ind: str, when: date, value, freq: str = "A", breakdown: str = "", status: str = "E",
            ent: str | None = None) -> None:
        v = num(value)
        if v is None or v != v:
            return
        e = ent or entity(place)
        if not e:
            if place:
                self.unknown.add(str(place))
            return
        if (e, ind, when, freq, breakdown) in self.seen:
            return
        self.seen.add((e, ind, when, freq, breakdown))
        self.rows.append((e, ind, when, freq, breakdown, v, status))
        self.found.add(ind)

    def __len__(self) -> int:
        return len(self.rows)


# ----------------------------------------------------------------------------- reading files
def sdmx_rows(f: Path):
    """Rows of an SDMX CSV from the IEA data explorer, or of every CSV in a zip of them."""
    if f.suffix.lower() == ".zip":
        with zipfile.ZipFile(f) as z:
            for n in z.namelist():
                if n.lower().endswith(".csv"):
                    yield from csv.DictReader(io.StringIO(z.read(n).decode("utf-8-sig", errors="replace")))
        return
    with f.open(encoding="utf-8-sig", errors="replace", newline="") as h:
        yield from csv.DictReader(h)


def dataset_of(f: Path) -> str | None:
    """Which IEA dataset a file holds, from its name (MESGEN.zip, RDDPUBLIC.csv ...) or first row."""
    n = f.name.upper()
    for ds in ("MESGEN", "MESBAL", "RDDPUBLIC", "RDDPRIVATE", "CSTWORLDTRADE", "CSTOECDTRADE", "CST"):
        if n.startswith((ds, f"OECD.IEA_{ds}")):
            return ds
    if f.suffix.lower() in (".csv", ".zip"):
        for r in sdmx_rows(f):
            m = re.match(r"OECD\.IEA:([A-Z]+)", r.get("DATASET_ID", "") or "")
            return m.group(1) if m else ("WEO" if "PUBLICATION" in r and "SCENARIO" in r else None)
    return None


def label(r: dict) -> str:
    return r.get("Country") or r.get("Country/Region") or r.get("COUNTRY") or ""


def month(s: str) -> date | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(s).strip())
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


ELEC_FUELS = {"TOTAL": "", "COAL": "coal", "NATURAL_GAS": "gas", "OIL_TOTAL": "oil", "NUCLEAR": "nuclear",
              "HYDRO": "hydro", "WIND": "wind", "SOLAR": "solar", "GEOTHERMAL": "geothermal",
              "BIOFUELS_RENWASTE": "bioenergy", "RENEWABLES_TOTAL": "renewables", "TOTAL_FOSSIL_FUELS": "fossil"}


def read_mesgen(f: Path, out: Out) -> None:
    by: dict[tuple, dict[str, float]] = defaultdict(dict)
    for r in sdmx_rows(f):
        fuel = ELEC_FUELS.get(r.get("ENERGY_PRODUCT", ""))
        d = month(r.get("TIME_PERIOD", ""))
        if fuel is None or not d or r.get("PLANT", "TOTAL") != "TOTAL" or r.get("ENERGY_BALANCE_FLOW") != "NELEPROD":
            continue
        out.add(label(r), "elec_month_gwh", d, r.get("OBS_VALUE"), "M", f"fuel={fuel}" if fuel else "")
        v = num(r.get("OBS_VALUE"))
        if v is not None:
            by[(label(r), d)][fuel or "total"] = v
    for (place, d), x in by.items():  # low-carbon and renewable shares of each month's production
        if x.get("total"):
            if "renewables" in x:
                out.add(place, "elec_month_renew_share", d, x["renewables"] / x["total"] * 100, "M")
            if "fossil" in x:
                out.add(place, "elec_month_fossil_share", d, x["fossil"] / x["total"] * 100, "M")


BAL_FLOWS = {"IMPORTS": "elec_month_imports", "EXPORTS": "elec_month_exports", "TFC_ENGY_CALC": "elec_month_use"}


def read_mesbal(f: Path, out: Out) -> None:
    for r in sdmx_rows(f):
        ind, d = BAL_FLOWS.get(r.get("ENERGY_BALANCE_FLOW", "")), month(r.get("TIME_PERIOD", ""))
        if ind and d and r.get("ENERGY_PRODUCT", "ELECTRICITY") == "ELECTRICITY":
            out.add(label(r), ind, d, r.get("OBS_VALUE"), "M")


RDD_TECH_NAMES: dict[str, str] = {}


def read_rdd(f: Path, out: Out, private: bool) -> None:
    ind = "energy_rdd_private" if private else "energy_rdd_public"
    for r in sdmx_rows(f):
        tech, unit = r.get("RDD_TECH", ""), r.get("UNIT", "")
        if r.get("RDD_TYPE") != "RDD" or r.get("RDD_SECTOR") not in ("PUBLIC", "PRIVATE") or not str(r.get("TIME_PERIOD", "")).isdigit():
            continue
        if not (tech == "TOTAL" or re.fullmatch(r"[A-HZ]", tech)):
            continue
        y = date(int(r["TIME_PERIOD"]), 1, 1)
        place = label(r)
        if place in ("Total IEA", "IEA Total"):
            place = "IEA"  # the IEA members together: not an entity here
        bd = "" if tech == "TOTAL" else f"tech={tech}"
        if tech != "TOTAL":
            RDD_TECH_NAMES[tech] = r.get("Technology", tech)
        if unit == "USD_R":
            out.add(place, ind, y, r.get("OBS_VALUE"), breakdown=bd)
        elif unit == "U_GDP" and tech == "TOTAL" and not private:
            out.add(place, "energy_rdd_public_gdp", y, r.get("OBS_VALUE"))


def read_coal(f: Path, out: Out, trade: bool) -> None:
    """Quarterly kt summed to million tonnes for years with all four quarters."""
    quarters: dict[tuple, list[float]] = defaultdict(list)
    for r in sdmx_rows(f):
        m = re.fullmatch(r"(\d{4})-Q([1-4])", str(r.get("TIME_PERIOD", "")).strip())
        v = num(r.get("OBS_VALUE"))
        if not m or v is None or r.get("UNIT", "KT") != "KT":
            continue
        flow, prod = r.get("ENERGY_BALANCE_FLOW", ""), r.get("ENERGY_PRODUCT", "")
        if trade:
            ind = {"EXPORTS": "coal_exports_mt", "IMPORTS": "coal_imports_mt"}.get(flow)
        else:
            ind = "coal_production_mt" if flow == "INDPROD_OSOURCES" else None
        if not ind:
            continue
        kind = {"STEAM_COKINGCOAL": "hard", "STEAMCOAL": "steam", "COKING_COAL": "coking", "LIGNITE": "lignite"}.get(prod, slug(prod))
        quarters[(label(r), ind, int(m.group(1)), kind)].append(v)
    years: dict[tuple, dict[str, list[float]]] = defaultdict(dict)
    for (place, ind, y, kind), vs in quarters.items():
        years[(place, ind, y)][kind] = vs
    for (place, ind, y), kinds in years.items():
        full = {k: vs for k, vs in kinds.items() if len(vs) == 4}
        for k, vs in full.items():
            out.add(place, ind, date(y, 1, 1), sum(vs) / 1000, breakdown=f"coal={k}")
        if full and len(full) == len(kinds):
            out.add(place, ind, date(y, 1, 1), sum(sum(vs) for vs in full.values()) / 1000)


def _find(table: list[list], first: str) -> int | None:
    return next((i for i, r in enumerate(table[:30]) if r and key(r[0]) == key(first)), None)


def read_subsidies(f: Path, out: Out) -> None:
    names = xlsx_sheet_names(f)
    sheet = next((n for n in names if key(n).startswith("subsidiesbycountry")), None)
    if sheet:
        t = xlsx_rows(f, sheet)
        head = next((i for i, r in enumerate(t[:20]) if r and sum(isinstance(c, (int, float)) and 1990 < c < 2100 for c in r) >= 2), None)
        if head is not None:
            years = {j: int(c) for j, c in enumerate(t[head]) if isinstance(c, (int, float)) and 1990 < c < 2100}
            place = None
            for r in t[head + 1:]:
                if not r or len(r) < 2:
                    continue
                place = r[0] or place  # the country is written once, on its first product's row
                prod = str(r[1] or "").strip()
                if not prod:
                    continue
                bd = "" if key(prod) in ("allproducts", "total") else f"fuel={slug(prod)}"
                for j, y in years.items():
                    if j < len(r):
                        out.add(place, "fossil_subsidies_usd", date(y, 1, 1), r[j], breakdown=bd)
    sheet = next((n for n in names if key(n).startswith("indicatorsbycountry")), None)
    if sheet:
        t = xlsx_rows(f, sheet)
        year = next((int(m.group(1)) for r in t[:3] for c in r if c for m in [re.search(r"(20\d\d)", str(c))] if m), None)
        head = _find(t, "Country")
        if year and head is not None:
            cols = {j: key(c) for j, c in enumerate(t[head]) if c}
            for r in t[head + 1:]:
                for j, k in cols.items():
                    if j >= len(r) or num(r[j]) is None:
                        continue
                    if k.startswith("averagesubsidisationrate"):
                        out.add(r[0], "fossil_subsidy_rate", date(year, 1, 1), num(r[j]) * 100)
                    elif k.startswith("subsidypercapita"):
                        out.add(r[0], "fossil_subsidy_pp", date(year, 1, 1), r[j])
                    elif k.startswith("totalsubsidyasshareofgdp"):
                        out.add(r[0], "fossil_subsidy_gdp", date(year, 1, 1), num(r[j]) * 100)


def _long_sheet(f: Path, sheet_key: str, need: set[str]) -> tuple[list[str], list[list]]:
    names = xlsx_sheet_names(f)
    sheet = next((n for n in names if key(n) == sheet_key), None)
    if not sheet:
        return [], []
    t = xlsx_rows(f, sheet)
    head = next((i for i, r in enumerate(t[:10]) if r and need <= {key(c) for c in r if c}), None)
    if head is None:
        return [], []
    return [key(c) for c in t[head]], t[head + 1:]


def _getter(r: list, i: dict[str, int]):
    """A function giving the cell under a (loosely compared) header in row r."""
    return lambda c: r[i[c]] if c in i and i[c] < len(r) else None


SPEND_UNITS = {"USD/POP": "household_energy_spend_pp", "USDRPPP/POP": "household_energy_spend_ppp_pp"}


def read_household_spend(f: Path, out: Out) -> None:
    cols, rows = _long_sheet(f, "data", {"codecountry", "codeunit", "value"})
    i = {c: n for n, c in enumerate(cols)}
    for r in rows:
        g = _getter(r, i)
        ind = SPEND_UNITS.get(str(g("codeunit") or ""))
        if not ind or str(g("codesector") or "RESIDENT") != "RESIDENT" or str(g("codeenduse") or "RESIDENT") != "RESIDENT":
            continue
        y = num(g("time") or g("codetime"))
        prod = str(g("codeproduct") or "TOTAL")
        if y:
            out.add(g("codecountry"), ind, date(int(y), 1, 1), g("value"),
                    breakdown="" if prod == "TOTAL" else f"fuel={slug(prod)}")


def read_appliances(f: Path, out: Out) -> None:
    cols, rows = _long_sheet(f, "data", {"country", "metric", "enduse", "value"})
    i = {c: n for n, c in enumerate(cols)}
    for r in rows:
        g = _getter(r, i)
        y = num(g("time"))
        if key(g("metric")) == "penetration" and y:
            out.add(g("country"), "appliance_ownership", date(int(y), 1, 1), g("value"), breakdown=f"appliance={slug(g('enduse'))}")


PUMP = {"gasoline": "pump_price_petrol_usd", "automotivediesel": "pump_price_diesel_usd", "lightfueloil": "heating_oil_price_usd"}


def read_pump_prices(f: Path, out: Out) -> None:
    cols, rows = _long_sheet(f, "rawdata", {"country", "product", "unit", "time", "value"})
    i = {c: n for n, c in enumerate(cols)}
    for r in rows:
        g = _getter(r, i)
        prod = key(str(g("product") or "").split("(")[0])
        ind, t = PUMP.get(prod), g("time")
        if not ind or str(g("unit") or "") != "USD" or key(g("flow") or "totalprice") != "totalprice":
            continue
        if isinstance(t, datetime):
            d = date(t.year, t.month, 1)
        else:
            m = re.match(r"(\d{4})-(\d{2})", str(t or ""))
            d = date(int(m.group(1)), int(m.group(2)), 1) if m else None
        if d:
            out.add(g("country"), ind, d, g("value"), "M")


VA = {"pervalueaddedenergyintensity": "energy_per_value_added", "pervalueaddedcarbonintensity": "carbon_per_value_added"}


def read_value_added(f: Path, out: Out) -> None:
    cols, rows = _long_sheet(f, "indicatorsdata", {"countryiso3", "indicator", "value"})
    i = {c: n for n, c in enumerate(cols)}
    for r in rows:
        g = _getter(r, i)
        ind, y, div = VA.get(key(g("indicator"))), num(g("year")), str(g("isicdivision") or "").strip()
        if ind and y and g("countryiso3"):
            out.add(g("countryiso3"), ind, date(int(y), 1, 1), g("value"),
                    breakdown="" if div.upper() == "TOTAL" else f"isic={div}")


SCENARIOS = {"historical": ("", "E"), "statedpoliciesscenario": ("", "P"), "currentpoliciesscenario": ("scenario=current", "P"),
             "netzeroemissionsby2050scenario": ("scenario=nze", "P")}
WEO_SERIES: dict[str, tuple[str, str]] = {}  # indicator -> (name, unit)


def weo_id(cat: str, prod: str, flow: str) -> str:
    return "weo_" + slug(f"{'' if cat == 'Energy' else cat} {prod} {flow}")[:60]


def read_weo(f: Path, out: Out) -> None:
    with f.open(encoding="utf-8-sig", errors="replace", newline="") as h:
        for r in csv.DictReader(h):
            sc = SCENARIOS.get(key(r.get("SCENARIO")))
            y = num(r.get("YEAR"))
            if not sc or not y:
                continue
            cat, prod, flow, unit = (r.get(k, "").strip() for k in ("CATEGORY", "PRODUCT", "FLOW", "UNIT"))
            ind = weo_id(cat, prod, flow)
            WEO_SERIES[ind] = (f"{prod}: {flow.lower()}" if cat == "Energy" else f"{cat}: {flow.lower()}", unit)
            out.add(r.get("REGION"), ind, date(int(y), 1, 1), r.get("VALUE"), breakdown=sc[0], status=sc[1])


# ----------------------------------------------------------------------------- the connector
def read_all(files: list[Path]) -> tuple[Out, list[str]]:
    out, used = Out(), []
    for f in files:
        n, suf = f.name.lower(), f.suffix.lower()
        try:
            if suf in (".csv", ".zip"):
                ds = dataset_of(f)
                if ds == "MESGEN":
                    read_mesgen(f, out)
                elif ds == "MESBAL":
                    read_mesbal(f, out)
                elif ds in ("RDDPUBLIC", "RDDPRIVATE"):
                    read_rdd(f, out, ds == "RDDPRIVATE")
                elif ds == "CST":
                    read_coal(f, out, trade=False)
                elif ds == "CSTWORLDTRADE":
                    read_coal(f, out, trade=True)
                elif ds == "WEO":
                    read_weo(f, out)
                else:
                    log.info("iea_data: %s is not a file this source reads; left out", f.name)
                    continue
            elif suf in (".xlsx", ".xlsm"):
                if "subsid" in n:
                    read_subsidies(f, out)
                elif "expenditure" in n:
                    read_household_spend(f, out)
                elif "appliance" in n:
                    read_appliances(f, out)
                elif "prices" in n and "monthly" in n:
                    read_pump_prices(f, out)
                elif "valueadded" in n.replace(" ", "").replace("_", ""):
                    read_value_added(f, out)
                else:
                    log.info("iea_data: %s is not a file this source reads; left out", f.name)
                    continue
            else:
                continue
            used.append(f.name)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            log.warning("iea_data: could not read %s (%s)", f.name, exc)
    return out, used


def indicators(found: set[str]) -> list[dict]:
    """The indicators read, catalogue-shaped."""
    E = "energy"
    defs = [
        ("elec_month_gwh", "Electricity production by month", "Net electricity production each month, total and by fuel "
         "(Monthly Electricity Statistics).", "GWh", E, 0, ["fuel"], "M", True),
        ("elec_month_renew_share", "Renewable share of electricity, by month", "Renewables' share of each month's net "
         "electricity production.", "%", E, 1, None, "M", True),
        ("elec_month_fossil_share", "Fossil share of electricity, by month", "Coal, oil and gas's share of each month's "
         "net electricity production.", "%", E, 1, None, "M", False),
        ("elec_month_imports", "Electricity imports by month", "Electricity imported each month.", "GWh", E, 0, None, "M", False),
        ("elec_month_exports", "Electricity exports by month", "Electricity exported each month.", "GWh", E, 0, None, "M", False),
        ("elec_month_use", "Electricity use by month", "Final consumption of electricity each month (calculated by the IEA).",
         "GWh", E, 0, None, "M", False),
        ("energy_rdd_public", "Public spending on energy research", "Government spending on energy research, development "
         "and demonstration, total and by technology (tech=A energy efficiency ... H other cross-cutting), "
         "constant US$.", "million US$ (constant)", E, 1, ["tech"], "A", True),
        ("energy_rdd_public_gdp", "Public energy research per 1,000 of GDP", "Government energy RD&D spending per 1,000 "
         "units of GDP.", "per 1,000 GDP", E, 3, None, "A", False),
        ("energy_rdd_private", "Private spending on energy research", "Companies' spending on energy RD&D (IEA estimates "
         "for a few countries), constant US$.", "million US$ (constant)", E, 1, ["tech"], "A", False),
        ("coal_production_mt", "Coal production (quarterly survey)", "Hard coal and lignite produced, summed from the "
         "IEA's quarterly coal statistics; years with all four quarters.", "Mt", E, 1, ["coal"], "A", False),
        ("coal_exports_mt", "Coal exports", "Steam coal, coking coal and lignite exported, summed from quarters.", "Mt", E, 1,
         ["coal"], "A", False),
        ("coal_imports_mt", "Coal imports", "Steam coal, coking coal and lignite imported, summed from quarters.", "Mt", E, 1,
         ["coal"], "A", False),
        ("fossil_subsidies_usd", "Fossil fuel subsidies", "Subsidies to the use of oil, gas, coal and fossil-fired "
         "electricity, worked out by the IEA's price-gap method (end-user prices below the full cost of supply), "
         "real 2024 US$.", "million US$ (2024)", E, 0, ["fuel"], "A", True),
        ("fossil_subsidy_rate", "Fossil fuel subsidy rate", "Subsidy as a share of the full cost of supply, on average.",
         "%", E, 1, None, "A", False),
        ("fossil_subsidy_pp", "Fossil fuel subsidy per person", "Fossil fuel subsidies divided by population.", "US$ per person",
         E, 0, None, "A", False),
        ("fossil_subsidy_gdp", "Fossil fuel subsidies, share of GDP", "Fossil fuel subsidies as a share of GDP.", "% of GDP",
         E, 1, None, "A", True),
        ("household_energy_spend_pp", "Household spending on energy per person", "What households spend on energy at "
         "home (electricity, gas, heating fuels, firewood), total and by fuel, US$ per person.", "US$ per person", E, 0,
         ["fuel"], "A", True),
        ("household_energy_spend_ppp_pp", "Household spending on energy per person (PPP)", "As above, in constant 2021 "
         "US$ at purchasing power parity.", "US$ (2021 PPP) per person", E, 0, ["fuel"], "A", False),
        ("appliance_ownership", "Homes with each appliance", "Share of households with a fridge, washing machine, air "
         "conditioner, television and so on.", "% of households", E, 1, ["appliance"], "A", False),
        ("pump_price_petrol_usd", "Petrol price at the pump", "End-user price of petrol (gasoline) including taxes, US$ a "
         "litre, monthly.", "US$ per litre", "prices", 2, None, "M", True),
        ("pump_price_diesel_usd", "Diesel price at the pump", "End-user price of road diesel including taxes, US$ a litre, "
         "monthly.", "US$ per litre", "prices", 2, None, "M", True),
        ("heating_oil_price_usd", "Heating oil price", "End-user price of light fuel oil for homes including taxes, "
         "US$ per 1,000 litres, monthly.", "US$ per 1,000 litres", "prices", 0, None, "M", False),
        ("energy_per_value_added", "Energy per unit of value added", "Energy used per US$ of value added (2015 prices, "
         "PPP), whole economy and by industry (isic=...).", "MJ per US$", E, 2, ["isic"], "A", False),
        ("carbon_per_value_added", "Carbon per unit of value added", "CO2 emitted per US$ of value added (2015 prices, "
         "PPP), by industry (isic=...).", "kg CO2 per US$", E, 3, ["isic"], "A", False),
    ]
    out = []
    for i, name, desc, unit, dom, dec, bds, freq, on in defs:
        if i in found:
            out.append(indicator(i, name, f"{desc} {NOTE}", unit, dom, SOURCE, i, decimals=dec, breakdowns=bds or [],
                                 frequency=freq, default_on=on, bounds=(0, 100) if unit.startswith("%") else (-1e15, 1e15)))
    for i, (name, unit) in sorted(WEO_SERIES.items()):
        if i in found:
            out.append(indicator(i, f"World Energy Outlook: {name}", f"{name} ({unit}): history and the IEA's Stated "
                                 "Policies scenario as the projection; scenario=current and scenario=nze hold the Current "
                                 f"Policies and Net Zero by 2050 scenarios. {NOTE}", unit, "energy", SOURCE, i,
                                 decimals=1, breakdowns=["scenario"], default_on=False))
    return out


class IEAData(Connector):
    source_id = SOURCE
    manual = True
    stage_version = 2  # 2: one value per place, period and breakdown
    keeps_files = True  # each file stays in use until a newer copy of it is saved

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("iea_data: the IEA files are saved by hand in var\\manual\\iea_data (see Data status)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(f for f in raw_dir.iterdir() if f.is_file() and f.suffix.lower() in (".csv", ".zip", ".xlsx", ".xlsm"))
        out, used = read_all(files)
        if not len(out):
            raise ConnectorError(f"iea_data: none of the {len(files)} files held IEA data this source reads "
                                 "(MESGEN, RDDPUBLIC, Subsidies ..., WEO Annex A); see Data status for the list")
        if out.unknown:
            log.info("iea_data: %s places left out (regions or names not matched), such as %s", len(out.unknown),
                     ", ".join(sorted(out.unknown)[:6]))
        log.info("iea_data: %s values from %s", len(out), ", ".join(used))
        self.listed_indicators = indicators(out.found)
        con.execute("CREATE TABLE iea (e VARCHAR, i VARCHAR, d DATE, f VARCHAR, b VARCHAR, v DOUBLE, s VARCHAR)")
        con.executemany("INSERT INTO iea VALUES (?, ?, ?, ?, ?, ?, ?)", out.rows)
        return (f"SELECT {sql_str(SOURCE)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, e AS source_code, "
                "i AS indicator_id, d AS period_start, f AS freq, b AS breakdown, 'central' AS variant, v AS value, "
                "s AS status FROM iea")
