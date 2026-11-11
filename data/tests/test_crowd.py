"""Crowd forecasts (connectors/crowd.py, crowd_tables.py) on small pages shaped like the sites' own."""

from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from worldmodel_contract import crowd
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.crowd import (POINTS, QUESTIONS, mc_scale, merge, read_gz_json, read_points, ts)
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "polymarket", "metaculus", "manifold", "views")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def test_matching():
    terms = crowd.build_terms([("NZL", "New Zealand", "New Zealand", ""), ("USA", "United States", "United States", ""),
                               ("GEO", "Georgia", "Georgia", ""), ("RUS", "Russia", "Russia", ""), ("UKR", "Ukraine", "Ukraine", "")])
    assert crowd.match_countries("Will Luxon still be NZ prime minister?", terms) == ["NZL"]
    assert crowd.match_countries("Will Russia and Ukraine agree a ceasefire?", terms) == ["RUS", "UKR"]
    assert crowd.match_countries("Who wins the Georgia Senate race?", terms) == ["USA"]  # the US state, not the country
    assert crowd.match_countries("Will Georgian Dream lose power in Georgia?", terms) == ["GEO"]
    assert crowd.match_countries("Will the Fed cut rates?", terms) == ["USA"]
    assert crowd.match_countries("Who will win the race for us?", terms) == []
    assert crowd.match_indicator("What will NZ's CPI inflation be?") == "inflation"
    assert crowd.categorise("Will the Chiefs win?", ["sports"], "polymarket") is None
    assert not crowd.wanted("Will Bitcoin hit 200k?")


def test_scale_and_merge():
    assert mc_scale(0.5, {"scaling": {"range_min": 0, "range_max": 10}}) == 5
    assert mc_scale(0.5, {"scaling": {"range_min": 1, "range_max": 100, "zero_point": 0}}) == pytest.approx(10, rel=1e-6)
    assert ts(1767225600) == "2026-01-01T00:00:00" and ts("2026-01-01T12:00:00Z") == "2026-01-01T12:00:00"
    q = {"key": "manifold:a", "site": "manifold", "title": "Will inflation rise?", "tags": [], "status": "open", "chance": 0.4}
    qs, pts = merge({}, [], [q], [], "2026-11-01T00:00:00", set())
    assert len(pts) == 1
    # A small move a day later is not saved; a big one is; a resolved question keeps its record when gone.
    qs, pts = merge(qs, pts, [{**q, "chance": 0.402}], [], "2026-11-02T00:00:00", set())
    assert len(pts) == 1
    qs, pts = merge(qs, pts, [{**q, "chance": 0.5}], [], "2026-11-03T00:00:00", set())
    assert [p["chance"] for p in pts] == [0.4, 0.5]
    qs, pts = merge(qs, pts, [], [], "2026-11-04T00:00:00", set())
    assert "manifold:a" in qs


def test_questions_and_history(built):
    _, con = built
    qs = {r[0]: r for r in con.execute("SELECT question_key, category, countries, indicator_id, status, resolution, chance, kind "
                                       "FROM crowd_questions").fetchall()}
    assert "polymarket:701" not in qs and "manifold:m3" not in qs  # sport and crypto left out
    assert qs["polymarket:501"][1:4] == ("politics", "NZL", None) and qs["polymarket:501"][6] == pytest.approx(0.62)
    assert qs["polymarket:601"][4:6] == ("resolved", "no") and qs["polymarket:601"][2] == "USA"
    assert qs["metaculus:31001"][2] == "RUS,UKR" and qs["metaculus:31001"][1] == "geopolitics"
    assert qs["metaculus:31002"][3] == "inflation" and qs["metaculus:31002"][7] == "numeric"
    assert qs["metaculus:31002"][6] == pytest.approx(2.5)  # 0.375 of -2..10
    assert qs["manifold:m1"][2:4] == ("AUS", "unemployment")
    hist = con.execute("SELECT origin, count(*) FROM crowd_points WHERE question_key = 'polymarket:501' GROUP BY 1").fetchall()
    assert dict(hist)["site"] == 3
    mine = con.execute("SELECT forecaster, chance, community FROM crowd_mine ORDER BY at_time").fetchall()
    assert [m[1] for m in mine] == [0.3, 0.2] and mine[0][2] == pytest.approx(0.25)
    com = con.execute("SELECT author, forecast, parent_id FROM crowd_comments ORDER BY created").fetchall()
    assert com[0][:2] == ("forecaster1", 0.15) and com[1][2] == "metaculus:9001"
    vf = con.execute("SELECT entity_id, deaths, chance_25 FROM conflict_forecasts WHERE month = DATE '2026-11-01' ORDER BY 1").fetchall()
    assert [v[0] for v in vf] == ["NZL", "SDN", "UKR"] and vf[1][1] == pytest.approx(491.7, rel=0.01)


def test_refresh_carries_history_and_prunes(tmp_path, monkeypatch):
    """A second fetch merges into the first's saved state, and only the newest vintages stay."""
    home = Paths(tmp_path / "var")
    store = VintageStore(home)
    conn = CONNECTORS["manifold"]
    monkeypatch.setattr(conn, "keep_vintages", 2)
    chances = iter([0.31, 0.45, 0.60])

    def fake_download(self, raw_dir, release):
        q = {"key": "manifold:m1", "site": "manifold", "site_id": "m1", "title": "Will Australia's unemployment rate rise?",
             "kind": "binary", "tags": [], "status": "open", "chance": next(chances)}
        self.save_state(raw_dir, [q], [], datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:19], set())
        return "test"

    monkeypatch.setattr(conn, "download", fake_download)
    monkeypatch.setattr(conn, "_home", lambda self: home.home)
    import time
    for _ in range(3):
        conn().ingest(store)
        time.sleep(1.1)
    ms = store.manifests("manifold")
    assert len(ms) == 2
    raw = home.home / ms[-1].raw_dir
    assert read_points(raw / POINTS)[-1]["chance"] == 0.60  # one saved chance a day: the day's last
    assert "manifold:m1" in read_gz_json(raw / QUESTIONS, {})
