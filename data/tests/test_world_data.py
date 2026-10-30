"""World data sources: World Bank WDI (with income groups), OWID energy and OWID charts."""

from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "imf_weo", "world_bank_wdi", "owid_energy", "owid_grapher"):
        CONNECTORS[source]().ingest(store, FIXTURES / source)
    result = build(home)
    return home, duckdb.connect(str(result.path), read_only=True)


def test_wdi_series_land_under_catalogue_and_own_ids(built):
    _, con = built
    # A series the catalogue maps is a second source for its indicator.
    got = dict(con.execute("""SELECT source_id, value FROM series WHERE entity_id = 'NZL' AND indicator_id = 'pop_total'
        AND period_start = DATE '2023-01-01' AND variant = 'central'""").fetchall())
    assert {"un_wpp", "world_bank_wdi"} <= set(got) and got["world_bank_wdi"] == pytest.approx(got["un_wpp"], rel=0.02)
    # The main ones get plain ids and start switched on; the rest wdi_<code>, switched off.
    inds = {r[0]: r for r in con.execute(
        "SELECT indicator_id, name, default_on, domain, unit, synonyms FROM indicators").fetchall()}
    assert inds["military_spending_gdp"][2] and inds["military_spending_gdp"][3] == "military"
    assert inds["unemployment"][2]
    assert not inds["wdi_ag_lnd_agri_zs"][2] and inds["wdi_ag_lnd_agri_zs"][4] == "% of land area"
    assert "AG.LND.AGRI.ZS" in inds["wdi_ag_lnd_agri_zs"][5]
    assert inds["pop_total"][2]  # catalogue indicators stay on
    assert con.execute("SELECT count(*) FROM series WHERE indicator_id = 'military_spending_gdp' "
                       "AND source_id = 'world_bank_wdi'").fetchone()[0] > 100


def test_income_groups_are_regions(built):
    _, con = built
    members = dict(con.execute("""SELECT group_id, count(*) FROM memberships WHERE group_id LIKE 'income-%'
        GROUP BY 1""").fetchall())
    assert set(members) == {"income-high", "income-upper-middle", "income-lower-middle", "income-low"}
    assert sum(members.values()) > 150
    # The World Bank's own income-group values are kept; other WB aggregates (EU, regions) are not.
    hic = con.execute("""SELECT is_aggregate FROM series WHERE entity_id = 'income-high' AND indicator_id = 'military_spending_gdp'
        AND period_start = DATE '2020-01-01'""").fetchall()
    assert hic == [(False,)]
    assert not con.execute("SELECT count(*) FROM series WHERE source_id = 'world_bank_wdi' AND entity_id = 'eu' "
                           "AND NOT is_aggregate").fetchone()[0]
    # Other sources' values are added up for income groups too.
    pop = con.execute("""SELECT value, is_aggregate FROM series WHERE entity_id = 'income-low' AND indicator_id = 'pop_total'
        AND source_id = 'un_wpp' AND period_start = DATE '2023-01-01' AND variant = 'central'""").fetchone()
    assert pop[1] and pop[0] > 1e8
    assert not con.execute("SELECT count(*) FROM unmapped_codes WHERE source_id = 'world_bank_wdi' "
                           "AND source_code IN ('EUU', 'EAS')").fetchone()[0]


def test_energy_and_conflict_series(built):
    _, con = built
    v = con.execute("""SELECT value FROM series WHERE entity_id = 'NZL' AND indicator_id = 'renewables_share_elec'
        AND period_start = DATE '2020-01-01'""").fetchone()[0]
    assert 70 < v < 95
    inds = {r[0]: r for r in con.execute(
        "SELECT indicator_id, default_on, agg_method, agg_numerator, unit FROM indicators").fetchall()}
    assert inds["renewables_share_elec"][1:4] == (True, "ratio", "renewables_electricity")
    assert inds["electricity_generation"][2] == "sum" and inds["electricity_generation"][4] == "TWh"
    assert "elec_lifecycle_emissions" in inds and "greenhouse_gas_emissions" not in inds
    assert "population" not in inds and "gdp" not in inds
    # Continents get shares recomputed from the amounts.
    eu = con.execute("""SELECT value FROM series WHERE entity_id = 'eu' AND indicator_id = 'renewables_share_elec'
        AND period_start = DATE '2020-01-01'""").fetchone()
    assert eu and 20 < eu[0] < 60
    # OWID charts: countries and the World; OWID's own continents are left out.
    rate = dict(con.execute("""SELECT entity_id, value FROM series WHERE indicator_id = 'owid_death_rate_in_armed_conflicts'
        AND period_start = DATE '2022-01-01' AND NOT is_aggregate""").fetchall())
    assert rate == {"UKR": 198.4, "NZL": 0.0, "world": 3.8}
    assert inds["owid_death_rate_in_armed_conflicts"][4] == "deaths per 100,000 people"


