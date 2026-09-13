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


def test_malformed_port_is_a_permanent_policy_rejection() -> None:
    fetcher = RestrictedHttpSourceFetcher(
        transport=RecordingTransport([]),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(SourceFetchFailure) as captured:
        fetcher.fetch("https://public.example:not-a-port/a")

    assert captured.value.failure_code == "source_policy_rejected"
    assert captured.value.retryable is False


def test_malformed_host_is_a_permanent_policy_rejection() -> None:
    fetcher = RestrictedHttpSourceFetcher(
        transport=RecordingTransport([]),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(SourceFetchFailure) as captured:
        fetcher.fetch("https://[not-an-ip]/")

    assert captured.value.failure_code == "source_policy_rejected"
    assert captured.value.retryable is False


def test_fragment_is_removed_from_transport_and_canonical_url() -> None:
    transport = RecordingTransport([
        TransportResponse(200, {"content-type": "text/plain"}, b"official disclosure"),
    ])
    fetcher = RestrictedHttpSourceFetcher(
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    fetched = fetcher.fetch("https://public.example/disclosure#section-2")

    assert transport.calls == [("https://public.example/disclosure", "93.184.216.34")]
    assert fetched.canonical_url == "https://public.example/disclosure"
    assert fetched.normalization_policy_version == "url-normalization-v1"


def test_host_and_default_https_port_are_canonicalized() -> None:
    transport = RecordingTransport([
        TransportResponse(200, {"content-type": "text/plain"}, b"official disclosure"),
    ])
    fetcher = RestrictedHttpSourceFetcher(
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    fetched = fetcher.fetch("https://PUBLIC.EXAMPLE:443/disclosure")

    assert transport.calls == [("https://public.example/disclosure", "93.184.216.34")]
    assert fetched.canonical_url == "https://public.example/disclosure"


def test_empty_path_is_canonicalized_to_root() -> None:
    transport = RecordingTransport([
        TransportResponse(200, {"content-type": "text/plain"}, b"official disclosure"),
    ])
    fetcher = RestrictedHttpSourceFetcher(
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    fetched = fetcher.fetch("https://public.example")

    assert transport.calls == [("https://public.example/", "93.184.216.34")]
    assert fetched.canonical_url == "https://public.example/"


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        (
            "https://PUBLIC.EXAMPLE:443/a/%2e%2e/B?b=2&a=1&a=0#section",
            "https://public.example/a/%2e%2e/B?b=2&a=1&a=0",
        ),
        (
            "https://PUBLIC.EXAMPLE:443/A/%7euser?x=&x=1&=empty#section",
            "https://public.example/A/%7euser?x=&x=1&=empty",
        ),
        (
            "https://PUBLIC.EXAMPLE:443/a//b/./c?#section",
            "https://public.example/a//b/./c?",
        ),
        (
            "https://PUBLIC.EXAMPLE:443/%2F?b=2&a=1#section",
            "https://public.example/%2F?b=2&a=1",
        ),
    ],
)
def test_v1_preserves_path_and_query_variants_and_is_idempotent(original: str, expected: str) -> None:
    first_transport = RecordingTransport([
        TransportResponse(200, {"content-type": "text/plain"}, b"official disclosure"),
    ])
    second_transport = RecordingTransport([
        TransportResponse(200, {"content-type": "text/plain"}, b"official disclosure"),
    ])
    first_fetcher = RestrictedHttpSourceFetcher(
        transport=first_transport,
        resolver=lambda host: ["93.184.216.34"],
    )
    second_fetcher = RestrictedHttpSourceFetcher(
        transport=second_transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    first = first_fetcher.fetch(original)
    second = second_fetcher.fetch(first.canonical_url)

    assert first.canonical_url == expected
    assert second.canonical_url == expected
    assert first.normalization_policy_version == "url-normalization-v1"
    assert second.normalization_policy_version == first.normalization_policy_version
    assert first_transport.calls == [(expected, "93.184.216.34")]
    assert second_transport.calls == [(expected, "93.184.216.34")]
