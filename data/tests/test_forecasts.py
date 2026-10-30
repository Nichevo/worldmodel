"""Forecast inputs: the WPP projection ranges, the IMF historical forecasts file and
the what-if checks in the build report."""

import csv
import gzip
import shutil
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from worldmodel_contract.queries import forecast_pairs_sql
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SCALE = {"Low": 0.1, "High": 1.03, "Lower 80 PI": 0.98, "Upper 80 PI": 1.02, "Lower 95 PI": 0.96,
         "Upper 95 PI": 1.04, "Median PI": 1.0, "Constant fertility": 1.1}


def wpp_with_variants(dest: Path) -> Path:
    """The WPP fixture plus an other-variants file made from its projection rows."""
    dest.mkdir()
    for f in (FIXTURES / "un_wpp").iterdir():
        shutil.copy2(f, dest / f.name)
    with gzip.open(FIXTURES / "un_wpp" / "WPP2024_Demographic_Indicators_Medium.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], rows[1:]
    t, v = header.index("Time"), header.index("Variant")
    pops = [header.index(c) for c in ("TPopulation1July", "TFR")]
    with gzip.open(dest / "WPP2024_Demographic_Indicators_OtherVariants.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for label, k in SCALE.items():
            for r in body:
                if int(r[t]) <= 2023:
                    continue
                out = list(r)
                out[v] = label
                for i in pops:
                    out[i] = f"{float(r[i]) * k:.4f}" if r[i] else ""
                w.writerow(out)
    return dest


def weo_history(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "ngdp_rpch"
    ws.append(["country", "WEO_Country_Code", "ISOAlpha_3Code", "year", "S2013ngdp_rpch", "F2013ngdp_rpch", "S2014ngdp_rpch"])
    for iso, code in (("NZL", 196), ("AUS", 193)):
        for year in range(2010, 2018):
            ws.append([iso, code, iso, year, 2.0 + (year - 2010) * 0.1, 2.5, "n/a" if year == 2017 else 3.0])
    ws2 = wb.create_sheet("pcpi_pch")
    ws2.append(["note: inflation"])
    ws2.append(["Country", "ISO", "Year", "S2013", "F2013"])
    ws2.append(["New Zealand", "NZL", 2013, 1.5, 1.2])
    wb.save(path)
    return path


@pytest.fixture
def built(tmp_path):
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    CONNECTORS["un_wpp"]().ingest(store, wpp_with_variants(tmp_path / "wpp"))
    CONNECTORS["imf_weo"]().ingest(store, FIXTURES / "imf_weo")
    manifest, _ = CONNECTORS["imf_weo_history"]().ingest(store, weo_history(tmp_path / "WEOhistorical.xlsx"))
    result = build(home)
    return home, result, manifest


def test_projection_ranges_are_variants_and_not_summed(built):
    _, result, _ = built
    con = duckdb.connect(str(result.path), read_only=True)
    got = dict(con.execute("""SELECT variant, value FROM series WHERE entity_id = 'NZL' AND indicator_id = 'pop_total'
        AND period_start = DATE '2024-01-01'""").fetchall())
    assert set(got) == {"central", "low", "high", "lower80", "upper80", "lower95", "upper95"}  # Median PI etc. left out
    assert got["upper95"] == pytest.approx(got["central"] * 1.04, rel=1e-3)
    # A variant may pass the central path's bounds (the fixture's low variant has fertility
    # far under the 0.3 floor) without failing the build.
    low_tfr = con.execute("""SELECT value FROM series WHERE entity_id = 'NZL' AND indicator_id = 'tfr' AND variant = 'low'
        AND period_start = DATE '2024-01-01'""").fetchone()[0]
    assert low_tfr < 0.3
    # No estimates years in the ranges, and groups get low/high summed but no summed interval bounds.
    assert not con.execute("SELECT count(*) FROM series WHERE variant <> 'central' AND status = 'E'").fetchone()[0]
    eu = {r[0] for r in con.execute("SELECT DISTINCT variant FROM series WHERE entity_id = 'eu' AND indicator_id = 'pop_total'").fetchall()}
    assert {"low", "high"} <= eu and not eu & {"lower80", "upper80", "lower95", "upper95"}


def test_history_file_gives_one_release_per_breakdown(built):
    _, result, manifest = built
    con = duckdb.connect(str(result.path), read_only=True)
    found = dict(con.execute("""SELECT breakdown, count(*) FROM series WHERE source_id = 'imf_weo_history'
        AND indicator_id = 'gdp_growth' GROUP BY 1""").fetchall())
    assert found == {"release=2013-04": 16, "release=2013-10": 16, "release=2014-04": 14}
    infl = con.execute("""SELECT breakdown, value FROM series WHERE source_id = 'imf_weo_history'
        AND indicator_id = 'inflation' ORDER BY 1""").fetchall()
    assert infl == [("release=2013-04", 1.5), ("release=2013-10", 1.2)]
    # Default views never see them.
    assert not con.execute("""SELECT count(*) FROM series WHERE source_id = 'imf_weo_history' AND breakdown = ''""").fetchone()[0]

    sql, params = forecast_pairs_sql("gdp_growth", ["NZL"])
    pairs = con.execute(sql, params).fetchall()
    releases = {r[1] for r in pairs}
    assert {"2013-04", "2013-10", "2014-04", "2015-04"} <= releases  # the file's, and the current vintage's own
    p = next(r for r in pairs if r[1] == "2013-04" and r[2] == 2014)
    assert p[3] == 1 and p[4] == pytest.approx(2.4) and p[5] is not None  # horizon, forecast, outcome


def test_whatif_checks_in_report(built):
    _, result, _ = built
    con = duckdb.connect(str(result.path), read_only=True)
    checks = dict(con.execute("SELECT check_id, status FROM build_checks WHERE check_id LIKE 'whatif:%'").fetchall())
    assert set(checks) == {"whatif:projection", "whatif:backtest"}
    assert "fail" not in checks.values()
