"""Weather layers: NOAA GFS steps read and drawn as tiles, runs downloaded and swapped, satellite clouds,
and a place's forecast from Open-Meteo or MET Norway. The GRIB file is a real 0.5° GFS step cut to a
box over central New Zealand (168-178°E, 36-46°S)."""

from datetime import datetime, timezone
from pathlib import Path

import io
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from worldmodel_api import main, weather
from worldmodel_api import userdata

pytest.importorskip("eccodes")

SAMPLE = Path(__file__).parent / "fixtures" / "gfs_nz_f003.grib2"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    weather._steps.clear()
    weather._tiles.clear()
    weather._points.clear()
    weather._clouds.clear()
    weather._air.clear()
    weather._models.clear()
    weather._wave_state.update(thread=None, checked=0.0, note="", fetching=None, error="")
    weather._state.update(thread=None, checked=0.0, note="", fetching=None, error="", model="gfs")
    yield tmp_path


def _rgba(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def _nz_tile(z=5, at=(-41.3, 174.8)):
    import math
    n = 2 ** z
    lat = math.radians(at[0])
    return int((at[1] + 180) / 360 * n), int((1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * n)


def test_decode_reads_fields_in_map_units_north_row_first():
    g = weather.decode(SAMPLE)
    assert g["lat0"] == -36.0 and g["dlat"] == 0.5 and g["lon0"] == 168.0
    f = g["fields"]
    assert set(f) >= {"temp", "rain", "cloud", "u", "v", "wind", "pressure"}
    assert -10 < float(f["temp"].min()) < float(f["temp"].max()) < 40        # °C, not K
    assert 990 < float(f["pressure"].mean()) < 1040                          # hPa
    assert 0 <= float(f["cloud"].min()) and float(f["cloud"].max()) <= 100
    # Wellington, about 15 °C on the night of the sample; nothing outside the box
    assert 10 < weather.sample(g, "temp", np.array([-41.3]), np.array([174.8]))[0] < 20
    assert np.isnan(weather.sample(g, "temp", np.array([0.0]), np.array([0.0]))[0])


def test_tiles_draw_each_field_and_leave_outside_see_through():
    g = weather.decode(SAMPLE)
    x, y = _nz_tile()
    for field in [f for f in weather.FIELDS if f not in weather.WAVE_FIELDS]:
        px = _rgba(weather.render(g, field, 5, x, y))
        assert px.shape == (256, 256, 4)
        assert px[..., 3].max() > 0, field
    temp = _rgba(weather.render(g, "temp", 5, x, y))
    assert temp[..., 3].min() == 0  # the box does not fill the tile
    assert _rgba(weather.render(g, "temp", 5, 0, 0))[..., 3].max() == 0


def _fake_run(home: Path, rid: str, steps: list[int], detail="0p50"):
    d = home / "weather" / "gfs" / detail / rid
    d.mkdir(parents=True, exist_ok=True)
    for s in steps:
        (d / f"f{s:03d}.grib2").write_bytes(SAMPLE.read_bytes())


def test_serving_prefers_newest_complete_run(_home):
    days = 1
    _fake_run(_home, "2026112506", weather.steps_for(days))
    _fake_run(_home, "2026112512", [0, 3])  # still downloading
    assert weather.serving("0p50", days) == ("2026112506", weather.steps_for(days))
    st = weather.status({"weather_days": days}, start=False)
    assert st["run"] == "2026112506" and st["run_time"] == "2026-11-25T06:00:00Z" and st["steps"][-1] == 24


def test_fetch_downloads_newest_ready_run_and_drops_older(_home):
    _fake_run(_home, "2026112500", weather.steps_for(1))
    asked = []

    def get(url, params):
        asked.append(params["file"])
        assert "filter_gfs_0p50.pl" in url and params["var_TMP"] == "on" and params["lev_mean_sea_level"] == "on"
        return SAMPLE.read_bytes()
    newest = weather.candidates()[1]
    head = lambda url: f"gfs.{newest[:8]}/{newest[8:]}/" in url  # noqa: E731 - the newest run is not out yet
    got = weather.fetch("0p50", 1, get=get, head=head, gap=0)
    assert got == newest
    assert asked == [f"gfs.t{newest[8:]}z.pgrb2full.0p50.f{s:03d}" for s in weather.steps_for(1)]
    assert list(weather.stored("0p50")) == [newest]
    # once complete, nothing more is downloaded
    assert weather.fetch("0p50", 1, get=lambda *a: pytest.fail("downloaded again"), head=head, gap=0) == newest


def test_fetch_refuses_an_error_page(_home):
    with pytest.raises(ValueError):
        weather.fetch("0p50", 1, get=lambda url, params: b"<html>error</html>", head=lambda url: True, gap=0)


def test_candidates_are_runs_already_out():
    now = datetime(2026, 11, 25, 20, 30, tzinfo=timezone.utc)
    assert weather.candidates(now, 3) == ["2026112512", "2026112506", "2026112500"]


def test_routes_serve_status_tiles_and_values(_home, monkeypatch):
    rid = "2026112512"
    _fake_run(_home, rid, weather.steps_for(1))
    monkeypatch.setattr(userdata, "settings", lambda: {"weather_maps": True, "weather_days": 1, "weather_detail": "0p50"})
    monkeypatch.setattr(weather, "_maybe_start", lambda *a: None)
    c = TestClient(main.app)
    st = c.get("/api/v1/weather/status").json()
    assert st["run"] == rid and st["legends"]["temp"][0][0] == -40
    x, y = _nz_tile()
    r = c.get(f"/api/v1/weather/tiles/temp/{rid}/3/5/{x}/{y}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get(f"/api/v1/weather/tiles/temp/2020010100/3/5/{x}/{y}.png").status_code == 404
    at = c.get("/api/v1/weather/at", params={"lat": -41.3, "lon": 174.8, "step": 3}).json()
    assert 10 < at["values"]["temp"] < 20 and 0 <= at["values"]["from_deg"] < 360 and at["valid"] == "2026-11-25T15:00:00Z"


def test_cloud_pixels_keep_cold_cloud_and_clear_warm_ground():
    px = np.array([[[100, 100, 100, 255], [220, 220, 220, 255], [255, 0, 200, 255], [0, 0, 0, 0]]], dtype=np.uint8)
    out = weather.cloud_pixels(px)
    assert out[0, 0, 3] == 0 and out[0, 1, 3] > 200 and out[0, 2, 3] == 235 and out[0, 3, 3] == 0


def test_clouds_tile_merges_satellites():
    def get(url):
        im = Image.new("RGBA", (256, 256), (230, 230, 230, 255) if "Himawari" in url else (0, 0, 0, 0))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()
    px = _rgba(weather.clouds_tile(7, 120, 40, get=get))
    assert px[..., 3].min() > 200


OPEN_METEO = {
    "timezone": "Pacific/Auckland", "utc_offset_seconds": 46800, "elevation": 20,
    "current": {"time": "2026-11-26T09:00", "temperature_2m": 16.2, "apparent_temperature": 14.0, "relative_humidity_2m": 70,
                "precipitation": 0, "cloud_cover": 20, "wind_speed_10m": 35.0, "wind_direction_10m": 315, "wind_gusts_10m": 60,
                "weather_code": 1, "pressure_msl": 1018},
    "hourly": {"time": ["2026-11-26T09:00", "2026-11-26T10:00"], "temperature_2m": [16.2, 17.0], "precipitation": [0, 0.4],
               "precipitation_probability": [5, 40], "cloud_cover": [20, 60], "wind_speed_10m": [35, 30],
               "wind_direction_10m": [315, 320], "weather_code": [1, 61]},
    "daily": {"time": ["2026-11-26"], "weather_code": [61], "temperature_2m_max": [19], "temperature_2m_min": [11],
              "precipitation_sum": [2.1], "precipitation_probability_max": [60], "wind_speed_10m_max": [45],
              "wind_direction_10m_dominant": [310], "sunrise": ["2026-11-26T05:50"], "sunset": ["2026-11-26T20:40"]},
}
MET = {"properties": {"timeseries": [
    {"time": "2026-11-25T20:00:00Z", "data": {"instant": {"details": {"air_temperature": 16.0, "cloud_area_fraction": 0.0,
     "wind_speed": 12.3, "wind_from_direction": 314.7, "relative_humidity": 64.2, "air_pressure_at_sea_level": 1021.8}},
     "next_1_hours": {"summary": {"symbol_code": "clearsky_night"}, "details": {"precipitation_amount": 0.0}}}},
    {"time": "2026-11-25T21:00:00Z", "data": {"instant": {"details": {"air_temperature": 15.0, "cloud_area_fraction": 50.0,
     "wind_speed": 10.0, "wind_from_direction": 300}},
     "next_1_hours": {"summary": {"symbol_code": "lightrain"}, "details": {"precipitation_amount": 0.6}}}},
]}}


def test_point_forecast_from_open_meteo_is_kept():
    calls = []

    def get(url, params):
        calls.append((url, params))
        return OPEN_METEO
    got = weather.point({"weather_point": "open_meteo", "weather_days": 7}, -41.2865, 174.7762, get=get)
    assert got["now"]["temp"] == 16.2 and got["now"]["words"] == "Mostly clear" and got["daily"][0]["words"] == "Light rain"
    assert got["hourly"]["rain"] == [0, 0.4] and got["timezone"] == "Pacific/Auckland" and got["lat"] == -41.29
    assert calls[0][1]["forecast_days"] == 7 and calls[0][1]["timezone"] == "auto"
    weather.point({"weather_point": "open_meteo", "weather_days": 7}, -41.2865, 174.7762, get=get)
    assert len(calls) == 1


def test_point_forecast_from_met_norway_in_the_same_shape():
    got = weather.point({"weather_point": "met_norway", "weather_days": 2}, -41.3, 174.8, get=lambda url, params: MET)
    assert got["source"] == "met_norway" and got["now"]["wind"] == 44.3 and got["now"]["words"] == "Clear"
    assert got["hourly"]["time"] == ["2026-11-25T20:00", "2026-11-25T21:00"]
    # hour-ending like Open-Meteo: the 20:00-21:00 rain (0.0) belongs to 21:00; 21:00-22:00's 0.6 is past the last hour
    assert got["hourly"]["rain"] == [None, 0.0]
    assert got["daily"][0]["high"] == 16.0 and got["daily"][0]["rain"] == 0.0


def test_point_failure_says_who():
    def boom(url, params):
        raise OSError("down")
    got = weather.point({}, 0, 0, get=boom)
    assert "Open-Meteo did not answer" in got["error"]


# ----------------------------------------------------------------------------- waves (NOAA GFS-Wave)
WAVES = Path(__file__).parent / "fixtures" / "gfswave_nz_f006.grib2"  # a real 0.25° step, 172-176°E, 34-38°S


def test_wave_file_reads_heights_periods_and_the_main_swell_with_land_left_out():
    g = weather.decode(WAVES)
    f = g["fields"]
    assert g["dlat"] == 0.25 and g["lat0"] == -34.0
    assert {"waves", "wave_period", "wind_waves", "swell", "swell_period", "wu", "wv", "su", "sv"} <= set(f)
    assert np.isnan(f["waves"]).any() and np.nanmax(f["waves"]) < 15      # Northland and Auckland are land
    assert 1 < np.nanmax(f["wave_period"]) < 25
    # off the west coast, about 37°S 173°E: sea, with a swell
    assert weather.sample(g, "swell", np.array([-37.0]), np.array([173.0]))[0] > 0.2


def test_wave_tiles_and_values_under_the_pointer(_home, monkeypatch):
    rid = "2026112612"
    d = _home / "weather" / "waves" / "0p25" / rid
    d.mkdir(parents=True)
    for s in weather.steps_for(1, "waves"):
        (d / f"f{s:03d}.grib2").write_bytes(WAVES.read_bytes())
    _fake_run(_home, rid, weather.steps_for(1))
    monkeypatch.setattr(userdata, "settings", lambda: {"weather_maps": True, "weather_days": 1, "weather_detail": "0p50"})
    monkeypatch.setattr(weather, "_maybe_start", lambda *a: None)
    c = TestClient(main.app)
    st = c.get("/api/v1/weather/status", params={"waves": True}).json()
    assert st["waves"]["run"] == rid and st["waves"]["steps"] == [0, 6, 12, 18, 24] and st["model"] == "gfs"
    x, y = _nz_tile(6, (-37.0, 173.0))
    for f in ("waves", "swell"):
        r = c.get(f"/api/v1/weather/tiles/{f}/{rid}/6/6/{x}/{y}.png")
        assert r.status_code == 200 and _rgba(r.content)[..., 3].max() > 0
    v = c.get("/api/v1/weather/at", params={"lat": -37.0, "lon": 173.0, "step": 3, "wave_step": 6}).json()["values"]
    assert v["waves"] > 0 and 0 <= v["wave_from"] < 360 and v["swell_period"] > 3 and "wu" not in v
    assert 10 < v["temp"] < 30  # the GFS step too


def test_wave_fetch_asks_nomads_for_the_wave_fields(_home):
    asked = []

    def get(url, params):
        asked.append(params["file"])
        assert url.endswith("filter_gfswave.pl") and params["var_SWELL"] == "on" and params["lev_1_in_sequence"] == "on"
        assert params["dir"].endswith("/wave/gridded")
        return WAVES.read_bytes()
    newest = weather.candidates(model="waves")[0]
    got = weather.fetch("0p25", 1, get=get, head=lambda url: "/wave/gridded/gfswave" in url and url.endswith(".idx"), gap=0, model="waves")
    assert got == newest and asked == [f"gfswave.t{newest[8:]}z.global.0p25.f{s:03d}.grib2" for s in (0, 6, 12, 18, 24)]
    assert list(weather.stored("0p25", "waves")) == [newest]


# ----------------------------------------------------------------------------- ECMWF open data
def _ecmwf_step(values: dict[int, float]) -> bytes:
    """A small GRIB2 step with ECMWF's six fields (paramId -> one value everywhere), 172-176°E, 35-38°S."""
    import eccodes
    h = eccodes.codes_grib_new_from_samples("GRIB2")
    for k, v in [("gridType", "regular_ll"), ("Ni", 5), ("Nj", 4), ("latitudeOfFirstGridPointInDegrees", -35.0),
                 ("longitudeOfFirstGridPointInDegrees", 172.0), ("latitudeOfLastGridPointInDegrees", -38.0),
                 ("longitudeOfLastGridPointInDegrees", 176.0), ("iDirectionIncrementInDegrees", 1.0), ("jDirectionIncrementInDegrees", 1.0)]:
        eccodes.codes_set(h, k, v)
    out = b""
    for pid, val in values.items():
        g = eccodes.codes_clone(h)
        eccodes.codes_set(g, "paramId", pid)
        eccodes.codes_set_values(g, np.full(20, val, dtype=float))
        out += eccodes.codes_get_message(g)
        eccodes.codes_release(g)
    eccodes.codes_release(h)
    return out


def test_ecmwf_steps_and_runs():
    assert weather.steps_for(7, "ecmwf")[-4:] == [150, 156, 162, 168] and weather.steps_for(7, "ecmwf")[48] == 144
    now = datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc)
    assert weather.candidates(now, 3, "ecmwf") == ["2026112612", "2026112600", "2026112512"]


def test_ecmwf_index_picks_the_six_surface_fields():
    lines = [
        '{"param": "msl", "levtype": "sfc", "step": "6", "_offset": 100, "_length": 50}',
        '{"param": "t", "levtype": "pl", "levelist": "850", "_offset": 0, "_length": 99}',
        '{"param": "2t", "levtype": "sfc", "_offset": 500, "_length": 10}',
        '{"param": "tp", "levtype": "sfc", "_offset": 300, "_length": 20}',
        'not json',
    ]
    assert weather.ecmwf_ranges("\n".join(lines)) == [(100, 50), (300, 20), (500, 10)]


def test_ecmwf_fetch_reads_fields_by_byte_range_and_rain_is_the_change(_home, monkeypatch):
    rid = weather.candidates(model="ecmwf")[0]
    files = {s: _ecmwf_step({167: 290.15, 228: s * 0.0005, 164: 80.0, 165: 3.0, 166: 4.0, 151: 101300.0})
             for s in weather.steps_for(1, "ecmwf")}
    ranges = []

    def get(url, params):
        step = int(url.rsplit("-", 3)[1].rstrip("h"))
        if url.endswith(".index"):
            return f'{{"param": "2t", "levtype": "sfc", "_offset": 0, "_length": {len(files[step])}}}'.encode()
        assert url.startswith("https://data.ecmwf.int/forecasts/") and "/ifs/0p25/oper/" in url
        ranges.append(params["__range"])
        a, b = map(int, params["__range"][6:].split("-"))
        return files[step][a:b + 1]
    got = weather.fetch("0p25", 1, get=get, head=lambda url: url.endswith(".index"), gap=0, model="ecmwf")
    assert got == rid and len(ranges) == len(weather.steps_for(1, "ecmwf"))
    g = weather.load_step("0p25", rid, 6, "ecmwf")
    f = g["fields"]
    assert abs(float(f["temp"][0, 0]) - 17.0) < 0.01 and abs(float(f["pressure"][0, 0]) - 1013.0) < 0.01
    assert abs(float(f["rain"][0, 0]) - 0.5) < 0.01   # 0.5 mm an hour: 1.5 mm more over the 3 hours since step 3
    assert abs(float(f["wind"][0, 0]) - 18.0) < 0.01 and "tp" not in f
    assert abs(float(weather.load_step("0p25", rid, 0, "ecmwf")["fields"]["rain"][0, 0]) - 0.5) < 0.01
    monkeypatch.setattr(weather, "_maybe_start", lambda *a: None)
    st = weather.status({"weather_model": "ecmwf", "weather_days": 1}, start=False)
    assert st["model"] == "ecmwf" and st["model_name"] == "ECMWF IFS" and st["run"] == rid and st["detail"] == "0p25"


def test_wind_grid_for_the_moving_lines(_home):
    import base64
    rid = "2026112512"
    _fake_run(_home, rid, [3])
    got = weather.wind_grid({"weather_detail": "0p50"}, rid, 3)
    assert (got["nj"], got["ni"], got["lat0"], got["d"]) == (181, 360, 90.0, 1.0)
    u = np.frombuffer(base64.b64decode(got["u"]), dtype="<i2").reshape(181, 360)
    assert u[0, 0] == 0 and np.abs(u[90 + 41, 174]) > 0  # nothing outside the sample's box; wind over New Zealand
    assert weather.wind_grid({"weather_detail": "0p50"}, rid, 9) is None


# ----------------------------------------------------------------------------- air quality
AIR = {"timezone": "Pacific/Auckland",
       "current": {"time": "2026-11-27T08:00", "us_aqi": 52, "european_aqi": 34, "pm2_5": 12.1, "pm10": 19.3, "dust": 0,
                   "ozone": 33, "nitrogen_dioxide": 3.6, "uv_index": 0.95},
       "hourly": {"time": ["2026-11-27T00:00", "2026-11-27T13:00", "2026-11-28T09:00"], "us_aqi": [46, 120, 30],
                  "pm2_5": [11, 40, 5], "dust": [0, 0, 0]}}


def test_air_point_now_and_worst_hour_each_day():
    calls = []

    def get(url, params):
        calls.append(params)
        return AIR
    got = weather.air_point({}, -36.85, 174.76, get=get)
    assert got["now"]["us_aqi"] == 52 and got["now"]["words"] == "Moderate" and got["now"]["pm2_5"] == 12.1
    assert got["days"][0] == {"date": "2026-11-27", "us_aqi": 120, "hour": "13:00", "words": "Unhealthy for sensitive groups"}
    weather.air_point({}, -36.85, 174.76, get=get)
    assert len(calls) == 1 and "us_aqi" in calls[0]["current"]
    assert "switched off" in weather.air_point({"weather_air": False}, 0, 0, get=get)["error"]


def test_air_layer_for_big_cities(monkeypatch):
    import json
    from worldmodel_api import hazards
    hazards._cache.clear()
    cities = [{"name": "Auckland", "country": "NZL", "lat": -36.85, "lon": 174.76}, {"name": "Nowhere", "country": "XXX", "lat": 0, "lon": 0}]
    got = hazards.air(cities, True, fetch=lambda url, params: json.dumps([AIR, {"current": {}}]))
    assert [f["properties"]["name"] for f in got["features"]] == ["Auckland"]
    assert got["features"][0]["properties"]["us_aqi"] == 52 and got["checked"] == 2
    assert hazards.air(cities, False)["note"]


def test_rain_soon_from_quarter_hours():
    t = [f"2026-11-27T09:{m:02d}" for m in (0, 15, 30, 45)] + ["2026-11-27T10:00", "2026-11-27T10:15"]
    got = weather.rain_soon({"time": t, "precipitation": [0, 0, 0.2, 0.5, 0.05, 0]})
    assert got == {"now": False, "starts": "2026-11-27T09:30", "ends": "2026-11-27T10:00", "mm": 0.7, "hours": 1.5}
    assert weather.rain_soon({"time": t[:2], "precipitation": [0.3, 0.3]})["now"] is True
    assert weather.rain_soon({"time": t[:2], "precipitation": [0, 0]})["starts"] is None
    assert weather.open_meteo({**OPEN_METEO, "minutely_15": {"time": t, "precipitation": [0] * 6}})["rain_soon"]["now"] is False


def test_models_side_by_side_and_when_they_disagree():
    keys = list(weather.MODEL_SET)
    daily = {"time": ["2026-11-27", "2026-11-28"]}
    for i, k in enumerate(keys):
        daily[f"temperature_2m_max_{k}"] = [20 + i * 0.2, 18 + i]     # day 2: 18 to 23, 5° apart
        daily[f"precipitation_sum_{k}"] = [0, 4.0 if i == 0 else 0]   # day 2: one model wet
    calls = []
    got = weather.models_point({}, -36.85, 174.76, get=lambda url, params: calls.append(params) or {"daily": daily})
    d1, d2 = got["days"]
    assert d1["agree"] and d1["n"] == 6 and d1["high_lo"] == 20 and d1["models"][0]["name"] == "ECMWF"
    assert not d2["agree"] and d2["why"] == "highs 5° apart, some dry, some wet"
    assert calls[0]["models"].startswith("ecmwf_ifs025,gfs_seamless")
    weather.models_point({}, -36.85, 174.76, get=lambda *a: pytest.fail("asked again"))
