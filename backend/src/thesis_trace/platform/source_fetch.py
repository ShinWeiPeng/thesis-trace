from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import ipaddress
import socket
import ssl
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from thesis_trace.modules.research.evidence_collection.contracts import FetchedSource


class SourceFetchFailure(RuntimeError):
    def __init__(self, failure_code: str, *, retryable: bool) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    content: bytes


class SourceTransport(Protocol):
    def fetch(self, url: str, approved_ip: str, *, timeout_seconds: float, max_bytes: int) -> TransportResponse: ...


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, approved_ip: str, *, timeout: float) -> None:
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self._approved_ip = approved_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._approved_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class PinnedHttpsTransport:
    def fetch(self, url: str, approved_ip: str, *, timeout_seconds: float, max_bytes: int) -> TransportResponse:
        parsed = urlsplit(url)
        connection = _PinnedHttpsConnection(parsed.hostname or "", approved_ip, timeout=timeout_seconds)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        try:
            connection.request("GET", path, headers={"User-Agent": "ThesisTrace/0.1"})
            response = connection.getresponse()
            headers = {name.casefold(): value for name, value in response.getheaders()}
            return TransportResponse(response.status, headers, response.read(max_bytes + 1))
        finally:
            connection.close()


def _resolve(hostname: str) -> list[str]:
    return sorted({item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)})


class RestrictedHttpSourceFetcher:
    def __init__(self, *, max_bytes: int = 2_000_000, timeout_seconds: float = 15,
                 max_redirects: int = 3, resolver: Callable[[str], Sequence[str]] = _resolve,
                 transport: SourceTransport | None = None) -> None:
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._transport = transport or PinnedHttpsTransport()

    def fetch(self, url: str) -> FetchedSource:
        current_url = url
        try:
            for redirect_count in range(self._max_redirects + 1):
                parsed = urlsplit(current_url)
                if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                        or parsed.port not in (None, 443)):
                    raise SourceFetchFailure("source_policy_rejected", retryable=False)
                addresses = list(self._resolver(parsed.hostname))
                if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
                    raise SourceFetchFailure("source_address_rejected", retryable=False)
                response = self._transport.fetch(
                    current_url, addresses[0], timeout_seconds=self._timeout_seconds, max_bytes=self._max_bytes
                )
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count >= self._max_redirects:
                        raise SourceFetchFailure("source_redirect_rejected", retryable=False)
                    current_url = urljoin(current_url, location)
                    continue
                if response.status != 200:
                    retryable = response.status >= 500 or response.status == 429
                    raise SourceFetchFailure("source_http_error", retryable=retryable)
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                if media_type not in {"text/html", "text/plain", "application/pdf", "application/json"}:
                    raise SourceFetchFailure("source_media_type_rejected", retryable=False)
                if len(response.content) > self._max_bytes:
                    raise SourceFetchFailure("source_too_large", retryable=False)
                retrieved_at = datetime.now(timezone.utc).isoformat()
                return FetchedSource(
                    canonical_url=current_url, publisher=parsed.hostname, content=response.content,
                    retrieved_at=retrieved_at, observed_at=retrieved_at,
                    excerpt=response.content[:500].decode("utf-8", errors="replace"),
                    source_category="C", lineage=url,
                )
            raise SourceFetchFailure("source_redirect_rejected", retryable=False)
        except SourceFetchFailure:
            raise
        except Exception as error:
            raise SourceFetchFailure("source_unavailable", retryable=True) from error
