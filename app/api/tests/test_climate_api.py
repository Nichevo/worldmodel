"""Climate endpoints on a copy of the sample warehouse with made-up climate rows added:
the overview, one country (temperature, gases, projections with ranges, disasters, El Niño
link), the El Niño page, storm counts, the live map switch and policy."""

import json
import math
import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import climate, main
from worldmodel_api.warehouse import SAMPLE, Warehouse


def add_climate_rows(path):
    con = duckdb.connect(str(path))
    rows = []

    def put(e, ind, d, v, src, freq="A", variant="central", status="E", breakdown=""):
        rows.append((e, ind, d, freq, breakdown, variant, src, "t", float(v), status))

    oni = {y: 1.5 * math.sin(y * 1.3) for y in range(1980, 2024)}
    for y in range(1980, 2024):
        for m in range(1, 13):
            put("world", "enso_oni", date(y, m, 1), oni[y], "noaa_enso", "M")
        put("NZL", "temp_anomaly", date(y, 1, 1), 0.02 * (y - 1980) - 0.3 * oni[y], "owid_climate")
        put("world", "temp_anomaly_world", date(y, 1, 1), 0.3 + 0.02 * (y - 1980), "nasa_gistemp")
        put("world", "co2_ppm", date(y, 1, 1), 338 + 2 * (y - 1980), "noaa_gml")
    for y in (2021, 2022):
        put("NZL", "co2_gcp", date(y, 1, 1), 33, "owid_co2")
        put("NZL", "methane_emissions", date(y, 1, 1), 37, "owid_co2")
        put("NZL", "ghg_sector_agriculture", date(y, 1, 1), 39.5e6, "owid_climate")
    put("NZL", "net_zero_year", date(2025, 1, 1), 2050, "net_zero_tracker")
    put("NZL", "net_zero_status", date(2025, 1, 1), 3, "net_zero_tracker")
    put("NZL", "carbon_price", date(2023, 1, 1), 40.1, "carbon_pricing")
    for y, (c, lo, hi) in ((2050, (13.6, 13.1, 14.2)), (2100, (14.6, 13.8, 15.5))):
        put("NZL", "proj_temp_ssp245", date(y, 1, 1), c, "cckp", status="P")
        put("NZL", "proj_temp_ssp245", date(y, 1, 1), lo, "cckp", variant="lower80", status="P")
        put("NZL", "proj_temp_ssp245", date(y, 1, 1), hi, "cckp", variant="upper80", status="P")
    for m in range(1, 13):  # monthly normals, NZ only
        put("NZL", "clim_temp", date(2020, 1, 1), 10 + m, "cckp_normals", breakdown=f"month={m:02d}")
        put("NZL", "clim_rain", date(2020, 1, 1), 100 + m, "cckp_normals", breakdown=f"month={m:02d}")
    put("NZL", "clim_rain_year", date(2020, 1, 1), 1278, "cckp_normals")
    con.executemany("INSERT INTO observations VALUES (" + ", ".join("?" * 10) + ")", rows)
    for s in sorted({r[6] for r in rows}):
        con.execute("INSERT INTO vintages BY NAME SELECT ? AS source_id, 't' AS vintage, 't' AS release, true AS is_latest", [s])
    units = {"enso_oni": ("°C", "M"), "temp_anomaly": ("°C", "A"), "temp_anomaly_world": ("°C", "A"), "co2_ppm": ("parts per million", "A"),
             "co2_gcp": ("million tonnes CO2", "A"), "methane_emissions": ("million tonnes CO2e", "A"), "ghg_sector_agriculture": ("t CO2e", "A"),
             "net_zero_year": ("year", "A"), "net_zero_status": ("level", "A"), "carbon_price": ("US$ per tonne CO2e", "A"),
             "proj_temp_ssp245": ("°C", "A"), "clim_temp": ("°C", "A"), "clim_rain": ("mm", "A"), "clim_rain_year": ("mm", "A")}
    srcs = {r[1]: r[6] for r in rows}
    for i, (u, f) in units.items():
        con.execute("INSERT INTO indicators BY NAME SELECT ? AS indicator_id, ? AS name, '' AS description, 'climate' AS domain, ? AS unit, "
                    "1 AS decimals, ? AS frequency, '' AS breakdowns, 'none' AS agg_method, true AS default_on", [i, i.replace("_", " "), u, f])
        con.execute("INSERT INTO indicator_sources BY NAME SELECT ? AS indicator_id, ? AS source_id, ? AS series, 1.0 AS scale, 1 AS rank", [i, srcs[i], i])
    ev = [("e1", "world", "noaa_enso", "enso", "el_nino", "El Niño (very strong, peak +2.6 °C)", date(2015, 1, 1), date(2016, 4, 28), 2.6, None, None),
          ("e2", "NZL", "gdacs", "disaster", "storm", "Tropical cyclone: Gabrielle (red alert)", date(2023, 2, 8), date(2023, 2, 17), None, 11, 8e9),
          ("e3", "NZL", "treaty", "treaty", "paris", "Paris Agreement ratified", date(2016, 10, 4), None, None, None, None)]
    for e in ev:
        con.execute("INSERT INTO events BY NAME SELECT ? AS event_id, ? AS entity_id, ? AS source_id, 't' AS vintage, ? AS kind, ? AS subkind, "
                    "? AS title, ? AS start_date, ? AS end_date, 'day' AS precision, ? AS size, ? AS deaths, ? AS damage_usd", list(e))
    feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[170, -20], [175, -30]]},
              "properties": {"name": f"S{i}", "year": 2020 + i % 2, "basin": "South Pacific", "cat": i % 5}} for i in range(6)]
    con.execute("INSERT INTO layers VALUES ('storm_tracks', 'Tropical cyclone tracks', '', 'line', 'ibtracs', 't', 6, ?)",
                [json.dumps({"type": "FeatureCollection", "features": feats})])
    con.close()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("climate_api")
    path = d / "climate-sample.duckdb"
    shutil.copy(SAMPLE, path)
    add_climate_rows(path)
    mp = pytest.MonkeyPatch()
    mp.setenv("WORLDMODEL_HOME", str(d))
    mp.setenv("WORLDMODEL_USER_DIR", str(d / "user"))
    old = main.warehouse
    main.warehouse = Warehouse(str(path))
    yield TestClient(main.app)
    main.warehouse = old
    mp.undo()


