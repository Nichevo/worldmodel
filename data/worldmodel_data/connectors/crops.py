"""Crop land in US states and counties, for Land > Top crops.

usda_nass
    USDA NASS Quick Stats API (free NASS_API_KEY): acres harvested of every crop in each state and
    county at each Census of Agriculture (2002, 2007, 2012, 2017, 2022, and later ones as they come),
    with orchards and vineyards counted by their bearing and non-bearing acres. One question per state
    and census (about 520 the first time); a census already read is not asked again. A CSV saved by
    hand from the Quick Stats site (var\\manual\\usda_nass) is read the same way.

Figures go to usreg_crop_area_ha (hectares, breakdown crop=<id>, ids from worldmodel_contract.crops).
"""

from __future__ import annotations

import csv
import io
import logging
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import httpx

from worldmodel_contract.crops import ACRE_HA, NASS_PART, nass_crop, nass_skip
from worldmodel_data.connectors.base import ConnectorError
from worldmodel_data.connectors.tabular import Rows, num
from worldmodel_data.connectors.us import STATES, USConnector, _ind, fips_of

log = logging.getLogger(__name__)

NASS_API = "https://quickstats.nass.usda.gov/api/api_GET/"
FIRST_CENSUS = 2002
STATS = ("AREA HARVESTED", "AREA BEARING & NON-BEARING")  # field crops; orchards and vineyards

# The Quick Stats site's own CSV ("Spreadsheet") names its columns differently from the API.
WEB_COLUMNS = {"program": "source_desc", "geo level": "agg_level_desc", "state ansi": "state_fips_code",
               "county ansi": "county_code", "commodity": "commodity_desc", "data item": "short_desc",
               "domain": "domain_desc", "year": "year", "value": "value", "period": "reference_period_desc"}


def census_years(today: date | None = None) -> list[int]:
    """Census years whose figures could be out: every fifth year from 2002, published about 14 months on."""
    t = today or date.today()
    return [y for y in range(FIRST_CENSUS, t.year, 5) if (t.year - y - 1) * 12 + t.month >= 14]


