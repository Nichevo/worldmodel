"""Flu, COVID, RSV, measles and other infections: every source read from small files shaped like
the real ones (OpenDengue, ECDC and New Zealand's wastewater files are cut from the real ones;
the rest are made up in the shape each API returns), then built into a warehouse."""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.disease import (
    don_events,
    flunet_rows,
    mmwr_monday,
    mmwr_start,
    nhsn_rows,
    nndss_rows,
    stmf_rows,
    stmf_text,
    ukhsa_rows,
)
from worldmodel_data.vintage_store import VintageStore

FIX = Path(__file__).parent / "fixtures" / "disease"

FLUNET = """COUNTRY_CODE,ISO_WEEKSTARTDATE,ORIGIN_SOURCE,SPEC_PROCESSED_NB,INF_A,INF_B,INF_ALL,INF_NEGATIVE,AH1N12009,AH3,BVIC_NODEL,BVIC_2DEL,BVIC_3DEL,BVIC_DELUNK,BYAM,RSV,RSV_PROCESSED
NZL,2025-07-07,SENTINEL,109,21,19,40,,6,1,,,,,,33,
NZL,2025-07-07,NONSENTINEL,900,200,50,250,,30,100,,,,,,80,600
NZL,2025-07-14,SENTINEL,5,1,0,1,,,,,,,,,,
X09,2025-01-06,SENTINEL,400,100,0,100,,60,40,,,,,,20,400
X10,2025-01-06,SENTINEL,100,20,0,20,,10,10,,,,,,5,100
AFG,2024-01-15,NONSENTINEL,28,13,0,13,15,0,13,0,,,,0,0,
AFG,2024-01-22,NONSENTINEL,,13,2,,15,0,13,0,,,,0,,
"""


def test_mmwr_weeks():
    assert mmwr_start(2025, 1) == date(2024, 12, 29)  # the Sunday of the week holding 4 January
    assert mmwr_monday(2025, 1) == date(2024, 12, 30) and mmwr_monday(2026, 1) == date(2026, 1, 5)


def test_flunet_adds_labs_and_uk_nations():
    rows = {(r[1], r[2], r[3]): r[6] for r in flunet_rows(FLUNET).rows}
    d = date(2025, 7, 7)
    assert rows[("NZL", "flu_tests", d)] == 1009 and rows[("NZL", "flu_positive", d)] == 290
    assert rows[("NZL", "flu_pct_positive", d)] == pytest.approx(100 * 290 / 1009)
    assert rows[("NZL", "rsv_positive", d)] == 113
    assert rows[("NZL", "rsv_pct_positive", d)] == pytest.approx(100 * 80 / 600)  # only labs that say how many they tested
    assert ("NZL", "flu_pct_positive", date(2025, 7, 14)) not in rows  # fewer than 10 tests
    assert rows[("GBR", "flu_tests", date(2025, 1, 6))] == 500 and rows[("GBR", "flu_a_h1n1_positive", date(2025, 1, 6))] == 70
    assert rows[("AFG", "flu_tests", date(2024, 1, 22))] == 30  # positives (A + B) plus negatives when tests are blank


def test_ukhsa_keeps_all_ages_and_averages_daily_figures():
    pages = {
        "influenza_healthcare_hospitalAdmissionRateByWeek": [
            {"date": "2025-12-01", "age": "all", "sex": "all", "stratum": "default", "metric_value": 12.5},
            {"date": "2025-12-01", "age": "00-04", "sex": "all", "stratum": "default", "metric_value": 40}],
        "COVID-19_testing_positivity7DayRolling": [
            {"date": "2025-12-01", "age": "all", "sex": "all", "stratum": "default", "metric_value": 6},
            {"date": "2025-12-03", "age": "all", "sex": "all", "stratum": "default", "metric_value": 8}],
        "measles_cases_casesByOnsetWeek": [{"date": "2025-12-01", "age": "all", "metric_value": 4}],
    }
    rows = {(r[2], r[3]): r[6] for r in ukhsa_rows(pages).rows}
    assert rows[("flu_admissions_per_100k", date(2025, 12, 1))] == 12.5
    assert rows[("covid_pct_positive", date(2025, 12, 1))] == 7
    assert rows[("measles_cases_weekly", date(2025, 12, 1))] == 4


