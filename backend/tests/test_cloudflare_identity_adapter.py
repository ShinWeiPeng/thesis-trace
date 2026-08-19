from __future__ import annotations
from datetime import datetime, timezone
import pytest
from thesis_trace.adapters.cloudflare_identity.adapter import CloudflareGetIdentityClient, CloudflareIdentityAdapter
from thesis_trace.modules.access.jwt_verifier import AccessJwtConfiguration, CloudflareJwtVerifier, derive_identity_facts

def verifier(claims):
    return CloudflareJwtVerifier(AccessJwtConfiguration("https://team.cloudflareaccess.com","aud",derive_identity_facts("same@example.com")),decoder=lambda token,config: claims,clock=lambda: 100)

def test_token_bound_identity_uses_idp_discriminator_and_mfa() -> None:
    adapter=CloudflareIdentityAdapter(verifier({"iss":"https://team.cloudflareaccess.com","aud":"aud","sub":"sub-1","email":"same@example.com","exp":200}),lambda token:{"user_uuid":"sub-1","idp":{"id":"google-id","type":"google"},"amr":["mfa"]})
    principal=adapter.verify("token")
    assert (principal.identity.provider_id,principal.identity.provider_type,principal.identity.subject)==("google-id","google","sub-1")
    assert principal.mfa_assured

@pytest.mark.parametrize("identity",[{}, {"user_uuid":"other","idp":{"id":"x","type":"google"},"amr":["mfa"]}, {"user_uuid":"sub-1","idp":{},"amr":["mfa"]}])
def test_missing_inconsistent_or_unavailable_identity_fails_closed(identity) -> None:
    adapter=CloudflareIdentityAdapter(verifier({"iss":"https://team.cloudflareaccess.com","aud":"aud","sub":"sub-1","email":"same@example.com","exp":200}),lambda token:identity)
    with pytest.raises(PermissionError): adapter.verify("token")

def test_lookup_outage_fails_closed() -> None:
    def failed(token): raise OSError("outage")
    with pytest.raises(PermissionError): CloudflareIdentityAdapter(verifier({"iss":"https://team.cloudflareaccess.com","aud":"aud","sub":"sub-1","email":"same@example.com","exp":200}),failed).verify("token")

def test_missing_official_mfa_amr_fails_closed() -> None:
    adapter=CloudflareIdentityAdapter(verifier({"iss":"https://team.cloudflareaccess.com","aud":"aud","sub":"sub-1","email":"same@example.com","exp":200}),lambda token:{"user_uuid":"sub-1","idp":{"id":"google-id","type":"google"},"amr":[]})
    with pytest.raises(PermissionError): adapter.verify("token")

@pytest.mark.parametrize("issuer", [
    "http://team.cloudflareaccess.com", "https://user@team.cloudflareaccess.com",
    "https://team.cloudflareaccess.com:443", "https://team.cloudflareaccess.com/path",
    "https://team.cloudflareaccess.com?query=1", "https://evil.example",
])
def test_jwt_and_identity_endpoint_require_canonical_cloudflare_issuer(issuer) -> None:
    with pytest.raises(ValueError):
        AccessJwtConfiguration(issuer, "aud", derive_identity_facts("same@example.com"))

class Response:
    def __init__(self, body=b"{}", media="application/json", status=200):
        self.body, self.headers, self.status = body, {"Content-Type": media}, status
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size): return self.body[:size]

def test_get_identity_rejects_redirect_media_and_oversize_without_secret_cause() -> None:
    token = "secret-token"
    for opener in (
        lambda request, timeout: Response(status=302),
        lambda request, timeout: Response(media="text/html"),
        lambda request, timeout: Response(body=b"x" * (64 * 1024 + 1)),
        lambda request, timeout: (_ for _ in ()).throw(RuntimeError(f"url and {token}")),
    ):
        with pytest.raises(PermissionError) as caught:
            CloudflareGetIdentityClient("https://team.cloudflareaccess.com", opener=opener)(token)
        assert str(caught.value) == "access_denied" and caught.value.__cause__ is None
        assert token not in repr(caught.value)
