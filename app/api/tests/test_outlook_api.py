"""Recession odds, nowcasts, the release calendar and Wikipedia attention, on made-up figures."""

import json
import math
import random
from datetime import date

import pytest

from worldmodel_api import attention, outlook, releases


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    outlook._fit_cache.clear()
    releases._mem.clear()


def made_up(countries=12, years=30, seed=4):
    """A leading indicator that dips about a year before each recession, policy rates that rise
    before it, and quarterly growth; returned as series rows."""
    rnd = random.Random(seed)
    out = []
    for c in range(countries):
        e = f"C{c:02d}"
        start = outlook.mi(date(1990, 1, 1))
        n = years * 12
        dips = sorted(rnd.sample(range(36, n - 24, 12), 3))
        cli = [100 + rnd.gauss(0, 0.3) for _ in range(n)]
        rate = [5 + rnd.gauss(0, 0.1) for _ in range(n)]
        for d in dips:
            for k in range(-10, 4):
                if 0 <= d + k < n:
                    cli[d + k] -= 2.5 * (1 - abs(k + 3) / 10)
            for k in range(-24, 0):
                rate[d + k] += 1.5 * (k + 24) / 24
        for i in range(n):
            out += [{"i": "oecd_cli", "e": e, "d": outlook.md(start + i), "v": cli[i]},
                    {"i": "bis_policy_rate_m", "e": e, "d": outlook.md(start + i), "v": rate[i]}]
        for i in range(0, n, 3):
            g = 0.6 + rnd.gauss(0, 0.25)
            if any(d + 1 <= i <= d + 6 for d in dips):
                g = -0.8 + rnd.gauss(0, 0.2)
            out.append({"i": "gdp_growth_q", "e": e, "d": outlook.md(start + i), "v": g})
    return out


@pytest.fixture(scope="module")
def data():
    return made_up()


def q_for(data, spread=None, gdpnow=None):
    extra = []
    for m, v in (spread or {}).items():
        extra.append({"i": "us_term_spread", "e": "USA", "d": m, "v": v})
    for m, v in (gdpnow or {}).items():
        extra.append({"i": "us_gdpnow", "e": "USA", "d": m, "v": v})

    def q(sql, params):
        ind, ents = params[0], params[1:]
        return [{"e": r["e"], "d": r["d"], "v": r["v"]} for r in data + extra if r["i"] == ind and (not ents or r["e"] in ents)]
    return q


def test_recessions_need_two_falling_quarters():
    g = {0: 0.5, 3: -0.2, 6: 0.1, 9: -0.3, 12: -0.4, 15: -0.1, 18: 0.4}
    assert outlook.recessions(g) == [(9, 17)]


def test_odds_rise_before_recessions(data):
    got = outlook.recession_odds(q_for(data), ["C00", "C01"], "v1")
    assert set(got["models"]) >= {"full"} and got["models"]["full"]["auc"] > 0.8
    c = got["countries"][0]
    assert c["model"] == "full" and 0 <= c["odds"] <= 100 and c["history"] and c["recessions"]
    assert {d["feature"] for d in c["drivers"]} == {"cli_gap", "cli_chg", "rate_chg", "g_last"}
    hist = dict(c["history"])
    start = outlook.md(outlook.mi(date.fromisoformat(c["recessions"][0][0] + "-01")) - 6).isoformat()[:7]
    assert hist[start] > got["models"]["full"]["base_rate"]  # half a year before, odds are above the usual rate


def test_yield_curve_model_for_the_us(data):
    got = outlook.recession_odds(q_for(data, spread={date(2026, 9, 1): 0.0, date(2026, 10, 1): -1.0}), ["USA"], "v2")
    yc = got["countries"][0]["yield_curve"]
    assert yc["month"] == "2026-10" and yc["spread"] == -1.0
    assert yc["odds"] == round(100 * 0.5 * (1 + math.erf((-0.5333 + 0.6330) / math.sqrt(2))), 1)


def test_nowcast_and_track_record(data):
    n = outlook.nowcast(q_for(data), "C03", "v3")
    assert n["estimate"] is not None and n["low"] < n["estimate"] < n["high"]
    assert n["uses_cli"] and len(n["track"]) >= 15 and n["typical_error"] > 0
    assert outlook.remembered()["C03"][n["quarter"]]["estimate"] == n["estimate"]


