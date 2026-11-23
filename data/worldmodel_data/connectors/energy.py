"""Energy balances for every country and the power traded between countries (Settings >
Energy, "Energy flows and power links").

unsd_energy
    UN Statistics Division energy statistics through its SDMX API (dataflow DF_UNDATA_ENERGY,
    keyless, free to reuse with UNSD cited): each country's production, trade, conversion and
    use of every fuel since 1990, in the fuel's own unit with a factor to terajoules. Turned
    into energy balance rows by fuel group (energy_flow.unsd_rows) and stored as
    energy_balance_pj with breakdown flow=<row>|fuel=<group>, the same indicator MBIE's New
    Zealand balance uses, so the energy flow chart draws any country. Summed for groups.
    Asked for ten countries at a time, a second apart; each answer kept gzipped (about 100 MB
    in all).
eurostat_power_trade
    Eurostat nrg_ti_eh and nrg_te_eh (JSON-stat, keyless): electricity each European country
    imports from and exports to each partner, GWh a year since 1990. Stored as
    elec_imports_gwh and elec_exports_gwh with breakdown origin=<partner>, and drawn on the
    map as the "Power links between countries" layer.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import httpx

from worldmodel_contract import catalogue
from worldmodel_contract.energy_flow import RENEWABLE, SUPPLY_SIGN, UN_TRANSACTIONS, _key, unsd_rows
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, num
from worldmodel_data.connectors.transport import EUROSTAT, eu_entity, jsonstat_rows

log = logging.getLogger(__name__)

SWITCH = "energy_flows_fetch"
UNSD_DATA = "https://data.un.org/ws/rest/data/UNSD,DF_UNDATA_ENERGY,1.2/A.{areas}..{transactions}/ALL/?startPeriod={start}"
UNSD_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}
BATCH = 10
START = 1990


def unsd_cells(lines) -> dict[tuple[str, int], dict[tuple[str, str], float]]:
    """An SDMX-CSV answer as {(M49 area, year): {(commodity, transaction): terajoules}}. Rows
    without a factor to terajoules (capacity, reserves, uranium in tonnes) are left out."""
    out: dict[tuple[str, int], dict[tuple[str, str], float]] = defaultdict(dict)
    for r in csv.DictReader(lines):
        v, f, y = num(r.get("OBS_VALUE")), num(r.get("CONVERSION_FACTOR")), num(r.get("TIME_PERIOD"))
        if v is None or f is None or y is None:
            continue
        out[(str(r.get("REF_AREA") or "").strip(), int(y))][(str(r["COMMODITY"]).strip(), str(r["TRANSACTION"]).strip())] = v * f
    return out


def un_areas() -> list[str]:
    """The M49 codes of the countries and territories the catalogue holds, as the UN writes them."""
    codes = set()
    for e in catalogue.entities().values():
        if e.type == "country" and getattr(e, "m49", None):
            codes.add(str(e.m49).split(".")[0].zfill(3))
    return sorted(codes)


class UNSDEnergy(Connector):
    source_id = "unsd_energy"
    switch = SWITCH
    fetch_every_days = 90  # updated once a year, usually in the northern spring

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        areas = un_areas()
        failed = []
        for i in range(0, len(areas), BATCH):
            part = areas[i:i + BATCH]
            url = UNSD_DATA.format(areas="+".join(part), transactions="+".join(UN_TRANSACTIONS), start=START)
            tmp = raw_dir / f"unsd_{i // BATCH:03d}.csv"
            try:
                self.get(url, tmp, headers=UNSD_CSV, cached=False)
            except (ConnectorError, httpx.HTTPError) as exc:
                log.info("unsd_energy: countries %s not read (%s)", ",".join(part), exc)
                failed += part
                continue
            with tmp.open("rb") as src, gzip.open(tmp.with_suffix(".csv.gz"), "wb") as dst:
                dst.write(src.read())
            tmp.unlink()
            time.sleep(1)
        if len(failed) > len(areas) / 2:
            raise ConnectorError(f"unsd_energy: the UN energy API turned away {len(failed)} of {len(areas)} countries; "
                                 "try the refresh again later")
        return UNSD_DATA.format(areas="...", transactions="...", start=START)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv.gz")) + sorted(raw_dir.glob("*.csv"))
        if not files:
            raise ConnectorError(f"unsd_energy: no saved answers in {raw_dir}")
        cells: dict[tuple[str, int], dict] = {}
        for p in files:
            opener = gzip.open if p.suffix == ".gz" else open
            with opener(p, "rt", encoding="utf-8-sig", newline="") as fh:
                cells.update(unsd_cells(fh))
        rows = Rows()
        for (area, year), c in sorted(cells.items()):
            ent = entity_for("m49", area)
            if not ent:
                continue
            supply: dict[str, float] = defaultdict(float)
            for flow_name, group, pj in unsd_rows(c):
                rows.add("iso3", ent, "energy_balance_pj", year, pj, breakdown=f"flow={flow_name}|fuel={group}")
                if _key(flow_name) in SUPPLY_SIGN:
                    supply[group] += SUPPLY_SIGN[_key(flow_name)] * pj
            total = sum(supply.values())
            if total > 0:
                rows.add("iso3", ent, "energy_primary_supply_pj", year, total)
                rows.add("iso3", ent, "energy_renewable_share_primary", year,
                         max(0.0, min(100.0, 100 * sum(v for g, v in supply.items() if g in RENEWABLE) / total)))
        if not len(rows):
            raise ConnectorError("unsd_energy: no energy figures read from the saved answers")
        note = "UN Statistics Division energy statistics (DF_UNDATA_ENERGY), turned into a balance by fuel group."
        self.listed_indicators = [
            indicator("energy_balance_pj", "Energy balance (by flow and fuel)",
                      "Each row of the energy balance: supply, transformation and use by sector, for each fuel "
                      "(breakdown flow=<row>|fuel=<fuel>). Drawn as the energy flow chart. " + note,
                      "PJ", "energy", self.source_id, "DF_UNDATA_ENERGY balance", decimals=2, breakdowns=["flow", "fuel"],
                      default_on=False, aggregation={"method": "sum"}),
            indicator("energy_primary_supply_pj", "Primary energy supply",
                      "Energy produced at home plus imports, less exports, stock building and fuel for international "
                      "ships and planes. Nuclear counts at its heat (33% efficient), geothermal at its heat. " + note,
                      "PJ", "energy", self.source_id, "TES", decimals=0, aggregation={"method": "sum"}, bounds=(0, 1e7)),
            indicator("energy_renewable_share_primary", "Renewable share of primary energy",
                      "Hydro, geothermal, wind, solar and bioenergy (wood and other biomass included) as a share of "
                      "primary energy supply. " + note, "% of primary energy", "energy", self.source_id, "TES renewable share",
                      bounds=(0, 100), aggregation={"method": "weighted_mean", "weight": "energy_primary_supply_pj"}),
        ]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- power trade
POWER_TRADE = (("nrg_ti_eh", "elec_imports_gwh"), ("nrg_te_eh", "elec_exports_gwh"))


class EurostatPowerTrade(Connector):
    source_id = "eurostat_power_trade"
    switch = SWITCH
    fetch_every_days = 90

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = ""
        for code, _ in POWER_TRADE:
            url = EUROSTAT.format(code=code, query=urlencode({"format": "JSON", "lang": "EN", "siec": "E7000", "unit": "GWH",
                                                              "sinceTimePeriod": str(START)}))
            self.get(url, raw_dir / f"eurostat_{code}.json")
            time.sleep(1)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for code, ind in POWER_TRADE:
            p = raw_dir / f"eurostat_{code}.json"
            if not p.exists():
                continue
            for cell, v in jsonstat_rows(json.loads(p.read_text(encoding="utf-8"))):
                geo, partner, year = eu_entity(cell.get("geo") or ""), cell.get("partner") or "", num(cell.get("time"))
                if not geo or year is None or v <= 0:
                    continue
                if partner == "TOTAL":
                    rows.add("iso3", geo, ind, int(year), v)
                    continue
                other = eu_entity(partner)
                if other and other != geo:
                    rows.add("iso3", geo, ind, int(year), v, breakdown=f"origin={other}")
        if not len(rows):
            raise ConnectorError(f"eurostat_power_trade: no electricity trade read in {raw_dir}")
        note = "Eurostat nrg_ti_eh / nrg_te_eh (electricity, GWh); by partner country (breakdown origin=<partner>)."
        self.listed_indicators = [
            indicator("elec_imports_gwh", "Electricity imports", "Electricity bought from other countries, in total and "
                      "from each neighbour. " + note, "GWh", "energy", self.source_id, "nrg_ti_eh E7000", decimals=0,
                      breakdowns=["origin"], bounds=(0, 1e7)),
            indicator("elec_exports_gwh", "Electricity exports", "Electricity sold to other countries, in total and "
                      "to each neighbour. " + note, "GWh", "energy", self.source_id, "nrg_te_eh E7000", decimals=0,
                      breakdowns=["origin"], bounds=(0, 1e7)),
        ]
        return rows.stage(con, self.source_id, vintage)
