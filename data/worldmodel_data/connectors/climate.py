"""Climate: temperatures, greenhouse gases, emissions in detail, ice and sea, El Niño and
the other ocean drivers, storm tracks, weather alerts, projections to 2100, climate
policy, and New Zealand's own series.

owid_co2
    Our World in Data's CO2 and greenhouse gas dataset (GitHub: owid/co2-data): emissions
    by country and year from the Global Carbon Project, Jones et al. and PRIMAP: CO2 by
    fuel, consumption-based CO2 (counted where goods are used), methane, nitrous oxide,
    all greenhouse gases, per person and per GDP, and each country's contribution to warming.
owid_climate
    Single OWID climate charts (ourworldindata.org/grapher/<slug>.csv): each country's
    yearly temperature against normal (Copernicus ERA5), sea level, ice sheets,
    ocean heat, greenhouse gases by sector (Climate Watch) and area burned by wildfires
    (GWIS). A chart that has gone only warns.
noaa_gml
    NOAA Global Monitoring Laboratory: CO2 at Mauna Loa by month since 1958, and the
    global yearly means of CO2, methane and nitrous oxide.
nasa_gistemp
    NASA GISTEMP v4: the world's surface temperature against 1951-1980, yearly and monthly.
noaa_enso
    The El Niño index (NOAA's Oceanic Niño Index, three-month seasons since 1950), the
    Indian Ocean Dipole (NOAA PSL, HadISST) and the Southern Annular Mode (NOAA CPC).
    El Niño and La Niña episodes (five overlapping seasons at 0.5 °C or more from normal)
    become events of kind "enso" on the World, which charts can show as bands.
ibtracs
    NOAA IBTrACS: every tropical cyclone track since 1980 (one CSV), as a map layer of
    lines with each storm's name, year, basin, strongest category and whether it hit land.
gdacs
    GDACS (UN and EU): orange and red alerts for cyclones, floods, droughts, wildfires,
    earthquakes and volcanoes since 2000, as events for each country affected.
cckp
    World Bank Climate Change Knowledge Portal: CMIP6 projections of each country's
    yearly mean temperature and rainfall to 2100 under four scenarios (SSP1-2.6 to
    SSP5-8.5), the median of the models with the 10th and 90th percentiles.
net_zero_tracker
    Net Zero Tracker: each country's net zero target year and how firm it is (in law, in
    a policy document, a pledge). Saved by hand (the site's export).
carbon_pricing
    World Bank Carbon Pricing Dashboard: carbon taxes and emissions trading prices by
    jurisdiction and year (the NZ ETS among them). Saved by hand.
niwa_7station
    NIWA's seven-station temperature series for New Zealand since 1909. Saved by hand.
mfe_ghg
    Ministry for the Environment: New Zealand's greenhouse gas inventory by sector since
    1990. Saved by hand.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, stage_events
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.owid import GRAPHER, GRAPHER_QUERY, _OWID, column_id
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, is_country, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)


def _settings() -> dict:
    from worldmodel_contract.local import load_settings
    from worldmodel_data.config import paths
    return load_settings(paths().home)


class Points:
    """Values with their own date, frequency and variant (monthly series, projections)."""

    def __init__(self) -> None:
        self.rows: list[tuple] = []

    def add(self, code: str, ind: str, d: date, value: float | None, freq: str = "A", variant: str = "central",
            status: str = "E") -> None:
        if value is None or value != value or abs(value) == float("inf"):
            return
        self.rows.append((code, ind, d, freq, variant, float(value), status))

    def __len__(self) -> int:
        return len(self.rows)

    def stage(self, con: duckdb.DuckDBPyConnection, source_id: str, vintage: str, table: str = "pts") -> str:
        con.execute(f"CREATE TABLE {table} (source_code VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, "
                    "variant VARCHAR, value DOUBLE, status VARCHAR)")
        if self.rows:
            con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)", self.rows)
        return (f"SELECT {sql_str(source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, source_code, "
                f"indicator_id, period_start, freq, '' AS breakdown, variant, value, status FROM {table}")


class _Yearly(Connector):
    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()


def _csv_rows(path: Path) -> list[list[str]]:
    """A CSV with '#' comment lines (NOAA's style) as rows."""
    return [r for r in csv.reader(io.StringIO("\n".join(l for l in _lines(path) if l.strip() and not l.startswith("#"))))]


def _table(path: Path) -> list[list]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return xlsx_rows(path)
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))))


