# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The unsigned-fallthrough family: an issuer without signing authority.

NEGATIVE_RESULTS §43 recorded that `ExecutionLease.issue()` returned an
UNSIGNED lease when the process held only verification material, instead of
refusing, and recorded that the same shape in `PolicyDecisionToken` and the A2A
envelope was untested rather than assumed absent. This file tests it.

The shape, wherever it appears:

    key = resolve_signing_key()
    if key:
        return signed_object
    return unsigned_object        # <-- authority-shaped, worthless, silent

The principle these tests establish:

    An authority issuer without signing authority must REFUSE TO ISSUE.
    It must not return an authority-shaped unsigned object on an
    authoritative path.

Two things this principle is careful NOT to say. It does not say every keyless
call must fail: research and library use legitimately run without keys, and
breaking that would push people towards configuring a key they do not protect.
And it does not say an unsigned object is exploitable: every verifier here
refuses one. The defect is silent degradation — a caller that asked for
authority and received an object has no reason to inspect whether it is real.

So the rule is applied where it can be applied soundly, at two triggers:

  1. the process holds VERIFICATION material but not SIGNING material
     (it is a verifier; verifiers must not mint), and
  2. the deployment declares itself authoritative (production fail-closed
     prerequisites), where an unsigned authority object should never exist.

Tests are written against current behaviour first. Where current behaviour is
already correct that is asserted, so a future change cannot silently loosen it.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.enforcement.lease import ExecutionLease, LeaseRefused  # noqa: E402
from remora.enforcement.token import PolicyDecisionToken  # noqa: E402
from remora.governance.a2a_envelope import (  # noqa: E402
    A2AGovernanceEnvelope,
    AgentIdentity,
)
from remora.toolcall import toolspec  # noqa: E402

ISSUED = datetime.now(UTC).isoformat()


def _a2a() -> A2AGovernanceEnvelope:
    """A minimal, fully accountable envelope: only the signature is missing."""
    return A2AGovernanceEnvelope.issue(
        identity=AgentIdentity(
            agent_id="agent-1", agent_version="1.0",
            issuer_org="acme", responsible_org="acme"),
        delegation_chain=(),
        requested_scope=("workorder:read",),
        policy_version="p1",
        audience="counterparty")

#: Every environment variable that can make one of these issuers produce a
#: signed object. Cleared wholesale so a test cannot pass because an unrelated
#: key happened to be set in the developer's shell.
_ALL_KEYS = (
    "REMORA_LEASE_SIGNING_KEY",
    "REMORA_PDP_SIGNING_KEY",
    "REMORA_A2A_SIGNING_KEY",
    "REMORA_ENVELOPE_SIGNING_KEY",
    "REMORA_AUDIT_SIGNING_KEY",
    signing.ENV_ED25519_PRIVATE,
    signing.ENV_ED25519_PUBLIC,
    signing.ENV_ACCEPT_HMAC,
)


@pytest.fixture()
def keyless(monkeypatch):
    for name in _ALL_KEYS:
        monkeypatch.delenv(name, raising=False)


# ── 1. ExecutionLease — fixed in §43, pinned here against regression ─────────

