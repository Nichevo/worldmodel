"""Sectors endpoints on a copy of the sample warehouse with a few made-up sector rows
added: the list, one sector's rankings, concentration, routes, reliance and prices,
the cars and EV battery extras, and one country's trade by chapter."""

import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main
from worldmodel_api.warehouse import SAMPLE, Warehouse


def add_sector_rows(path):
    """Made-up bauxite, alumina, lithium, chip and dairy figures, enough to draw every part of the pages."""
    con = duckdb.connect(str(path))
    rows = []

    def put(e, ind, y, v, bd="", src="baci", freq="A", month=1):
        rows.append((e, ind, date(y, month, 1), freq, bd, "central", src, "t", float(v), "E"))

    for y in (2021, 2022, 2023):
        k = 1 + (y - 2021) / 10
        put("AUS", "sx_bauxite", y, 600e6 * k)
        put("GIN", "sx_bauxite", y, 900e6 * k)
        put("AUS", "sx_bauxite", y, 500e6 * k, "partner=CHN")
        put("GIN", "sx_bauxite", y, 850e6 * k, "partner=CHN")
        put("AUS", "sxq_bauxite", y, 12e6)
        put("GIN", "sxq_bauxite", y, 20e6)
        put("CHN", "sm_bauxite", y, 1400e6 * k)
        put("CHN", "smq_bauxite", y, 30e6)
        put("NZL", "sm_alumina", y, 400e6)
        put("NZL", "smq_alumina", y, 650e3)
        put("AUS", "sp_bauxite", y, 100e6, src="usgs_mcs")
        put("CHN", "sp_bauxite", y, 90e6, src="usgs_mcs")
        put("GIN", "sp_bauxite", y, 97e6, src="wmd")
        put("CHN", "sp_bauxite", y, 1, src="wmd")  # a worse-ranked source does not replace USGS
        put("AUS", "sp_lithium_raw", y, 86e3, src="usgs_mcs")
        put("CHL", "sp_lithium_raw", y, 44e3, src="usgs_mcs")
        put("TWN", "sx_chips", y, 180e9)
        put("KOR", "sx_chips", y, 110e9)
        put("NZL", "sx_chips", y, 0.1e9)
        for cc, xv, mv in (("04", 12e9 * k, 0.3e9), ("44", 3e9, 0.2e9), ("87", 0.2e9, 6e9 * k)):
            put("NZL", f"tgx_{cc}", y, xv)
            put("NZL", f"tgm_{cc}", y, mv)
        put("NZL", "tgx_04", y, 4e9, "partner=CHN")
        put("NZL", "tgm_87", y, 2.5e9, "partner=JPN")
        put("NZL", "ev_sales_share", y, 10 + y - 2021, src="iea_ev")
        put("NOR", "ev_sales_share", y, 80 + y - 2021, src="iea_ev")
        put("world", "ev_sales_share", y, 14 + 2 * (y - 2021), src="iea_ev")
    for m in (1, 2):
        put("world", "price_aluminium", 2024, 2200 + m, src="wb_pinksheet", freq="M", month=m)
    for y in range(2014, 2024):  # ten years of monthly prices: 2000 rising 10 a month
        for m in range(1, 13):
            put("world", "price_aluminium", y, 2000 + 10 * ((y - 2014) * 12 + m - 1), src="wb_pinksheet", freq="M", month=m)
            put("world", "pindex_metals", y, 100 + (y - 2014), src="wb_pinksheet", freq="M", month=m)
            put("world", "ffpi_dairy", y, 120 - (y - 2014), src="fao_ffpi", freq="M", month=m)
            put("NZL", "anz_dairy", y, 300, src="anz_cpi", freq="M", month=m)
    for y, v in ((1980, 10), (1981, 10)) + tuple((y, 2) for y in range(1982, 2025)):
        put("USA", "inflation", y, v, src="imf_weo")
    put("AUS", "sr_bauxite", 2023, 3.5e9, src="usgs_mcs")
    con.executemany("INSERT INTO observations VALUES (" + ", ".join("?" * 10) + ")", rows)
    for src in sorted({r[6] for r in rows}):
        con.execute("INSERT INTO vintages BY NAME SELECT ? AS source_id, 't' AS vintage, 't' AS release, true AS is_latest", [src])
    inds = {"sx_bauxite": ("US dollars", "baci"), "sxq_bauxite": ("tonnes", "baci"), "sm_bauxite": ("US dollars", "baci"),
            "smq_bauxite": ("tonnes", "baci"), "sm_alumina": ("US dollars", "baci"), "smq_alumina": ("tonnes", "baci"),
            "sp_bauxite": ("tonnes", "usgs_mcs"), "sp_lithium_raw": ("tonnes", "usgs_mcs"), "sr_bauxite": ("tonnes", "usgs_mcs"),
            "sx_chips": ("US dollars", "baci"), "ev_sales_share": ("%", "iea_ev"), "price_aluminium": ("US$ per mt", "wb_pinksheet"),
            "tgx_04": ("US dollars", "baci"), "tgm_04": ("US dollars", "baci"), "tgx_44": ("US dollars", "baci"),
            "tgm_44": ("US dollars", "baci"), "tgx_87": ("US dollars", "baci"), "tgm_87": ("US dollars", "baci"),
            "pindex_metals": ("index, 2010 = 100", "wb_pinksheet"), "ffpi_dairy": ("index, 2014-2016 = 100", "fao_ffpi"),
            "anz_dairy": ("index", "anz_cpi")}
    for i, (unit, src) in inds.items():
        con.execute("INSERT INTO indicators BY NAME SELECT ? AS indicator_id, ? AS name, '' AS description, 'trade' AS domain, "
                    "? AS unit, 0 AS decimals, ? AS frequency, '' AS breakdowns, 'none' AS agg_method, true AS default_on",
                    [i, i.replace("_", " "), unit, "M" if i.startswith(("price", "pindex", "ffpi", "anz")) else "A"])
        con.execute("INSERT INTO indicator_sources BY NAME SELECT ? AS indicator_id, ? AS source_id, ? AS series, 1.0 AS scale, 1 AS rank",
                    [i, src, i])
    con.execute("INSERT INTO indicator_sources BY NAME SELECT 'sp_bauxite' AS indicator_id, 'wmd' AS source_id, 'sp_bauxite' AS series, 1.0 AS scale, 2 AS rank")
    con.close()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("sectors_api")
    path = d / "sectors-sample.duckdb"
    shutil.copy(SAMPLE, path)
    add_sector_rows(path)
    mp = pytest.MonkeyPatch()
    mp.setenv("WORLDMODEL_HOME", str(d))
    mp.setenv("WORLDMODEL_USER_DIR", str(d / "user"))
    old = main.warehouse
    main.warehouse = Warehouse(str(path))
    yield TestClient(main.app)
    main.warehouse = old
    mp.undo()


