"""Energy balances from the UN's energy statistics (New Zealand's 2022 answer, as the API gave it,
and a small French one with nuclear) and electricity trade between European countries."""

import csv
import gzip
import json
import shutil
from pathlib import Path

import duckdb
import pytest
from worldmodel_contract.energy_flow import flow, unsd_rows
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.energy import unsd_cells
from worldmodel_data.vintage_store import VintageStore

FIX = Path(__file__).parent / "fixtures"
HEAD = "DATAFLOW,FREQ,REF_AREA,COMMODITY,TRANSACTION,TIME_PERIOD,OBS_VALUE,UNIT_MULT,UNIT_MEASURE,OBS_STATUS,CONVERSION_FACTOR\n"
FRANCE = HEAD + "".join(f"UNSD:DF_UNDATA_ENERGY(1.2),A,250,{c},{t},2022,{v},0,{u},A,{f}\n" for c, t, v, u, f in (
    ("7000N", "01", 294700, "GWHR", 3.6), ("7000H", "01", 49600, "GWHR", 3.6), ("7000", "01", 470000, "GWHR", 3.6),
    ("7000", "04", 33000, "GWHR", 3.6), ("7000", "03", 49000, "GWHR", 3.6), ("7000", "1231", 160000, "GWHR", 3.6),
    ("7000", "121", 110000, "GWHR", 3.6), ("3000", "03", 1700000, "TJ", 1), ("3000", "088", 300000, "TJ", 1),
    ("3000", "1231", 500000, "TJ", 1), ("8000", "01", 150000, "TJ", 1), ("8000", "1231", 120000, "TJ", 1),
    ("9101", "01", 0, "TN", ""),
))


def trade(rows: list[tuple[str, str, int, float]]) -> dict:
    """A JSON-stat answer like Eurostat's for nrg_ti_eh / nrg_te_eh (geo, partner, time)."""
    geos = sorted({r[0] for r in rows})
    partners = sorted({r[1] for r in rows})
    times = sorted({str(r[2]) for r in rows})
    value = {}
    for g, p, t, v in rows:
        value[str((geos.index(g) * len(partners) + partners.index(p)) * len(times) + times.index(str(t)))] = v
    return {"id": ["geo", "partner", "time"],
            "size": [len(geos), len(partners), len(times)],
            "dimension": {"geo": {"category": {"index": {g: i for i, g in enumerate(geos)}}},
                          "partner": {"category": {"index": {p: i for i, p in enumerate(partners)}}},
                          "time": {"category": {"index": {t: i for i, t in enumerate(times)}}}},
            "value": value}


def nz_cells() -> dict:
    with (FIX / "unsd_energy" / "554.csv").open(encoding="utf-8") as fh:
        return unsd_cells(fh)[("554", 2022)]


def test_nz_balance_from_un_figures():
    f = flow(unsd_rows(nz_cells()))
    t = f["totals"]
    # MBIE's own balance for 2022 gives about 830 PJ of primary energy and 209 PJ for transport; the UN's
    # figures for the same year land close (geothermal counted at its heat in both).
    assert 790 < t["primary_supply"] < 850
    assert t["use_by_sector"]["Transport"] == pytest.approx(205.1, abs=0.5)
    assert t["electricity_generated"] == pytest.approx(44663.246 * 3.6 / 1000, abs=0.01)
    links = {(x["source"], x["target"]): x["value"] for x in f["links"]}
    assert links[("Geothermal", "Electricity generation")] == pytest.approx(197.583, abs=0.01)  # DG heat, not 7000G / 10%
    assert links[("Hydro", "Electricity generation")] == pytest.approx(26273.578 * 3.6 / 1000, abs=0.01)
    assert links[("Oil", "Transport")] > 200 and links[("Electricity", "Residential")] > 40
    assert ("Electricity generation", "Heat") in links
    # The parts of hard coal are used, not the total line beside them (else coal would count twice).
    assert t["supply_by_group"]["Coal"] < 40