def test_nhsn_and_nndss():
    nhsn = ("weekendingdate,jurisdiction,totalconfflunewadmper100k,totalconfc19newadmper100k,totalconfrsvnewadmper100k\n"
            "2025-12-06T00:00:00.000,USA,5.1,2.2,1.3\n2025-12-06T00:00:00.000,CA,4,,1\n2025-12-06T00:00:00.000,Region 1,9,9,9\n")
    rows = {(r[1], r[2]): r[6] for r in nhsn_rows(nhsn).rows}
    assert rows[("USA", "flu_admissions_per_100k")] == 5.1 and rows[("US-CA", "rsv_admissions_per_100k")] == 1
    assert ("US-CA", "covid_admissions_per_100k") not in rows and len(rows) == 5
    assert {r[3] for r in nhsn_rows(nhsn).rows} == {date(2025, 12, 1)}  # Saturday week end -> that week's Monday
    nndss = ("states,year,week,label,m1\nTotal,2025,10,\"Measles, Indigenous\",20\nTotal,2025,10,\"Measles, Imported\",3\n"
             "California,2025,10,Pertussis,9\nTotal,2025,10,Pertussis,186\n")
    rows = {(r[2], r[3]): r[6] for r in nndss_rows(nndss).rows}
    assert rows == {("measles_cases_weekly", mmwr_monday(2025, 10)): 23, ("pertussis_cases_weekly", mmwr_monday(2025, 10)): 186}


def test_stmf_adds_up_the_uk():
    text = ("CountryCode,Year,Week,Sex,D0_14,D15_64,D65_74,D75_84,D85p,DTotal,R0_14,R15_64,R65_74,R75_84,R85p,RTotal,Split,SplitSex,Forecast\n"
            "NZL_NP,2024,27,b,1,2,3,4,5,700,0,0,0,0,0,0.0072,0,0,0\nNZL_NP,2024,27,m,1,2,3,4,5,360,0,0,0,0,0,0.007,0,0,0\n"
            "GBRTENW,2024,27,b,0,0,0,0,0,9000,0,0,0,0,0,0.0095,0,0,0\nGBR_SCO,2024,27,b,0,0,0,0,0,1100,0,0,0,0,0,0.01,0,0,0\n"
            "GBR_NIR,2024,27,b,0,0,0,0,0,300,0,0,0,0,0,0.009,0,0,0\n")
    rows = {(r[1], r[2]): r[6] for r in stmf_rows(text).rows}
    assert rows[("NZL", "deaths_weekly")] == 700 and rows[("NZL", "death_rate_weekly")] == pytest.approx(7.2)
    assert rows[("GBR", "deaths_weekly")] == 10400


def test_outbreak_news_names_countries():
    items = [{"Title": "Cholera - Angola", "PublicationDate": "2025-02-01T10:00:00Z", "UrlName": "2025-DON555", "DonId": "2025-DON555",
              "Summary": "<p>As of 26 January,&nbsp;1 234 cases.</p>"},
             {"Title": "Mpox – Uganda and Kenya", "PublicationDate": "2024-08-01T10:00:00Z", "UrlName": "2024-DON1"},
             {"Title": "Avian influenza A(H5N1) - Multi-country", "PublicationDate": "2024-05-01T10:00:00Z", "UrlName": "x"}]
    rows, unmatched = don_events(items)
    assert [(r[0], r[3], r[5]) for r in rows] == [("AGO", "cholera", date(2025, 2, 1)), ("UGA", "mpox", date(2024, 8, 1)),
                                                 ("KEN", "mpox", date(2024, 8, 1))]
    assert rows[0][15] == "As of 26 January, 1 234 cases." and rows[0][14].endswith("/2025-DON555")
    assert unmatched == {"Multi-country"}


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("disease")
    home = Paths(tmp / "var")
    store = VintageStore(home)

    def folder(name: str, files: dict[str, str]) -> Path:
        d = tmp / name
        d.mkdir()
        for f, text in files.items():
            (d / f).write_text(text, encoding="utf-8")
        return d

    CONNECTORS["who_flunet"]().ingest(store, folder("flunet", {"flunet_2025.csv": FLUNET}))
    CONNECTORS["nz_wastewater"]().ingest(store, FIX / "nz_wastewater")
    CONNECTORS["ecdc_erviss"]().ingest(store, FIX / "ILIARIRates.csv")
    CONNECTORS["opendengue"]().ingest(store, FIX / "opendengue.csv")
    gho = {"value": [{"SpatialDimType": "COUNTRY", "SpatialDim": "NZL", "TimeDim": 2025, "NumericValue": 58, "Dim1": None},
                     {"SpatialDimType": "COUNTRY", "SpatialDim": "NZL", "TimeDim": 2019, "NumericValue": 2193, "Dim1": None},
                     {"SpatialDimType": "REGION", "SpatialDim": "WPR", "TimeDim": 2025, "NumericValue": 9999, "Dim1": None}]}
    CONNECTORS["who_gho_disease"]().ingest(store, folder("gho", {"WHS3_62.json": json.dumps(gho)}))
    fluview = {"epidata": [{"region": "nat", "epiweek": 202550, "wili": 3.2, "ili": 3.0},
                           {"region": "ca", "epiweek": 202550, "wili": None, "ili": 2.5}]}
    CONNECTORS["delphi_fluview"]().ingest(store, folder("fluview", {"fluview_nat.json": json.dumps(fluview)}))
    don = [{"Title": "Measles - New Zealand", "PublicationDate": "2025-10-20T00:00:00Z", "UrlName": "2025-DON600", "DonId": "2025-DON600"}]
    CONNECTORS["who_don"]().ingest(store, folder("don", {"don.json": json.dumps(don)}))
    return duckdb.connect(str(build(home).path), read_only=True)


