from __future__ import annotations

import time
import json

import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from thesis_trace.modules.access.jwt_verifier import (
    AccessJwtConfiguration,
    CloudflareJwtVerifier,
    JwtVerificationError,
    derive_identity_facts,
)
from thesis_trace.adapters.cloudflare_identity.adapter import CloudflareJwksDecoder


class JwksResponse:
    def __init__(self, body: bytes, *, status: int = 200, media: str = "application/jwk-set+json") -> None:
        self.body, self.status, self.headers = body, status, {"Content-Type": media}
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size: int) -> bytes: return self.body[:size]


def jwks_decoder(public_key, *, status: int = 200) -> CloudflareJwksDecoder:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    body = json.dumps({"keys": [jwk]}).encode()
    return CloudflareJwksDecoder(
        "https://team.cloudflareaccess.com",
        "aud",
        opener=lambda request, timeout: JwksResponse(body, status=status),
    )


def test_access_jwt_accepts_only_matching_issuer_audience_and_identity() -> None:
    now = int(time.time())
    claims = {
        "iss": "https://team.cloudflareaccess.com",
        "aud": ["app-audience"],
        "sub": "identity-1",
        "email": "owner@example.com",
        "exp": now + 60,
        "iat": now - 1,
    }
    verifier = CloudflareJwtVerifier(
        AccessJwtConfiguration(
            issuer="https://team.cloudflareaccess.com",
            audience="app-audience",
            allowed_identity_facts=derive_identity_facts("owner@example.com"),
        ),
        decoder=lambda token, config: claims,
        clock=lambda: now,
    )

    actor = verifier.verify("signed-token")

    assert actor.actor_id == "identity-1"
    assert actor.identity_version == 1


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.invalid"},
        {"aud": ["other"]},
        {"email": "stranger@example.com"},
        {"exp": 0},
    ],
)
def test_access_jwt_fails_closed_for_invalid_claims(change: dict[str, object]) -> None:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "https://team.cloudflareaccess.com",
        "aud": ["app-audience"],
        "sub": "identity-1",
        "email": "owner@example.com",
        "exp": now + 60,
    }
    claims.update(change)
    verifier = CloudflareJwtVerifier(
        AccessJwtConfiguration(
            issuer="https://team.cloudflareaccess.com",
            audience="app-audience",
            allowed_identity_facts=derive_identity_facts("owner@example.com"),
        ),
        decoder=lambda token, config: claims,
        clock=lambda: now,
    )

    with pytest.raises(JwtVerificationError):
        verifier.verify("signed-token")


def test_access_jwt_rejects_missing_token_or_configuration() -> None:
    with pytest.raises(ValueError):
        AccessJwtConfiguration(issuer="", audience="aud", allowed_identity_facts=derive_identity_facts("a@b"))

    verifier = CloudflareJwtVerifier(
        AccessJwtConfiguration("https://team.cloudflareaccess.com", "aud", derive_identity_facts("a@b")),
        decoder=lambda token, config: {},
    )
    with pytest.raises(JwtVerificationError):
        verifier.verify("")


def test_real_rs256_signature_is_verified_against_local_jwks() -> None:
    now = int(time.time())
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode({"iss": "https://team.cloudflareaccess.com", "aud": ["aud"], "sub": "owner-id",
        "email": "owner@example.com", "iat": now, "exp": now + 60}, private_key, algorithm="RS256", headers={"kid": "key-1"})
    verifier = CloudflareJwtVerifier(AccessJwtConfiguration(
        "https://team.cloudflareaccess.com", "aud", derive_identity_facts("owner@example.com")),
        decoder=jwks_decoder(public_key), clock=lambda: now)
    assert verifier.verify(token).actor_id == "owner-id"


def test_real_rs256_wrong_key_and_jwks_failure_fail_closed() -> None:
    now = int(time.time())
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    token = jwt.encode({"iss": "https://team.cloudflareaccess.com", "aud": "aud", "sub": "owner-id",
        "email": "owner@example.com", "exp": now + 60}, signing_key, algorithm="RS256", headers={"kid": "key-1"})
    verifier = CloudflareJwtVerifier(AccessJwtConfiguration(
        "https://team.cloudflareaccess.com", "aud", derive_identity_facts("owner@example.com")),
        decoder=jwks_decoder(wrong_key), clock=lambda: now)
    with pytest.raises(JwtVerificationError): verifier.verify(token)

    failed = CloudflareJwksDecoder(
        "https://team.cloudflareaccess.com",
        "aud",
        opener=lambda request, timeout: (_ for _ in ()).throw(RuntimeError("jwks unavailable")),
    )
    unavailable = CloudflareJwtVerifier(AccessJwtConfiguration(
        "https://team.cloudflareaccess.com", "aud", derive_identity_facts("owner@example.com")),
        decoder=failed, clock=lambda: now)
    with pytest.raises(JwtVerificationError): unavailable.verify(token)


def test_jwks_redirect_and_wrong_media_fail_closed_without_following() -> None:
    configuration = AccessJwtConfiguration(
        "https://team.cloudflareaccess.com", "aud", derive_identity_facts("owner@example.com")
    )
    for response in (JwksResponse(b"{}", status=302), JwksResponse(b"{}", media="text/html")):
        calls: list[str] = []
        decoder = CloudflareJwksDecoder(
            configuration.issuer,
            configuration.audience,
            opener=lambda request, timeout, response=response: calls.append(request.full_url) or response,
        )
        with pytest.raises(PermissionError) as caught:
            decoder("not-a-token", configuration)
        assert calls == ["https://team.cloudflareaccess.com/cdn-cgi/access/certs"]
        assert caught.value.__cause__ is None
