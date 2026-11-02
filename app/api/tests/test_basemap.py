"""The local map file: sizes before download, making the files (with a stand-in for the
go-pmtiles tool and the download site), and serving them in pieces to the map."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from worldmodel_api import basemap, main
from worldmodel_api.warehouse import SAMPLE, Warehouse

ASSETS = [{"name": "go-pmtiles-1.28.0_Darwin_arm64.zip"}, {"name": "go-pmtiles_1.28.0_Linux_x86_64.tar.gz"},
          {"name": "go-pmtiles_1.28.0_Windows_x86_64.zip"}, {"name": "checksums.txt"}]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDMODEL_HOME", str(tmp_path))
    monkeypatch.setenv("WORLDMODEL_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setattr(basemap, "get_tool", lambda client: Path("pmtiles"))
    monkeypatch.setattr(basemap, "latest_build", lambda client: "20261101.pmtiles")

    def fonts(client):
        p = basemap.root() / "fonts" / "Noto Sans Regular" / "0-255.pbf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"font")
    monkeypatch.setattr(basemap, "get_fonts", fonts)
    calls = []

    def run(args, timeout):
        calls.append(args)
        if "--dry-run" in args:
            return "fetching directories...\nArchive size: 1.5 GB\n" if "world.pmtiles" in args[3] else "total size 600 MB"
        Path(args[3]).write_bytes(b"PMTiles" + bytes(range(256)) * 4)
        return "done"
    monkeypatch.setattr(basemap, "_run", run)
    main.warehouse = Warehouse(str(SAMPLE))
    c = TestClient(main.app)
    c.calls = calls
    return c


def test_tool_download_for_this_computer():
    assert basemap.asset_for(ASSETS, "Windows", "AMD64")["name"].endswith("Windows_x86_64.zip")
    assert basemap.asset_for(ASSETS, "Darwin", "arm64")["name"].endswith("Darwin_arm64.zip")
    assert basemap.asset_for(ASSETS, "Linux", "x86_64")["name"].endswith(".tar.gz")


def test_size_from_the_dry_run():
    assert basemap.size_from("Archive size: 1.5 GB") == 1.5e9
    assert basemap.size_from("tiles: 12,345\ntotal size 600 MB") == 600e6
    assert basemap.size_from("nothing here") is None


def test_size_shown_before_making(client):
    client.put("/api/v1/settings", json={"basemap_regions": "NZL", "basemap_world_zoom": 7})
    est = client.post("/api/v1/basemap/estimate").json()
    assert [(i["name"], i["maxzoom"], i["bytes"]) for i in est["items"]] == [("world.pmtiles", 7, 1.5e9), ("NZL.pmtiles", 15, 600e6)]
    assert est["size"] == "2.1 GB" and est["fits"]
    nz = next(a for a in client.calls if "NZL.pmtiles" in a[3])
    assert any(a.startswith("--region=") for a in nz) and "--maxzoom=15" in nz
    client.put("/api/v1/settings", json={"basemap_limit_gb": 1})
    est = client.post("/api/v1/basemap/estimate").json()
    assert not est["fits"] and "map files limit" in est["why"]


def test_make_files_then_serve_them_in_pieces(client):
    client.put("/api/v1/settings", json={"basemap_regions": "NZL"})
    assert client.post("/api/v1/basemap/make").json()["state"] == "running"
    for _ in range(50):
        st = client.get("/api/v1/basemap").json()
        if st["job"]["state"] != "running":
            break
        time.sleep(0.05)
    assert st["job"]["state"] == "done", st["job"]
    assert [f["name"] for f in st["files"]] == ["world.pmtiles", "NZL.pmtiles"] and st["fonts"]
    assert st["files"][0]["build"] == "20261101.pmtiles"
    r = client.get("/api/v1/basemap/files/world.pmtiles", headers={"Range": "bytes=0-6"})
    assert r.status_code == 206 and r.content == b"PMTiles"
    assert client.get("/api/v1/basemap/files/..%2Fsettings.json").status_code == 404
    assert client.get("/api/v1/basemap/fonts/Noto Sans Regular/0-255.pbf").content == b"font"
    assert client.get("/api/v1/basemap/fonts/..%2F..%2Fuser/0-255.pbf").status_code == 404
    assert client.delete("/api/v1/basemap/files/NZL.pmtiles").json()["ok"]
    assert [f["name"] for f in client.get("/api/v1/basemap").json()["files"]] == ["world.pmtiles"]
    usage = client.get("/api/v1/storage").json()
    assert any(c["key"] == "basemap" and c["bytes"] > 0 for c in usage["categories"])


def test_a_failure_is_explained(client, monkeypatch):
    def broken(args, timeout):
        raise RuntimeError("fetching header: 404 Not Found")
    monkeypatch.setattr(basemap, "_run", broken)
    client.post("/api/v1/basemap/make")
    for _ in range(50):
        st = client.get("/api/v1/basemap").json()
        if st["job"]["state"] != "running":
            break
        time.sleep(0.05)
    assert st["job"]["state"] == "failed" and "404" in st["job"]["error"]
    assert st["files"] == []