# ----------------------------------------------------------------------------- OWID CO2 and greenhouse gases
CO2_BASE = "https://raw.githubusercontent.com/owid/co2-data/master/"
CO2_FILES = ("owid-co2-data.csv", "owid-co2-codebook.csv")
# column -> (indicator id, name, unit, decimals, switched on). Totals carry "(GCP)" so they sit
# beside the World Bank's own figures of the same name rather than replace them.
CO2_COLUMNS = {
    "co2": ("co2_gcp", "CO2 emissions (GCP, million tonnes)", "million tonnes CO2", 1, True),
    "co2_per_capita": ("co2_per_capita_gcp", "CO2 emissions per person (GCP, tonnes)", "tonnes CO2 per person", 2, False),
    "co2_including_luc": ("co2_with_land_use", "CO2 emissions with land use change", "million tonnes CO2", 1, False),
    "land_use_change_co2": ("co2_land_use", "CO2 from land use change (forests cleared or planted)", "million tonnes CO2", 1, False),
    "consumption_co2": ("co2_consumption", "CO2 emissions counted where goods are used", "million tonnes CO2", 1, True),
    "consumption_co2_per_capita": ("co2_consumption_per_capita", "CO2 counted where goods are used, per person", "tonnes CO2 per person", 2, True),
    "trade_co2_share": ("co2_trade_share", "CO2 in net imports, % of emissions made at home", "%", 1, False),
    "co2_per_gdp": ("co2_per_gdp", "CO2 per dollar of GDP", "kg CO2 per dollar (PPP)", 3, False),
    "coal_co2": ("co2_coal", "CO2 from coal", "million tonnes CO2", 1, False),
    "oil_co2": ("co2_oil", "CO2 from oil", "million tonnes CO2", 1, False),
    "gas_co2": ("co2_gas", "CO2 from gas", "million tonnes CO2", 1, False),
    "cement_co2": ("co2_cement", "CO2 from cement", "million tonnes CO2", 1, False),
    "flaring_co2": ("co2_flaring", "CO2 from gas flaring", "million tonnes CO2", 1, False),
    "methane": ("methane_emissions", "Methane emissions (CO2 equivalent)", "million tonnes CO2e", 1, True),
    "nitrous_oxide": ("n2o_emissions", "Nitrous oxide emissions (CO2 equivalent)", "million tonnes CO2e", 1, True),
    "total_ghg": ("ghg_total_gcp", "Greenhouse gas emissions, all gases (PRIMAP)", "million tonnes CO2e", 1, True),
    "ghg_per_capita": ("ghg_per_capita", "Greenhouse gas emissions per person", "tonnes CO2e per person", 2, True),
    "cumulative_co2": ("co2_cumulative", "CO2 emitted since 1750", "million tonnes CO2", 0, False),
    "share_global_co2": ("co2_share_world", "Share of the world's CO2 emissions", "%", 2, True),
    "share_global_cumulative_co2": ("co2_share_cumulative", "Share of the world's CO2 since 1750", "%", 2, False),
    "temperature_change_from_ghg": ("warming_from_ghg", "Warming caused by the country's emissions", "°C", 4, False),
}


class OWIDCO2(_OWID):
    source_id = "owid_co2"
    switch = "climate_fetch"
    fetch_every_days = 60

    def download(self, raw_dir: Path, release: str) -> str:
        for name in CO2_FILES:
            self.get(CO2_BASE + name, raw_dir / name)
        return " ".join(CO2_BASE + n for n in CO2_FILES)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        data = raw_dir / CO2_FILES[0]
        if not data.exists():
            raise ConnectorError(f"owid_co2: {data.name} missing from {raw_dir}")
        book = {}
        if (raw_dir / CO2_FILES[1]).exists():
            with (raw_dir / CO2_FILES[1]).open(encoding="utf-8-sig", newline="") as f:
                book = {r["column"]: r for r in csv.DictReader(f)}
        with data.open(encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f))
        columns = {c: CO2_COLUMNS[c][0] for c in header if c in CO2_COLUMNS}
        if not columns:
            raise ConnectorError("owid_co2: none of the expected columns (co2, methane, total_ghg ...) found")
        con.execute("CREATE TABLE co2 (source_code VARCHAR, scheme VARCHAR, indicator_id VARCHAR, period_start DATE, value DOUBLE)")
        self._stage_wide(con, "co2", data, "country", "iso_code", "year", columns)
        out = []
        for col, ind in columns.items():
            _, name, unit, dec, on = CO2_COLUMNS[col]
            b = book.get(col, {})
            out.append(indicator(ind, name, (b.get("description") or name).strip()[:1200], unit, "climate", self.source_id, col,
                                 decimals=dec, default_on=on, notes=(b.get("source") or "Our World in Data, CO2 and greenhouse gas emissions")[:500],
                                 aggregation={"method": "sum"} if "million tonnes" in unit else None))
        self.listed_indicators = out
        return self._query(vintage, "co2")


# ----------------------------------------------------------------------------- OWID climate charts
# slug -> (indicator id for a one-column chart, or a prefix for several, domain, what it is)
CLIMATE_CHARTS = (
    ("annual-temperature-anomalies", "temp_anomaly", "ERA5: each country's yearly surface temperature against 1991-2020"),
    ("sea-level", "sea_level", "Global mean sea level against 1993-2008 (several reconstructions)"),
    ("ice-sheet-mass-balance", "ice_sheet_mass", "Greenland and Antarctic ice sheets: change in mass since 2002 (NASA GRACE)"),
    ("ocean-heat-content-upper", "ocean_heat", "Heat content of the top 700 m of the oceans (NOAA)"),
    ("ghg-emissions-by-sector", "ghg_sector", "Greenhouse gas emissions by sector (Climate Watch)"),
    ("annual-area-burnt-by-wildfires", "wildfire_area", "Area burned by wildfires each year (GWIS)"),
    ("arctic-sea-ice", "sea_ice_owid", "Arctic sea ice extent (NSIDC)"),
)
# For a chart with several columns, the one that takes the chart's own id (the others get prefix_column).
CLIMATE_MAIN = {"sea-level": "sea_level_average", "ocean-heat-content-upper": "ocean_heat_content_noaa_700m"}


