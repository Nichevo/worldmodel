"""Downloads that go wrong part way: a connection cut off mid-file, a site that leaves out
its intermediate certificate."""

from pathlib import Path

import httpx
import pytest

from worldmodel_data.connectors import base
from worldmodel_data.connectors.base import Connector, ConnectorError

DATA = bytes(range(256)) * 4000  # about 1 MB


class Dummy(Connector):
    source_id = "dummy"

    def default_release(self, fetched_at):
        return "x"

    def release_from_files(self, files):
        return None

    def download(self, raw_dir, release):
        return ""

    def stage(self, con, raw_dir, release, vintage):
        return ""


def cut_after(n: int, start: int = 0):
    def body():
        yield DATA[start:start + n]
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")
    return body()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)


def test_resumes_a_cut_off_download(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range")
        seen.append(rng)
        if rng is None:
            return httpx.Response(200, headers={"accept-ranges": "bytes"}, content=cut_after(300_000))
        start = int(rng.split("=")[1].rstrip("-"))
        if len(seen) == 2:  # cut off again
            return httpx.Response(206, headers={"content-range": f"bytes {start}-{len(DATA) - 1}/{len(DATA)}"},
                                  content=cut_after(200_000, start))
        return httpx.Response(206, headers={"content-range": f"bytes {start}-{len(DATA) - 1}/{len(DATA)}"},
                              content=DATA[start:])

    c = Dummy(httpx.Client(transport=httpx.MockTransport(handler)))
    c.get("https://example.org/big.zip", tmp_path / "big.zip")
    assert (tmp_path / "big.zip").read_bytes() == DATA
    assert seen == [None, "bytes=300000-", "bytes=500000-"]


def test_server_without_ranges_starts_again(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.headers.get("range"))
        return httpx.Response(200, content=cut_after(1000) if len(calls) == 1 else iter([DATA]))

    c = Dummy(httpx.Client(transport=httpx.MockTransport(handler)))
    c.get("https://example.org/f", tmp_path / "f")
    assert (tmp_path / "f").read_bytes() == DATA


def test_gives_up_after_repeated_cuts(tmp_path):
    def handler(request):
        rng = request.headers.get("range")
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        return httpx.Response(206 if rng else 200, headers={"content-range": f"bytes {start}-/{len(DATA)}"},
                              content=cut_after(10, start))

    c = Dummy(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ConnectorError, match="cut off 7 times"):
        c.get("https://example.org/f", tmp_path / "f")


def test_missing_intermediate_certificate_is_fetched(tmp_path, monkeypatch):
    def bad_chain(request):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate")

    asked = []

    def fixed(host):
        asked.append(host)
        return True

    monkeypatch.setattr(base, "aia_context", fixed)
    real_client = httpx.Client

    def client_after_fix(**kw):  # the connector's new client, made with the fixed check
        return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok")))

    c = Dummy(httpx.Client(transport=httpx.MockTransport(bad_chain)))
    monkeypatch.setattr(base.httpx, "Client", client_after_fix)
    c.get("https://www.uky.edu/~clthyn2/coup_data/powell_thyne_ccode_year.txt", tmp_path / "coups.txt")
    assert asked == ["www.uky.edu"] and (tmp_path / "coups.txt").read_bytes() == b"ok"
