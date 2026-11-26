"""More hospital lists: OpenStreetMap (healthsites.io), Overture, official lists and your own,
the official counts, and the build merging them with Wikidata's into one Hospitals layer with
each hospital once."""

import csv
import json
import zipfile
from pathlib import Path

import duckdb
import pytest

from worldmodel_data import hospitals
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.health import country_boxes, osm_hospital_rows
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


def _csv(path: Path, rows: list[dict], delimiter: str = ",") -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=delimiter)
        w.writeheader()
        w.writerows(rows)


def osm_files(d: Path) -> Path:
    d.mkdir()
    base = {k: "" for k in ("X", "Y", "osm_id", "osm_type", "completeness", "amenity", "healthcare", "name", "operator", "beds",
                            "operator_type", "emergency")}
    _csv(d / "NZL.csv", [
        base | {"X": "174.7702", "Y": "-36.8602", "osm_id": '"11"', "osm_type": "way", "amenity": "hospital",
                "healthcare": "hospital", "name": "Auckland City Hospital", "beds": "1000"},  # Wikidata has it too
        base | {"X": "174.81", "Y": "-36.90", "osm_id": '"12"', "osm_type": "node", "amenity": "hospital", "name": ""},
        base | {"X": "174.70", "Y": "-36.80", "osm_id": '"13"', "osm_type": "node", "amenity": "pharmacy", "name": "Chemist"}])
    _csv(d / "CHN.csv", [base | {"X": "113.26", "Y": "23.13", "osm_id": '"21"', "amenity": "hospital", "healthcare": "hospital",
                                 "name": "广东省人民医院"}])
    return d


def overture_files(d: Path) -> Path:
    d.mkdir()
    _csv(d / "overture_hospitals.csv", [
        {"name": "Guangdong Provincial People's Hospital 广东省人民医院", "lat": "23.1302", "lon": "113.2601", "confidence": "0.9"},
        {"name": "Apollo Hospital", "lat": "13.06", "lon": "80.25", "confidence": "0.95"}])
    (d / "overture_release.txt").write_text("2026-11-18.0\nIND,CHN\n", encoding="utf-8")
    return d


