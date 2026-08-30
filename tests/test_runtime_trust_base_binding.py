# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The executing runtime is part of the authorization (ADR-D, property H).

``docs/research/adjacent-systems-crosswalk-v2.md`` §3 walks a case in which
every property REMORA implements reports success while the action executes
against an implementation nobody authorized:

    At authorization: ToolSpec T1, policy P1, runtime R1, no drift before
    authorization. At execution: arguments unchanged, target unchanged, policy
    still P1, ToolSpec declaration still T1 — but the runtime implementation is
    R2.

Exact-call integrity passes: the call IS the authorized call. Authorization
drift passes: the declaration did not change. Boundary traversal passes: no
alternate path was used. The crosswalk's conclusion was that the case is not
reducible to the existing properties, and its condition for admitting property
H was that the discriminating test must fail without an implementation. This
file is that test.

``test_h_is_not_reducible_to_exact_call_integrity`` is the load-bearing one: it
asserts in code that the mismatched-runtime call satisfies the argument binding
and is refused anyway. Without the binding it would execute.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement import runtime_identity as rid  # noqa: E402
from remora.enforcement.lease import (  # noqa: E402
    ExecutionLease,
    GovernedToolDispatcher,
    NonceLedger,
)
from remora.policy.observation import canonical_tool_call_hash  # noqa: E402
from remora.profiles import PROFILE_ENV  # noqa: E402

BUNDLE = "bundle-hash-abc"
TENANT = "acme"
TOOL = "wo_close"
TARGET = "staging"
ARGS = {"id": "WO-1"}

R1 = rid.RuntimeTrustBaseIdentity(
    runtime_kind="mcp-worker",
    deployment_id="dep-eu-1",
    image_digest="sha256:1111",
    executor_instance_class="standard",
    tool_runtime_identity="wo-tools@1",
    generation="7",
)
#: R2 differs in exactly one field. The rolled-back-image and stale-generation
#: cases are the realistic ones, and one field is enough to prove the binding.
R2 = R1.with_generation("8")


def _become(identity: rid.RuntimeTrustBaseIdentity, monkeypatch) -> None:
    """Make this process BE the given runtime, as the executor would at boot."""
    monkeypatch.setenv(rid.ENV_RUNTIME_KIND, identity.runtime_kind)
    monkeypatch.setenv(rid.ENV_DEPLOYMENT_ID, identity.deployment_id)
    monkeypatch.setenv(rid.ENV_IMAGE_DIGEST, identity.image_digest)
    monkeypatch.setenv(rid.ENV_EXECUTOR_INSTANCE_CLASS, identity.executor_instance_class)
    monkeypatch.setenv(rid.ENV_TOOL_RUNTIME_IDENTITY, identity.tool_runtime_identity)
    monkeypatch.setenv(rid.ENV_DEPLOYMENT_GENERATION, identity.generation)
    rid.reset_runtime_identity()


@pytest.fixture(autouse=True)
def _clean_identity(monkeypatch):
    """Reload-restore: no test may inherit another's cached identity."""
    monkeypatch.setenv(PROFILE_ENV, "research")
    # The dispatcher refuses an unsigned lease before any of this file's
    # checks run, so every test needs issuing material.
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "k" * 32)
    for env in (
        rid.ENV_RUNTIME_KIND, rid.ENV_DEPLOYMENT_ID, rid.ENV_IMAGE_DIGEST,
        rid.ENV_EXECUTOR_INSTANCE_CLASS, rid.ENV_TOOL_RUNTIME_IDENTITY,
        rid.ENV_DEPLOYMENT_GENERATION,
    ):
        monkeypatch.delenv(env, raising=False)
    rid.reset_runtime_identity()
    yield
    rid.reset_runtime_identity()


def _lease(*, runtime_identity_hash: str = "") -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept",
        tenant_id=TENANT,
        actor_identity="agent-1",
        tool_name=TOOL,
        arguments=ARGS,
        target_environment=TARGET,
        policy_bundle_hash=BUNDLE,
        issued_at=datetime.now(UTC).isoformat(),
        runtime_identity_hash=runtime_identity_hash,
    )


def _dispatcher(ledger: NonceLedger | None = None) -> tuple[GovernedToolDispatcher, list]:
    calls: list = []
    dispatcher = GovernedToolDispatcher(BUNDLE, ledger=ledger)
    dispatcher.register(TOOL, lambda args: calls.append(args) or "closed")
    return dispatcher, calls


def _dispatch(dispatcher: GovernedToolDispatcher, lease: ExecutionLease):
    return dispatcher.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        actor_identity="agent-1",
    )


def test_identity_hash_is_empty_when_nothing_is_declared():
    """An undeclared runtime is distinguishable from six declared blanks.

    Dispatch and the strict guard both test for the empty hash, so a wholly
    undeclared runtime must not produce a hash the way a deliberately blank
    declaration would.
    """
    assert rid.RuntimeTrustBaseIdentity().identity_hash() == ""
    assert rid.RuntimeTrustBaseIdentity(generation="0").identity_hash() != ""


