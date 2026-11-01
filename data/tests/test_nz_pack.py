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
