"""Tourism: visitors by country and origin, New Zealand in full, the WEF tourism index
and World Heritage sites (version 4, PR 4). The World Bank's arrivals, receipts and
spending come through world_bank_wdi.

unesco_heritage
    UNESCO World Heritage List (CC BY-SA 3.0 IGO) as XML: about 1,200 sites with their
    type, year listed and whether they are in danger, as a map layer and as counts per
    country by year.
un_tourism
    UN Tourism (UNWTO) data dashboard tables saved by hand in var/manual/un_tourism:
    inbound arrivals (total and by country of origin where given), departures, nights
    and spending. Any CSV or Excel table with a country, a year (or year columns) and
    a figure; the measure is read from an indicator column or the file name.
wef_ttdi
    World Economic Forum Travel & Tourism Development Index (2024) and the older Travel
    & Tourism Competitiveness Index (2007-2019), saved by hand in var/manual/wef_ttdi:
    the overall score and rank and each pillar's score.
nz_tourism
    New Zealand in full, from files saved by hand in var/manual/nz_tourism: visitor
    arrivals by country of residence and purpose (Stats NZ International travel), visitor
    spending by country (MBIE International Visitor Survey) and the Tourism Satellite
    Account (tourism's share of GDP and jobs). Monthly figures add up to full years.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.layers import collection, feature
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num
from worldmodel_data.connectors.transport import iso3_of, read_table

log = logging.getLogger(__name__)
NO_ROWS = EMPTY_OBSERVATIONS

# ----------------------------------------------------------------------------- UNESCO World Heritage
WHC_URL = "https://whc.unesco.org/en/list/xml/"


def whc_sites(xml_text: str) -> list[dict]:
    """The sites in UNESCO's list XML as dicts of their fields."""
    root = ET.fromstring(xml_text)
    out = []
    for row in root.iter("row"):
        out.append({c.tag: (c.text or "").strip() for c in row})
    return out


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


class UNESCOHeritage(Connector):
    source_id = "unesco_heritage"
    switch = "tourism_fetch"
    fetch_every_days = 182

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(WHC_URL, raw_dir / "whc_list.xml")
        return WHC_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.xml"))
        if not files:
            raise ConnectorError(f"unesco_heritage: no XML list in {raw_dir}")
        sites = whc_sites(files[0].read_text(encoding="utf-8", errors="replace"))
        feats, rows = [], Rows()
        inscribed: dict[str, list[int]] = defaultdict(list)
        danger: dict[str, int] = defaultdict(int)
        for s in sites:
            lat, lon = num(s.get("latitude")), num(s.get("longitude"))
            year = num(s.get("date_inscribed"))
            ents = [e for e in (entity_for("iso2", c.strip().upper()) for c in re.split(r"[,;]", s.get("iso_code") or "")) if e]
            in_danger = bool(s.get("danger")) and s.get("danger") not in ("0", "N", "n")
            for e in ents:
                if year:
                    inscribed[e].append(int(year))
                if in_danger:
                    danger[e] += 1
            if lat is None or lon is None:
                continue
            feats.append(feature({"type": "Point", "coordinates": [lon, lat]}, {
                "name": _plain(s.get("site")), "type": (s.get("category") or "").lower() or None,
                "year": int(year) if year else None, "danger": 1 if in_danger else None,
                "countries": ",".join(ents) or None, "url": s.get("http_url") or None,
                "about": _plain(s.get("short_description"))[:300] or None}))
        if not feats:
            raise ConnectorError("unesco_heritage: no sites with a location in the list")
        this_year = date.today().year
        for e, years in inscribed.items():
            years.sort()
            for y in range(years[0], this_year + 1):
                rows.add("iso3", e, "heritage_sites", y, sum(1 for x in years if x <= y))
            rows.add("iso3", e, "heritage_sites_in_danger", this_year, danger.get(e, 0))
        self.layers = [{"layer_id": "heritage_sites", "name": "World Heritage sites", "kind": "point",
                        "description": "UNESCO World Heritage sites: cultural, natural or mixed, with the year listed; red rings are sites in danger.",
                        "feature_count": len(feats), "geojson": collection(feats)}]
        self.listed_indicators = [
            indicator("heritage_sites", "World Heritage sites", "UNESCO World Heritage sites in the country listed by "
                      "that year (a site shared by several countries counts for each).", "sites", "culture",
                      self.source_id, "whc_sites", decimals=0, bounds=(0, 200), aggregation={"method": "sum"}),
            indicator("heritage_sites_in_danger", "World Heritage sites in danger", "Sites on UNESCO's List of World "
                      "Heritage in Danger now.", "sites", "culture", self.source_id, "whc_danger", decimals=0, bounds=(0, 50),
                      aggregation={"method": "sum"}),
        ]
        log.info("unesco_heritage: %s sites", len(feats))
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- tables saved by hand
COUNTRY_HEADS = ("country", "economy", "countryname", "countryofresidence", "reportingcountry", "iso3", "economyiso3",
                 "countrycode", "nationality", "origin", "market")
