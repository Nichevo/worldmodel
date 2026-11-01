"""New Zealand pack: RBNZ spreadsheets (and, as more NZ sources land, the rest)."""

from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.nz import read_rbnz
from worldmodel_data.vintage_store import VintageStore


def rbnz_file(path: Path, series: list[tuple[str, str, str, str]], values) -> Path:
    """An RBNZ-shaped spreadsheet: Series Definitions, and Data with 4 header rows then dates."""
    wb = Workbook()
    d = wb.active
    d.title = "Data"
    d.append(["Notes"] + [""] * len(series))
    d.append(["Group"] + [s[0] for s in series])
    d.append(["Series"] + [s[1] for s in series])
    d.append(["Unit"] + [s[2] for s in series])
    d.append(["Series Id"] + [s[3] for s in series])
    for month, vals in values:
        d.append([month, *vals])
    m = wb.create_sheet("Series Definitions")
    m.append(["Group", "Series", "Unit", "Series Id"])
    for s in series:
        m.append(list(s))
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("rbnz")
    rbnz_file(d / "hb2-monthly-close.xlsx", [
        ("Cash rate", "Official Cash Rate (OCR)", "Percent", "INM.MG111.N"),
        ("Government bonds", "10 year", "Percent", "INM.MG110.NZC"),
    ], [(datetime(2024, m, 28), [5.5 if m < 8 else 4.25, 4.6]) for m in range(1, 13)])
    rbnz_file(d / "hb20.xlsx", [
        ("New residential mortgage standard interest rates", "Floating", "Percent", "MRS.MS1.N"),
        ("New residential mortgage standard interest rates", "2 years", "Percent", "MRS.MS4.N"),
    ], [(datetime(2024, m, 28), [8.6, 6.9]) for m in range(1, 13)])
    rbnz_file(d / "hb1-monthly.xlsx", [
        ("Exchange rates", "United States dollar", "USD per NZD", "EXR.MS11.D06"),
        ("Exchange rates", "Trade weighted index (TWI-17)", "Index", "EXR.MS11.D51"),
    ], [(datetime(2024, m, 28), [0.6, 70.0]) for m in range(1, 13)])
    return d


def test_read_rbnz(files):
    series = read_rbnz(files / "hb2-monthly-close.xlsx")
    assert [s["id"] for s in series] == ["INM.MG111.N", "INM.MG110.NZC"] and len(series[0]["points"]) == 12


def test_rbnz_series(files, tmp_path):
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, Path(__file__).parent / "fixtures" / "imf_weo")
    CONNECTORS["rbnz"]().ingest(store, files)
    con = duckdb.connect(str(build(home).path), read_only=True)

    def v(ind):
        return con.execute("SELECT value FROM series WHERE entity_id = 'NZL' AND indicator_id = ? AND "
                           "period_start = '2024-01-01'", [ind]).fetchone()[0]
    assert v("rbnz_ocr") == pytest.approx((7 * 5.5 + 5 * 4.25) / 12)
    assert v("rbnz_govt_bond_10y") == pytest.approx(4.6)
    assert v("rbnz_mortgage_floating") == pytest.approx(8.6) and v("rbnz_mortgage_2y") == pytest.approx(6.9)
    assert v("rbnz_nzd_usd") == pytest.approx(0.6) and v("rbnz_twi") == pytest.approx(70)
    on = dict(con.execute("SELECT indicator_id, default_on FROM indicators WHERE indicator_id LIKE 'rbnz%'").fetchall())
    assert on["rbnz_ocr"] is True and len(on) == 6


def test_corrections_quarterly_pages(tmp_path):
    from worldmodel_data.connectors.nz import QUARTER_LINK, read_prison_page

    fixtures = Path(__file__).parent / "fixtures" / "nz_corrections"
    got = read_prison_page((fixtures / "prisons_2025-12.html").read_text())
    assert got["total"] == 10860 and got["remand_accused"] == 2776 and got["total_female"] == 756
    assert QUARTER_LINK.findall('<a href="/resources/statistics/quarterly_prison_statistics/'
                                'prison_facts_and_statistics_-_december_2025">x</a>')[0][1:] == ("december", "2025")
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, Path(__file__).parent / "fixtures" / "imf_weo")
    CONNECTORS["nz_corrections"]().ingest(store, fixtures)
    con = duckdb.connect(str(build(home).path), read_only=True)
    vals = dict(con.execute("SELECT year(period_start), value FROM series WHERE entity_id = 'NZL' "
                            "AND indicator_id = 'nz_prisoners_total'").fetchall())
    assert vals == {2024: 10300, 2025: 10860}  # each year's latest quarter


