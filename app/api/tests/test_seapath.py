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
