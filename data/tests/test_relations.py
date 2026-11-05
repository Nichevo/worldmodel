"""The relationship scan on a made-up warehouse: X drives Y a year later, W moves with
Y in the same year, Z is noise; recessions knock V down. The scan must find the first
three links with the right labels, leave noise alone, and write files the contract reads."""

import json
import math

import duckdb
import numpy as np
import pytest

from worldmodel_contract import local
from worldmodel_contract import relations as rel
from worldmodel_data import relations

YEARS = range(1971, 2021)


def _warehouse(path, n=60, seed=1):
    rng = np.random.default_rng(seed)
    countries = [f"C{i:02d}" for i in range(n)]
    data: dict[str, dict] = {k: {} for k in ("ind_x", "ind_y", "ind_w", "ind_z", "ind_v", rel.CONTROL)}
    events = []
    for c in countries:
        lx = ly = lw = lz = lv = 100.0
        dx_prev = 0.0
        for y in YEARS:
            g = rng.normal(2, 2)
            dx = rng.normal(0, 1)
            dy = 0.8 * dx_prev + rng.normal(0, 0.6)       # X leads Y by one year
            dw = 0.9 * dy + rng.normal(0, 0.4)             # W moves with Y, same year
            dz = rng.normal(0, 1)                          # noise
            hit = rng.random() < 0.05
            dv = rng.normal(1, 0.5) - (6 if hit else 0)
            if hit:
                events.append((f"e{c}{y}", c, "recession", f"{y}-01-01"))
            lx, ly, lw, lz, lv = lx + dx, ly + dy, lw + dw, lz + dz, lv * math.exp(dv / 100)
            for k, v in (("ind_x", lx), ("ind_y", ly), ("ind_w", lw), ("ind_z", lz), ("ind_v", lv), (rel.CONTROL, g)):
                data[k][(c, y)] = v
            dx_prev = dx
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE meta (key VARCHAR, value VARCHAR)")
    con.execute("INSERT INTO meta VALUES ('build_id', 'b1')")
    con.execute("CREATE TABLE indicators (indicator_id VARCHAR, name VARCHAR, domain VARCHAR, unit VARCHAR, "
                "frequency VARCHAR, default_on BOOLEAN)")
    units = {"ind_v": "tonnes", rel.CONTROL: "annual %"}  # the rest are "%": changes in points
    con.executemany("INSERT INTO indicators VALUES (?, ?, ?, ?, 'A', true)",
                    [(k, k.upper(), "test", units.get(k, "%")) for k in data])
    con.execute("CREATE TABLE indicator_sources (indicator_id VARCHAR, source_id VARCHAR, rank INTEGER)")
    con.executemany("INSERT INTO indicator_sources VALUES (?, 'src', 1)", [(k,) for k in data])
    con.execute("CREATE TABLE entities (entity_id VARCHAR, type VARCHAR)")
    con.executemany("INSERT INTO entities VALUES (?, 'country')", [(c,) for c in countries])
    con.execute("CREATE TABLE memberships (group_id VARCHAR, member_id VARCHAR)")
    con.executemany("INSERT INTO memberships VALUES (?, ?)",
                    [("income-high" if i % 2 else "income-low", c) for i, c in enumerate(countries)])
    con.execute("CREATE TABLE events (event_id VARCHAR, entity_id VARCHAR, kind VARCHAR, start_date DATE)")
    con.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", events)
    con.execute("CREATE TABLE series (entity_id VARCHAR, indicator_id VARCHAR, period_start DATE, freq VARCHAR, "
                "breakdown VARCHAR, variant VARCHAR, source_id VARCHAR, value DOUBLE, status VARCHAR)")
    rows = path.with_suffix(".csv")
    rows.write_text("".join(f"{c},{k},{y}-01-01,{v!r}\n" for k, d in data.items() for (c, y), v in d.items()))
    con.execute(f"INSERT INTO series SELECT column0, column1, column2::DATE, 'A', '', 'central', 'src', column3, 'E' "
                f"FROM read_csv('{rows.as_posix()}', header = false, columns = {{'column0': 'VARCHAR', 'column1': 'VARCHAR', "
                f"'column2': 'VARCHAR', 'column3': 'DOUBLE'}})")
    con.close()


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("scan")
    wh = tmp / "w.duckdb"
    _warehouse(wh)
    s = dict(local.SETTINGS)
    s.update(relations_min_countries=20, relations_min_years=10)
    summary = relations.scan(wh, tmp, "b1", s, log_line=lambda *_: None)
    return tmp, summary


def _pairs(home):
    meta = rel.latest(home)
    con = duckdb.connect()
    r = con.execute(f"SELECT * FROM read_parquet('{meta['pairs_path']}')")
    cols = [d[0] for d in r.description]
    return {(row[0], row[1]): dict(zip(cols, row)) for row in r.fetchall()}, meta


