"""Markets (daily exchange rates, gas and oil storage, JODI stocks), BIS effective exchange
rates and the Stats NZ regions. All from small sample files."""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.statsnz import parse_flows, pick_flow, read_flows, region_of
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("ecb_fx", "fed_h10", "gie_agsi", "eia", "jodi", "statsnz", "bis")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("markets") / "var")
    store = VintageStore(home)
    for source in ("un_wpp",) + SOURCES:
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def value(con, entity, indicator, period, source=None, freq=None):
    sql = "SELECT value FROM series WHERE entity_id = ? AND indicator_id = ? AND period_start = ? AND breakdown = ''"
    params = [entity, indicator, period]
    if source:
        sql += " AND source_id = ?"
        params.append(source)
    if freq:
        sql += " AND freq = ?"
        params.append(freq)
    r = con.execute(sql, params).fetchone()
    return r[0] if r else None


def test_ecb_rates_per_us_dollar_on_every_user_of_the_currency(con):
    assert value(con, "NZL", "fx_usd_d", "2024-01-02", "ecb_fx") == pytest.approx(1.7408 / 1.0956)
    assert value(con, "DEU", "fx_usd_d", "2024-01-02", "ecb_fx") == pytest.approx(1 / 1.0956)
    assert value(con, "eu", "fx_usd_d", "2024-01-02", "ecb_fx") == pytest.approx(1 / 1.0956)
    assert value(con, "USA", "fx_usd_d", "2024-01-02", "ecb_fx") == 1
    # Croatia: kuna until 2022, the euro from 2023; Bulgaria's lev until 2025
    assert value(con, "HRV", "fx_usd_d", "2022-12-30", "ecb_fx") == pytest.approx(7.5365 / 1.0666)
    assert value(con, "HRV", "fx_usd_d", "2024-01-02", "ecb_fx") == pytest.approx(1 / 1.0956)
    assert value(con, "BGR", "fx_usd_d", "2024-01-02", "ecb_fx") == pytest.approx(1.9558 / 1.0956)
    freq, f = con.execute("SELECT frequency, default_on FROM indicators WHERE indicator_id = 'fx_usd_d'").fetchone()
    assert freq == "D" and f is False
    ranks = con.execute("SELECT source_id FROM indicator_sources WHERE indicator_id = 'fx_usd_d' ORDER BY rank").fetchall()
    assert [r[0] for r in ranks] == ["ecb_fx", "fed_h10"]


def test_fed_rates_reach_back_and_invert_dollar_quotes(con):
    assert value(con, "NZL", "fx_usd_d", "1985-01-02", "fed_h10") == pytest.approx(1 / 0.49)
    assert value(con, "NZL", "fx_usd_d", "1985-01-03", "fed_h10") is None
    assert value(con, "JPN", "fx_usd_d", "1985-01-02", "fed_h10") == pytest.approx(251.8)
    assert value(con, "TWN", "fx_usd_d", "2024-01-02", "fed_h10") == pytest.approx(30.75)


def test_gas_storage_and_lng(con):
    assert value(con, "eu", "gas_storage_fill", "2024-01-02") == pytest.approx(85.7)
    assert value(con, "DEU", "gas_storage_twh", "2024-01-01") == pytest.approx(227.1)
    assert value(con, "DEU", "gas_storage_fill", "2024-01-02") is None  # "-" in the file
    assert value(con, "GBR", "lng_stock_fill", "2024-01-01") == pytest.approx(70)


def test_eia_weekly_stocks(con):
    assert value(con, "USA", "us_spr_stocks", "2024-01-05") == pytest.approx(354.4)
    assert value(con, "USA", "us_gas_storage", "2024-01-05") == 3336
    assert con.execute("SELECT frequency FROM indicators WHERE indicator_id = 'us_spr_stocks'").fetchone()[0] == "W"


def test_jodi_stocks_and_days_of_cover(con):
    assert value(con, "NZL", "jodi_product_stocks", "2024-01-01", freq="M") == 6200
    assert value(con, "NZL", "jodi_crude_stocks", "2024-01-01", freq="M") == 1500  # thousand barrels, not tonnes
    assert value(con, "NZL", "jodi_product_days", "2024-01-01", freq="M") == pytest.approx(6200 / 155)
    assert value(con, "AUS", "jodi_product_days", "2024-01-01") is None  # no demand figure


def test_bis_effective_exchange_rates(con):
    assert value(con, "NZL", "bis_eer_nominal", "2023-01-01", freq="A") == pytest.approx(99.0)
    assert value(con, "NZL", "bis_eer_nominal_m", "2023-02-01", freq="M") == pytest.approx(99.5)
    assert value(con, "eu", "bis_eer_nominal", "2023-01-01", freq="A") == pytest.approx(95.0)
    assert value(con, "NZL", "bis_policy_rate_m", "2023-01-01", freq="M") == pytest.approx(4.75)


