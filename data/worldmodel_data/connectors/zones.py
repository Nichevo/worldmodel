"""Places beyond countries: sea ice at the poles, and what is in orbit.

nsidc_sea_ice
    The Sea Ice Index (NSIDC G02135): one CSV per month of the year and hemisphere,
    with the mean ice extent and area that month for every year since 1978:
        https://noaadata.apps.nsidc.org/NOAA/G02135/<north|south>/monthly/data/<N|S>_<MM>_extent_v<4.0|3.0>.csv
    (columns year, mo, data-type, region, extent, area; -9999 where missing). The
    newest version is tried first. Stored on the Arctic (north) and Antarctica (south):
    sea_ice_extent monthly, and per year its mean, its lowest month and its highest month
    (million km²).

celestrak_satcat
    CelesTrak's copy of the satellite catalogue: every object tracked in orbit since
    1957, with its owner (a country or an organisation), launch date and site, and decay
    date. Stored per owner country: sats_launched (payloads launched that year),
    sats_in_orbit (payloads still in orbit at the year's end), debris_in_orbit (rocket
    bodies and debris in orbit at the year's end) and space_launches (launches from
    sites in that country; a launch is counted once however many objects it carried).
    Totals for all of space go on the "space" zone: objects in orbit by type.
    Owners that are organisations (ESA, Intelsat...) count only towards the totals.
"""

from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.tabular import Rows, indicator, num

log = logging.getLogger(__name__)

NSIDC = "https://noaadata.apps.nsidc.org/NOAA/G02135/{hemi}/monthly/data/{H}_{mm:02d}_extent_v{v}.csv"
VERSIONS = ("4.0", "3.0")
HEMISPHERES = (("north", "N", "arctic"), ("south", "S", "ATA"))


ICE_NOTE = "From the NSIDC Sea Ice Index; the Arctic holds the northern hemisphere, Antarctica the southern."
ICE_INDICATORS = [
    indicator("sea_ice_extent", "Sea ice extent (monthly)", "Area of ocean with at least 15% ice cover, the month's "
              "average, in million km².", "million km²", "climate", "nsidc_sea_ice", "extent", decimals=2,
              bounds=(0, 25), frequency="M", notes=ICE_NOTE),
    indicator("sea_ice_extent_mean", "Sea ice extent (year's average)", "Average of the twelve monthly sea ice "
              "extents, in million km².", "million km²", "climate", "nsidc_sea_ice", "extent_mean", decimals=2,
              bounds=(0, 25), notes=ICE_NOTE),
    indicator("sea_ice_extent_min", "Sea ice extent (year's lowest month)", "The smallest monthly sea ice extent of "
              "the year (September in the Arctic, February in the Antarctic), in million km².", "million km²",
              "climate", "nsidc_sea_ice", "extent_min", decimals=2, bounds=(0, 25), notes=ICE_NOTE),
    indicator("sea_ice_extent_max", "Sea ice extent (year's highest month)", "The largest monthly sea ice extent of "
              "the year, in million km².", "million km²", "climate", "nsidc_sea_ice", "extent_max", decimals=2,
              bounds=(0, 25), notes=ICE_NOTE),
]
SPACE_NOTE = "From CelesTrak's satellite catalogue; objects owned by organisations (ESA, Intelsat) count only in space totals."
SPACE_INDICATORS = [
    indicator("sats_launched", "Satellites launched", "Satellites (payloads) the country's government or companies "
              "put into orbit that year.", "count", "space", "celestrak_satcat", "launched", decimals=0,
              aggregation={"method": "sum"}, bounds=(0, 100000), notes=SPACE_NOTE),
    indicator("sats_in_orbit", "Satellites in orbit", "The country's satellites still in orbit at the end of the "
              "year, working or not.", "count", "space", "celestrak_satcat", "in_orbit", decimals=0,
              aggregation={"method": "sum"}, bounds=(0, 1000000), notes=SPACE_NOTE),
    indicator("debris_in_orbit", "Rocket bodies and debris in orbit", "Spent rocket stages and tracked debris "
              "pieces from the country's launches still in orbit at the end of the year.", "count", "space",
              "celestrak_satcat", "debris", decimals=0, aggregation={"method": "sum"}, bounds=(0, 1000000),
              notes=SPACE_NOTE),
    indicator("space_launches", "Space launches from the country", "Launches into orbit from launch sites in the "
              "country that year (one launch however many objects it carried).", "count", "space",
              "celestrak_satcat", "launches", decimals=0, aggregation={"method": "sum"}, bounds=(0, 10000),
              notes=SPACE_NOTE),
] + [indicator(f"objects_in_orbit_{k}", f"Objects in orbit: {label}", f"All {label.lower()} in orbit at the end of "
               "the year, whoever owns them.", "count", "space", "celestrak_satcat", f"total_{k}", decimals=0,
               bounds=(0, 10000000), notes=SPACE_NOTE)
     for k, label in (("payload", "Satellites"), ("rocket_body", "Rocket bodies"), ("debris", "Debris"))]


