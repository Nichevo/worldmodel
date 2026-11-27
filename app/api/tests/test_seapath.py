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


def test_along_a_path_and_across_the_date_line():
    from worldmodel_api.live import along

    path = [[179.0, 0.0], [-179.0, 0.0]]  # 2 degrees of longitude = 120 NM, across 180
    lon, lat, end = along(path, 60)
    assert abs(abs(lon) - 180) < 0.01 and not end
    assert along(path, 500)[2] is True and along(path, 500)[0] == -179.0


def test_quiet_ships_moved_along_or_left_where_heard(tmp_path, monkeypatch):
    import time as _t

    from worldmodel_api import live, seapath
    from worldmodel_api.shipstore import ShipStore

    now = _t.time()
    s = live.Ships(store=ShipStore(tmp_path / "ships"), settings=lambda: {"ships_quiet_days": 3})
    port = {"name": "Auckland", "lon": 175.0, "lat": -36.0, "locode": "NZAKL"}
    s.ports_fn = lambda: {"code": {"NZAKL": port}, "name": {"AUCKLAND": port}}
    s.store.details = {
        1: {"lat": -36.0, "lon": 170.0, "speed_kn": 10, "destination": "NZAKL", "last_seen": now - 6 * 3600, "name": "GOING"},
        2: {"lat": -40.0, "lon": 172.0, "speed_kn": 0, "last_seen": now - 2 * 86400, "name": "STILL"},
        3: {"lat": -40.0, "lon": 172.0, "last_seen": now - 9 * 86400, "name": "TOO OLD"},
        4: {"lat": -40.0, "lon": 172.0, "last_seen": now - 60, "name": "JUST HEARD"},
    }
    monkeypatch.setattr(seapath, "sea_path_soon", lambda *a: {"coords": [[170.0, -36.0], [175.0, -36.0]], "nm": 243, "passages": []})
    got = {f["properties"]["name"]: f for f in s.quiet_ships([(160.0, -50.0, 180.0, -30.0)], set(), now)}
    assert set(got) == {"GOING", "STILL"}
    going = got["GOING"]
    assert going["properties"]["estimated"] is True and 171.0 < going["geometry"]["coordinates"][0] < 171.5  # 60 NM on
    assert got["STILL"]["properties"]["estimated"] is False and got["STILL"]["geometry"]["coordinates"] == [172.0, -40.0]
    s2 = live.Ships(store=ShipStore(tmp_path / "s2"), settings=lambda: {"ships_quiet_days": 0})
    s2.store.details = s.store.details
    assert s2.quiet_ships([(160.0, -50.0, 180.0, -30.0)], set(), now) == []


def test_ships_thinned_when_zoomed_out_and_lean(monkeypatch):
    from worldmodel_api import live

    def f(mmsi, lon, lat, **p):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"id": mmsi, "imo": 9000000 + mmsi, "kind": 70, "seen": 1, "speed_kn": 12.345, **p}}
    feats = [f(1, 174.80001, -36.8, length_m=30), f(2, 174.81, -36.81, length_m=300), f(3, 174.82, -36.8, quiet=5.0, length_m=400),
             f(4, 174.83, -36.8, length_m=10), f(5, 150.0, -30.0)]
    kept = live.thin_ships(feats, 3)
    assert sorted(x["properties"]["id"] for x in kept) == [2, 5]  # the longest heard lately; the far one stays
    assert live.thin_ships(feats, 8) == feats  # zoomed in: every ship

    ships = live.Ships()
    monkeypatch.setattr(ships, "settings", lambda: {"ships_thin": True})
    out = ships._lean({"features": [dict(x, properties=dict(x["properties"])) for x in feats]}, 3, {"9000004"})
    ids = sorted(x["properties"]["id"] for x in out["features"])
    assert ids == [4, 5] and out["thinned"] == 3  # the sanctioned one comes first in its square
    p = next(x for x in out["features"] if x["properties"]["id"] == 4)
    assert p["properties"]["sanctioned"] and "imo" not in p["properties"] and "seen" not in p["properties"]
    assert p["properties"]["speed_kn"] == 12.3 and p["geometry"]["coordinates"] == [174.83, -36.8]
    monkeypatch.setattr(ships, "settings", lambda: {"ships_thin": False})
    assert len(ships._lean({"features": [dict(x, properties=dict(x["properties"])) for x in feats]}, 3, None)["features"]) == 5