def yearly_from_days(path: Path, dest: Path) -> bool:
    """A chart with a Day column (dates) as one with a Year column: the mean of each year's values."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        lower = [h.lower() for h in header]
        if "day" not in lower or "entity" not in lower:
            return False
        di, ei = lower.index("day"), lower.index("entity")
        ci = lower.index("code") if "code" in lower else None
        vals = [i for i, h in enumerate(lower) if h not in ("entity", "code", "day") and "annotation" not in h]
        sums: dict[tuple, list] = {}
        for row in r:
            if len(row) < len(header) or not re.match(r"\d{4}-", row[di]):
                continue
            k = (row[ei], row[ci] if ci is not None else "", row[di][:4])
            acc = sums.setdefault(k, [[0.0, 0] for _ in vals])
            for j, i in enumerate(vals):
                v = num(row[i])
                if v is not None:
                    acc[j][0] += v
                    acc[j][1] += 1
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Entity", "Code", "Year", *[header[i] for i in vals]])
        for (e, c, y), acc in sorted(sums.items()):
            w.writerow([e, c, y, *[(a / n if n else "") for a, n in acc]])
    return True


class OWIDClimate(_OWID):
    source_id = "owid_climate"
    stage_version = 2  # 2: dated charts as yearly means, renamed charts, last copy of a chart that failed
    switch = "climate_fetch"
    fetch_every_days = 30
    pause_seconds = 1.0

    def download(self, raw_dir: Path, release: str) -> str:
        got = []
        for i, (slug, _, _) in enumerate(CLIMATE_CHARTS):
            if i:
                time.sleep(self.pause_seconds)
            try:
                self.get(f"{GRAPHER}{slug}.csv{GRAPHER_QUERY}", raw_dir / f"{slug}.csv")
                self.get(f"{GRAPHER}{slug}.metadata.json{GRAPHER_QUERY}", raw_dir / f"{slug}.metadata.json")
                got.append(slug)
            except ConnectorError as exc:
                log.warning("owid_climate: chart %s skipped (%s)", slug, exc)
                for p in raw_dir.glob(f"{slug}.*"):
                    p.unlink()
        if not got:
            raise ConnectorError("owid_climate: none of the charts could be downloaded")
        return " ".join(f"{GRAPHER}{s}" for s in got)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        con.execute("CREATE TABLE charts (source_code VARCHAR, scheme VARCHAR, indicator_id VARCHAR, period_start DATE, value DOUBLE)")
        spec = {s: (p, about) for s, p, about in CLIMATE_CHARTS}
        out = []
        for slug in spec:
            path = raw_dir / f"{slug}.csv"
            if not path.exists():  # that chart failed to download this time: keep the last copy
                if not (path := self.earlier_copy(raw_dir, path.name)):
                    continue
            prefix, about = spec[slug]
            meta_path = path.parent / f"{slug}.metadata.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            with path.open(encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f))
            lower = {h.lower(): h for h in header}
            if "year" not in lower and "day" in lower:  # dated readings (sea level, ice sheets): yearly means
                yearly = Path(tempfile.mkdtemp(prefix="owid_climate_")) / f"{slug}.csv"
                if yearly_from_days(path, yearly):
                    path = yearly
                    with path.open(encoding="utf-8-sig", newline="") as f:
                        header = next(csv.reader(f))
                    lower = {h.lower(): h for h in header}
            if not {"entity", "year"} <= set(lower):
                log.warning("owid_climate: %s has no Entity and Year columns; skipped", path.name)
                continue
            values = [h for h in header if h.lower() not in ("entity", "code", "year", "day") and "annotation" not in h.lower()]
            main = CLIMATE_MAIN.get(slug)
            columns = {h: prefix if len(values) == 1 or h == main else f"{prefix}_{column_id(h)[5:].removeprefix(prefix + '_')}"[:64]
                       for h in values}
            self._stage_wide(con, "charts", path, lower["entity"], lower.get("code", lower["entity"]), lower["year"], columns)
            for h, ind in columns.items():
                m = meta.get("columns", {}).get(h, {})
                name = (m.get("titleShort") or m.get("titleLong") or h.replace("_", " ")).strip()
                if len(values) > 1 and prefix == "ghg_sector":
                    name = f"Greenhouse gases from {name.lower()}"
                out.append(indicator(ind, name, (m.get("descriptionShort") or about).strip()[:1200], (m.get("unit") or m.get("shortUnit") or "").strip(),
                                     "climate", self.source_id, f"{slug}:{h}", decimals=2, default_on=prefix in ("temp_anomaly", "wildfire_area"),
                                     notes=(m.get("citationShort") or about)[:500]))
        if not out:
            raise ConnectorError(f"owid_climate: no chart files with yearly values in {raw_dir}")
        self.listed_indicators = out
        return self._query(vintage, "charts")


# ----------------------------------------------------------------------------- greenhouse gas concentrations
GML = "https://gml.noaa.gov/webdata/ccgg/trends/"
GML_FILES = {"co2_mm_mlo.csv": "co2/co2_mm_mlo.csv", "co2_annmean_gl.csv": "co2/co2_annmean_gl.csv",
             "ch4_annmean_gl.csv": "ch4/ch4_annmean_gl.csv", "n2o_annmean_gl.csv": "n2o/n2o_annmean_gl.csv"}
GML_INDICATORS = [
    ("co2_ppm_mlo", "CO2 in the air at Mauna Loa (monthly)", "parts per million", "M"),
    ("co2_ppm", "CO2 in the air, world average", "parts per million", "A"),
    ("ch4_ppb", "Methane in the air, world average", "parts per billion", "A"),
    ("n2o_ppb", "Nitrous oxide in the air, world average", "parts per billion", "A"),
]


class NOAAGML(_Yearly):
    source_id = "noaa_gml"
    switch = "climate_fetch"
    fetch_every_days = 30

    def download(self, raw_dir: Path, release: str) -> str:
        for name, path in GML_FILES.items():
            self.get(GML + path, raw_dir / name)
        return GML

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pts = Points()
        for f in raw_dir.glob("*.csv"):
            rows = _csv_rows(f)
            if not rows:
                continue
            head = [key(c) for c in rows[0]]
            n = f.name.lower()
            if "_mm_" in n and "month" in head:
                y, m, v = head.index("year"), head.index("month"), head.index("average")
                for r in rows[1:]:
                    val = num(r[v])
                    if val is not None and val > 0:
                        pts.add("world", "co2_ppm_mlo", date(int(num(r[y])), int(num(r[m])), 1), val, "M")
            elif "annmean" in n and "mean" in head:
                ind = {"co2": "co2_ppm", "ch4": "ch4_ppb", "n2o": "n2o_ppb"}.get(n[:3])
                y, v = head.index("year"), head.index("mean")
                for r in rows[1:]:
                    val = num(r[v])
                    if ind and val is not None and val > 0:
                        pts.add("world", ind, date(int(num(r[y])), 1, 1), val)
        if not len(pts):
            raise ConnectorError(f"noaa_gml: no readings in {raw_dir}")
        found = {r[1] for r in pts.rows}
        self.listed_indicators = [indicator(i, n, f"{n} (NOAA Global Monitoring Laboratory).", u, "climate", self.source_id, i,
                                            decimals=1 if i.startswith("co2") else 0, frequency=fq, default_on=True, bounds=(0, 1e5))
                                  for i, n, u, fq in GML_INDICATORS if i in found]
        return pts.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- GISTEMP
GISTEMP_URL = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class GISTEMP(_Yearly):
    source_id = "nasa_gistemp"
    switch = "climate_fetch"
    fetch_every_days = 30

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(GISTEMP_URL, raw_dir / "GLB.Ts+dSST.csv")
        return GISTEMP_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pts = Points()
        for f in raw_dir.glob("*.csv"):
            rows = list(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
            h = next((i for i, r in enumerate(rows[:5]) if r and key(r[0]) == "year"), None)
            if h is None:
                continue
            head = [key(c) for c in rows[h]]
            for r in rows[h + 1:]:
                y = num(r[0]) if r else None
                if not y:
                    continue
                for i, c in enumerate(head):
                    v = num(r[i]) if i < len(r) and "*" not in r[i] else None
                    if c == "jd":
                        pts.add("world", "temp_anomaly_world", date(int(y), 1, 1), v)
                    elif c in MONTHS:
                        pts.add("world", "temp_anomaly_world_monthly", date(int(y), MONTHS.index(c) + 1, 1), v, "M")
        if not len(pts):
            raise ConnectorError(f"nasa_gistemp: no temperatures read in {raw_dir}")
        note = "NASA GISS Surface Temperature Analysis (GISTEMP v4); against the 1951-1980 average."
        self.listed_indicators = [
            indicator("temp_anomaly_world", "World temperature against 1951-1980 (NASA)", "The world's yearly mean surface temperature, land and sea, against the 1951-1980 average.",
                      "°C", "climate", self.source_id, "J-D", decimals=2, notes=note, bounds=(-5, 10)),
            indicator("temp_anomaly_world_monthly", "World temperature against 1951-1980, monthly (NASA)", "The same, month by month.",
                      "°C", "climate", self.source_id, "monthly", decimals=2, frequency="M", notes=note, bounds=(-5, 10))]
        return pts.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- El Niño and other drivers
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
DMI_URL = "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data"
SAM_URL = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_ao_index/aao/monthly.aao.index.b79.current.ascii"
SEASON_MONTH = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6, "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


def enso_episodes(series: list[tuple[date, float]]) -> list[dict]:
    """El Niño and La Niña episodes: five or more overlapping seasons in a row at +0.5 °C
    or more (or -0.5 or less), with the peak and NOAA's strength words."""
    out, run, sign = [], [], 0
    for d, v in sorted(series) + [(date(9999, 1, 1), 0.0)]:
        s = 1 if v >= 0.5 else -1 if v <= -0.5 else 0
        if s and s == sign:
            run.append((d, v))
            continue
        if sign and len(run) >= 5:
            peak = max(abs(x) for _, x in run)
            strength = "very strong" if peak >= 2 else "strong" if peak >= 1.5 else "moderate" if peak >= 1 else "weak"
            out.append({"kind": "El Niño" if sign > 0 else "La Niña", "start": run[0][0], "end": run[-1][0],
                        "peak": round(sign * peak, 1), "strength": strength})
        run, sign = ([(d, v)], s) if s else ([], 0)
    return out


