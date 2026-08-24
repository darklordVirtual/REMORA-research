# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A receipt must be about the dispatch it claims to observe (RMR-002).

The recorder checked that a proposal existed and then stored whatever status
arrived. A proposal that was assessed and never executed could be recorded
``EFFECT_VERIFIED``, and the lifecycle projection reported it as such.

That is a false VERIFIED, and it is the worst failure this model has. Every
other status is an admission -- MISMATCH, UNOBSERVABLE, VERIFIER_FAILED and
UNSUPPORTED all say something did not happen or is not known, and nobody
fabricates those. VERIFIED is the only verdict worth lying about, and until now
the only one with no check.

The rule under test:

    EFFECT_VERIFIED =
        valid_dispatch_lineage
        AND authoritative_observation
        AND observation_recorded_for_re_checking
        AND freshness_valid
        AND receipt_not_replayed

Every test here submits a receipt that is *well formed* and would previously
have been accepted. A test that submits obvious garbage proves nothing: the
question is whether a plausible attestation about the wrong thing is refused.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.governance.effect_receipt import (  # noqa: E402
    ReceiptRefused,
    derive_status,
    resolve_lineage,
    verify_receipt,
)
from remora.governance.effect_verification import EffectStatus  # noqa: E402

DISPATCHED_AT = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
OBSERVED_AT = DISPATCHED_AT + timedelta(seconds=5)
CALL_HASH = "a" * 64
JTI = "jti-dispatch-1"
DIGEST = "d" * 64


def _event(name: str, payload: dict | None = None, *, at: datetime | None = None):
    return {"event": name,
            "timestamp": (at or DISPATCHED_AT).isoformat(),
            "payload": {"event": name, "proposal_id": "prop-1",
                        **(payload or {})}}


def _dispatched(*, executed: bool = True, unknown: bool = False, **over):
    return [
        _event("assessed", at=DISPATCHED_AT - timedelta(seconds=30)),
        _event("execution_authorized", at=DISPATCHED_AT - timedelta(seconds=1)),
        _event("execution_result", {
            "tool_call_hash": CALL_HASH, "grant_jti": JTI,
            "tool_executed": executed, "state_unknown": unknown, **over}),
    ]


def _submit(events=None, **over):
    kwargs = dict(
        events=events if events is not None else _dispatched(),
        proposal_id="prop-1",
        claimed_status=EffectStatus.VERIFIED,
        tool_call_hash=CALL_HASH,
        grant_jti=JTI,
        expected_sha256=DIGEST,
        observed_sha256=DIGEST,
        verified_at=OBSERVED_AT.isoformat(),
        verifier_identity="deployment-graph-verifier",
        trusted_verifiers=[],
    )
    kwargs.update(over)
    return verify_receipt(**kwargs)


# ── the receipt that should be accepted ─────────────────────────────────────

def test_a_bound_observation_verifies():
    lineage, status = _submit()
    assert status is EffectStatus.VERIFIED
    assert lineage.dispatch_id == JTI
    assert lineage.tool_call_hash == CALL_HASH


# ── no dispatch at all: the original defect ────────────────────────────────

def test_a_proposal_that_never_dispatched_cannot_be_verified():
    """The reported reproduction. Assess, never approve, submit VERIFIED."""
    assessed_only = [_event("assessed"), _event("execution_verify")]
    with pytest.raises(ReceiptRefused) as exc:
        _submit(events=assessed_only)
    assert exc.value.reason == "no_dispatch"


def test_a_refused_dispatch_cannot_be_verified():
    """Refused is not merely unsuccessful: nothing ran, so nothing happened."""
    with pytest.raises(ReceiptRefused) as exc:
        _submit(events=_dispatched(executed=False))
    assert exc.value.reason == "dispatch_did_not_execute"


# ── wrong subject ───────────────────────────────────────────────────────────

def test_a_receipt_for_another_proposal_is_refused():
    with pytest.raises(ReceiptRefused) as exc:
        _submit(proposal_id="prop-other")
    assert exc.value.reason == "proposal_mismatch"


def test_a_receipt_for_another_call_is_refused():
    """Same proposal, different exact call. The digests could still match."""
    with pytest.raises(ReceiptRefused) as exc:
        _submit(tool_call_hash="b" * 64)
    assert exc.value.reason == "tool_call_hash_mismatch"


def test_a_receipt_carrying_another_dispatch_identity_is_refused():
    with pytest.raises(ReceiptRefused) as exc:
        _submit(grant_jti="jti-some-other-dispatch")
    assert exc.value.reason == "dispatch_mismatch"


# ── replay ──────────────────────────────────────────────────────────────────

def test_re_verifying_a_settled_dispatch_is_refused():
    """One SETTLED verdict per dispatch.

    Once VERIFIED or MISMATCH is recorded, a second verdict would either
    overwrite evidence or let a caller keep submitting until one is accepted.
    """
    with pytest.raises(ReceiptRefused) as exc:
        _submit(already_recorded=[{"dispatch_id": JTI,
                                   "status": "EFFECT_VERIFIED"}])
    assert exc.value.reason == "receipt_replayed"


def test_re_verifying_a_settled_mismatch_is_also_refused():
    with pytest.raises(ReceiptRefused) as exc:
        _submit(already_recorded=[{"dispatch_id": JTI,
                                   "status": "EFFECT_MISMATCH"}])
    assert exc.value.reason == "receipt_replayed"


@pytest.mark.parametrize("unresolved", ["EFFECT_UNOBSERVABLE",
                                        "EFFECT_VERIFIER_FAILED"])
