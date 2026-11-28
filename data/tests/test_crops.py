"""Top crops: crop names shared by the sources, USDA NASS Quick Stats rows (API and site CSVs),
FAOSTAT's every-crop areas and Stats NZ horticulture by region, on small synthetic files."""

from datetime import date

import duckdb
import httpx
import pytest
from worldmodel_contract.crops import ACRE_HA, colour, fao_crop, name, nass_crop, nass_skip
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.crops import census_years, crop_acres, nass_records
from worldmodel_data.connectors.statsnz import read_table
from worldmodel_data.vintage_store import VintageStore

API_CSV = (
    '"source_desc","sector_desc","group_desc","commodity_desc","class_desc","prodn_practice_desc","util_practice_desc",'
    '"statisticcat_desc","unit_desc","short_desc","domain_desc","domaincat_desc","agg_level_desc","state_fips_code",'
    '"state_alpha","county_code","county_name","year","Value"\n'
    # Story County, Iowa: corn has no whole figure, so grain and silage add up; irrigated corn is a part, not more
    '"CENSUS","CROPS","FIELD CROPS","CORN","ALL CLASSES","ALL PRODUCTION PRACTICES","GRAIN","AREA HARVESTED","ACRES",'
    '"CORN, GRAIN - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","160,000"\n'
    '"CENSUS","CROPS","FIELD CROPS","CORN","ALL CLASSES","ALL PRODUCTION PRACTICES","SILAGE","AREA HARVESTED","ACRES",'
    '"CORN, SILAGE - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","2,000"\n'
    '"CENSUS","CROPS","FIELD CROPS","CORN","ALL CLASSES","IRRIGATED","GRAIN","AREA HARVESTED","ACRES",'
    '"CORN, GRAIN, IRRIGATED - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","500"\n'
    '"CENSUS","CROPS","FIELD CROPS","SOYBEANS","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","SOYBEANS - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","120,000"\n'
    # hay & haylage holds hay: the larger is kept, not the sum
    '"CENSUS","CROPS","FIELD CROPS","HAY","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","HAY - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","5,000"\n'
    '"CENSUS","CROPS","FIELD CROPS","HAY & HAYLAGE","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","HAY & HAYLAGE - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","6,000"\n'
    # withheld, totals, size classes and combined counties are left out
    '"CENSUS","CROPS","FIELD CROPS","OATS","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","OATS - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","(D)"\n'
    '"CENSUS","CROPS","CROP TOTALS","FIELD CROPS","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","FIELD CROPS - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","169","STORY","2022","300,000"\n'
    '"CENSUS","CROPS","FIELD CROPS","SOYBEANS","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","SOYBEANS - ACRES HARVESTED","AREA HARVESTED","AREA HARVESTED: (1.0 TO 24.9 ACRES)","COUNTY","19","IA","169","STORY","2022","900"\n'
    '"CENSUS","CROPS","FIELD CROPS","CORN","ALL CLASSES","ALL PRODUCTION PRACTICES","GRAIN","AREA HARVESTED","ACRES",'
    '"CORN, GRAIN - ACRES HARVESTED","TOTAL","NOT SPECIFIED","COUNTY","19","IA","998","OTHER (COMBINED) COUNTIES","2022","10"\n'
    # a state: wheat's whole figure wins over its classes
    '"CENSUS","CROPS","FIELD CROPS","WHEAT","ALL CLASSES","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","WHEAT - ACRES HARVESTED","TOTAL","NOT SPECIFIED","STATE","20","KS","","","2022","7,000,000"\n'
    '"CENSUS","CROPS","FIELD CROPS","WHEAT","WINTER","ALL PRODUCTION PRACTICES","ALL UTILIZATION PRACTICES",'
    '"AREA HARVESTED","ACRES","WHEAT, WINTER - ACRES HARVESTED","TOTAL","NOT SPECIFIED","STATE","20","KS","","","2022","6,900,000"\n'
)
# The Quick Stats site's own Spreadsheet CSV: other column names, orchards by bearing and non-bearing acres.
WEB_CSV = (
    '"Program","Year","Period","Week Ending","Geo Level","State","State ANSI","Ag District","Ag District Code","County",'
    '"County ANSI","Zip Code","Region","watershed_code","Watershed","Commodity","Data Item","Domain","Domain Category","Value","CV (%)"\n'
    '"CENSUS","2022","YEAR","","COUNTY","CALIFORNIA","06","SAN JOAQUIN VALLEY","51","FRESNO","019","","","00000000","",'
    '"ALMONDS","ALMONDS - ACRES BEARING & NON-BEARING","TOTAL","NOT SPECIFIED","250,000","1.2"\n'
    '"CENSUS","2022","YEAR","","COUNTY","CALIFORNIA","06","SAN JOAQUIN VALLEY","51","FRESNO","019","","","00000000","",'
    '"GRAPES","GRAPES - ACRES BEARING & NON-BEARING","TOTAL","NOT SPECIFIED","180,000","1.0"\n'
    '"CENSUS","2022","YEAR","","COUNTY","CALIFORNIA","06","SAN JOAQUIN VALLEY","51","FRESNO","019","","","00000000","",'
    '"COTTON","COTTON, UPLAND - ACRES HARVESTED","TOTAL","NOT SPECIFIED","20,000","3.0"\n'
    '"CENSUS","2022","YEAR","","COUNTY","CALIFORNIA","06","SAN JOAQUIN VALLEY","51","FRESNO","019","","","00000000","",'
    '"COTTON","COTTON, PIMA - ACRES HARVESTED","TOTAL","NOT SPECIFIED","30,000","3.0"\n'
)
HORT = ("STRUCTURE,STRUCTURE_ID,ACTION,AREA_AGR_002: Area,MEASURE_AGR_002: Horticulture,TIME_PERIOD: Year,OBS_VALUE\n"
        + "".join(f"DATAFLOW,STATSNZ:AGR_AGR_002(1.0),I,{code}: {reg},{m}: Total {crop} (hectares),2024,{v}\n"
                  for code, reg in (("01", "Northland Region"), ("02", "Auckland Region"), ("03", "Waikato Region"),
                                    ("04", "Bay of Plenty Region"), ("06", "Hawke's Bay Region"), ("08", "Manawatu-Wanganui Region"),
                                    ("13", "Canterbury Region"), ("14", "Otago Region"), ("18", "Marlborough Region"))
                  for m, crop, v in (("AP", "apples", 100 if code != "06" else 5000), ("KF", "kiwifruit", 3000 if code == "04" else 10),
                                     ("WG", "wine grapes", 28000 if code == "18" else 50))))


