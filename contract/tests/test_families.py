from worldmodel_contract import families


def ind(i, series=None):
    return {"indicator_id": i, "sources": [{"source_id": "wdi", "series": series}] if series else []}


def test_hand_listed_pairs_need_both_present():
    found = families.parents([ind("pop_total"), ind("pop_male"), ind("life_expectancy_male")])
    assert found == {"pop_male": {"parent": "pop_total", "kind": "part"}}


def test_wdi_male_female_codes_sit_under_the_total():
    found = families.parents([ind("wdi_a", "SE.PRM.CMPT.ZS"), ind("wdi_b", "SE.PRM.CMPT.MA.ZS"), ind("wdi_c", "SE.PRM.CMPT.FE.ZS"),
                              ind("wdi_d", "SL.TLF.MA.ZS")])
    assert found == {"wdi_b": {"parent": "wdi_a", "kind": "sex"}, "wdi_c": {"parent": "wdi_a", "kind": "sex"}}
