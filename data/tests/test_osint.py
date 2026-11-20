"""Detail from the OSINT communities: located events (UCDP, ACLED), war trackers (Oryx, claimed
losses, DeepState, Kiel), internet outages (IODA, Cloudflare Radar, #KeepItOn), sanctions in force
(OpenSanctions), military strength (Global Firepower) and arms deals (SIPRI), staged from small
hand-made fixtures and built into one warehouse."""

from datetime import date
from pathlib import Path

import duckdb
import pytest
from worldmodel_contract import osint
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.military import gfp_listing, gfp_values, sipri_deals
from worldmodel_data.connectors.wars import area_km2, oryx_totals
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("ucdp_ged", "ucdp_candidate", "acled", "oryx", "ua_claimed_losses", "deepstate", "kiel_ukraine", "ioda",
           "cloudflare_radar", "keepiton", "opensanctions", "gfp", "sipri_arms")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", *SOURCES):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return duckdb.connect(str(result.path), read_only=True)


def test_contract_names():
    assert osint.acled_kind("Explosions/Remote violence") == "explosion" and osint.acled_kind("Protests") == "protest"
    assert osint.loss_category("Armoured Fighting Vehicles") == "afv" and osint.loss_category("Tanks") == "tanks"
    assert osint.authority("New Zealand Russia Sanctions Register") == "NZL"
    assert osint.authority("US OFAC Specially Designated Nationals (SDN) List") == "USA"
    assert osint.authority("UN Security Council Consolidated List") == "un"
    assert osint.authority("EU Financial Sanctions Files (FSF)") == "eu"
    assert osint.war("russia_ukraine")["sides"] == ["RUS", "UKR"]


def test_oryx_page_totals():
    t = oryx_totals((FIXTURES / "oryx" / "oryx_RUS_2026-11-20.html").read_text(encoding="utf-8"))
    assert t["total"] == {"total": 21839, "destroyed": 16050, "damaged": 978, "abandoned": 1186, "captured": 3625}
    assert t["tanks"]["total"] == 4085 and t["tanks"]["captured"] == 521
    assert t["naval"]["total"] == 28 and "afv" in t


def test_gfp_pages():
    listing = gfp_listing((FIXTURES / "gfp" / "gfp_listing.html").read_text(encoding="utf-8"))
    assert listing["new-zealand"] == {"name": "New Zealand", "power_index": 1.8962}
    v = gfp_values((FIXTURES / "gfp" / "gfp_new-zealand.html").read_text(encoding="utf-8"))
    assert v["gfp_personnel_total"] == 9450 and v["gfp_personnel_active"] == 8750
    assert v["gfp_helicopters"] == 18 and v["gfp_helicopters_attack"] == 0
    assert v["gfp_tanks"] == 0 and v["gfp_aircraft_tankers"] == 0 and v["gfp_navy_total"] == 9
    assert v["gfp_budget_usd"] == 3.75e9 and v["gfp_power_index"] == 1.8962


def test_sipri_deals():
    rows = sipri_deals((FIXTURES / "sipri_arms" / "Trade-Register-1950-2025.csv").read_text(encoding="utf-8"))
    nz = next(r for r in rows if r[1] == "NZL")
    assert nz[0] == "USA" and nz[2] == 2018 and nz[3:5] == (2022, 2023) and nz[5] == "P-8A Poseidon" and nz[8] == 360


def test_area_is_about_right():
    from shapely.geometry import box
    # one degree square at the equator: about 111.2 km x 110.6 km
    assert 12_200 < area_km2(box(0, 0, 1, 1)) < 12_400


def test_conflict_events(con):
    rows = con.execute("SELECT event_id, entity_id, kind, deaths, source_id FROM conflict_events ORDER BY event_id").fetchall()
    ids = {r[0] for r in rows}
    assert {"ged:1", "ged:2", "ged:3", "ged:4", "ged:901", "acled:NZL1", "acled:UKR77", "acled:AUS5"} <= ids
    assert "ged:900" not in ids  # a candidate event the yearly dataset already covers
    by = {r[0]: r for r in rows}
    assert by["ged:3"][1] == "MMR" and by["ged:3"][2] == "onesided"
    assert by["acled:NZL1"][1] == "NZL" and by["acled:NZL1"][2] == "protest"
    assert by["acled:AUS5"][1] == "AUS" and by["acled:AUS5"][2] == "riot"
    ged_deaths = con.execute("""SELECT value FROM series WHERE indicator_id = 'fighting_deaths' AND entity_id = 'UKR'
        AND year(period_start) = 2024 AND source_id = 'ucdp_ged'""").fetchone()
    assert ged_deaths and ged_deaths[0] == 120
    acled = con.execute("""SELECT value FROM series WHERE indicator_id = 'fighting_deaths' AND entity_id = 'UKR'
        AND year(period_start) = 2024 AND source_id = 'acled'""").fetchone()
    assert acled and acled[0] == 12  # the same indicator from both sources, side by side