def test_identity_is_read_once_and_cached(monkeypatch):
    """The compared value cannot be changed after startup.

    This is the security property, not an optimisation: if the environment
    could be re-read per dispatch, anything able to set an environment variable
    in the executing process could satisfy any lease.
    """
    _become(R1, monkeypatch)
    first = rid.current_runtime_identity_hash()
    monkeypatch.setenv(rid.ENV_DEPLOYMENT_GENERATION, "8")
    assert rid.current_runtime_identity_hash() == first
    rid.reset_runtime_identity()
    assert rid.current_runtime_identity_hash() != first


def test_dispatch_refuses_a_lease_minted_for_another_runtime(monkeypatch):
    """Authorize under R1, execute under R2: refuse. Property H's existence proof."""
    _become(R1, monkeypatch)
    lease = _lease(runtime_identity_hash=R1.identity_hash())

    _become(R2, monkeypatch)
    dispatcher, calls = _dispatcher()
    result = _dispatch(dispatcher, lease)

    assert result.executed is False
    assert result.refusal_reason == "runtime_identity_mismatch"
    assert calls == []


def test_dispatch_allows_the_runtime_that_was_authorized(monkeypatch):
    """No false positive: the authorized runtime still executes."""
    _become(R1, monkeypatch)
    dispatcher, calls = _dispatcher()
    result = _dispatch(dispatcher, _lease(runtime_identity_hash=R1.identity_hash()))

    assert result.executed is True
    assert calls == [ARGS]


def test_h_is_not_reducible_to_exact_call_integrity(monkeypatch):
    """The refused call satisfies the argument binding exactly.

    The crosswalk's claim is that C, F1 and E all pass in this scenario. This
    asserts the sharpest of them in code: the lease's argument hash is the hash
    of the presented call, so nothing about the call itself is wrong. Only the
    runtime is, and only the ADR-D binding notices.
    """
    _become(R1, monkeypatch)
    lease = _lease(runtime_identity_hash=R1.identity_hash())
    assert lease.tool_args_hash == canonical_tool_call_hash(
        name=TOOL, arguments=ARGS, tenant=TENANT, target=TARGET,
    )

    _become(R2, monkeypatch)
    verdict = lease.verify(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, expected_policy_bundle_hash=BUNDLE,
        actor_identity="agent-1",
    )
    assert verdict.verified is True, "the lease itself is valid; only the runtime differs"

    dispatcher, _ = _dispatcher()
    assert _dispatch(dispatcher, lease).refusal_reason == "runtime_identity_mismatch"


def test_refusal_does_not_consume_the_nonce(monkeypatch):
    """A rejected runtime must not burn the authorization.

    Burning it would turn a plain authorization failure into a permanently dead
    grant, and — once a correct runtime retried — into an unknown-state
    incident rather than a clean refusal.
    """
    _become(R1, monkeypatch)
    lease = _lease(runtime_identity_hash=R1.identity_hash())
    ledger = NonceLedger()

    _become(R2, monkeypatch)
    wrong, _ = _dispatcher(ledger)
    assert _dispatch(wrong, lease).executed is False

    _become(R1, monkeypatch)
    right, calls = _dispatcher(ledger)
    result = _dispatch(right, lease)
    assert result.executed is True, "the nonce survived the refusal"
    assert calls == [ARGS]


def test_unbound_lease_is_allowed_outside_strict(monkeypatch):
    """Existing leases carry no binding and must keep working."""
    _become(R1, monkeypatch)
    dispatcher, calls = _dispatcher()
    assert _dispatch(dispatcher, _lease()).executed is True
    assert calls == [ARGS]


def test_unbound_lease_is_refused_under_a_strict_profile(monkeypatch):
    """Under strict, the binding cannot be dropped by never setting it.

    Note this holds even though the executing process IS declared: the test is
    on the lease, not on the process. Otherwise a strict deployment could
    satisfy the property while issuing unbound authorizations.
    """
    _become(R1, monkeypatch)
    # Issued under research: minting authority is refused to the executor role
    # under a strict profile, which is the custody split working as intended.
    lease = _lease()

    monkeypatch.setenv(PROFILE_ENV, "controlled_pilot")
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    dispatcher, calls = _dispatcher()

    result = _dispatch(dispatcher, lease)

    assert result.executed is False
    assert result.refusal_reason == "runtime_identity_undeclared"
    assert calls == []


def test_binding_is_covered_by_the_signature(monkeypatch):
    """Mutate the field on a signed lease and verification must fail.

    Without this the field is bookkeeping: anything able to present a lease
    could rewrite the runtime it was granted for.
    """
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "k" * 32)
    _become(R1, monkeypatch)
    lease = _lease(runtime_identity_hash=R1.identity_hash())
    assert lease.is_signed is True

    from dataclasses import replace

    tampered = replace(lease, runtime_identity_hash=R2.identity_hash())
    verdict = tampered.verify(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, expected_policy_bundle_hash=BUNDLE,
        actor_identity="agent-1",
    )
    assert verdict.verified is False