class NSIDCSeaIce(Connector):
    source_id = "nsidc_sea_ice"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got, version = 0, None
        for hemi, h, _ in HEMISPHERES:
            for mm in range(1, 13):
                for v in ([version] if version else VERSIONS):
                    try:
                        self.get(NSIDC.format(hemi=hemi, H=h, mm=mm, v=v), raw_dir / f"{h}_{mm:02d}_extent.csv")
                        version = v
                        got += 1
                        break
                    except ConnectorError as exc:
                        log.info("nsidc_sea_ice: %s %02d v%s: %s", hemi, mm, v, exc)
        if not got:
            raise ConnectorError("nsidc_sea_ice: no monthly file could be downloaded")
        return f"NSIDC Sea Ice Index v{version}, {got} monthly files"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        monthly: dict[tuple[str, int, int], float] = {}
        for p in sorted(raw_dir.glob("*_extent*.csv")):
            h = p.name[0].upper()
            ent = next((e for _, hh, e in HEMISPHERES if hh == h), None)
            if not ent:
                continue
            for y, m, extent in read_extent(p.read_text(encoding="utf-8", errors="replace")):
                monthly[(ent, y, m)] = extent
        if not monthly:
            raise ConnectorError(f"nsidc_sea_ice: no extents read from {raw_dir}")
        con.execute("CREATE TABLE ice (source_code VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, value DOUBLE)")
        out = [(e, "sea_ice_extent", date(y, m, 1), "M", v) for (e, y, m), v in monthly.items()]
        by_year: dict[tuple[str, int], list[float]] = defaultdict(list)
        for (e, y, _), v in monthly.items():
            by_year[(e, y)].append(v)
        for (e, y), vals in by_year.items():
            if len(vals) == 12:  # a full year only: a part year's mean or low would mislead
                out += [(e, "sea_ice_extent_mean", date(y, 1, 1), "A", round(sum(vals) / 12, 3)),
                        (e, "sea_ice_extent_min", date(y, 1, 1), "A", min(vals)),
                        (e, "sea_ice_extent_max", date(y, 1, 1), "A", max(vals))]
        con.executemany("INSERT INTO ice VALUES (?, ?, ?, ?, ?)", out)
        self.listed_indicators = ICE_INDICATORS
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, "
                "source_code, indicator_id, period_start, freq, '' AS breakdown, 'central' AS variant, value, "
                "'E' AS status FROM ice")


