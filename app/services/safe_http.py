"""Bounded public-web fetch with DNS validation at socket connection time.

The network backend connects to the validated IP, while HTTP Host and TLS SNI
remain the original hostname. A second hostname lookup cannot rebind the socket.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

MAX_BYTES = 1_048_576
MAX_REDIRECTS = 4


class UnsafeURL(ValueError):
    pass


def public_ip(value: str) -> str:
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_unspecified:
        raise UnsafeURL("Non-public network target")
    if isinstance(address, ipaddress.IPv6Address) and (
        address.ipv4_mapped or address.sixtofour or address.teredo
    ):
        raise UnsafeURL("IPv6 transition targets are unsupported")
    return str(address)


def validate_url(url: str) -> tuple[str, int]:
    if len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise UnsafeURL("Invalid URL")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
                or parsed.password is not None or "%" in host
                or port != (443 if parsed.scheme == "https" else 80)):
            raise UnsafeURL("Only public HTTP/HTTPS default ports are supported")
        host = host.encode("idna").decode("ascii")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if host.rstrip(".").lower() == "localhost" or host.lower().endswith(".localhost"):
                raise UnsafeURL("Local host is unsupported")
        else:
            public_ip(host)
        return host, port
    except (ValueError, UnicodeError) as exc:
        raise UnsafeURL("Invalid or non-public URL") from exc


async def public_addresses(host: str, port: int) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    addresses = list(dict.fromkeys(public_ip(record[4][0]) for record in records))
    if not addresses:
        raise UnsafeURL("No public address")
    return addresses


class PublicNetworkBackend(AutoBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        async with asyncio.timeout(timeout or 10):
            addresses = await public_addresses(host, port)
            return await super().connect_tcp(
                addresses[0], port, timeout=timeout, local_address=local_address,
                socket_options=socket_options,
            )


class PublicHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        # httpx's transport adapter owns an httpcore pool. Pin httpcore's major
        # version and exercise this boundary in tests when upgrading dependencies.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicNetworkBackend(),
            max_connections=3, max_keepalive_connections=0,
        )


async def fetch_public(url: str, *, transport=None) -> httpx.Response:
    async with asyncio.timeout(25):
        async with httpx.AsyncClient(
            transport=transport or PublicHTTPTransport(), timeout=10,
            follow_redirects=False, trust_env=False,
            headers={"User-Agent": "SmmAiHelper/1.0", "Accept": "text/html,application/xhtml+xml",
                     "Accept-Encoding": "identity"},
        ) as client:
            for hop in range(MAX_REDIRECTS + 1):
                validate_url(url)
                async with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or hop == MAX_REDIRECTS:
                            raise UnsafeURL("Redirect limit or missing target")
                        url = urljoin(url, location)
                        continue
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise UnsafeURL("Compressed responses are unsupported")
                    size = response.headers.get("content-length")
                    if size and (not size.isdecimal() or int(size) > MAX_BYTES):
                        raise UnsafeURL("Response is too large")
                    content = bytearray()
                    async for chunk in response.aiter_raw():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise UnsafeURL("Response is too large")
                    return httpx.Response(
                        response.status_code, headers=response.headers, content=bytes(content),
                        request=httpx.Request("GET", url),
                    )
    raise UnsafeURL("No response")
