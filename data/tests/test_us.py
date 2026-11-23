"""US states and counties: each reader on small fixtures made in the test, then one build."""

import io
import json
import zipfile

import duckdb
import pytest
from worldmodel_contract import catalogue
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.us import acs_value, fips5, fips_of
from worldmodel_data.vintage_store import VintageStore

PEP_2020 = """SUMLEV,REGION,DIVISION,STATE,COUNTY,STNAME,CTYNAME,CENSUS2010POP,POPESTIMATE2019,POPESTIMATE2020,BIRTHS2020,DEATHS2020,DOMESTICMIG2020,INTERNATIONALMIG2020
040,4,9,06,000,California,California,37253956,39437463,39368078,420000,300000,-200000,40000
050,4,9,06,037,California,Los Angeles County,9818605,10039107,9989165,105000,70000,-110000,20000
050,4,8,35,013,New Mexico,Do\xf1a Ana County,209233,218195,219561,2800,1800,500,100
"""
PEP_2024 = """SUMLEV,REGION,DIVISION,STATE,COUNTY,STNAME,CTYNAME,ESTIMATESBASE2020,POPESTIMATE2020,POPESTIMATE2024,BIRTHS2024
040,4,9,06,000,California,California,39538223,39503200,39431263,405000
050,4,9,06,037,California,Los Angeles County,10014009,10000000,9757179,99000
"""
ACS_STATE = [["NAME", "B19013_001E", "B17001_002E", "B17001_001E", "B19083_001E", "B16001_002E", "B16001_001E", "state"],
             ["California", "91905", "4700000", "38600000", "0.4900", "20000000", "37000000", "06"]]
ACS_COUNTY = [["NAME", "B19013_001E", "B25077_001E", "state", "county"],
              ["Los Angeles County, California", "83411", "-666666666", "06", "037"]]
BEA_SAGDP1 = """GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,2022,2023
 "00000","United States", ,SAGDP1,1,"...","Real GDP (millions of chained 2017 dollars) ","Millions of chained 2017 dollars",21822037,22376904
 "06000","California",8,SAGDP1,1,"...","Real GDP (millions of chained 2017 dollars) ","Millions of chained 2017 dollars",3192385,3292339
 "06000","California",8,SAGDP1,3,"...","Current-dollar GDP (millions of current dollars) ","Millions of current dollars",3641643,3870379
"""
BEA_CAGDP1 = """GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,2022,2023
 "06037","Los Angeles, CA",8,CAGDP1,3,"...","Current-dollar GDP (thousands of current dollars) ","Thousands of dollars",942000000,(NA)
"""
BEA_RPP = """GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,2023
 "06000","California",8,SARPP,1,"...","RPPs: All items ","Index",112.6
"""
FRED_UR = ("observation_date,CAUR,NMUR\n" + "".join(f"2023-{m:02d}-01,{4.0 + (m % 2) * 0.2:.1f},4.0\n" for m in range(1, 13))
           + "2024-01-01,5.0,4.1\n")
FHFA_STATE = "CA,1999,1,90.0\nCA,1999,2,90.0\nCA,1999,3,90.0\nCA,1999,4,90.0\n" + "".join(f"CA,2000,{q},100.0\n" for q in range(1, 5)) \
    + "".join(f"CA,2001,{q},110.0\n" for q in range(1, 5))
CHR = ("State FIPS Code,County FIPS Code,5-digit FIPS Code,State Abbreviation,Name,Release Year,Premature Death raw value,"
       "Life Expectancy raw value,Uninsured raw value\n"
       "statecode,countycode,fipscode,state,county,year,v001_rawvalue,v147_rawvalue,v085_rawvalue\n"
       "00,000,00000,US,United States,2025,8351.7,77.6,0.084\n"
       "06,000,06000,CA,California,2025,6500.2,80.4,0.075\n"
       "06,037,06037,CA,Los Angeles County,2025,6100.0,81.0,0.09\n")
PRES = ('year,state,state_po,state_fips,state_cen,state_ic,office,candidate,party_detailed,writein,candidatevotes,totalvotes,version,notes,party_simplified\n'
        '2020,CALIFORNIA,CA,6,93,71,US PRESIDENT,"BIDEN, JOSEPH R. JR",DEMOCRAT,False,11110250,17500881,1,,DEMOCRAT\n'
        '2020,CALIFORNIA,CA,6,93,71,US PRESIDENT,"TRUMP, DONALD J.",REPUBLICAN,False,6006429,17500881,1,,REPUBLICAN\n'
        '2020,CALIFORNIA,CA,6,93,71,US PRESIDENT,OTHER,LIBERTARIAN,False,384202,17500881,1,,LIBERTARIAN\n')