def national_files(d: Path) -> Path:
    d.mkdir()
    cnes = d / "cnes.csv"
    _csv(cnes, [
        {"CO_CNES": "1", "TP_UNIDADE": "5", "NO_FANTASIA": "HOSPITAL DAS CLINICAS", "NO_RAZAO_SOCIAL": "", "NU_LATITUDE": "-23.557",
         "NU_LONGITUDE": "-46.669", "CO_MOTIVO_DESAB": ""},
        {"CO_CNES": "2", "TP_UNIDADE": "2", "NO_FANTASIA": "POSTO", "NO_RAZAO_SOCIAL": "", "NU_LATITUDE": "-23.5",
         "NU_LONGITUDE": "-46.6", "CO_MOTIVO_DESAB": ""},
        {"CO_CNES": "3", "TP_UNIDADE": "7", "NO_FANTASIA": "FECHADO", "NO_RAZAO_SOCIAL": "", "NU_LATITUDE": "-23.4",
         "NU_LONGITUDE": "-46.5", "CO_MOTIVO_DESAB": "01"}], delimiter=";")
    with zipfile.ZipFile(d / "cnes_estabelecimentos.zip", "w") as z:
        z.write(cnes, "cnes_estabelecimentos.csv")
    cnes.unlink()
    _csv(d / "CHN guangdong top hospitals.csv", [{"Name": "中山大学附属第一医院", "Latitude": "23.13", "Longitude": "113.29", "Beds": "3000"}])
    return d


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("h")
    home = Paths(tmp / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "wikidata_places"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    CONNECTORS["healthsites_osm"]().ingest(store, osm_files(tmp / "osm"))
    CONNECTORS["overture_hospitals"]().ingest(store, overture_files(tmp / "ov"))
    CONNECTORS["national_hospitals"]().ingest(store, national_files(tmp / "nat"))
    counts = tmp / "counts"
    counts.mkdir()
    (counts / "who_devices00.json").write_text(json.dumps({"value": [
        {"SpatialDimType": "COUNTRY", "SpatialDim": "NZL", "TimeDim": 2013, "NumericValue": 1.9}]}), encoding="utf-8")
    CONNECTORS["hospital_counts"]().ingest(store, counts)
    result = build(home)
    con = duckdb.connect(str(result.path), read_only=True)
    HOMES[id(con)] = (home, tmp)
    return con


HOMES: dict[int, tuple[Paths, Path]] = {}


def _hospitals(con) -> list[dict]:
    got = con.execute("SELECT geojson FROM layers WHERE layer_id = 'hospitals'").fetchone()
    return [f["properties"] | {"xy": f["geometry"]["coordinates"]} for f in json.loads(got[0])["features"]]


def test_one_layer_with_each_hospital_once(built):
    h = _hospitals(built)
    auck = [x for x in h if x["name"] == "Auckland City Hospital"]
    assert len(auck) == 1 and auck[0]["beds"] == 1100  # the largest figure any list gives
    assert auck[0]["found"] == "Wikidata + OpenStreetMap"
    canton = [x for x in h if "广东省人民医院" in x["name"]]
    assert len(canton) == 1 and canton[0]["found"] == "OpenStreetMap + Overture"
    assert any(x["name"] == "Hospital (no name given)" for x in h)
    assert not any(x["name"] in ("Chemist", "Posto", "Fechado") for x in h)
    assert any(x["name"] == "Hospital Das Clinicas" and x["found"] == "Official lists" for x in h)
    own = next(x for x in h if x["name"] == "中山大学附属第一医院")
    assert own["beds"] == 3000 and own["country"] == "CHN"
    assert built.execute("SELECT count(*) FROM layers WHERE layer_id LIKE 'hospitals_%'").fetchone()[0] == 0


def test_layer_items_by_list_and_official_counts(built):
    cats = dict(built.execute("SELECT category, count(*) FROM layer_items WHERE layer_id = 'hospitals' GROUP BY 1").fetchall())
    assert cats.get("Wikidata + OpenStreetMap") == 1
    got = dict(built.execute("""SELECT indicator_id, value FROM series WHERE entity_id IN ('CHN', 'NZL')
                                AND indicator_id IN ('hospitals_official', 'who_hospitals_per_100k')""").fetchall())
    assert got.get("hospitals_official") == 38355 and got.get("who_hospitals_per_100k") == 1.9


def test_osm_rows_and_names():
    assert hospitals.similar("Auckland City Hospital", "Auckland Hospital")
    assert not hospitals.similar("Starship Children's Hospital", "Middlemore Hospital")
    assert hospitals.similar("广东省人民医院", "Guangdong Provincial People's Hospital 广东省人民医院")


def test_merge_keeps_close_but_different_hospitals_apart():
    f = lambda name, lon, lat, **p: {"geometry": {"coordinates": [lon, lat]}, "properties": {"name": name, **p}}  # noqa: E731
    got = hospitals.merge({"wikidata": [f("Starship Children's Hospital", 174.7700, -36.8600)],
                           "osm": [f("Auckland City Hospital", 174.7710, -36.8600),  # ~90 m away, other name: kept apart
                                   f("Starship Hospital", 174.7701, -36.8600)]})  # same one
    assert [x["properties"]["name"] for x in got] == ["Starship Children's Hospital", "Auckland City Hospital"]
    assert got[0]["properties"]["found"] == "Wikidata + OpenStreetMap"


def test_country_boxes_split_across_the_date_line(tmp_path):
    p = tmp_path / "c.geojson"
    p.write_text(json.dumps({"features": [{"properties": {"ISO_A3": "FJI"}, "geometry": {"type": "MultiPolygon", "coordinates": [
        [[[177, -18], [179.9, -18], [179.9, -16], [177, -16], [177, -18]]],
        [[[-180, -17], [-179, -17], [-179, -16], [-180, -16], [-180, -17]]]]}}]}), encoding="utf-8")
    boxes = country_boxes(p, {"FJI"})["FJI"]
    assert len(boxes) == 2 and all(b[2] - b[0] < 5 for b in boxes)


def test_osm_file_keeps_hospitals_only(tmp_path):
    rows = osm_hospital_rows(osm_files(tmp_path / "o") / "NZL.csv")
    assert len(rows) == 2 and rows[0]["url"] == "https://www.openstreetmap.org/way/11" and rows[0]["beds"] == "1000"


def test_likely_hospital_or_clinic(built):
    h = {x["name"]: x for x in _hospitals(built)}
    assert h["Auckland City Hospital"]["tier"] == "hospital"
    assert h["Hospital (no name given)"]["tier"] == "unsure"  # only OpenStreetMap, nothing else to go on
    assert h["Hospital Das Clinicas"]["tier"] == "hospital" and h["Hospital Das Clinicas"]["kind"] == "general hospital"
    tiers = dict(built.execute("""SELECT name, json_extract_string(props, '$.tier') FROM layer_items
                                  WHERE layer_id = 'hospitals'""").fetchall())
    assert tiers["Auckland City Hospital"] == "hospital"


def test_tier_rules():
    t = lambda name, found="Overture", **p: hospitals.tier({"name": name, "found": found, **p})  # noqa: E731
    assert t("Pediatric Clinic LBJ") == "clinic" and t("Hope Dialysis Center") == "clinic"
    assert t("绿园西新开元周成卫生所", "OpenStreetMap") == "clinic" and t("三亚市人民医院") == "hospital"
    assert t("Infection Prevention Office, Lbj Hospital") == "clinic"
    assert t("Small Clinic", beds=120) == "hospital" and t("Riverside Hospital", beds=8) == "clinic"
    assert t("Hospital (no name given)", "OpenStreetMap") == "unsure"
    assert t("Hospital (no name given)", "OpenStreetMap", emergency="yes") == "hospital"
    assert t("Unit 4", "Official lists", kind="day hospital") == "clinic"


def _reused(result) -> str:
    return next((c.detail for c in result.checks if c.check_id == "build:reused"), "")


def test_second_build_reuses_unchanged_steps(built):
    home, tmp = HOMES[id(built)]
    first = sorted(json.dumps(x, sort_keys=True) for x in _hospitals(built))
    items = built.execute("SELECT count(*), sum(hash(l)) FROM layer_items l").fetchone()
    again = build(home)
    assert "hospitals" in _reused(again) and "layer_items" in _reused(again)
    con = duckdb.connect(str(again.path), read_only=True)
    try:
        assert sorted(json.dumps(x, sort_keys=True) for x in _hospitals(con)) == first
        assert con.execute("SELECT count(*), sum(hash(l)) FROM layer_items l").fetchone() == items
    finally:
        con.close()
    # A changed list: the merge is done again, and only the hospitals layer's dots are placed again.
    d = tmp / "osm2"
    osm_files(d)
    with (d / "AUS.csv").open("w", encoding="utf-8") as fh:
        fh.write("X,Y,osm_id,osm_type,completeness,amenity,healthcare,name,operator,beds,operator_type,emergency\n"
                 '151.2,-33.9,"31",node,,hospital,hospital,Sydney Hospital,,,,\n')
    CONNECTORS["healthsites_osm"]().ingest(VintageStore(home), d)
    third = build(home)
    assert "hospitals" not in _reused(third).replace("layer_items", "")
    con = duckdb.connect(str(third.path), read_only=True)
    try:
        assert any(x["name"] == "Sydney Hospital" for x in _hospitals(con))
        assert con.execute("SELECT count(*) FROM layer_items WHERE layer_id = 'hospitals' AND name = 'Sydney Hospital'").fetchone()[0] == 1
    finally:
        con.close()


def test_reuse_switched_off_works_everything_out(built):
    home, _ = HOMES[id(built)]
    assert _reused(build(home, reuse=False)) == ""
