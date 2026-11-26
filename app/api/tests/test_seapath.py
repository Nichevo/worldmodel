"""The way by sea to a port: searoute when installed, else no path (callers keep the straight line)."""

from __future__ import annotations

import sys
import types

from worldmodel_api import seapath


def test_sea_path_uses_searoute(monkeypatch):
    asked = []

    def fake(o, d, **kw):
        asked.append((o, d, kw))
        return {"geometry": {"coordinates": [o, [150.0, -30.0], d]},
                "properties": {"length": 1234.4, "traversed_passages": ["malacca"]}}

    monkeypatch.setitem(sys.modules, "searoute", types.SimpleNamespace(searoute=fake))
    seapath._route.cache_clear()
    got = seapath.sea_path(174.78, -36.84, 103.84, 1.26)
    assert got == {"coords": [[174.78, -36.84], [150.0, -30.0], [103.84, 1.26]], "nm": 1234, "passages": ["malacca"]}
    assert asked[0][2]["units"] == "naut" and asked[0][2]["append_orig_dest"] is True
    seapath.sea_path(174.78, -36.84, 103.84, 1.26)  # kept: not asked again
    assert len(asked) == 1
    seapath._route.cache_clear()


def test_sea_path_without_searoute_or_path(monkeypatch):
    monkeypatch.setitem(sys.modules, "searoute", None)  # import fails
    seapath._route.cache_clear()
    assert seapath.sea_path(0, 0, 1, 1) is None and not seapath.available()

    def boom(*a, **k):
        raise ValueError("no path")

    monkeypatch.setitem(sys.modules, "searoute", types.SimpleNamespace(searoute=boom))
    seapath._route.cache_clear()
    assert seapath.sea_path(0, 0, 1, 1) is None
    seapath._route.cache_clear()


def test_sea_path_soon_never_waits(monkeypatch):
    import time as _t

    def fake(o, d, **kw):
        return {"geometry": {"coordinates": [o, d]}, "properties": {"length": 99.0, "traversed_passages": []}}

    monkeypatch.setitem(sys.modules, "searoute", types.SimpleNamespace(searoute=fake))
    seapath._route.cache_clear()
    seapath._known.clear()
    assert seapath.sea_path_soon(170.1, -40.1, 174.78, -36.84) is None  # queued
    for _ in range(50):
        if seapath.sea_path_soon(170.1, -40.1, 174.78, -36.84):
            break
        _t.sleep(0.02)
    assert seapath.sea_path_soon(170.1, -40.1, 174.78, -36.84)["nm"] == 99
    seapath._known.clear()
    seapath._route.cache_clear()


def test_ship_feature_carries_length():
    from worldmodel_api.live import _ship_feature

    v = {"id": 1, "lat": -36.8, "lon": 174.8, "seen": 1}
    assert "length_m" not in _ship_feature(v)["properties"]
    assert _ship_feature(v, {1: {"length_m": 300}})["properties"]["length_m"] == 300
    assert _ship_feature({**v, "length_m": 25}, {1: {"length_m": 300}})["properties"]["length_m"] == 25