def test_nuclear_and_heat():
    cells = unsd_cells(FRANCE.splitlines(keepends=True))[("250", 2022)]
    assert ("9101", "01") not in cells  # uranium in tonnes has no factor to terajoules
    f = flow(unsd_rows(cells))
    links = {(x["source"], x["target"]): x["value"] for x in f["links"]}
    assert links[("Nuclear", "Electricity generation")] == pytest.approx(294700 * 3.6 / 0.33 / 1000, rel=1e-3)
    assert links[("Electricity generation", "Heat")] == pytest.approx(150)
    assert links[("Heat", "Residential")] == pytest.approx(120)
    assert f["totals"]["supply_by_group"]["Nuclear"] > 3000


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("energy")
    home = Paths(tmp / "var")
    store = VintageStore(home)
    d = tmp / "unsd_energy"
    d.mkdir()
    with (FIX / "unsd_energy" / "554.csv").open("rb") as src, gzip.open(d / "unsd_000.csv.gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    (d / "unsd_001.csv").write_text(FRANCE, encoding="utf-8")
    CONNECTORS["unsd_energy"]().ingest(store, d)
    t = tmp / "eurostat_power_trade"
    t.mkdir()
    (t / "eurostat_nrg_ti_eh.json").write_text(json.dumps(trade([("IT", "FR", 2023, 18000.0), ("IT", "CH", 2023, 20000.0),
                                                                  ("IT", "TOTAL", 2023, 51000.0), ("FR", "IT", 2023, 1500.0)])))
    (t / "eurostat_nrg_te_eh.json").write_text(json.dumps(trade([("FR", "IT", 2023, 18500.0), ("FR", "TOTAL", 2023, 50000.0)])))
    CONNECTORS["eurostat_power_trade"]().ingest(store, t)
    return duckdb.connect(str(build(home).path), read_only=True)


def test_build(con):
    n = con.execute("SELECT count(*) FROM series WHERE indicator_id = 'energy_balance_pj' AND entity_id = 'NZL' "
                    "AND source_id = 'unsd_energy'").fetchone()[0]
    assert n > 30
    v = dict(con.execute("SELECT indicator_id, value FROM series WHERE entity_id = 'NZL' AND breakdown = '' "
                         "AND source_id = 'unsd_energy' AND year(period_start) = 2022").fetchall())
    assert 790 < v["energy_primary_supply_pj"] < 850 and 30 < v["energy_renewable_share_primary"] < 60
    # The balance is summed for groups, as the flow chart for Oceania or the world needs.
    world = con.execute("SELECT value FROM series WHERE entity_id = 'oceania' AND indicator_id = 'energy_balance_pj' "
                        "AND breakdown = 'flow=Indigenous production|fuel=Geothermal'").fetchone()
    assert world and world[0] > 190
    imp = dict(con.execute("SELECT breakdown, value FROM series WHERE entity_id = 'ITA' AND indicator_id = 'elec_imports_gwh'").fetchall())
    assert imp == {"": 51000.0, "origin=FRA": 18000.0, "origin=CHE": 20000.0}
    assert con.execute("SELECT value FROM series WHERE entity_id = 'FRA' AND indicator_id = 'elec_exports_gwh' "
                       "AND breakdown = 'origin=ITA'").fetchone()[0] == 18500.0


def test_download_in_batches(tmp_path, monkeypatch):
    import httpx

    from worldmodel_data.connectors import energy

    monkeypatch.setattr(energy, "un_areas", lambda: ["036", "554", "250"])
    monkeypatch.setattr(energy, "BATCH", 2)
    monkeypatch.setattr(energy.time, "sleep", lambda s: None)
    asked = []
    body = (FIX / "unsd_energy" / "554.csv").read_text(encoding="utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append((str(req.url), req.headers.get("accept")))
        return httpx.Response(200, text=body) if "554" in str(req.url) else httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    CONNECTORS["unsd_energy"](client=client).download(tmp_path, "2026-11")
    assert [p.name for p in sorted(tmp_path.glob("*.gz"))] == ["unsd_000.csv.gz"]
    assert "A.036+554..01+03+04" in asked[0][0] and "sdmx.data+csv" in asked[0][1]
    with gzip.open(tmp_path / "unsd_000.csv.gz", "rt", encoding="utf-8") as fh:
        assert next(csv.reader(fh))[0] == "DATAFLOW"
