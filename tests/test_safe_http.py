import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import safe_http
from app.services.safe_http import UnsafeURL, fetch_public, validate_url
from app.services.url_analyzer import UrlAnalyzer


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.1.2.3/", "http://169.254.169.254/",
    "http://[::1]/", "http://[fc00::1]/", "http://[::ffff:127.0.0.1]/",
    "http://localhost/", "https://public.example:8443/", "ftp://public.example/",
    "https://user:secret@public.example/", "https://example.com\\@127.0.0.1/",
    "https://[fe80::1%25eth0]/", "https://example.com/\nheader", "http://224.0.0.1/",
])
def test_rejects_unsafe_url_without_fetch(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_dns_validation_rejects_mixed_public_and_private_answers(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[
            (None, None, None, None, ("93.184.216.34", 443)),
            (None, None, None, None, ("192.168.1.1", 443)),
        ]))
        with pytest.raises(UnsafeURL):
            await safe_http.public_addresses("public.example", 443)
    asyncio.run(run())


def test_network_connects_to_validated_ip_without_second_dns_lookup(monkeypatch):
    connect = AsyncMock(return_value="socket")
    monkeypatch.setattr(safe_http, "public_addresses", AsyncMock(return_value=["93.184.216.34"]))
    monkeypatch.setattr(safe_http.AutoBackend, "connect_tcp", connect)
    result = asyncio.run(safe_http.PublicNetworkBackend().connect_tcp("public.example", 443))
    assert result == "socket"
    assert connect.call_args.args[:2] == ("93.184.216.34", 443)


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks): self.chunks = chunks
    async def __aiter__(self):
        for chunk in self.chunks: yield chunk


def test_redirect_to_private_target_is_never_requested():
    visited = []
    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    with pytest.raises(UnsafeURL):
        asyncio.run(fetch_public("https://example.com", transport=httpx.MockTransport(handler)))
    assert visited == ["https://example.com"]


def test_redirect_budget_and_stream_size_are_bounded():
    with pytest.raises(UnsafeURL):
        asyncio.run(fetch_public("https://example.com", transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "/next"})
        )))
    with pytest.raises(UnsafeURL):
        asyncio.run(fetch_public("https://example.com", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=Stream([b"x" * 600_000, b"y" * 600_000]))
        )))


def test_public_html_can_be_fetched_and_compression_is_rejected():
    response = asyncio.run(fetch_public("https://example.com", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, stream=Stream([b"<h1>public</h1>"]))
    )))
    assert response.text == "<h1>public</h1>"
    with pytest.raises(UnsafeURL):
        asyncio.run(fetch_public("https://example.com", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Stream([]))
        )))


def test_analyzer_parallelizes_network_without_touching_caller_session(monkeypatch):
    import app.services.url_analyzer as module
    caller = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("caller session used")),
                             commit=AsyncMock(side_effect=AssertionError("caller commit")),
                             rollback=AsyncMock(side_effect=AssertionError("caller rollback")))
    active = 0
    peak = 0
    async def fetch(url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<h1>Observed offer</h1>", request=httpx.Request("GET", url))
    class CacheSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def begin(self): return self
        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)
    monkeypatch.setattr(module, "fetch_public", fetch)
    analyzer = UrlAnalyzer(caller, cache_session_factory=CacheSession)
    result = asyncio.run(analyzer.analyze("https://one.example https://two.example"))
    assert peak == 2
    assert all(summary["h1"] == ["Observed offer"] for summary in result.url_summaries)
    caller.execute.assert_not_called()
