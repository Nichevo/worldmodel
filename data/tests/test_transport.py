"""Transport, tourism and networks sources (connectors/transport.py, tourism.py, networks.py),
on fixtures. The airports and shipping lanes fixtures are trimmed copies of the real files."""

import json
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.networks import chain, parse_wkt
from worldmodel_data.connectors.tourism import figures, year_totals
from worldmodel_data.connectors.transport import chokepoint_events, shore_key
from worldmodel_data.port_pressure import impact, normal_series
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "portwatch", "nyfed_gscpi", "unctad_port_calls", "world_port_index", "shipping_lanes", "ourairports", "airport_traffic",
           "eurostat_waterways", "taic_inquiries", "unesco_heritage", "un_tourism", "wef_ttdi", "nz_tourism",
           "hydrosheds", "waterways", "submarine_cables", "gem_infrastructure", "ne_railways")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    CONNECTORS["transport_curated"]().ingest(store)
    result = build(home)
    result.home = home
    return result, duckdb.connect(str(result.path), read_only=True)


def _vals(con, ind, ent, breakdown=""):
    return {r[0]: r[1] for r in con.execute(
        "SELECT year(period_start), value FROM series WHERE indicator_id = ? AND entity_id = ? AND breakdown = ?",
        [ind, ent, breakdown]).fetchall()}


def _layer(con, layer_id):
    row = con.execute("SELECT geojson FROM layers WHERE layer_id = ?", [layer_id]).fetchone()
    return json.loads(row[0])["features"] if row else []


def _geo(con, layer_id):
    return {r[0]: (r[1], json.loads(r[2]), r[3]) for r in con.execute(
        "SELECT feature_id, name, props, countries FROM geo_features WHERE layer_id = ?", [layer_id]).fetchall()}


