"""SR-07 / SEC-07: only signed threshold proposals may relax the conformal
ACCEPT band, within a rolling-window budget, with an audit event.

On HEAD the bridge reads a plain JSON file, honours ``approved: true`` and
lowers ``trust_critical_min`` every adapt cycle — no signature, no author,
no window cap, no audit entry. Write access to the artifacts directory (or
control of the friction optimiser's episode-log input) silently widened the
gate's ACCEPT band.
"""

from __future__ import annotations

import datetime as _dt
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
    issued_at: str | None = None,
) -> None:
    payload = {
        "adjustments": adjustments,
        "holdout_evidence_sha256": "ab" * 32,
        "issued_at": issued_at
        or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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


def test_signed_proposal_cannot_be_replayed_after_the_window(tmp_path, monkeypatch) -> None:
    """Review follow-up: restoring a consumed file once the rolling window has
    rolled must not re-apply the same signed relaxation."""
    import shutil

    from remora.aromer.integration import bridge as bridge_mod

    proposals = tmp_path / "candidate_threshold_adjustments.json"
    key = _key()
    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key)
    saved = tmp_path / "saved.json"
    shutil.copy(proposals, saved)

    bridge = _bridge(tmp_path, proposals, key)
    first = bridge._apply_friction_optimizer_proposals()
    assert first["applied"] == 1
    after_first = bridge.get_threshold("trust_critical_min")

    # Age the relax log past the window so the budget is free again, keep the
    # proposal itself inside its validity window, and restore the file.
    bridge._relax_log = [(t - bridge_mod._RELAX_WINDOW_SECONDS - 1, d)
                         for t, d in bridge._relax_log]
    shutil.copy(saved, proposals)
    second = bridge._apply_friction_optimizer_proposals()
    assert second["applied"] == 0
    assert "replayed" in second["error"]
    assert bridge.get_threshold("trust_critical_min") == after_first

    # The replay ledger survives a restart.
    reloaded = _bridge(tmp_path, proposals, key)
    reloaded._relax_log = []
    third = reloaded._apply_friction_optimizer_proposals()
    assert third["applied"] == 0 and "replayed" in third["error"]


@pytest.mark.parametrize(
    "issued_at",
    ["2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z", "2026-10-28T00:00:00", "not-a-date"],
    ids=["expired", "future", "naive", "garbage"],
)
def test_proposal_outside_validity_window_is_refused(tmp_path, issued_at) -> None:
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    key = _key()
    _write_proposals(
        proposals, [{"approved": True, "max_delta": 0.05}], key, issued_at=issued_at
    )
    bridge = _bridge(tmp_path, proposals, key)
    before = bridge.get_threshold("trust_critical_min")
    result = bridge._apply_friction_optimizer_proposals()
    assert result["applied"] == 0
    assert "issued_at" in result["error"] or "validity window" in result["error"]
    assert bridge.get_threshold("trust_critical_min") == before
    assert proposals.exists(), "a refused proposal stays in place"


def test_audit_failure_leaves_threshold_and_file_untouched(tmp_path) -> None:
    """Review follow-up: the audit event is written before the change, so a
    failing sink applies nothing and consumes nothing."""
    proposals = tmp_path / "candidate_threshold_adjustments.json"
    key = _key()
    _write_proposals(proposals, [{"approved": True, "max_delta": 0.05}], key)

    def _sink(event: dict) -> None:
        raise OSError("audit store down")

    bridge = _bridge(tmp_path, proposals, key, audit=_sink)
    before = bridge.get_threshold("trust_critical_min")
    result = bridge._apply_friction_optimizer_proposals()
    assert result["applied"] == 0
    assert bridge.get_threshold("trust_critical_min") == before
    assert proposals.exists()
    assert bridge._relax_log == []
