"""Pundits: Prediction Archive pages saved by hand (made-up fixtures in the site's layout),
read and built into the pundits and pundit_calls tables."""

from datetime import date
from pathlib import Path

import duckdb
import pytest
from worldmodel_data.build import build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.connectors.pundits import page_kind, parse_prediction, parse_predictor, parse_ranking, parse_search
from worldmodel_data.vintage_store import VintageStore

FIX = Path(__file__).parent / "fixtures" / "prediction_archive"
Z = "01a05faa-0000-7000-8000-000000000001"
W = "01a05faa-0000-7000-8000-000000000003"


def page(name: str) -> str:
    return (FIX / f"{name} _ PredictionArchive.htm").read_text(encoding="utf-8")


def test_page_kinds():
    assert page_kind(page("Top Predictors"))[0] == "ranking"
    assert page_kind(page("Sample Pundit")) == ("predictor", "Sample Pundit")
    assert page_kind(page("Search"))[0] == "search"
    assert page_kind("<html>something else</html>") == (None, "")


def test_ranking():
    rows = parse_ranking(page("Top Predictors"))
    assert len(rows) == 3
    z = rows[2]
    assert z["predictor_id"] == Z and z["rank"] == 3 and z["evaluated"] == 2596 and z["correct"] == 1003
    assert z["incorrect"] == 1057 and z["indeterminate"] == 536 and z["total"] == 5005 and abs(z["accuracy"] - 0.487) < 1e-9
    assert rows[0]["name"] == "Kea Forecasting Ltd"


def test_predictor_page():
    p = parse_predictor(page("Sample Pundit"))
    assert p["predictor_id"] == Z and p["about"].startswith("Sample Pundit is a made-up")
    assert (p["correct"], p["incorrect"], p["indeterminate"], p["evaluated"], p["total"], p["pending"]) == (1003, 1057, 536, 2596, 5005, 2409)
    calls = {c["title"]: c for c in p["calls"]}
    five = calls["New Zealand will leave the Five Eyes within a decade"]
    assert five["outcome"] == "pending" and five["next_check"] == date(2027, 3, 24) and five["made"] == date(2022, 3, 24)
    assert calls["Oil will fall to around $30 a barrel within a year"]["outcome"] == "incorrect"


def test_prediction_page():
    c = parse_prediction(page("The Reserve Bank Of New Zealand Will Cut Rates Twice In 2026"))
    assert c["predictor_id"] == W and c["predictor"] == "Wellington Economist" and c["made"] == date(2026, 6, 19)
    assert c["outcome"] == "correct" and c["evaluated"] == date(2026, 11, 10) and c["checked_against"] == 2
    assert c["source_url"] == "https://example.org/rates-outlook" and c["source_title"] == "Rates outlook & more"
    assert c["horizon"] == "By the end of 2026" and c["verbatim"] == "We expect two more cuts this year."


def test_search_page():
    q, items = parse_search(page("Search"))
    assert q == "New Zealand" and len(items) == 2 and items[1]["outcome"] is None and items[1]["made"] == date(2026, 9, 9)


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    home = Paths(tmp_path_factory.mktemp("w") / "var")
    store = VintageStore(home)
    for source in ("un_wpp", "prediction_archive"):
        CONNECTORS[source]().ingest(store, FIX if source == "prediction_archive" else Path(__file__).parent / "fixtures" / source)
    return duckdb.connect(str(build(home).path), read_only=True)


def test_built_tables(con):
    who = {r[0]: r for r in con.execute("SELECT name, accuracy, correct, pending, total, calls_held, from_site, site_rank, url FROM pundits").fetchall()}
    assert set(who) >= {"Sample Pundit", "Kea Forecasting Ltd", "Wellington Economist"}
    z = who["Sample Pundit"]
    assert abs(z[1] - 1003 / 2060) < 1e-9 and z[3] == 2409 and z[4] == 5005 and z[5] == 3 and z[6] and z[7] == 3
    assert z[8] == f"https://predictionarchive.com/predictors/{Z}/detail"
    calls = {r[0]: r for r in con.execute("SELECT title, outcome, countries, url, predictor FROM pundit_calls").fetchall()}
    # The same call on the forecaster's page and in search results is one call, keeping its grade.
    five = calls["New Zealand will leave the Five Eyes within a decade"]
    assert five[1] == "pending" and "NZL" in five[2] and five[3].endswith("/predictions/01a05ff8-0000-7000-8000-00000000000a/detail")
    rbnz = [r for t, r in calls.items() if t.lower().startswith("the reserve bank of new zealand")][0]
    assert rbnz[1] == "correct" and "NZL" in rbnz[2] and "search?q=" in rbnz[3]
    assert "AUS" in calls["Australia will build nuclear submarines at home by 2030"][2]
    assert len(calls) == 5
