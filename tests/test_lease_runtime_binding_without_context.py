# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The authority binds its declared runtime into a lease without an execution context.

Found by the stage I end-to-end retest (2026-10-07): the init-review scaffold
run as three processes under review/v2. A strict executor refuses a lease
that names no runtime (``runtime_identity_undeclared``, ADR-D), and on the API
path only an execution context put a runtime into the lease. An execution
context provider must attest the model initiator through an inference gateway
or trusted orchestrator, which a deployment may not have. Without one, a
strict deployment could execute nothing.

Decision (2026-10-07): when no execution context is configured, the
authority signs its own declared runtime identity (``REMORA_RUNTIME_*``)
into the lease, and the executor compares it with its own as before. An
undeclared runtime hashes to the empty string, so a deployment that declares
none issues the same leases as before.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from remora.enforcement import runtime_identity as rid
from remora.enforcement.lease import GovernedToolDispatcher
from remora.execution.dispatch import _issue_local_lease

ARGS = {"id": "WO-1"}
SEMANTIC = {"tool_contract_bundle_hash": "", "intent_authority_hash": ""}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "runtime-binding-key")
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_SIGNATURE_FORMAT",
                 rid.ENV_RUNTIME_KIND, rid.ENV_DEPLOYMENT_ID, rid.ENV_IMAGE_DIGEST,
                 rid.ENV_EXECUTOR_INSTANCE_CLASS, rid.ENV_TOOL_RUNTIME_IDENTITY,
                 rid.ENV_DEPLOYMENT_GENERATION):
        monkeypatch.delenv(name, raising=False)
    rid.reset_runtime_identity()
    yield monkeypatch
    rid.reset_runtime_identity()


def _declare(monkeypatch, deployment: str) -> None:
    monkeypatch.setenv(rid.ENV_RUNTIME_KIND, "local-review")
    monkeypatch.setenv(rid.ENV_DEPLOYMENT_ID, deployment)
    rid.reset_runtime_identity()


def _lease():
    call = SimpleNamespace(tool_name="wo_close", arguments=ARGS, target_environment="prod")
    return _issue_local_lease(
        tenant="acme", principal="agent-1", tool_call=call, semantic=SEMANTIC,
        now=datetime.now(UTC), policy_bundle_hash="b1", toolspec=None,
        proposal_id="p-1", grant_jti="j-1")


def _dispatch(lease):
    dispatcher = GovernedToolDispatcher("b1")
    dispatcher.register("wo_close", lambda args: "ok")
    return dispatcher.dispatch(lease, "wo_close", ARGS, tenant_id="acme",
                               target_environment="prod", actor_identity="agent-1")


def test_a_declared_runtime_is_signed_into_the_lease(keys) -> None:
    _declare(keys, "deploy-a")
    assert _lease().runtime_identity_hash == rid.current_runtime_identity_hash() != ""


def test_an_undeclared_runtime_issues_the_lease_as_before(keys) -> None:
    assert _lease().runtime_identity_hash == ""


def test_a_strict_executor_with_the_same_runtime_executes(keys) -> None:
    _declare(keys, "deploy-a")
    lease = _lease()
    keys.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    keys.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    # Durable single-use is H-01's subject (tests/test_hostile_review_2026_10_08.py), not this one.
    keys.setattr(GovernedToolDispatcher, "_durability_refusal", lambda self: None)
    result = _dispatch(lease)
    assert result.executed, result.refusal_reason


def test_a_lease_for_another_runtime_refuses(keys) -> None:
    _declare(keys, "deploy-a")
    lease = _lease()
    _declare(keys, "deploy-b")
    assert _dispatch(lease).refusal_reason == "runtime_identity_mismatch"
