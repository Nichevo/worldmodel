"""Remote's Global Life-Work Balance Index and Natixis' Global Retirement Index: staged from
fixtures shaped like the real page and report, and read into the Scorecard's new rows."""

from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.wellbeing import gri_csv, gri_table, lwb_values
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "remote_lwb", "natixis_gri"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return duckdb.connect(str(result.path), read_only=True)


def _v(con, ind, ent, year):
    got = con.execute("SELECT value FROM series WHERE indicator_id = ? AND entity_id = ? AND year(period_start) = ?",
                      [ind, ent, year]).fetchall()
    return got[0][0] if got else None


def test_life_work_balance(con):
    assert _v(con, "lwb_score", "NZL", 2025) == pytest.approx(86.59)
    assert _v(con, "lwb_paid_leave_days", "NZL", 2025) == 31
    assert _v(con, "lwb_maternity_weeks", "NOR", 2025) == 49
    assert _v(con, "lwb_score", "IRQ", 2025) == pytest.approx(37.66)  # "Iraq,\nBaghdad" with no link
    assert _v(con, "lwb_paid_leave_days", "USA", 2025) == 11
    assert _v(con, "lwb_min_wage_usd", "NOR", 2025) is None  # no statutory minimum, written as 0
    assert _v(con, "lwb_maternity_pay_pct", "AUS", 2025) is None  # paid at the minimum wage, not a share
    assert _v(con, "lwb_sick_pay_pct", "GBR", 2025) is None  # a flat amount a week
    assert _v(con, "lwb_peace_index", "IRL", 2025) == pytest.approx(1.12)


def test_retirement_index(con):
    assert _v(con, "gri_score", "NOR", 2026) == 83
    assert _v(con, "gri_score", "IND", 2026) == 9
    assert _v(con, "gri_health", "LUX", 2026) == 94
    assert _v(con, "gri_finances", "IRL", 2026) == 76
    assert _v(con, "gri_quality_of_life", "FIN", 2026) == 92
    assert _v(con, "gri_material_wellbeing", "DNK", 2026) == 83
    assert _v(con, "gri_score", "KOR", 2026) == 69  # "Korea, Rep."
    assert _v(con, "gri_finances", "NZL", 2026) == 73


def test_lwb_cells():
    got = lwb_values({"index_score_100": "55.46", "statutory_annual_leave": "3\n16",
                      "minimum_statutory_sick_pay_percentage": "50.00",
                      "paid_maternity_leave_and_payment_rate": "18\nFixed: 290.18 USD",
                      "average_hours_per_week_per_employed_person": "-"})
    assert got == {"lwb_score": 55.46, "lwb_annual_leave_days": 3, "lwb_public_holidays": 16, "lwb_sick_pay_pct": 50,
                   "lwb_maternity_weeks": 18, "lwb_paid_leave_days": 19}


def test_gri_rows_layout_and_chart_check():
    names = ["Norway", "Ireland", "Netherlands", "Switzerland", "Denmark", "Australia", "Germany", "Luxembourg",
             "Iceland", "Czechia", "Slovenia", "New Zealand"]
    n = len(names)
    health = [75 + (i * 4) % 17 for i in range(n)]
    finances = [60 + (i * 7) % 15 for i in range(n)]
    material = [70 + (i * 5) % 20 for i in range(n)]
    quality = [50 + (i * 3) % 30 for i in range(n)]
    overall = [80 - i for i in range(n)]
    # the overall column first and the sub-indices in another order, one row per country
    rows = " ".join(f"{nm} {o}% {m}% {h}% {q}% {f}%" for nm, o, m, h, q, f in
                    zip(names, overall, material, health, quality, finances))
    charts = {"Material Wellbeing": f"{max(material)}% Top 25 Countries in Material Wellbeing Sub-Index Ranking change "
                                    f"{names[material.index(max(material))]}",
              "Health": f"{max(health)}% Ranking change {names[health.index(max(health))]}",
              "Quality of Life": f"{max(quality)}% Ranking change {names[quality.index(max(quality))]}",
              "Finances in Retirement": f"{max(finances)}% Ranking change {names[finances.index(max(finances))]}"}
    got = gri_table("Full Rankings 40% and below 41%-50% " + rows, charts)
    assert got["NOR"]["gri_score"] == 80 and got["NZL"]["gri_score"] == 80 - (n - 1)
    assert [got[e]["gri_material_wellbeing"] for e in ("NOR", "IRL")] == material[:2]
    assert [got[e]["gri_quality_of_life"] for e in ("NOR", "IRL")] == quality[:2]
    assert [got[e]["gri_finances"] for e in ("NOR", "IRL")] == finances[:2]
    assert [got[e]["gri_health"] for e in ("NOR", "IRL")] == health[:2]


def test_gri_csv():
    got = gri_csv([["Rank", "Country", "Overall", "Health", "Finances in retirement", "Material wellbeing", "Quality of life"],
                   ["1", "Norway", "83%", "92%", "70%", "81%", "90%"]])
    assert got == {"NOR": {"gri_score": 83, "gri_health": 92, "gri_finances": 70, "gri_material_wellbeing": 81,
                           "gri_quality_of_life": 90}}
