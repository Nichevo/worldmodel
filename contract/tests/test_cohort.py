"""The population what-if model: life tables, ageing, births, migration and the UN match."""

import pytest

from worldmodel_contract import cohort as c


def flat(n: float = 1000.0) -> c.Pyramid:
    return c.Pyramid([n] * 21, [n] * 21)


def raw(years, tfr=2.0, e0=75.0, mig=0.0, **extra):
    return {"tfr": {y: tfr for y in years}, "e0_male": {y: e0 for y in years}, "e0_female": {y: e0 for y in years},
            "net_migration": {y: mig for y in years}, **extra}


def test_life_tables_hit_the_asked_life_expectancy():
    for e0 in (35, 60, 72.5, 85, 92):
        assert c.table_for(e0).e0 == pytest.approx(e0, abs=0.02)
    assert c.table_for(50).L[0] < c.table_for(80).L[0]  # more babies die where life is shorter


def test_without_births_or_migration_people_only_age():
    years = range(2000, 2011)
    run = c.project(2000, flat().male, flat().female, c.fill_paths(raw(years, tfr=0.0, e0=95.0), 2000, 2010), 2010)
    a, b = run[0], run[5]
    assert b.male[30] == pytest.approx(a.male[25], rel=0.01)  # five years older, nearly all alive
    assert sum(b.male[:5]) == 0 and b.births == 0
    assert run[-1].total < run[0].total


def test_births_follow_fertility_and_sex_ratio():
    years = range(2000, 2002)
    run = c.project(2000, flat().male, flat().female,
                    c.fill_paths(raw(years, tfr=2.0, srb={y: 105.0 for y in years}), 2000, 2001), 2001)
    women = sum(flat().female[3:10]) / 1  # 15-49 in five-year groups: 7 groups of 1000
    assert run[1].births == pytest.approx(2.0 / 35 * women, rel=0.03)  # flat ages: TFR spread over 35 years
    assert run[1].male[0] / run[1].female[0] == pytest.approx(1.05, rel=0.01)


def test_migration_adds_people_mostly_young_adults():
    years = range(2000, 2002)
    p = c.fill_paths(raw(years, tfr=0.0, mig=10_000), 2000, 2001)
    with_mig = c.project(2000, flat().male, flat().female, p, 2001)[1]
    none = c.project(2000, flat().male, flat().female, p, 2001, c.Levers(migration=0))[1]
    assert with_mig.total - none.total == pytest.approx(10_000, rel=1e-6)
    added = [a - b for a, b in zip(with_mig.male, none.male)]
    assert added.index(max(added)) in range(18, 30)


def test_whatif_defaults_equal_the_un_and_levers_change_it():
    years = range(2020, 2051)
    un = {y: c.Pyramid([1100.0] * 21, [1100.0] * 21) for y in (2030, 2040, 2050)}
    totals = {y: 44_000.0 for y in years}
    base = c.whatif(2020, flat(), raw(years), 2050, c.Levers(), un, totals)
    assert base["scenario"] == base["baseline"]
    assert base["pyramids"][2040]["baseline"]["male"] == un[2040].male  # UN pyramid where held
    assert base["baseline"][5] == pytest.approx(44_000)  # else the UN total
    assert base["raw_error"]["worst_total_pct"] is not None
    up = c.whatif(2020, flat(), raw(years), 2050, c.Levers(tfr=1.0, phase=0), un, totals)
    assert up["scenario"][-1] > up["baseline"][-1]
    assert up["inputs"]["tfr"]["scenario"][3] == pytest.approx(3.0)
    ramp = c.whatif(2020, flat(), raw(years), 2050, c.Levers(e0=10, phase=10), un, totals)
    assert ramp["inputs"]["e0"]["scenario"][5] == pytest.approx(80.0)  # half way through the phase-in


def test_tuning_to_un_births_and_deaths():
    years = range(2000, 2011)
    r = raw(years, births={y: 900.0 for y in years}, deaths={y: 500.0 for y in years})
    tune = {}
    run = c.project(2000, flat().male, flat().female, c.fill_paths(r, 2000, 2010), 2010, tune=tune)
    assert [round(y.births) for y in run[1:]] == [900] * 10
    assert run[3].deaths == pytest.approx(500, rel=0.02)
    assert set(tune) == set(range(2000, 2010))


def test_missing_inputs_are_held_and_flagged():
    p = c.fill_paths({"tfr": {2020: 1.5, 2025: 1.4}, "e0_male": {2020: 80}, "e0_female": {2020: 84}}, 2020, 2030)
    assert p.values["tfr"][2024] == 1.5 and p.values["tfr"][2030] == 1.4
    assert p.held == {"tfr": 2025, "e0_male": 2020, "e0_female": 2020, "net_migration": 2020}
    assert p.values["mac"][2030] == c.DEFAULTS["mac"]
    with pytest.raises(ValueError):
        c.fill_paths({}, 2020, 2030)


def test_summary():
    s = c.summary(flat())
    assert s["share_0_14"] == pytest.approx(300 / 21) and s["median_age"] == pytest.approx(52.5)
