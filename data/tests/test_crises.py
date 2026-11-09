from pathlib import Path

import duckdb

from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.crises import flag, runs
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_flags_and_runs():
    assert flag("Yes") == 1 and flag(0) == 0 and flag(2) == 1 and flag("n/a") is None and flag(None) is None
    assert runs([2003, 2001, 2002, 2008]) == [(2001, 2003), (2008, 2008)]


def test_crisis_history(tmp_path):
    store = VintageStore(Paths(tmp_path / "var"))
    m, _ = CONNECTORS["crisis_history"]().ingest(store, FIXTURES / "crisis_history")
    assert m.vintage.startswith("2016-09")
    d = store.vintage_dir("crisis_history", m.vintage)
    obs = dict(((r[0], r[1], r[2].year), r[3]) for r in duckdb.sql(
        f"SELECT source_code, indicator_id, period_start, value FROM '{d / 'observations.parquet'}'").fetchall())
    assert obs[("ARG", "crisis_banking", 2001)] == 1
    assert obs[("ARG", "crisis_default_external", 2003)] == 1
    assert obs[("ARG", "crisis_kinds", 2002)] == 4  # banking, foreign default, currency, inflation; systemic not counted twice
    assert obs[("ARG", "rr_inflation", 2002)] == 25.9
    assert ("NZL", "crisis_banking", 1988) not in obs  # n/a is unknown, not 0
    assert not any(k[0] == "XXX" for k in obs)
    ev = duckdb.sql(f"SELECT source_code, subkind, start_date, end_date FROM '{d / 'events.parquet'}' "
                    "ORDER BY subkind").fetchall()
    spells = {(e[0], e[1]): (e[2].year, e[3].year) for e in ev}
    assert spells[("ARG", "banking")] == (2001, 2002)
    assert spells[("ARG", "default_external")] == (2001, 2003)
    assert ("NZL", "banking") not in spells


def test_crisis_series_names_are_unique(tmp_path):
    """Each listed indicator needs its own series name, or the build drops all but the first (rr_inflation)."""
    import json
    store = VintageStore(Paths(tmp_path / "var"))
    m, _ = CONNECTORS["crisis_history"]().ingest(store, FIXTURES / "crisis_history")
    listed = json.loads((store.vintage_dir("crisis_history", m.vintage) / "indicators.json").read_text())
    series = [s["series"] for i in listed for s in i["sources"]]
    assert len(series) == len(set(series)) and "rr_inflation" in {i["id"] for i in listed}
