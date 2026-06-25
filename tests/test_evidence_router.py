"""Tests for remora.evidence — EvidenceSignal, EvidenceDecision,
CriticalEvidenceRouter."""
from __future__ import annotations

import pytest

from remora.evidence import (
    CriticalEvidenceRouter,
    EvidenceDecision,
    EvidenceLabel,
    EvidenceSignal,
)


# ---------------------------------------------------------------------------
# EvidenceSignal validation
# ---------------------------------------------------------------------------


def _make_signal(**overrides) -> EvidenceSignal:
    defaults = dict(
        evidence_strength=0.85,
        contradiction_score=0.10,
        citation_coverage=0.80,
        cross_evidence_consistency=0.90,
        source_reliability=0.90,
    )
    defaults.update(overrides)
    return EvidenceSignal(**defaults)


class TestEvidenceSignal:
    def test_valid_signal(self):
        sig = _make_signal()
        assert sig.evidence_strength == 0.85
        assert sig.contradiction_score == 0.10

    def test_boundary_values(self):
        # 0.0 and 1.0 are valid
        sig = _make_signal(evidence_strength=0.0, contradiction_score=1.0)
        assert sig.evidence_strength == 0.0

    @pytest.mark.parametrize(
        "field,value",
        [
            ("evidence_strength", -0.01),
            ("evidence_strength", 1.001),
            ("contradiction_score", -0.1),
            ("citation_coverage", 1.5),
            ("source_reliability", -0.5),
        ],
    )
    def test_invalid_field_raises(self, field, value):
        with pytest.raises(ValueError, match=field):
            _make_signal(**{field: value})

    def test_frozen(self):
        sig = _make_signal()
        with pytest.raises((AttributeError, TypeError)):
            sig.evidence_strength = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EvidenceDecision validation
# ---------------------------------------------------------------------------


class TestEvidenceDecision:
    def _make_decision(self, action="evidence_accept", confidence=0.90):
        sig = _make_signal()
        return EvidenceDecision(
            action=action,
            reason="test",
            signal=sig,
            confidence=confidence,
        )

    def test_valid_actions(self):
        for action in ("evidence_accept", "abstain", "escalate"):
            d = self._make_decision(action=action)
            assert d.action == action

    def test_invalid_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            self._make_decision(action="INVALID")

    def test_confidence_out_of_range(self):
        with pytest.raises(ValueError, match="confidence"):
            self._make_decision(confidence=1.5)

    def test_confidence_negative(self):
        with pytest.raises(ValueError, match="confidence"):
            self._make_decision(confidence=-0.1)

    def test_frozen(self):
        d = self._make_decision()
        with pytest.raises((AttributeError, TypeError)):
            d.action = "abstain"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EvidenceLabel enum
# ---------------------------------------------------------------------------


class TestEvidenceLabel:
    def test_values(self):
        assert EvidenceLabel.SUPPORTS.value == "supports"
        assert EvidenceLabel.INSUFFICIENT.value == "insufficient"
        assert EvidenceLabel.CONTRADICTS.value == "contradicts"


# ---------------------------------------------------------------------------
# CriticalEvidenceRouter — happy path
# ---------------------------------------------------------------------------


class TestCriticalEvidenceRouterDefaults:
    def setup_method(self):
        self.router = CriticalEvidenceRouter()

    def test_evidence_accept_strong_signal(self):
        sig = _make_signal(
            evidence_strength=0.92,
            contradiction_score=0.05,
            citation_coverage=0.85,
            source_reliability=0.95,
        )
        d = self.router.route(sig)
        assert d.action == "evidence_accept"
        assert 0.0 < d.confidence <= 1.0

    def test_abstain_high_contradiction(self):
        sig = _make_signal(
            evidence_strength=0.88,
            contradiction_score=0.75,
            citation_coverage=0.80,
        )
        d = self.router.route(sig)
        assert d.action == "abstain"

    def test_escalate_low_coverage(self):
        sig = _make_signal(
            evidence_strength=0.90,
            contradiction_score=0.05,
            citation_coverage=0.20,  # below 0.50 minimum
        )
        d = self.router.route(sig)
        assert d.action == "escalate"
        assert "coverage" in d.reason.lower()

    def test_escalate_weak_evidence(self):
        sig = _make_signal(
            evidence_strength=0.40,   # below accept_threshold 0.80
            contradiction_score=0.10,
            citation_coverage=0.70,
        )
        d = self.router.route(sig)
        assert d.action == "escalate"

    def test_escalate_low_reliability(self):
        sig = _make_signal(
            evidence_strength=0.90,
            contradiction_score=0.05,
            citation_coverage=0.80,
            source_reliability=0.40,  # below reliability_minimum 0.60
        )
        d = self.router.route(sig)
        assert d.action == "escalate"

    def test_escalate_borderline_contradiction(self):
        """contradiction_score above limit but below floor → escalate, not abstain."""
        sig = _make_signal(
            evidence_strength=0.85,
            contradiction_score=0.30,  # > limit 0.15, < floor 0.50
            citation_coverage=0.80,
        )
        d = self.router.route(sig)
        assert d.action == "escalate"

    def test_abstain_above_floor(self):
        """contradiction_score strictly above floor → abstain."""
        sig = _make_signal(
            contradiction_score=0.51,  # default floor is 0.50; must be strictly >
            citation_coverage=0.80,
        )
        d = self.router.route(sig)
        assert d.action == "abstain"

    def test_escalate_exactly_at_floor(self):
        """contradiction_score exactly == floor is NOT sufficient for abstain → escalate."""
        sig = _make_signal(
            evidence_strength=0.50,   # below accept_threshold
            contradiction_score=0.50,  # == floor (not strictly >)
            citation_coverage=0.80,
        )
        d = self.router.route(sig)
        assert d.action == "escalate"