def vals(con, ind, ent):
    return con.execute("SELECT period_start, freq, value FROM series WHERE indicator_id = ? AND entity_id = ? ORDER BY period_start",
                       [ind, ent]).fetchall()


def test_built(con):
    assert vals(con, "flu_positive", "NZL") == [(date(2025, 7, 7), "D", 290), (date(2025, 7, 14), "D", 1)]
    assert con.execute("SELECT frequency, domain FROM indicators WHERE indicator_id = 'flu_pct_positive'").fetchone() == ("W", "health")
    # wastewater: weeks ending Sunday 15 November start Monday 9 November
    assert vals(con, "covid_wastewater", "NZL")[-1] == (date(2026, 11, 9), "D", 2483992)
    assert vals(con, "covid_wastewater", "NZ-AUK")[-1][2] == 2193781
    layer = json.loads(con.execute("SELECT geojson FROM layers WHERE layer_id = 'nz_wastewater'").fetchone()[0])
    assert {f["properties"]["name"] for f in layer["features"]} == {"Auckland Central", "Wellington (Moa Point)"}
    assert vals(con, "ili_rate_per_100k", "IRL") == [(date(2026, 11, 2), "D", 14), (date(2026, 11, 9), "D", 11.2)]
    assert vals(con, "dengue_cases", "AUS")[-1] == (date(2025, 1, 1), "A", 205)  # months added up where no yearly figure
    assert vals(con, "dengue_cases", "AUS")[0] == (date(2013, 1, 1), "A", 1841)
    assert vals(con, "dengue_cases_weekly", "SGP")[0] == (date(2023, 12, 11), "D", 211)
    assert vals(con, "measles_cases", "NZL") == [(date(2019, 1, 1), "A", 2193), (date(2025, 1, 1), "A", 58)]
    assert vals(con, "ili_pct_visits", "USA") == [(mmwr_monday(2025, 50), "D", 3.2)]
    assert vals(con, "ili_pct_visits", "US-CA") == [(mmwr_monday(2025, 50), "D", 2.5)]
    ev = con.execute("SELECT kind, subkind, title FROM events WHERE source_id = 'who_don' AND entity_id = 'NZL'").fetchall()
    assert ev == [("epidemic", "measles", "Measles (WHO outbreak news)")]


def test_stmf_reads_the_zip_and_skips_input_files(tmp_path):
    import zipfile
    head = "CountryCode,Year,Week,Sex,D0_14,DTotal,RTotal\n"
    with zipfile.ZipFile(tmp_path / "STMF_all.zip", "w") as z:
        z.writestr("input/NZL_input.csv", "PopCode,Area,Year,Week,Sex,Age,Deaths\nNZL,1,2024,1,b,TOT,700\n")
        z.writestr("stmf.csv", "Short-term mortality fluctuations\n" + head + "NZL_NP,2024,1,b,5,700,0.0134\n")
    (tmp_path / "more.csv").write_text(head + "AUS,2024,1,b,9,3000,0.0115\n")
    text = stmf_text(tmp_path)
    assert text.count("CountryCode") == 1 and "PopCode" not in text
    ents = {r[1] for r in stmf_rows(text).rows}
    assert ents == {"NZL", "AUS"}
