# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bypass suite: the dynamic half of Agent Authority property E.

The static gate (scripts/check_credential_topology.py) reasons about the
import graph. It cannot see the three ways an execution boundary is
actually crossed in practice: extracting the callable, sharing the process,
or reaching the effect through something already authenticated.

This suite attempts named bypasses and records what happens. Two of the
cases below assert that a bypass SUCCEEDS. That is deliberate. A suite
that only demonstrated refusals would be evidence about the refusals, not
about the boundary, and property E is the one place in the model where an
untested assumption has historically been read as a pass.

Each case carries an identifier used in the conformance assessment:

    B1  dispatch with no lease
    B2  dispatch of an unregistered tool (the raw tool path)
    B3  extraction of the registered callable from the dispatcher  (SUCCEEDS)
    B4  ambient environment read from inside the agent zone        (SUCCEEDS)
    B5  credential or dispatcher reachable through the public SDK surface
    B6  dispatch of a call the lease does not cover
    B7  deployment-supplied downstream credentials (scope statement, L5)

B3 and B4 are why REMORA's execution boundary is a PROCESS boundary
(ADR-A) and not a call boundary. In a single process, Python offers no
custody: attribute privacy is a convention. Recording that plainly is more
useful than a suite of green refusals that quietly assume it away.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

BUNDLE = "b" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _later() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


@pytest.fixture
def effect() -> dict:
    """Stand-in for a protected side effect, so a bypass is observable."""
    return {"fired": 0}


@pytest.fixture
def dispatcher(effect: dict) -> GovernedToolDispatcher:
    disp = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)

    def send_mail(arguments: object) -> str:
        effect["fired"] += 1
        return "sent"

    disp.register("send_mail", send_mail)
    return disp


# --------------------------------------------------------------------------
# B1 / B2 — the boundary holding where it is supposed to hold
# --------------------------------------------------------------------------


def test_b1_dispatch_without_lease_is_refused(
    dispatcher: GovernedToolDispatcher, effect: dict
) -> None:
    result = dispatcher.dispatch(None, "send_mail", {"to": "a@example.com"})
    assert result.executed is False
    assert result.refusal_reason == "missing_lease"
    assert effect["fired"] == 0


def test_b2_unregistered_tool_is_refused(
    dispatcher: GovernedToolDispatcher, effect: dict
) -> None:
    """The raw-tool-path case: an unwrapped name must not fall through."""
    lease = ExecutionLease.issue(
        decision="accept",
        tenant_id="t1",
        actor_identity="agent-1",
        tool_name="send_mail_raw",
        arguments={"to": "a@example.com"},
        target_environment="prod",
        policy_bundle_hash=BUNDLE,
        issued_at=_now(),
        expires_at=_later(),
    )
    result = dispatcher.dispatch(
        lease, "send_mail_raw", {"to": "a@example.com"}, tenant_id="t1"
    )
    assert result.executed is False
    assert result.refusal_reason == "unknown_tool"
    assert effect["fired"] == 0


# --------------------------------------------------------------------------
# B3 / B4 — the boundary NOT holding, recorded rather than assumed
# --------------------------------------------------------------------------


def test_b3_registered_callable_can_be_extracted_in_process(
    dispatcher: GovernedToolDispatcher, effect: dict
) -> None:
    """In-process custody is a convention, and this records that it is.

    Anything holding a reference to the dispatcher can reach the callable
    it guards and invoke it with no lease at all. This is not a defect in
    the dispatcher; it is the reason the enforcement boundary must be a
    process boundary. If this test ever starts failing, the custody model
    has genuinely changed and the conformance assessment for E must be
    rewritten rather than merely re-run.

    The answer to this bypass is not a fix here, because there is none to
    make in a single interpreter. It is that the configuration in which it
    matters is refused: under a strict runtime profile the authority domain
    cannot register a tool callable at all
    (``test_custody_guard.py::test_k7_authority_cannot_register_tool_callables``).
    This test runs under the research profile, where that weaker
    configuration is supported and honestly labelled.
    """
    smuggled = dispatcher._tools["send_mail"]
    smuggled({"to": "attacker@example.com"})
    assert effect["fired"] == 1, (
        "expected the in-process extraction bypass to succeed; if it no "
        "longer does, E's scope has changed"
    )


def test_b4_agent_zone_process_can_read_the_ambient_environment() -> None:
    """Limit L2: import reachability is not process co-residency.

    The static gate proves no agent-zone module IMPORTS a credential
    reader. It cannot prove the credential is absent from the process. Here
    a value placed in the environment is read back with no import at all,
    which is why co-residency is stated as a deployment obligation instead
    of being claimed as a property of the code.
    """
    key = "REMORA_CONFORMANCE_B4_PROBE"
    os.environ[key] = "ambient-secret"
    try:
        assert os.environ.get(key) == "ambient-secret"
    finally:
        os.environ.pop(key, None)


# --------------------------------------------------------------------------
# B5 / B6 — surface and minting
# --------------------------------------------------------------------------


def test_b5_public_sdk_surface_exposes_no_dispatcher_or_credential() -> None:
    """The declared agent surface must not hand out the things E protects."""
    import remora.sdk as sdk

    exported = set(sdk.__all__)
    forbidden = {"GovernedToolDispatcher", "ExecutionLease", "NonceLedger"}
    assert exported & forbidden == set()

    suspicious = [
        name
        for name in exported
        if any(word in name.lower() for word in ("secret", "credential", "signing"))
    ]
    assert suspicious == [], suspicious


def test_b6_lease_verification_binds_to_the_exact_call(
    dispatcher: GovernedToolDispatcher, effect: dict
) -> None:
    """A lease for one call must not dispatch another.

    Included in the E suite rather than the C suite for one reason: a
    boundary that can be walked past with a lease for a different call is
    not a boundary, whatever the binding proves on paper.
    """
    lease = ExecutionLease.issue(
        decision="accept",
        tenant_id="t1",
        actor_identity="agent-1",
        tool_name="send_mail",
        arguments={"to": "approved@example.com"},
        target_environment="prod",
        policy_bundle_hash=BUNDLE,
        issued_at=_now(),
        expires_at=_later(),
    )
    result = dispatcher.dispatch(
        lease,
        "send_mail",
        {"to": "attacker@example.com"},
        tenant_id="t1",
        target_environment="prod",
        actor_identity="agent-1",
    )
    assert result.executed is False
    assert effect["fired"] == 0


def test_b7_deployment_supplied_credentials_are_out_of_repository_scope() -> None:
    """Limit L5, asserted so it cannot be quietly dropped.

    The dispatcher holds tool callables registered by deployment
    configuration, and those callables close over the real downstream
    credential. Nothing in this repository holds an SMTP or vendor API
    credential for a governed tool, so nothing here can demonstrate that a
    deployment's credential is unreachable. The suite states the gap rather
    than leaving E's largest hole to prose.
    """
    disp = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    assert disp._tools == {}, (
        "a shipped default tool registration would change E's scope and must "
        "be assessed, not inherited"
    )
