"""Climate sources from small sample files: emissions (OWID CO2), climate charts, gases in
the air, world temperature, El Niño and other drivers with their episodes as events, storm
tracks, GDACS alerts, projections, net zero targets, carbon prices and New Zealand's series."""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.climate import enso_episodes
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("owid_co2", "owid_climate", "noaa_gml", "nasa_gistemp", "noaa_enso", "ibtracs", "gdacs", "cckp",
           "net_zero_tracker", "carbon_pricing", "niwa_7station", "mfe_ghg")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("climate") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi") + SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, period, variant="central", freq=None):
    sql = "SELECT value, status FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ? AND breakdown = '' AND variant = ?"
    params = [entity, indicator, period, variant]
    if freq:
        sql += " AND freq = ?"
        params.append(freq)
    r = con.execute(sql, params).fetchone()
    return r[0] if r else None


def test_owid_emissions(con):
    assert value(con, "NZL", "co2_gcp", "2022-01-01") == pytest.approx(31.966)
    assert value(con, "NZL", "methane_emissions", "2022-01-01") is not None
    assert value(con, "world", "co2_gcp", "2022-01-01") > 30000
    assert value(con, "CHN", "co2_consumption", "2021-01-01") is not None
    name = con.execute("SELECT name, domain FROM indicators WHERE indicator_id = 'co2_gcp'").fetchone()
    assert "GCP" in name[0] and name[1] == "climate"


def test_owid_climate_charts(con):
    assert value(con, "NZL", "temp_anomaly", "2022-01-01") == pytest.approx(0.95)
    assert value(con, "world", "temp_anomaly", "2023-01-01") == pytest.approx(0.6)
    assert value(con, "NZL", "ghg_sector_agriculture", "2021-01-01") == 39_500_000
    assert con.execute("SELECT name FROM indicators WHERE indicator_id = 'ghg_sector_energy'").fetchone()[0] == "Greenhouse gases from energy"


def test_gases_and_world_temperature(con):
    assert value(con, "world", "co2_ppm_mlo", "2024-05-01", freq="M") == pytest.approx(426.90)
    assert value(con, "world", "co2_ppm_mlo", "2024-06-01", freq="M") is None  # -99.99 is missing
    assert value(con, "world", "co2_ppm", "2023-01-01") == pytest.approx(419.31)
    assert value(con, "world", "ch4_ppb", "2023-01-01") == pytest.approx(1922.6)
    assert value(con, "world", "temp_anomaly_world", "2024-01-01") == pytest.approx(1.28)
    assert value(con, "world", "temp_anomaly_world", "2025-01-01") is None
    assert value(con, "world", "temp_anomaly_world_monthly", "2025-02-01", freq="M") == pytest.approx(1.26)


def test_enso_index_and_episodes(con):
    assert value(con, "world", "enso_oni", "2015-12-01", freq="M") == pytest.approx(2.6)
    assert value(con, "world", "iod_dmi", "2019-10-01", freq="M") == pytest.approx(1.5)
    assert value(con, "world", "iod_dmi", "2024-02-01", freq="M") is None
    assert value(con, "world", "sam_index", "2024-02-01", freq="M") == pytest.approx(-0.3)
    ev = con.execute("SELECT subkind, title, start_date FROM events WHERE kind = 'enso' ORDER BY start_date").fetchall()
    assert ev[0][0] == "el_nino" and "very strong" in ev[0][1] and ev[0][2] == date(2015, 1, 1)
    assert ev[1][0] == "la_nina" and "weak" in ev[1][1]


def test_enso_episodes_need_five_seasons():
    s = [(date(2000, m, 1), v) for m, v in enumerate([0.6, 0.7, 0.6, 0.5, 0.2, 0.6], 1)]
    assert enso_episodes(s) == []
    s = [(date(2000, m, 1), v) for m, v in enumerate([0.6, 0.7, 1.1, 0.8, 0.5], 1)]
    assert enso_episodes(s)[0]["strength"] == "moderate"