def test_regions_from_stats_nz_files(con):
    assert value(con, "NZ-NTL", "nzreg_population", "2023-01-01") == 203900  # the total, not males
    assert value(con, "NZ-AUK", "nzreg_population", "2023-01-01") == 1739300
    assert value(con, "NZ-MWT", "nzreg_population", "2023-01-01") == 260900  # macron in the label
    assert value(con, "NZ-NTL", "nzreg_maori", "2023-01-01") == 72000
    assert value(con, "NZ-MWT", "nzreg_maori", "2023-01-01") == 60000  # no macron in the label
    kind = con.execute("SELECT type FROM entities WHERE entity_id = 'NZ-AUK'").fetchone()[0]
    assert kind == "subnational"
    parent = con.execute("SELECT parent_id, code FROM subdivisions WHERE entity_id = 'NZ-AUK'").fetchone()
    assert parent == ("NZL", "02")


def test_region_names_and_table_choice():
    assert region_of("08: Manawatū-Whanganui Region") == "NZ-MWT"
    assert region_of("Hawke's Bay") == "NZ-HKB"
    assert region_of("0100: Far North District") is None
    xml = ("<m:Structure xmlns:m='m' xmlns:s='s' xmlns:c='c'><m:Structures><s:Dataflows>"
           "<s:Dataflow id='POPES_SUB_001' agencyID='STATSNZ' version='1.0'><c:Name xml:lang='en'>Subnational population estimates (TA)</c:Name></s:Dataflow>"
           "<s:Dataflow id='POPES_SUB_006' agencyID='STATSNZ' version='1.0'><c:Name xml:lang='en'>Subnational population estimates (RC, SA2), by age and sex</c:Name></s:Dataflow>"
           "</s:Dataflows></m:Structures></m:Structure>")
    flows = parse_flows(xml)
    assert len(flows) == 2
    assert pick_flow(flows, {"find": ["subnational", "population", "estimates"], "prefer": ["rc", "sex"]})["id"] == "POPES_SUB_006"
    assert pick_flow(flows, {"find": ["census"]}) is None
    # The same list with a byte order mark, gzipped, or as SDMX-JSON; a web page fails saying what came back.
    import gzip

    import pytest

    from worldmodel_data.connectors.base import ConnectorError

    assert read_flows(b"\xef\xbb\xbf" + xml.encode()) == flows
    assert read_flows(gzip.compress(xml.encode())) == flows
    js = {"data": {"dataflows": [{"id": "POPES_SUB_006", "agencyID": "STATSNZ", "version": "1.0",
                                  "names": {"en": "Subnational population estimates (RC, SA2), by age and sex"}}]}}
    assert read_flows(json.dumps(js).encode())[0]["id"] == "POPES_SUB_006"
    with pytest.raises(ConnectorError, match="neither XML nor JSON; it starts: 'Access denied"):
        read_flows(b"Access denied due to invalid subscription key.")


def _q(con):
    def q(sql, params=None):
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return q


def test_currency_pairs_storage_and_regions_for_the_app(con):
    from worldmodel_api import markets

    q = _q(con)
    fx = markets.fx(q, "NZL", ["JPN", "eu"], 2024, 2024)
    assert fx["currency"] == "NZD" and fx["step"] == "day"
    jpy = next(p for p in fx["partners"] if p["entity_id"] == "JPN")
    assert dict(jpy["points"])["2024-01-02"] == pytest.approx(155.65 / 1.7408)  # yen per NZ dollar
    idx = markets.fx(q, "NZL", ["JPN"], 2024, 2024, mode="index")["partners"][0]["points"]
    assert idx[0][1] == pytest.approx(100)
    assert any(c["currency"] == "EUR" and c["entity_id"] == "eu" for c in markets.fx(q, "NZL", None, None, None)["choices"])
    assert markets.top_partners(q, "NZL")[:1] == ["USA"]  # no trade figures here: the standard list
    items = markets.storage_list(q)
    assert {"indicator_id": "gas_storage_fill", "entity_id": "eu"}.items() <= next(i for i in items if i["entity_id"] == "eu").items()
    s = markets.storage(q, "gas_storage_fill", "eu", 5)
    assert s["year"] == 2024 and s["latest"]["value"] == pytest.approx(85.7) and s["years"]["2024"][0][0] == 1
    nz = markets.storage(q, "jodi_product_days", "NZL", 5)
    assert nz["frequency"] == "M" and nz["years"]["2024"][0][0] == 15  # mid-January
    r = markets.regions(q, "NZL")
    assert len(r["regions"]) == 16
    pop = next(m for m in r["measures"] if m["indicator_id"] == "nzreg_population")
    assert pop["values"]["NZ-AUK"]["2023"] == 1739300
    assert markets.regions(q, "AUS")["regions"] == []
