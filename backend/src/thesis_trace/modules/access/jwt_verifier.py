from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import time
from typing import Any
from urllib.parse import urlsplit

from thesis_trace.modules.access.contracts import AuthenticatedActor, Role


class JwtVerificationError(PermissionError):
    """A stable, non-secret rejection for an invalid Access credential."""


@dataclass(frozen=True, slots=True)
class AccessJwtConfiguration:
    issuer: str
    audience: str
    allowed_identity_facts: frozenset[str]

    def __post_init__(self) -> None:
        if not self.issuer or not self.audience or not self.allowed_identity_facts:
            raise ValueError("Cloudflare Access JWT configuration is incomplete")
        parsed = urlsplit(self.issuer)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port is not None
                or not parsed.hostname or not parsed.hostname.endswith(".cloudflareaccess.com")
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Cloudflare Access issuer is not canonical")


def derive_identity_facts(secret_value: str) -> frozenset[str]:
    """Derive normalized one-way allowlist facts without retaining identity text."""
    return frozenset(
        sha256(identity.strip().casefold().encode("utf-8")).hexdigest()
        for identity in secret_value.split(",")
        if identity.strip()
    )


JwtDecoder = Callable[[str, AccessJwtConfiguration], Mapping[str, Any]]


class CloudflareJwtVerifier:
    def __init__(
        self,
        configuration: AccessJwtConfiguration,
        *,
        decoder: JwtDecoder | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._configuration = configuration
        self._decoder = decoder or _missing_decoder
        self._clock = clock

    def verify(self, token: str) -> AuthenticatedActor:
        claims = self.verify_claims(token)
        return AuthenticatedActor(str(claims["sub"]), Role.OWNER, 1)

    def verify_claims(self, token: str) -> Mapping[str, Any]:
        if not token:
            raise JwtVerificationError("access_token_required")
        try:
            claims = self._decoder(token, self._configuration)
            issuer = str(claims.get("iss", "")).rstrip("/")
            expected_issuer = self._configuration.issuer.rstrip("/")
            audiences = claims.get("aud", [])
            if isinstance(audiences, str):
                audiences = [audiences]
            email = str(claims.get("email", "")).casefold()
            subject = str(claims.get("sub", ""))
            expiry = int(claims.get("exp", 0))
            if issuer != expected_issuer:
                raise JwtVerificationError("invalid_issuer")
            if self._configuration.audience not in audiences:
                raise JwtVerificationError("invalid_audience")
            identity_fact = sha256(email.encode("utf-8")).hexdigest()
            if identity_fact not in self._configuration.allowed_identity_facts:
                raise JwtVerificationError("identity_not_allowed")
            if expiry <= int(self._clock()) or not subject:
                raise JwtVerificationError("token_expired_or_invalid")
            return claims
        except JwtVerificationError:
            raise
        except Exception as error:
            raise JwtVerificationError("token_invalid") from error


def _missing_decoder(_token: str, _configuration: AccessJwtConfiguration) -> Mapping[str, Any]:
    raise JwtVerificationError("jwt_decoder_required")
