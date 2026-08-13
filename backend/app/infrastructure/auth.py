"""Provider-neutral OIDC bearer-token verification.

The verifier accepts only signed tokens from the configured issuer. It does
not decode or trust client-controlled identity headers, and it never logs the
token or its claims.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

import jwt
from jwt import InvalidTokenError, PyJWKClient

from backend.app.contracts.identity import AuthenticatedPrincipal, AuthenticationError


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class OidcBearerTokenVerifier:
    """Verify an OIDC access token with an explicit asymmetric allowlist."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        algorithms: Iterable[str] = ("RS256",),
        identity_verified_claim: str = "identity_verified",
        jwks_client: SigningKeyClient | None = None,
        leeway_seconds: int = 5,
    ) -> None:
        if not issuer.strip() or not audience.strip() or not jwks_url.strip():
            raise ValueError("OIDC issuer, audience, and JWKS URL are required")
        allowed = tuple(dict.fromkeys(algorithms))
        if not allowed or any(
            algorithm not in {"RS256", "ES256", "EdDSA"} for algorithm in allowed
        ):
            raise ValueError("Only approved asymmetric OIDC algorithms are allowed")
        if not identity_verified_claim.strip():
            raise ValueError("identity_verified_claim is required")
        self._issuer = issuer
        self._audience = audience
        self._algorithms = allowed
        self._identity_verified_claim = identity_verified_claim
        self._jwks_client = jwks_client or PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )
        self._leeway_seconds = leeway_seconds

    def authenticate(self, authorization_header: str) -> AuthenticatedPrincipal:
        token = self._extract_bearer(authorization_header)
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (InvalidTokenError, OSError, TimeoutError) as exc:
            raise AuthenticationError("Invalid bearer token") from exc
        except Exception as exc:
            # Provider/JWKS failures must not leak transport details or result
            # in an unauthenticated principal.
            raise AuthenticationError("Bearer token verification unavailable") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("Token subject is invalid")
        roles = self._string_set(claims.get("roles", ()))
        scopes = self._parse_scopes(claims.get("scope", ""))
        identity_verified = claims.get(self._identity_verified_claim) is True
        return AuthenticatedPrincipal(
            subject_ref=f"oidc:{subject}",
            roles=roles,
            scopes=scopes,
            identity_verified=identity_verified,
        )

    @staticmethod
    def _extract_bearer(authorization_header: str) -> str:
        pieces = authorization_header.strip().split()
        if len(pieces) != 2 or pieces[0].lower() != "bearer" or not pieces[1].strip():
            raise AuthenticationError("Bearer authentication is required")
        return pieces[1]

    @staticmethod
    def _string_set(value: object) -> frozenset[str]:
        if not isinstance(value, (list, tuple, set)):
            return frozenset()
        return frozenset(item for item in value if isinstance(item, str) and item.strip())

    @staticmethod
    def _parse_scopes(value: object) -> frozenset[str]:
        if not isinstance(value, str):
            return frozenset()
        return frozenset(item for item in value.split() if item.strip())
