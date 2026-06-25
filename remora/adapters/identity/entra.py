# Author: Stian Skogbrott
# License: Apache-2.0
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
        except Exception:
            return None
