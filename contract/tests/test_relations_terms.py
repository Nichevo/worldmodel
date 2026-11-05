"""The relationship scan's shared terms: p-values without scipy, false discovery rate, change kinds."""

import pytest

from worldmodel_contract import local
from worldmodel_contract import relations as rel


def test_pvalues():
    assert rel.t_pvalue(1.96, 10_000) == pytest.approx(0.05, abs=1e-3)
    assert rel.t_pvalue(2.228, 10) == pytest.approx(0.05, abs=1e-3)
    assert rel.f_pvalue(3.0, 3, 100) == pytest.approx(0.0342, abs=1e-3)
    assert rel.t_pvalue(float("nan"), 5) == 1.0 and rel.f_pvalue(-1, 2, 3) == 1.0


def test_bh():
    assert rel.bh_qvalues([0.01, 0.04, 0.03, 0.5]) == pytest.approx([0.04, 0.0533, 0.0533, 0.5], abs=1e-3)
    assert rel.bh_qvalues([]) == []


def test_change_kinds_and_units():
    assert rel.change_kind("% of GDP", True) == "diff" and rel.change_kind("persons", True) == "pct"
    assert rel.change_kind("US dollars", False) == "diff"
    assert rel.change_unit("persons", "pct") == "% change"
    assert rel.change_unit("annual %", "diff") == "change in percentage points"
    assert rel.change_unit("% of GDP", "diff") == "change in points (% of GDP)"
    assert rel.built_in("recession", "gdp_usd") and not rel.built_in("coup", "gdp_usd")


def test_settings():
    s = local.clean_settings({"relations_fdr": 0.001, "relations_indicators": "all", "relations_min_countries": 1})
    assert s["relations_fdr"] == 0.001 and s["relations_indicators"] == "all" and s["relations_min_countries"] == 5
    assert local.clean_settings({"relations_indicators": "some"})["relations_indicators"] == "on"


@pytest.mark.parametrize("x, xn, y, yn, why", [
    ("wdi_en_atm_co2e_kt", "CO2 emissions (kt)", "wdi_en_atm_co2e_pc", "CO2 emissions (metric tons per capita)", "total and per person"),
    ("gdp_usd", "GDP, current US dollars", "gdp_per_capita_usd", "GDP per person, current US dollars", "total and per person"),
    ("gdp_growth", "GDP growth", "gdp_usd", "GDP, current US dollars", "a figure and its growth"),
    ("wdi_ny_gdp_mktp_kd_zg", "GDP growth (annual %)", "wdi_ny_gdp_mktp_cd", "GDP (current US$)", "a figure and its growth"),
    ("gdp_usd", "GDP, current US dollars", "gdp_ppp", "GDP, purchasing power parity", "the same figure in other units"),
    ("wdi_sh_xpd_chex_gd_zs", "Current health expenditure (% of GDP)", "wdi_sh_xpd_chex_pc_cd",
     "Current health expenditure per capita (current US$)", "a figure and its share of GDP"),
    ("pop_total", "Population", "gdp_per_capita_usd", "GDP per person, current US dollars",
     "a per-person figure and the population it divides by"),
    ("govt_debt_gdp", "Government debt (% of GDP)", "gdp_usd", "GDP, current US dollars", "a share of GDP and GDP itself"),
    ("births", "Births", "birth_rate", "Crude birth rate", "a ratio and what it is made from"),
])
def test_built_from_each_other(x, xn, y, yn, why):
    ratios = {"birth_rate": ("births", "pop_total")}
    assert rel.built_from(x, xn, y, yn, ratios) == why
    assert rel.built_from(y, yn, x, xn, ratios) == why


@pytest.mark.parametrize("x, xn, y, yn", [
    ("inflation", "Inflation", "gdp_growth", "GDP growth"),
    ("wdi_sp_dyn_le00_in", "Life expectancy at birth, total (years)", "wdi_ny_gdp_pcap_cd", "GDP per capita (current US$)"),
    ("wdi_ms_mil_xpnd_gd_zs", "Military expenditure (% of GDP)", "wdi_se_xpd_totl_gd_zs",
     "Government expenditure on education, total (% of GDP)"),
])
def test_separately_measured_pairs_are_not_built_from_each_other(x, xn, y, yn):
    assert rel.built_from(x, xn, y, yn) is None
