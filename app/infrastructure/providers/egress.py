"""Runtime DNS pinning and destination checks for provider HTTP traffic.

httpcore intentionally receives the vetted numeric address for the TCP socket;
its connection implementation still uses the original request hostname for TLS
SNI and certificate verification. The only integration point with httpx is the
locked httpcore connection-pool backend; construction fails closed if that
internal contract changes.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from typing import Any

import httpcore
from httpcore._backends.auto import AutoBackend

AddressInfo = tuple[int, int, int, str, tuple[Any, ...]]
Resolver = Callable[[str, int], Any]


class ProviderEgressError(httpcore.ConnectError):
    """Raised when a provider hostname resolves to a disallowed address."""


class DnsPinningBackend(httpcore.AsyncNetworkBackend):
    """Validate DNS answers and pin each new TCP connection to a checked IP."""

    def __init__(
        self,
        *,
        allow_private_network: bool,
        backend: httpcore.AsyncNetworkBackend | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._allow_private_network = allow_private_network
        self._backend = backend or AutoBackend()
        self._resolver = resolver or self._resolve

    @staticmethod
    async def _resolve(host: str, port: int) -> list[AddressInfo]:
        loop = asyncio.get_running_loop()
        return await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)

    def _validate_address(self, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ProviderEgressError("provider DNS returned a non-IP address") from exc

        if (
            address.is_unspecified
            or address.is_multicast
            or address.is_reserved
            or address.is_link_local
        ):
            raise ProviderEgressError("provider DNS resolved to a prohibited address")
        if not self._allow_private_network and not address.is_global:
            raise ProviderEgressError("provider DNS resolved outside the public address space")
        return str(address)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        answers = await self._resolver(host, port)
        checked: list[tuple[int, str]] = []
        for family, _socktype, _protocol, _canonname, sockaddr in answers:
            numeric = self._validate_address(str(sockaddr[0]))
            candidate = (family, numeric)
            if candidate not in checked:
                checked.append(candidate)
        if not checked:
            raise ProviderEgressError("provider DNS returned no usable addresses")

        # Never connect using the hostname after validation: that would permit a
        # second resolver lookup and a DNS-rebinding time-of-check/time-of-use gap.
        family, pinned_ip = checked[0]
        if family == socket.AF_INET6 and "%" in pinned_ip:
            raise ProviderEgressError("scoped IPv6 provider addresses are not allowed")
        return await self._backend.connect_tcp(
            pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise ProviderEgressError("Unix socket provider transports are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def install_provider_egress_guard(transport: Any, *, allow_private_network: bool) -> None:
    """Install the guarded backend on a no-proxy httpx AsyncHTTPTransport."""
    pool = getattr(transport, "_pool", None)
    if isinstance(pool, httpcore.AsyncHTTPProxy):
        raise RuntimeError("provider egress guard does not permit proxy transports")
    if not isinstance(pool, httpcore.AsyncConnectionPool) or not hasattr(pool, "_network_backend"):
        raise RuntimeError(
            "unsupported httpx/httpcore transport internals; refusing unguarded egress"
        )
    pool._network_backend = DnsPinningBackend(allow_private_network=allow_private_network)
