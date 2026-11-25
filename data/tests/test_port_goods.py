"""Goods by port (connectors/port_goods.py): each source's reader on small made-up files, and
the build tying ports to IMF PortWatch ports."""

import zipfile
from datetime import date
from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.port_goods import (
    bitre_top_ports,
    census_rows,
    dft_rows,
    eurostat_rows,
    statsnz_rows,
    write_rows,
)
from worldmodel_data.network_tables import match_port, port_name_key
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_statsnz_rows(tmp_path):
    imp = ('Month,Harmonised System Code,Harmonised System Description,Unit Qty,Country,NZ Port,Imports ($NZD vfd),'
           'Imports ($NZD cif),Imports Qty,Imports Gross Weight,Status\n'
           '202402,2709000001,"Crude oil",KGM,Australia,Port of Tauranga,"1,000,000","1,100,000",5,"2,000,000",Final\n'
           '202402,2710000001,"Fuel",KGM,Singapore,Port of Tauranga,"500,000","510,000",5,"400,000",Final\n')
    exp = ('Month,Harmonised System Code,Harmonised System Description,Unit Qty,Country,NZ Port,Exports ($NZD fob),'
           'Exports Qty,Exports Gross Weight,Re-exports ($NZD fob),Re-exports Qty,Re-exports Gross Weight,'
           'Total Exports ($NZD fob),Total Exports Qty,Total Gross Weight,Status\n'
           '202402,4403210000,"Logs",KGM,China,Port of Tauranga,"2,000,000",1,"5,000,000","100,000",0,"10,000",'
           '"2,100,000",1,"5,010,000",Final\n')
    zp = tmp_path / "y.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("Feb_2024_Imports_HS10_by_Country_by_Port.csv", imp)
        z.writestr("Feb_2024_Exports_HS10_by_Country_by_Port.csv", exp)
    rows = {(r[5], r[6], r[8]): r for r in statsnz_rows(zp)}
    oil = rows[("in", "27", "")]
    assert oil[1] == "NZ:port-of-tauranga" and oil[3] == "2024-02-01" and oil[7] == "Oil, gas and coal"
    assert oil[9] == pytest.approx(2400) and oil[10] == pytest.approx(1_500_000)  # two HS10 lines, kg to tonnes
    logs = rows[("out", "44", "")]
    assert logs[9] == pytest.approx(5010) and logs[10] == pytest.approx(2_100_000)  # re-exports included
    assert rows[("in", "TOTAL", "SGP")][10] == pytest.approx(500_000)
    assert rows[("out", "TOTAL", "CHN")][9] == pytest.approx(5010)


def test_eurostat_rows():
    def body(cargo, partners):
        return {"id": ["freq", "direct", "cargo", "unit", "par_mar", "rep_mar", "time"],
                "size": [1, 1, len(cargo), 1, len(partners), 2, 1],
                "dimension": {"freq": {"category": {"index": {"Q": 0}}}, "direct": {"category": {"index": {"IN": 0}}},
                              "cargo": {"category": {"index": {c: i for i, c in enumerate(cargo)}}},
                              "unit": {"category": {"index": {"THS_T": 0}}},
                              "par_mar": {"category": {"index": {p: i for i, p in enumerate(partners)}}},
                              "rep_mar": {"category": {"index": {"NL": 0, "NL_0NLRTM": 1},
                                                       "label": {"NL": "Netherlands", "NL_0NLRTM": "Rotterdam"}}},
                              "time": {"category": {"index": {"2024-Q2": 0}}}},
                "value": {str(i): 10.0 * (i + 1) for i in range(len(cargo) * len(partners) * 2)}}
    rows = eurostat_rows(body(["TOTAL", "LBK", "DBK"], ["TOTAL"]), "cargo")
    assert {r[6] for r in rows} == {"LBK", "DBK"}  # the total and the country row are left out
    lbk = next(r for r in rows if r[6] == "LBK")
    assert lbk[:6] == ("NLD", "EU:NL_0NLRTM", "Rotterdam", "2024-04-01", "Q", "in") and lbk[9] == 40_000
    rows = eurostat_rows(body(["TOTAL"], ["TOTAL", "US", "NL", "DE_1"]), "partner")
    assert {r[8] for r in rows} == {"USA"}  # not the total, the reporter itself or a sea area