def _norm(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        k2 = (k or "").strip().lower()
        out[WEB_COLUMNS.get(k2, k2)] = (v or "").strip()
    return out


def nass_records(text: str):
    """(fips, year, crop, commodity, qualifiers, statistic, acres) for each usable Quick Stats row:
    domain TOTAL, units ACRES, a state or county, a figure that is not withheld ("(D)")."""
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        r = _norm(r)
        if r.get("domain_desc", "TOTAL").upper() != "TOTAL":
            continue
        level = r.get("agg_level_desc", "").upper()
        if level not in ("STATE", "COUNTY"):
            continue
        acres = num(r.get("value", "").replace(",", ""))
        if acres is None or acres <= 0:
            continue
        desc = r.get("short_desc", "").upper()
        what, _, stat = desc.partition(" - ")
        stat = stat.strip()
        if stat not in ("ACRES HARVESTED", "ACRES BEARING & NON-BEARING"):
            continue
        commodity = (r.get("commodity_desc") or what.split(",")[0]).upper().strip()
        if nass_skip(commodity):
            continue
        rest = what[len(commodity):] if what.startswith(commodity) else what.partition(",")[2]
        quals = tuple(q.strip() for q in rest.split(",") if q.strip())
        if any(NASS_PART.search(q) for q in quals):
            continue
        county = (r.get("county_code") or r.get("county_ansi") or "") if level == "COUNTY" else ""
        if county == "998":  # "other (combined) counties": not one place
            continue
        state = r.get("state_fips_code") or r.get("state_ansi")
        f = fips_of(state, county or None)
        if not f or (level == "COUNTY" and len(f) != 5):
            continue
        try:
            y = int(r.get("year", ""))
        except ValueError:
            continue
        yield f, y, nass_crop(commodity), commodity, quals, stat, acres


def crop_acres(records) -> dict[tuple[str, int, str], float]:
    """Acres of each crop in each place and year. Per commodity: its own total where given, else the
    parts at the fewest levels added up (corn for grain plus corn for silage); harvested and bearing
    acres are not added (the larger is kept); commodities that are the same crop (hay, haylage) keep the largest."""
    by: dict[tuple[str, int, str, str, str], list[tuple[tuple[str, ...], float]]] = defaultdict(list)
    for f, y, crop, commodity, quals, stat, acres in records:
        by[(f, y, crop, commodity, stat)].append((quals, acres))
    per_commodity: dict[tuple[str, int, str, str], float] = {}
    for (f, y, crop, commodity, _stat), parts in by.items():
        whole = [a for q, a in parts if not q]
        if whole:
            v = max(whole)
        else:
            groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
            for q, a in parts:
                groups[q[0]].append((len(q), a))
            v = 0.0
            for items in groups.values():
                fewest = min(n for n, _ in items)
                v += sum(a for n, a in items if n == fewest)
        k = (f, y, crop, commodity)
        per_commodity[k] = max(per_commodity.get(k, 0.0), v)
    out: dict[tuple[str, int, str], float] = {}
    for (f, y, crop, _c), v in per_commodity.items():
        out[(f, y, crop)] = max(out.get((f, y, crop), 0.0), v)
    return out


class USDANASS(USConnector):
    source_id = "usda_nass"
    needs_env = ("NASS_API_KEY",)
    keeps_files = True  # a census does not change once out; only one not yet read is asked for
    fetch_every_days = 90

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("NASS_API_KEY")
        last = self.last_vintage_dir(raw_dir)
        asked = got = 0
        for y in census_years():
            for stat in STATS:
                tag = "harvested" if stat == "AREA HARVESTED" else "bearing"
                jobs = [("states", {"agg_level_desc": "STATE"})] + [
                    (s, {"agg_level_desc": "COUNTY", "state_alpha": s}) for s in sorted(STATES.values())]
                for part, extra in jobs:
                    name = f"nass_{y}_{tag}_{part}.csv"
                    if last and (last / name).exists():
                        continue  # carried over by keeps_files
                    q = {"key": key, "source_desc": "CENSUS", "sector_desc": "CROPS", "statisticcat_desc": stat,
                         "unit_desc": "ACRES", "domain_desc": "TOTAL", "year": str(y), "format": "CSV", **extra}
                    if asked:
                        time.sleep(0.4)
                    asked += 1
                    try:
                        r = self.client.get(NASS_API + "?" + urlencode(q), timeout=120)
                    except httpx.HTTPError as exc:
                        log.info("usda_nass: %s %s %s did not answer (%s)", y, tag, part, exc)
                        continue
                    if r.status_code == 401 or (r.status_code == 403 and not got):
                        raise ConnectorError("usda_nass: Quick Stats turned the key away (is NASS_API_KEY right? "
                                             "Sign up at https://quickstats.nass.usda.gov/api)")
                    if r.status_code == 400 and "no data" in r.text.lower():
                        (raw_dir / name).write_text("", encoding="utf-8")  # nothing for this state: remember that
                        continue
                    if r.status_code != 200 or "short_desc" not in r.text[:2000]:
                        log.info("usda_nass: %s %s %s gave HTTP %s", y, tag, part, r.status_code)
                        continue
                    (raw_dir / name).write_text(r.text, encoding="utf-8")
                    got += 1
        if not got and not last:
            raise ConnectorError("usda_nass: Quick Stats gave nothing (is NASS_API_KEY right?)")
        log.info("usda_nass: %s answers from Quick Stats (%s questions)", got, asked)
        return NASS_API

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        records = []
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() in (".csv", ".txt") and p.stat().st_size:
                raw = p.read_bytes()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                records += list(nass_records(text))
        acres = crop_acres(records)
        if not acres:
            raise ConnectorError(f"usda_nass: no crop acres read from {raw_dir}")
        rows = Rows()
        for (f, y, crop), a in acres.items():
            rows.add("us_fips", f, "usreg_crop_area_ha", y, a * ACRE_HA, breakdown=f"crop={crop}")
        self.listed_indicators = [
            _ind("usreg_crop_area_ha", "Crop land by crop (US states and counties)", "Hectares of each crop in each state "
                 "and county at the Census of Agriculture (acres harvested; orchards and vineyards by bearing and "
                 "non-bearing acres), breakdown crop=<id>. Land > Top crops maps the largest.", "ha", "land",
                 self.source_id, "usreg_crop_area_ha", decimals=0, bounds=(0, 5e7), breakdowns=["crop"]),
        ]
        return rows.stage(con, self.source_id, vintage)