class NOAAEnso(_Yearly):
    source_id = "noaa_enso"
    switch = "climate_fetch"
    fetch_every_days = 25

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(ONI_URL, raw_dir / "oni.ascii.txt")
        for url, name in ((DMI_URL, "dmi.had.long.data"), (SAM_URL, "monthly.aao.index.txt")):
            try:
                self.get(url, raw_dir / name)
            except ConnectorError as exc:
                log.warning("noaa_enso: %s skipped (%s)", name, exc)
        return ONI_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pts, oni = Points(), []
        for f in raw_dir.iterdir():
            n = f.name.lower()
            lines = _lines(f)
            if "oni" in n:
                for l in lines:
                    p = l.split()
                    if len(p) >= 4 and p[0] in SEASON_MONTH and (y := num(p[1])) and (v := num(p[3])) is not None:
                        d = date(int(y), SEASON_MONTH[p[0]], 1)
                        pts.add("world", "enso_oni", d, v, "M")
                        oni.append((d, v))
            elif "dmi" in n:
                for l in lines:
                    p = l.split()
                    if len(p) == 13 and re.fullmatch(r"(18|19|20)\d\d", p[0]):
                        for m, s in enumerate(p[1:], 1):
                            v = num(s)
                            if v is not None and v > -99:
                                pts.add("world", "iod_dmi", date(int(p[0]), m, 1), v, "M")
            elif "aao" in n or "sam" in n:
                for l in lines:
                    p = l.split()
                    if len(p) == 3 and re.fullmatch(r"(19|20)\d\d", p[0]) and (v := num(p[2])) is not None:
                        pts.add("world", "sam_index", date(int(p[0]), int(p[1]), 1), v, "M")
        if not oni:
            raise ConnectorError(f"noaa_enso: no Oceanic Niño Index read in {raw_dir}")
        found = {r[1] for r in pts.rows}
        spec = [("enso_oni", "El Niño index (ONI)", "Sea surface temperature in the central Pacific (Niño 3.4) against normal, three-month means: +0.5 °C or more is El Niño, -0.5 or less La Niña."),
                ("iod_dmi", "Indian Ocean Dipole (DMI)", "The difference in sea surface temperature between the western and eastern Indian Ocean; positive phases bring drought to Australia."),
                ("sam_index", "Southern Annular Mode", "Where the westerly winds sit around Antarctica; a positive phase brings settled weather to eastern New Zealand.")]
        self.listed_indicators = [indicator(i, n, d, "°C" if i != "sam_index" else "index", "climate", self.source_id, i, decimals=2,
                                            frequency="M", default_on=True, bounds=(-10, 10)) for i, n, d in spec if i in found]
        rows = [("world", f"enso-{e['start'].isoformat()}", "enso", "el_nino" if e["peak"] > 0 else "la_nina",
                 f"{e['kind']} ({e['strength']}, peak {e['peak']:+.1f} °C)", e["start"],
                 (e["end"].replace(day=28)), "month", abs(e["peak"]), "°C", None, None, None, "Pacific Ocean",
                 "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php",
                 "From NOAA's Oceanic Niño Index.", "#c0392b" if e["peak"] > 0 else "#2471a3") for e in enso_episodes(oni)]
        self.events_query = stage_events(con, self.source_id, vintage, rows, set())
        return pts.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- storm tracks
