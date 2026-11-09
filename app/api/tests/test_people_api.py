"""Religion and languages endpoints on a copy of the sample warehouse with made-up rows."""

import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from worldmodel_api import main, people
from worldmodel_api.warehouse import SAMPLE, Warehouse


def add_rows(path):
    con = duckdb.connect(str(path))
    rows = []

    def put(e, ind, y, v, bd, src, st="E"):
        rows.append((e, ind, date(y, 1, 1), "A", bd, "central", src, "t", float(v), st))

    for y, nz, us in ((1950, (90, 5), (90, 2)), (2010, (55, 35), (78, 16))):
        put("NZL", "rel_people", y, nz[0] * 2e4, "rel=christian", "cow_religion")
        put("NZL", "rel_people", y, nz[1] * 2e4, "rel=none", "cow_religion")
        put("NZL", "rel_share", y, nz[0], "rel=christian", "cow_religion")
        put("NZL", "rel_share", y, nz[1], "rel=none", "cow_religion")
        put("USA", "rel_people", y, us[0] * 3e6, "rel=christian", "cow_religion")
        put("USA", "rel_people", y, us[1] * 3e6, "rel=none", "cow_religion")
        put("USA", "rel_share", y, us[0], "rel=christian", "cow_religion")
        put("USA", "rel_share", y, us[1], "rel=none", "cow_religion")
    put("NZL", "rel_share", 2020, 37, "rel=christian", "pew_religion")
    put("NZL", "rel_share", 2020, 52, "rel=none", "pew_religion")
    put("NZL", "rel_share", 2050, 45, "rel=christian", "pew_religion", "P")
    for e, code, share, spk, off in (("NZL", "en", 98, 5e6, 3), ("NZL", "mi", 2.8, 1.4e5, 4), ("USA", "en", 96, 3.2e8, 3),
                                     ("USA", "es", 13, 4.3e7, None)):
        put(e, "lang_share", 2026, share, f"lang={code}", "cldr_languages")
        put(e, "lang_speakers", 2026, spk, f"lang={code}", "cldr_languages")
        if off:
            put(e, "lang_official", 2026, off, f"lang={code}", "cldr_languages")
    put("NZL", "lang_count", 2026, 4, "", "glottolog")
    put("NZL", "lang_endangered", 2026, 1, "", "glottolog")
    con.executemany("INSERT INTO observations VALUES (" + ", ".join("?" * 10) + ")", rows)
    for src in ("cow_religion", "pew_religion", "cldr_languages", "glottolog"):
        con.execute("INSERT INTO vintages BY NAME SELECT ? AS source_id, 't' AS vintage, 't' AS release, true AS is_latest", [src])
    texts = [("NZL", "cldr_languages", "Languages", "English", "lang:en", "official in practice", 0),
             ("NZL", "cldr_languages", "Languages", "Māori", "lang:mi", "official", 1),
             ("USA", "cldr_languages", "Languages", "Spanish", "lang:es", "", 1),
             ("NZL", "glottolog", "Endangered languages", "Maori", "glotto:maor1246", "shifting|Austronesian", 3)]
    con.executemany("INSERT INTO texts BY NAME SELECT ? AS entity_id, ? AS source_id, 't' AS vintage, 2026 AS edition, "
                    "? AS section, ? AS field, ? AS field_key, ? AS content, ? AS position", texts)
    con.close()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("people_api")
    path = d / "people.duckdb"
    shutil.copy(SAMPLE, path)
    add_rows(path)
    mp = pytest.MonkeyPatch()
    mp.setenv("WORLDMODEL_HOME", str(d))
    mp.setenv("WORLDMODEL_USER_DIR", str(d / "user"))
    old = main.warehouse
    main.warehouse = Warehouse(str(path))
    yield TestClient(main.app)
    main.warehouse = old
    mp.undo()


def test_factbook_religion_lines():
    got = people.factbook_religion("Christian 37.3% (Catholic 10.1%, Anglican 6.8%), Hindu 2.7%, Muslim, 1.3%, "
                                   "other 1.6%, none 48.6%, not stated 6.7% (2018 est.)", 2024)
    assert got["year"] == 2018 and got["shares"] == {"christian": 37.3, "hindu": 2.7, "muslim": 1.3, "other": 1.6, "none": 48.6}
    assert people.factbook_religion("81% Christian, 18% none, 1% Hindu", 1990)["shares"]["christian"] == 81
    assert people.factbook_religion("Roman Catholic 27%, Protestant 11%, unspecified 60%", 2000) is None  # under half placed
    assert people.classify("Presbyterian and Congregational") == "christian" and people.classify("Shia") == "muslim"


def test_religion_world_and_map(client):
    r = client.get("/api/v1/religion", params={"year": 2010, "group": "none", "since": 1950}).json()
    cow = {p["year"]: p for p in r["world"]["cow_religion"]}
    # weighted by people: the US dominates the two-country world
    assert 16 < cow[2010]["shares"]["none"] < 17
    nz = next(x for x in r["map"]["rows"] if x["entity_id"] == "NZL")
    assert nz["largest"] == "christian" and nz["share"] == 35 and nz["change"] == 30
    assert r["sources"][0]["id"] == "pew_religion"
    assert client.get("/api/v1/religion", params={"group": "martian"}).status_code == 422


def test_religion_country(client):
    r = client.get("/api/v1/entities/NZL/religion").json()
    src = {s["id"]: s for s in r["sources"]}
    pew = {p["year"]: p for p in src["pew_religion"]["points"]}
    assert pew[2050]["projected"] and not pew[2020]["projected"]
    assert "cia_factbook" in src and src["cia_factbook"]["points"][-1]["shares"]["christian"] > 30


def test_languages(client):
    r = client.get("/api/v1/languages").json()
    assert r["top"][0]["code"] == "en" and r["top"][0]["name"] == "English" and r["top"][0]["countries"] == 2
    assert r["lang"] == "en" and {x["entity_id"] for x in r["map"]} == {"NZL", "USA"}
    es = client.get("/api/v1/languages", params={"lang": "es"}).json()
    assert es["lang_name"] == "Spanish" and es["map"][0]["official"] is None
    c = client.get("/api/v1/entities/NZL/languages").json()
    assert [x["code"] for x in c["languages"]] == ["en", "mi"]  # official first, by share
    assert c["languages"][1]["official"] == "official" and c["counts"]["lang_count"] == 4
    assert c["endangered"][0]["name"] == "Maori" and c["endangered"][0]["family"] == "Austronesian"
    assert c["factbook"]["content"].startswith("English")