def test_names_and_colours():
    assert fao_crop("Maize (corn)") == "maize" and fao_crop("Lettuce and chicory") == "lettuce_and_chicory"
    assert nass_crop("HAY & HAYLAGE") == "hay" and nass_crop("CORN") == "maize" and nass_crop("ARTICHOKES") == "artichokes"
    assert nass_skip("FIELD CROPS") and nass_skip("VEGETABLE TOTALS") and nass_skip("ORCHARDS") and not nass_skip("SOYBEANS")
    assert name("maize") == "Maize (corn)" and name("lettuce_and_chicory") == "Lettuce and chicory"
    assert colour("maize") == "#e8478b" and colour("artichokes") == colour("artichokes") and colour("artichokes").startswith("#")
    assert census_years(date(2026, 11, 28)) == [2002, 2007, 2012, 2017, 2022]
    assert census_years(date(2029, 1, 10)) == [2002, 2007, 2012, 2017, 2022]  # the 2027 census is not out yet
    assert census_years(date(2029, 3, 1))[-1] == 2027


def test_nass_rows():
    acres = crop_acres(list(nass_records(API_CSV)) + list(nass_records(WEB_CSV)))
    assert acres[("19169", 2022, "maize")] == 162_000
    assert acres[("19169", 2022, "soybeans")] == 120_000
    assert acres[("19169", 2022, "hay")] == 6_000
    assert ("19169", 2022, "oats") not in acres and not any(k[2] == "field_crops" for k in acres)
    assert not any(k[0].endswith("998") for k in acres)
    assert acres[("20", 2022, "wheat")] == 7_000_000
    assert acres[("06019", 2022, "almonds")] == 250_000 and acres[("06019", 2022, "cotton")] == 50_000


def test_nz_horticulture():
    m = {"id": "nzreg_hort_wine_grapes_ha", "keep": {"*": "total wine grapes"}}
    got = read_table(HORT, m)
    assert got[("NZ-MBH", 2024)] == 28000 and got[("NZ-CAN", 2024)] == 50


def test_nass_download(tmp_path, monkeypatch):
    """One question per state and census for each kind of acreage; the key is sent but never kept."""
    asked = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.url)
        if req.url.params.get("state_alpha") == "IA" and req.url.params.get("statisticcat_desc") == "AREA HARVESTED":
            return httpx.Response(200, text=API_CSV)
        return httpx.Response(400, json={"error": ["no data for selected query"]})

    monkeypatch.setenv("NASS_API_KEY", "k")
    monkeypatch.setattr("worldmodel_data.connectors.crops.census_years", lambda: [2022])
    monkeypatch.setattr("worldmodel_data.connectors.crops.time.sleep", lambda s: None)
    c = CONNECTORS["usda_nass"](client=httpx.Client(transport=httpx.MockTransport(handler)))
    c.download(tmp_path, "r")
    assert len(asked) == 2 * 52 and all(u.params["key"] == "k" for u in asked)
    assert (tmp_path / "nass_2022_harvested_IA.csv").read_text().startswith('"source_desc"')
    assert "k" not in (tmp_path / "nass_2022_harvested_IA.csv").read_text().split("\n")[0]


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("crops")
    home = Paths(tmp / "var")
    store = VintageStore(home)
    d = tmp / "usda_nass"
    d.mkdir()
    (d / "nass_2022_harvested_IA.csv").write_text(API_CSV, encoding="utf-8")
    (d / "Quick Stats export.csv").write_text(WEB_CSV, encoding="utf-8")
    CONNECTORS["usda_nass"]().ingest(store, d)
    return duckdb.connect(str(build(home).path), read_only=True)


def test_nass_build(con):
    def val(ent, crop):
        r = con.execute("SELECT value FROM series WHERE indicator_id = 'usreg_crop_area_ha' AND entity_id = ? AND breakdown = ?",
                        [ent, f"crop={crop}"]).fetchone()
        return r and r[0]
    assert val("US-19169", "maize") == pytest.approx(162_000 * ACRE_HA)
    assert val("US-KS", "wheat") == pytest.approx(7_000_000 * ACRE_HA)
    assert val("US-06019", "almonds") == pytest.approx(250_000 * ACRE_HA)