FIX = Path(__file__).parent / "fixtures"


def test_rbnz_real_file_and_history(tmp_path):
    """RBNZ's own B2 monthly-close file says its sheet is one cell (A1), which once read as
    empty; a history file loaded beside it fills the earlier years, and stays when the
    current files are fetched again."""
    series = {s["id"]: s for s in read_rbnz(FIX / "rbnz" / "hb2-monthly-close.xlsx")}
    assert len(series) == 25 and series["INM.MP1.N.nae"]["points"][0][1] == 1.75
    hist = tmp_path / "hist"
    hist.mkdir()
    rbnz_file(hist / "hb2-daily-close-1985-2017.xlsx", [("Cash rate", "Official Cash Rate (OCR)", "%pa", "INM.DP1.N")],
              [(datetime(2017, 1, 2 + d), [1.75]) for d in range(20)] + [(datetime(2018, 1, 3), [9.0])])
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, FIX / "imf_weo")
    CONNECTORS["rbnz"]().ingest(store, hist)
    import time
    time.sleep(1.1)
    m, _ = CONNECTORS["rbnz"]().ingest(store, FIX / "rbnz")  # the current file, as a refresh brings it
    assert sorted(f["name"] for f in m.files) == ["hb2-daily-close-1985-2017.xlsx", "hb2-monthly-close.xlsx"]
    con = duckdb.connect(str(build(home).path), read_only=True)
    ocr = dict(con.execute("SELECT year(period_start), value FROM series WHERE entity_id = 'NZL' AND indicator_id = 'rbnz_ocr'").fetchall())
    assert ocr[2017] == pytest.approx(1.75) and ocr[2018] == pytest.approx(1.75)  # 2018 from the current file, not the 9.0
    assert min(ocr) == 2017 and max(ocr) == 2026
    assert con.execute("SELECT count(*) FROM indicators WHERE indicator_id = 'rbnz_inm_ms61_nzzc'").fetchone()[0] == 1


def test_mbie_energy_balance_and_flow(tmp_path):
    from worldmodel_contract.energy_flow import flow
    from worldmodel_data.connectors.nz import read_energy_balance

    rows = read_energy_balance(FIX / "mbie_energy" / "energy-balance-tables.xlsx")
    f = flow([(e, fu, v) for e, fu, y, v in rows if y == 2025])
    # MBIE's own balance table for 2025: primary supply 827.05 PJ, transport 208.99 PJ.
    assert f["totals"]["primary_supply"] == pytest.approx(827.053, abs=0.01)
    assert f["totals"]["use_by_sector"]["Transport"] == pytest.approx(208.994, abs=0.01)
    links = {(x["source"], x["target"]): x["value"] for x in f["links"]}
    assert links[("Geothermal", "Electricity generation")] > 200 and links[("Oil", "Transport")] > 200
    assert links[("Electricity generation", "Electricity")] == pytest.approx(f["totals"]["electricity_generated"])
    assert {n["name"] for n in f["nodes"] if n["kind"] == "loss"} == {"Conversion losses", "Losses and own use"}

    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["imf_weo"]().ingest(store, FIX / "imf_weo")
    CONNECTORS["mbie_energy"]().ingest(store, FIX / "mbie_energy")
    path = build(home).path
    con = duckdb.connect(str(path), read_only=True)
    v = dict(con.execute("SELECT indicator_id, value FROM series WHERE entity_id = 'NZL' AND breakdown = '' "
                         "AND period_start = '2025-01-01' AND source_id = 'mbie_energy'").fetchall())
    assert v["nz_energy_primary_supply"] == pytest.approx(827.05, abs=0.01)
    assert v["nz_energy_consumer"] == pytest.approx(523.15, abs=0.01)
    assert 40 < v["nz_energy_renewable_share_primary"] < 60
    con.close()

    from fastapi.testclient import TestClient
    from worldmodel_api import main
    from worldmodel_api.warehouse import Warehouse

    main.warehouse = Warehouse(str(path))
    got = TestClient(main.app).get("/api/v1/energy-flow", params={"entity": "NZL", "year": 2030}).json()
    assert got["years"] == [2024, 2025] and got["year"] == 2025 and got["totals"]["primary_supply"] == pytest.approx(827.053, abs=0.01)
    assert TestClient(main.app).get("/api/v1/energy-flow", params={"entity": "AUS"}).json()["years"] == []