def test_an_unresolved_verdict_may_be_superseded(unresolved):
    """This is how an unknown gets closed honestly.

    UNOBSERVABLE and VERIFIER_FAILED both mean "we do not know yet". Refusing a
    later observation would leave every timed-out read permanently
    unresolvable, which is a worse outcome than the replay it would prevent.
    """
    _lineage, status = _submit(
        already_recorded=[{"dispatch_id": JTI, "status": unresolved}])
    assert status is EffectStatus.VERIFIED


def test_a_receipt_for_a_different_dispatch_is_not_a_replay():
    """The check must be per dispatch, not per proposal.

    A retry produces a new grant and deserves its own receipt; refusing that
    would make an honest second attempt unverifiable.
    """
    lineage, status = _submit(
        already_recorded=[{"dispatch_id": "jti-an-earlier-attempt"}])
    assert status is EffectStatus.VERIFIED
    assert lineage.dispatch_id == JTI


# ── freshness ───────────────────────────────────────────────────────────────

def test_an_observation_predating_the_dispatch_is_refused():
    """A reading taken before the call cannot be evidence that it worked.

    This is the check that catches a pre-existing matching state being passed
    off as a verification -- the graph already said what the write was going
    to say, so the digests match and nothing was proved.
    """
    with pytest.raises(ReceiptRefused) as exc:
        _submit(verified_at=(DISPATCHED_AT - timedelta(seconds=1)).isoformat())
    assert exc.value.reason == "observation_precedes_dispatch"


def test_an_observation_at_the_dispatch_instant_is_allowed():
    """The boundary is exclusive: equal timestamps are not evidence of staleness."""
    _lineage, status = _submit(verified_at=DISPATCHED_AT.isoformat())
    assert status is EffectStatus.VERIFIED


def test_an_unparseable_observation_time_is_refused():
    with pytest.raises(ReceiptRefused) as exc:
        _submit(verified_at="whenever")
    assert exc.value.reason == "verified_at_unparseable"


# ── who looked ──────────────────────────────────────────────────────────────

def test_an_untrusted_verifier_is_refused():
    """Signed by someone is not signed by someone trusted to look."""
    with pytest.raises(ReceiptRefused) as exc:
        _submit(trusted_verifiers=["deployment-graph-verifier"],
                verifier_identity="attacker-verifier")
    assert exc.value.reason == "untrusted_verifier"


def test_an_empty_allowlist_accepts_any_named_verifier():
    """The research default, asserted so that tightening it is a visible change."""
    _lineage, status = _submit(trusted_verifiers=[],
                               verifier_identity="some-other-verifier")
    assert status is EffectStatus.VERIFIED


# ── the verdict is derived, not reported ────────────────────────────────────

def test_differing_digests_do_not_by_themselves_refuse_verified():
    """The rule this file originally encoded was WRONG, and is pinned here.

    expected_sha256 and observed_sha256 hash two different maps -- the expected
    FIELDS and the observed ROW -- and the comparison between them is
    rule-based. A passing verification routinely produces different digests, so
    requiring equality refused every legitimate VERIFIED the SDK produces.
    Caught by tests/test_sdk_effect_roundtrip.py, which was asserting the real
    contract while effect_receipt was inventing a different one.

    REMORA does not re-run the comparison and does not claim to.
    """
    _lineage, status = _submit(observed_sha256="e" * 64)
    assert status is EffectStatus.VERIFIED


def test_verified_is_refused_without_an_observation_to_compare():
    """A verdict with nothing behind it is an assertion, not a measurement."""
    with pytest.raises(ReceiptRefused) as exc:
        _submit(observed_sha256="")
    assert exc.value.reason == "verified_without_observation"


@pytest.mark.parametrize("status", [
    EffectStatus.MISMATCH,
    EffectStatus.UNOBSERVABLE,
    EffectStatus.VERIFIER_FAILED,
    EffectStatus.UNSUPPORTED,
])
def test_the_admissions_are_recorded_as_reported(status):
    """Bad news about itself is taken at face value, and should be.

    Only VERIFIED is derived. Requiring evidence for an admission would give a
    verifier a reason to stay silent instead of reporting a mismatch.
    """
    assert derive_status(status, expected_sha256="", observed_sha256="") is status


# ── UNKNOWN resolved by a later authoritative check ─────────────────────────

def test_an_unknown_dispatch_can_be_resolved_to_verified():
    """A lost response does not mean nothing happened.

    Requiring a SUCCEEDED dispatch first would force a false success to be
    recorded before the truth could be, which is the opposite of what this
    model is for.
    """
    _lineage, status = _submit(
        events=_dispatched(executed=False, unknown=True))
    assert status is EffectStatus.VERIFIED


def test_an_unknown_dispatch_can_also_be_resolved_to_mismatch():
    _lineage, status = _submit(
        events=_dispatched(executed=False, unknown=True),
        claimed_status=EffectStatus.MISMATCH,
        observed_sha256="e" * 64)
    assert status is EffectStatus.MISMATCH


# ── lineage is read from the chain, never from the receipt ──────────────────

def test_the_latest_dispatch_supersedes_an_earlier_one():
    events = _dispatched()
    events.append(_event("execution_result", {
        "tool_call_hash": CALL_HASH, "grant_jti": "jti-retry",
        "tool_executed": True}, at=DISPATCHED_AT + timedelta(seconds=1)))
    lineage = resolve_lineage(events)
    assert lineage.dispatch_id == "jti-retry", (
        "a retry supersedes; a receipt must attest to the attempt that ran last")
