"""The client's own handling, without the app: errors and the switched-off message."""

import httpx
import pytest

from worldmodel_client import ApiOff, Client, WorldmodelError


def _client(handler):
    return Client(http=httpx.Client(base_url="http://x/api/public/v1", transport=httpx.MockTransport(handler)))


def test_off_and_errors():
    off = _client(lambda r: httpx.Response(403, json={"detail": "The API is switched off. Switch it on..."}))
    with pytest.raises(ApiOff):
        off.countries()
    bad = _client(lambda r: httpx.Response(404, json={"detail": "no indicator x"}))
    with pytest.raises(WorldmodelError, match="no indicator"):
        bad.data("x", frame=False)


def test_params_and_rows():
    seen = {}

    def handler(r: httpx.Request):
        seen.update(dict(r.url.params))
        return httpx.Response(200, json={"name": "GDP growth", "unit": "percent", "rows": [{"entity": "NZL", "year": 2000, "value": 2.0}]})

    rows = _client(handler).data("gdp_growth", ["NZL", "AUS"], start=2000, frame=False)
    assert rows[0]["value"] == 2.0
    assert seen["entities"] == "NZL,AUS" and seen["from"] == "2000" and "to" not in seen
