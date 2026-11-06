"""Discover: each check on a small made-up panel, tone and category, your ratings and their
effect on ranking, settings, and the finds saved after a build."""

import numpy as np

from worldmodel_contract import discover as d
from worldmodel_contract import local

NAMES = {"NZL": "New Zealand", "AUS": "Australia", "FJI": "Fiji", "USA": "United States"}


def panel(rows: dict[str, list[float]], ind: str = "x", name: str = "Unemployment rate", unit: str = "percent", first: int = 1990):
    ents = sorted(rows)
    n = max(len(v) for v in rows.values())
    p = d.Panel(ents, list(range(first, first + n)))
    a = np.full((len(ents), n), np.nan)
    for e, vals in rows.items():
        a[p.ei[e], : len(vals)] = vals
    p.data[ind] = a
    p.meta[ind] = {"name": name, "domain": "labour", "unit": unit, "decimals": 1, "source_id": "wdi"}
    return p


def test_better_when_and_tone():
    assert d.better_when("unemployment_rate", "Unemployment rate") == "lower"
    assert d.better_when("life_expectancy", "Life expectancy") == "higher"
    assert d.better_when("net_migration", "Net migration") == "neither"
    assert d.better_when("hpi_nominal", "House prices (nominal)") == "neither"
    assert d.better_when("unemployment_rate", "Unemployment rate", {"unemployment_rate": "neither"}) == "neither"
    assert d.tone("lower", True) == "bad" and d.tone("higher", True) == "good" and d.tone("neither", True) == "neutral"
    assert d.tone("higher", None) == "neutral"
    assert d.category("labour") == "Economy" and d.category(None, "co2_per_person CO2 emissions") == "Climate"
    assert d._lc("House prices") == "house prices" and d._lc("GDP per person") == "GDP per person"


def test_records_find_highest_on_record_and_since_long_ago():
    p = panel({"NZL": [5 + 0.1 * i for i in range(30)], "AUS": [10] + [5] * 28 + [8]})
    found = {f["entities"][0]: f for f in d.records(p, NAMES, {})}
    nz = found["NZL"]
    assert "highest on record" in nz["headline"] and nz["tone"] == "bad" and nz["value"] == p.data["x"][p.ei["NZL"], 29]
    assert nz["chart"]["series"][0]["points"][-1][0] == 2019 and nz["chart"]["mark"] == [2019]
    assert "highest since 1990" in found["AUS"]["headline"]


def test_movers_need_a_change_far_outside_the_usual():
    calm = [5 + 0.1 * ((-1) ** i) for i in range(25)]
    p = panel({"NZL": calm[:-1] + [9.0], "AUS": calm})
    found = d.movers(p, NAMES, {})
    assert [f["entities"] for f in found] == [["NZL"]]
    assert "jumped" in found[0]["headline"] and found[0]["tone"] == "bad" and found[0]["kind"] == "mover"


def test_turning_points():
    rising = [float(i) for i in range(15)] + [14.0, 14.1, 13.9, 14.0, 14.05]
    p = panel({"NZL": rising}, ind="tfr", name="Fertility rate", unit="births per woman")
    found = d.turning(p, NAMES, {})
    assert found and "levelled off after 15 years of rises" in found[0]["headline"]


def test_overtakes_for_key_countries_and_rank_jumps():
    rows = {f"C{i:02d}": [100.0 - i, 100.0 - i] for i in range(45)}
    rows["NZL"] = [80.0, 90.5]   # jumps past eleven countries; the nearest one passed is named
    p = panel(rows, ind="gdp_pc", name="GDP per person", unit="US$")
    found = d.overtakes(p, {**NAMES, "C10": "Ten"}, {}, ["NZL"])
    heads = [f["headline"] for f in found]
    assert any(h.startswith("New Zealand passes Ten in GDP per person") for h in heads)
    assert any("New Zealand climbs" in h for h in heads)