IBTRACS_URL = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.since1980.list.v04r01.csv"
BASINS = {"NA": "North Atlantic", "EP": "Eastern Pacific", "WP": "Western Pacific", "NI": "North Indian", "SI": "South Indian",
          "SP": "South Pacific", "SA": "South Atlantic", "MM": "Mixed"}


class IBTrACS(_Yearly):
    source_id = "ibtracs"
    switch = "climate_fetch"
    fetch_every_days = 30

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(IBTRACS_URL, raw_dir / "ibtracs.since1980.list.v04r01.csv")
        return IBTRACS_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv"))
        if not files:
            raise ConnectorError(f"ibtracs: no CSV in {raw_dir}")
        first = int(_settings().get("climate_storms_from", 1980))
        feats = storm_features(files[-1], first)
        if not feats:
            raise ConnectorError("ibtracs: no storm tracks read; the columns may have changed")
        self.layers = [{"layer_id": "storm_tracks", "name": "Tropical cyclone tracks",
                        "description": f"Every tropical storm and cyclone since {first} (NOAA IBTrACS), coloured by its strongest category.",
                        "kind": "line", "feature_count": len(feats), "geojson": collection(feats)}]
        return EMPTY_OBSERVATIONS


def storm_features(path: Path, first: int) -> list[dict]:
    """One line per storm: positions every six hours, with name, year, basin, the strongest
    Saffir-Simpson category (0 = tropical storm) and the highest wind in knots."""
    tracks: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        r = csv.reader(f)
        head = [key(c) for c in next(r)]
        col = {c: i for i, c in enumerate(head)}
        need = ("sid", "season", "basin", "name", "isotime", "lat", "lon")
        if not all(c in col for c in need):
            return []
        for row in r:
            if len(row) < len(head) or not re.fullmatch(r"\d{4}", row[col["season"]].strip()):
                continue  # the units row under the header
            season = int(row[col["season"]])
            t = row[col["isotime"]]
            if season < first or not t.endswith(("00:00:00", "06:00:00", "12:00:00", "18:00:00")):
                continue
            lat, lon = num(row[col["lat"]]), num(row[col["lon"]])
            if lat is None or lon is None:
                continue
            s = tracks.setdefault(row[col["sid"]], {"name": row[col["name"]].strip().title(), "year": season,
                                                    "basin": row[col["basin"]].strip() or "NA", "pts": [], "cat": -9, "wind": 0, "land": False})
            pts = s["pts"]
            if pts and abs(lon - pts[-1][0]) > 180:  # keep the line continuous across 180°
                lon += 360 if lon < pts[-1][0] else -360
            pts.append([lon, lat])
            cat = num(row[col["usasshs"]]) if "usasshs" in col else None
            wind = num(row[col["usawind"]]) if "usawind" in col else None
            wind = wind if wind is not None else (num(row[col["wmowind"]]) if "wmowind" in col else None)
            if cat is not None and cat > s["cat"]:
                s["cat"] = int(cat)
            if wind and wind > s["wind"]:
                s["wind"] = wind
            if "dist2land" in col and num(row[col["dist2land"]]) == 0:
                s["land"] = True
    out = []
    for sid, s in tracks.items():
        if len(s["pts"]) < 2 or s["cat"] < 0:
            continue  # depressions and disturbances are left out
        name = "Unnamed" if s["name"] in ("", "Not_Named", "Unnamed") else s["name"]
        out.append(feature({"type": "LineString", "coordinates": s["pts"]},
                           {"name": f"{name} ({s['year']})", "year": s["year"], "basin": BASINS.get(s["basin"], s["basin"]),
                            "cat": s["cat"], "wind": int(s["wind"]) or None, "land": 1 if s["land"] else 0, "sid": sid}))
    return out


# ----------------------------------------------------------------------------- GDACS alerts
GDACS_SEARCH = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDACS_TYPES = {"TC": ("storm", "Tropical cyclone"), "FL": ("flood", "Flood"), "DR": ("drought", "Drought"),
               "WF": ("wildfire", "Wildfire"), "EQ": ("earthquake", "Earthquake"), "VO": ("volcano", "Volcanic eruption"),
               "TS": ("tsunami", "Tsunami")}