def test_gdpnow_for_the_us(data):
    rows = [dict(r, e="USA") for r in data if r["e"] == "C05"]
    n = outlook.nowcast(q_for(rows, gdpnow={date(2026, 10, 1): 2.0}), "USA", "v4")
    assert n["gdpnow"] == {"quarter": "2026 Q4", "annualised": 2.0, "quarterly": 0.5}


ONS = {"releases": [
    {"uri": "/releases/gdpfirstquarterlyestimateukjulytoseptember2026",
     "description": {"title": "GDP first quarterly estimate, UK: July to September 2026", "release_date": "2026-11-14T07:00:00.000Z",
                     "finalised": True, "cancelled": False}},
    {"uri": "/releases/x", "description": {"title": "Deaths registered weekly", "release_date": "2026-11-15T09:30:00.000Z"}},
    {"uri": "/releases/cpi", "description": {"title": "Consumer price inflation, UK: October 2026", "release_date": "2026-11-18T07:00:00.000Z",
                                             "finalised": True}}]}
ABS = """<html><body><div class="cal">
<h3><time>Tuesday 17 November 2026 11:30am AEDT</time></h3><a href="/a">Livestock products</a><p>Reference period: September 2026</p>
<h3><time>Thursday 19 November 2026 11:30am AEDT</time></h3><a href="/b">Labour Force, Australia</a><p>Reference period: October 2026</p>
<h3><time>Wednesday 2 December 2026 11:30am AEDT</time></h3><span>Updated information</span><a href="/c">Australian National Accounts: National Income, Expenditure and Product</a><p>Reference period: September 2026</p>
</div></body></html>"""


def test_live_calendars_parse():
    o = releases.ons_items(ONS)
    assert [r["title"][:3] for r in o] == ["GDP", "Con"] and o[0]["time"] == "07:00" and o[0]["kind"] == "gdp"
    a = releases.abs_items(ABS)
    assert [(r["date"], r["kind"]) for r in a] == [("2026-11-19", "jobs"), ("2026-12-02", "gdp")]
    assert a[0]["time"] == "11:30" and a[1]["period"] == "September 2026"


def test_calendar_merges_and_converts_to_nz_time():
    def fetch(url, params=None):
        return json.dumps(ONS) if "ons" in url else ABS
    nowcasts = {"NZL": {"2026 Q3": {"estimate": 0.4}}}
    got = releases.calendar(True, ["NZL", "AUS", "GBR", "USA"], today=date(2026, 11, 13), nowcasts=nowcasts, fetch=fetch)
    titles = [r["title"] for r in got["items"]]
    assert "Labour Force, Australia" in titles and "GDP (Stats NZ)" in titles and "Jobs report (employment situation)" in titles
    nz_gdp = next(r for r in got["items"] if r["title"] == "GDP (Stats NZ)")
    assert nz_gdp["nz_date"] == "2026-12-17" and nz_gdp["expected"]["value"] == 0.4
    jobs = next(r for r in got["items"] if r["title"].startswith("Jobs") and r["date"] == "2026-12-04")
    assert jobs["nz_time"] == "Sat 05 Dec 02:30"  # 08:30 in New York
    past = next(r for r in got["items"] if r["date"] == "2026-11-06")
    assert past["past"]
    off = releases.calendar(False, ["GBR"], today=date(2026, 11, 13), fetch=fetch)
    assert off["notes"] and all(r["kind"] == "rates" for r in off["items"])


def test_attention_spikes_and_top():
    pts = [[f"2026-08-{d:02d}", 2000] for d in range(1, 31)] + [["2026-08-31", 9000]]
    s = attention.summarise(pts)
    assert s["spikes"] == [{"day": "2026-08-31", "views": 9000, "times": 4.5}] and s["usual"] == 2000
    items = {"items": [{"timestamp": "2026111000", "views": 300}, {"timestamp": "2026111100", "views": 500}]}
    got = attention.country("NZL", "New Zealand", True, fetch=lambda url: json.dumps(items), today=date(2026, 11, 12))
    assert got["points"] == [["2026-11-10", 300], ["2026-11-11", 500]] and got["latest"] == 500
    top = {"items": [{"articles": [{"article": "Main_Page", "views": 9, "rank": 1}, {"article": "New_Zealand", "views": 50000, "rank": 7}]}]}
    t = attention.top({"New Zealand": "NZL"}, True, fetch=lambda url: json.dumps(top), today=date(2026, 11, 12))
    assert t["day"] == "2026-11-11" and t["countries"] == [{"entity": "NZL", "article": "New Zealand", "views": 50000, "rank": 7}]
    assert attention.country("NZL", "New Zealand", False)["note"]