def test_list(client):
    r = client.get("/api/v1/sectors").json()
    assert r["has_trade"] and "metals" in r["groups"]
    alu = next(s for s in r["sectors"] if s["id"] == "aluminium")
    baux = alu["stages"][0]
    assert baux["exports"]["top"] == "GIN" and baux["exports"]["year"] == 2023
    assert baux["production"]["top"] == "AUS"
    assert alu["nz"] is True  # Tiwai Point
    assert any(s["id"] == "semiconductors" for s in r["sectors"])


def test_sector_page(client):
    r = client.get("/api/v1/sectors/aluminium?year=2022&country=NZL").json()
    baux = r["stages"][0]
    assert baux["exports"]["year"] == 2022 and baux["exports"]["rows"][0]["entity_id"] == "GIN"
    assert baux["exports"]["rows"][0]["share"] == pytest.approx(60.0)
    prod = {x["entity_id"]: x["value"] for x in baux["production"]["rows"]}
    assert prod["CHN"] == 90e6  # USGS (rank 1) wins over World Mining Data for China
    assert prod["GIN"] == 97e6  # and World Mining Data fills in where USGS has nothing
    y, top3, hhi, n = baux["production"]["concentration"][-1]
    assert n == 3 and top3 == 100.0 and 3000 < hhi < 3500
    assert baux["routes"][0] == {"from": "GIN", "from_name": baux["routes"][0]["from_name"], "to": "CHN",
                                 "to_name": baux["routes"][0]["to_name"], "value": pytest.approx(935e6)}
    assert baux["reserves"]["rows"][0]["entity_id"] == "AUS"
    china = next(x for x in baux["reliance"] if x["entity_id"] == "CHN")
    assert china["reliance"] == pytest.approx(25.0)  # 30 Mt imported of 120 Mt used
    alumina = r["stages"][1]
    assert alumina["country"]["series"]["imports"][-1] == [2023, 400e6]
    assert [p[0] for p in baux["unit_value"]] == [2021, 2022, 2023]
    assert r["prices"][0]["id"] == "price_aluminium" and r["prices"][0]["points"][-1] == ["2024-02", 2202.0]
    assert any(c.get("nz") for c in r["companies"])
    assert client.get("/api/v1/sectors/nothing").status_code == 404


