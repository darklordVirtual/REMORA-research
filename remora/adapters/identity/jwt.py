# Author: Stian Skogbrott
# License: Apache-2.0
"""JWT identity adapter — stateless token validation.

Works with any OIDC-compatible identity provider (Keycloak, Auth0, Entra ID).

Requirements:
    pip install pyjwt cryptography
"""
from __future__ import annotations

from remora.adapters.identity import Identity, IdentityAdapter


class JWTAdapter(IdentityAdapter):
    """Validate JWTs using a shared secret or public key.

    Parameters
    ----------
    secret_or_key:
        HMAC secret or RSA/EC public key (PEM format).
    algorithms:
        Allowed algorithms (default: HS256).
    audience:
        Expected audience claim. None to skip validation.
    issuer:
        Expected issuer claim. None to skip validation.
    roles_claim:
        JWT claim that contains the user's roles (default: 'roles').
    """

    def __init__(
        self,
        secret_or_key: str,
        algorithms: list[str] | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        roles_claim: str = "roles",
    ):
        self._secret = secret_or_key
        self._algorithms = algorithms or ["HS256"]
        self._audience = audience
        self._issuer = issuer
        self._roles_claim = roles_claim

    def validate(self, token: str) -> Identity | None:
        import jwt as pyjwt

        try:
            payload = pyjwt.decode(
                token,
                self._secret,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
            )
            subject = payload.get("sub", "unknown")
            roles = payload.get(self._roles_claim, [])
            if isinstance(roles, str):
                roles = [roles]
            return Identity(
                subject=subject,
                roles=tuple(roles),
                claims={k: str(v) for k, v in payload.items()},
            )
        except pyjwt.PyJWTError:
            return None
