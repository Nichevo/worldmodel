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