def test_helpers():
    assert shore_key("Strait of Hormuz") == shore_key("Hormuz Strait") == "hormuz"
    assert shore_key("Bab el-Mandeb Strait") == "bab mandeb"
    assert parse_wkt("LINESTRING (1 2, 3 4)") == {"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]}
    assert parse_wkt("MULTILINESTRING ((1 2, 3 4), (5 6, 7 8))")["type"] == "MultiLineString"
    assert parse_wkt("nonsense") is None
    assert chain([[[0, 0], [1, 1]], [[1, 1], [2, 2]]]) == [[[0, 0], [1, 1], [2, 2]]]
    # A fork stays as separate lines
    assert len(chain([[[0, 0], [1, 1]], [[1, 1], [2, 2]], [[1, 1], [3, 3]]])) == 3
    # Twelve months add up to a year; eleven do not
    t = year_totals([(("a",), 2024, m, 1.0) for m in range(1, 13)] + [(("a",), 2025, m, 1.0) for m in range(1, 12)])
    assert t == [(("a",), 2024, 12.0)]
    wide = figures([["Country", "2019", "2020"], ["New Zealand", "5", "6"]], "x")
    assert [(f["year"], f["value"]) for f in wide] == [(2019, 5.0), (2020, 6.0)]


def test_chokepoint_falls_become_one_event():
    days = []
    for y in (2022, 2023, 2024):
        for m in range(1, 13):
            for d in range(1, 26):  # a month needs 20 days or more to count
                days.append(("c1", "Suez Canal", date(y, m, d), 30.0 if y == 2024 and m <= 4 else 60.0))
    ev = chokepoint_events(days)
    assert len(ev) == 1
    cid, name, first, last, fall = ev[0]
    assert (first, last) == (date(2024, 1, 1), date(2024, 4, 1)) and fall == pytest.approx(50)


def test_portwatch(built):
    _, con = built
    calls = _vals(con, "port_calls", "NZL")
    assert calls[2024] == 12 * 220 and 2025 not in calls  # 2025 has three months only
    assert _vals(con, "seaborne_exports_t", "NZL")[2023] == 12 * 220 * 1500
    ports = {f["properties"]["name"]: f["properties"] for f in _layer(con, "ports")}
    assert ports["Auckland"]["calls"] == 1200 and ports["Auckland"]["year"] == 2024
    n = con.execute("SELECT count(*), min(day) FROM chokepoint_traffic WHERE chokepoint_id = 'chokepoint1'").fetchone()
    assert n[0] == 365 + 365 + 366 and n[1].year == 2022
    assert con.execute("SELECT count(*) FROM port_traffic WHERE entity_id = 'NZL'").fetchone()[0] == 2 * 36 + 3
    ev = con.execute("SELECT entity_id, title, start_date FROM events WHERE source_id = 'portwatch'").fetchall()
    assert ev == [("EGY", "Ships through Suez Canal down 50%", date(2024, 1, 1))]
    # Daily calls by ship type (2024 has a daily file, other years monthly sums only)
    d = con.execute("SELECT count(*), sum(calls), sum(container) FROM port_daily WHERE port_id = 'port2'").fetchone()
    assert d == (240, 1440, 480)
    ports = {f["properties"]["id"]: f["properties"] for f in _layer(con, "ports")}
    assert ports["port2"]["fact"] == "Largest export port in the economy"
    assert ports["port1"]["mix"] == {"container": 60, "dry_bulk": 20, "roro": 20}
    assert con.execute("SELECT transit_days, share_at_risk FROM port_links WHERE from_port = 'port1'").fetchone() == (1.5, 0.12)
    dis = {r[0]: r[1:] for r in con.execute(
        "SELECT event_id, port_id, hazard, alert, entity_id, start_date, end_date, distance_km FROM port_disruptions").fetchall()}
    assert dis["1001"] == ("port2", "cyclone", "red", "NZL", date(2024, 6, 13), date(2024, 6, 17), 42.5)
    assert dis["1002"][0] == "" and dis["1002"][3] == "TON"  # reached no port
    # The build works out weeks against normal and the cyclone's impact on Tauranga
    assert con.execute("SELECT count(*) FROM traffic_weekly WHERE place_kind = 'chokepoint'").fetchone()[0] > 150
    imp = con.execute("SELECT place_name, hazard, origin FROM traffic_impacts").fetchall()
    assert imp == [("Tauranga", "cyclone", "portwatch")]


def test_supply_chain_pressure_and_time_in_port(built):
    _, con = built
    g = dict(con.execute("SELECT period_start, value FROM observations WHERE indicator_id = 'gscpi' AND freq = 'M'").fetchall())
    assert g[date(2021, 12, 1)] == 4.33 and g[date(2020, 4, 1)] == 2.85 and len(g) == 5
    assert _vals(con, "port_time_days", "NZL") == {2022: 1.32, 2023: 1.21}
    assert _vals(con, "port_time_container_days", "NZL")[2023] == 0.95
    assert _vals(con, "port_time_liquid_bulk_days", "AUS")[2023] == 1.30
    assert _vals(con, "port_time_days", "world")[2023] == 0.99


def test_port_pressure_off_season_port():
    # A port busy only part of the year: in earlier years no ships came in the weeks after the
    # event, so nothing is expected then. That is no impact to measure, not an error.
    weeks = 52 * 3 + 30
    v = np.array([20.0 if (i % 52) < 10 else 0.0 for i in range(weeks)])
    assert impact(v, None, 52 * 3 + 12, 52 * 3 + 13) is None


def test_port_pressure_maths():
    weeks = 52 * 3 + 30
    season = np.array([100 + 20 * np.sin(2 * np.pi * (i % 52) / 52) for i in range(weeks)])
    v = season.copy()
    s = 52 * 3 + 10
    v[s:s + 3] = season[s:s + 3] * 0.5  # three weeks at half
    norm = normal_series(v)
    assert np.isnan(norm[:8]).all() and abs(norm[s - 1] / season[s - 1] - 1) < 0.02
    got = impact(v, v * 1000, s, s + 2)
    assert got["worst_pct"] == pytest.approx(-50, abs=1)
    assert got["rec"] == s + 3  # back the week after
    assert got["lost"] == pytest.approx(season[s:s + 3].sum() * 0.5, rel=0.03)
    assert got["lost_t"] == pytest.approx(got["lost"] * 1000, rel=0.03)
    assert len(got["curve"]) == 21 and got["curve"][4] == pytest.approx(0.5, abs=0.02)
    # Too little before an event to tell
    assert impact(v, None, 3, 4) is None


def test_ports_lanes_airports(built):
    _, con = built
    wpi = {f["properties"]["name"]: f["properties"] for f in _layer(con, "ports_all")}
    assert wpi["Auckland"]["size"] == "medium" and wpi["Lyttelton"]["depth"] == 10
    lanes = _layer(con, "shipping_lanes")
    assert {f["properties"]["rank"] for f in lanes} == {1, 2, 3}
    airports = _layer(con, "airports")
    akl = next(f for f in airports if f["properties"].get("iata") == "AKL")
    assert akl["properties"]["size"] == "large" and akl["properties"]["country"] == "NZL"
    assert akl["properties"]["runway_m"] == 3635  # the longest open runway; the closed grass one is left out
    chc = next(f for f in airports if f["properties"].get("iata") == "CHC")
    assert chc["properties"]["runway_m"] == 3288
    assert all(f["properties"]["size"] in ("large", "medium") for f in airports)


def test_airport_and_river_traffic(built):
    _, con = built
    at = {(r[0], r[1]): (r[2], r[3], r[4]) for r in con.execute(
        "SELECT airport, year, entity_id, passengers, freight_t FROM airport_traffic").fetchall()}
    assert at[("EDDF", 2024)] == ("DEU", 61600000, 2000000)
    assert at[("NZAA", 2024)][:2] == ("NZL", 18500000)
    assert _vals(con, "inland_waterway_freight", "DEU")[2023] == 172000 * 1000
    assert _vals(con, "inland_waterway_freight", "NLD")[2023] == 340000 * 1000


def test_accident_and_infrastructure_events(built):
    _, con = built
    taic = con.execute("SELECT subkind, start_date, deaths FROM events WHERE source_id = 'taic_inquiries' ORDER BY 2").fetchall()
    assert taic == [("sea", date(2018, 3, 15), 0), ("air", date(2021, 2, 12), 2)]
    cur = con.execute("SELECT entity_id, kind, subkind, start_date, end_date FROM events WHERE source_id = 'transport_curated'").fetchall()
    ns = [r for r in cur if r[2] == "pipeline" and r[3] == date(2022, 9, 26)]
    assert {r[0] for r in ns} == {"DEU", "RUS", "DNK", "SWE"}
    assert any(r[0] == "TON" and r[2] == "cable" and r[4] == date(2022, 2, 22) for r in cur)
    assert any(r[0] == "USA" and r[1] == "transport" for r in cur)


def test_tourism(built):
    _, con = built
    assert _vals(con, "heritage_sites", "NZL")[1990] == 2 and _vals(con, "heritage_sites", "NZL")[1998] == 3
    assert _vals(con, "heritage_sites_in_danger", "AFG")
    sites = {f["properties"]["name"]: f["properties"] for f in _layer(con, "heritage_sites")}
    assert sites["Bamiyan Valley"]["danger"] == 1 and "Glaciers" in sites["Te Wahipounamu – South West New Zealand"]["about"]
    assert _vals(con, "unt_arrivals", "NZL")[2019] == 3702 * 1000
    assert _vals(con, "unt_arrivals", "NZL", "origin=AUS")[2019] == 1500000
    assert _vals(con, "unt_receipts_usd", "NZL")[2019] == 11300 * 1e6
    assert _vals(con, "ttdi_score", "NZL")[2024] == pytest.approx(4.68)
    assert _vals(con, "ttdi_rank", "NZL")[2024] == 20
    assert _vals(con, "ttdi_score", "NZL", "pillar=Natural Resources")[2024] == pytest.approx(5.4)
    arr = _vals(con, "nz_visitor_arrivals", "NZL")
    assert arr == {2024: 12 * 300000}
    assert _vals(con, "nz_visitor_arrivals", "NZL", "origin=AUS") == {2024: 12 * 120000}
    assert _vals(con, "nz_tourism_gdp_share", "NZL")[2019] == pytest.approx(5.5)


def test_rivers_and_basins(built):
    _, con = built
    rivers = _geo(con, "rivers")
    # Smaller rivers (order 4 and up) are stored by square, and by the name they run along
    waikato = {k: v for k, v in rivers.items() if k.startswith("1:5:")}
    assert set(waikato) == {"1:5:58_-13", "1:5:waikato:58_-13"}
    assert sum(v[1]["length"] for v in waikato.values()) == 145 and waikato["1:5:58_-13"][2] == "NZL"
    # A reach that runs along one of Natural Earth's named rivers takes its name, and a known
    # river shows from its name's rank (Waikato: scalerank 6 -> 5) or its flow order if sooner
    named = waikato["1:5:waikato:58_-13"]
    assert named[0] == "Waikato" and named[1]["order"] == 5 and named[1]["flow"] == 345
    assert "1:7:117_-26" in rivers  # flow order 7 (under 1 m3/s) is kept in New Zealand ...
    assert not any(k.startswith("40:") for k in rivers)  # ... but not elsewhere
    assert rivers["30:6:115_-29"][1]["order"] == 6  # 1 to 10 m3/s is kept everywhere
    assert {k for k in rivers if k.startswith("10:4:")} == {"10:4:23_-6", "10:4:24_-6"}  # order 4: 6 degree squares
    basins = _geo(con, "basins")
    assert set(basins) == {"500", "600"}  # the small basin outside New Zealand is left out
    name, props, countries = basins["600"]
    assert name == "Murray basin" and props["area"] == 1050000 and countries == "AUS"
    assert props["flow"] == 420 and props["of_country"]["AUS"] > 0.05 and not props["transboundary"]
    assert basins["500"][0] == "Waikato basin" and basins["500"][1]["flow"] == 340
    assert "Waikato" in {v[0] for v in _geo(con, "river_names").values()}


def test_waterways_cables_pipelines(built):
    _, con = built
    ww = _geo(con, "waterways")
    assert ww["us:mississippiriver"][0] == "Mississippi River" and ww["us:mississippiriver"][2] == "USA"
    assert ww["eu:rhine:vib"][1]["cemt"] == "VIb"
    assert ww["river:mekong"][1]["to"].startswith("Phnom Penh")
    cables = _geo(con, "cables")
    scn = cables["southern-cross-next"]
    assert scn[1]["rfs"] == 2022 and set(scn[2].split(",")) == {"AUS", "FJI", "NZL", "USA"}
    tga = cables["tasman-global-access"]  # no details: countries from the landing points at its ends
    assert set(tga[2].split(",")) == {"AUS", "NZL"}
    assert len(_layer(con, "cable_landings")) == 3
    gas = _geo(con, "gas_pipelines")
    assert gas["P0001"][0] == "Maui Pipeline" and gas["P0001"][2] == "NZL" and gas["P0001"][1]["capacity"] == 2.0
    assert set(gas["P0002"][2].split(",")) == {"DEU", "RUS"} and "P0003" not in gas
    assert _geo(con, "oil_pipelines")["O0001"][0] == "Refinery to Auckland Pipeline"
    lng = {f["properties"]["name"]: f["properties"] for f in _layer(con, "lng_terminals")}
    assert lng["Gladstone LNG"]["capacity"] == 7.8 and lng["Marsden Point LNG"]["status"] == "proposed"


def test_railways(built):
    _, con = built
    geo = _geo(con, "railways")
    assert geo and all(name == "Railways" for name, _, _ in geo.values())
    ranks = {props["rank"] for _, props, _ in geo.values()}
    assert ranks == {1, 2, 3}  # the fixture has New Zealand lines from scalerank 5 to 10
    assert any("NZL" in (c or "") for _, _, c in geo.values())


def test_river_names_and_many_geo_rows(tmp_path):
    from worldmodel_data.connectors.networks import RiverNames, clean_river_name, spread
    from worldmodel_data.connectors.transport import stage_geo

    assert clean_river_name("Waikato  River") == "Waikato" and clean_river_name("") is None
    assert spread([[0, 0], [4, 0]], 5) == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
    f = tmp_path / "ne.geojson"
    f.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "Big River", "featurecla": "River", "scalerank": 4},
         "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}}]}))
    names = RiverNames([f, None])
    assert names.name_of([[0.1, 0.01], [0.5, -0.01], [0.9, 0.02]]) == ("Big", 4)  # runs along it
    assert names.name_of([[0.5, 0.5], [0.5, 0.2], [0.5, 0.0]]) is None  # a side stream that only meets it
    assert names.name_of([[0.1, 0.01], [0.5, -0.01], [0.9, 0.02]], 7) is None  # a stream far smaller than it
    assert names.name_of([[0.1, 0.01], [0.5, -0.01], [0.9, 0.02]], 6) == ("Big", 4)
    # Many rows go in by way of a file, names with quotes and all
    con = duckdb.connect()
    rows = [("rivers", str(i), 'Wai "o" ā' if i % 2 else None, 6, {"flow": 1.5}, ["NZL"],
             {"type": "LineString", "coordinates": [[170 + i / 1e4, -40], [170.1, -40.1]]}) for i in range(2500)]
    q = stage_geo(con, rows)
    got = con.execute(f"SELECT count(*), count(name), max(name), min(west) FROM ({q})").fetchone()
    assert got == (2500, 1250, 'Wai "o" ā', 170.0)


