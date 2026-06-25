"""Tests for AccessContext and its integration with CloudflareRAGOracle."""
from __future__ import annotations

import pytest

from remora.adapters.identity import AccessContext, Identity


# ── AccessContext unit tests ──────────────────────────────────────────────────

class TestAllowedClearances:
    def test_public_sees_only_public(self):
        ctx = AccessContext(subject="u", clearance_level="public")
        assert ctx.allowed_clearances() == ["public"]

    def test_internal_sees_public_and_internal(self):
        ctx = AccessContext(subject="u", clearance_level="internal")
        assert ctx.allowed_clearances() == ["public", "internal"]

    def test_restricted_is_cumulative(self):
        ctx = AccessContext(subject="u", clearance_level="restricted")
        assert ctx.allowed_clearances() == ["public", "internal", "restricted"]

    def test_secret_sees_all(self):
        ctx = AccessContext(subject="u", clearance_level="secret")
        assert ctx.allowed_clearances() == ["public", "internal", "restricted", "secret"]

    def test_unknown_clearance_falls_back_to_public(self):
        ctx = AccessContext(subject="u", clearance_level="top_secret_xyz")
        assert ctx.allowed_clearances() == ["public"]


class TestAllows:
    def test_public_allows_public(self):
        ctx = AccessContext(subject="u", clearance_level="public")
        assert ctx.allows("public") is True

    def test_public_denies_internal(self):
        ctx = AccessContext(subject="u", clearance_level="public")
        assert ctx.allows("internal") is False

    def test_restricted_allows_public(self):
        ctx = AccessContext(subject="u", clearance_level="restricted")
        assert ctx.allows("public") is True

    def test_restricted_allows_internal(self):
        ctx = AccessContext(subject="u", clearance_level="restricted")
        assert ctx.allows("internal") is True

    def test_restricted_allows_restricted(self):
        ctx = AccessContext(subject="u", clearance_level="restricted")
        assert ctx.allows("restricted") is True

    def test_restricted_denies_secret(self):
        ctx = AccessContext(subject="u", clearance_level="restricted")
        assert ctx.allows("secret") is False


class TestFromIdentity:
    def test_maps_clearance_claim(self):
        identity = Identity(
            subject="alice",
            roles=(),
            claims={"clearance": "internal"},
        )
        ctx = AccessContext.from_identity(identity)
        assert ctx.subject == "alice"
        assert ctx.clearance_level == "internal"

    def test_defaults_to_public_when_no_clearance_claim(self):
        identity = Identity(subject="bob", roles=(), claims={})
        ctx = AccessContext.from_identity(identity)
        assert ctx.clearance_level == "public"

    def test_maps_roles_to_acl_groups(self):
        identity = Identity(
            subject="carol",
            roles=("finance", "legal"),
            claims={},
        )
        ctx = AccessContext.from_identity(identity)
        assert set(ctx.acl_groups) == {"finance", "legal"}

    def test_reads_entra_id_tid_claim(self):
        identity = Identity(
            subject="dave",
            roles=(),
            claims={"tid": "org_acme"},
        )
        ctx = AccessContext.from_identity(identity)
        assert ctx.tenant_id == "org_acme"

    def test_reads_keycloak_tenant_id_claim(self):
        identity = Identity(
            subject="eve",
            roles=(),
            claims={"tenant_id": "org_beta"},
        )
        ctx = AccessContext.from_identity(identity)
        assert ctx.tenant_id == "org_beta"

    def test_tid_takes_precedence_over_tenant_id(self):
        identity = Identity(
            subject="frank",
            roles=(),
            claims={"tid": "org_from_tid", "tenant_id": "org_from_tenant_id"},
        )
        ctx = AccessContext.from_identity(identity)
        assert ctx.tenant_id == "org_from_tid"

    def test_tenant_id_none_when_no_claim(self):
        identity = Identity(subject="grace", roles=(), claims={})
        ctx = AccessContext.from_identity(identity)
        assert ctx.tenant_id is None

    def test_result_is_frozen(self):
        identity = Identity(subject="h", roles=(), claims={})
        ctx = AccessContext.from_identity(identity)
        with pytest.raises(Exception):  # dataclass(frozen=True) → FrozenInstanceError
            ctx.clearance_level = "secret"  # type: ignore[misc]


# ── CloudflareRAGOracle.with_access integration ───────────────────────────────

class TestWithAccess:
    """Verify with_access() creates a scoped instance without mutating the original."""

    def _make_oracle(self):
        from remora.oracles.cloudflare_rag import CloudflareRAGOracle
        return CloudflareRAGOracle(
            domain="test",
            worker_url="https://example.com",
        )

    def test_with_access_returns_new_instance(self):
        oracle = self._make_oracle()
        ctx = AccessContext(subject="u", clearance_level="internal")
        scoped = oracle.with_access(ctx)
        assert scoped is not oracle

    def test_original_has_no_access_context(self):
        oracle = self._make_oracle()
        ctx = AccessContext(subject="u", clearance_level="internal")
        oracle.with_access(ctx)
        # Original must be unchanged — no access context set
        assert oracle._access_context is None

    def test_scoped_oracle_carries_access_context(self):
        oracle = self._make_oracle()
        ctx = AccessContext(
            subject="u",
            clearance_level="restricted",
            acl_groups=("legal",),
            tenant_id="org_acme",
        )
        scoped = oracle.with_access(ctx)
        assert scoped._access_context is ctx

    def test_with_access_called_twice_gives_latest_context(self):
        oracle = self._make_oracle()
        ctx1 = AccessContext(subject="u1", clearance_level="public")
        ctx2 = AccessContext(subject="u2", clearance_level="secret")
        scoped1 = oracle.with_access(ctx1)
        scoped2 = oracle.with_access(ctx2)
        assert scoped1._access_context is ctx1
        assert scoped2._access_context is ctx2
        # Original still unchanged
        assert oracle._access_context is None
