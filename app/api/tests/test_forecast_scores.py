"""Forecast scores: back-tests that only use what was known at each point, baselines, and the running record."""

import math
import random
from datetime import date

import duckdb
import pytest
from worldmodel_api import forecast_scores as S
from worldmodel_api import outlook


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    outlook._fit_cache.clear()


def season(peak: int, height: float) -> list[float]:
    return [2 + height * math.exp(-(min(abs(w - peak), 52 - abs(w - peak)) ** 2) / 32) for w in range(1, 53)]


def flu(peak: int, seed: int, end: date) -> list[tuple[date, float]]:
    rnd = random.Random(seed)
    out = []
    for y in range(2010, end.year + 1):
        s = season(peak, 10 * rnd.uniform(0.6, 1.6))
        for w in range(1, 53):
            d = date.fromisocalendar(y, w, 1)
            if d <= end:
                out.append((d, s[w - 1] * rnd.uniform(0.9, 1.1)))
    return out


def test_summary_skill_and_cover():
    pairs = [{"f": 10, "lo": 8, "hi": 12, "a": 11, "scale": 1.0, "base": {"naive": 13}},
             {"f": 10, "lo": 8, "hi": 12, "a": 14, "scale": 1.0, "base": {"naive": 12}}]
    s = S.summarise(pairs, ("naive",))
    assert s["n"] == 2 and s["mae"] == 2.5 and s["cover"] == 0.5 and s["bias"] == -2.5
    assert s["base"]["naive"]["mae"] == 2 and s["best_base"] == "naive" and s["skill"] == pytest.approx(1 - 2.5 / 2)
    o = S.summarise_odds([{"p": 0.8, "a": 1, "base": 0.2}, {"p": 0.1, "a": 0, "base": 0.2}])
    assert o["brier"] == pytest.approx((0.04 + 0.01) / 2) and o["skill"] > 0 and o["events"] == 1


def test_disease_backtest_never_sees_the_future():
    end = date(2026, 11, 2)
    nz, uk = flu(27, 1, end), flu(3, 2, end)
    everyone = {"NZL": nz, "GBR": uk}
    since = date(2025, 11, 1)
    got = S.disease_pairs(nz, everyone, since, "NZL", {})
    assert got and {p["h"] for p in got} == {1, 2, 4, 8}
    assert all(p["o"] >= since.isoformat() and p["t"] > p["o"] for p in got)
    # change everything after one origin: forecasts made at or before it stay the same
    cut = date(2026, 6, 1)
    later = [(d, v * (5 if d > cut else 1)) for d, v in nz]
    again = S.disease_pairs(later, {"NZL": later, "GBR": uk}, since, "NZL", {})
    before = {(p["o"], p["h"]): p["f"] for p in got if p["o"] <= cut.isoformat()}
    assert before and all(p["f"] == pytest.approx(before[(p["o"], p["h"])]) for p in again if (p["o"], p["h"]) in before)
    t = S.table(got, S.HORIZONS["disease"], ("last", "usual"), {"NZL": "New Zealand"})
    one = next(r for r in t["pooled"] if r["h"] == 1 and r["group"] == "all")
    assert one["n"] > 20 and 0 <= one["cover"] <= 1 and set(one["base"]) == {"last", "usual"}
    assert t["countries"][0]["name"] == "New Zealand" and any(r["group"] == "key" for r in t["pooled"])


def test_stat_backtest_uses_only_earlier_years():
    rnd = random.Random(3)
    series = [(y, 2 + rnd.gauss(0, 1)) for y in range(1990, 2025)]
    meta = {"unit": "%", "bound_min": None, "bound_max": None}
    got = S.stat_pairs(series, meta, "NZL")
    assert {p["h"] for p in got} == {1, 2, 3, 5} and all(int(p["t"]) - int(p["o"]) == p["h"] for p in got)
    assert all(p["base"]["naive"] == dict(series)[int(p["o"])] for p in got)
    changed = series[:-1] + [(2024, 500.0)]
    again = {(p["o"], p["h"]): p["f"] for p in S.stat_pairs(changed, meta, "NZL")}
    assert all(again[(p["o"], p["h"])] == pytest.approx(p["f"]) for p in got if (p["o"], p["h"]) in again)
    s = S.summarise([p for p in got if p["h"] == 1], ("naive",))
    assert s["n"] == 10 and s["cover"] is not None


def test_nowcast_pairs_range_from_earlier_misses_only():
    track = [{"quarter": f"20{10 + i // 4} Q{i % 4 + 1}", "estimate": 0.5, "actual": 0.5 + (0.2 if i % 2 else -0.2), "before": 0.4}
             for i in range(10)]
    got = S.nowcast_pairs(track, "NZL")
    assert got[0]["lo"] is None and got[6]["lo"] == pytest.approx(0.5 - 1.2816 * 0.2)
    assert got[0]["base"] == {"prev": 0.4}


def made_up_recessions():
    from tests.test_outlook_api import made_up, q_for
    return q_for(made_up())