def _ods(path: Path, rows: list[list[str]]) -> None:
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
    body = "".join("<table:table-row>" + "".join(f"<table:table-cell><text:p>{c}</text:p></table:table-cell>" for c in r)
                   + "</table:table-row>" for r in rows)
    xml = (f'<?xml version="1.0"?><office:document-content {ns}><office:body><office:spreadsheet>'
           '<table:table table:name="Cover"><table:table-row><table:table-cell><text:p>x</text:p></table:table-cell>'
           f'</table:table-row></table:table><table:table table:name="port0499">{body}</table:table>'
           '</office:spreadsheet></office:body></office:document-content>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", xml)


def test_dft_rows(tmp_path):
    head = ["Year", "Major Port", "Port of Load/Unload Region", "Port of Load/Unload Country", "Direction", "Cargo Group",
            "Cargo Category", "Cargo Description", "Tonnage(thousands)", "Loaded Units (thousands)"]
    p = tmp_path / "port0499.ods"
    _ods(p, [["Table PORT0499"], head[:8] + ["Total of filtered rows: Tonnage(thousands)"], head,
             ["2024", "Felixstowe", "Far East", "China", "Inwards", "Container", "51", "20ft", "1,200", "10"],
             ["2024", "Felixstowe", "Far East", "Japan", "Inwards", "Container", "51", "20ft", "300", "2"],
             ["2024", "Felixstowe", "Africa", "Africa - Small Flows", "Outwards", "Liquid Bulk", "11", "Crude", "LOW", "0"],
             ["2024", "Milford Haven", "Europe", "Norway", "Inwards", "Liquid Bulk", "13", "Gas", "5000", "0"]])
    rows = dft_rows(p)
    goods = {(r[2], r[5], r[6]): r[9] for r in rows if r[8] == ""}
    assert goods[("Felixstowe", "in", "container")] == pytest.approx(1_500_000)
    assert goods[("Felixstowe", "out", "liquid_bulk")] == 0
    part = {(r[2], r[8]): r[9] for r in rows if r[8]}
    assert part[("Felixstowe", "CHN")] == pytest.approx(1_200_000) and part[("Milford Haven", "NOR")] == 5_000_000
    assert all(r[3] == "2024-01-01" and r[4] == "A" for r in rows)


def test_census_rows():
    body = [["PORT", "PORT_NAME", "E_COMMODITY", "VES_VAL_MO", "VES_WGT_MO", "time", "COMM_LVL"],
            ["2704", "Los Angeles, CA", "84", "1000000", "50000", "2024-03", "HS2"],
            ["2704", "Los Angeles, CA", "-", "9000000", "900000", "2024-03", "HS2"],
            ["3901", "Chicago, IL", "84", "0", "0", "2024-03", "HS2"]]
    rows = census_rows(body, "exports")
    assert rows == [("USA", "US:2704", "Los Angeles, CA", "2024-03-01", "M", "out", "84", "Machinery", "", 50.0,
                     1_000_000.0, "USD")]


def test_bitre_top_ports():
    table = [["Table 1.4 Top ten ports"], ["Financial\r\nyear", "Port Hedland", "Dampier", "All ports a"],
             ["Exports", None, "( million tonnes )", None], ["2022–23", 557.2, 168.6, 1535.3], ["2023–24", 563.8, 167.2, 1558.1],
             ["Annual growth rate", None, "( % )", None], ["1 year", 1.1, -0.7, 1.4],
             [None, "Sydney", "Melbourne", "All ports a"], ["Imports", None, "( million tonnes )", None],
             ["2023–24", 20.5, 16.9, 111.5]]
    rows = bitre_top_ports(table, "weight")
    got = {(r[2], r[3], r[5]): r[9] for r in rows}
    assert got[("Port Hedland", "2024-06-30", "out")] == pytest.approx(563.8e6)
    assert got[("Sydney", "2024-06-30", "in")] == pytest.approx(20.5e6)
    assert not any(r[2].startswith("All ports") for r in rows) and len(rows) == 6


def test_port_names_match():
    assert port_name_key("Port of Los Angeles") == port_name_key("Los Angeles, CA") == "losangeles"
    ports = [(port_name_key("Tauranga"), "p2"), (port_name_key("Auckland"), "p1"), (port_name_key("Lyttelton"), "p3")]
    assert match_port("Port of Tauranga", ports) == "p2"
    assert match_port("Lyttelton Port", ports) == "p3"
    assert match_port("Napier", ports) is None


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "portwatch", "statsnz_port_trade"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return result, duckdb.connect(str(result.path), read_only=True)


def test_port_goods_built(built):
    _, con = built
    rows = con.execute("""SELECT port_key, port_id, kind, entity_id, period, direction, goods, partner_id, tonnes, value
                          FROM port_goods ORDER BY ALL""").fetchall()
    assert rows
    taur = [r for r in rows if r[0] == "NZ:port-of-tauranga"]
    assert {r[1] for r in taur} == {"port2"} and {r[2] for r in taur} == {"sea"} and {r[3] for r in taur} == {"NZL"}
    air = [r for r in rows if r[0] == "NZ:auckland-airport"]
    assert air and {r[1] for r in air} == {None} and {r[2] for r in air} == {"air"}
    milk = next(r for r in taur if r[6] == "04")
    assert milk[4] == date(2024, 1, 1) and milk[5] == "out" and milk[8] == pytest.approx(800)
    assert any(r[7] == "CHN" and r[6] == "TOTAL" for r in taur)


def test_write_rows_round_trip(tmp_path):
    p = tmp_path / "port_goods_x.csv.gz"
    write_rows(p, [("NZL", "NZ:a", "A", "2024-01-01", "M", "in", "01", "Live animals", "", 1.0, 2.0, "NZD")])
    con = duckdb.connect()
    from worldmodel_data.connectors.port_goods import load_rows
    assert load_rows(con, [p]) == 1
