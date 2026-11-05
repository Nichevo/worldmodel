"""Files saved by hand that the loaders did not read before: World Prison Brief's Highest to
Lowest page, NZ Corrections' quarterly workbook, and ILOSTAT data explorer tables."""

from pathlib import Path

from typer.testing import CliRunner

from worldmodel_data import cli
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.laws import wpb_table
from worldmodel_data.connectors.nz import read_prison_workbook
from worldmodel_data.vintage_store import VintageStore

FIX = Path(__file__).parent / "fixtures"


def _staged(tmp_path, source, folder):
    store = VintageStore(Paths(tmp_path / "var"))
    manifest, _ = CONNECTORS[source]().ingest(store, folder)
    return manifest


def test_prison_brief_page_every_country_whole():
    t = wpb_table((FIX / "wpb_page" / "wpb_2026.htm").read_text(encoding="utf-8"), 2026)
    by = {r[1]: r for r in t[1:]}
    assert len(t) - 1 == 221
    assert by["New Zealand"][3:] == [11256.0, 210.0, 41.0, 7.5, 1.0, 3.0, 93.8]
    assert by["United States of America"][6] == 9.8  # "Estimate c. 9.8%"
    uk = by["United Kingdom"]  # England and Wales, Scotland and Northern Ireland added up
    assert uk[0] == "GB" and uk[3] > 90000 and 100 < uk[4] < 160 and uk[-1] is None
    assert not any(":" in r[1] for r in t[1:])


def test_prison_brief_page_loads(tmp_path):
    manifest = _staged(tmp_path, "world_prison_brief", FIX / "wpb_page")
    assert manifest.row_count > 1000  # about 220 countries, up to seven figures each


def test_prisons_command_fetches_latest_and_missing_years(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "var"))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    page = (FIX / "wpb_page" / "wpb_2026.htm").read_bytes()
    urls = []
    cls = CONNECTORS["world_prison_brief"]

    def fake_get(self, url, dest):
        urls.append(url)
        dest.write_bytes(page)

    monkeypatch.setattr(cls, "get", fake_get)
    out = CliRunner().invoke(cli.app, ["prisons", "--since", "2023", "--pause", "0"])
    assert out.exit_code == 0, out.output
    assert len(urls) == 1 + (__import__("datetime").date.today().year - 2023)
    assert "max%5D=2023-12-31" in urls[-1] and "stored new vintage" in out.output
    urls.clear()
    out = CliRunner().invoke(cli.app, ["prisons", "--since", "2023", "--pause", "0"])  # past years kept: only the latest again
    assert out.exit_code == 0, out.output
    assert len(urls) == 1


def test_corrections_quarterly_workbook(tmp_path):
    q = read_prison_workbook(FIX / "nz_corrections_xlsx" / "Prison_Stats_-_Q1_FY_2026_27.xlsx")
    assert q[(2026, 9)]["total"] == 11327 and q[(2026, 9)]["remand_accused_female"] == 256
    assert q[(2018, 3)]["sentenced"] == 7333
    manifest = _staged(tmp_path, "nz_corrections", FIX / "nz_corrections_xlsx")
    assert manifest.row_count == 90  # nine years (2018-2026), the year's latest quarter, ten figures


def test_ilostat_explorer_tables(tmp_path):
    manifest = _staged(tmp_path, "ilostat_earnings", FIX / "ilostat_explorer")
    assert manifest.row_count > 400  # monthly earnings by sex; the hourly file is skipped
