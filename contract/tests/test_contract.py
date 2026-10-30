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


def test_problems_count_repeats_and_close_once_a_run_passes(tmp_path):
    import json

    from worldmodel_contract import local

    log = local.refresh_log_path(tmp_path)
    log.parent.mkdir(parents=True)
    (tmp_path / "warehouse" / "reports").mkdir()
    # An older run logged before failures were recorded: they come from its report.
    (tmp_path / "warehouse" / "reports" / "B1.md").write_text(
        "# Build B1\n\nResult: FAILED, not swapped in\nFile: B1.failed.duckdb\n\n| Check | Kind | Status | Detail |\n"
        "| --- | --- | --- | --- |\n| dbt:within_indicator_bounds_observations_ | dbt_test | fail | 2 failing row(s) |\n"
        "\n## Failing rows: dbt:within_indicator_bounds_observations_\n\n- gdp_growth KWT: 1 row(s), 1992-1992\n")
    bounds = {"check_id": "dbt:within_indicator_bounds_observations_", "kind": "dbt_test",
              "detail": "1 failing row(s)", "examples": ["gdp_growth STP: 1 row(s), 2012-2012"]}
    runs = [
        {"kind": "refresh", "status": "failed", "started_at": "2026-10-01T00:00:00+00:00", "build_id": "B1",
         "error": "1 validation gate(s) failed", "sources": [{"source_id": "imf_weo", "status": "error", "error": "HTTP 403"}]},
        {"kind": "build", "status": "failed", "started_at": "2026-10-02T00:00:00+00:00", "build_id": "B2",
         "error": "1 validation gate(s) failed", "failures": [bounds], "sources": []},
        {"kind": "refresh", "status": "ok", "started_at": "2026-10-03T00:00:00+00:00", "build_id": "B3",
         "sources": [{"source_id": "imf_weo", "status": "error", "error": "HTTP 403"}]},
        {"kind": "build", "status": "failed", "started_at": "2026-10-04T00:00:00+00:00", "build_id": "B4",
         "error": "1 validation gate(s) failed", "failures": [bounds], "sources": []},
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in runs))
    found = {p["key"]: p for p in local.problems(tmp_path)}
    b = found["check:dbt:within_indicator_bounds_observations_"]
    assert b["title"] == "Values outside the plausible range" and b["times"] == 3 and b["open"]
    assert b["in_a_row"] == 1 and b["first_seen"].startswith("2026-10-01") and b["examples"][0].startswith("gdp_growth STP")
    f = found["fetch:imf_weo"]
    assert f["times"] == 2 and f["open"] and f["in_a_row"] == 2 and f["summary"] == "HTTP 403"
    # A later run that fetches the source and passes closes both.
    log.write_text(log.read_text() + json.dumps({"kind": "refresh", "status": "ok", "started_at": "2026-10-05T00:00:00+00:00",
                                                 "sources": [{"source_id": "imf_weo", "status": "unchanged"}]}) + "\n")
    assert not any(p["open"] for p in local.problems(tmp_path))