YEAR_HEADS = ("year", "period", "edition", "time", "date", "yearended")
MEASURE_HEADS = ("indicator", "series", "measure", "variable", "pillar", "indicatorname", "seriesname", "attribute")
VALUE_HEADS = ("value", "score", "amount", "total", "obsvalue", "count", "spend", "arrivals")


def _year_of(v) -> tuple[int, int | None] | None:
    """(year, month or None) from 2024, 2024M01, 2024-01, Jan 2024 or a datetime."""
    if isinstance(v, (datetime, date)):
        return v.year, None
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d{4})(?:\.0)?", s)
    if m:
        return int(m[1]), None
    m = re.fullmatch(r"(\d{4})\s*[-M/]\s*(\d{1,2})", s)
    if m and 1 <= int(m[2]) <= 12:
        return int(m[1]), int(m[2])
    m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    return (int(m[1]), None) if m else None


def figures(table: list[list], measure_default: str) -> list[dict]:
    """Rows of {country, year, month, measure, value, extra} from a long or wide table."""
    for i, row in enumerate(table[:40]):
        heads = [key(c) if c not in (None, "") else "" for c in row]
        cidx = next((j for j, h in enumerate(heads) if h in COUNTRY_HEADS or h.startswith("countryof")), None)
        if cidx is None:
            continue
        yidx = next((j for j, h in enumerate(heads) if h in YEAR_HEADS), None)
        midx = next((j for j, h in enumerate(heads) if h in MEASURE_HEADS), None)
        vidx = next((j for j, h in enumerate(heads) if h in VALUE_HEADS), None)
        if vidx is None:  # "Visitor arrivals", "Total spend"
            vidx = next((j for j, h in enumerate(heads) if j not in (cidx, yidx, midx) and h.endswith(VALUE_HEADS)), None)
        others = {j: h for j, h in enumerate(heads) if h and j not in (cidx, yidx, midx, vidx)}
        out = []
        if yidx is not None and vidx is not None:
            for r in table[i + 1:]:
                if len(r) <= max(cidx, yidx, vidx):
                    continue
                y, v = _year_of(r[yidx]), num(r[vidx])
                if not y or v is None or r[cidx] in (None, ""):
                    continue
                out.append({"country": r[cidx], "year": y[0], "month": y[1],
                            "measure": str(r[midx]) if midx is not None and r[midx] else measure_default, "value": v,
                            "extra": {h: r[j] for j, h in others.items() if j < len(r)}})
            return out
        ycols = {j: _year_of(c) for j, c in enumerate(row) if c not in (None, "") and _year_of(c) and re.search(r"\d{4}", str(c))}
        if ycols:
            for r in table[i + 1:]:
                if len(r) <= cidx or r[cidx] in (None, ""):
                    continue
                for j, y in ycols.items():
                    v = num(r[j]) if j < len(r) else None
                    if v is not None:
                        out.append({"country": r[cidx], "year": y[0], "month": y[1],
                                    "measure": str(r[midx]) if midx is not None and r[midx] else measure_default, "value": v,
                                    "extra": {h: r[k] for k, h in others.items() if k < len(r) and k not in ycols}})
            return out
    return []


