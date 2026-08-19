from __future__ import annotations
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
import json
from urllib.request import HTTPRedirectHandler, Request, build_opener
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity, VerifiedPrincipal
from thesis_trace.modules.access.jwt_verifier import CloudflareJwtVerifier

class CloudflareIdentityAdapter:
    def __init__(self, verifier: CloudflareJwtVerifier, get_identity: Callable[[str], Mapping[str,Any]]) -> None:
        self._verifier,self._get_identity=verifier,get_identity
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            claims=self._verifier.verify_claims(token); full=self._get_identity(token); idp=full.get("idp",{})
            subject=str(claims.get("sub","")); full_subject=str(full.get("user_uuid",full.get("sub","")))
            provider_id=str(idp.get("id","")); provider_type=str(idp.get("type","")); amr=full.get("amr",[])
            if not subject or subject!=full_subject or not provider_id or not provider_type or not isinstance(amr, list) or "mfa" not in amr: raise PermissionError
            return VerifiedPrincipal(ProviderIdentity(provider_id,provider_type,subject),True,datetime.fromtimestamp(int(claims["exp"]),tz=timezone.utc))
        except Exception:
            raise PermissionError("access_denied") from None


class CloudflareGetIdentityClient:
    """Bounded token-forwarding client for Cloudflare's full identity endpoint."""

    def __init__(self, issuer: str, *, opener: Callable[..., Any] | None = None, timeout_seconds: float = 3.0) -> None:
        self._url = f"{issuer.rstrip('/')}/cdn-cgi/access/get-identity"
        self._opener = opener or build_opener(_RejectRedirects()).open
        self._timeout = timeout_seconds

    def __call__(self, token: str) -> Mapping[str, Any]:
        request = Request(self._url, headers={"Cookie": f"CF_Authorization={token}"})
        try:
            with self._opener(request, timeout=self._timeout) as response:
                if getattr(response, "status", 200) != 200:
                    raise PermissionError("access_denied")
                media_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
                if media_type not in {"application/json", "application/problem+json"}:
                    raise PermissionError("access_denied")
                body = response.read(64 * 1024 + 1)
                if len(body) > 64 * 1024:
                    raise PermissionError("access_denied")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise PermissionError("access_denied")
                return value
        except Exception:
            raise PermissionError("access_denied") from None


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CloudflareJwksDecoder:
    """Fetch and use Cloudflare signing keys without accepting redirects."""

    def __init__(self, issuer: str, audience: str, *, opener: Callable[..., Any] | None = None, timeout_seconds: float = 3.0) -> None:
        self._url = f"{issuer.rstrip('/')}/cdn-cgi/access/certs"
        self._issuer, self._audience = issuer, audience
        self._opener = opener or build_opener(_RejectRedirects()).open
        self._timeout = timeout_seconds

    def __call__(self, token: str, _configuration: Any) -> Mapping[str, Any]:
        request = Request(self._url, headers={"Accept": "application/json"})
        try:
            with self._opener(request, timeout=self._timeout) as response:
                if getattr(response, "status", 200) != 200:
                    raise PermissionError("access_denied")
                media_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
                if media_type not in {"application/json", "application/jwk-set+json"}:
                    raise PermissionError("access_denied")
                body = response.read(256 * 1024 + 1)
                if len(body) > 256 * 1024:
                    raise PermissionError("access_denied")
                jwks = json.loads(body)
                if not isinstance(jwks, dict):
                    raise PermissionError("access_denied")

            import jwt

            key_id = str(jwt.get_unverified_header(token).get("kid", ""))
            keys = [key for key in jwt.PyJWKSet.from_dict(jwks).keys if key.key_id == key_id]
            if not key_id or len(keys) != 1:
                raise PermissionError("access_denied")
            return jwt.decode(
                token,
                keys[0].key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub", "email"]},
            )
        except Exception:
            raise PermissionError("access_denied") from None