COUNTY_PRES = ("year\tstate\tstate_po\tcounty_name\tcounty_fips\toffice\tcandidate\tparty\tcandidatevotes\ttotalvotes\tversion\tmode\n"
               "2020\tCALIFORNIA\tCA\tLOS ANGELES\t6037\tUS PRESIDENT\tJOSEPH R BIDEN JR\tDEMOCRAT\t2000000\t4000000\t1\tELECTION DAY\n"
               "2020\tCALIFORNIA\tCA\tLOS ANGELES\t6037\tUS PRESIDENT\tJOSEPH R BIDEN JR\tDEMOCRAT\t1000000\t4000000\t1\tMAIL\n"
               "2020\tCALIFORNIA\tCA\tLOS ANGELES\t6037\tUS PRESIDENT\tDONALD J TRUMP\tREPUBLICAN\t1000000\t4000000\t1\tTOTAL\n")
SEDS = {"response": {"total": 3, "data": [
    {"period": "2022", "seriesId": "TETCB", "stateId": "CA", "value": "7000000"},
    {"period": "2022", "seriesId": "TETPB", "stateId": "CA", "value": "180"},
    {"period": "2022", "seriesId": "TETCB", "stateId": "US", "value": "100000000"}]}}


def test_codes():
    assert fips_of("6") == "06" and fips_of("6", "37") == "06037" and fips_of("06", "000") == "06"
    assert fips5(' "06000"') == "06" and fips5("6037") == "06037" and fips5("00000") is None and fips5("72001") is None
    assert acs_value("share", [5.0, 20.0]) == 25.0 and acs_value("rest", [75.0, 100.0]) == 25.0
    assert acs_value("v", [-666666666.0]) is None


def test_catalogue_places():
    ents, subs = catalogue.entities(), {s["entity_id"]: s for s in catalogue.subdivisions()}
    assert ents["US-CA"].short_name == "California" and ents["US-06037"].short_name == "Los Angeles County, CA"
    assert subs["US-CA"]["parent_id"] == "USA" and subs["US-06037"]["parent_id"] == "US-CA"
    states = [k for k, s in subs.items() if s["parent_id"] == "USA"]
    assert len(states) == 51
    assert sum(1 for s in subs.values() if s["level"] == "county") > 3100


def _shp_zip(path, records):
    """A tiny Census-style shapefile zip: STATEFP/COUNTYFP and a square each."""
    import shapefile

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    w.field("STATEFP", "C", 2)
    w.field("COUNTYFP", "C", 3)
    for st, co, (x, y) in records:
        w.poly([[[x, y], [x, y + 1], [x + 1, y + 1], [x + 1, y], [x, y]]])
        w.record(st, co)
    w.close()
    with zipfile.ZipFile(path, "w") as z:
        for ext, b in (("shp", shp), ("shx", shx), ("dbf", dbf)):
            z.writestr(f"cb.{ext}", b.getvalue())


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("us")
    home = Paths(tmp / "var")
    store = VintageStore(home)

    def load(source, files):
        d = tmp / source
        d.mkdir()
        for name, body in files.items():
            if callable(body):
                body(d / name)
            elif isinstance(body, bytes):
                (d / name).write_bytes(body)
            else:
                (d / name).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        CONNECTORS[source]().ingest(store, d)

    load("us_census_pep", {"co-est2020-alldata.csv": PEP_2020.encode("latin-1"), "co-est2024-alldata.csv": PEP_2024})
    load("us_acs", {"acs5_2023_state.json": ACS_STATE, "acs5_2023_county.json": ACS_COUNTY})
    load("bea_regional", {"SAGDP1__ALL_AREAS_1997_2025.csv": BEA_SAGDP1, "CAGDP1__ALL_AREAS_2001_2024.csv": BEA_CAGDP1,
                          "SARPP_STATE_2008_2024.csv": BEA_RPP})
    load("us_unemployment", {"state_ur_01.csv": FRED_UR})
    load("fhfa_hpi", {"hpi_at_state.csv": FHFA_STATE})
    load("mit_elections", {"president_state.csv": PRES})
    load("mit_county_elections", {"countypres_2000-2024.tab": COUNTY_PRES})
    load("chr_health", {"analytic_data2025.csv": CHR})
    load("eia_seds", {"seds_01.json": SEDS})
    load("us_shapes", {"cb_us_state_5m.zip": lambda p: _shp_zip(p, [("06", "", (-120, 35))]),
                       "cb_us_county_5m.zip": lambda p: _shp_zip(p, [("06", "037", (-118.5, 34))])})
    nz = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"iso_3166_2": "NZ-AUK"},
         "geometry": {"type": "Polygon", "coordinates": [[[174, -37], [175, -37], [175, -36], [174, -36], [174, -37]]]}},
        {"type": "Feature", "properties": {"iso_3166_2": "NZ-X01~"},
         "geometry": {"type": "Polygon", "coordinates": [[[178, -30], [179, -30], [179, -29], [178, -30]]]}}]}
    load("ne_admin1", {"ne_10m_admin_1_states_provinces.geojson": nz})
    return duckdb.connect(str(build(home).path), read_only=True)


def val(con, ind, ent, year):
    r = con.execute("SELECT value FROM series WHERE indicator_id = ? AND entity_id = ? AND year(period_start) = ? AND freq = 'A'",
                    [ind, ent, year]).fetchone()
    return r[0] if r else None