# ---------------------------------------------------------------------------
# CriticalEvidenceRouter — custom thresholds
# ---------------------------------------------------------------------------


class TestCriticalEvidenceRouterCustomThresholds:
    def test_lower_accept_threshold(self):
        router = CriticalEvidenceRouter(accept_threshold=0.60)
        sig = _make_signal(
            evidence_strength=0.65,
            contradiction_score=0.08,
            citation_coverage=0.70,
            source_reliability=0.80,
        )
        d = router.route(sig)
        assert d.action == "evidence_accept"

    def test_stricter_contradiction_limit(self):
        router = CriticalEvidenceRouter(contradiction_limit=0.05)
        sig = _make_signal(
            evidence_strength=0.92,
            contradiction_score=0.10,  # > new limit 0.05
            citation_coverage=0.80,
        )
        d = router.route(sig)
        # Should escalate or abstain, not accept
        assert d.action in ("escalate", "abstain")

    def test_invalid_threshold_negative(self):
        with pytest.raises(ValueError):
            CriticalEvidenceRouter(accept_threshold=-0.1)

    def test_invalid_threshold_above_one(self):
        with pytest.raises(ValueError):
            CriticalEvidenceRouter(accept_threshold=1.5)

    def test_contradiction_limit_must_be_below_floor(self):
        with pytest.raises(ValueError, match="contradiction_limit"):
            CriticalEvidenceRouter(
                contradiction_limit=0.60, contradiction_floor=0.50
            )

    def test_equal_limit_and_floor_raises(self):
        with pytest.raises(ValueError, match="contradiction_limit"):
            CriticalEvidenceRouter(
                contradiction_limit=0.50, contradiction_floor=0.50
            )


# ---------------------------------------------------------------------------
# CriticalEvidenceRouter — decision precedence
# ---------------------------------------------------------------------------


class TestDecisionPrecedence:
    """Coverage gate fires before contradiction block."""

    def test_low_coverage_overrides_high_contradiction(self):
        router = CriticalEvidenceRouter()
        sig = _make_signal(
            citation_coverage=0.10,   # below coverage_minimum
            contradiction_score=0.95,  # above contradiction_floor
        )
        d = router.route(sig)
        # Coverage gate fires first → escalate, not abstain
        assert d.action == "escalate"
        assert "coverage" in d.reason.lower()

    def test_accept_gate_not_triggered_by_high_contradiction(self):
        router = CriticalEvidenceRouter()
        sig = _make_signal(
            evidence_strength=0.95,
            contradiction_score=0.60,  # above floor → abstain
            citation_coverage=0.80,
        )
        d = router.route(sig)
        assert d.action == "abstain"  # not evidence_accept


# ---------------------------------------------------------------------------
# Confidence range checks
# ---------------------------------------------------------------------------


class TestConfidenceValues:
    def test_evidence_accept_confidence_in_range(self):
        router = CriticalEvidenceRouter()
        sig = _make_signal(
            evidence_strength=0.90,
            contradiction_score=0.05,
            citation_coverage=0.85,
            cross_evidence_consistency=0.85,
            source_reliability=0.92,
        )
        d = router.route(sig)
        assert d.action == "evidence_accept"
        assert 0.0 < d.confidence <= 1.0

    def test_abstain_confidence_in_range(self):
        router = CriticalEvidenceRouter()
        sig = _make_signal(contradiction_score=0.80, citation_coverage=0.75)
        d = router.route(sig)
        assert d.action == "abstain"
        assert 0.0 <= d.confidence <= 1.0

    def test_escalate_confidence_in_range(self):
        router = CriticalEvidenceRouter()
        sig = _make_signal(evidence_strength=0.30, citation_coverage=0.60)
        d = router.route(sig)
        assert d.action == "escalate"
        assert 0.0 <= d.confidence <= 1.0
