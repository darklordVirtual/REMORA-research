# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Credential scope observed from the issuer, not declared by the provider (Q3.3).

The signed ToolSpec bundle's credential-scope check compares the scope a
tool uses with the scope its signed spec declares. Until now the only input the
reference runtime could give it was the scope the deployment *provider*
said the tool had: an assertion by the party whose tools are being checked.

This module supplies the other input. A :class:`CredentialIssuer` issues each
tool a scoped credential and can be *queried* for the scope a credential
actually carries. The reference runtime obtains the credential at
registration, asks the issuer for its scope, and compares that with the
signed spec; it asks again immediately before every dispatch, so a grant
widened after registration is refused.

:class:`ReferenceCredentialIssuer` is the reference form: stateless,
HMAC-signed credentials whose scope is fixed by the issuer's own grant
policy, not by the requester. A request for more than the grant is narrowed
to the grant, never widened.

Scope: a reference issuer in the same trust domain as the runtime. A
production deployment replaces it with an adapter over its real issuer (a
secrets manager or a cloud token service) behind the same two methods.
REMORA checks the scope the issuer reports; it cannot check that the
downstream system enforces that scope.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from remora.errors import RemoraError

__all__ = [
    "CredentialIssuer",
    "CredentialRefused",
    "IssuedCredential",
    "ReferenceCredentialIssuer",
]


class CredentialRefused(RemoraError):
    """The issuer did not vouch for this credential."""

    code = "credential_refused"
    category = "enforcement"


@dataclass(frozen=True)
class IssuedCredential:
    credential_id: str
    issuer_id: str
    tool_id: str
    scope: tuple[str, ...]
    expires_at: float
    signature: str

    def _payload(self) -> bytes:
        return json.dumps(
            {"credential_id": self.credential_id, "expires_at": self.expires_at,
             "issuer_id": self.issuer_id, "scope": list(self.scope), "tool_id": self.tool_id},
            sort_keys=True, separators=(",", ":")).encode()


@runtime_checkable
class CredentialIssuer(Protocol):
    def issue(self, tool_id: str, requested: Sequence[str]) -> IssuedCredential:
        """A credential for ``tool_id``, at most the issuer's grant."""
        ...

    def introspect(self, credential: IssuedCredential) -> tuple[str, ...]:
        """The scope the issuer vouches this credential carries. Raises
        ``CredentialRefused`` for one it did not issue, or that expired."""
        ...


class ReferenceCredentialIssuer:
    """Stateless, HMAC-signed credentials scoped by the issuer's own grants."""

    def __init__(self, *, key: bytes, issuer_id: str,
                 grants: Mapping[str, Sequence[str]], ttl_seconds: float = 300.0) -> None:
        if not key:
            raise ValueError("an issuer needs a signing key")
        self._key = key
        self.issuer_id = issuer_id
        self._grants = MappingProxyType({t: tuple(sorted(set(s))) for t, s in grants.items()})
        self._ttl = ttl_seconds

    def _sign(self, credential: IssuedCredential) -> str:
        return hmac.new(self._key, credential._payload(), hashlib.sha256).hexdigest()

    def issue(self, tool_id: str, requested: Sequence[str]) -> IssuedCredential:
        grant = self._grants.get(tool_id)
        if grant is None:
            raise CredentialRefused(f"issuer {self.issuer_id!r} grants nothing to {tool_id!r}")
        # The issuer's policy decides: a request can narrow the grant, never widen it.
        scope = tuple(sorted(set(requested) & set(grant))) if requested else grant
        unsigned = IssuedCredential(str(uuid.uuid4()), self.issuer_id, tool_id, scope,
                                    time.time() + self._ttl, "")
        return IssuedCredential(unsigned.credential_id, unsigned.issuer_id, tool_id,
                                scope, unsigned.expires_at, self._sign(unsigned))

    def introspect(self, credential: IssuedCredential) -> tuple[str, ...]:
        if credential.issuer_id != self.issuer_id:
            raise CredentialRefused("credential from another issuer")
        if not hmac.compare_digest(self._sign(credential), credential.signature):
            raise CredentialRefused("credential signature does not verify")
        if credential.expires_at <= time.time():
            raise CredentialRefused("credential expired")
        return credential.scope