class GDACS(_Yearly):
    source_id = "gdacs"
    switch = "climate_fetch"
    fetch_every_days = 7
    pause_seconds = 1.0

    def download(self, raw_dir: Path, release: str) -> str:
        """Orange and red alerts, a year at a time since 2000 (a few small requests a year)."""
        this = datetime.now().year
        for y in range(2000, this + 1):
            for page in range(1, 20):
                url = (f"{GDACS_SEARCH}?eventlist={';'.join(GDACS_TYPES)}&fromDate={y}-01-01&toDate={y}-12-31"
                       f"&alertlevel=Orange;Red&pagesize=100&pagenumber={page}")
                dest = raw_dir / f"gdacs_{y}_{page:02d}.json"
                try:
                    self.get(url, dest)
                except ConnectorError as exc:
                    if page == 1 and y == this:
                        raise
                    log.info("gdacs: %s page %s: %s", y, page, exc)
                    break
                time.sleep(self.pause_seconds)
                try:
                    n = len(json.loads(dest.read_text(encoding="utf-8")).get("features", []))
                except ValueError:
                    n = 0
                if n < 100:
                    break
        return GDACS_SEARCH

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows, seen = [], set()
        for f in sorted(raw_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for feat in data.get("features", []):
                rows.extend(gdacs_rows(feat.get("properties") or {}, seen))
        if not rows and not list(raw_dir.glob("*.json")):
            raise ConnectorError(f"gdacs: no alert files in {raw_dir}")
        self.events_query = stage_events(con, self.source_id, vintage, rows, set())
        return EMPTY_OBSERVATIONS


def gdacs_rows(p: dict, seen: set) -> list[tuple]:
    t = p.get("eventtype")
    if t not in GDACS_TYPES or str(p.get("alertlevel", "")).lower() not in ("orange", "red"):
        return []
    sub, label = GDACS_TYPES[t]
    start = _day(p.get("fromdate"))
    end = _day(p.get("todate")) or start
    if not start:
        return []
    countries = [c.get("iso3") for c in p.get("affectedcountries") or [] if c.get("iso3")] or [p.get("iso3")]
    sev = p.get("severitydata") or {}
    name = (p.get("name") or "").strip()
    title = f"{label}{': ' + name if name and name.lower() not in label.lower() else ''} ({p['alertlevel'].lower()} alert)"
    out = []
    for iso in countries:
        ent = entity_for("iso3", iso)
        k = f"gdacs-{t}-{p.get('eventid')}-{ent}"
        if not ent or k in seen:
            continue
        seen.add(k)
        out.append((ent, k, "disaster", sub, title, start, end, "day", num(sev.get("severity")), sev.get("severityunit"),
                    None, None, None, p.get("country") or None, (p.get("url") or {}).get("report"),
                    (sev.get("severitytext") or "")[:500], "#c0392b" if p["alertlevel"].lower() == "red" else "#e67e22"))
    return out


def _day(s) -> date | None:
    try:
        return datetime.fromisoformat(str(s)[:19]).date()
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- projections
CCKP_URL = "https://cckpapi.worldbank.org/cckp/v1/cmip6-x0.25_timeseries_{var}_timeseries_annual_2015-2100_{stat}_{ssp}_ensemble_all_mean/{codes}?_format=json"
SSPS = {"ssp126": "SSP1-2.6 (low emissions)", "ssp245": "SSP2-4.5 (middle)", "ssp370": "SSP3-7.0 (high)", "ssp585": "SSP5-8.5 (very high)"}
STATS = {"median": "central", "p10": "lower80", "p90": "upper80"}
VARS = {"tas": ("proj_temp", "Mean temperature", "°C"), "pr": ("proj_rain", "Rainfall", "mm a year")}


class CCKP(_Yearly):
    source_id = "cckp"
    switch = "climate_fetch"
    fetch_every_days = 365
    pause_seconds = 0.5
    CHUNK = 60

    def download(self, raw_dir: Path, release: str) -> str:
        codes = sorted({c["code"] for c in catalogue.entity_codes() if c["scheme"] == "iso3" and len(c["code"]) == 3
                        and is_country(c["entity_id"]) and not c.get("valid_to")})
        got = 0
        for var in VARS:
            for ssp in SSPS:
                for stat in STATS:
                    for i in range(0, len(codes), self.CHUNK):
                        url = CCKP_URL.format(var=var, stat=stat, ssp=ssp, codes=",".join(codes[i:i + self.CHUNK]))
                        try:
                            self.get(url, raw_dir / f"cckp_{var}_{ssp}_{stat}_{i // self.CHUNK:02d}.json")
                            got += 1
                        except ConnectorError as exc:
                            log.warning("cckp: %s %s %s part %s skipped (%s)", var, ssp, stat, i // self.CHUNK, exc)
                        time.sleep(self.pause_seconds)
        if not got:
            raise ConnectorError("cckp: no projections could be downloaded")
        return CCKP_URL.split("{var}")[0]

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pts = Points()
        for f in sorted(raw_dir.glob("*.json")):
            m = re.match(r"cckp_(tas|pr)_(ssp\d{3})_(median|p10|p90)", f.name)
            if not m:
                continue
            var, ssp, stat = m.groups()
            try:
                data = json.loads(f.read_text(encoding="utf-8")).get("data", {})
            except ValueError:
                continue
            for code, series in data.items():
                ent = entity_for("iso3", code)
                if not ent or not isinstance(series, dict):
                    continue
                for when, v in series.items():
                    y = re.match(r"(\d{4})", str(when))
                    val = num(v)
                    if y and val is not None:
                        pts.add(ent, f"{VARS[var][0]}_{ssp}", date(int(y.group(1)), 1, 1), val * (1 if var == "tas" else 1), "A", STATS[stat], "P")
        if not len(pts):
            raise ConnectorError(f"cckp: no projections read in {raw_dir}")
        found = {r[1] for r in pts.rows}
        self.listed_indicators = [
            indicator(f"{pre}_{ssp}", f"{name}, projected under {label}", f"{name} each year to 2100 under {label}: the median of the CMIP6 climate models, with the 10th to 90th percentile as the range.",
                      unit, "climate", self.source_id, f"{v}:{ssp}", decimals=1 if v == "tas" else 0, default_on=ssp == "ssp245",
                      notes="World Bank Climate Change Knowledge Portal, CMIP6 0.25° ensemble.", bounds=(-60, 10000))
            for v, (pre, name, unit) in VARS.items() for ssp, label in SSPS.items() if f"{pre}_{ssp}" in found]
        return pts.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- policy, saved by hand
NZT_STATUS = {"in law": 3, "achieved (self-declared)": 4, "achieved": 4, "in policy document": 2, "declaration / pledge": 1,
              "declaration": 1, "pledge": 1, "proposed / in discussion": 0.5, "proposed": 0.5}


class NetZeroTracker(_Yearly):
    source_id = "net_zero_tracker"
    manual = True
    fetch_every_days = 0

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("net_zero_tracker: save the export from zerotracker.net into var\\manual\\net_zero_tracker")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for f in sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".xlsx")):
            table = _table(f)
            if not table:
                continue
            # The export has a row of group headings ("Identification", "End target information")
            # above the column names: start from the row that names the target year.
            h = next((i for i, r in enumerate(table[:10]) if any(key(c) in ("endtargetyear", "endtargettargetyear", "targetyear") for c in r if c)), 0)
            table = table[h:]
            head = {key(c): i for i, c in enumerate(table[0]) if c}
            c_type = next((head[k] for k in ("actortype", "entitytype", "type") if k in head), None)
            c_code = next((head[k] for k in ("iso3", "iso", "country", "code", "idcode") if k in head), None)
            c_name = next((head[k] for k in ("name", "country", "actor") if k in head), None)
            c_year = next((head[k] for k in ("endtargettargetyear", "endtargetyear", "targetyear") if k in head), None)
            c_stat = next((head[k] for k in ("endtargetstatus", "statusofendtarget", "status") if k in head), None)
            c_kind = next((head[k] for k in ("endtarget",) if k in head), None)
            if c_year is None or (c_code is None and c_name is None):
                continue
            year = int(re.search(r"(20\d\d)", f.name).group(1)) if re.search(r"(20\d\d)", f.name) else datetime.now().year
            for r in table[1:]:
                if c_type is not None and str(r[c_type] or "").strip().lower() not in ("country", ""):
                    continue
                ent = entity_for("iso3", str(r[c_code] or "").strip()) if c_code is not None else None
                ent = ent or (catalogue.country_by_name(str(r[c_name] or "")) if c_name is not None else None)
                target = num(r[c_year])
                if not ent or not target or (c_kind is not None and "net zero" not in str(r[c_kind] or "").lower() and "neutral" not in str(r[c_kind] or "").lower()):
                    continue
                rows.add("iso3", ent, "net_zero_year", year, target)
                st = NZT_STATUS.get(str(r[c_stat] or "").strip().lower()) if c_stat is not None else None
                rows.add("iso3", ent, "net_zero_status", year, st)
        if not len(rows):
            raise ConnectorError("net_zero_tracker: no country targets read; expected columns such as id_code, end_target, end_target_year, end_target_status")
        note = "Net Zero Tracker (Energy and Climate Intelligence Unit, Data-Driven EnviroLab, NewClimate Institute, Oxford Net Zero)."
        self.listed_indicators = [
            indicator("net_zero_year", "Net zero target year", "The year by which the country has said it will reach net zero (or carbon neutrality).", "year",
                      "climate", self.source_id, "end_target_year", decimals=0, notes=note, bounds=(2000, 2200)),
            indicator("net_zero_status", "How firm the net zero target is", "4 achieved, 3 in law, 2 in a policy document, 1 a declaration or pledge, 0.5 proposed.",
                      "level", "climate", self.source_id, "end_target_status", decimals=1, notes=note, bounds=(0, 4))]
        return rows.stage(con, self.source_id, vintage)