def test_storm_tracks_layer(con):
    lay = con.execute("SELECT feature_count, geojson FROM layers WHERE layer_id = 'storm_tracks'").fetchone()
    assert lay[0] == 1  # the 1985 depression and the 1979 storm (before 1980) are left out
    f = json.loads(lay[1])["features"][0]
    p = f["properties"]
    assert p["name"] == "Gabrielle (2023)" and p["cat"] == 3 and p["land"] == 1 and p["basin"] == "South Pacific"
    lons = [c[0] for c in f["geometry"]["coordinates"]]
    assert len(lons) == 5 and lons[-1] > 180  # six-hourly points, continuous across 180°


def test_gdacs_alerts_as_events(con):
    ev = con.execute("SELECT entity_id, subkind, title, start_date FROM events WHERE source_id = 'gdacs' ORDER BY entity_id").fetchall()
    assert [e[0] for e in ev] == ["AUS", "NZL", "PAK"]  # green alerts left out; each affected country gets one
    nz = ev[1]
    assert nz[1] == "storm" and "Gabrielle" in nz[2].title() and "red alert" in nz[2] and nz[3] == date(2023, 2, 8)


def test_projections(con):
    assert value(con, "NZL", "proj_temp_ssp245", "2050-01-01") == pytest.approx(13.6)
    assert value(con, "NZL", "proj_temp_ssp245", "2050-01-01", "lower80") == pytest.approx(13.1)
    assert value(con, "NZL", "proj_temp_ssp245", "2050-01-01", "upper80") == pytest.approx(14.2)
    assert value(con, "NZL", "proj_rain_ssp585", "2050-01-01") == 1720
    st = con.execute("SELECT DISTINCT status FROM series WHERE indicator_id = 'proj_temp_ssp245'").fetchall()
    assert st == [("P",)]


def test_net_zero_and_carbon_prices(con):
    assert value(con, "NZL", "net_zero_year", "2025-01-01") == 2050
    assert value(con, "NZL", "net_zero_status", "2025-01-01") == 3
    assert value(con, "IND", "net_zero_status", "2025-01-01") == 1
    assert value(con, "CHN", "net_zero_year", "2025-01-01") == 2060
    assert value(con, "NZL", "carbon_price", "2022-01-01") == 49.0
    assert value(con, "NZL", "carbon_price", "2023-01-01") == pytest.approx(40.1)  # the highest scheme, not the tax
    assert value(con, "eu", "carbon_price", "2023-01-01") == 90.0


def test_new_zealand_series(con):
    assert value(con, "NZL", "nz_temp_anomaly_7station", "2022-01-01") == pytest.approx(1.15)
    assert value(con, "NZL", "nz_temp_7station", "1909-01-01") == pytest.approx(11.9)
    assert value(con, "NZL", "nz_ghg_agriculture", "2022-01-01") == pytest.approx(39.2)  # all gases only, kt to Mt
    assert value(con, "NZL", "nz_ghg_forestry", "2022-01-01") == pytest.approx(-21.0)


def test_dated_chart_as_yearly_means(con):
    assert value(con, "world", "sea_level", "2020-01-01") == pytest.approx(82.0)  # the mean of the year's readings
    assert value(con, "world", "sea_level_uhslc", "2021-01-01") == pytest.approx(86.0)


def test_file_missing_from_a_vintage_taken_from_the_last_one(tmp_path):
    """One failed download among several must not wipe a series out (BIS household credit)."""
    import shutil
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    bis = CONNECTORS["bis"]()
    bis.ingest(store, FIXTURES / "bis")
    part = tmp_path / "bis_part"
    shutil.copytree(FIXTURES / "bis", part)
    (part / "tc_households.csv").unlink()
    (part / "spp.csv").write_text((FIXTURES / "bis" / "spp.csv").read_text(encoding="utf-8") + "\n", encoding="utf-8")  # new content
    m, new = bis.ingest(store, part)
    assert new
    con = duckdb.connect()
    sql = bis.stage(con, home.home / m.raw_dir, m.release, m.vintage)
    n = con.execute(f"SELECT count(*) FROM ({sql}) WHERE indicator_id = 'bis_household_credit_gdp'").fetchone()[0]
    assert n > 0


