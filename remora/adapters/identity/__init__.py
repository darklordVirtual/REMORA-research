# Author: Stian Skogbrott
# License: Apache-2.0
"""Identity adapters — platform-agnostic authentication and authorisation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    """Authenticated identity."""
    subject: str
    roles: tuple[str, ...]
    claims: dict[str, str]


# Ordered clearance ladder — each level implies access to all levels below.
_CLEARANCE_LEVELS: tuple[str, ...] = ("public", "internal", "restricted", "secret")


@dataclass(frozen=True)
class AccessContext:
    """Runtime access context for RAG retrieval and tool-call policy enforcement.

    Derived from a validated Identity and passed *optionally* to
    :class:`~remora.oracles.cloudflare_rag.CloudflareRAGOracle` and the
    tool-call policy gate.  When absent, no access restrictions are applied
    (suitable only for fully-trusted internal contexts).

    Usage::

        identity = jwt_adapter.validate(bearer_token)
        ctx = AccessContext.from_identity(identity)

        # Scoped oracle — returns a new instance, thread-safe
        oracle = base_rag_oracle.with_access(ctx)
        response = oracle.ask(prompt)

    Clearance levels (cumulative, lowest → highest)::

        public     — unrestricted; visible to all authenticated users
        internal   — employees / service accounts
        restricted — approved personnel; sensitive business data
        secret     — highest grade; legal / regulatory / classified

    Multi-tenant isolation::

        Set *tenant_id* to enforce hard per-organisation boundaries in the
        Vectorize index.  All queries are filtered to ``tenant_id == ctx.tenant_id``
        before any clearance filter is applied.

    ACL groups::

        Fine-grained within a clearance level.  Mapped from Identity.roles.
        Post-retrieval filter: chunks whose ``acl_groups`` metadata does not
        intersect the user's groups are dropped before LLM synthesis.
    """

    subject: str
    clearance_level: str = "public"          # see _CLEARANCE_LEVELS
    acl_groups: tuple[str, ...] = field(default_factory=tuple)  # e.g. ("finance", "legal")
    tenant_id: str | None = None             # multi-tenant org boundary

    def allowed_clearances(self) -> list[str]:
        """Return all clearance labels this context may see (cumulative).

        Example: clearance_level='restricted' → ['public', 'internal', 'restricted']
        """
        try:
            idx = _CLEARANCE_LEVELS.index(self.clearance_level)
        except ValueError:
            idx = 0  # unknown level → treat as public
        return list(_CLEARANCE_LEVELS[: idx + 1])

    def allows(self, doc_clearance: str) -> bool:
        """Return True if this context is permitted to see *doc_clearance* documents."""
        return doc_clearance in self.allowed_clearances()

    @classmethod
    def from_identity(cls, identity: Identity) -> AccessContext:
        """Build an AccessContext from a validated Identity.

        JWT claim mapping:

        * ``clearance``  → clearance_level (default: ``'public'``)
        * Identity.roles  → acl_groups
        * ``tid``         → tenant_id (Entra ID convention)
        * ``tenant_id``   → tenant_id (Keycloak / custom OIDC)
        """
        return cls(
            subject=identity.subject,
            clearance_level=identity.claims.get("clearance", "public"),
            acl_groups=tuple(identity.roles),
            tenant_id=(
                identity.claims.get("tid")
                or identity.claims.get("tenant_id")
                or None
            ),
        )


class IdentityAdapter(ABC):
    """Abstract base class for identity adapters.

    Validates tokens/credentials and returns an Identity object with
    the authenticated subject and their roles.
    """

    @abstractmethod
    def validate(self, token: str) -> Identity | None:
        """Validate a token and return the identity, or None if invalid."""
        ...
