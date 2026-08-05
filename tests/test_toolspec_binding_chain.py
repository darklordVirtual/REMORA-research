# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The ToolSpec identity must survive the whole chain, or nothing is bound.

Handoff gate §1.3 and §1.5: the same ToolSpec hash has to appear at
assessment, in the authorization token, in the execution lease, and at
dispatch. If any stage can carry a different spec, then the action that
executes is not the action that was reviewed — and every check upstream
becomes decoration.

The lease already binds tenant, actor, tool, exact arguments, target and
the policy bundle. These tests add the two identifiers that were missing:
``tool_id``'s spec hash and its version. A signed spec that nothing binds
is a document, not a control.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from remora.enforcement.lease import ExecutionLease, LeaseRefused

SPEC_HASH = "d" * 64
OTHER_SPEC_HASH = "e" * 64


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """An unsigned lease refuses everything, so without a key these tests
    would pass for the wrong reason — every refusal would be
    'no_signing_key' rather than the binding under test."""
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "binding-chain-test-key")


def _issue(**overrides) -> ExecutionLease:
    kwargs = {
        "decision": "accept",
        "tenant_id": "acme",
        "actor_identity": "agent-1",
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "a-1"},
        "target_environment": "prod",
        "policy_bundle_hash": "sha256:policy",
        "issued_at": datetime.now(UTC).isoformat(),
        "toolspec_hash": SPEC_HASH,
        "toolspec_version": 3,
    }
    kwargs.update(overrides)
    return ExecutionLease.issue(**kwargs)


def _verify(lease: ExecutionLease, **overrides) -> bool:
    kwargs = {
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "a-1"},
        "tenant_id": "acme",
        "target_environment": "prod",
        "actor_identity": "agent-1",
        "expected_policy_bundle_hash": "sha256:policy",
        "toolspec_hash": SPEC_HASH,
        "toolspec_version": 3,
    }
    kwargs.update(overrides)
    return lease.verify(**kwargs).verified


def test_lease_carries_the_toolspec_identity() -> None:
    lease = _issue()
    assert lease.toolspec_hash == SPEC_HASH
    assert lease.toolspec_version == 3
    assert lease.to_dict()["toolspec_hash"] == SPEC_HASH


def test_matching_spec_verifies() -> None:
    assert _verify(_issue()) is True


def test_a_different_spec_hash_refuses() -> None:
    """The redeploy case: same tool, same arguments, different spec."""
    lease = _issue()
    assert _verify(lease, toolspec_hash=OTHER_SPEC_HASH) is False


def test_a_different_spec_version_refuses() -> None:
    """Same content hash is impossible across versions, but the version is
    bound separately so a mismatch is reported as one rather than being
    inferred from the hash."""
    lease = _issue()
    assert _verify(lease, toolspec_version=4) is False


def test_the_spec_identity_is_covered_by_the_signature() -> None:
    """Binding a field the signature does not cover would let an attacker
    edit it freely — the whole point is that it cannot be swapped."""
    lease = _issue()
    tampered = ExecutionLease(**{
        **lease.to_dict(),
        "toolspec_hash": OTHER_SPEC_HASH,
    })
    assert _verify(tampered, toolspec_hash=OTHER_SPEC_HASH) is False


def test_unsigned_legacy_lease_without_spec_identity_still_refuses(
    monkeypatch,
) -> None:
    """A lease issued before spec binding existed must not verify against a
    spec-bearing check: absent identity is not a wildcard."""
    lease = _issue(toolspec_hash="", toolspec_version=0)
    assert _verify(lease) is False


def test_refusal_names_the_toolspec_mismatch() -> None:
    lease = _issue()
    result = lease.verify(
        tool_name="store_artifact", arguments={"artifact_id": "a-1"},
        tenant_id="acme", target_environment="prod",
        actor_identity="agent-1", expected_policy_bundle_hash="sha256:policy",
        toolspec_hash=OTHER_SPEC_HASH, toolspec_version=3,
    )
    assert not result.verified
    assert "toolspec" in result.reason.lower(), result.reason


def test_non_accept_decision_still_refuses_a_lease() -> None:
    """The pre-existing invariant must survive the new fields."""
    with pytest.raises(LeaseRefused):
        _issue(decision="verify")
