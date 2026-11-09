"""Languages (CLDR, Glottolog) and religion sources."""

from pathlib import Path

import duckdb

from worldmodel_data.config import Paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

FIXTURES = Path(__file__).parent / "fixtures"


def _staged(tmp_path, source):
    store = VintageStore(Paths(tmp_path / "var"))
    manifest, _ = CONNECTORS[source]().ingest(store, FIXTURES / source)
    d = store.vintage_dir(source, manifest.vintage)
    con = duckdb.connect()
    obs = con.execute(f"SELECT source_code, indicator_id, breakdown, value FROM '{d / 'observations.parquet'}'").fetchall()
    texts = con.execute(f"SELECT source_code, section, field, field_key, content FROM '{d / 'texts.parquet'}' "
                        "ORDER BY source_code, position").fetchall()
    return manifest, {(c, i, b): v for c, i, b, v in obs}, texts, d


def test_cldr_languages_shares_speakers_and_official_status(tmp_path):
    m, obs, texts, d = _staged(tmp_path, "cldr_languages")
    assert obs[("NZL", "lang_share", "lang=mi")] == 2.8
    assert round(obs[("NZL", "lang_speakers", "lang=en")]) == round(0.98 * 5161210)
    assert obs[("NZL", "lang_official", "lang=en")] == 3 and obs[("NZL", "lang_official", "lang=mi")] == 4
    assert ("CHE", "lang_official", "lang=en") not in obs and obs[("CHE", "lang_official", "lang=rm")] == 2
    assert obs[("CHE", "lang_official_count", "")] == 3 and obs[("CHE", "lang_listed", "")] == 5
    assert obs[("CHE", "lang_main_share", "")] == 64
    assert not any(k[0] == "QO" for k in obs)  # not a country in the crosswalk
    assert ("NZL", "Languages", "Māori", "lang:mi", "official") in texts
    assert (d / "indicators.json").exists()


def test_glottolog_counts_languages_and_names_the_endangered(tmp_path):
    m, obs, texts, d = _staged(tmp_path, "glottolog")
    assert obs[("NZL", "lang_count", "")] == 4  # Maori, Moriori, NZ Sign Language, English; not "bookkeeping"
    assert obs[("NZL", "lang_endangered", "")] == 1 and obs[("NZL", "lang_extinct", "")] == 1
    assert obs[("NZL", "lang_threatened", "")] == 1 and obs[("GBR", "lang_count", "")] == 1
    names = {(t[0], t[2]): t[4] for t in texts}
    assert names[("NZL", "Maori")] == "shifting|Austronesian" and names[("NZL", "Moriori")].startswith("extinct")
    assert ("NZL", "English") not in names


def test_cow_religion_shares_by_group_and_state(tmp_path):
    _, obs, _, _ = _obs_only(tmp_path, "cow_religion")
    assert round(obs[("NZL", "rel_share", "rel=christian", 2010)], 1) == round(1850000 / 4370000 * 100, 1)
    assert round(obs[("NZL", "rel_none_share", "", 2010)], 1) == round(1600000 / 4370000 * 100, 1)
    assert obs[("NZL", "rel_people", "rel=christian.catholic", 1945)] == 230000
    assert ("SUN", "rel_share", "rel=muslim", 1985) in obs and obs[("SUN", "rel_people", "rel=muslim.other", 1985)] == 0
    assert round(obs[("NZL", "rel_largest_share", "", 1945)]) == 95
    assert not any(k[0] == "XXX" for k in obs)


def test_pew_religion_reads_a_table_of_shares(tmp_path):
    _, obs, _, _ = _obs_only(tmp_path, "pew_religion")
    assert obs[("NZL", "rel_share", "rel=none", 2020)] == 51.6
    assert obs[("NZL", "rel_largest_share", "", 2020)] == 51.6
    assert len({k[0] for k in obs}) == 1


def _obs_only(tmp_path, source):
    store = VintageStore(Paths(tmp_path / "var"))
    manifest, _ = CONNECTORS[source]().ingest(store, FIXTURES / source)
    d = store.vintage_dir(source, manifest.vintage)
    rows = duckdb.connect().execute(f"SELECT source_code, indicator_id, breakdown, year(period_start), value "
                                    f"FROM '{d / 'observations.parquet'}'").fetchall()
    return manifest, {(c, i, b, y): v for c, i, b, y, v in rows}, None, d