class CarbonPricing(_Yearly):
    source_id = "carbon_pricing"
    manual = True
    fetch_every_days = 0

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("carbon_pricing: save the data file from carbonpricingdashboard.worldbank.org into var\\manual\\carbon_pricing")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        best: dict[tuple[str, int], float] = {}
        for f in sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".xlsx")):
            sheets = [s for s in xlsx_sheet_names(f) if "price" in s.lower()] if f.suffix.lower() == ".xlsx" else [None]
            for s in sheets or [0]:
                table = xlsx_rows(f, s) if f.suffix.lower() == ".xlsx" else _table(f)
                carbon_prices(table, best)
        if not best:
            raise ConnectorError("carbon_pricing: no prices read; expected a sheet with a Jurisdiction column and one column per year")
        rows = Rows()
        for (ent, y), v in best.items():
            rows.add("iso3", ent, "carbon_price", y, v)
        self.listed_indicators = [indicator("carbon_price", "Carbon price (highest national scheme)",
                                            "The highest price on a tonne of CO2e among the country's national carbon taxes and emissions trading systems (nominal US$).",
                                            "US$ per tonne CO2e", "climate", self.source_id, "price", decimals=2,
                                            notes="World Bank Carbon Pricing Dashboard.", bounds=(0, 1000))]
        return rows.stage(con, self.source_id, vintage)


def carbon_prices(table: list[list], best: dict) -> None:
    h = next((i for i, r in enumerate(table[:10]) if any(key(c).startswith("jurisdiction") for c in r if c)), None)
    if h is None:
        return
    head = table[h]
    c_j = next(i for i, c in enumerate(head) if c and key(c).startswith("jurisdiction"))
    years = [(i, int(str(c).split(".")[0])) for i, c in enumerate(head) if c and re.fullmatch(r"(19|20)\d\d(\.0)?", str(c).strip())]
    for r in table[h + 1:]:
        name = str(r[c_j] or "").strip() if c_j < len(r) else ""
        ent = "eu" if name.lower() in ("eu", "european union", "eu ets") else catalogue.country_by_name(name)
        if not ent:
            continue
        for i, y in years:
            v = num(r[i]) if i < len(r) else None
            if v is not None and v > 0:
                best[(ent, y)] = max(best.get((ent, y), 0.0), v)


