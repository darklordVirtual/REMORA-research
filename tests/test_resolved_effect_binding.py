# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The lease binds the effect a call resolves to (quality program Q7.4).

Every other lease binding holds through an alias retarget, a resource
redirect or an implementation remap, because none of them changes the tool
name, the arguments, the tenant or the target. The resolved-effect digest is
the binding that does change, so the dispatcher can refuse.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.enforcement.resolved_effect import (
    ClosedWorldResolver,
    ResolvedEffect,
    UnresolvedReference,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = "b1"
ARGS = {"id": "WO-1"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "resolved-effect-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _resolver() -> ClosedWorldResolver:
    return ClosedWorldResolver(
        tools={"close_wo": ("workorder.close@1", "write")},
        resources={("prod", "WO-1"): "tenant-a/WO-1"},
        resource_argument={"close_wo": "id"})


def _lease(resolved: ResolvedEffect | None) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="close_wo", arguments=ARGS, target_environment="prod",
        policy_bundle_hash=BUNDLE, issued_at=datetime.now(UTC).isoformat(),
        resolved_effect=resolved)


def _dispatch(lease, resolver=None):
    calls: list = []
    dispatcher = GovernedToolDispatcher(BUNDLE)
    dispatcher.register("close_wo", lambda args: calls.append(args) or "ok")
    if resolver is not None:
        dispatcher.bind_effect_resolver(resolver)
    result = dispatcher.dispatch(lease, "close_wo", ARGS, tenant_id="acme",
                                 target_environment="prod", actor_identity="agent-1")
    return result, calls


class TestDigest:
    #: Frozen: changing the canonical form invalidates every issued lease.
    GOLDEN = ResolvedEffect("close_wo", "workorder.close@1", "tenant-a/WO-1", "write")

    def test_the_digest_is_frozen(self):
        assert self.GOLDEN.digest() == (
            "541bc8ffd4a04d859ae5e85f3d95f39802bb6d6a0c6f75b02077d4d90a31d007")

    def test_the_digest_matches_its_definition(self):
        import hashlib

        canonical = ('{"effect":"write","implementation":"workorder.close@1",'
                     '"resource":"tenant-a/WO-1","tool_name":"close_wo"}')
        assert self.GOLDEN.digest() == hashlib.sha256(canonical.encode()).hexdigest()

    @pytest.mark.parametrize("field", ["tool_name", "implementation", "resource", "effect"])
    def test_every_field_moves_the_digest(self, field):
        import dataclasses

        assert dataclasses.replace(self.GOLDEN, **{field: "x"}).digest() != self.GOLDEN.digest()


class TestTheDispatcherResolvesAgain:
    def test_an_unchanged_resolution_executes(self):
        resolver = _resolver()
        result, calls = _dispatch(_lease(resolver.resolve("close_wo", ARGS, "prod")), resolver)
        assert result.executed and calls == [ARGS]

    @pytest.mark.parametrize("change", [
        {"tools": {"close_wo": ("workorder.delete@1", "delete")}},
        {"resources": {("prod", "WO-1"): "tenant-b/WO-1"}},
        {"tools": {"close_wo": ("workorder.close@2", "write")}},
    ], ids=["alias", "redirect", "remap"])
    def test_a_changed_resolution_refuses_and_nothing_runs(self, change):
        resolver = _resolver()
        lease = _lease(resolver.resolve("close_wo", ARGS, "prod"))
        result, calls = _dispatch(lease, resolver.with_changes(**change))
        assert (result.executed, result.refusal_reason) == (False, "resolved_effect_mismatch")
        assert calls == []

    def test_a_refusal_does_not_burn_the_nonce(self):
        resolver = _resolver()
        lease = _lease(resolver.resolve("close_wo", ARGS, "prod"))
        kwargs = dict(tenant_id="acme", target_environment="prod", actor_identity="agent-1")
        redirected = GovernedToolDispatcher(BUNDLE)
        redirected.register("close_wo", lambda args: "ok")
        redirected.bind_effect_resolver(
            resolver.with_changes(resources={("prod", "WO-1"): "tenant-b/WO-1"}))
        assert not redirected.dispatch(lease, "close_wo", ARGS, **kwargs).executed
        restored = GovernedToolDispatcher(BUNDLE, ledger=redirected._ledger)
        restored.register("close_wo", lambda args: "ok")
        restored.bind_effect_resolver(resolver)
        assert restored.dispatch(lease, "close_wo", ARGS, **kwargs).executed

    def test_with_changes_leaves_the_original_resolver_alone(self):
        resolver = _resolver()
        resolver.with_changes(resources={("prod", "WO-1"): "elsewhere"})
        assert resolver.resolve("close_wo", ARGS, "prod").resource == "tenant-a/WO-1"

    def test_a_reference_dropped_from_the_registry_refuses(self):
        resolver = _resolver()
        lease = _lease(resolver.resolve("close_wo", ARGS, "prod"))
        broken = ClosedWorldResolver(tools={}, resources={}, resource_argument={})
        result, calls = _dispatch(lease, broken)
        assert result.refusal_reason == "unresolved_reference" and calls == []

    def test_a_failing_resolver_refuses_rather_than_skipping(self):
        class Broken:
            def resolve(self, *a):
                raise RuntimeError("registry down")

        resolver = _resolver()
        result, _ = _dispatch(_lease(resolver.resolve("close_wo", ARGS, "prod")), Broken())
        assert result.refusal_reason == "resolved_effect_unresolvable"

    def test_an_unbound_lease_runs_outside_strict(self):
        result, _ = _dispatch(_lease(None), _resolver())
        assert result.executed

    def test_an_unbound_lease_refuses_under_a_strict_profile(self, monkeypatch):
        import remora.enforcement.custody as custody

        calls: list = []
        dispatcher = GovernedToolDispatcher(BUNDLE)
        dispatcher.register("close_wo", lambda args: calls.append(args) or "ok")
        dispatcher.bind_effect_resolver(_resolver())
        lease = _lease(None)
        # Strict from here on; the runtime binding is ADR-D's subject, not this one.
        monkeypatch.setattr(custody, "custody_is_enforced", lambda: True)
        monkeypatch.setattr(GovernedToolDispatcher, "_runtime_refusal",
                            staticmethod(lambda lease: None))
        # Durable single-use is H-01's subject (tests/test_hostile_review_2026_10_08.py), not this one.
        monkeypatch.setattr(GovernedToolDispatcher, "_durability_refusal", lambda self: None)
        result = dispatcher.dispatch(lease, "close_wo", ARGS, tenant_id="acme",
                                     target_environment="prod", actor_identity="agent-1")
        assert result.refusal_reason == "resolved_effect_unbound" and calls == []

    def test_no_resolver_leaves_behaviour_unchanged(self):
        result, _ = _dispatch(_lease(_resolver().resolve("close_wo", ARGS, "prod")))
        assert result.executed


class TestTheLeaseSignsTheDigest:
    def test_an_unbound_lease_signs_no_digest(self):
        assert "resolved_effect_hash" not in _lease(None)._signed_fields()

    def test_rewriting_the_digest_breaks_the_signature(self):
        data = {**_lease(_resolver().resolve("close_wo", ARGS, "prod")).to_dict(),
                "resolved_effect_hash": "0" * 64}
        verdict = ExecutionLease.from_dict(data).verify(
            tool_name="close_wo", arguments=ARGS, tenant_id="acme",
            target_environment="prod", actor_identity="agent-1")
        assert verdict.reason == "signature_invalid"


class TestClosedWorld:
    def test_an_unknown_tool_is_not_guessed(self):
        with pytest.raises(UnresolvedReference):
            _resolver().resolve("close_workorder", ARGS, "prod")

    def test_an_unknown_resource_is_not_guessed(self):
        with pytest.raises(UnresolvedReference):
            _resolver().resolve("close_wo", {"id": "WO-404"}, "prod")

    def test_a_missing_resource_argument_is_not_guessed(self):
        with pytest.raises(UnresolvedReference):
            _resolver().resolve("close_wo", {}, "prod")

    def test_the_same_reference_in_another_environment_is_unknown(self):
        with pytest.raises(UnresolvedReference):
            _resolver().resolve("close_wo", ARGS, "staging")


def test_the_committed_fixtures_reproduce():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_resolved_effect_fixtures.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    artifact = json.loads((ROOT / "artifacts" / "resolved_effect" / "fixtures_v1.json").read_text(encoding="utf-8"))
    assert artifact["summary"]["all_as_required"] is True
