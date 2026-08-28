# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Microsoft Entra ID (Azure AD) identity adapter.

Validates Entra ID bearer tokens using OIDC discovery and JWKS.

Requirements:
    pip install pyjwt cryptography requests
"""
from __future__ import annotations

from remora.adapters.identity import Identity, IdentityAdapter


class EntraIDAdapter(IdentityAdapter):
    """Validate Microsoft Entra ID bearer tokens.

    Parameters
    ----------
    tenant_id:
        Azure AD tenant ID.
    client_id:
        Application (client) ID — used as the expected audience.
    roles_claim:
        JWT claim containing roles (default: 'roles' for app roles).
    """

    def __init__(self, tenant_id: str, client_id: str, roles_claim: str = "roles"):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._roles_claim = roles_claim
        self._jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._issuer = f"https://sts.windows.net/{tenant_id}/"

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
            subject = payload.get("sub", payload.get("oid", "unknown"))
            roles = payload.get(self._roles_claim, [])
            if isinstance(roles, str):
                roles = [roles]
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
                    idp="entra", error=type(exc).__name__,
                )
            except Exception:
                pass  # telemetry must never turn an auth failure into a crash
            return None