def test_gem_whole_download_zip(tmp_path):
    """GEM's whole-site download: a zip of every tracker, the pipelines' routes in GeoJSON
    inside zips of their own; the spreadsheets have no routes and other trackers are ignored."""
    import io
    import zipfile

    from worldmodel_data.connectors.networks import GEMInfrastructure

    def fc(*feats):
        return json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": p, "geometry": g} for p, g in feats]}).encode()

    gas = fc(({"ProjectID": "P0001", "PipelineName": "Maui Pipeline", "Status": "operating", "CountriesOrAreas": "New Zealand", "Fuel": "Gas"},
              {"type": "LineString", "coordinates": [[174.0, -39.1], [174.8, -38.0]]}),
             ({"ProjectID": "P0002", "PipelineName": "Odd one", "Status": "proposed", "CountriesOrAreas": "Australia", "Fuel": "Gas"},
              {"type": "GeometryCollection", "geometries": [{"type": "LineString", "coordinates": [[150.0, -30.0], [151.0, -31.0]]}]}))
    oil = fc(({"ProjectID": "O0001", "PipelineName": "Refinery to Auckland Pipeline", "Status": "operating", "CountriesOrAreas": "New Zealand"},
              {"type": "LineString", "coordinates": [[174.49, -35.84], [174.78, -36.98]]}),
             ({"ProjectID": "O0002", "PipelineName": "No route yet", "Status": "proposed"}, None))
    lng = fc(({"ProjectID": "T1", "UnitID": "G1", "TerminalName": "Gladstone LNG", "Status": "operating", "Country/Area": "Australia",
               "CapacityinMtpa": 7.8, "FacilityType": "export"}, {"type": "Point", "coordinates": [151.3, -23.8]}))

    def zipped(files: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, d in files.items():
                z.writestr(n, d)
        return buf.getvalue()

    outer = zipped({
        "GEM-GGIT-Gas-Pipelines-2025-11.zip": zipped({"GEM-GGIT-Gas-Pipelines-2025-11.geojson": gas,
                                                      "__MACOSX/._GEM-GGIT-Gas-Pipelines-2025-11.geojson": b"junk"}),
        "GEM-GOIT-Oil-NGL-Pipelines-2026-06-corrected.zip": zipped({"GEM-GOIT-Oil-NGL-Pipelines-2026-07-21.geojson": oil,
                                                                    "GEM-GOIT-Oil-NGL-Pipelines-2026-07-21-shp.zip": b"not read"}),
        "GEM-GGIT-LNG-Terminals-2026-10.zip": zipped({"GEM-GGIT-LNG-Terminals-2026-10.geojson": lng}),
        "GEM-GGIT-Gas-Pipelines-2025-11.xlsx": b"not a real workbook: left out, the GeoJSON has the routes",
        "GEM LNG Carrier Tracker - June 2026 release.xlsx": b"other tracker",
        "Global-Coal-Plant-Tracker-July-2026.xlsx": b"other tracker",
    })
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "gem-data.zip").write_bytes(outer)
    c = GEMInfrastructure()
    names = sorted(p.name for p, _ in c._files(raw))
    assert names == ["GEM-GGIT-Gas-Pipelines-2025-11.geojson", "GEM-GGIT-LNG-Terminals-2026-10.geojson",
                     "GEM-GOIT-Oil-NGL-Pipelines-2026-07-21.geojson"]
    con = duckdb.connect()
    c.stage(con, raw, "2026-11", "v1")
    g = c.layers[0]["geojson"]
    lng_feats = (json.loads(g) if isinstance(g, str) else g)["features"]
    assert [(f["properties"]["name"], f["properties"]["country"], f["properties"]["capacity"]) for f in lng_feats] == [("Gladstone LNG", "AUS", 7.8)]
    assert lng_feats[0]["geometry"]["coordinates"] == [151.3, -23.8]
    got = {r[1]: (r[0], r[2], r[5]) for r in con.execute(c.history_queries["geo_features"]).fetchall()}
    assert got == {"P0001": ("gas_pipelines", "Maui Pipeline", "NZL"), "P0002": ("gas_pipelines", "Odd one", "AUS"),
                   "O0001": ("oil_pipelines", "Refinery to Auckland Pipeline", "NZL")}  # O0002 has no route


