"""Transport, tourism and networks sources (connectors/transport.py, tourism.py, networks.py),
on fixtures. The airports and shipping lanes fixtures are trimmed copies of the real files."""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.networks import chain, parse_wkt
from worldmodel_data.connectors.tourism import figures, year_totals
from worldmodel_data.connectors.transport import chokepoint_events, shore_key
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("un_wpp", "portwatch", "world_port_index", "shipping_lanes", "ourairports", "airport_traffic",
           "eurostat_waterways", "taic_inquiries", "unesco_heritage", "un_tourism", "wef_ttdi", "nz_tourism",
           "hydrosheds", "waterways", "submarine_cables", "gem_infrastructure")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    CONNECTORS["transport_curated"]().ingest(store)
    result = build(home)
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


def test_ports_lanes_airports(built):
    _, con = built
    wpi = {f["properties"]["name"]: f["properties"] for f in _layer(con, "ports_all")}
    assert wpi["Auckland"]["size"] == "medium" and wpi["Lyttelton"]["depth"] == 10
    lanes = _layer(con, "shipping_lanes")
    assert {f["properties"]["rank"] for f in lanes} == {1, 2, 3}
    airports = _layer(con, "airports")
    akl = next(f for f in airports if f["properties"].get("iata") == "AKL")
    assert akl["properties"]["size"] == "large" and akl["properties"]["country"] == "NZL"
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
    waikato = rivers["1:5"]
    assert waikato[1]["flow"] == 340 and waikato[1]["length"] == 120 and waikato[2] == "NZL"
    geom = json.loads(con.execute("SELECT geojson FROM geo_features WHERE layer_id = 'rivers' AND feature_id = '1:5'").fetchone()[0])
    assert geom["type"] == "LineString"  # three reaches chained into one line
    assert "1:7" not in rivers  # flow order 7 is left out
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
