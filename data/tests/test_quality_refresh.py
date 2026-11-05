"""After a build the refresh keeps every indicator's grade and says what changed."""

from worldmodel_contract import quality as q


def test_refresh_keeps_the_grades_and_says_what_changed(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from worldmodel_api.warehouse import SAMPLE
    from worldmodel_data import cli

    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    (tmp_path / "user").mkdir()
    (tmp_path / "user" / "indicator_stars.json").write_text('{"stars": ["pop_total"]}')
    p = SimpleNamespace(home=tmp_path)
    cli._quality_after(p, SAMPLE, "20261105T000000Z")
    saved = q.load(tmp_path, "20261105T000000Z")
    assert saved["pop_total"]["grade"] == "A"
    q.save(tmp_path, "20261101T000000Z", {**saved, "pop_total": {**saved["pop_total"], "grade": "A"}})
    worse = {**saved, "pop_total": {**saved["pop_total"], "grade": "A"}}
    monkeypatch.setattr(q, "compute", lambda con: {**worse, "pop_total": {**worse["pop_total"], "grade": "C"}})
    cli._quality_after(p, SAMPLE, "20261106T000000Z")
    out = capsys.readouterr().out
    assert "1 lost a grade" in out and "starred indicator fell from A to C: pop_total" in out