def scale_of(text: str) -> float:
    t = text.lower()
    return 1e9 if "billion" in t else 1e6 if "million" in t else 1e3 if "thousand" in t or "(000)" in t or "'000" in t else 1.0


def year_totals(found: list[tuple[tuple, int, int | None, float]]) -> list[tuple[tuple, int, float]]:
    """Monthly figures summed to the year (full years only); yearly figures as they are."""
    months: dict[tuple, dict[int, float]] = defaultdict(dict)
    out = []
    for k, y, m, v in found:
        if m is None:
            out.append((k, y, v))
        else:
            months[(k, y)][m] = months[(k, y)].get(m, 0) + v
    for (k, y), ms in months.items():
        if len(ms) == 12:
            out.append((k, y, sum(ms.values())))
    return out


class _HandTables(Connector):
    manual = True
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError(f"{self.source_id}: save the files by hand (see Data status)")

    def tables(self, raw_dir: Path):
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() in (".csv", ".xlsx", ".xlsm", ".txt"):
                try:
                    yield p, read_table(p)
                except Exception as exc:  # noqa: BLE001 - one unreadable file should not stop the rest
                    log.warning("%s: %s not read (%s)", self.source_id, p.name, exc)


UNT = {  # indicator id -> (name, description, unit, words that must all be in the measure)
    "unt_arrivals": ("Visitor arrivals (UN Tourism)", "Overnight visitors (tourists) arriving from abroad.", "arrivals", ("arriv",)),
    "unt_departures": ("Trips abroad (UN Tourism)", "Trips abroad by the country's residents.", "departures", ("depart",)),
    "unt_nights": ("Nights spent by visitors (UN Tourism)", "Nights visitors from abroad spent in hotels and similar.", "nights", ("night",)),
    "unt_receipts_usd": ("Spending by visitors from abroad (UN Tourism)", "What visitors from abroad spent in the country.", "US$", ("expend", "inbound")),
    "unt_spending_abroad_usd": ("Spending abroad by residents (UN Tourism)", "What the country's residents spent on trips abroad.", "US$", ("expend", "outbound")),
}


class UNTourism(_HandTables):
    source_id = "un_tourism"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        found = []
        for p, table in self.tables(raw_dir):
            for f in figures(table, p.stem):
                text = f"{f['measure']} {p.stem}".lower()
                iid = next((i for i, (*_, words) in UNT.items() if all(w in text for w in words)), None)
                ent = iso3_of(f["country"])
                if not iid or not ent:
                    continue
                origin = next((iso3_of(v) for h, v in f["extra"].items() if h.startswith(("origin", "countryofresidence",
                                                                                          "partner", "source"))), None)
                bd = f"origin={origin}" if origin else ""
                found.append(((ent, iid, bd), f["year"], f["month"], f["value"] * scale_of(text)))
        rows = Rows()
        for (ent, iid, bd), y, v in year_totals(found):
            rows.add("iso3", ent, iid, y, v, breakdown=bd)
        if not len(rows):
            raise ConnectorError(f"un_tourism: no figures read from {raw_dir}")
        used = {r[2] for r in rows.rows}
        self.listed_indicators = [indicator(i, n, d, u, "tourism", self.source_id, i, decimals=0, bounds=(0, 1e13),
                                            aggregation={"method": "sum"}, breakdowns=["origin"])
                                  for i, (n, d, u, _) in UNT.items() if i in used]
        return rows.stage(con, self.source_id, vintage)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:50]


