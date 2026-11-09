from pathlib import Path

import duckdb

from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.iea_data import entity
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_names():
    assert entity("SaudiArabia") == "SAU" and entity("Republic of Türkiye") == "TUR"
    assert entity("Hong Kong, China") == "HKG" and entity("World") == "world" and entity("IEA Europe") is None


def test_iea_files(tmp_path):
    store = VintageStore(Paths(tmp_path / "var"))
    m, _ = CONNECTORS["iea_data"]().ingest(store, FIXTURES / "iea_data")
    d = store.vintage_dir("iea_data", m.vintage)
    obs = {(r[0], r[1], str(r[2]), r[3], r[4]): (r[5], r[6]) for r in duckdb.sql(
        f"SELECT source_code, indicator_id, period_start, freq, breakdown, value, status "
        f"FROM '{d / 'observations.parquet'}'").fetchall()}
    # monthly electricity, total and by fuel, and the renewable share worked out
    assert obs[("NZL", "elec_month_gwh", "2026-07-01", "M", "")][0] == 4000
    assert obs[("NZL", "elec_month_gwh", "2026-07-01", "M", "fuel=hydro")][0] == 2400
    assert obs[("NZL", "elec_month_renew_share", "2026-07-01", "M", "")][0] == 85
    assert not any(k[0] not in ("NZL", "AUS", "IDN", "world") for k in obs)  # IEA Europe left out
    # coal: four quarters summed to Mt; 2025 has only two lignite quarters, so no total that year
    assert obs[("AUS", "coal_production_mt", "2024-01-01", "A", "")][0] == 440
    assert obs[("AUS", "coal_production_mt", "2024-01-01", "A", "coal=lignite")][0] == 40
    assert ("AUS", "coal_production_mt", "2025-01-01", "A", "") not in obs
    # subsidies: the world total, a product, and the 2024 indicators as percentages
    assert obs[("world", "fossil_subsidies_usd", "2024-01-01", "A", "")][0] == 598459.5
    assert obs[("world", "fossil_subsidies_usd", "2024-01-01", "A", "fuel=oil")][0] == 280000
    assert obs[("IDN", "fossil_subsidy_rate", "2024-01-01", "A", "")][0] == 25
    assert round(obs[("IDN", "fossil_subsidy_gdp", "2024-01-01", "A", "")][0], 2) == 1.31
    # World Energy Outlook: history, Stated Policies as the projection, other scenarios as breakdowns
    assert obs[("world", "weo_total_total_energy_supply", "2024-01-01", "A", "")] == (654.2, "E")
    assert obs[("world", "weo_total_total_energy_supply", "2035-01-01", "A", "")] == (700, "P")
    assert obs[("world", "weo_total_total_energy_supply", "2035-01-01", "A", "scenario=nze")] == (560, "P")
