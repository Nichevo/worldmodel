"""Forecast accuracy: forecasts recorded, airport reports and the analysis turned into what happened,
models scored and ranked, and the page, card line and map layer built from them (no network: a
fake fetch stands in for Open-Meteo and aviationweather.gov)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from worldmodel_api import forecast_skill as fs
from worldmodel_api import main
from worldmodel_contract.forecast_skill import BY_ID, CITIES, MODELS

T0 = int(datetime(2026, 11, 20, 0, tzinfo=timezone.utc).timestamp())


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    fs._cache.clear()
    fs._state.update(running=False, note="", error="")
    yield tmp_path


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _truth(t: int) -> float:
    return 15 + (t // 3600) % 5  # what "happened": a temperature that changes hour by hour


def fake_get(now: int, offsets: dict[str, float] | None = None, wet_hours: set[int] = frozenset()):
    """Open-Meteo and METAR answers: model m is off by offsets[m] °C; the truth is _truth()."""
    offsets = offsets or {m: i * 0.5 for i, m in enumerate(MODELS)}

    def get(url, params):
        if url == fs.METAR:
            out = []
            for icao in params["ids"].split(","):
                for h in range(params["hours"]):
                    t = now - now % 3600 - h * 3600
                    out.append({"icaoId": icao, "obsTime": t, "temp": _truth(t), "wspd": 10, "lat": -37.0, "lon": 174.8, "name": icao,
                                "wxString": "-RA" if t in wet_hours else None})
            return out
        n = len(params["latitude"].split(","))
        if "past_days" in params:
            start = now - now % 86400 - 2 * 86400
            times = [start + h * 3600 for h in range(72)]
            one = {"hourly": {"time": [_iso(t) for t in times], "temperature_2m": [_truth(t) for t in times],
                              "precipitation": [0.0] * 72, "wind_speed_10m": [18.52] * 72}}
            return [one] * n if n > 1 else one
        start = now - now % 86400
        times = [start + h * 3600 for h in range(72)]
        hourly = {"time": [_iso(t) for t in times]}
        for m in MODELS:
            hourly[f"temperature_2m_{m}"] = [_truth(t) + offsets[m] for t in times]
            hourly[f"precipitation_{m}"] = [0.0] * 72
            hourly[f"wind_speed_10m_{m}"] = [18.52 + offsets[m]] * 72
        one = {"hourly": hourly}
        return [one] * n if n > 1 else one
    return get


def test_metar_hours_takes_the_nearest_report_and_wet_weather():
    h = T0
    got = fs.metar_hours([
        {"obsTime": h - 1800, "temp": 10, "wspd": 5, "wxString": "-RA"},       # half past: wet in the hour ending h
        {"obsTime": h + 60, "temp": 12, "wspd": 10, "wxString": "VCSH"},       # nearest to h; showers nearby are not here
        {"obsTime": h + 3600 - 120, "temp": 13, "wspd": 0, "wxString": "BR"},  # mist is not wet
    ])
    assert got[h]["temp"] == 12 and round(got[h]["wind"], 2) == 18.52 and got[h]["wet"] == 1
    assert got[h + 3600]["temp"] == 13 and got[h + 3600]["wet"] == 0
    assert fs.metar_hours([{"obsTime": h, "temp": 9, "wspd": 3, "wxString": "TSRA"}])[h]["wet"] == 1


def test_a_round_records_and_the_closest_model_wins():
    got = fs.record(T0, fake_get(T0))
    assert got["forecasts"] > 0 and got["airport"] > 0 and got["analysis"] > 0 and not got["note"]
    # Later rounds bring the airport and analysis hours the first round's forecasts were for.
    for k in range(1, 9):
        fs.record(T0 + k * 6 * 3600, fake_get(T0 + k * 6 * 3600))
    t = fs.table("day1", now=T0 + 48 * 3600)
    assert t["rounds"] == 9 and t["days"] == 2.0
    akl = next(c for c in t["cities"] if c["id"] == "auckland")
    assert akl["best"] == "best_match"  # off by 0 °C
    assert [m["model"] for m in akl["models"]][:2] == ["best_match", "ecmwf_ifs025"]
    assert akl["models"][0]["temp"] == 0 and akl["models"][0]["airport_share"] == 1.0
    # The airport's own place is learnt from its reports and used from then on.
    assert (akl["lat"], akl["lon"]) == (-37.0, 174.8)
    kyiv = next(c for c in t["cities"] if c["id"] == "kyiv")
    assert kyiv["best"] == "best_match" and kyiv["models"][0]["airport_share"] == 0  # analysis only
    oceania = next(r for r in t["regions"] if r["region"] == "Oceania")
    assert oceania["wins"][0] == {"model": "best_match", "name": MODELS["best_match"], "cities": oceania["cities"]}


def test_one_part_failing_keeps_the_others():
    good = fake_get(T0)

    def get(url, params):
        if url == fs.METAR:
            raise OSError("aviationweather.gov is down")
        return good(url, params)
    got = fs.record(T0, get)
    assert got["airport"] == 0 and got["forecasts"] > 0 and "airport: OSError" in got["note"]


def test_balanced_rain_score_does_not_reward_always_dry():
    rows = []
    for i in range(40):  # 4 wet hours in 40
        wet = int(i < 4)
        rows.append(("x", "dry", 15, 0.0, 10, 15, 10, wet, "airport"))           # always says dry
        rows.append(("x", "sees", 15, 1.0 if wet else 0.0, 10, 15, 10, wet, "airport"))  # sees the rain
    s = fs.score_rows(rows)["x"]
    assert s["sees"]["rain"] < s["dry"]["rain"]
    assert s["dry"]["wet_hours"] == 4
    ranked = fs.rank(s)
    assert ranked[0]["model"] == "sees"


def test_too_few_checks_are_not_ranked():
    s = fs.score_rows([("x", "m", 15, 0.0, 10, 15, 10, 0, "analysis")] * (fs.MIN_PAIRS - 1))
    assert fs.rank(s["x"])[0]["mean_rank"] is None


def test_card_line_layer_and_routes():
    for k in range(9):
        fs.record(T0 + k * 6 * 3600, fake_get(T0 + k * 6 * 3600))
    fs._cache.clear()
    now = T0 + 48 * 3600
    t = fs.table("day1", now=now)  # cached for the calls below, which use the time now
    fs._cache[("day1", int(__import__("time").time()) // 600)] = t
    near = fs.near(-36.9, 174.8)
    assert near["city"] == "Auckland" and near["best"] == "best_match" and near["order"][0] == "best_match"
    assert fs.near(0, -150)["city"] is None  # far from every scored city
    lay = fs.layer()
    assert len(lay["features"]) == len(CITIES)
    p = next(f["properties"] for f in lay["features"] if f["properties"]["name"] == "Wellington")
    assert p["best"] == "best_match" and p["airport"] == BY_ID["wellington"].icao and p["runner_up"] == "ECMWF"
    with TestClient(main.app) as client:
        assert client.get("/api/v1/weather/skill").json()["cities"][0]["id"] == "auckland"
        assert client.get("/api/v1/weather/skill/near", params={"lat": -36.9, "lon": 174.8}).json()["best"] == "best_match"
        assert client.get("/api/v1/weather/skill/status").json()["rounds"] == 9
        assert client.get("/api/v1/layers/forecast_skill").json()["type"] == "FeatureCollection"


def test_empty_before_the_first_round():
    assert fs.table()["cities"] == [] and fs.near(-36.9, 174.8) == {"city": None, "days": 0}
    lay = fs.layer()
    assert lay["features"] == [] and "not run yet" in lay["note"]


def test_each_forecast_is_checked_once_and_only_sums_are_kept():
    for k in range(9):
        fs.record(T0 + k * 6 * 3600, fake_get(T0 + k * 6 * 3600))
    db = fs.connect()
    try:
        until = db.execute("SELECT v FROM meta WHERE k = 'checked_until'").fetchone()[0]
        assert until == T0 + 48 * 3600 - fs.SETTLE
        assert db.execute("SELECT MIN(valid) FROM forecasts").fetchone()[0] >= until  # checked forecasts are gone
        before = db.execute("SELECT SUM(n) FROM sums").fetchone()[0]
        assert fs.check(db, T0 + 48 * 3600) == 0  # nothing new settled: nothing counted twice
        assert db.execute("SELECT SUM(n) FROM sums").fetchone()[0] == before
    finally:
        db.close()