def read_extent(text: str) -> list[tuple[int, int, float]]:
    """(year, month, extent in million km²) from one Sea Ice Index monthly file."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    try:
        iy, im, ie = head.index("year"), head.index("mo"), head.index("extent")
    except ValueError:
        return []
    out = []
    for r in rows[1:]:
        if len(r) <= max(iy, im, ie):
            continue
        y, m, e = num(r[iy]), num(r[im]), num(r[ie])
        if y and m and e is not None and e >= 0:
            out.append((int(y), int(m), e))
    return out


# ---------------------------------------------------------------- satellites
SATCAT = "https://celestrak.org/pub/satcat.csv"
# CelesTrak owner codes for countries -> entity. Others (ESA, ITSO, GLOB...) are organisations.
OWNERS = {
    "US": "USA", "PRC": "CHN", "JPN": "JPN", "FR": "FRA", "UK": "GBR", "IND": "IND", "GER": "DEU", "IT": "ITA",
    "CA": "CAN", "ISRA": "ISR", "BRAZ": "BRA", "SPN": "ESP", "AUS": "AUS", "NZ": "NZL", "SKOR": "KOR", "NKOR": "PRK",
    "IRAN": "IRN", "ARGN": "ARG", "INDO": "IDN", "MALA": "MYS", "THAI": "THA", "SAUD": "SAU", "UAE": "ARE",
    "TURK": "TUR", "MEX": "MEX", "CHLE": "CHL", "PER": "PER", "EGYP": "EGY", "ALG": "DZA", "NIG": "NGA",
    "SAFR": "ZAF", "KAZ": "KAZ", "UKR": "UKR", "BELA": "BLR", "NOR": "NOR", "SWED": "SWE", "FIN": "FIN",
    "DEN": "DNK", "NETH": "NLD", "BEL": "BEL", "LUXE": "LUX", "POL": "POL", "CZCH": "CZE", "AUT": "AUT",
    "SWTZ": "CHE", "GREC": "GRC", "POR": "PRT", "SING": "SGP", "TWN": "TWN", "PAKI": "PAK", "BGD": "BGD",
    "VTNM": "VNM", "PHIL": "PHL", "QAT": "QAT", "KUW": "KWT", "AZER": "AZE", "TMMC": "TKM", "ROM": "ROU",
    "HUN": "HUN", "BUL": "BGR", "EST": "EST", "LTU": "LTU", "LAT": "LVA", "SVN": "SVN", "SVK": "SVK",
    "IRL": "IRL", "ISL": "ISL", "COL": "COL", "ECU": "ECU", "BOL": "BOL", "VENZ": "VEN", "URY": "URY",
    "PRY": "PRY", "CRI": "CRI", "GUAT": "GTM", "KEN": "KEN", "ETH": "ETH", "RWA": "RWA", "UAE ": "ARE",
    "MNG": "MNG", "LKA": "LKA", "NPL": "NPL", "BHR": "BHR", "JOR": "JOR", "TUN": "TUN", "MA": "MAR", "GHA": "GHA",
    "UGA": "UGA", "ZWE": "ZWE", "SDN": "SDN", "ANG": "AGO", "LAOS": "LAO", "KGZ": "KGZ", "IRAQ": "IRQ",
}
# Launch sites -> the country they are in.
SITES = {
    "AFETR": "USA", "AFWTR": "USA", "WLPIS": "USA", "KODAK": "USA", "ERAS": "USA", "KWAJ": "USA", "CAS": "USA",
    "WRAS": "USA", "PMRF": "USA", "SPKII": "USA", "SEAL": None, "OREM": None,
    "PLMSC": "RUS", "KYMSC": "RUS", "VOSTO": "RUS", "DLS": "RUS", "SVOBO": "RUS", "SNMLP": None, "BAR": "RUS",
    "TYMSC": "KAZ",
    "JSC": "CHN", "TSC": "CHN", "XSC": "CHN", "WSC": "CHN", "YSLA": "CHN", "SCSLA": "CHN", "DFSC": "CHN",
    "TANSC": "JPN", "KSCUT": "JPN", "TNSTA": "JPN",
    "SRILR": "IND", "FRGUI": "FRA", "HGSTR": "DZA", "NSC": "KOR", "SEMLS": "IRN", "SHAHR": "IRN", "SMTS": "IRN",
    "YUN": "PRK", "SADOL": None, "PALMA": "ISR", "WOMRA": "AUS", "SANMR": "ITA", "RLLB": "NZL", "RLLC": "NZL",
    "MAHIA": "NZL", "ALCLC": "BRA",
}


class CelesTrakSatcat(Connector):
    source_id = "celestrak_satcat"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(SATCAT, raw_dir / "satcat.csv")
        return SATCAT

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        f = raw_dir / "satcat.csv"
        if not f.exists():
            files = sorted(raw_dir.glob("*.csv"))
            if not files:
                raise ConnectorError(f"celestrak_satcat: no satcat.csv in {raw_dir}")
            f = files[0]
        rows = satcat_rows(f.read_text(encoding="utf-8", errors="replace"), datetime.now().year)
        if not rows:
            raise ConnectorError(f"celestrak_satcat: nothing read from {f.name}; the columns may have changed")
        self.listed_indicators = SPACE_INDICATORS
        return rows.stage(con, self.source_id, vintage)


def _day(s: str) -> date | None:
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def owner_entity(code: str, on: date) -> str | None:
    code = code.strip().upper()
    if code == "CIS":  # the USSR, then Russia
        return "SUN" if on < date(1991, 12, 26) else "RUS"
    return OWNERS.get(code)


def satcat_rows(text: str, this_year: int) -> Rows:
    reader = csv.DictReader(io.StringIO(text))
    fields = {k.strip().upper(): k for k in (reader.fieldnames or [])}
    need = ("OBJECT_ID", "OBJECT_TYPE", "OWNER", "LAUNCH_DATE")
    if not all(n in fields for n in need):
        return Rows()
    get = lambda r, n: (r.get(fields[n]) or "") if n in fields else ""  # noqa: E731
    launched: dict[tuple[str, int], int] = defaultdict(int)
    alive: dict[tuple[str, str], list[tuple[int, int | None]]] = defaultdict(list)  # (entity, type) -> [(launch, decay)]
    launches: dict[tuple[str, int], set[str]] = defaultdict(set)
    totals: list[tuple[str, int, int | None]] = []
    unknown_sites: set[str] = set()
    for r in reader:
        start = _day(get(r, "LAUNCH_DATE"))
        if not start:
            continue
        decay = _day(get(r, "DECAY_DATE"))
        typ = get(r, "OBJECT_TYPE").strip().upper()
        kind = "payload" if typ.startswith("PAY") else "rocket_body" if typ.startswith("R/B") else "debris" if typ.startswith("DEB") else "unknown"
        totals.append((kind, start.year, decay.year if decay else None))
        owner = owner_entity(get(r, "OWNER"), start)
        if owner:
            if kind == "payload":
                launched[(owner, start.year)] += 1
            alive[("SUN" if owner == "RUS" else owner, "payload" if kind == "payload" else "debris")].append((start.year, decay.year if decay else None))
        site = get(r, "LAUNCH_SITE").strip().upper()
        launch = get(r, "OBJECT_ID").strip()[:8]
        if site:
            if site in SITES:
                if SITES[site]:
                    launches[(SITES[site], start.year)].add(launch)
            else:
                unknown_sites.add(site)
    if unknown_sites:
        log.info("celestrak_satcat: launch sites not placed in a country: %s", ", ".join(sorted(unknown_sites)))
    rows = Rows()
    for (e, y), n in launched.items():
        rows.add("iso3", e, "sats_launched", y, n)
    for (e, y), ids in launches.items():
        rows.add("iso3", e, "space_launches", y, len(ids))
    for (e, kind), spans in alive.items():
        ind = "sats_in_orbit" if kind == "payload" else "debris_in_orbit"
        first = min(s for s, _ in spans)
        for y in range(first, this_year + 1):
            # Soviet and Russian objects together: the USSR's until 1991, then Russia's (which took them over)
            rows.add("iso3", ("SUN" if y <= 1991 else "RUS") if e == "SUN" else e, ind, y, sum(1 for s, d in spans if s <= y and (d is None or d > y)))
    first = min((s for _, s, _ in totals), default=this_year)
    for kind in ("payload", "rocket_body", "debris"):
        spans = [(s, d) for k, s, d in totals if k == kind]
        for y in range(first, this_year + 1):
            rows.add("iso3", "space", f"objects_in_orbit_{kind}", y, sum(1 for s, d in spans if s <= y and (d is None or d > y)))
    return rows
