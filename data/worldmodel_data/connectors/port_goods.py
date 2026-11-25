"""What goes through each port: goods by kind and trading partner, port by port.

Every source writes the history table port_goods: one row per port, period, direction
(in or out) and either a kind of goods (partner '') or a partner country (goods 'TOTAL').
Tonnes and, where the source gives it, value in the source's currency.

statsnz_port_trade
    Stats NZ overseas merchandise trade by New Zealand port (sea ports and airports), HS10
    by country by port, one zip a year from 2015 (about 28 MB each). Each year is cut down
    to HS chapters and partner countries month by month as soon as it is fetched (the zip is
    then dropped); finished years are not fetched again. Values in NZ dollars (exports fob,
    imports vfd), gross weight in tonnes.
eurostat_port_goods
    Eurostat maritime transport of goods, quarterly, for the main ports of each reporting
    country in Europe (mar_go_qm_<country>): thousand tonnes by type of cargo (liquid bulk,
    dry bulk, containers, ro-ro, other) and by partner country, from 2019.
dft_port_freight
    UK Department for Transport port freight statistics, PORT0499 (the port level downloadable
    dataset, yearly from 2000): tonnes by major port, direction, cargo group and country of
    load or unload. The link changes with each release, so it is read from the PORT tables page.
census_port_trade
    US Census Bureau international trade by US port (Census API, needs the free
    CENSUS_API_KEY): monthly value and shipping weight carried by ship, by HS chapter, from 2019.
bitre_sea_freight
    Australia's Bureau of Infrastructure and Transport Research Economics, Australian sea
    freight (yearly): value and tonnes for the top ten ports for exports and for imports, by
    financial year. Australia publishes no goods-by-port table openly.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import re
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import num, xlsx_rows
from worldmodel_data.connectors.transport import EU_GEO, iso3_of, jsonstat_rows

log = logging.getLogger(__name__)
SWITCH = "port_goods_fetch"
FIRST_YEAR = 2019
COLUMNS = ("country_code", "port_code", "port", "period", "freq", "direction", "goods", "goods_name", "partner",
           "tonnes", "value", "currency")
PG_DDL = ("CREATE TABLE pg (country_code VARCHAR, port_code VARCHAR, port VARCHAR, period DATE, freq VARCHAR, "
          "direction VARCHAR, goods VARCHAR, goods_name VARCHAR, partner VARCHAR, tonnes DOUBLE, value DOUBLE, "
          "currency VARCHAR)")

# Short names of the HS chapters (two-digit codes), for NZ and US figures.
HS2 = {
    "01": "Live animals", "02": "Meat", "03": "Fish and seafood", "04": "Dairy, eggs and honey", "05": "Other animal products",
    "06": "Plants and flowers", "07": "Vegetables", "08": "Fruit and nuts", "09": "Coffee, tea and spices", "10": "Cereals",
    "11": "Flour and malt", "12": "Oil seeds", "13": "Gums and resins", "14": "Other plant products", "15": "Fats and oils",
    "16": "Meat and fish preparations", "17": "Sugar", "18": "Cocoa", "19": "Cereal foods and baked goods",
    "20": "Vegetable and fruit preparations", "21": "Other food preparations", "22": "Drinks", "23": "Animal feed and food waste",
    "24": "Tobacco", "25": "Salt, stone and cement", "26": "Ores", "27": "Oil, gas and coal", "28": "Inorganic chemicals",
    "29": "Organic chemicals", "30": "Medicines", "31": "Fertilisers", "32": "Dyes and paints", "33": "Perfumes and cosmetics",
    "34": "Soap and waxes", "35": "Proteins and glues", "36": "Explosives", "37": "Photographic goods",
    "38": "Other chemical products", "39": "Plastics", "40": "Rubber", "41": "Hides and skins", "42": "Leather goods",
    "43": "Furs", "44": "Wood and logs", "45": "Cork", "46": "Basketwork", "47": "Wood pulp", "48": "Paper",
    "49": "Books and printed matter", "50": "Silk", "51": "Wool", "52": "Cotton", "53": "Other plant fibres",
    "54": "Man-made filaments", "55": "Man-made fibres", "56": "Wadding and rope", "57": "Carpets", "58": "Special fabrics",
    "59": "Coated fabrics", "60": "Knitted fabrics", "61": "Knitted clothing", "62": "Clothing (not knitted)",
    "63": "Other textile articles", "64": "Footwear", "65": "Hats", "66": "Umbrellas", "67": "Feathers and artificial flowers",
    "68": "Stone and cement articles", "69": "Ceramics", "70": "Glass", "71": "Gold, gems and jewellery", "72": "Iron and steel",
    "73": "Iron and steel articles", "74": "Copper", "75": "Nickel", "76": "Aluminium", "78": "Lead", "79": "Zinc", "80": "Tin",
    "81": "Other base metals", "82": "Tools", "83": "Metal articles", "84": "Machinery", "85": "Electrical equipment",
    "86": "Railway equipment", "87": "Vehicles", "88": "Aircraft", "89": "Ships and boats", "90": "Instruments",
    "91": "Clocks and watches", "92": "Musical instruments", "93": "Arms", "94": "Furniture", "95": "Toys and games",
    "96": "Other manufactured goods", "97": "Art and antiques", "98": "Special items", "99": "Other or confidential",
}
# Eurostat types of cargo (main groups only).
EU_CARGO = {"LBK": "Liquid bulk", "DBK": "Dry bulk", "LCNT": "Large containers", "RO_MSP": "Ro-ro, self-propelled",
            "RO_MNSP": "Ro-ro, not self-propelled", "OTH": "Other general cargo", "UNK": "Unknown cargo"}


def hs2_name(code: str) -> str:
    return HS2.get(code, f"HS {code}")


def _period(y: int, m: int = 1) -> date:
    return date(y, m, 1)


def write_rows(path: Path, rows: list[tuple]) -> int:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(rows)
    return len(rows)


def load_rows(con: duckdb.DuckDBPyConnection, files: list[Path]) -> int:
    """Every file written by write_rows into table pg (made here); later files win over earlier
    ones for the same port, period, direction, goods and partner."""
    con.execute(PG_DDL)
    if files:
        types = {c: "VARCHAR" for c in COLUMNS} | {"tonnes": "DOUBLE", "value": "DOUBLE"}
        con.execute(f"""
            INSERT INTO pg SELECT country_code, port_code, port, try_cast(period AS DATE), freq, direction, goods,
                   goods_name, coalesce(partner, ''), tonnes, value, currency
            FROM read_csv(?, header = true, columns = {types!r}, filename = true)
            WHERE try_cast(period AS DATE) IS NOT NULL AND (tonnes IS NOT NULL OR value IS NOT NULL)
            QUALIFY row_number() OVER (PARTITION BY port_code, period, freq, direction, goods, coalesce(partner, '')
                                       ORDER BY filename DESC) = 1""", [[f.as_posix() for f in files]])
    return con.execute("SELECT count(*) FROM pg").fetchone()[0]


class PortGoods(Connector):
    """Shared set-up: the Settings switch, files kept between vintages, a history table only."""
    switch = SWITCH
    fetch_every_days = 30
    keeps_files = True
    keep_vintages = 2

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def try_get(self, url: str, dest: Path, **kw) -> bool:
        try:
            self.get(url, dest, **kw)
            return dest.exists() and dest.stat().st_size > 0
        except Exception as exc:  # noqa: BLE001 - one missing file should not stop the rest
            log.info("%s: could not fetch %s (%s)", self.source_id, re.sub(r"(key)=[^&]+", r"\1=...", url), exc)
            dest.unlink(missing_ok=True)
            return False

    def have(self, raw_dir: Path, name: str) -> bool:
        last = self.last_vintage_dir(raw_dir)
        return bool(last and (last / name).exists())

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("port_goods_*.csv.gz"))
        n = load_rows(con, files)
        if not n:
            raise ConnectorError(f"{self.source_id}: no port goods rows in {raw_dir}")
        log.info("%s: %s rows, %s ports", self.source_id, n,
                 con.execute("SELECT count(DISTINCT port_code) FROM pg").fetchone()[0])
        self.history_queries = {"port_goods": "SELECT * FROM pg"}
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- Stats NZ
STATSNZ_ZIP = "https://www3.stats.govt.nz/HS10_by_country/{year}_HS10_by_Country_by_Port.zip"


def _nz_port_code(name: str) -> str:
    return "NZ:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def statsnz_rows(zip_path: Path, con: duckdb.DuckDBPyConnection | None = None) -> list[tuple]:
    """HS chapter and partner rows by port and month from one Stats NZ yearly zip (HS10 by country by
    port). Monthly CSVs are summed with DuckDB: a year is about 2 million lines."""
    own = con is None
    con = con or duckdb.connect()
    out: list[tuple] = []
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                name = info.filename
                low = name.lower()
                if not low.endswith(".csv"):
                    continue
                direction = "in" if "import" in low else "out" if "export" in low else None
                if not direction:
                    continue
                path = Path(tmp) / Path(name).name
                path.write_bytes(z.read(info))
                cols = [c.strip() for c in next(csv.reader(io.StringIO(path.open(encoding="utf-8-sig").readline())))]

                def col(*want: str) -> str | None:
                    for w in want:
                        for c in cols:
                            if c.lower().startswith(w.lower()):
                                return c
                    return None
                money = col("Total Exports ($NZD fob)", "Exports ($NZD fob)") if direction == "out" else col("Imports ($NZD vfd)")
                weight = col("Total Gross Weight", "Exports Gross Weight") if direction == "out" else col("Imports Gross Weight")
                port, country, hs, month = col("NZ Port"), col("Country"), col("Harmonised System Code"), col("Month")
                if not all((money, weight, port, country, hs, month)):
                    log.info("statsnz_port_trade: %s has unexpected columns %s", name, cols)
                    continue

                def n(c: str) -> str:
                    return f"try_cast(replace(CAST(\"{c}\" AS VARCHAR), ',', '') AS DOUBLE)"
                con.execute(f"CREATE OR REPLACE TEMP TABLE nz AS SELECT CAST(\"{month}\" AS VARCHAR) AS month, "
                            f"CAST(\"{port}\" AS VARCHAR) AS port, CAST(\"{country}\" AS VARCHAR) AS country, "
                            f"left(lpad(CAST(\"{hs}\" AS VARCHAR), 10, '0'), 2) AS hs2, {n(money)} AS value, {n(weight)} AS kg "
                            "FROM read_csv(?, header = true, all_varchar = true, quote = '\"')", [path.as_posix()])
                for m, p, h, v, kg in con.execute(
                        "SELECT month, port, hs2, sum(value), sum(kg) FROM nz GROUP BY ALL").fetchall():
                    d = _nz_month(m)
                    if d and p:
                        out.append(("NZL", _nz_port_code(p), p, d.isoformat(), "M", direction, h, hs2_name(h), "",
                                    round((kg or 0) / 1000, 3), v, "NZD"))
                for m, p, c, v, kg in con.execute(
                        "SELECT month, port, country, sum(value), sum(kg) FROM nz GROUP BY ALL").fetchall():
                    d, iso = _nz_month(m), iso3_of(c)
                    if d and p and iso and iso != "NZL":
                        out.append(("NZL", _nz_port_code(p), p, d.isoformat(), "M", direction, "TOTAL", "All goods", iso,
                                    round((kg or 0) / 1000, 3), v, "NZD"))
                path.unlink(missing_ok=True)
    finally:
        if own:
            con.close()
    return out


def _nz_month(v) -> date | None:
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) >= 6 and 1 <= int(s[4:6]) <= 12:
        return date(int(s[:4]), int(s[4:6]), 1)
    return None


class StatsNZPortTrade(PortGoods):
    source_id = "statsnz_port_trade"

    def download(self, raw_dir: Path, release: str) -> str:
        this = date.today().year
        got = 0
        for y in range(FIRST_YEAR, this + 1):
            name = f"port_goods_{y}.csv.gz"
            if y < this - 1 and self.have(raw_dir, name):
                continue  # carried over by keeps_files
            zp = raw_dir / f"_{y}.zip"
            if not self.try_get(STATSNZ_ZIP.format(year=y), zp):
                continue
            try:
                rows = statsnz_rows(zp)
            except zipfile.BadZipFile:
                log.info("statsnz_port_trade: %s is not a zip file", zp.name)
                rows = []
            zp.unlink(missing_ok=True)
            if rows:
                write_rows(raw_dir / name, rows)
                got += 1
        if not got and not self.last_vintage_dir(raw_dir):
            raise ConnectorError("statsnz_port_trade: no yearly by-port file could be read")
        return STATSNZ_ZIP.format(year="{year}")


# ----------------------------------------------------------------------------- Eurostat
EU_PORT_COUNTRIES = ("be", "bg", "dk", "de", "ee", "ie", "el", "es", "fr", "hr", "it", "cy", "lv", "lt", "mt", "nl", "pl",
                     "pt", "ro", "si", "fi", "se", "no", "me", "tr")
EU_DATA = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}?{query}"


def eu_iso3(code: str) -> str | None:
    code = (code or "").upper()
    if code in EU_GEO:
        return EU_GEO[code]
    if len(code) != 2:
        return None
    from worldmodel_data.connectors.tabular import entity_for
    ent = entity_for("iso2", code)
    return ent if ent and len(ent) == 3 else None


def _quarter(t: str) -> date | None:
    m = re.match(r"(\d{4})-?Q([1-4])", t or "")
    return date(int(m[1]), 3 * int(m[2]) - 2, 1) if m else None


def eurostat_rows(body: dict, what: str) -> list[tuple]:
    """Rows from one mar_go_qm_<country> answer: 'cargo' (types of cargo, all partners) or
    'partner' (all cargo, by partner country). Ports only (codes like NL_0NLRTM)."""
    labels = ((body.get("dimension") or {}).get("rep_mar") or {}).get("category", {}).get("label") or {}
    out = []
    for cell, v in jsonstat_rows(body):
        port = cell.get("rep_mar") or ""
        if "_" not in port or cell.get("unit") not in (None, "THS_T"):
            continue
        d = _quarter(cell.get("time") or "")
        direction = {"IN": "in", "OUT": "out"}.get(cell.get("direct") or "")
        if not d or not direction:
            continue
        iso = eu_iso3(port.split("_")[0])
        name = labels.get(port) or port
        if what == "cargo":
            cargo = cell.get("cargo") or ""
            if cargo not in EU_CARGO or cell.get("par_mar") not in (None, "TOTAL"):
                continue
            out.append((iso, f"EU:{port}", name, d.isoformat(), "Q", direction, cargo, EU_CARGO[cargo], "", v * 1000, None, None))
        else:
            partner = eu_iso3(cell.get("par_mar") or "")
            if not partner or partner == iso or cell.get("cargo") not in (None, "TOTAL"):
                continue
            out.append((iso, f"EU:{port}", name, d.isoformat(), "Q", direction, "TOTAL", "All goods", partner, v * 1000,
                        None, None))
    return out


class EurostatPortGoods(PortGoods):
    source_id = "eurostat_port_goods"
    keeps_files = False  # each fetch asks for every quarter since 2019 again (they get revised)

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for c in EU_PORT_COUNTRIES:
            code = f"mar_go_qm_{c}"
            base = [("sinceTimePeriod", f"{FIRST_YEAR}-Q1"), ("direct", "IN"), ("direct", "OUT"), ("unit", "THS_T")]
            asks = {"cargo": base + [("par_mar", "TOTAL")] + [("cargo", k) for k in EU_CARGO],
                    "partner": base + [("cargo", "TOTAL")]}
            rows = []
            for what, q in asks.items():
                dest = raw_dir / f"_{code}_{what}.json"
                if self.try_get(EU_DATA.format(code=code, query=urlencode(q)), dest):
                    try:
                        body = json.loads(dest.read_text(encoding="utf-8"))
                        if body.get("error"):
                            log.info("eurostat_port_goods: %s %s: %s", code, what, body["error"])
                        else:
                            rows += eurostat_rows(body, what)
                    except json.JSONDecodeError:
                        log.info("eurostat_port_goods: %s %s was not JSON", code, what)
                dest.unlink(missing_ok=True)
                time.sleep(0.5)
            if rows:
                write_rows(raw_dir / f"port_goods_{c}.csv.gz", rows)
                got += 1
        if not got:
            raise ConnectorError("eurostat_port_goods: no country's port figures could be read")
        return EU_DATA.format(code="mar_go_qm_<country>", query="")


# ----------------------------------------------------------------------------- UK DfT
DFT_PAGE = "https://www.gov.uk/government/statistical-data-sets/port-and-domestic-waterborne-freight-statistics-port"


def ods_rows(path: Path, sheet: str) -> list[list[str]]:
    """Cell text of one sheet of an OpenDocument spreadsheet, read as a stream (the PORT0499
    file is about 9 MB zipped and far bigger unzipped)."""
    from xml.etree.ElementTree import iterparse

    t = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    tx = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    rows: list[list[str]] = []
    with zipfile.ZipFile(path) as z, z.open("content.xml") as fh:
        inside = False
        for ev, el in iterparse(fh, events=("start", "end")):
            if el.tag == f"{t}table":
                if ev == "start":
                    inside = (el.get(f"{t}name") or "").lower() == sheet.lower()
                elif inside:
                    break
                continue
            if not inside or ev != "end" or el.tag != f"{t}table-row":
                continue
            cells: list[str] = []
            for c in el:
                if c.tag not in (f"{t}table-cell", f"{t}covered-table-cell"):
                    continue
                text = c.get("{urn:oasis:names:tc:opendocument:xmlns:office:1.0}value") or \
                    " ".join("".join(p.itertext()) for p in c.iter(f"{tx}p"))
                rep = min(int(c.get(f"{t}number-columns-repeated") or 1), 50)
                cells.extend([text] * rep)
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(cells)
            el.clear()
    return rows


def dft_rows(path: Path) -> list[tuple]:
    """Cargo group and partner country rows by UK major port and year from PORT0499."""
    rows = ods_rows(path, "port0499")
    head_i = next((i for i, r in enumerate(rows) if r and r[0].lower().startswith("year") and
                   any("major port" in c.lower() for c in r) and any("tonnage" in c.lower() for c in r) and
                   not any("total of filtered" in c.lower() for c in r)), None)
    if head_i is None:
        raise ConnectorError(f"dft_port_freight: no header row (Year, Major Port, ... Tonnage) in {path.name}")
    head = [c.lower() for c in rows[head_i]]

    def col(word: str) -> int | None:
        return next((i for i, h in enumerate(head) if word in h), None)
    iy, ip, ic, idr, ig, it = col("year"), col("major port"), col("country"), col("direction"), col("cargo group"), col("tonnage")
    goods: dict[tuple, float] = defaultdict(float)
    partners: dict[tuple, float] = defaultdict(float)
    for r in rows[head_i + 1:]:
        if len(r) <= max(iy, ip, idr, ig, it):
            continue
        y = num(r[iy])
        direction = "in" if r[idr].lower().startswith("in") else "out" if r[idr].lower().startswith("out") else None
        v = 0.0 if r[it].strip().upper() == "LOW" else num(r[it])
        if not y or not direction or v is None or not r[ip]:
            continue
        port = r[ip].strip()
        goods[(port, int(y), direction, r[ig].strip() or "Other")] += v * 1000
        iso = iso3_of(r[ic]) if ic is not None and ic < len(r) else None
        if iso and iso != "GBR":
            partners[(port, int(y), direction, iso)] += v * 1000
    code = lambda p: "UK:" + re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-")
    out = [("GBR", code(p), p, _period(y).isoformat(), "A", d, re.sub(r"[^a-z0-9]+", "_", g.lower()).strip("_"), g, "",
            round(t, 1), None, None) for (p, y, d, g), t in goods.items()]
    out += [("GBR", code(p), p, _period(y).isoformat(), "A", d, "TOTAL", "All goods", iso, round(t, 1), None, None)
            for (p, y, d, iso), t in partners.items()]
    return out


class DfTPortFreight(PortGoods):
    source_id = "dft_port_freight"
    keeps_files = False

    def download(self, raw_dir: Path, release: str) -> str:
        page = raw_dir / "_port_tables.html"
        self.get(DFT_PAGE, page, cached=False)
        html = page.read_text(encoding="utf-8", errors="replace")
        page.unlink(missing_ok=True)
        m = re.search(r'href="([^"]*port0499\.ods)"', html, re.IGNORECASE)
        if not m:
            raise ConnectorError("dft_port_freight: no PORT0499 link on the PORT tables page (has it moved?)")
        url = urljoin(DFT_PAGE, m[1])
        ods = raw_dir / "_port0499.ods"
        self.get(url, ods)
        rows = dft_rows(ods)
        ods.unlink(missing_ok=True)
        write_rows(raw_dir / "port_goods_uk.csv.gz", rows)
        return url


# ----------------------------------------------------------------------------- US Census
CENSUS_PORTS = "https://api.census.gov/data/timeseries/intltrade/{way}/porths"
CENSUS_ASK = {"exports": ("E_COMMODITY", "out"), "imports": ("I_COMMODITY", "in")}


def census_rows(body: list, way: str) -> list[tuple]:
    """HS chapter rows by US port for one month: value and weight carried by ship (kg to tonnes)."""
    if not body or len(body) < 2:
        return []
    head = [h.upper() for h in body[0]]
    comm, direction = CENSUS_ASK[way]
    ix = {h: i for i, h in enumerate(head)}
    need = ("PORT", "PORT_NAME", comm, "VES_VAL_MO", "VES_WGT_MO", "time")
    if any(n.upper() not in ix for n in need):
        return []
    out = []
    for r in body[1:]:
        hs = str(r[ix[comm]] or "")
        m = re.match(r"(\d{4})-(\d{2})", str(r[ix["TIME"]] or ""))
        val, kg = num(r[ix["VES_VAL_MO"]]), num(r[ix["VES_WGT_MO"]])
        if len(hs) != 2 or not m or not (val or kg):
            continue
        port = str(r[ix["PORT"]] or "")
        out.append(("USA", f"US:{port}", (r[ix["PORT_NAME"]] or port).strip(), date(int(m[1]), int(m[2]), 1).isoformat(),
                    "M", direction, hs, hs2_name(hs), "", round((kg or 0) / 1000, 3), val, "USD"))
    return out


class CensusPortTrade(PortGoods):
    source_id = "census_port_trade"
    needs_env = ("CENSUS_API_KEY",)

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("CENSUS_API_KEY")
        today = date.today()
        got = 0
        for y in range(FIRST_YEAR, today.year + 1):
            name = f"port_goods_{y}.csv.gz"
            if y < today.year - 1 and self.have(raw_dir, name):
                continue
            rows: list[tuple] = []
            for m in range(1, 13):
                if (y, m) >= (today.year, today.month):
                    break
                for way, (comm, _d) in CENSUS_ASK.items():
                    q = urlencode({"get": f"PORT,PORT_NAME,{comm},VES_VAL_MO,VES_WGT_MO", "COMM_LVL": "HS2",
                                   "time": f"{y}-{m:02d}", "key": key})
                    dest = raw_dir / f"_{way}_{y}_{m:02d}.json"
                    if self.try_get(f"{CENSUS_PORTS.format(way=way)}?{q}", dest, cached=False):
                        try:
                            rows += census_rows(json.loads(dest.read_text(encoding="utf-8")), way)
                        except json.JSONDecodeError:
                            log.info("census_port_trade: %s %s-%02d gave no table (is CENSUS_API_KEY right?)", way, y, m)
                    dest.unlink(missing_ok=True)
                    time.sleep(0.2)
            if rows:
                write_rows(raw_dir / name, rows)
                got += 1
        if not got and not self.last_vintage_dir(raw_dir):
            raise ConnectorError("census_port_trade: the Census API gave nothing (is CENSUS_API_KEY right?)")
        return CENSUS_PORTS.format(way="{exports,imports}")


# ----------------------------------------------------------------------------- Australia BITRE
BITRE_MARITIME = "https://www.bitre.gov.au/maritime"


def bitre_top_ports(rows: list[list], what: str) -> list[tuple]:
    """Port rows from BITRE's Table 1.3 (value, $ billion) or 1.4 (weight, million tonnes): an
    Exports block and an Imports block, each under a header row of port names."""
    out = []
    ports: list[str] = []
    direction = None
    for r in rows:
        cells = ["" if c is None else str(c).strip() for c in r]
        if not any(cells):
            continue
        first = cells[0].lower()
        names = [c for c in cells[1:] if c]
        if names and not any(num(c) is not None for c in names) and (first.startswith("financial") or not first) \
                and not any("(" in c for c in names):
            ports = cells[1:]
            continue
        if first.startswith("exports"):
            direction = "out"
            continue
        if first.startswith("imports"):
            direction = "in"
            continue
        m = re.match(r"(\d{4})\D+(\d{2,4})$", cells[0])
        if not m or not direction or not ports:
            continue
        end = int(m[1]) + 1
        for name, v in zip(ports, cells[1:]):
            v = num(v)
            if not name or v is None or name.lower().startswith("all ports") or "various" in name.lower() or \
                    name.lower().startswith("other"):
                continue
            code = "AU:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            tonnes, value = (v * 1e6, None) if what == "weight" else (None, v * 1e9)
            out.append(("AUS", code, name, date(end, 6, 30).isoformat(), "FY", direction, "TOTAL", "All goods", "",
                        tonnes, value, "AUD" if value is not None else None))
    return out


class BITRESeaFreight(PortGoods):
    source_id = "bitre_sea_freight"
    keeps_files = False
    fetch_every_days = 60

    def download(self, raw_dir: Path, release: str) -> str:
        page = raw_dir / "_maritime.html"
        self.get(BITRE_MARITIME, page, cached=False)
        m = re.search(r'href="([^"]*australian-sea-freight-[^"]*)"', page.read_text(encoding="utf-8", errors="replace"))
        page.unlink(missing_ok=True)
        if not m:
            raise ConnectorError("bitre_sea_freight: no Australian sea freight link on the maritime page")
        res = urljoin(BITRE_MARITIME, m[1])
        page = raw_dir / "_asf.html"
        self.get(res, page, cached=False)
        z = re.search(r'href="([^"]*chapter-1\.zip)"', page.read_text(encoding="utf-8", errors="replace"))
        page.unlink(missing_ok=True)
        if not z:
            raise ConnectorError(f"bitre_sea_freight: no chapter 1 tables on {res}")
        zp = raw_dir / "_chapter1.zip"
        self.get(urljoin(res, z[1]), zp)
        rows = bitre_rows(zp, raw_dir)
        zp.unlink(missing_ok=True)
        write_rows(raw_dir / "port_goods_au.csv.gz", rows)
        return res


def bitre_rows(zip_path: Path, tmp_dir: Path) -> list[tuple]:
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = Path(info.filename).name.lower()
            what = "value" if base == "table 1.3.xlsx" else "weight" if base == "table 1.4.xlsx" else None
            if not what:
                continue
            p = tmp_dir / f"_{base.replace(' ', '_')}"
            p.write_bytes(z.read(info))
            out += bitre_top_ports(xlsx_rows(p), what)
            p.unlink(missing_ok=True)
    if not out:
        raise ConnectorError("bitre_sea_freight: no top ports in Tables 1.3 and 1.4")
    # Value and weight rows for the same port and year become one row.
    both: dict[tuple, list] = {}
    for r in out:
        k = r[:9]
        cur = both.setdefault(k, list(r))
        if r[9] is not None:
            cur[9] = r[9]
        if r[10] is not None:
            cur[10], cur[11] = r[10], r[11]
    return [tuple(v) for v in both.values()]
