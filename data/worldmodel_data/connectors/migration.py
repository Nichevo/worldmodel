"""Migration in and out: who lives in a country having been born elsewhere, who was
born there and lives abroad, and refugees.

un_ims
    UN DESA International Migrant Stock (2024 edition): one Excel file,
    undesa_pd_YYYY_ims_stock_by_sex_destination_and_origin.xlsx, linked from the
    edition's page. Sheet "Table 1": one row per destination and origin (countries,
    regions and the World, by UN M49 code), people born abroad at mid-year, for
    1990, 1995 ... 2020 and 2024, both sexes first, then men, then women.
    migrant_stock    people living in the country who were born abroad (origin World)
    emigrant_stock   people born in the country living abroad (destination World)
    migrant_stock_by_origin
                     the same by country of birth, breakdown origin=<country>; read
                     the other way round (breakdown origin=X across destinations)
                     it gives where X's emigrants live

unhcr
    UNHCR Refugee Data Finder API (api.unhcr.org/population/v1/population), every
    country of origin against every country of asylum, 1951 on, paged (10,000 rows
    a page, a second apart). Refugees and asylum seekers hosted and fled, people
    displaced inside their own country, stateless people, and refugees hosted by
    country of origin (breakdown origin=<country>).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import (Rows, entity_for, indicator, is_country, key, num, xlsx_rows,
                                                xlsx_sheet_names)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------- UN IMS
IMS_PAGE = "https://www.un.org/development/desa/pd/content/international-migrant-stock"
IMS_SITE = "https://www.un.org"
IMS_FILE = re.compile(r"""href=["']([^"']*undesa_pd_(\d{4})_ims_stock_by_sex_destination_and_origin\.xlsx)["']""", re.I)
WORLD = "900"


class UNIMS(Connector):
    source_id = "un_ims"
    fetch_every_days = 90  # a new edition every few years

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            if m := re.search(r"undesa_pd_(\d{4})_ims", f.name, re.I):
                return m.group(1)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        page = raw_dir / "page.html"
        self.get(IMS_PAGE, page)
        html = page.read_text(encoding="utf-8", errors="replace")
        page.unlink()
        links = IMS_FILE.findall(html)
        if not links:
            raise ConnectorError(
                f"un_ims: no undesa_pd_YYYY_ims_stock_by_sex_destination_and_origin.xlsx link on {IMS_PAGE}; the page "
                "may have changed. Download the file by hand and load it with: worldmodel-data fetch un_ims --from <file>")
        link = max(links, key=lambda x: x[1])[0]
        url = link if link.startswith("http") else IMS_SITE + link
        self.get(url, raw_dir / Path(url).name)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.xlsx"))
        if not files:
            raise ConnectorError(f"un_ims: no .xlsx file in {raw_dir}")
        path = files[-1]
        names = xlsx_sheet_names(path)
        sheet = next((n for n in names if key(n) == "table1"), names[0])
        table = xlsx_rows(path, sheet)
        head = next((i for i, r in enumerate(table[:30])
                     if any("codeofdestination" in key(c) for c in r) and any("codeoforigin" in key(c) for c in r)), None)
        if head is None:
            raise ConnectorError(f"un_ims: {path.name} has no header naming the location codes of destination and origin")
        header = table[head]
        dest = next(i for i, c in enumerate(header) if "codeofdestination" in key(c))
        orig = next(i for i, c in enumerate(header) if "codeoforigin" in key(c))
        years: dict[int, int] = {}  # column -> year, first block only (both sexes)
        for i, c in enumerate(header):
            y = int(num(c)) if num(c) is not None and 1900 < num(c) < 2100 else None
            if y and y not in years.values():
                years[i] = y
        if not years:
            raise ConnectorError(f"un_ims: no year columns in {path.name}")
        rows = Rows()
        for r in table[head + 1:]:
            if len(r) <= max(dest, orig) or r[dest] is None or r[orig] is None:
                continue
            d, o = _code(r[dest]), _code(r[orig])
            for i, y in years.items():
                v = num(r[i]) if i < len(r) else None
                if v is None:
                    continue
                if o == WORLD:
                    rows.add("un_wpp", d, "migrant_stock", y, v)
                elif d == WORLD:
                    rows.add("un_wpp", o, "emigrant_stock", y, v)
                elif is_country(origin := entity_for("m49", o)) and is_country(entity_for("m49", d)) and v > 0:
                    rows.add("un_wpp", d, "migrant_stock_by_origin", y, v, breakdown=f"origin={origin}")
        if not len(rows):
            raise ConnectorError(f"un_ims: no values read from {path.name}")
        self.listed_indicators = IMS_INDICATORS
        return rows.stage(con, self.source_id, vintage)


def _code(v) -> str:
    return str(v).strip().split(".")[0].lstrip("0") or "0"


IMS_NOTE = "UN DESA International Migrant Stock: people living outside their country of birth (or citizenship, where " \
           "birthplace is not recorded), at mid-year."
IMS_INDICATORS = [
    indicator("migrant_stock", "Immigrants living in the country",
              "People living in the country who were born in another country. " + IMS_NOTE,
              "persons", "migration", "un_ims", "Table 1: origin World", decimals=0, aggregation={"method": "sum"}),
    indicator("emigrant_stock", "Emigrants living abroad",
              "People born in the country who live in another country. " + IMS_NOTE,
              "persons", "migration", "un_ims", "Table 1: destination World", decimals=0, aggregation={"method": "sum"}),
    indicator("migrant_stock_by_origin", "Immigrants by country of birth",
              "People living in the country by the country they were born in (breakdown origin=<country>). " + IMS_NOTE,
              "persons", "migration", "un_ims", "Table 1", decimals=0, breakdowns=["origin"], default_on=False),
]


# ----------------------------------------------------------------------------------------------- UNHCR
UNHCR_API = "https://api.unhcr.org/population/v1/population/"
UNHCR_PAGE_SIZE = 10000
UNHCR_FIELDS = {  # API field -> (hosted indicator, fled indicator)
    "refugees": ("refugees_hosted", "refugees_from"),
    "asylum_seekers": ("asylum_seekers_hosted", "asylum_seekers_from"),
    "oip": ("protection_needed_hosted", None),
    "idps": (None, "idps"),
    "stateless": ("stateless", None),
}


class UNHCR(Connector):
    source_id = "unhcr"
    fetch_every_days = 30
    pause_seconds = 1.0

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        page, pages = 1, 1
        while page <= pages:
            if page > 1:
                time.sleep(self.pause_seconds)
            url = f"{UNHCR_API}?limit={UNHCR_PAGE_SIZE}&page={page}&coo_all=true&coa_all=true&yearFrom=1951"
            dest = raw_dir / f"population_{page:03d}.json"
            self.get(url, dest)
            data = json.loads(dest.read_text(encoding="utf-8"))
            pages = min(int(data.get("maxPages") or 1), 200)
            if not data.get("items"):
                dest.unlink()
                break
            page += 1
        return f"{UNHCR_API}?coo_all=true&coa_all=true ({page - 1} pages)"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        totals: dict[tuple[str, str, int], float] = {}
        by_origin: dict[tuple[str, str, int], float] = {}
        for p in sorted(raw_dir.glob("population_*.json")):
            for it in json.loads(p.read_text(encoding="utf-8")).get("items", []):
                try:
                    y = int(it.get("year"))
                except (TypeError, ValueError):
                    continue
                coo, coa = str(it.get("coo_iso") or "").upper(), str(it.get("coa_iso") or "").upper()
                for field, (hosted, fled) in UNHCR_FIELDS.items():
                    v = num(it.get(field))
                    if not v:
                        continue
                    if hosted and coa:
                        totals[(coa, hosted, y)] = totals.get((coa, hosted, y), 0) + v
                    if fled and coo:
                        totals[(coo, fled, y)] = totals.get((coo, fled, y), 0) + v
                    if field == "refugees" and coa and is_country(origin := entity_for("iso3", coo)) and origin != coa:
                        by_origin[(coa, origin, y)] = by_origin.get((coa, origin, y), 0) + v
        rows = Rows()
        for (c, ind, y), v in totals.items():
            rows.add("iso3", c, ind, y, v)
        for (c, origin, y), v in by_origin.items():
            rows.add("iso3", c, "refugees_by_origin", y, v, breakdown=f"origin={origin}")
        if not len(rows):
            raise ConnectorError(f"unhcr: no values read from {raw_dir}")
        self.listed_indicators = UNHCR_INDICATORS
        return rows.stage(con, self.source_id, vintage)


UNHCR_NOTE = "UNHCR Refugee Data Finder, end of year."
_sum = {"method": "sum"}
UNHCR_INDICATORS = [
    indicator("refugees_hosted", "Refugees hosted", "Refugees under UNHCR's mandate living in the country. " + UNHCR_NOTE,
              "persons", "migration", "unhcr", "refugees by country of asylum", decimals=0, aggregation=_sum),
    indicator("refugees_from", "Refugees from the country",
              "Refugees under UNHCR's mandate who fled the country, wherever they now live. " + UNHCR_NOTE,
              "persons", "migration", "unhcr", "refugees by country of origin", decimals=0, aggregation=_sum),
    indicator("asylum_seekers_hosted", "Asylum seekers hosted",
              "People in the country whose claim for refugee status has not yet been decided. " + UNHCR_NOTE,
              "persons", "migration", "unhcr", "asylum_seekers by country of asylum", decimals=0, aggregation=_sum),
    indicator("asylum_seekers_from", "Asylum seekers from the country",
              "People from the country waiting abroad for a decision on their asylum claim. " + UNHCR_NOTE,
              "persons", "migration", "unhcr", "asylum_seekers by country of origin", decimals=0, aggregation=_sum),
    indicator("protection_needed_hosted", "Others in need of protection hosted",
              "People outside their country who need international protection but are not counted as refugees or "
              "asylum seekers (many Venezuelans abroad, for example). " + UNHCR_NOTE,
              "persons", "migration", "unhcr", "oip by country of asylum", decimals=0, aggregation=_sum),
    indicator("idps", "Internally displaced people",
              "People forced from their homes who stay inside their own country (conflict; those UNHCR assists). "
              + UNHCR_NOTE, "persons", "migration", "unhcr", "idps", decimals=0, aggregation=_sum),
    indicator("stateless", "Stateless people", "People no country recognises as its citizens, living in the country. "
              + UNHCR_NOTE, "persons", "migration", "unhcr", "stateless", decimals=0, aggregation=_sum),
    indicator("refugees_by_origin", "Refugees hosted by country of origin",
              "Refugees living in the country by the country they fled (breakdown origin=<country>). " + UNHCR_NOTE,
              "persons", "migration", "unhcr", "refugees by origin and asylum", decimals=0, breakdowns=["origin"],
              default_on=False),
]
