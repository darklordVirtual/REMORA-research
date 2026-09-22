# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The complete refusal surface of ``ExecutionLease.verify``, and what it signs.

``tests/test_lease_verification_contracts.py`` covers six of the sixteen named
refusals. The other ten, the order the checks run in, and the boundary of the
validity window were asserted only as "not verified", which a mutant can
satisfy while reporting the wrong cause. Twenty-five mutants in ``verify`` and
seven in ``_canonical_payload`` survived the 2026-09-21 sweep on that basis.

Two invariants here are not about reason literals at all, and they are the
reason this module exists rather than a handful of extra cases in the older
file:

* **Every persisted field must be inside the signature.** ``_signed_fields``
  is the preimage; ``_FIELDS`` is what ``from_dict`` will reconstruct. A field
  in the second set and not the first travels with the lease, is trusted by
  the dispatcher, and can be rewritten by whoever holds the lease without
  invalidating anything. The test derives the comparison instead of listing
  it, so a field added to the dataclass and forgotten in the preimage fails
  here rather than in an incident.
* **Each signed field is individually tamper-evident.** Mutating any one of
  them must produce ``signature_invalid``, which is what "the verifier
  reconstructs what it expects" has to mean in practice.

Scope (declared, not exhaustive): HMAC signing only, which is what the
environment under test provides. The Ed25519 path, key custody and downgrade
protection are covered by ``tests/test_lease_signing_contracts.py`` and
``tests/test_lease_authority_custody.py``; this module deliberately does not
restate them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from remora.enforcement import lease_signing as _signing
from remora.enforcement.lease import ExecutionLease

ISSUED = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
CALL: dict[str, Any] = {
    "tool_name": "wo_close",
    "arguments": {"id": "WO-1"},
    "tenant_id": "acme",
    "target_environment": "staging",
}


@pytest.fixture(autouse=True)
def _hmac_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "verification-completeness-key")
    for name in (
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
    ):
        monkeypatch.delenv(name, raising=False)


def _lease(**over) -> ExecutionLease:
    kwargs: dict[str, Any] = {
        "decision": "accept",
        "actor_identity": "agent-1",
        "policy_bundle_hash": "b1",
        "issued_at": ISSUED.isoformat(),
        **CALL,
    }
    kwargs.update(over)
    return ExecutionLease.issue(**kwargs)


def _verify(lease: ExecutionLease, at: datetime | None = None, **over):
    call = {**CALL, **over}
    call.setdefault("actor_identity", "agent-1")
    return lease.verify(now=(at or ISSUED).isoformat(), **call)


def _rebuild(lease: ExecutionLease, **over) -> ExecutionLease:
    """A lease with fields replaced but the ORIGINAL signature kept."""
    data = lease.to_dict()
    data.update(over)
    return ExecutionLease.from_dict(data)


def _resigned(lease: ExecutionLease, **over) -> ExecutionLease:
    """A lease with fields replaced and a VALID signature over the new values.

    ``issue`` mints accepts only, so the ``decision_not_accept`` branch is
    unreachable through it. Re-signing reaches the branch without weakening
    anything: the signature is genuine, which is the point -- a correctly
    signed lease for a non-accept decision must still refuse.
    """
    rebuilt = _rebuild(lease, **over)
    payload = ExecutionLease._canonical_payload(rebuilt._signed_fields())
    signature = _signing.sign_payload(payload, alg=rebuilt.sig_alg)
    return _rebuild(rebuilt, signature=signature, is_signed=True)


# ── what the signature has to cover ─────────────────────────────────────────


def test_every_reconstructable_field_is_inside_the_signature() -> None:
    signed = set(_lease()._signed_fields())
    reconstructable = set(ExecutionLease._FIELDS) - {"signature", "is_signed"}
    unsigned = sorted(reconstructable - signed)
    assert not unsigned, (
        f"these lease fields survive from_dict but are outside the signed preimage, so "
        f"the holder of a lease can rewrite them undetected: {unsigned}"
    )


def test_the_signed_preimage_is_canonical_json() -> None:
    """Pins the bytes, not only that a signature verifies against them."""
    fields = {"b": "2", "a": "1"}
    payload = ExecutionLease._canonical_payload(fields)
    assert payload == b'{"a":"1","b":"2"}', (
        "the lease preimage must be sorted, compact JSON; any other spelling "
        "invalidates every lease signed under the old one"
    )


