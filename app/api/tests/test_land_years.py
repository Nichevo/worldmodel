"""Yearly land cover maps: ESA CCI pictures put together from Planetary Computer's 45-degree
squares, Esri's 10 m maps by year, and land that changed between two years."""

import io

import httpx
import pytest
from PIL import Image

from worldmodel_api import land, tiles


def png(colour, size=256, box=None):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if box is None:
        box = (0, 0, size, size)
    im.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), colour), box[:2])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_cci_items():
    assert tiles.cci_item("1995", 174.7, -41.3) == "ESACCI-LC-L4-LCCS-Map-300m-P1Y-1995-v2.0.7cds-S45E135"
    assert tiles.cci_item("2020", -0.1, 51.5) == "C3S-LC-L4-LCCS-Map-300m-P1Y-2020-v2.1.1-N45W045"
    assert tiles.cci_item("2016", 0.0, 0.0).endswith("-N00E000")
    nz = tiles.tile_of(174.7, -37.0, 6)  # Auckland (a Wellington tile reaches past 45 S)
    assert tiles.cci_items("2020", 6, *nz) == ["C3S-LC-L4-LCCS-Map-300m-P1Y-2020-v2.1.1-S45E135"]
    assert len(tiles.cci_items("2020", 0, 0, 0)) == 32
    assert len(tiles.cci_items("2020", 1, 1, 1)) == 8  # south-east quarter of the world


def test_cci_tile_put_together(monkeypatch):
    seen = []

    def handler(request):
        item = request.url.params["item"]
        seen.append(item)
        if item.endswith("S45E135"):
            return httpx.Response(200, content=png((255, 0, 0, 255), box=(0, 0, 128, 256)), headers={"content-type": "image/png"})
        if item.endswith("S45E090"):
            return httpx.Response(200, content=png((0, 0, 255, 255), box=(128, 0, 256, 256)), headers={"content-type": "image/png"})
        return httpx.Response(424, json={"error": "outside bounds"})

    monkeypatch.setattr(tiles, "_http", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    status, data, kind = tiles.fetch_upstream("lcyears", 2, 3, 2, "2000")
    assert status == 200 and kind == "image/png"
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    assert im.getpixel((10, 10)) == (255, 0, 0, 255) and im.getpixel((200, 10)) == (0, 0, 255, 255)
    assert all("2000-v2.0.7cds" in s for s in seen)


def test_esri_by_year(monkeypatch):
    got = {}

    def handler(request):
        got["url"] = str(request.url)
        return httpx.Response(200, content=png((1, 2, 3, 255)), headers={"content-type": "image/png"})

    monkeypatch.setattr(tiles, "_http", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    status, _, kind = tiles.fetch_upstream("lc10", 0, 0, 0, "2023")
    assert status == 200 and kind == "image/png"
    assert "time=1672531200000,1704067199000" in got["url"] and "bbox=-20037508.34,-20037508.34,20037508.34,20037508.34" in got["url"]


def test_starter_years(monkeypatch):
    from worldmodel_contract import local
    for keep, n in (("every5", 7), ("every", 29), ("none", 0)):
        monkeypatch.setattr(local, "load_settings", lambda home=None, k=keep: {"land_cover_years_keep": k})
        assert len([a for a in tiles.starter() if a["set"] == "lcyears"]) == n


def test_cover_change():
    # A square country; in 1992 all grassland, by 2020 the left half is forest.
    geom = {"type": "Polygon", "coordinates": [[[170, -45], [175, -45], [175, -40], [170, -40], [170, -45]]]}
    grass, trees = (0xff, 0xb4, 0x32, 255), (0x00, 0x64, 0x00, 255)

    def fetch(z, x, y, t):
        if t == "1992":
            return png(grass), "image/png"
        w, s, e, n = tiles.lonlat_box(z, x, y)
        return png(trees if (w + e) / 2 < 172.5 else grass), "image/png"

    out = land.cover_change("XXX", "1992", "2020", fetch=fetch, geometry=geom)
    assert out["changes"][0]["from"] == "grass" and out["changes"][0]["to"] == "trees"
    total = out["totals"]["grass"]["from"]
    assert 2.1e7 < total < 2.4e7  # about 5 x 5 degrees at 42.5 S (555 by 409 km), in hectares
    assert out["totals"]["trees"]["to"] == pytest.approx(out["changes"][0]["ha"])
    with pytest.raises(ValueError):
        land.cover_change("XXX", "1980", "2020", fetch=fetch, geometry=geom)