def test_overview(client):
    r = client.get("/api/v1/climate").json()
    assert r["world"]["co2_ppm"][-1] == [2023, 424.0]
    assert r["enso"]["month"] == "2023-12" and r["enso"]["name"] in ("El Niño", "La Niña", "Neutral")
    assert "temp_anomaly" in r["emission_maps"] and "co2_gcp" in r["emission_maps"]


def test_country(client):
    r = client.get("/api/v1/climate/country/NZL").json()
    assert r["temperature"]["temp_anomaly"][0][0] == 1980
    assert r["gases"]["methane_emissions"][-1] == [2022, 37.0]
    assert r["net_zero"] == {"year": 2050.0, "status": 3.0}
    assert r["projections"]["proj_temp_ssp245"] == [[2050, 13.6, 13.1, 14.2], [2100, 14.6, 13.8, 15.5]]
    assert r["disasters"][0]["title"].startswith("Tropical cyclone")
    assert "south-westerly" in r["enso"]["el_nino"]  # the hand-written note
    assert r["enso"]["temp_r"] < -0.9  # made up to cool with El Niño, once the warming trend is taken out


def test_enso_page(client):
    r = client.get("/api/v1/climate/enso").json()
    assert len(r["series"]["enso_oni"]) == 44 * 12
    assert r["episodes"][0]["subkind"] == "el_nino"
    assert r["link"][0]["entity_id"] == "NZL" and "NZL" in r["notes"]


def test_storms_and_policy(client):
    r = client.get("/api/v1/climate/storms").json()
    assert r["years"] == [2020, 2021] and r["counts"] == [[3], [3]] and r["strong"] == [1, 1]
    p = client.get("/api/v1/climate/policy").json()
    nz = next(x for x in p["rows"] if x["entity_id"] == "NZL")
    assert nz["net_zero_year"] == 2050 and nz["carbon_price"] == pytest.approx(40.1) and nz["paris"] == "2016-10-04"


def test_live_switched_off():
    assert climate.live(False) == {"off": True, "rows": []}


ACTIVE_CSV = """SID,SEASON,NUMBER,BASIN,SUBBASIN,NAME,ISO_TIME,NATURE,LAT,LON,WMO_WIND,USA_WIND,USA_SSHS
 ,Year, , , , ,,, degrees_north,degrees_east,kts,kts,1
2026300S15170,2026,1,SP,MM,GITA,2026-11-08 00:00:00,TS,-15.0,178.0,40,45,0
2026300S15170,2026,1,SP,MM,GITA,2026-11-08 06:00:00,TS,-15.5,-179.5,,90,2
2026300S15170,2026,1,SP,MM,GITA,2026-11-09 12:00:00,TS,-16.0,-178.0,,70,1
2026290N10130,2026,2,WP,MM,OLDONE,2026-10-20 00:00:00,TS,10.0,130.0,,50,0
2026290N10130,2026,2,WP,MM,OLDONE,2026-10-21 00:00:00,TS,11.0,131.0,,55,0
"""


def test_active_storms_only_recent_and_across_180():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc).timestamp()
    feats = climate.active_features(ACTIVE_CSV, now)
    assert [f["properties"]["name"] for f in feats] == ["Gita"]  # the October storm is over
    p = feats[0]["properties"]
    assert p["cat"] == 2 and p["wind"] == 90 and p["basin"] == "South Pacific" and p["last"] == "2026-11-09 12:00"
    xs = [c[0] for c in feats[0]["geometry"]["coordinates"]]
    assert xs == [178.0, 180.5, 182.0]  # continuous across the date line


def test_active_storms_layer_says_why_when_off_or_failing(monkeypatch):
    climate._active.update(at=0.0, data=None)
    assert climate.active_storms(False)["features"] == []

    def boom() -> str:
        raise ConnectionError("no network")
    got = climate.active_storms(True, fetch=boom)
    assert got["features"] == [] and "NOAA did not answer" in got["note"]
    climate._active.update(at=0.0, data=None)


def test_monthly_normals(client):
    d = client.get("/api/v1/climate/normals", params={"entities": "NZL,AUS"}).json()
    assert [c["entity_id"] for c in d["countries"]] == ["NZL"]
    nz = d["countries"][0]
    assert nz["temp"][0] == 11 and nz["temp"][11] == 22 and nz["rain"][6] == 107 and nz["high"] == [None] * 12
    assert nz["summary"]["clim_rain_year"] == 1278 and d["period"] == "1991-2020"