def test_population(con):
    assert val(con, "usreg_population", "US-CA", 2024) == 39431263
    assert val(con, "usreg_population", "US-CA", 2020) == 39503200  # the later file's 2020 replaces the earlier one
    assert val(con, "usreg_population", "US-06037", 2019) == 10039107
    assert val(con, "usreg_population", "US-35013", 2020) == 219561  # Doña Ana, read from a Latin-1 file
    assert val(con, "usreg_births", "US-06037", 2024) == 99000
    assert val(con, "usreg_domestic_migration", "US-CA", 2020) == -200000
    assert val(con, "population", "US-CA", 2024) is None  # region figures stay apart from country figures


def test_acs_bea_jobs_prices(con):
    assert val(con, "usreg_median_household_income", "US-CA", 2023) == 91905
    assert round(val(con, "usreg_poverty_rate", "US-CA", 2023), 2) == round(100 * 4.7 / 38.6, 2)
    assert round(val(con, "usreg_other_language_share", "US-CA", 2023), 1) == 45.9
    assert val(con, "usreg_median_household_income", "US-06037", 2023) == 83411
    assert val(con, "usreg_median_home_value", "US-06037", 2023) is None  # Census's "not available" code
    assert val(con, "usreg_real_gdp", "US-CA", 2023) == 3292339 and val(con, "usreg_gdp", "US-CA", 2022) == 3641643
    assert val(con, "usreg_gdp", "US-06037", 2022) == 942000 and val(con, "usreg_gdp", "US-06037", 2023) is None
    assert val(con, "usreg_price_level", "US-CA", 2023) == 112.6
    assert round(val(con, "usreg_unemployment_rate", "US-CA", 2023), 2) == 4.1
    assert val(con, "usreg_unemployment_rate", "US-CA", 2024) is None  # one month is not a year
    assert val(con, "usreg_house_prices", "US-CA", 2001) == pytest.approx(110.0)
    assert val(con, "usreg_house_price_change", "US-CA", 2000) == pytest.approx(100 * (100 / 90 - 1))


def test_votes_health_energy(con):
    assert round(val(con, "usreg_pres_dem_share", "US-CA", 2020), 1) == 63.5
    assert val(con, "usreg_pres_votes", "US-CA", 2020) == 17500881
    # county modes: TOTAL rows win where a county has them, else the modes add up
    assert val(con, "usreg_pres_rep_share", "US-06037", 2020) == pytest.approx(100 * 1 / 4)
    assert val(con, "usreg_life_expectancy", "US-CA", 2025) == 80.4
    assert val(con, "usreg_uninsured", "US-06037", 2025) == pytest.approx(9.0)
    assert val(con, "usreg_energy_use", "US-CA", 2022) == pytest.approx(7000000 * 1.055056e-3)
    assert val(con, "usreg_energy_use_per_person", "US-CA", 2022) == pytest.approx(180 * 1.055056)


def test_region_outlines(con):
    got = con.execute("SELECT feature_id, countries, json_extract_string(props, '$.level'), json_extract_string(props, '$.parent') "
                      "FROM geo_features WHERE layer_id = 'regions' ORDER BY 1").fetchall()
    assert got == [("NZ-AUK", "NZL", "region", "NZL"), ("US-06037", "USA", "county", "US-CA"), ("US-CA", "USA", "state", "USA")]


def test_downloads(tmp_path):
    """BEA zips are cut to the tables read; County Health Rankings files are found on its page; MIT's file through Dataverse."""
    import httpx

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("SARPP_STATE_2008_2024.csv", BEA_RPP)
        z.writestr("SAIRPD_STATE_2008_2024.csv", "not read")
    page = ('<a href="/sites/default/files/media/document/analytic_data2025_v3.csv">2025</a>'
            '<a href="https://www.countyhealthrankings.org/sites/default/files/media/document/analytic_data2024.csv">2024</a>')
    listing = {"data": {"latestVersion": {"files": [{"label": "1976-2024-president.csv", "dataFile": {"id": 99}}]}}}

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "SARPP.zip" in u:
            return httpx.Response(200, content=zbuf.getvalue())
        if "apps.bea.gov" in u:
            return httpx.Response(404)
        if "data-documentation" in u:
            return httpx.Response(200, text=page)
        if "analytic_data" in u:
            return httpx.Response(200, text=CHR)
        if "datasets/:persistentId" in u:
            return httpx.Response(200, json=listing)
        if "datafile/99" in u:
            return httpx.Response(200, text=PRES)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    for source, want in (("bea_regional", ["SARPP_STATE_2008_2024.csv"]),
                         ("chr_health", ["analytic_data2024.csv", "analytic_data2025.csv"]),
                         ("mit_elections", ["president_state.csv"])):
        d = tmp_path / source
        d.mkdir()
        CONNECTORS[source](client=client).download(d, "2026-11-23")
        assert sorted(p.name for p in d.iterdir()) == want
