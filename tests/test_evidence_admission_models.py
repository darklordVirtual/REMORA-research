# SPDX-License-Identifier: BUSL-1.1
"""Type-level invariants for the evidence-admission models."""
from __future__ import annotations

import pytest

from remora.evidence.admission import (
    CoverageAttestation,
    CoverageState,
    InvocationBindingProof,
    KnownGap,
    ManifestTrust,
    ObservationVantage,
    PriorCommitment,
    ProducerCapabilityManifest,
    VantageIndependence,
)

H64 = "a" * 64


def _manifest(**kw) -> ProducerCapabilityManifest:
    base = dict(
        producer_id="collector-1", manifest_id="m-1", schema_version="v1",
        fields_visible=("effect", "delegation"), scope={"tenant": "acme"},
        trust=ManifestTrust.ACCEPTED, valid_from=0, valid_until=1000,
    )
    base.update(kw)
    return ProducerCapabilityManifest(**base)


class TestProducerCapabilityManifest:
    def test_digest_is_deterministic(self) -> None:
        assert _manifest().digest == _manifest().digest
        assert len(_manifest().digest) == 64

    def test_digest_changes_with_fields(self) -> None:
        assert _manifest().digest != _manifest(
            fields_visible=("effect",),).digest

    def test_supplied_digest_cannot_hide_changed_manifest_content(self) -> None:
        with pytest.raises(ValueError, match="digest does not match"):
            _manifest(digest=_manifest().digest, fields_visible=("effect",))

    def test_invalid_window_refused(self) -> None:
        with pytest.raises(ValueError, match="valid_until"):
            _manifest(valid_from=100, valid_until=100)

    def test_empty_producer_refused(self) -> None:
        with pytest.raises(ValueError, match="producer_id"):
            _manifest(producer_id="  ")

    def test_frozen(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            _manifest().producer_id = "other"  # type: ignore[misc]

    def test_declared_is_not_accepted(self) -> None:
        m = _manifest(trust=ManifestTrust.DECLARED)
        assert m.trust is ManifestTrust.DECLARED


def _coverage(**kw) -> CoverageAttestation:
    base = dict(
        invocation_id="inv-1", fields=("effect",), interval_start=100,
        interval_end=200, state=CoverageState.COMPLETE, producer_id="collector-1",
    )
    base.update(kw)
    return CoverageAttestation(**base)


class TestCoverageAttestation:
    def test_complete_with_gaps_refused(self) -> None:
        with pytest.raises(ValueError, match="known gaps"):
            _coverage(known_gaps=(KnownGap(120, 130, "collector_unavailable"),))

    def test_incomplete_may_carry_gaps(self) -> None:
        c = _coverage(state=CoverageState.INCOMPLETE,
                      known_gaps=(KnownGap(120, 130, "collector_unavailable"),))
        assert c.state is CoverageState.INCOMPLETE

    def test_covers_interval_inside(self) -> None:
        assert _coverage().covers_interval(110, 190)

    def test_covers_interval_outside(self) -> None:
        assert not _coverage().covers_interval(50, 190)
        assert not _coverage().covers_interval(110, 250)

    def test_covers_interval_never_for_non_complete(self) -> None:
        assert not _coverage(state=CoverageState.UNKNOWN).covers_interval(110, 190)
        assert not _coverage(
            state=CoverageState.INCOMPLETE,
            known_gaps=(KnownGap(120, 130, "x"),),
        ).covers_interval(110, 190)


def _vantage(**kw) -> ObservationVantage:
    base = dict(
        observer_id="watcher-1", observed_party="agent-1",
        control_domain="deployer-a", observed_control_domain="deployer-a",
        can_observed_party_forge=False, can_observed_party_suppress=False,
    )
    base.update(kw)
    return ObservationVantage(**base)


class TestObservationVantage:
    def test_self_observation_is_never_independent(self) -> None:
        v = _vantage(observer_id="agent-1", observed_party="agent-1")
        assert v.independence is VantageIndependence.NOT_INDEPENDENT

    def test_declared_true_without_facts_stays_unestablished(self) -> None:
        v = _vantage(declared_independence=True)
        assert v.independence is VantageIndependence.NOT_ESTABLISHED

    def test_distinct_control_domain_derives_independence(self) -> None:
        v = _vantage(control_domain="deployer-b")
        assert v.independence is VantageIndependence.INDEPENDENT

    def test_forgeable_or_suppressible_is_not_independent(self) -> None:
        assert _vantage(control_domain="deployer-b",
                        can_observed_party_forge=True).independence is (
            VantageIndependence.NOT_INDEPENDENT)
        assert _vantage(control_domain="deployer-b",
                        can_observed_party_suppress=True).independence is (
            VantageIndependence.NOT_INDEPENDENT)


def _binding(**kw) -> InvocationBindingProof:
    base = dict(
        evidence_id="ev-1", proposal_id="p-1", execution_id="e-1",
        tool_call_hash=H64,
    )
    base.update(kw)
    return InvocationBindingProof(**base)


class TestInvocationBindingProof:
    def test_exact_match(self) -> None:
        assert _binding().matches(
            proposal_id="p-1", execution_id="e-1", tool_call_hash=H64)

    def test_hash_mismatch_rejects(self) -> None:
        assert not _binding().matches(
            proposal_id="p-1", execution_id="e-1", tool_call_hash="b" * 64)

    def test_declared_axis_absent_on_presented_side_rejects(self) -> None:
        b = _binding(tenant="acme")
        assert not b.matches(proposal_id="p-1", execution_id="e-1",
                             tool_call_hash=H64)

    def test_presented_axis_absent_on_declared_side_rejects(self) -> None:
        assert not _binding().matches(
            proposal_id="p-1", execution_id="e-1", tool_call_hash=H64,
            tenant="acme")

    def test_bad_hash_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="tool_call_hash"):
            _binding(tool_call_hash="not-a-hash")


def _commitment(**kw) -> PriorCommitment:
    base = dict(
        commitment_id="c-1", proposal_id="p-1", tool_call_hash=H64,
        target="prod", operation="write", expected_digest="c" * 64,
        created_at=100, valid_until=1000, issuer="deployer",
        provenance_ref="deployment-ledger://commitment/c-1",
    )
    base.update(kw)
    return PriorCommitment(**base)


class TestPriorCommitment:
    def test_digest_is_bound_to_content(self) -> None:
        commitment = _commitment()
        with pytest.raises(ValueError, match="digest does not match"):
            _commitment(digest=commitment.digest, expected_digest="d" * 64)

    def test_predates(self) -> None:
        assert _commitment().predates(150)
        assert not _commitment().predates(50)

    def test_binds_to_exact_action(self) -> None:
        c = _commitment()
        assert c.binds_to(proposal_id="p-1", tool_call_hash=H64,
                          target="prod", operation="write")
        assert not c.binds_to(proposal_id="p-2", tool_call_hash=H64,
                              target="prod", operation="write")

    def test_invalid_window_refused(self) -> None:
        with pytest.raises(ValueError, match="valid_until"):
            _commitment(created_at=500, valid_until=500)
