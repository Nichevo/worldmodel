"""Time zone outlines (timezone-boundary-builder), staged from a small hand-made fixture."""

import json
import zipfile
from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.timezones import read_features, zone_rows
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures" / "tz_boundaries"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source, folder in (("un_wpp", FIXTURES.parent / "un_wpp"), ("tz_boundaries", FIXTURES)):
        CONNECTORS[source]().ingest(store, folder)
    result = build(home)
    return duckdb.connect(str(result.path), read_only=True)


def test_rows_named_by_zone_and_simplified():
    rows = zone_rows(read_features(FIXTURES / "timezones-with-oceans-now.geojson"))
    by = {r[1]: r for r in rows}
    assert set(by) == {"Pacific/Auckland", "Australia/Sydney", "Asia/Kolkata", "Etc/GMT+12"}  # no name: left out
    assert by["Etc/GMT+12"][4]["sea"] is True and by["Pacific/Auckland"][4]["sea"] is False
    nz = by["Pacific/Auckland"][6]
    assert nz["type"] == "Polygon" and len(nz["coordinates"][0]) < 20  # the wiggly edge smoothed
    assert by["Asia/Kolkata"][6]["type"] == "MultiPolygon"


def test_reads_the_zip(tmp_path):
    z = tmp_path / "timezones-with-oceans-now.geojson.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(FIXTURES / "timezones-with-oceans-now.geojson", "combined-with-oceans-now.json")
    assert len(read_features(z)) == 5


def test_layer_in_warehouse(built):
    got = dict(built.execute("SELECT feature_id, props FROM geo_features WHERE layer_id = 'timezones'").fetchall())
    assert len(got) == 4 and json.loads(got["Pacific/Auckland"])["tz"] == "Pacific/Auckland"
