"""UNESCO's World Heritage list XML: the older one-point layout and the 2026 <geolocations> layout."""

from worldmodel_data.connectors.tourism import whc_sites

OLD = """<?xml version="1.0"?><query><row><site>Old site</site><iso_code>nz</iso_code>
<latitude>-45.0</latitude><longitude>170.0</longitude><date_inscribed>1990</date_inscribed></row></query>"""

NEW = """<?xml version="1.0"?><query><row><site>Serial site</site><iso_code>it,es</iso_code>
<geolocations><poi><latitude>38.132</latitude><longitude>15.961</longitude><iso2>it</iso2></poi>
<poi><latitude>41.11</latitude><longitude>-3.499</longitude><iso2>es</iso2></poi></geolocations>
<location></location><date_inscribed>2007</date_inscribed></row>
<row><site>No points</site><iso_code>fr</iso_code></row></query>"""


def test_old_layout_keeps_its_point():
    (s,) = whc_sites(OLD)
    assert (s["latitude"], s["longitude"], s["site"]) == ("-45.0", "170.0", "Old site")


def test_geolocations_layout_uses_first_point():
    a, b = whc_sites(NEW)
    assert (a["latitude"], a["longitude"]) == ("38.132", "15.961")
    assert "geolocations" not in a and a["iso_code"] == "it,es"
    assert not b.get("latitude")
