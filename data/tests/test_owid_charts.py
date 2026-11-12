from pathlib import Path

import duckdb

from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_chart_ids_and_domains(tmp_path):
    store = VintageStore(Paths(tmp_path / "var"))
    conn = CONNECTORS["owid_grapher"]()
    m, _ = conn.ingest(store, FIXTURES / "owid_grapher")
    d = store.vintage_dir("owid_grapher", m.vintage)
    ids = {r[0] for r in duckdb.sql(f"SELECT DISTINCT indicator_id FROM '{d / 'observations.parquet'}'").fetchall()}
    assert "wid_income_top1" in ids  # one column: the chart's own id
    assert "wvs_religion_important_very_important" in ids  # several: id and column
    assert "owid_death_rate_in_armed_conflicts" in ids  # no id given: as before
    listed = {i["id"]: i for i in conn.listed_indicators}
    assert listed["wid_income_top1"]["domain"] == "inequality"
    assert listed["owid_death_rate_in_armed_conflicts"]["domain"] == "conflict"


def test_democracy_charts(tmp_path):
    store = VintageStore(Paths(tmp_path / "var"))
    conn = CONNECTORS["owid_grapher"]()
    m, _ = conn.ingest(store, FIXTURES / "owid_grapher")
    d = store.vintage_dir("owid_grapher", m.vintage)
    got = dict(duckdb.sql(f"""SELECT indicator_id || ':' || source_code || ':' || year(period_start), value
        FROM '{d / 'observations.parquet'}' WHERE indicator_id IN ('democracy_eiu', 'regime_row')""").fetchall())
    assert got["democracy_eiu:NZL:2024"] == 9.61 and got["regime_row:CHN:2024"] == 0
    listed = {i["id"]: i for i in conn.listed_indicators}
    assert listed["democracy_eiu"]["domain"] == "democracy"
