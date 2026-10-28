"""SR-07 / SEC-07: only signed threshold proposals may relax the conformal
ACCEPT band, within a rolling-window budget, with an audit event.

On HEAD the bridge reads a plain JSON file, honours ``approved: true`` and
lowers ``trust_critical_min`` every adapt cycle — no signature, no author,
no window cap, no audit entry. Write access to the artifacts directory (or
control of the friction optimiser's episode-log input) silently widened the
gate's ACCEPT band.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.crypto.domain_signing import (
    SignatureDomain,
    SigningKey,
    sign,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _key(domains=(SignatureDomain.THRESHOLD_PROPOSAL,)) -> SigningKey:
    return SigningKey.generate(domains)


def _write_proposals(
    path: Path,
    adjustments: list[dict],
    key: SigningKey | None,
    *,
    sign_domains: tuple[SignatureDomain, ...] | None = None,
) -> None:
    payload = {
        "adjustments": adjustments,
        "holdout_evidence_sha256": "ab" * 32,
        "issued_at": "2026-10-28T00:00:00Z",
        "window_id": "2026-W44",
    }
    if key is None:
        path.write_text(json.dumps(payload), encoding="utf-8")
        return
    from remora.aromer.integration.bridge import (
        canonical_threshold_proposal_payload,
    )

    canonical = canonical_threshold_proposal_payload(**payload)
    signing_key = key
    if sign_domains is not None:
        signing_key = _key(sign_domains)
    sig = sign(signing_key.domains.__iter__().__next__(), canonical, signing_key)
    path.write_text(
        json.dumps({**payload, "signature": sig.to_dict()}), encoding="utf-8"
    )


def _bridge(tmp_path: Path, proposals: Path, key: SigningKey | None, audit=None):
    from remora.aromer.integration.bridge import AromerAdapterBridge

    keys = [key.verification_key()] if key is not None else None
    return AromerAdapterBridge(
        state_path=tmp_path / "bridge_state.json",
        proposals_path=proposals,
        proposal_verification_keys=keys,
        audit_sink=audit,
    )


def test_unsigned_approved_proposal_does_not_change_threshold(tmp_path) -> None:
    """The SR-07 attack: approved:true in plain JSON must do nothing."""
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    key = _key()
    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key=None)
    bridge = _bridge(tmp_path, proposals, key)

    start = bridge.get_threshold("trust_critical_min")
    report = bridge._apply_friction_optimizer_proposals()

    assert bridge.get_threshold("trust_critical_min") == pytest.approx(start)
    assert report["applied"] == 0
    assert "error" in report
    assert proposals.exists(), "a refused proposal file must stay for inspection"


def test_no_verification_keys_refuses_even_signed_files(tmp_path) -> None:
    """No configured trust anchor means nothing applies (fail closed)."""
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    signer = _key()
    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], signer)
    bridge = _bridge(tmp_path, proposals, key=None)

    start = bridge.get_threshold("trust_critical_min")
    report = bridge._apply_friction_optimizer_proposals()

    assert bridge.get_threshold("trust_critical_min") == pytest.approx(start)
    assert report["applied"] == 0
    assert "error" in report


def test_signed_proposal_applies_and_emits_audit_event(tmp_path) -> None:
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    key = _key()
    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key)
    events: list[dict] = []
    bridge = _bridge(tmp_path, proposals, key, audit=events.append)

    start = bridge.get_threshold("trust_critical_min")
    report = bridge._apply_friction_optimizer_proposals()

    assert report["applied"] == 1
    assert bridge.get_threshold("trust_critical_min") == pytest.approx(start - 0.05)

    assert len(events) == 1
    event = events[0]
    assert event["event"] == "threshold_changed"
    assert event["threshold"] == "trust_critical_min"
    assert event["before"] == pytest.approx(start)
    assert event["after"] == pytest.approx(start - 0.05)
    assert event["proposal_sha256"]
    assert event["signature_kid"] == key.kid


def test_wrong_domain_signature_is_refused(tmp_path) -> None:
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    key = _key()
    _write_proposals(
        proposals,
        [{"approved": True, "max_delta": 0.05}],
        key,
        sign_domains=(SignatureDomain.AUDIT,),
    )
    bridge = _bridge(tmp_path, proposals, key)

    start = bridge.get_threshold("trust_critical_min")
    report = bridge._apply_friction_optimizer_proposals()

    assert bridge.get_threshold("trust_critical_min") == pytest.approx(start)
    assert report["applied"] == 0
    assert "error" in report


def test_window_cap_holds_across_cycles(tmp_path) -> None:
    """Ten valid proposals in one window cannot relax more than the budget."""
    key = _key()
    bridge = _bridge(tmp_path, tmp_path / "proposals.json", key)
    proposals = bridge._proposals_path
    start = bridge.get_threshold("trust_critical_min")

    for _ in range(10):
        _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key)
        bridge._apply_friction_optimizer_proposals()

    relaxed = start - bridge.get_threshold("trust_critical_min")
    assert relaxed <= 0.05 + 1e-9, (
        f"rolling-window budget exceeded: {relaxed} > 0.05"
    )
    assert relaxed > 0, "the first signed proposal should have applied"


def test_relax_log_and_events_survive_restart(tmp_path) -> None:
    """The window budget must not reset with the process."""
    key = _key()
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    events: list[dict] = []
    bridge = _bridge(tmp_path, proposals, key, audit=events.append)

    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key)
    bridge._apply_friction_optimizer_proposals()
    after_first = bridge.get_threshold("trust_critical_min")

    from remora.aromer.integration.bridge import AromerAdapterBridge

    reopened = AromerAdapterBridge(
        state_path=tmp_path / "bridge_state.json",
        proposals_path=proposals,
        proposal_verification_keys=[key.verification_key()],
    )
    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key)
    report = reopened._apply_friction_optimizer_proposals()

    assert reopened.get_threshold("trust_critical_min") == pytest.approx(after_first)
    assert report["applied"] == 0 or report.get("total_delta", 0) == 0