def test_outliers_in_a_group():
    rows = {f"C{i}": [5.0 + 0.1 * i] for i in range(10)}
    rows["FJI"] = [30.0]
    p = panel(rows)
    found = d.outliers(p, NAMES, {}, {"oecd": list(rows)})
    assert len(found) == 1 and found[0]["headline"] == "Fiji has the highest unemployment rate in the OECD"
    assert "the OECD" in found[0]["tags"]


def test_ranking_follows_ratings_key_countries_and_never():
    finds = [
        {"key": "a", "kind": "record", "category": "Economy", "tone": "bad", "score": 0.5, "headline": "A", "entities": ["FJI"], "tags": ["Fiji", "Records"]},
        {"key": "b", "kind": "mover", "category": "People", "tone": "good", "score": 0.5, "headline": "B", "entities": ["NZL"], "tags": ["New Zealand"]},
        {"key": "c", "kind": "record", "category": "Economy", "tone": "neutral", "score": 0.45, "headline": "C", "entities": ["USA"], "tags": ["Records"]},
    ]
    st = {"ratings": {}, "tags": {}, "tones": {}, "never": [], "first_seen": {}, "kept": {}}
    r = d.ranked(finds, st, ["NZL"], 1.5, True)
    assert [f["key"] for f in r][0] == "b"  # key country lifted
    st["ratings"] = {"a": 1}
    st["kept"] = {"a": finds[0]}
    r = d.ranked(finds, st, [], 1.0, True)
    assert [f["key"] for f in r][:2] == ["a", "c"]  # records (and the tag Records) rise after an Interesting
    assert r[0]["rating"] == 1
    # A find you kept stays when it is no longer found; your tone wins; never marks the kind.
    st["tones"] = {"c": "good"}
    st["never"] = ["mover"]
    r = {f["key"]: f for f in d.ranked(finds[1:], st, [], 1.0, False)}
    assert r["a"]["stale"] and r["c"]["tone"] == "good" and r["b"]["never"]


def test_user_state_and_saved_finds(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    st = d.user_state()
    assert st["ratings"] == {} and st["last_visit"] is None
    st["ratings"]["x"] = 1
    d.save_user_state(st)
    assert d.user_state()["ratings"] == {"x": 1}
    for b in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z", "20260104T000000Z", "20260105T000000Z", "20260106T000000Z"):
        d.save(tmp_path, b, [{"key": b}])
    assert len(list(d.folder(tmp_path).glob("*.json"))) == 5
    assert d.load_saved(tmp_path)["build_id"] == "20260106T000000Z"
    assert d.load_saved(tmp_path, "nope", exact=True) is None and d.load_saved(tmp_path, "nope")["build_id"] == "20260106T000000Z"


def test_settings_are_checked():
    s = local.clean_settings({"discover_key_countries": "NZL, aus,bad id!", "discover_keep": 10, "discover_key_boost": 9,
                              "discover_better": {"unemployment_rate": "higher", "x": "sideways", "bad id!": "lower"},
                              "news_feeds": "rnz,BBC", "news_reliefweb_app": "  my app  "})
    assert s["discover_key_countries"] == "NZL,aus"
    assert s["discover_keep"] == 50 and s["discover_key_boost"] == 5
    assert s["discover_better"] == {"unemployment_rate": "higher"}
    assert s["news_feeds"] == "rnz,bbc" and s["news_reliefweb_app"] == "my app"


def test_compute_on_the_sample_warehouse(tmp_path, monkeypatch):
    import duckdb

    from worldmodel_api.warehouse import SAMPLE

    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    con = duckdb.connect(str(SAMPLE), read_only=True)
    try:
        finds = d.compute(con, tmp_path, {"discover_keep": 80})
    finally:
        con.close()
    assert len(finds) <= 80
    assert len({f["key"] for f in finds}) == len(finds)
    for f in finds:
        assert f["kind"] in d.KINDS and f["category"] in d.CATEGORIES and f["tone"] in d.TONES and 0 <= f["score"] <= 1
        assert f["headline"] and isinstance(f["tags"], list)