def test_world_port_index_outage_copy(tmp_path):
    """While NGA's portal answers 503, the zipped copy its outage page links to is used."""
    import zipfile

    import httpx

    csv_bytes = (FIXTURES / "world_port_index" / "UpdatedPub150.csv").read_bytes()
    zp = tmp_path / "WPI.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("UpdatedPub150.csv", csv_bytes)

    def handler(req):
        if req.url.path == "/apology_objects/WPI.zip":
            return httpx.Response(200, content=zp.read_bytes())
        return httpx.Response(503, text="<html>MSI IS CURRENTLY UNDER MAINTENANCE</html>")

    raw = tmp_path / "raw"
    raw.mkdir()
    conn = CONNECTORS["world_port_index"](client=httpx.Client(transport=httpx.MockTransport(handler)))
    from worldmodel_data.connectors import base
    real_sleep, base.time.sleep = base.time.sleep, lambda s: None
    try:
        assert conn.download(raw, "x").endswith("WPI.zip")
    finally:
        base.time.sleep = real_sleep
    assert not (raw / "UpdatedPub150.csv").exists()
    conn.stage(duckdb.connect(), raw, "x", "v")
    assert conn.layers and conn.layers[0]["feature_count"] == 2


def test_port_pressure_reused_when_traffic_and_events_unchanged(built):
    result, con = built
    same = "SELECT count(*), sum(hash(t)) FROM {} t"
    before = [con.execute(same.format(t)).fetchone() for t in ("traffic_weekly", "traffic_impacts")]
    again = build(result.home)
    reused = next((c.detail for c in again.checks if c.check_id == "build:reused"), "")
    assert "port_pressure_weeks" in reused and "port_pressure_impacts" in reused
    con2 = duckdb.connect(str(again.path), read_only=True)
    try:
        assert [con2.execute(same.format(t)).fetchone() for t in ("traffic_weekly", "traffic_impacts")] == before
    finally:
        con2.close()


