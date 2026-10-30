"""End to end on small fixtures: fetch, vintages, build, gates, swap, failure handling."""

import gzip
import shutil
from pathlib import Path

import duckdb
import pytest

from worldmodel_data.build import BuildFailed, build
from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def home(tmp_path):
    return Paths(tmp_path / "var")


def fetch_all(home: Paths, wpp_dir: Path = FIXTURES / "un_wpp"):
    store = VintageStore(home)
    wpp, new_wpp = CONNECTORS["un_wpp"]().ingest(store, wpp_dir)
    imf, new_imf = CONNECTORS["imf_weo"]().ingest(store, FIXTURES / "imf_weo")
    return wpp, imf, new_wpp, new_imf


def test_fetch_stores_vintages_and_skips_unchanged(home):
    wpp, imf, new_wpp, new_imf = fetch_all(home)
    assert (wpp.vintage, imf.vintage) == ("2024", "2015-04")
    assert new_wpp and new_imf and wpp.row_count > 1000
    assert (home.home / wpp.raw_dir / "WPP2024_Demographic_Indicators_Medium.csv.gz").exists()
    staged = duckdb.sql(f"SELECT * FROM '{home.vintages / 'un_wpp' / '2024' / 'observations.parquet'}'")
    assert {"pop_total", "tfr", "pop_by_age_sex", "pop_share_65_plus"} <= {r[0] for r in staged.select("indicator_id").distinct().fetchall()}
    # Same content again: no new vintage.
    _, _, again_wpp, again_imf = fetch_all(home)
    assert not again_wpp and not again_imf


def test_build_passes_gates_and_goes_live(home):
    fetch_all(home)
    result = build(home)
    assert home.current_build() == result.path
    con = duckdb.connect(str(result.path), read_only=True)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    assert meta["schema_version"]
    world, = con.execute("""SELECT value FROM series WHERE entity_id = 'world' AND indicator_id = 'pop_total'
        AND period_start = DATE '2023-01-01'""").fetchone()
    assert 8.0e9 < world < 8.2e9
    eu = con.execute("""SELECT value, members_total, coverage FROM series WHERE entity_id = 'eu'
        AND indicator_id = 'pop_total' AND period_start = DATE '2023-01-01'""").fetchone()
    assert eu[1] == 27 and eu[2] == pytest.approx(1.0) and 4.4e8 < eu[0] < 4.6e8
    statuses = dict(con.execute("SELECT status, count(*) FROM build_checks GROUP BY 1").fetchall())
    assert statuses.get("fail", 0) == 0
    assert not {r[0] for r in con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()} & {"src", "int"}


def test_failed_gate_keeps_previous_build(home, tmp_path):
    fetch_all(home)
    good = build(home).path

    # A new WPP vintage that has lost China: the world total no longer adds up.
    broken = tmp_path / "broken_wpp"
    broken.mkdir()
    for f in (FIXTURES / "un_wpp").iterdir():
        with gzip.open(f, "rt") as src, gzip.open(broken / f.name, "wt") as dst:
            for line in src:
                if ",156,,CHN," not in line:
                    dst.write(line)
    CONNECTORS["un_wpp"]().ingest(VintageStore(home), broken, release="2024")

    with pytest.raises(BuildFailed) as exc:
        build(home)
    assert home.current_build() == good
    report = exc.value.report.read_text()
    assert "assert_world_population_matches_countries" in report
    assert "## Failing rows: dbt:assert_world_population_matches_countries" in report  # shows what broke
    assert list(home.builds.glob("*.failed.duckdb"))


def test_refresh_skips_downloads_the_server_says_are_unchanged(home):
    import httpx

    served = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        etag = f'"{name}-v1"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        if not (FIXTURES / "un_wpp" / name).exists():
            return httpx.Response(404)  # the optional other-variants file: only warns
        served.append(name)
        return httpx.Response(200, content=(FIXTURES / "un_wpp" / name).read_bytes(), headers={"ETag": etag})

    store = VintageStore(home)
    first, new = CONNECTORS["un_wpp"](httpx.Client(transport=httpx.MockTransport(handler))).ingest(store)
    assert new and len(served) == 2
    again, new_again = CONNECTORS["un_wpp"](httpx.Client(transport=httpx.MockTransport(handler))).ingest(store)
    assert not new_again and again.vintage == first.vintage
    assert len(served) == 2  # nothing downloaded the second time


def test_busy_server_is_tried_again(home, monkeypatch, tmp_path):
    import httpx

    from worldmodel_data.connectors import base

    waits, calls = [], []
    monkeypatch.setattr(base.time, "sleep", waits.append)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "7"} if len(calls) == 1 else {})
        return httpx.Response(200, content=b"ok")

    conn = CONNECTORS["imf_weo_history"](httpx.Client(transport=httpx.MockTransport(handler)))
    conn.get("https://example.org/file", tmp_path / "file")
    assert (tmp_path / "file").read_bytes() == b"ok" and waits == [7, base.RETRY_WAITS[1]]


def test_build_logs_changes_disk_and_storage(home, monkeypatch):
    import json

    from typer.testing import CliRunner

    from worldmodel_contract import local
    from worldmodel_data.cli import app

    monkeypatch.setenv("WORLDMODEL_HOME", str(home.home))
    monkeypatch.delenv("WORLDMODEL_USER_DIR", raising=False)
    fetch_all(home)
    runner = CliRunner()
    first = runner.invoke(app, ["build"])
    assert first.exit_code == 0, first.output
    assert "Whole data folder:" in first.output
    second = runner.invoke(app, ["build"])
    assert second.exit_code == 0, second.output
    log = [json.loads(line) for line in local.refresh_log_path(home.home).read_text().splitlines()]
    assert [r["kind"] for r in log] == ["build", "build"]
    wpp = {s["source_id"]: s for s in log[0]["sources"]}["un_wpp"]
    assert wpp["added"] == wpp["rows"] > 1000
    again = {s["source_id"]: s for s in log[1]["sources"]}["un_wpp"]
    assert again["added"] == again["changed"] == again["removed"] == 0
    assert log[1]["disk"]["builds"] > 0 and log[1]["checks"]["fail"] == 0
    assert "## Storage" in (home.reports / f"{log[1]['build_id']}.md").read_text()
    assert [r["build_id"] for r in local.read_refresh_log(home.home)] == [r["build_id"] for r in log]


def test_free_space_keeps_the_newest_downloads(home):
    from worldmodel_contract import local

    for stamp in ("20250101T000000Z", "20250601T000000Z", "20260101T000000Z"):
        d = home.raw / "imf_weo" / "2025-10" / stamp
        d.mkdir(parents=True)
        (d / "a.xls").write_bytes(b"x" * 10)
    assert [f["fetched"] for f in local.freeable_raw(home.home)] == ["20250101T000000Z"]
    assert local.free_raw(home.home)["freed_bytes"] == 10
    assert sorted(p.name for p in (home.raw / "imf_weo" / "2025-10").iterdir()) == ["20250601T000000Z", "20260101T000000Z"]