class WEFTTDI(_HandTables):
    source_id = "wef_ttdi"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for p, table in self.tables(raw_dir):
            for f in figures(table, "Travel & Tourism Development Index"):
                ent = iso3_of(f["country"])
                attr = str(next((v for h, v in f["extra"].items() if h in ("attribute", "type", "measure")), "score")).lower()
                if not ent:
                    continue
                m = f["measure"]
                overall = bool(re.search(r"development index|competitiveness index|overall|ttdi|ttci", m, re.I)) or m == p.stem
                if "rank" in attr or "rank" in m.lower():
                    if overall:
                        rows.add("iso3", ent, "ttdi_rank", f["year"], f["value"])
                    continue
                if "score" not in attr and "value" not in attr:
                    continue
                rows.add("iso3", ent, "ttdi_score", f["year"], f["value"], breakdown="" if overall else f"pillar={m.strip()[:60]}")
        if not len(rows):
            raise ConnectorError(f"wef_ttdi: no scores read from {raw_dir}")
        self.listed_indicators = [
            indicator("ttdi_score", "Travel and tourism development index (WEF)", "World Economic Forum's score for how "
                      "well a country is set up for travel and tourism, 1 to 7 (the Travel & Tourism Competitiveness Index "
                      "before 2021, with a different method). Pillars as breakdowns.", "score", "tourism", self.source_id,
                      "ttdi_score", decimals=2, bounds=(0, 7.01), breakdowns=["pillar"]),
            indicator("ttdi_rank", "Travel and tourism development rank (WEF)", "The country's rank in the WEF index "
                      "(1 = best).", "rank", "tourism", self.source_id, "ttdi_rank", decimals=0, bounds=(1, 200)),
        ]
        return rows.stage(con, self.source_id, vintage)


NZT = {  # indicator id -> (name, description, unit, words in the measure or file name)
    "nz_visitor_arrivals": ("Visitor arrivals to New Zealand", "Overseas visitors arriving, by country of residence "
                            "(Stats NZ International travel).", "arrivals", ("arriv",)),
    "nz_visitor_spend": ("Visitor spending in New Zealand", "What overseas visitors spent, by country of residence "
                         "(MBIE International Visitor Survey).", "NZ$", ("spend",)),
    "nz_tourism_gdp_share": ("Tourism's direct share of New Zealand's GDP", "Tourism direct GDP as a share of GDP "
                             "(Stats NZ Tourism Satellite Account).", "%", ("gdp",)),
    "nz_tourism_jobs": ("People employed directly in tourism in New Zealand", "Tourism Satellite Account.", "people", ("employ",)),
}


class NZTourism(_HandTables):
    source_id = "nz_tourism"
    pack = "nz"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        found = []
        for p, table in self.tables(raw_dir):
            for f in figures(table, p.stem):
                text = f"{f['measure']} {p.stem}".lower()
                iid = next((i for i, (*_, words) in NZT.items() if all(w in text for w in words)), None)
                if not iid:
                    continue
                origin_text = str(f["country"]).strip()
                total = origin_text.lower().startswith(("total", "all"))
                origin = None if total else iso3_of(origin_text)
                if not total and not origin:
                    continue
                purpose = next((str(v) for h, v in f["extra"].items() if "purpose" in h and v), None)
                if purpose and purpose.lower().startswith(("total", "all")):
                    purpose = None
                if origin and purpose:
                    continue  # by origin, or by purpose, but not both
                bd = f"origin={origin}" if origin else f"purpose={purpose[:40]}" if purpose else ""
                found.append(((iid, bd), f["year"], f["month"], f["value"] * scale_of(text)))
        rows = Rows()
        for (iid, bd), y, v in year_totals(found):
            rows.add("iso3", "NZL", iid, y, v, breakdown=bd)
        if not len(rows):
            raise ConnectorError(f"nz_tourism: no figures read from {raw_dir}")
        used = {r[2] for r in rows.rows}
        self.listed_indicators = [indicator(i, n, d, u, "tourism", self.source_id, i, decimals=1 if u == "%" else 0,
                                            bounds=(0, 1e12), breakdowns=["origin", "purpose"])
                                  for i, (n, d, u, _) in NZT.items() if i in used]
        return rows.stage(con, self.source_id, vintage)
