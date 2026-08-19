from __future__ import annotations

import pytest

from thesis_trace.platform.source_fetch import RestrictedHttpSourceFetcher, SourceFetchFailure, TransportResponse


class RecordingTransport:
    def __init__(self, responses: list[TransportResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def fetch(self, url: str, approved_ip: str, *, timeout_seconds: float, max_bytes: int) -> TransportResponse:
        self.calls.append((url, approved_ip))
        return self.responses.pop(0)


def test_redirect_target_is_resolved_and_rejected_before_second_connection() -> None:
    transport = RecordingTransport([TransportResponse(302, {"location": "https://metadata.invalid/secret"}, b"")])
    addresses = {"public.example": ["93.184.216.34"], "metadata.invalid": ["169.254.169.254"]}
    fetcher = RestrictedHttpSourceFetcher(transport=transport, resolver=lambda host: addresses[host])

    with pytest.raises(SourceFetchFailure, match="source_address_rejected"):
        fetcher.fetch("https://public.example/a")

    assert transport.calls == [("https://public.example/a", "93.184.216.34")]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (TransportResponse(200, {"content-type": "image/png"}, b"x"), "source_media_type_rejected"),
        (TransportResponse(200, {"content-type": "text/plain"}, b"toolarge"), "source_too_large"),
    ],
)
def test_media_type_and_size_are_enforced(response: TransportResponse, code: str) -> None:
    fetcher = RestrictedHttpSourceFetcher(
        max_bytes=4, transport=RecordingTransport([response]), resolver=lambda host: ["93.184.216.34"]
    )
    with pytest.raises(SourceFetchFailure, match=code):
        fetcher.fetch("https://public.example/a")


def test_transport_receives_the_validated_ip_so_dns_cannot_rebind() -> None:
    transport = RecordingTransport([TransportResponse(200, {"content-type": "text/plain"}, b"ok")])
    calls = 0
    def resolver(host: str) -> list[str]:
        nonlocal calls
        calls += 1
        return ["93.184.216.34"] if calls == 1 else ["127.0.0.1"]

    RestrictedHttpSourceFetcher(transport=transport, resolver=resolver).fetch("https://public.example/a")
    assert calls == 1
    assert transport.calls[0][1] == "93.184.216.34"