def test_execution_lease_refuses_to_issue_when_verifier_only(keyless, monkeypatch):
    """The §43 fix. A verifier must not be able to produce an authority object."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ed25519

    public = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public.hex())

    with pytest.raises(LeaseRefused):
        ExecutionLease.issue(
            decision="accept", tenant_id="acme", actor_identity="agent-1",
            tool_name="wo_close", arguments={}, target_environment="staging",
            policy_bundle_hash="b1", issued_at=ISSUED)


def test_execution_lease_still_issues_unsigned_when_wholly_keyless(keyless):
    """Library and research use is deliberately preserved.

    Asserted rather than assumed: if this ever starts raising, keyless
    research use has been broken and that is a decision someone must take
    on purpose, not a side effect of hardening.
    """
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="wo_close", arguments={}, target_environment="staging",
        policy_bundle_hash="b1", issued_at=ISSUED)
    assert lease.is_signed is False


def test_an_unsigned_lease_is_refused_at_verification(keyless):
    """The reason the unsigned object is a hygiene defect, not a hole."""
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="wo_close", arguments={}, target_environment="staging",
        policy_bundle_hash="b1", issued_at=ISSUED)
    result = lease.verify(
        tool_name="wo_close", arguments={}, tenant_id="acme",
        target_environment="staging", now=ISSUED, actor_identity="agent-1")
    assert result.verified is False
    assert result.reason == "lease_not_signed"


# ── 2. PolicyDecisionToken — the same shape, previously untested ─────────────

def test_policy_decision_token_issues_unsigned_when_keyless(keyless):
    """Current behaviour, recorded.

    token.py:236 returns an unsigned token when no key resolves. Unlike the
    lease there is no asymmetric mode yet, so there is no verifier-only state
    to detect: a process either has the shared key or has nothing. The
    equivalent of the §43 trigger therefore does not exist here, and inventing
    one would mean refusing legitimate keyless research use for no gain.

    What DOES protect this in production is the fail-closed prerequisite on
    REMORA_PDP_SIGNING_KEY, asserted below.
    """
    token = PolicyDecisionToken.issue(
        action="accept", observation_hash="h" * 64,
        request_id="req-1", issued_at=ISSUED, audience="pep")
    assert token.is_signed is False
    assert token.signature == ""


def test_an_unsigned_token_is_refused_by_a_strict_gate(keyless):
    """The compensating control, pinned."""
    from remora.enforcement.gate import EnforcementGate

    token = PolicyDecisionToken.issue(
        action="accept", observation_hash="h" * 64,
        request_id="req-1", issued_at=ISSUED, audience="pep")
    result = EnforcementGate(strict=True, audience="pep").check(token)
    assert result.allowed is False


# ── 3. A2A envelope — the same shape ────────────────────────────────────────

def test_a2a_envelope_issues_unsigned_when_keyless(keyless):
    """Current behaviour, recorded (a2a_envelope.py:228-230).

    Same reasoning as the token: symmetric only, so no verifier-only state
    exists to trigger a refusal. Its compensating control is that verify()
    fails closed on an unsigned envelope.
    """
    envelope = _a2a()
    assert envelope.is_signed is False


def test_an_unsigned_a2a_envelope_does_not_verify(keyless):
    envelope = _a2a()
    result = envelope.verify(expected_audience="counterparty")
    assert not result.valid, (
        "an unsigned envelope must not verify -- the compensating control "
        "that makes the unsigned-issuance shape a hygiene defect rather than "
        "a hole")


# ── 4. ToolSpec — structurally immune, asserted so it stays that way ─────────

def test_toolspec_signing_cannot_be_called_without_a_key(keyless):
    """sign_bundle takes the key as a required parameter.

    There is no environment fallthrough to degrade through, which is the
    correct shape and the one the others should converge on. Pinned so that
    adding an environment-variable convenience later is a visible change.
    """
    with pytest.raises(TypeError):
        toolspec.sign_bundle(  # type: ignore[call-arg]
            {"tool_id": "t", "version": 1},
            signing_identity="deployment", signed_at=ISSUED)


# ── 5. The production prerequisite list ─────────────────────────────────────

def test_production_requires_every_authority_signing_key(keyless, monkeypatch):
    """The gap this audit found.

    servers/api.py refuses to start in production without
    REMORA_ENVELOPE_SIGNING_KEY and REMORA_PDP_SIGNING_KEY, on the stated
    grounds that without them the records are unsigned and nothing
    distinguishes an authentic one from a fabricated one.

    That reasoning applies verbatim to the ExecutionLease, which is the object
    that actually authorises a side effect -- and it was not on the list. A
    production deployment could therefore run with no lease signing material
    at all, and every lease would be issued unsigned.

    Not exploitable: verify() refuses an unsigned lease, so execution fails
    closed rather than proceeding. But the guard was inconsistent with its own
    argument, and a fail-closed prerequisite that omits the most consequential
    of the three keys is not doing the job it claims.
    """
    import inspect

    from servers import api as api_module

    source = inspect.getsource(api_module)
    assert "REMORA_ENVELOPE_SIGNING_KEY" in source
    assert "REMORA_PDP_SIGNING_KEY" in source
    assert "REMORA_LEASE_SIGNING_KEY" in source, (
        "production fail-closed omits the lease signing key; leases would be "
        "issued unsigned on the authoritative path"
    )


# ── the guard that keeps this evidence running ──────────────────────────────

def test_the_security_extra_guard_fails_hard_in_ci_and_skips_locally(
        monkeypatch):
    """CI must not be able to silently skip the Ed25519 custody evidence.

    That already happened once: CI installed .[dev,causal,api] without
    [security], every Ed25519 test skipped, and the only visible symptom was a
    coverage floor. The guard exists so a missing dependency is reported as a
    missing dependency.

    Both halves are asserted, because a guard that always raises would break
    every local checkout without the extra, and a guard that always skips is
    the bug it was written to prevent.
    """
    import importlib as _il

    from _security_extra import require_security_extra

    def missing(name):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(_il, "import_module", missing)

    monkeypatch.setenv("REMORA_REQUIRE_SECURITY_EXTRA", "1")
    with pytest.raises(ImportError):
        require_security_extra()

    # The other half routes to pytest.importorskip. It cannot be provoked into
    # skipping here -- cryptography IS installed in this environment and
    # importorskip does its own import, which the monkeypatch above does not
    # reach -- so what is asserted is the ROUTING: not-required goes to
    # importorskip and never to the hard import.
    called: list = []
    monkeypatch.setattr(pytest, "importorskip",
                        lambda *a, **k: called.append(a[0]))
    monkeypatch.delenv("REMORA_REQUIRE_SECURITY_EXTRA")
    require_security_extra()
    assert called == ["cryptography"], (
        "without the CI flag the guard must skip rather than fail the run")
