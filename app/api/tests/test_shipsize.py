"""Ship sizes: TEU estimates, canal and port limits, exact TEU from a saved list."""

from worldmodel_api import shipsize


def test_teu_estimate_is_near_known_ships():
    assert abs(shipsize.estimate_teu(399.9, 58.8) - 20124) / 20124 < 0.2   # Ever Given
    assert abs(shipsize.estimate_teu(294, 32.2) - 4500) / 4500 < 0.2       # a Panamax
    assert abs(shipsize.estimate_teu(147, 23.2) - 1000) / 1000 < 0.2       # a small feeder
    assert shipsize.estimate_teu(30, 8) is None and shipsize.estimate_teu(None, 30) is None


def test_canals_and_ports():
    ulcv = {"length_m": 400, "width_m": 61, "draught_m": 14.5}
    f = {c["id"]: c for c in shipsize.fits(ulcv)["canals"]}
    assert f["panama_new"]["ok"] is False and any("wide" in w for w in f["panama_new"]["why"])
    assert f["suez"]["ok"] is True  # 61 m wide: Suez allows about 16.9 m draught
    assert f["kiel"]["ok"] is False and f["malacca"]["ok"] is True  # Malacca limits draught only
    feeder = {"length_m": 150, "width_m": 23, "draught_m": 9.0}
    assert {c["id"]: c["ok"] for c in shipsize.fits(feeder)["canals"]}["kiel"] is True  # under 160 m: 9.5 m allowed
    assert shipsize.check({"length_m": 150}, shipsize.CANAL_BY_ID["seaway"])["checked"] == 1
    assert shipsize.check({}, shipsize.CANAL_BY_ID["seaway"])["ok"] is None
    tauranga = {"name": "Tauranga", "locode": "NZTRG", "max_len": 348.0, "max_beam": 48.4, "max_draft": 14.5}
    port = shipsize.fits(ulcv, tauranga)["port"]
    assert port["ok"] is False and len(port["why"]) == 2
    assert shipsize.too_big(ulcv, "port:NZTRG", {"NZTRG": tauranga}) and not shipsize.too_big(feeder, "port:NZTRG", {"NZTRG": tauranga})
    assert shipsize.port_limit({"name": "Nowhere"}) is None


def test_exact_teu_wins(tmp_path):
    (tmp_path / "mine.csv").write_text("IMO,Name,TEU\n9811000,Ever Given,\"20,124\"\nbad,x,1\n")
    known = shipsize.KnownTeu(tmp_path)
    assert known.get(9811000) == 20124 and known.get(1234567) is None
    ship = {"length_m": 399.9, "width_m": 58.8}
    assert shipsize.teu_of(ship, known.get(9811000))["estimated"] is False
    assert shipsize.teu_of(ship, None, 20000)["source"] == "Wikidata"
    est = shipsize.teu_of(ship, None, None, False)
    assert est["estimated"] and est["container"] is False
    assert shipsize.looks_container("MAERSK INNOSHIMA") and shipsize.looks_container("ABC", ["Container"])
    assert not shipsize.looks_container("AFRICAN ISABELLE", ["Logs"])


def test_size_endpoint(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from worldmodel_api import live, main
    from worldmodel_api.shipstore import ShipStore

    ships = live.Ships(store=ShipStore(tmp_path / "ships"), settings=lambda: {"ship_schedules": True})
    ships.store.note(111, name="MAERSK KOWLOON", imo=9784270, kind=71, length_m=354, width_m=49, draught_m=13.1, now=time.time())
    monkeypatch.setattr(live, "SHIPS", ships)
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    c = TestClient(main.app)
    got = c.get("/api/v1/live/ships/size/111").json()
    assert got["teu"]["estimated"] and got["teu"]["container"] and 10000 < got["teu"]["teu"] < 17000
    by = {x["id"]: x["ok"] for x in got["canals"]}
    assert by["panama_new"] is True and by["panama_old"] is False
    assert c.get("/api/v1/live/ships/size/999").status_code == 404
    assert len(c.get("/api/v1/live/ships/limits").json()["canals"]) == 6
