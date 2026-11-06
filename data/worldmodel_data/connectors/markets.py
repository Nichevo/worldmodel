"""Markets: daily exchange rates, gas and oil storage, month by month oil and gas stocks.

ecb_fx
    European Central Bank euro foreign exchange reference rates, every working day
    since 1999 (one zip, eurofxref-hist.csv: Date and one column per currency, units
    per euro). Turned into units per US dollar for every country using the currency.

fed_h10
    US Federal Reserve H.10 noon buying rates in New York, daily since 1971, read from
    FRED (fredgraph.csv, one series per currency). Adds the years before 1999 and
    currencies the ECB does not list (New Taiwan dollar, Sri Lanka rupee).

gie_agsi
    Gas Infrastructure Europe AGSI+ (gas storage, daily since 2011, the EU and each
    country with storage) and ALSI (LNG terminal stocks, since 2012): free key
    GIE_API_KEY. One file per area and year; past years are kept and only the
    current year is fetched again.

eia
    US Energy Information Administration API v2, weekly: working gas in storage (lower
    48 states), crude oil stocks without and in the Strategic Petroleum Reserve,
    gasoline, distillate and jet fuel stocks. Free key EIA_API_KEY.

jodi
    Joint Organisations Data Initiative bulk files: oil (crude and products) and natural
    gas closing stocks month by month for about 100 countries, with product demand, so
    days of cover can be worked out (New Zealand has no public gas storage reports).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.tabular import indicator, num

log = logging.getLogger(__name__)


class DatedRows:
    """Values on exact dates (daily, weekly or monthly), by (scheme, code, indicator)."""

    def __init__(self) -> None:
        self.rows: list[tuple] = []

    def add(self, scheme: str, code: str, ind: str, day: date, value: float | None, freq: str = "D",
            breakdown: str = "") -> None:
        if value is None or value != value or abs(value) == float("inf"):
            return
        self.rows.append((scheme, str(code), ind, day, freq, breakdown, float(value)))

    def __len__(self) -> int:
        return len(self.rows)

    def stage(self, con: duckdb.DuckDBPyConnection, source_id: str, vintage: str, table: str = "dated") -> str:
        con.execute(f"CREATE TABLE {table} (scheme VARCHAR, source_code VARCHAR, indicator_id VARCHAR, "
                    "period_start DATE, freq VARCHAR, breakdown VARCHAR, value DOUBLE)")
        if self.rows:
            con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)", self.rows)
        return (f"SELECT {sql_str(source_id)} AS source_id, {sql_str(vintage)} AS vintage, scheme, source_code, "
                f"indicator_id, period_start, freq, breakdown, 'central' AS variant, value, 'E' AS status FROM {table}")


def parse_day(s) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


# ------------------------------------------------------------------------------------- exchange rates
def users_of(currency: str) -> list[tuple[str, date | None, date | None]]:
    """(entity id, from, to) of every country using a currency."""
    out = []
    for r in catalogue.currencies():
        if r["currency"] == currency:
            f = date.fromisoformat(r["valid_from"]) if r.get("valid_from") else None
            t = date.fromisoformat(r["valid_to"]) if r.get("valid_to") else None
            out.append((r["entity_id"], f, t))
    return out


def add_per_usd(rows: DatedRows, per_usd: dict[str, dict[date, float]]) -> None:
    """Units of each currency per US dollar, put on every country using it on that day."""
    for cur, days in per_usd.items():
        users = users_of(cur)
        if not users:
            continue
        for d, v in days.items():
            for ent, f, t in users:
                if (f is None or d >= f) and (t is None or d <= t):
                    rows.add("iso3", ent, "fx_usd_d", d, v)


FX_INDICATOR = indicator(
    "fx_usd_d", "Exchange rate, daily (local currency per US dollar)",
    "How many units of the country's currency one US dollar bought that day; a rise means the currency weakened "
    "against the dollar. The Currency card on country pages works out any other pair from these.",
    "local currency per US$", "finance", "ecb_fx", "eurofxref-hist", decimals=4, default_on=False,
    bounds=(0, 1e9), frequency="D",
    notes="ECB reference rates (14:15 Frankfurt time), turned into units per US dollar through the euro.")

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"


class ECBRates(Connector):
    source_id = "ecb_fx"
    switch = "markets_daily"

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(ECB_URL, raw_dir / "eurofxref-hist.zip")
        return ECB_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        text = None
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as z:
                    name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
                    if name:
                        text = z.read(name).decode("utf-8-sig", errors="replace")
            elif f.suffix.lower() == ".csv":
                text = f.read_text(encoding="utf-8-sig", errors="replace")
            if text:
                break
        if not text:
            raise ConnectorError(f"ecb_fx: no eurofxref-hist file in {raw_dir}")
        per_usd = ecb_per_usd(text)
        if not per_usd.get("EUR"):
            raise ConnectorError("ecb_fx: no US dollar column in the ECB file")
        rows = DatedRows()
        add_per_usd(rows, per_usd)
        self.listed_indicators = [FX_INDICATOR]
        return rows.stage(con, self.source_id, vintage)


def ecb_per_usd(text: str) -> dict[str, dict[date, float]]:
    """The ECB file (units per euro) as units per US dollar, by currency and day."""
    out: dict[str, dict[date, float]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        d = parse_day(r.get("Date"))
        usd = num(r.get("USD"))
        if not d or not usd:
            continue
        out.setdefault("EUR", {})[d] = 1 / usd
        out.setdefault("USD", {})[d] = 1.0
        for cur, v in r.items():
            cur = (cur or "").strip().upper()
            if len(cur) != 3 or cur in ("USD", "EUR"):
                continue
            x = num(v)
            if x:
                out.setdefault(cur, {})[d] = x / usd
    return out


# FRED series of the H.10 release: (currency, True when quoted as US dollars per unit).
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
H10 = {
    "DEXUSEU": ("EUR", True), "DEXUSUK": ("GBP", True), "DEXUSAL": ("AUD", True), "DEXUSNZ": ("NZD", True),
    "DEXCAUS": ("CAD", False), "DEXJPUS": ("JPY", False), "DEXCHUS": ("CNY", False), "DEXSZUS": ("CHF", False),
    "DEXINUS": ("INR", False), "DEXKOUS": ("KRW", False), "DEXMXUS": ("MXN", False), "DEXBZUS": ("BRL", False),
    "DEXSDUS": ("SEK", False), "DEXDNUS": ("DKK", False), "DEXNOUS": ("NOK", False), "DEXSIUS": ("SGD", False),
    "DEXHKUS": ("HKD", False), "DEXTAUS": ("TWD", False), "DEXTHUS": ("THB", False), "DEXMAUS": ("MYR", False),
    "DEXSLUS": ("LKR", False), "DEXSFUS": ("ZAR", False),
}


class FedH10(Connector):
    source_id = "fed_h10"
    switch = "markets_daily"
    fetch_every_days = 7

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got, failed = [], []
        for sid in H10:
            try:
                self.get(FRED_URL.format(id=sid), raw_dir / f"{sid}.csv")
                got.append(sid)
            except ConnectorError as exc:
                failed.append(f"{sid} ({exc})")
            time.sleep(0.5)
        if not got:
            raise ConnectorError("fed_h10: no series downloaded from FRED: " + "; ".join(failed[:3]))
        if failed:
            log.warning("fed_h10: %d series not downloaded: %s", len(failed), "; ".join(failed[:5]))
        return f"FRED {len(got)} series"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        per_usd: dict[str, dict[date, float]] = {}
        for sid, (cur, inverse) in H10.items():
            p = raw_dir / f"{sid}.csv"
            if not p.exists():
                continue
            for r in csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig", errors="replace"))):
                if len(r) < 2:
                    continue
                d, v = parse_day(r[0]), num(r[1])
                if d and v:
                    per_usd.setdefault(cur, {})[d] = 1 / v if inverse else v
        if not per_usd:
            raise ConnectorError(f"fed_h10: no rates read from {raw_dir}")
        per_usd["USD"] = {d: 1.0 for days in per_usd.values() for d in days}
        rows = DatedRows()
        add_per_usd(rows, per_usd)
        self.listed_indicators = [{**FX_INDICATOR, "sources": [{
            "source_id": self.source_id, "series": "H.10", "scale": 1.0,
            "notes": "Federal Reserve H.10 noon buying rates in New York, from FRED."}]}]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------- gas storage (GIE)
AGSI_URL = "https://agsi.gie.eu/api"
ALSI_URL = "https://alsi.gie.eu/api"
GIE_FIRST = {"agsi": 2011, "alsi": 2012}
# Areas with gas storage reported to AGSI+ ("eu" is the EU total); LNG stocks for the EU and the UK.
AGSI_AREAS = ["eu", "AT", "BE", "BG", "HR", "CZ", "DK", "FR", "DE", "HU", "IT", "LV", "NL", "PL", "PT", "RO",
              "SK", "ES", "SE", "GB", "UA"]
ALSI_AREAS = ["eu", "GB"]
GIE_PAUSE = 1.1  # seconds between requests: the API allows about 60 a minute

GIE_INDICATORS = [
    indicator("gas_storage_fill", "Gas storage fill, daily", "How full underground gas storage is, as a share of "
              "its working capacity, at the start of each gas day. GIE AGSI+.", "percent", "energy", "gie_agsi",
              "agsi:full", decimals=1, default_on=False, bounds=(0, 110), frequency="D"),
    indicator("gas_storage_twh", "Gas in storage, daily", "Working gas in underground storage, in terawatt hours. "
              "GIE AGSI+.", "TWh", "energy", "gie_agsi", "agsi:gasInStorage", decimals=1, default_on=False,
              bounds=(0, 2000), frequency="D"),
    indicator("gas_storage_capacity_twh", "Gas storage working capacity", "The working gas volume storage can "
              "hold, in terawatt hours. GIE AGSI+.", "TWh", "energy", "gie_agsi", "agsi:workingGasVolume",
              decimals=1, default_on=False, bounds=(0, 2000), frequency="D"),
    indicator("lng_stock", "LNG in terminal tanks, daily", "Liquefied natural gas held in import terminal tanks, "
              "thousand cubic metres of LNG. GIE ALSI.", "thousand m3 LNG", "energy", "gie_agsi", "alsi:lngInventory",
              decimals=0, default_on=False, bounds=(0, 1e6), frequency="D"),
    indicator("lng_stock_fill", "LNG terminal tanks fill, daily", "LNG in terminal tanks as a share of the declared "
              "maximum. GIE ALSI.", "percent", "energy", "gie_agsi", "alsi:lngInventory/dtmi", decimals=1,
              default_on=False, bounds=(0, 110), frequency="D"),
]


def area_entity(code: str) -> tuple[str, str]:
    """(scheme, code) for a GIE or JODI area code."""
    return ("iso3", "eu") if code.lower() in ("eu", "eu27", "xm") else ("iso2", code.upper())


class GIEStorage(Connector):
    source_id = "gie_agsi"
    switch = "markets_daily"
    needs_env = ("GIE_API_KEY",)
    keeps_files = True  # finished years stay; only the current one is fetched again
    fetch_version = 1

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("GIE_API_KEY")
        this_year = date.today().year
        n = 0
        for api, url, areas in (("agsi", AGSI_URL, AGSI_AREAS), ("alsi", ALSI_URL, ALSI_AREAS)):
            for area in areas:
                for y in range(GIE_FIRST[api], this_year + 1):
                    name = f"{api}_{area}_{y}.json"
                    if y < this_year - (1 if date.today().month == 1 else 0) and self.earlier_copy(raw_dir, name):
                        continue  # a finished year, already stored
                    data = self._year(url, key, area, y)
                    (raw_dir / name).write_text(json.dumps(data), encoding="utf-8")
                    n += 1
                    if n % 25 == 0:
                        log.info("gie_agsi: %d files so far (%s %s %s)", n, api, area, y)
        return f"GIE AGSI+ and ALSI, {n} area-years fetched"

    def _year(self, url: str, key: str, area: str, y: int) -> list[dict]:
        out, page = [], 1
        where = {"type": "eu"} if area == "eu" else {"country": area}
        while True:
            params = {**where, "from": f"{y}-01-01", "to": f"{y}-12-31", "size": 300, "page": page}
            time.sleep(GIE_PAUSE)
            r = self.client.get(url, params=params, headers={"x-key": key})
            if r.status_code in (401, 403):
                raise ConnectorError("gie_agsi: the GIE API refused the key (check GIE_API_KEY in .env)")
            if r.status_code == 429:
                time.sleep(60)
                continue
            if r.status_code != 200:
                raise ConnectorError(f"gie_agsi: {url} {area} {y} returned HTTP {r.status_code}")
            self.downloaded_bytes += len(r.content)
            body = r.json()
            out += body.get("data") or []
            if page >= int(body.get("last_page") or 1):
                return out
            page += 1

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = DatedRows()
        for f in sorted(raw_dir.glob("*.json")):
            parts = f.stem.split("_")
            if len(parts) != 3 or parts[0] not in ("agsi", "alsi"):
                continue
            api, area = parts[0], parts[1]
            scheme, code = area_entity(area)
            for r in json.loads(f.read_text(encoding="utf-8")):
                d = parse_day(r.get("gasDayStart"))
                if not d:
                    continue
                if api == "agsi":
                    rows.add(scheme, code, "gas_storage_fill", d, num(r.get("full")))
                    rows.add(scheme, code, "gas_storage_twh", d, num(r.get("gasInStorage")))
                    rows.add(scheme, code, "gas_storage_capacity_twh", d, num(r.get("workingGasVolume")))
                else:
                    inv = r.get("lngInventory")
                    inv = num(inv.get("lng") if isinstance(inv, dict) else inv)
                    cap = r.get("dtmi")
                    cap = num(cap.get("lng") if isinstance(cap, dict) else cap)
                    rows.add(scheme, code, "lng_stock", d, inv)
                    if inv is not None and cap:
                        rows.add(scheme, code, "lng_stock_fill", d, 100 * inv / cap)
        if not len(rows):
            raise ConnectorError(f"gie_agsi: no values read from {raw_dir}")
        self.listed_indicators = GIE_INDICATORS
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------- US stocks (EIA)
EIA_URL = "https://api.eia.gov/v2/seriesid/{sid}?api_key={key}&length=5000&offset={offset}"
EIA_SERIES = {
    "NG.NW2_EPG0_SWO_R48_BCF.W": ("us_gas_storage", "US working gas in storage, weekly", "billion cubic feet",
                                  "Working natural gas in underground storage in the lower 48 states, end of week."),
    "PET.WCESTUS1.W": ("us_crude_stocks", "US commercial crude oil stocks, weekly", "thousand barrels",
                       "US crude oil stocks, not counting the Strategic Petroleum Reserve, end of week."),
    "PET.WCSSTUS1.W": ("us_spr_stocks", "US Strategic Petroleum Reserve, weekly", "thousand barrels",
                       "Crude oil in the US Strategic Petroleum Reserve, end of week."),
    "PET.WGTSTUS1.W": ("us_gasoline_stocks", "US motor gasoline stocks, weekly", "thousand barrels",
                       "US stocks of motor gasoline (all grades, with blending components), end of week."),
    "PET.WDISTUS1.W": ("us_distillate_stocks", "US distillate fuel oil stocks, weekly", "thousand barrels",
                       "US stocks of distillate fuel oil (diesel and heating oil), end of week."),
    "PET.WKJSTUS1.W": ("us_jet_stocks", "US jet fuel stocks, weekly", "thousand barrels",
                       "US stocks of kerosene-type jet fuel, end of week."),
}


class EIAStocks(Connector):
    source_id = "eia"
    needs_env = ("EIA_API_KEY",)
    fetch_every_days = 3

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("EIA_API_KEY")
        for sid in EIA_SERIES:
            data, offset = [], 0
            while True:
                tmp = raw_dir / "_page.json"
                try:
                    self.get(EIA_URL.format(sid=sid, key=key, offset=offset), tmp, cached=False)
                except ConnectorError as exc:
                    if "HTTP 403" in str(exc) or "HTTP 401" in str(exc):
                        raise ConnectorError("eia: the EIA API refused the key (check EIA_API_KEY in .env)") from exc
                    raise
                body = json.loads(tmp.read_text(encoding="utf-8"))
                tmp.unlink()
                page = (body.get("response") or {}).get("data") or []
                data += page
                total = int((body.get("response") or {}).get("total") or 0)
                offset += len(page)
                if not page or offset >= total:
                    break
                time.sleep(0.5)
            (raw_dir / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")
            time.sleep(0.5)
        return f"EIA API v2, {len(EIA_SERIES)} weekly series"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = DatedRows()
        for sid, (ind, *_rest) in EIA_SERIES.items():
            p = raw_dir / f"{sid}.json"
            if not p.exists():
                continue
            for r in json.loads(p.read_text(encoding="utf-8")):
                d = parse_day(r.get("period"))
                if d:
                    rows.add("iso3", "USA", ind, d, num(r.get("value")))
        if not len(rows):
            raise ConnectorError(f"eia: no values read from {raw_dir}")
        self.listed_indicators = [indicator(ind, name, desc + " US EIA.", unit, "energy", self.source_id, sid,
                                            decimals=0, default_on=False, bounds=(0, 1e7), frequency="W")
                                  for sid, (ind, name, unit, desc) in EIA_SERIES.items()]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------------- JODI
JODI_FILES = {
    "jodi_oil_primary.zip": "https://www.jodidata.org/_resources/files/downloads/oil-data/world_primary_csv.zip",
    "jodi_oil_secondary.zip": "https://www.jodidata.org/_resources/files/downloads/oil-data/world_secondary_csv.zip",
    "jodi_gas.zip": "https://www.jodidata.org/_resources/files/downloads/gas-data/jodi_gas_csv_beta.zip",
}
# (product, flow, unit) -> indicator
JODI_KEEP = {
    ("CRUDEOIL", "CLOSTLV", "KBBL"): "jodi_crude_stocks",
    ("TOTPRODS", "CLOSTLV", "KBBL"): "jodi_product_stocks",
    ("TOTPRODS", "TOTDEMO", "KBD"): "jodi_product_demand",
    ("NATGAS", "CLOSTLV", "M3"): "jodi_gas_stocks",
    ("NATGAS", "TOTDEMO", "M3"): "jodi_gas_demand",
}
JODI_INDICATORS = [
    indicator("jodi_crude_stocks", "Crude oil stocks, monthly", "Closing stocks of crude oil at the end of each "
              "month, thousand barrels. JODI Oil.", "thousand barrels", "energy", "jodi", "CRUDEOIL/CLOSTLV/KBBL",
              decimals=0, default_on=False, bounds=(0, 1e7), frequency="M"),
    indicator("jodi_product_stocks", "Oil product stocks, monthly", "Closing stocks of all oil products (petrol, "
              "diesel, jet fuel, fuel oil and others) at the end of each month, thousand barrels. JODI Oil.",
              "thousand barrels", "energy", "jodi", "TOTPRODS/CLOSTLV/KBBL", decimals=0, default_on=False,
              bounds=(0, 1e7), frequency="M"),
    indicator("jodi_product_demand", "Oil product demand, monthly", "Demand for all oil products, thousand barrels a "
              "day. JODI Oil.", "thousand barrels a day", "energy", "jodi", "TOTPRODS/TOTDEMO/KBD", decimals=1,
              default_on=False, bounds=(0, 1e5), frequency="M"),
    indicator("jodi_product_days", "Oil product stocks, days of demand", "Closing stocks of oil products divided by "
              "that month's daily demand: how many days the stocks would last. Worked out from JODI Oil.", "days",
              "energy", "jodi", "TOTPRODS stocks / demand", decimals=0, default_on=False, bounds=(0, 3650),
              frequency="M"),
    indicator("jodi_gas_stocks", "Natural gas stocks, monthly", "Closing stocks of natural gas at the end of each "
              "month, million cubic metres. JODI Gas.", "million m3", "energy", "jodi", "NATGAS/CLOSTLV/M3",
              decimals=0, default_on=False, bounds=(0, 1e7), frequency="M"),
    indicator("jodi_gas_demand", "Natural gas demand, monthly", "Natural gas demand in each month, million cubic "
              "metres. JODI Gas.", "million m3", "energy", "jodi", "NATGAS/TOTDEMO/M3", decimals=0, default_on=False,
              bounds=(0, 1e7), frequency="M"),
]


class JODI(Connector):
    source_id = "jodi"
    fetch_every_days = 14

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got, failed = [], []
        for name, url in JODI_FILES.items():
            try:
                self.get(url, raw_dir / name)
                got.append(url)
            except ConnectorError as exc:
                failed.append(f"{name} ({exc})")
        if not got:
            raise ConnectorError("jodi: nothing downloaded: " + "; ".join(failed))
        if failed:
            log.warning("jodi: %s", "; ".join(failed))
        return " ".join(got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = DatedRows()
        stocks: dict[tuple[str, date], float] = {}
        demand: dict[tuple[str, date], float] = {}
        names = [n for n in JODI_FILES] + [f.name for f in raw_dir.iterdir() if f.suffix.lower() in (".zip", ".csv")
                                           and f.name not in JODI_FILES]
        for name in names:
            p = raw_dir / name
            if not p.exists():
                p = self.earlier_copy(raw_dir, name) or p
            if not p.exists():
                continue
            for r in jodi_rows(p):
                k = (key_up(r.get("ENERGY_PRODUCT")), key_up(r.get("FLOW_BREAKDOWN")), key_up(r.get("UNIT_MEASURE")))
                ind = JODI_KEEP.get(k)
                if not ind:
                    continue
                d = parse_day(f"{str(r.get('TIME_PERIOD', '')).strip()[:7]}-01")
                v = num(r.get("OBS_VALUE"))
                area = str(r.get("REF_AREA") or "").strip()
                if not d or v is None or not area:
                    continue
                scheme, code = area_entity(area)
                rows.add(scheme, code, ind, d, v, freq="M")
                if ind == "jodi_product_stocks":
                    stocks[(area, d)] = v
                elif ind == "jodi_product_demand":
                    demand[(area, d)] = v
        for (area, d), s in stocks.items():
            dem = demand.get((area, d))
            if dem and dem > 0:
                scheme, code = area_entity(area)
                rows.add(scheme, code, "jodi_product_days", d, s / dem, freq="M")
        if not len(rows):
            raise ConnectorError(f"jodi: no stocks read from {raw_dir}")
        self.listed_indicators = JODI_INDICATORS
        return rows.stage(con, self.source_id, vintage)


def key_up(v) -> str:
    return str(v or "").strip().upper()


def jodi_rows(path: Path):
    """The rows of a JODI CSV, or of every CSV inside a JODI zip, as dicts."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith(".csv"):
                    with z.open(n) as fh:
                        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace"))
    else:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            yield from csv.DictReader(fh)
