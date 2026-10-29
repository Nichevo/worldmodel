from datetime import date

from worldmodel_contract import SCHEMA_VERSION, catalogue, is_compatible
from worldmodel_contract.queries import SeriesQuery, series_sql, stream_query


def test_catalogues_are_consistent():
    assert catalogue.validate() == []


def test_crosswalk_covers_the_world():
    ents = catalogue.entities()
    countries = [e for e in ents.values() if e.type == "country"]
    assert len(countries) >= 240
    world = {m["member_id"] for m in catalogue.memberships() if m["group_id"] == "world"}
    assert {"NZL", "CHN", "XKX", "TWN"} <= world
    assert not any(ents[m].type == "historical_country" for m in world)


def test_codes_map_to_one_entity_at_a_time():
    seen = {}
    for c in catalogue.entity_codes():
        key = (c["scheme"], c["code"])
        assert key not in seen or c["valid_from"] != seen[key], key
        seen[key] = c["valid_from"]


def test_bloc_membership_dates():
    eu = [m for m in catalogue.memberships() if m["group_id"] == "eu"]
    gbr = next(m for m in eu if m["member_id"] == "GBR")
    assert (gbr["valid_from"], gbr["valid_to"]) == ("1973-01-01", "2020-01-31")

    def members(group, on):
        return {m["member_id"] for m in catalogue.memberships() if m["group_id"] == group
                and (m["valid_from"] or "") <= on and (m["valid_to"] or "9999") >= on}

    assert len(members("eu", "1990-07-01")) == 12
    assert len(members("eu", "2024-07-01")) == 27
    assert "FIN" in members("nato", "2024-01-01") and "SWE" not in members("nato", "2024-01-01")
    assert members("usmca", "2019-07-01") == set() and members("nafta", "2019-07-01") == {"USA", "CAN", "MEX"}


def test_every_indicator_has_plain_language_fields():
    for i in catalogue.indicators().values():
        assert i.name and i.description and i.synonyms, i.id


def test_schema_version_rules():
    assert is_compatible(SCHEMA_VERSION)
    major, minor, _ = (int(x) for x in SCHEMA_VERSION.split("."))
    assert is_compatible(f"{major}.{minor + 1}.0")
    assert not is_compatible(f"{major + 1}.0.0")
    assert not is_compatible(f"{major}.{minor}.0", f"{major}.{minor + 1}.0")


def test_series_sql_parameters_line_up():
    sql, params = series_sql(SeriesQuery("tfr", ["NZL", "AUS"], start=1990, end=2000, as_of=date(2025, 1, 1)))
    assert sql.count("?") == len(params)
    st = next(s for s in catalogue.streams() if s["name"] == "g7-gdp-growth")
    sql, params = series_sql(stream_query(st))
    assert sql.count("?") == len(params) and "g7" in params
