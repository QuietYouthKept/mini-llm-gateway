from __future__ import annotations

import asyncio
import ipaddress
import json
import socket

import httpcore
import httpx
import pytest

from app.domain.errors import ProviderBadStatusError, ProviderFailedError
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from app.infrastructure.config.config_models import HTTPProviderConfig
from app.infrastructure.providers.egress import (
    DnsPinningBackend,
    ProviderEgressError,
    install_provider_egress_guard,
)
from app.infrastructure.providers.openai_compatible import OpenAICompatibleProvider


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.stream: RecordingTlsStream | None = None

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        self.hosts.append(host)
        if self.stream is None:
            raise OSError("test backend reached")
        return self.stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("Unix sockets must not be used")

    async def sleep(self, seconds: float) -> None:
        return None


class RecordingTlsStream:
    def __init__(self) -> None:
        self.server_hostname: str | None = None

    async def start_tls(
        self,
        ssl_context: object,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> RecordingTlsStream:
        self.server_hostname = server_hostname
        return self


def addrinfo(address: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]


async def resolved(
    addresses: str | list[tuple[int, int, int, str, tuple[str, int]]],
) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return addrinfo(addresses) if isinstance(addresses, str) else addresses


@pytest.mark.asyncio
async def test_dns_answer_is_pinned_to_checked_ip() -> None:
    delegate = RecordingBackend()
    backend = DnsPinningBackend(
        allow_private_network=False,
        backend=delegate,
        resolver=lambda _host, _port: resolved("8.8.8.8"),
    )

    with pytest.raises(OSError, match="test backend reached"):
        await backend.connect_tcp("api.example.test", 443)

    assert delegate.hosts == ["8.8.8.8"]


@pytest.mark.asyncio
async def test_mixed_public_and_private_dns_answers_fail_closed() -> None:
    delegate = RecordingBackend()
    answers = addrinfo("8.8.8.8") + addrinfo("10.0.0.5")
    backend = DnsPinningBackend(
        allow_private_network=False,
        backend=delegate,
        resolver=lambda _host, _port: resolved(answers),
    )

    with pytest.raises(ProviderEgressError, match="outside the public address space"):
        await backend.connect_tcp("rebound.example.test", 443)

    assert delegate.hosts == []


@pytest.mark.asyncio
async def test_private_address_requires_explicit_opt_in_and_link_local_is_always_blocked() -> None:
    delegate = RecordingBackend()
    allowed = DnsPinningBackend(
        allow_private_network=True,
        backend=delegate,
        resolver=lambda _host, _port: resolved("192.168.1.10"),
    )
    with pytest.raises(OSError, match="test backend reached"):
        await allowed.connect_tcp("internal.example.test", 443)
    assert delegate.hosts == ["192.168.1.10"]

    blocked = DnsPinningBackend(
        allow_private_network=True,
        backend=delegate,
        resolver=lambda _host, _port: resolved("169.254.169.254"),
    )
    with pytest.raises(ProviderEgressError, match="prohibited address"):
        await blocked.connect_tcp("metadata.example.test", 443)
    assert delegate.hosts == ["192.168.1.10"]


def test_httpx_transport_installs_guard_without_proxy_and_keeps_tls_verification() -> None:
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    install_provider_egress_guard(transport, allow_private_network=False)

    assert isinstance(transport._pool._network_backend, DnsPinningBackend)
    assert transport._pool._proxy is None
    assert transport._pool._ssl_context.verify_mode == 2  # ssl.CERT_REQUIRED


def test_guard_refuses_unknown_or_proxy_transport() -> None:
    with pytest.raises(RuntimeError, match="unsupported"):
        install_provider_egress_guard(object(), allow_private_network=False)

    proxy_transport = httpx.AsyncHTTPTransport(
        trust_env=False,
        proxy="http://127.0.0.1:8080",
    )
    with pytest.raises(RuntimeError, match="does not permit proxy"):
        install_provider_egress_guard(proxy_transport, allow_private_network=False)


@pytest.mark.asyncio
async def test_tls_keeps_original_hostname_after_socket_ip_is_pinned() -> None:
    delegate = RecordingBackend()
    delegate.stream = RecordingTlsStream()
    backend = DnsPinningBackend(
        allow_private_network=False,
        backend=delegate,
        resolver=lambda _host, _port: resolved("8.8.8.8"),
    )
    connection = httpcore.AsyncHTTPConnection(
        origin=httpcore.Origin(scheme=b"https", host=b"provider.example.test", port=443),
        network_backend=backend,
    )

    stream = await connection._connect(
        httpcore.Request(method="GET", url="https://provider.example.test/chat")
    )

    assert stream is delegate.stream
    assert delegate.hosts == ["8.8.8.8"]
    assert delegate.stream.server_hostname == "provider.example.test"


@pytest.mark.asyncio
async def test_default_provider_client_pins_resolved_ip_on_real_tcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        payload = json.dumps(
            {
                "choices": [{"message": {"content": "pinned"}}],
                "model": "m",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + payload
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def resolve(_host: str, _port: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return addrinfo("127.0.0.1")

    monkeypatch.setattr(DnsPinningBackend, "_resolve", staticmethod(resolve))
    provider = OpenAICompatibleProvider(
        "test-provider",
        HTTPProviderConfig(
            base_url=f"http://provider.invalid:{port}/v1",
            model="m",
            allow_private_network=True,
        ),
    )
    assert provider._client.follow_redirects is False
    assert provider._client._trust_env is False
    request = ChatRequest(
        profile="p",
        messages=[ChatMessage(role="user", content="probe")],
    )
    try:
        response = await provider.chat(request)
    finally:
        await provider.close()
        server.close()
        await server.wait_closed()

    assert response.content == "pinned"
    assert len(requests) == 1
    assert b"host: provider.invalid:" in requests[0].lower()


@pytest.mark.asyncio
async def test_default_provider_rejects_private_dns_answer_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted_connections = 0

    async def handle(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal accepted_connections
        accepted_connections += 1
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def resolve(_host: str, _port: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return addrinfo("127.0.0.1")

    monkeypatch.setattr(DnsPinningBackend, "_resolve", staticmethod(resolve))
    provider = OpenAICompatibleProvider(
        "test-provider",
        HTTPProviderConfig(
            base_url=f"http://provider.invalid:{port}/v1",
            model="m",
            allow_private_network=False,
        ),
    )
    request = ChatRequest(
        profile="p",
        messages=[ChatMessage(role="user", content="probe")],
    )
    try:
        with pytest.raises(ProviderFailedError):
            await provider.chat(request)
    finally:
        await provider.close()
        server.close()
        await server.wait_closed()

    assert accepted_connections == 0


@pytest.mark.asyncio
async def test_default_provider_does_not_follow_upstream_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(
            b"HTTP/1.1 302 Found\r\nLocation: http://redirect.invalid/v1/chat/completions\r\n"
            b"Content-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def resolve(_host: str, _port: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return addrinfo("127.0.0.1")

    monkeypatch.setattr(DnsPinningBackend, "_resolve", staticmethod(resolve))
    provider = OpenAICompatibleProvider(
        "test-provider",
        HTTPProviderConfig(
            base_url=f"http://provider.invalid:{port}/v1",
            model="m",
            allow_private_network=True,
        ),
    )
    request = ChatRequest(
        profile="p",
        messages=[ChatMessage(role="user", content="probe")],
    )
    try:
        with pytest.raises(ProviderBadStatusError):
            await provider.chat(request)
    finally:
        await provider.close()
        server.close()
        await server.wait_closed()

    assert len(requests) == 1