def test_build_report_lists_divergent_sources(built):
    _, con = built
    checks = {r[0]: r for r in con.execute("SELECT check_id, status, detail FROM build_checks").fetchall()}
    assert checks["sources:divergence"][1] in ("pass", "info")


def test_wdi_falls_back_to_the_indicators_api(tmp_path, monkeypatch):
    import json

    import httpx

    from worldmodel_data.connectors import world_bank_wdi

    monkeypatch.setattr(world_bank_wdi, "API_PAUSE", 0)
    asked = []
    economies = [
        {"id": "NZL", "iso2Code": "NZ", "name": "New Zealand", "region": {"id": "EAS", "value": "East Asia & Pacific"},
         "incomeLevel": {"id": "HIC", "value": "High income"}},
        {"id": "NER", "iso2Code": "NE", "name": "Niger", "region": {"id": "SSF", "value": "Sub-Saharan Africa "},
         "incomeLevel": {"id": "LIC", "value": "Low income"}},
        {"id": "WLD", "iso2Code": "1W", "name": "World", "region": {"id": "NA", "value": "Aggregates"},
         "incomeLevel": {"id": "NA", "value": "Aggregates"}},
    ]

    def rows(code, name):
        return [{"indicator": {"id": code, "value": name}, "country": {"id": e["iso2Code"], "value": e["name"]},
                 "countryiso3code": e["id"], "date": str(y), "value": None if y == 2023 else 1.5 + i,
                 "unit": "", "obs_status": "", "decimal": 1} for i, e in enumerate(economies) for y in (2022, 2023)]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if "databank.worldbank.org" in url:
            return httpx.Response(403, content=b"Forbidden")
        path = request.url.path
        if path == "/v2/country":
            return httpx.Response(200, json=[{"page": 1, "pages": 1, "total": 3}, economies])
        code = path.rsplit("/", 1)[-1]
        if code == "MS.MIL.XPND.GD.ZS":
            return httpx.Response(200, json=[{"page": 1, "pages": 1}, rows(code, "Military expenditure (% of GDP)")])
        if code == "SP.POP.TOTL":
            return httpx.Response(200, json=[{"page": 1, "pages": 1}, rows(code, "Population, total")])
        return httpx.Response(200, json=[{"message": [{"id": "120", "value": "Invalid value"}]}])

    store = VintageStore(Paths(tmp_path / "var"))
    conn = CONNECTORS["world_bank_wdi"](httpx.Client(transport=httpx.MockTransport(handler)))
    manifest, new = conn.ingest(store)
    assert new and "api.worldbank.org" in manifest.origin and manifest.row_count == 6
    assert any("source=2" in u and "/indicator/SP.POP.TOTL" in u for u in asked)
    out = store.vintage_dir("world_bank_wdi", manifest.vintage)
    inds = {i["id"]: i for i in json.loads((out / "indicators.json").read_text())}
    assert inds["military_spending_gdp"]["domain"] == "military" and inds["military_spending_gdp"]["unit"] == "% of GDP"
    groups = {(m["group_id"], m["member_id"]) for m in json.loads((out / "memberships.json").read_text())}
    assert groups == {("income-high", "NZL"), ("income-low", "NER")}
    con = duckdb.connect()
    got = con.execute(f"""SELECT scheme, source_code, indicator_id, value FROM read_parquet('{(out / "observations.parquet").as_posix()}')
        ORDER BY 2, 3""").fetchall()
    assert ("wdi", "WLD", "pop_total", 3.5) in got and ("iso3", "NZL", "military_spending_gdp", 1.5) in got
    # The same answers again make the same file: no new vintage.
    again, new_again = CONNECTORS["world_bank_wdi"](httpx.Client(transport=httpx.MockTransport(handler))).ingest(store)
    assert not new_again and again.vintage == manifest.vintage
