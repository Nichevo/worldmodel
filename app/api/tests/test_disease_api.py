"""The Disease page's views, on made-up weekly flu: New Zealand peaks mid-year, the UK in winter."""

import math
from datetime import date, timedelta

import duckdb
import pytest

from worldmodel_api import disease


def season(peak: int, height: float, width: float = 4) -> list[float]:
    return [2 + height * math.exp(-(min(abs(w - peak), 52 - abs(w - peak)) ** 2) / (2 * width ** 2)) for w in range(1, 53)]


@pytest.fixture(scope="module")
def q():
    con = duckdb.connect()
    con.execute("CREATE TABLE series (entity_id VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, breakdown VARCHAR, "
                "variant VARCHAR, source_id VARCHAR, value DOUBLE, status VARCHAR)")
    con.execute("CREATE TABLE indicator_sources (indicator_id VARCHAR, source_id VARCHAR, rank INTEGER)")
    con.execute("CREATE TABLE sources (source_id VARCHAR, short_name VARCHAR)")
    con.execute("CREATE TABLE events (entity_id VARCHAR, source_id VARCHAR, subkind VARCHAR, title VARCHAR, start_date DATE, place VARCHAR, "
                "url VARCHAR, detail VARCHAR)")
    con.execute("CREATE TABLE entities (entity_id VARCHAR, name VARCHAR, short_name VARCHAR)")
    con.execute("CREATE TABLE indicators (indicator_id VARCHAR, name VARCHAR)")
    con.execute("INSERT INTO indicators VALUES ('cause_death_rate_cancers', 'Cancers'), ('cause_death_rate_digestive_diseases', 'Digestive diseases')")
    con.execute("INSERT INTO sources VALUES ('who_flunet', 'WHO FluNet'), ('other', 'Other')")
    con.execute("INSERT INTO indicator_sources VALUES ('flu_pct_positive', 'who_flunet', 1), ('flu_pct_positive', 'other', 2)")
    con.execute("INSERT INTO entities VALUES ('NZL', 'New Zealand', 'New Zealand'), ('GBR', 'United Kingdom', 'UK')")
    rows = []
    today = date.today()
    for y in range(2012, today.year + 1):
        nz = season(27, 10 + (y % 5) * 4)
        uk = season(3, 12 + (y % 3) * 5)
        if y in (2020, 2021):
            nz = [1.0] * 52
        if y == 2024:
            nz = season(27, 40)  # the biggest season
        for w in range(1, 53):
            d = date.fromisocalendar(y, w, 1)
            if d > today - timedelta(days=7):
                break
            rows.append(("NZL", "flu_pct_positive", d, "D", "", "central", "who_flunet", nz[w - 1], "E"))
            rows.append(("GBR", "flu_pct_positive", d, "D", "", "central", "who_flunet", uk[w - 1], "E"))
            rows.append(("NZL", "flu_a_h3_positive", d, "D", "", "central", "who_flunet", 8, "E"))
            rows.append(("NZL", "flu_b_positive", d, "D", "", "central", "who_flunet", 2, "E"))
    rows.append(("NZL", "flu_pct_positive", date(2025, 1, 6), "D", "", "central", "other", 99.0, "E"))  # lower-ranked source: ignored
    for y in (2000, 2019, 2024, 2025):
        rows.append(("NZL", "measles_cases", date(y, 1, 1), "A", "", "central", "who_gho_disease", {2019: 2193, 2025: 58}.get(y, 10), "E"))
        rows.append(("NZL", "pop_total", date(y, 1, 1), "A", "", "central", "un_wpp", 5e6, "E"))
    for y, n in ((2019, 2193), (2020, 10), (2021, 0), (2022, 5), (2023, 20), (2024, 30), (2025, 58)):
        rows.append(("NZL", "nz_notifiable_cases", date(y, 1, 1), "A", "disease=measles", "central", "nz_notifiable", n, "E"))
        rows.append(("NZL", "nz_notifiable_cases", date(y, 1, 1), "A", "disease=vtec_stec_infection", "central", "nz_notifiable", 1000, "E"))
    rows.append(("NZL", "nz_notifiable_rate", date(2025, 1, 1), "A", "disease=measles", "central", "nz_notifiable", 1.1, "E"))
    for y, c, g in ((2017, 114.0, 11.0), (2018, 112.4, 10.7)):
        rows.append(("NZL", "cause_death_rate_cancers", date(y, 1, 1), "A", "", "central", "owid_grapher", c, "E"))
        rows.append(("NZL", "cause_death_rate_digestive_diseases", date(y, 1, 1), "A", "", "central", "owid_grapher", g, "E"))
    con.executemany("INSERT INTO series VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("INSERT INTO events VALUES ('NZL', 'who_don', 'measles', 'Measles (WHO outbreak news)', '2025-10-20', 'New Zealand', 'u', 'd')")

    def run(sql, params):
        rel = con.execute(sql, params or [])
        cols = [c[0] for c in rel.description]
        return [dict(zip(cols, r)) for r in rel.fetchall()]
    return run


def test_season_split_follows_the_peak(q):
    nz = disease.weekly(q, "flu_pct_positive", ["NZL"])["NZL"]
    uk = disease.weekly(q, "flu_pct_positive", ["GBR"])["GBR"]
    assert disease.split_week(nz) == 1 and disease.split_week(uk) == 27
    assert dict(nz)[date(2025, 1, 6)] < 50  # the best-ranked source only


def test_seasons_view(q):
    v = disease.seasons_view(q, "NZL", "flu_pct_positive")
    assert v["split_week"] == 1 and v["band_label"] == "2015-2019"
    by = {s["season"]: s for s in v["seasons"]}
    assert by[2024]["peak"] == pytest.approx(42, abs=0.01)
    lo, hi, mean = next(b[1:] for b in v["band"] if b[0] == 27)
    assert lo < mean < hi
    assert v["headline"]["rank"] >= 1 and set(v["sources"]) == {"WHO FluNet", "Other"}
    uk = disease.seasons_view(q, "GBR", "flu_pct_positive")
    assert uk["split_week"] == 27 and uk["seasons"][1]["label"].count("/") == 1
    # a northern season starts in July: week 1 of the 2015/16 season is the Monday of ISO week 27 of 2015
    s = next(s for s in uk["seasons"] if s["season"] == 2015)
    assert s["points"][0][:2] == [1, date.fromisocalendar(2015, 27, 1).isoformat()]


def test_heat_names_the_main_strain(q):
    v = disease.heat_view(q, "NZL", "flu_pct_positive")
    s = next(s for s in v["seasons"] if s["season"] == 2016)
    assert set(s["strain"].values()) == {"A(H3N2) 80%"}


def test_now_and_card(q):
    n = disease.now_view(q, "flu_pct_positive")
    assert {r["entity"] for r in n["rows"]} == {"NZL", "GBR"}
    assert all(r["usual"] for r in n["rows"]) and n["rows"][0]["ratio"] >= n["rows"][1]["ratio"]
    card = disease.card_view(q, "NZL")
    assert [t["measure"]["id"] for t in card["tiles"]] == ["flu_pct_positive"] and len(card["tiles"][0]["spark"]) == 26
    assert card["yearly"][0]["value"] == 58 and card["yearly"][0]["rank"] == 2 and card["yearly"][0]["of"] == 4


def test_usual_skips_covid_years():
    pts = [(date.fromisocalendar(y, w, 1), 10.0 if y not in (2020, 2021) else 99.0) for y in range(2022, 2026) for w in range(1, 53)]
    assert disease.usual_for_week(pts, date.fromisocalendar(2026, 10, 1)) == 10
    assert disease.usual_for_week(pts[:52], date.fromisocalendar(2023, 10, 1)) is None  # one earlier year is not enough


def test_long_view_per_million_and_outbreaks(q):
    v = disease.long_view(q, ["NZL"], "measles_cases")
    pts = {p[0]: p[1] for p in v["series"][0]["points"]}
    assert pts[2019] == pytest.approx(438.6) and v["unit"] == "per million people" and v["pandemics"]
    o = disease.outbreaks(q, ["NZL"], 10)
    assert o[0]["disease"] == "measles" and o[0]["name"] == "New Zealand"


def test_trend_and_level():
    up = [(date(2025, 1, 6) + timedelta(weeks=i), v) for i, v in enumerate([1, 2, 3, 4])]
    assert disease.trend(up) == "rising" and disease.level(2) == "high" and disease.level(None) == "no_usual"


def test_nz_notifiable(q):
    v = disease.notifiable(q)
    assert v["year"] == 2025 and v["diseases"][0]["name"] == "VTEC/STEC infection"
    m = next(d for d in v["diseases"] if d["key"] == "measles")
    assert m["latest"] == 58 and m["latest_rate"] == 1.1 and m["usual"] == pytest.approx((5 + 20 + 30) / 3)  # 2020-2024 without 2020 and 2021


def test_causes_of_death(q):
    v = disease.causes(q, ["NZL", "GBR"])
    assert [c["id"] for c in v["causes"]] == ["cause_death_rate_cancers", "cause_death_rate_digestive_diseases"]
    nz = v["series"][0]["causes"]
    assert nz["cause_death_rate_cancers"][-1] == [2018, 112.4] and v["series"][1]["causes"] == {}


def test_forecast_follows_the_other_hemisphere_and_the_weeks_seen():
    from worldmodel_api import disease_forecast as F
    pts = [(date.fromisocalendar(y, w, 1), v) for y in range(2012, 2026) for w, v in enumerate(season(27, 10), start=1)]
    today = date(2026, 1, 20)
    plain, big = F.forecast(pts, None, today), F.forecast(pts, 3.0, today)
    assert plain["label"] == "2026" and plain["weeks_seen"] == 0  # the 2025 season is over: next one
    assert plain["peak"] == pytest.approx(12, rel=0.01) and big["peak"] == pytest.approx(12 * 2, rel=0.01)  # 1 + 0.5 * (3 - 1)
    assert big["peak_week"] == date.fromisocalendar(2026, 27, 1).isoformat()
    # ten weeks into a season running twice the usual size: the weeks seen pull the forecast up
    seen = pts + [(date.fromisocalendar(2026, w, 1), 2 + 2 * (v - 2)) for w, v in enumerate(season(27, 10), start=1) if w <= 24]
    f = F.forecast(seen, None, date(2026, 6, 20))
    assert f["label"] == "2026" and f["peak"] > 16 and f["points"][0][0] == 25 and f["points"][0][3] <= f["points"][0][2] <= f["points"][0][4]


def test_hemisphere_signal_and_view(q):
    from worldmodel_api import disease_forecast as F
    v = F.forecast_view(q, "NZL", "flu_pct_positive")
    assert v["forecast"] and v["signal"]["hemisphere"] == "northern" and v["forecast"]["split_week"] == 1
    assert v["skill"]["of"] >= 1
    m = F.forecast_map(q, "flu_pct_positive")
    assert {r["entity"] for r in m["rows"]} == {"NZL", "GBR"}
    everyone = {"A": [(date.fromisocalendar(y, w, 1), v * (2 if y == 2025 else 1)) for y in range(2015, 2026)
                      for w, v in enumerate(season(3, 10), start=1)],
                "B": [(date.fromisocalendar(y, w, 1), v) for y in range(2015, 2026) for w, v in enumerate(season(3, 10), start=1)]}
    s = F.hemisphere_signal(everyone, False, date(2025, 12, 1))
    assert s["ratio"] == pytest.approx((12 * 2 / 12 + 1) / 2, rel=0.05) and len(s["countries"]) == 2
