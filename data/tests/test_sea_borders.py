"""Economic zones (Marine Regions) and flight information regions (VATSIM), staged from small
hand-made and trimmed fixtures."""

import json
from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.seas import _country_of, eez_areas, vatspy
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "marine_regions", "vatsim_airspace"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return duckdb.connect(str(result.path), read_only=True)


def _geo(con, layer_id):
    return {r[0]: (r[1], json.loads(r[2]), sorted(filter(None, (r[3] or "").split(","))), r[4]) for r in con.execute(
        "SELECT feature_id, name, props, countries, rank FROM geo_features WHERE layer_id = ?", [layer_id]).fetchall()}


def test_vatspy_names():
    text = (FIXTURES / "vatsim_airspace" / "VATSpy.dat").read_text(encoding="utf-8")
    prefixes, names = vatspy(text)
    assert prefixes["NZ"] == "New Zealand" and prefixes["YM"] == "Australia"
    assert names["NZZO"] == "Auckland Radio"  # its own entry, not Pago Pago's that reuses the outline
    assert names["YBAR"] == "Brisbane (Barra)"  # radio frequencies taken off
    assert _country_of("NZZO", prefixes) == "NZL" and _country_of("NFFF", prefixes) == "FJI"


def test_eez_areas_leave_out_joint_regimes():
    feats = json.loads((FIXTURES / "marine_regions" / "eez_zones.geojson").read_text())["features"]
    areas = eez_areas(feats)
    assert areas["NZL"] == 4083744 + 319031  # Tokelau counts for New Zealand
    assert areas["AUS"] == 6048681


def test_layers_and_sea_area(built):
    con = built
    lines = _geo(con, "eez_lines")
    assert lines["101"][1]["outer"] is True and lines["102"][1]["outer"] is False
    assert lines["102"][2] == ["AUS", "NZL"]
    air = _geo(con, "airspace")
    assert air["fir:NZZO"][0] == "Auckland Radio" and air["fir:NZZO"][3] == 2
    nz = air["country:NZL"]
    assert nz[3] == 1 and nz[0].endswith("airspace") and {"Auckland Radio", "Auckland Radio - Tasman"} <= set(nz[1]["firs"])
    assert json.loads(con.execute("SELECT geojson FROM geo_features WHERE feature_id = 'country:AUS'").fetchone()[0])["type"] in (
        "Polygon", "MultiPolygon")
    v = con.execute("SELECT value FROM series WHERE indicator_id = 'eez_area_km2' AND entity_id = 'NZL'").fetchone()
    assert v and v[0] == 4083744 + 319031