def test_cars_and_batteries(client):
    cars = client.get("/api/v1/sectors/cars").json()
    assert cars["electric"]["ranking"][0]["entity_id"] == "NOR"
    assert cars["electric"]["sales_share"]["NZL"][-1] == [2023, 12]
    bat = client.get("/api/v1/sectors/ev_batteries").json()["battery"]
    lith = next(m for m in bat["materials"] if m["material"] == "lithium")
    assert lith["steps"][0]["top"][0]["entity_id"] == "AUS" and lith["steps"][0]["high"] is True
    assert {r["country"] for r in bat["rules"]} >= {"IDN", "CHN"}
    assert bat["chemistries"][0]["chemistry"] == "NMC 811"


def test_by_country(client):
    r = client.get("/api/v1/sectors/by-country?country=NZL&since=2021").json()
    assert r["year"] == 2023 and r["since"] == 2021
    dairy = next(c for c in r["chapters"] if c["chapter"] == "04")
    assert dairy["exports"] == pytest.approx(14.4e9) and dairy["exports_change"] == pytest.approx(20.0)
    assert dairy["export_partners"][0]["entity_id"] == "CHN"
    cars = next(c for c in r["chapters"] if c["chapter"] == "87")
    assert cars["balance"] < 0 and cars["import_partners"][0]["entity_id"] == "JPN"
    chips = next(s for s in r["stages"] if s["stage"] == "chips")
    assert chips["exports"]["rank"] == 3 and chips["exports"]["of"] == 3
    assert r["totals"][-1][0] == 2023


def test_overview(client):
    r = client.get("/api/v1/sectors/overview").json()
    metals = next(g for g in r["board"] if g["id"] == "metals")
    alu = next(x for x in metals["items"] if x["id"] == "price_aluminium")
    assert alu["date"] == "2024-02" and alu["value"] == 2202
    assert alu["pos10"] == 100 or alu["value"] < alu["high10"]  # Jan-Feb 2024 sit below Dec 2023's 3190
    assert len(alu["spark"]) == 60 and alu["y1"] is not None
    assert metals["index"]["id"] == "pindex_metals"
    food = next(g for g in r["board"] if g["id"] == "food")
    assert any(x["id"] == "ffpi_dairy" for x in food["items"])
    nz = next(g for g in r["board"] if g["id"] == "nz")
    assert nz["items"][0]["id"] == "anz_dairy"
    # trade by group, per sector, makers and New Zealand
    metals_trade = next(g for g in r["trade_groups"] if g["id"] == "metals")
    assert metals_trade["value"] == pytest.approx((600e6 + 900e6) * 1.2) and metals_trade["top"][0]["name"]
    assert r["sectors"]["aluminium"]["trade"]["year"] == 2023
    assert r["sectors"]["aluminium"]["makers"]["rows"][0]["entity_id"] == "AUS"
    assert r["sectors"]["dairy"]["price"]["id"] == "anz_dairy"
    assert r["heads"]["world_trade"]["year"] == 2023
    assert r["heads"]["concentrated"]


def test_prices_table_series_and_trade(client):
    t = client.get("/api/v1/sectors/prices").json()
    alu = next(x for x in t["items"] if x["id"] == "price_aluminium")
    assert alu["group"] == "metals" and alu["sectors"][0]["id"] == "aluminium" and "spark" not in alu
    assert t["deflator"][0] == [1980, 1.0]
    s = client.get("/api/v1/sectors/prices/series?ids=price_aluminium,anz_dairy,nonsense").json()
    assert [x["id"] for x in s["series"]] == ["price_aluminium", "anz_dairy"]
    assert s["series"][0]["points"][0] == ["2014-01", 2000]
    tr = client.get("/api/v1/sectors/prices/price_aluminium/trade").json()
    assert tr["stage"] == "bauxite" and tr["sellers"][0]["entity_id"] == "GIN"
    assert client.get("/api/v1/sectors/prices/price_nothing/trade").status_code == 404
