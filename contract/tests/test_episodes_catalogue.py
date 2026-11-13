"""The typed-in episodes list (episodes.yaml) is complete and consistent."""

import re

from worldmodel_contract import catalogue

DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def test_episodes_are_well_formed():
    cat = catalogue.episodes()
    eps = cat["episodes"]
    ents = catalogue.entities()
    assert len(eps) >= 16
    assert len({e["id"] for e in eps}) == len(eps)
    for e in eps:
        assert e["kind"] in cat["kinds"], e["id"]
        assert DATE.match(e["start"]) and DATE.match(e["end"]) and e["start"][:4] <= e["end"][:4], e["id"]
        assert all(c in ents for c in e["countries"]), e["id"]
        assert e["summary"] and "\\" not in e["summary"], e["id"]
        assert e["timeline"] and all(DATE.match(t["date"]) for t in e["timeline"]), e["id"]
        assert e["charts"] and e["links"] and all(link["url"].startswith("https://en.wikipedia.org/") for link in e["links"]), e["id"]
    assert any(e["nz"] for e in eps)