def test_recession_backtest_refits_on_what_was_known():
    try:
        q = made_up_recessions()
    except ImportError:
        pytest.skip("outlook test data not importable")
    F = outlook.fit(q, "v1")
    pairs = S.recession_pairs(F, years=12, step=6)
    assert pairs and all(0 <= p["p"] <= 1 and p["a"] in (0, 1) and 0 < p["base"] < 1 for p in pairs)
    s = S.summarise_odds(pairs)
    assert s["events"] >= 1 and s["skill"] is not None and s["skill"] > 0  # the made-up dips do warn of recessions


@pytest.fixture()
def q():
    con = duckdb.connect()
    con.execute("CREATE TABLE series (entity_id VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, breakdown VARCHAR, "
                "variant VARCHAR, source_id VARCHAR, value DOUBLE, status VARCHAR)")
    con.execute("CREATE TABLE indicator_sources (indicator_id VARCHAR, source_id VARCHAR, rank INTEGER)")
    con.execute("CREATE TABLE entities (entity_id VARCHAR, name VARCHAR, short_name VARCHAR, type VARCHAR)")
    con.execute("CREATE TABLE indicators (indicator_id VARCHAR, name VARCHAR, unit VARCHAR, decimals INTEGER, bound_min DOUBLE, bound_max DOUBLE)")
    con.execute("INSERT INTO indicators VALUES ('gdp_growth', 'GDP growth', '%', 1, -100, 100)")
    con.execute("INSERT INTO indicator_sources VALUES ('gdp_growth', 'imf_weo', 1), ('flu_pct_positive', 'who_flunet', 1)")
    con.execute("INSERT INTO entities VALUES ('NZL', 'New Zealand', 'New Zealand', 'country'), ('GBR', 'United Kingdom', 'UK', 'country')")
    rnd = random.Random(5)
    rows = [(e, "gdp_growth", date(y, 1, 1), "A", "", "central", "imf_weo", 2 + rnd.gauss(0, 1), "E")
            for e in ("NZL", "GBR") for y in range(1990, 2025)]
    end = date(2026, 11, 2)
    for e, peak, seed in (("NZL", 27, 1), ("GBR", 3, 2)):
        rows += [(e, "flu_pct_positive", d, "D", "", "central", "who_flunet", v, "E") for d, v in flu(peak, seed, end)]
    con.executemany("INSERT INTO series VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def run(sql, params=None):
        rel = con.execute(sql, params or [])
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, r)) for r in rel.fetchall()]
    run.con = con
    return run


def test_stat_backtest_table(q):
    got = S.stat_backtest(q, "gdp_growth", {"NZL": "New Zealand", "GBR": "UK"})
    assert got["label"] == "GDP growth" and not got["rel_is_share"]
    one = next(r for r in got["pooled"] if r["h"] == 1 and r["group"] == "all")
    assert one["n"] == 20 and "cover95" in one and one["cover95"] >= (one["cover"] or 0)
    assert [r["e"] for r in got["countries"][:1]] == ["NZL"]


def test_running_record_keeps_the_first_forecast_and_scores_it_later(q):
    rows = S.stat_now(q, "gdp_growth")
    assert rows and {r["o"] for r in rows} == {"2024"}
    assert S.save(rows, "b1") == len(rows) and S.save(rows, "b2") == 0  # same figures: nothing new
    flu_rows = S.disease_now(q, "flu_pct_positive", date(2026, 11, 10))
    assert flu_rows and S.save(flu_rows, "b1") == len(flu_rows)
    out = S.score_kept(q, "v", S.kept(), {})
    assert out["saved"] == len(rows) + len(flu_rows)
    st = out["families"]["stat"]["gdp_growth"]
    assert st["n"] == 0 and st["waiting"] == len(rows)  # no 2025 figure yet
    q.con.execute("INSERT INTO series VALUES ('NZL', 'gdp_growth', '2025-01-01', 'A', '', 'central', 'imf_weo', 1.5, 'E')")
    st = S.score_kept(q, "v", S.kept(), {})["families"]["stat"]["gdp_growth"]
    assert st["n"] == 1 and st["waiting"] == len(rows) - 1 and st["pooled"][0]["h"] == 1
    d = S.score_kept(q, "v", S.kept(), {})["families"]["disease"]["flu_pct_positive"]
    assert d["n"] == 0 and d["waiting"] == len(flu_rows)


def test_worker_queues_asks_first_and_keeps_results(q, monkeypatch):
    done = []
    sc = S.Scores()
    sc.configure(q, lambda: "b1", lambda: "v", lambda: {"forecast_backtest_years": 1, "forecast_scores_keep": False})
    monkeypatch.setattr(sc, "work", lambda part: done.append(part) or {"part": part})
    first = sc.ask("stat:gdp_growth")
    assert first["status"] in ("working", "ready")
    sc.thread.join(10)
    assert done[0] == "stat:gdp_growth" and set(S.PARTS_DEFAULT) <= set(done)
    assert sc.ask("stat:gdp_growth")["status"] == "ready"
    again = S.Scores()
    again.configure(q, lambda: "b1", lambda: "v", lambda: {})
    assert again.ask("nowcast")["status"] == "ready"  # read back from disk, not worked out again
