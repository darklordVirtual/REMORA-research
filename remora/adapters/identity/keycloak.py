# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Keycloak identity adapter for on-premises OIDC.

Requirements:
    pip install pyjwt cryptography requests
"""
from __future__ import annotations

from remora.adapters.identity import Identity, IdentityAdapter


class KeycloakAdapter(IdentityAdapter):
    """Validate Keycloak bearer tokens via OIDC discovery.

    Parameters
    ----------
    server_url:
        Keycloak server URL (e.g. https://keycloak.internal.example.com).
    realm:
        Keycloak realm name.
    client_id:
        Expected audience (client ID).
    roles_claim:
        JWT claim containing roles. Keycloak uses 'realm_access.roles' by default.
    """

    def __init__(self, server_url: str, realm: str, client_id: str, roles_claim: str = "realm_access"):
        self._server_url = server_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._roles_claim = roles_claim
        self._jwks_url = f"{self._server_url}/realms/{realm}/protocol/openid-connect/certs"
        self._issuer = f"{self._server_url}/realms/{realm}"

    def validate(self, token: str) -> Identity | None:
        import jwt as pyjwt
        from jwt import PyJWKClient

        try:
            jwks_client = PyJWKClient(self._jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._issuer,
            )
            subject = payload.get("sub", "unknown")
            realm_access = payload.get(self._roles_claim, {})
            roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
            return Identity(
                subject=subject,
                roles=tuple(roles),
                claims={k: str(v) for k, v in payload.items()},
            )
        except Exception as exc:
            # None is correct either way -- unverifiable is unauthenticated.
            # But an expired or malformed token (InvalidTokenError family)
            # and an unreachable JWKS endpoint are opposite operational
            # events, and both were an unlogged None: an IdP outage looked
            # exactly like credential stuffing (issue #45 gap 3).
            try:
                import logging as _logging

                import jwt as _pyjwt

                from remora.observability.events import governance_event

                rejected = isinstance(exc, _pyjwt.exceptions.InvalidTokenError)
                governance_event(
                    "identity.token_rejected" if rejected
                    else "identity.verification_unavailable",
                    level=_logging.INFO if rejected else _logging.ERROR,
                    idp="keycloak", error=type(exc).__name__,
                )
            except Exception:
                pass
            return None
