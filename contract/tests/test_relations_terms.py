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