def test_port_pressure_impacts_redone_when_only_events_change(tmp_path):
    from worldmodel_data import port_pressure
    from worldmodel_data.stepcache import StepCache

    def con_with(events: list[tuple]):
        c = duckdb.connect()
        c.execute("""CREATE TABLE port_daily AS SELECT 'p1' AS port_id, 'NZL' AS entity_id, d::DATE AS day,
                     CASE WHEN d BETWEEN DATE '2024-06-10' AND DATE '2024-06-23' THEN 2 ELSE 10 END AS calls,
                     100.0 AS import_t, 50.0 AS export_t
                     FROM range(DATE '2023-01-02', DATE '2024-12-30', INTERVAL 1 DAY) r(d)""")
        c.execute("CREATE TABLE port_disruptions (event_id VARCHAR, port_id VARCHAR, name VARCHAR, hazard VARCHAR, "
                  "entity_id VARCHAR, start_date DATE, end_date DATE)")
        c.executemany("INSERT INTO port_disruptions VALUES (?, 'p1', ?, 'cyclone', 'NZL', ?, ?)", events)
        return c

    cache = StepCache(tmp_path)
    one = [("e1", "Storm", date(2024, 6, 10), date(2024, 6, 20))]
    first = port_pressure.compute(con_with(one), cache)
    assert first["traffic_impacts"] == 1 and cache.reused == []
    port_pressure.compute(con_with(one), cache)
    assert cache.reused == ["port_pressure_weeks", "port_pressure_impacts"]
    cache.reused.clear()
    c = con_with(one + [("e2", "Second storm", date(2024, 6, 12), date(2024, 6, 20))])
    got = port_pressure.compute(c, cache)
    assert cache.reused == ["port_pressure_weeks"] and got["traffic_impacts"] == 2
    assert got["traffic_weekly"] == first["traffic_weekly"]