# ----------------------------------------------------------------------------- New Zealand, saved by hand
class NIWA7Station(_Yearly):
    source_id = "niwa_7station"
    manual = True
    fetch_every_days = 0

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("niwa_7station: save NIWA's seven-station series into var\\manual\\niwa_7station")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        seen: set[tuple[str, int]] = set()
        for f in sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".xlsx")):
            table = _table(f)
            h = next((i for i, r in enumerate(table[:15]) if any(key(c) == "year" for c in r if c)), None)
            if h is None:
                continue
            head = [key(c) if c else "" for c in table[h]]
            cy = head.index("year")
            sub = [key(c) if c else "" for c in table[h + 1]] if h + 1 < len(table) else []
            comp = next((i for i, c in enumerate(head) if "composite" in c or c.startswith(("7stn", "7station", "sevenstation"))), None)
            if comp is not None and "temp" in sub[comp:comp + 2] and "anomaly" in sub[comp:comp + 2]:
                # NIWA's annual workbook: a row of station names over a row of Temp / Anomaly pairs;
                # the seven-station composite is the last pair.
                ct, cv = comp + sub[comp:comp + 2].index("temp"), comp + sub[comp:comp + 2].index("anomaly")
                h += 1
            elif "anomal" in f.name.lower() and "annual" in head:
                # NIWA's monthly anomalies workbook: one column per month and the year's anomaly.
                cv, ct = head.index("annual"), None
            else:
                cv = next((i for i, c in enumerate(head) if "anomaly" in c), None)
                ct = next((i for i, c in enumerate(head) if c.startswith(("mean", "temperature", "nz"))), None)
            for r in table[h + 1:]:
                y = num(r[cy]) if cy < len(r) else None
                if not y:
                    continue
                # Two of NIWA's files can give the same year (annual and monthly): the first one read is kept.
                if cv is not None and cv < len(r) and num(r[cv]) is not None and ("a", int(y)) not in seen:
                    seen.add(("a", int(y)))
                    rows.add("iso3", "NZL", "nz_temp_anomaly_7station", int(y), num(r[cv]))
                if ct is not None and ct < len(r) and num(r[ct]) is not None and ("t", int(y)) not in seen:
                    seen.add(("t", int(y)))
                    rows.add("iso3", "NZL", "nz_temp_7station", int(y), num(r[ct]))
        if not len(rows):
            raise ConnectorError("niwa_7station: no years read; expected a Year column and an anomaly or mean temperature column")
        found = {r[2] for r in rows.rows}
        note = "NIWA seven-station temperature series (Auckland, Masterton, Wellington, Nelson, Hokitika, Lincoln, Dunedin)."
        self.listed_indicators = [i for i in (
            indicator("nz_temp_anomaly_7station", "New Zealand temperature against 1981-2010 (NIWA seven stations)", "New Zealand's yearly mean temperature against the 1981-2010 normal, from seven long-running stations.",
                      "°C", "climate", self.source_id, "anomaly", decimals=2, notes=note, bounds=(-5, 5)),
            indicator("nz_temp_7station", "New Zealand mean temperature (NIWA seven stations)", "New Zealand's yearly mean temperature from seven long-running stations.",
                      "°C", "climate", self.source_id, "mean", decimals=2, notes=note, bounds=(0, 30))) if i["id"] in found]
        return rows.stage(con, self.source_id, vintage)


MFE_SECTORS = {"energy": "energy", "agriculture": "agriculture", "industrialprocessesandproductuse": "industry", "ippu": "industry",
               "industrialprocesses": "industry", "waste": "waste", "landuselandusechangeandforestry": "forestry", "lulucf": "forestry"}


class MfEGHG(_Yearly):
    source_id = "mfe_ghg"
    manual = True
    fetch_every_days = 0

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("mfe_ghg: save the greenhouse gas inventory table from data.mfe.govt.nz into var\\manual\\mfe_ghg")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        sums: dict[tuple[str, int], float] = defaultdict(float)
        for f in sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".xlsx")):
            table = _table(f)
            h = next((i for i, r in enumerate(table[:15]) if any(key(c) == "year" for c in r if c)), None)
            if h is None:
                continue
            head = [key(c) for c in table[h]]
            cy = head.index("year")
            cs = next((i for i, c in enumerate(head) if c in ("sector", "category", "sectorname")), None)
            cg = next((i for i, c in enumerate(head) if c in ("gas", "gasname")), None)
            cv = next((i for i, c in enumerate(head) if c.startswith(("value", "emissions", "ktco2"))), None)
            if cs is None or cv is None:
                continue
            for r in table[h + 1:]:
                if max(cy, cs, cv) >= len(r):
                    continue
                sector = MFE_SECTORS.get(key(r[cs]))
                gas = key(r[cg]) if cg is not None and cg < len(r) else "all"
                y, v = num(r[cy]), num(r[cv])
                if sector and y and v is not None and gas in ("all", "allgases", "total", "co2e", "totalco2e", ""):
                    sums[(sector, int(y))] += v
        if not sums:
            raise ConnectorError("mfe_ghg: no sector totals read; expected Year, Sector (Energy, Agriculture ...) and Value columns")
        rows = Rows()
        for (s, y), v in sums.items():
            rows.add("iso3", "NZL", f"nz_ghg_{s}", y, v / 1000)  # kt to million tonnes
        found = {r[2] for r in rows.rows}
        names = {"energy": "energy (with transport)", "agriculture": "farming", "industry": "industrial processes", "waste": "waste",
                 "forestry": "land use and forests (negative: taken up)"}
        self.listed_indicators = [indicator(f"nz_ghg_{s}", f"New Zealand greenhouse gases from {n}", f"Greenhouse gas emissions from {n}, New Zealand's national inventory.",
                                            "million tonnes CO2e", "climate", self.source_id, s, decimals=2, notes="Ministry for the Environment, New Zealand's Greenhouse Gas Inventory.")
                                  for s, n in names.items() if f"nz_ghg_{s}" in found]
        return rows.stage(con, self.source_id, vintage)
