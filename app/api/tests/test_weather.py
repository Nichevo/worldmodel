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
    weather._state.update(thread=None, checked=0.0, note="", fetching=None, error="")
    yield tmp_path


def _rgba(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def _nz_tile(z=5):
    import math
    n = 2 ** z
    lat = math.radians(-41.3)
    return int((174.8 + 180) / 360 * n), int((1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * n)


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
    for field in weather.FIELDS:
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
    assert got["daily"][0]["high"] == 16.0 and got["daily"][0]["rain"] == 0.6


def test_point_failure_says_who():
    def boom(url, params):
        raise OSError("down")
    got = weather.point({}, 0, 0, get=boom)
    assert "Open-Meteo did not answer" in got["error"]