def test_files_as_the_sites_give_them(tmp_path):
    """The Net Zero Tracker's snapshot (group headings above the column names, ISO3 in Country)
    and NIWA's annual and monthly workbooks (notes above; Temp / Anomaly pairs per station)."""
    import duckdb
    import openpyxl

    from worldmodel_data.connectors import CONNECTORS

    def xlsx(path, rows):
        wb = openpyxl.Workbook()
        for r in rows:
            wb.active.append(r)
        wb.save(path)

    nzt = tmp_path / "nzt"
    nzt.mkdir()
    xlsx(nzt / "current_current-snapshot_2026-11-04_08-54-13.xlsx", [
        ["Identification", None, None, "Entity type and location", None, None, None, None, "End target information"],
        ["Last_updated", "ID_Code", "ISIN_ID", "Name", "Country", "Geographic_region", "Entity_type", "Private_company", "End_target",
         "End_target_percentage_reduction", "End_target_baseline_year", "End_target_year", "Status_of_end_target"],
        ["10/03/2026", "COU-0001", None, "Afghanistan", "AFG", "Asia", "Country", None, "Reduction v. BAU", 13.6, None, 2030, "Proposed / in discussion"],
        ["12/05/2026", "COU-0120", None, "New Zealand", "NZL", "Oceania", "Country", None, "Net zero", None, None, 2050, "In law"],
        ["12/05/2026", "CIT-0001", None, "Auckland", "NZL", "Oceania", "City", None, "Net zero", None, None, 2050, "In policy document"],
    ])
    niwa = tmp_path / "niwa"
    niwa.mkdir()
    xlsx(niwa / "NZT7_Adjusted_Annual_TMean2018_Web-updated-jan-2019.xlsx", [
        ['NIWA "7-STATION" TEMPERATURE SERIES: ANNUAL DATA'], ["Notes:"], [None],
        ["Year", "Auckland", None, "Masterton", None, "7-Stn Composite"],
        [None, "Temp", "Anomaly", "Temp", "Anomaly", "Temp", "Anomaly"],
        [2017, 16.13, 0.7, 12.63, 0.06, 13.15, 0.54],
        [2018, 16.12, 0.68, 13.39, 0.82, 13.41, 0.8],
        ["Average", 15.44, None, 12.57, None, 12.61]])
    xlsx(niwa / "NZT7_Adjusted_Monthly_TMean_Anomalies2018-updated-jan-2019.xlsx", [
        ["NIWA MONTHLY MEANS"], ["Notes:"], ["Year", "Jan", "Feb", "Annual"], [2018, 3.15, 0.83, 0.8], [2019, 1.0, 0.5, 0.9], ["CLIM", 17.13, 17.22, 12.61]])
    for sid, folder in (("net_zero_tracker", nzt), ("niwa_7station", niwa)):
        con = duckdb.connect()
        CONNECTORS[sid]().stage(con, folder, "2026", "v1")
        got = {(r[0], r[1], r[2].year): r[3] for r in con.execute("SELECT source_code, indicator_id, period_start, value FROM vals").fetchall()}
        if sid == "net_zero_tracker":
            assert got == {("NZL", "net_zero_year", 2026): 2050, ("NZL", "net_zero_status", 2026): 3}
        else:
            assert got[("NZL", "nz_temp_7station", 2018)] == 13.41 and got[("NZL", "nz_temp_anomaly_7station", 2018)] == 0.8
            assert got[("NZL", "nz_temp_anomaly_7station", 2019)] == 0.9  # a year only the monthly file has
            assert ("NZL", "nz_temp_7station", 2019) not in got