def test_the_signature_is_an_hmac_over_exactly_that_payload() -> None:
    key = b"explicit-key"
    fields = _lease()._signed_fields()
    expected = hmac.new(
        key, json.dumps(fields, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256
    ).hexdigest()
    assert ExecutionLease._compute_signature(fields, key) == expected


@pytest.mark.parametrize(
    "field",
    # sig_alg is excluded: naming an unknown algorithm is refused as an
    # algorithm question (no_signing_key / signature_algorithm_refused) before
    # any signature is compared, which is the downgrade-protection contract in
    # tests/test_lease_signing_contracts.py rather than a tamper question.
    sorted(set(ExecutionLease._FIELDS) - {"signature", "is_signed", "decision", "sig_alg"}),
)
def test_each_signed_field_is_individually_tamper_evident(field: str) -> None:
    lease = _lease(
        toolspec_hash="ts-1",
        toolspec_version=3,
        proposal_id="prop-1",
        grant_jti="jti-1",
        runtime_identity_hash="rt-1",
        tool_contract_bundle_hash="tcb-1",
        intent_authority_hash="ia-1",
    )
    original = getattr(lease, field)
    tampered_value: Any
    if isinstance(original, int) and not isinstance(original, bool):
        tampered_value = original + 1
    else:
        tampered_value = f"{original or ''}-tampered"
    result = _verify(_rebuild(lease, **{field: tampered_value}))
    assert result.reason == "signature_invalid", (
        f"rewriting {field} on a signed lease produced {result.reason!r}; a field the "
        "signature does not cover is a field the holder controls"
    )


# ── the complete refusal surface ────────────────────────────────────────────


def test_an_accepted_call_verifies() -> None:
    result = _verify(_lease())
    assert (result.verified, result.reason) == (True, "ok")


def test_an_unsigned_lease_is_refused_before_anything_else_is_read() -> None:
    lease = _rebuild(_lease(), signature="", is_signed=False)
    assert _verify(lease).reason == "lease_not_signed"

    claimed_signed = _rebuild(_lease(), signature="", is_signed=True)
    assert _verify(claimed_signed).reason == "lease_not_signed", (
        "is_signed is presenter-supplied; an empty signature must refuse regardless"
    )


def test_a_correctly_signed_non_accept_lease_still_authorises_nothing() -> None:
    non_accept = _resigned(_lease(), decision="verify")
    assert _verify(non_accept).reason == "decision_not_accept", (
        "the signature says who minted the lease, not that the decision permits "
        "execution; a genuine signature over a non-accept must not open the path"
    )


def test_unparseable_timestamps_reach_a_verdict_rather_than_raising() -> None:
    lease = _lease()
    tampered = _rebuild(lease, expires_at="not-a-timestamp")
    # The signature covers expires_at, so the forged value is caught first.
    assert _verify(tampered).reason == "signature_invalid"
    # Supplied by the caller rather than carried by the lease: same fail-closed exit.
    result = lease.verify(now="not-a-timestamp", actor_identity="agent-1", **CALL)
    assert result.reason == "expiry_unparseable"


@pytest.mark.parametrize(
    ("name", "over", "expected"),
    [
        ("another tool", {"tool_name": "wo_open"}, "tool_name_mismatch"),
        ("another tenant", {"tenant_id": "other"}, "tenant_mismatch"),
        ("another environment", {"target_environment": "prod"}, "target_environment_mismatch"),
        ("another argument set", {"arguments": {"id": "WO-2"}}, "tool_args_hash_mismatch"),
        ("no actor presented", {"actor_identity": None}, "actor_identity_required"),
        ("another actor", {"actor_identity": "agent-2"}, "actor_identity_mismatch"),
    ],
)
def test_each_call_binding_names_its_own_refusal(name: str, over: dict, expected: str) -> None:
    result = _verify(_lease(), **over)
    assert result.verified is False
    assert result.reason == expected, f"{name} reported {result.reason!r}, expected {expected!r}"


@pytest.mark.parametrize(
    ("name", "issue_over", "verify_over", "expected"),
    [
        (
            "a lease issued before spec binding, checked against a spec",
            {},
            {"toolspec_hash": "ts-1"},
            "toolspec_hash_mismatch",
        ),
        (
            "a lease bound to another spec",
            {"toolspec_hash": "ts-1"},
            {"toolspec_hash": "ts-2"},
            "toolspec_hash_mismatch",
        ),
        (
            "a lease bound to another spec version",
            {"toolspec_hash": "ts-1", "toolspec_version": 2},
            {"toolspec_hash": "ts-1", "toolspec_version": 3},
            "toolspec_version_mismatch",
        ),
        (
            "a lease with no bundle identity, checked against one",
            {"policy_bundle_hash": ""},
            {"expected_policy_bundle_hash": "b1"},
            "policy_bundle_missing",
        ),
        (
            "a lease decided under another bundle",
            {},
            {"expected_policy_bundle_hash": "b2"},
            "policy_bundle_mismatch",
        ),
        (
            "a lease with no proposal identity, checked against one",
            {},
            {"expected_proposal_id": "prop-1"},
            "proposal_binding_missing",
        ),
        (
            "a lease bound to another proposal",
            {"proposal_id": "prop-1"},
            {"expected_proposal_id": "prop-2"},
            "proposal_mismatch",
        ),
    ],
)
def test_an_absent_binding_is_never_a_wildcard(
    name: str, issue_over: dict, verify_over: dict, expected: str
) -> None:
    """Upgrading a check must not amnesty the leases issued before it existed."""
    result = _verify(_lease(**issue_over), **verify_over)
    assert result.verified is False
    assert result.reason == expected, f"{name} reported {result.reason!r}"


def test_the_validity_window_is_half_open_at_both_ends() -> None:
    lease = _lease()
    expiry = datetime.fromisoformat(lease.expires_at)

    assert _verify(lease, at=ISSUED).verified is True, "usable at its own issuance instant"
    assert _verify(lease, at=ISSUED - timedelta(microseconds=1)).reason == "lease_not_yet_valid"
    assert _verify(lease, at=expiry - timedelta(microseconds=1)).verified is True
    assert _verify(lease, at=expiry).reason == "lease_expired", (
        "the window is [issued_at, expires_at); the expiry instant is outside it"
    )


def test_the_checks_run_in_the_order_the_refusals_claim() -> None:
    """A lease failing several checks must report the first one.

    Order is what makes a refusal diagnostic: a stolen lease presented for the
    wrong tool should read as the theft, not as the tool.
    """
    lease = _lease()
    expired_and_wrong_tool = _verify(
        lease, at=datetime.fromisoformat(lease.expires_at) + timedelta(minutes=1),
        tool_name="wo_open",
    )
    assert expired_and_wrong_tool.reason == "lease_expired"

    wrong_tool_and_tenant = _verify(lease, tool_name="wo_open", tenant_id="other")
    assert wrong_tool_and_tenant.reason == "tool_name_mismatch"

    wrong_tenant_and_actor = _verify(lease, tenant_id="other", actor_identity="agent-2")
    assert wrong_tenant_and_actor.reason == "tenant_mismatch"

    not_accept_and_expired = _verify(
        _resigned(_lease(), decision="verify"),
        at=ISSUED + timedelta(days=1),
    )
    assert not_accept_and_expired.reason == "decision_not_accept", (
        "the decision check precedes the lifetime check"
    )


def test_every_refusal_reason_in_this_module_is_distinct() -> None:
    lease = _lease()
    reasons = {
        _verify(_rebuild(lease, signature="", is_signed=False)).reason,
        _verify(_resigned(_lease(), decision="verify")).reason,
        _verify(lease, at=ISSUED - timedelta(seconds=1)).reason,
        _verify(lease, at=ISSUED + timedelta(days=1)).reason,
        _verify(lease, tool_name="wo_open").reason,
        _verify(lease, tenant_id="other").reason,
        _verify(lease, actor_identity=None).reason,
        _verify(lease, actor_identity="agent-2").reason,
        _verify(lease, target_environment="prod").reason,
        _verify(lease, arguments={"id": "WO-2"}).reason,
        _verify(lease, toolspec_hash="ts-1").reason,
        _verify(_lease(policy_bundle_hash=""), expected_policy_bundle_hash="b1").reason,
        _verify(lease, expected_policy_bundle_hash="b2").reason,
        _verify(lease, expected_proposal_id="prop-1").reason,
        _verify(lease).reason,
    }
    assert len(reasons) == 15, f"refusal literals collide: {sorted(reasons)}"