def test_finds_the_links_and_labels_them(scanned):
    home, summary = scanned
    pairs, meta = _pairs(home)
    assert meta["build_id"] == "b1" and summary["pairs_tested"] == 15  # 6 indicators
    xy = pairs[("ind_x", "ind_y")]
    assert xy["first"] == "x" and xy["best_lag"] == 1 and "first" in xy["labels"]
    assert xy["lags"][rel.MAX_LAG + 1] > 0.5  # X one year earlier
    assert xy["countries_x_first"] > xy["countries_tested"] / 2
    wy = pairs[("ind_w", "ind_y")]
    assert {"together", "holds"} <= set(wy["labels"]) and wy["r"] > 0.8 and wy["slope"] > 0
    assert all("ind_z" not in k for k in pairs), "noise must not be reported"


def test_event_study_and_files(scanned):
    home, summary = scanned
    meta = rel.latest(home)
    con = duckdb.connect()
    ev = con.execute(f"SELECT kind, indicator_id, effect_3, significant, h, effect FROM read_parquet('{meta['events_path']}') "
                     "WHERE indicator_id = 'ind_v'").fetchall()
    assert ev and ev[0][0] == "recession" and ev[0][3] and ev[0][2] < -3
    assert ev[0][5][ev[0][4].index(-1)] == 0.0
    assert summary["names"]["ind_v"]["kind"] == "pct" and summary["names"]["ind_x"]["kind"] == "diff"
    on_disk = json.loads((rel.results_dir(home) / "b1.json").read_text())
    assert on_disk["label_counts"] == summary["label_counts"]


def test_time_limit_keeps_what_is_done(tmp_path):
    wh = tmp_path / "w.duckdb"
    _warehouse(wh, n=25)
    s = dict(local.SETTINGS)
    s.update(relations_min_countries=20, relations_min_years=10, relations_max_minutes=0)  # below the range: stop at once
    out = relations.scan(wh, tmp_path, "b2", s, log_line=lambda *_: None)
    assert out["partial"] and out["pairs_tested"] <= 1 and rel.latest(tmp_path, "b2")["build_id"] == "b2"


def test_old_scans_pruned(tmp_path):
    for i in range(5):
        relations.write(tmp_path, f"b{i}", [], [], {"build_id": f"b{i}"})
    assert sorted(p.name for p in rel.results_dir(tmp_path).glob("*.json")) == ["b2.json", "b3.json", "b4.json"]
    assert rel.latest(tmp_path)["build_id"] == "b4" and rel.latest(tmp_path, "b3")["build_id"] == "b3"


def test_two_way_and_cluster_helpers():
    x = np.array([[1.0, 2.0, np.nan], [3.0, 5.0, 7.0]])
    z = relations.two_way(x)
    assert np.isnan(z[0, 2]) and abs(np.nansum(z, 1)).max() < 1e-3
    rng = np.random.default_rng(0)
    a = rng.normal(size=500)
    r, p, g = relations.corr_cluster(a - a.mean(), (a + rng.normal(size=500)) - a.mean(), np.repeat(np.arange(50), 10))
    assert r > 0.5 and p < 0.001 and g == 50


def test_scan_skipped_when_nothing_new(tmp_path):
    wh = tmp_path / "w.duckdb"
    _warehouse(wh, n=25)
    s = dict(local.SETTINGS)
    s.update(relations_min_countries=20, relations_min_years=10)
    first = relations.scan(wh, tmp_path, "b1", s, log_line=lambda *_: None)
    lines = []
    again = relations.scan(wh, tmp_path, "b2", s, log_line=lines.append)
    assert again["skipped"] and again["build_id"] == "b1" and "no new figures" in lines[0]
    assert not (rel.results_dir(tmp_path) / "b2.json").exists() and rel.latest(tmp_path, "b2")["build_id"] == "b1"
    forced = relations.scan(wh, tmp_path, "b3", s, log_line=lambda *_: None, force=True)
    assert not forced.get("skipped") and forced["inputs"] == first["inputs"]
    s.update(relations_fdr=0.1)  # a changed setting scans again
    assert not relations.scan(wh, tmp_path, "b4", s, log_line=lambda *_: None).get("skipped")
    con = duckdb.connect(str(wh))
    con.execute("UPDATE series SET value = value + 1 WHERE indicator_id = 'ind_z' AND entity_id = (SELECT min(entity_id) FROM series)")
    con.close()
    assert not relations.scan(wh, tmp_path, "b5", s, log_line=lambda *_: None).get("skipped")
    s.update(relations_only_new=False)
    assert not relations.scan(wh, tmp_path, "b6", s, log_line=lambda *_: None).get("skipped")