def test_war_trackers(con):
    seen = con.execute("""SELECT count FROM war_losses WHERE side = 'RUS' AND category = 'tanks' AND status = 'total'
        AND basis = 'seen' AND day = DATE '2026-11-20'""").fetchone()
    assert seen and seen[0] == 4085
    ukr = con.execute("SELECT count FROM war_losses WHERE side = 'UKR' AND category = 'tanks' AND status = 'captured'").fetchone()
    assert ukr and ukr[0] == 150
    claimed = con.execute("""SELECT count FROM war_losses WHERE side = 'RUS' AND category = 'tanks' AND basis = 'claimed'
        ORDER BY day DESC LIMIT 1""").fetchone()
    assert claimed and claimed[0] == 12485
    assert con.execute("SELECT count FROM war_losses WHERE category = 'personnel'").fetchone()[0] == 1633130
    areas = con.execute("SELECT day, area_km2 FROM war_areas ORDER BY day").fetchall()
    assert [a[0] for a in areas] == [date(2024, 7, 8), date(2026, 11, 19), date(2026, 11, 20)]
    assert 32_000 < areas[0][1] < 34_000  # 2 x 2 degrees at 48 N and areas[2][1] > areas[1][1] > areas[0][1]
    front = con.execute("SELECT feature_id, rank FROM geo_features WHERE layer_id = 'front_line' ORDER BY feature_id").fetchall()
    assert ("russia_ukraine:2026-11-20", 1) in front and ("russia_ukraine:2024-07-08", 2) in front  # a Monday
    aid = con.execute("""SELECT value FROM series WHERE indicator_id = 'ukraine_aid_military_eur' AND entity_id = 'NZL'""").fetchone()
    assert aid and aid[0] == 0.06


def test_outages(con):
    ev = con.execute("SELECT entity_id, source_id, subkind FROM events WHERE kind = 'outage' ORDER BY 1, 2").fetchall()
    assert ("IRN", "ioda", "detected") in ev and ("TON", "ioda", "detected") in ev
    assert sum(1 for e in ev if e[:2] == ("TON", "ioda")) == 1  # the half-hour one is left out
    assert ("IRQ", "cloudflare_radar", "government order") in ev and ("TON", "cloudflare_radar", "cable cut") in ev
    assert sum(1 for e in ev if e[:2] == ("PAK", "keepiton")) == 2 and ("IND", "keepiton", "government order") in ev
    h = con.execute("""SELECT value FROM series WHERE indicator_id = 'internet_outage_hours' AND entity_id = 'IRN'
        AND year(period_start) = 2024""").fetchone()
    assert h and h[0] == 2
    n = con.execute("""SELECT value FROM series WHERE indicator_id = 'internet_shutdowns' AND entity_id = 'PAK'""").fetchone()
    assert n and n[0] == 2


def test_sanctions(con):
    c = dict(((r[0], r[1]), r[2]) for r in con.execute(
        "SELECT target, authority, sum(listed) FROM sanction_counts GROUP BY 1, 2").fetchall())
    assert c[("RUS", "NZL")] == 1 and c[("RUS", "USA")] == 1 and c[("RUS", "eu")] == 1 and c[("ARE", "eu")] == 1
    assert c[("IRN", "GBR")] == 1 and c[("IRN", "AUS")] == 1 and c[("PRK", "un")] == 1
    ship = con.execute("SELECT identifiers, authorities FROM sanction_listings WHERE schema = 'Vessel'").fetchone()
    assert ship == ("412345678,9123456", "AUS,GBR")


def test_military(con):
    m = dict(con.execute("SELECT measure, value FROM military_strength WHERE entity_id = 'NZL' AND edition = 2026").fetchall())
    assert m["gfp_personnel_active"] == 8750 and m["gfp_power_index"] == 1.8962
    assert con.execute("""SELECT value FROM military_strength WHERE entity_id = 'USA' AND measure = 'gfp_power_index'""").fetchone()[0] == 0.0744
    s = con.execute("""SELECT value FROM series WHERE indicator_id = 'gfp_frigates' AND entity_id = 'NZL'""").fetchone()
    assert s and s[0] == 2
    deals = con.execute("SELECT supplier, recipient, weapon FROM arms_deals ORDER BY recipient").fetchall()
    assert ("USA", "AUS", "Virginia") in deals and ("USA", "NZL", "P-8A Poseidon") in deals
