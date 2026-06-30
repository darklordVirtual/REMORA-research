# Author: Stian Skogbrott
# License: Apache-2.0
"""Policy engine assurance audit tests — Agent A findings (2026-06-30).

Tests corresponding to the threat model and findings documented in
docs/assurance/policy_engine_audit_v1.md.

Findings covered
----------------
F-1: Unknown action_type + unknown risk_tier can reach ACCEPT (design gap, documented)
F-2: PolicyDecisionToken has no expiry — observation-hash binding verified as partial mitigation
F-3: AROMER_CONFORMAL_TRUST_THRESHOLD class attribute has no effect on decide()
F-4: policy_bundle_hash utility produces deterministic output

Additional coverage
-------------------
- Critical risk is blocked from all ACCEPT paths (verified)
- Schema unverified floor fires before conformal ACCEPT paths
- GAP A (counterfactual=None) fires before conformal ACCEPT paths
- argument_tainted floor survives all ACCEPT conditions
- Token action-field tampering is rejected by PEP
- Envelope hash detects verdict tampering
- Hash chain single-entry tamper detected
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.invariants import check_all_invariants, assert_invariants
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason
from remora.policy.versioning import compute_policy_bundle_hash, policy_bundle_manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="audit test action", **kwargs)


_engine = RemoraDecisionEngine()
_engine_conformal_phase = RemoraDecisionEngine(conformal_phase_thresholds={"ordered": 0.5})
_engine_conformal_trust = RemoraDecisionEngine(conformal_trust_threshold=0.5)
_engine_temperature = RemoraDecisionEngine(temperature_threshold=0.5)


# ---------------------------------------------------------------------------
# Finding F-1: Unknown action_type + unknown risk_tier can reach ACCEPT
# (documented design gap — tests assert current behavior, not fix it)
# ---------------------------------------------------------------------------

class TestUnknownActionTypeAcceptPath:
    """F-1: unknown action_type with unknown risk_tier can ACCEPT — documented gap.

    The engine intentionally does not block unknown action_type conservatively to
    avoid over-blocking tools that declare no action_type.  These tests document
    the gap and verify that the existing invariants still hold.
    """

    def test_none_action_type_none_risk_tier_high_trust_can_accept(self) -> None:
        """Unknown action + unknown risk + high trust + ordered phase → ACCEPT (gap)."""
        obs = _obs(
            phase="ordered",
            risk_tier=None,
            trust_score=0.95,
            action_type=None,
            target_environment=None,
        )
        report = _engine.decide(obs)
        # Document: this is the gap — no gate blocks unclassified actions
        assert report.action == DecisionAction.ACCEPT, (
            "F-1 gap: unknown action_type + unknown risk_tier + high trust ACCEPTS. "
            "Callers must classify action_type or accept this conservative default."
        )
        # Invariants must still hold even for this accepted observation
        assert_invariants(obs, report)

    def test_none_action_type_conformal_phase_can_accept(self) -> None:
        """Unknown action + ordered conformal phase threshold + high trust → ACCEPT (gap)."""
        obs = _obs(
            phase="ordered",
            risk_tier=None,
            trust_score=0.99,
            action_type=None,
        )
        report = _engine_conformal_phase.decide(obs)
        # F-1: still ACCEPT through conformal path
        assert report.action == DecisionAction.ACCEPT
        assert_invariants(obs, report)

    def test_known_action_type_unknown_risk_mutating_not_accept(self) -> None:
        """Known mutating action + unknown risk_tier must NOT ACCEPT."""
        obs = _obs(
            phase="ordered",
            risk_tier=None,
            trust_score=0.99,
            action_type="write",
        )
        report = _engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            "write + unknown risk_tier must be blocked by unknown_risk_tier gate"
        )
        assert DecisionReason.UNKNOWN_RISK_TIER_VERIFY in report.reasons

    def test_production_env_unknown_risk_not_accept(self) -> None:
        """Unknown risk_tier + production target must NOT ACCEPT."""
        obs = _obs(
            phase="ordered",
            risk_tier=None,
            trust_score=0.99,
            target_environment="prod",
        )
        report = _engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# Critical risk is blocked from all ACCEPT paths
# ---------------------------------------------------------------------------

class TestCriticalRiskNeverAccepts:
    """Verify critical risk_tier is architecturally excluded from ACCEPT."""

    @pytest.mark.parametrize("engine", [
        _engine,
        _engine_conformal_phase,
        _engine_conformal_trust,
        _engine_temperature,
    ])
    def test_critical_risk_does_not_accept_with_all_accept_conditions(
        self, engine: RemoraDecisionEngine
    ) -> None:
        """Critical risk must not ACCEPT regardless of trust/evidence/conformal settings."""
        obs = _obs(
            phase="ordered",
            risk_tier="critical",
            trust_score=0.99,
            temperature=0.01,
            evidence_action="answer",
            evidence_confidence=0.99,
            counterfactual_passed=True,
            evidence_contradictions=0,
            action_type="read",
            schema_valid=True,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            f"critical risk must never ACCEPT; got {report.action} via {engine!r}"
        )
        assert_invariants(obs, report)

    def test_critical_risk_invariant_holds(self) -> None:
        """CRITICAL_NEVER_AUTONOMOUSLY_ACCEPTED invariant holds for all engine configs."""
        engines = [_engine, _engine_conformal_phase, _engine_conformal_trust, _engine_temperature]
        for eng in engines:
            obs = _obs(risk_tier="critical", trust_score=0.99, phase="ordered")
            report = eng.decide(obs)
            results = check_all_invariants(obs, report)
            violations = [r for r in results if r.violated]
            assert not violations, f"Invariant violation: {violations}"


# ---------------------------------------------------------------------------
# Schema unverified floor fires before conformal ACCEPT
# ---------------------------------------------------------------------------

class TestSchemaUnverifiedFloorBeforeConformal:
    """Schema floor (GAP B) must fire before any conformal ACCEPT path."""

    @pytest.mark.parametrize("action_type", ["write", "delete", "config_change"])
    def test_schema_none_mutating_not_accept_with_conformal_phase(
        self, action_type: str
    ) -> None:
        """schema_valid=None + mutating action MUST NOT ACCEPT even with conformal threshold."""
        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            action_type=action_type,
            schema_valid=None,
        )
        report = _engine_conformal_phase.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            f"schema_valid=None + {action_type!r} must not ACCEPT via conformal path"
        )
        assert DecisionReason.SCHEMA_UNVERIFIED_VERIFY in report.reasons

    @pytest.mark.parametrize("action_type", ["write", "delete"])
    def test_schema_none_mutating_not_accept_with_conformal_trust(
        self, action_type: str
    ) -> None:
        """schema_valid=None + mutating action: same for marginal conformal trust threshold."""
        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            action_type=action_type,
            schema_valid=None,
        )
        report = _engine_conformal_trust.decide(obs)
        assert report.action != DecisionAction.ACCEPT

    @pytest.mark.parametrize("action_type", ["write", "delete"])
    def test_schema_none_mutating_not_accept_with_temperature(
        self, action_type: str
    ) -> None:
        """schema_valid=None + mutating action: same for temperature threshold."""
        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            temperature=0.01,  # well below threshold
            action_type=action_type,
            schema_valid=None,
        )
        report = _engine_temperature.decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_schema_none_read_only_can_accept_via_conformal(self) -> None:
        """Read-only action with schema_valid=None CAN still accept via conformal."""
        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            action_type="read",
            schema_valid=None,
        )
        report = _engine_conformal_phase.decide(obs)
        assert report.action == DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# GAP A (counterfactual=None) fires before conformal ACCEPT
# ---------------------------------------------------------------------------

class TestCounterfactualNoneBeforeConformal:
    """counterfactual_passed=None for high/critical evidence path fires before conformal."""

    @pytest.mark.parametrize("risk_tier", ["high", "critical"])
    def test_counterfactual_none_high_critical_not_accept_via_conformal(
        self, risk_tier: str
    ) -> None:
        """GAP A check fires before conformal ACCEPT for high/critical risk with evidence."""
        obs = _obs(
            phase="ordered",
            risk_tier=risk_tier,
            trust_score=0.99,
            evidence_action="answer",
            evidence_confidence=0.95,
            counterfactual_passed=None,
        )
        report = _engine_conformal_phase.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            f"counterfactual_passed=None + {risk_tier!r} must not ACCEPT via conformal"
        )

    def test_counterfactual_none_high_risk_reason_code(self) -> None:
        """COUNTERFACTUAL_UNKNOWN_VERIFY reason appears when GAP A fires."""
        obs = _obs(
            phase="ordered",
            risk_tier="high",
            evidence_action="evidence_accept",
            evidence_confidence=0.9,
            counterfactual_passed=None,
        )
        report = _engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT
        assert DecisionReason.COUNTERFACTUAL_UNKNOWN_VERIFY in report.reasons


# ---------------------------------------------------------------------------
# argument_tainted floor survives all ACCEPT conditions
# ---------------------------------------------------------------------------

class TestArgumentTaintedFloor:
    """argument_tainted=True must prevent ACCEPT regardless of other conditions."""

    @pytest.mark.parametrize("engine", [
        _engine,
        _engine_conformal_phase,
        _engine_conformal_trust,
        _engine_temperature,
    ])
    def test_tainted_argument_not_accept_any_engine(
        self, engine: RemoraDecisionEngine
    ) -> None:
        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            temperature=0.01,
            evidence_action="answer",
            evidence_confidence=0.99,
            counterfactual_passed=True,
            schema_valid=True,
            argument_tainted=True,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            "argument_tainted=True must prevent ACCEPT regardless of trust/evidence"
        )

    def test_tainted_reason_code_present(self) -> None:
        obs = _obs(argument_tainted=True, phase="ordered", trust_score=0.99)
        report = _engine.decide(obs)
        assert DecisionReason.TAINTED_ARGUMENT_VERIFY in report.reasons


# ---------------------------------------------------------------------------
# F-2: Token observation-hash binding — partial mitigation for no-expiry gap
# ---------------------------------------------------------------------------

class TestTokenObservationHashBinding:
    """F-2: Token has no expiry, but observation_hash binding limits cross-action reuse."""

    def test_token_for_obs_a_cannot_authorize_obs_b(self, monkeypatch) -> None:
        """A token issued for observation A is rejected when presented for observation B."""
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "audit-test-key")
        from remora.enforcement.token import PolicyDecisionToken, _hash_observation

        obs_a = _obs(phase="ordered", trust_score=0.9, risk_tier="low")
        obs_b = _obs(phase="ordered", trust_score=0.9, risk_tier="high")
        hash_a = _hash_observation(obs_a)
        hash_b = _hash_observation(obs_b)
        assert hash_a != hash_b, "Different observations must produce different hashes"

        token_a = PolicyDecisionToken.issue("accept", hash_a, "req-a", "2026-06-30T00:00:00Z")

        # Token issued for obs_a must fail when checked against obs_b's hash
        result = token_a.verify(observation_hash=hash_b)
        assert not result.verified
        assert result.reason == "observation_hash_mismatch"

    def test_same_observation_hash_reuse_is_possible(self, monkeypatch) -> None:
        """F-2 documented gap: token for obs_a still passes when re-checked against obs_a's hash."""
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "audit-test-key")
        from remora.enforcement.token import PolicyDecisionToken, _hash_observation

        obs = _obs(phase="ordered", trust_score=0.9, risk_tier="low")
        obs_hash = _hash_observation(obs)
        token = PolicyDecisionToken.issue("accept", obs_hash, "req-1", "2026-06-30T00:00:00Z")

        # First use
        result1 = token.verify(observation_hash=obs_hash)
        assert result1.verified

        # Second use (replay) — still passes because no nonce/TTL
        result2 = token.verify(observation_hash=obs_hash)
        assert result2.verified, (
            "F-2: token replay for same observation is not blocked (no TTL/nonce). "
            "This is a documented gap requiring a nonce store."
        )


# ---------------------------------------------------------------------------
# Token action-field tampering rejected by PEP
# ---------------------------------------------------------------------------

class TestTokenActionTamperingRejected:
    """Changing token action field after signing must be rejected."""

    def test_escalate_to_accept_tamper_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "audit-test-key-pep")
        from remora.enforcement.token import PolicyDecisionToken
        from remora.enforcement.gate import EnforcementGate

        token = PolicyDecisionToken.issue("escalate", "obs-hash", "req-1", "2026-06-30T00:00:00Z")
        # Tamper: change action to 'accept' but keep original signature
        tampered = PolicyDecisionToken(
            action="accept",                      # changed from escalate
            observation_hash=token.observation_hash,
            request_id=token.request_id,
            issued_at=token.issued_at,
            signature=token.signature,            # original signature (now invalid)
            is_signed=True,
        )
        gate = EnforcementGate(strict=True)
        result = gate.check(tampered)
        assert not result.allowed, "Tampered action field must be rejected by PEP"
        assert "token_verification_failed" in result.reason


# ---------------------------------------------------------------------------
# F-3: AROMER_CONFORMAL_TRUST_THRESHOLD class attribute has no effect on decide()
# ---------------------------------------------------------------------------

class TestAromerConformalThresholdClassAttrUnused:
    """F-3: AROMER_CONFORMAL_TRUST_THRESHOLD is a documentation constant, not an active gate."""

    def test_class_attribute_does_not_activate_conformal_accept(self) -> None:
        """Setting class attribute does not enable conformal ACCEPT path."""
        engine_no_conf = RemoraDecisionEngine()  # no instance conformal_trust_threshold
        # Verify class attribute value is set
        assert engine_no_conf.AROMER_CONFORMAL_TRUST_THRESHOLD == 0.72

        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            action_type="read",
        )
        report = engine_no_conf.decide(obs)
        # Even with trust=0.99 > 0.72, conformal_trust_threshold=None means the
        # marginal conformal path is inactive; ACCEPT comes from ordered_high_trust path
        assert report.action == DecisionAction.ACCEPT
        assert DecisionReason.CONFORMAL_ACCEPT not in report.reasons
        assert DecisionReason.ORDERED_HIGH_TRUST in report.reasons

    def test_instance_conformal_threshold_activates_accept(self) -> None:
        """Instance conformal_trust_threshold does activate the conformal ACCEPT path."""
        engine_with_conf = RemoraDecisionEngine(conformal_trust_threshold=0.72)
        obs = _obs(
            phase="ordered",
            risk_tier="low",
            trust_score=0.99,
            action_type="read",
        )
        report = engine_with_conf.decide(obs)
        assert report.action == DecisionAction.ACCEPT
        assert DecisionReason.CONFORMAL_ACCEPT in report.reasons


# ---------------------------------------------------------------------------
# Envelope hash detects verdict tampering
# ---------------------------------------------------------------------------

class TestEnvelopeHashIntegrity:
    """Verify DecisionEnvelope.envelope_hash() detects verdict tampering."""

    def test_envelope_hash_changes_on_verdict_tamper(self) -> None:
        from remora.governance.envelope import (
            DecisionEnvelope, RequestBlock, AssessmentBlock, GateBlock, AuditBlock
        )
        req = RequestBlock(
            request_id="req-audit-001",
            domain="finance",
            risk_tier="high",
            proposed_action="transfer 10000",
            action_type="financial_write",
            target_environment="prod",
        )
        ass = AssessmentBlock(
            oracle_votes=[],
            thermodynamic={"trust_score": 0.3},
            evidence_quality={},
            policy_triggers=["trap_escalate"],
        )
        env_escalate = DecisionEnvelope(
            request=req,
            assessment=ass,
            gate=GateBlock(outcome="escalate"),
            audit=AuditBlock(policy_version="RemoraDecisionEngine-v3"),
        )
        env_accept = DecisionEnvelope(
            request=req,
            assessment=ass,
            gate=GateBlock(outcome="accept"),   # tampered
            audit=AuditBlock(policy_version="RemoraDecisionEngine-v3"),
        )
        assert env_escalate.envelope_hash() != env_accept.envelope_hash(), (
            "Verdict change must produce different envelope hash"
        )

    def test_envelope_hash_stable_for_same_inputs(self) -> None:
        from remora.governance.envelope import (
            DecisionEnvelope, RequestBlock, AssessmentBlock, GateBlock, AuditBlock
        )
        req = RequestBlock(
            request_id="req-stable",
            domain="infra",
            risk_tier="critical",
            proposed_action="restart prod",
            action_type="production_write",
            target_environment="production",
        )
        ass = AssessmentBlock(
            oracle_votes=[],
            thermodynamic={},
            evidence_quality={},
            policy_triggers=["critical_phase"],
        )
        env = DecisionEnvelope(
            request=req,
            assessment=ass,
            gate=GateBlock(outcome="escalate"),
            audit=AuditBlock(policy_version="RemoraDecisionEngine-v3"),
        )
        h1 = env.envelope_hash()
        h2 = env.envelope_hash()
        assert h1 == h2, "Envelope hash must be deterministic"

    def test_envelope_hash_changes_on_risk_tier_tamper(self) -> None:
        from remora.governance.envelope import (
            DecisionEnvelope, RequestBlock, AssessmentBlock, GateBlock, AuditBlock
        )
        ass = AssessmentBlock(
            oracle_votes=[],
            thermodynamic={},
            evidence_quality={},
            policy_triggers=[],
        )
        env_high = DecisionEnvelope(
            request=RequestBlock("r1", "d", "high", "a", "write", "prod"),
            assessment=ass, gate=GateBlock("verify"),
            audit=AuditBlock(),
        )
        env_low = DecisionEnvelope(
            request=RequestBlock("r1", "d", "low", "a", "write", "prod"),  # changed tier
            assessment=ass, gate=GateBlock("verify"),
            audit=AuditBlock(),
        )
        assert env_high.envelope_hash() != env_low.envelope_hash()


# ---------------------------------------------------------------------------
# Hash chain single-entry tamper detected
# ---------------------------------------------------------------------------

class TestHashChainTamperDetection:
    """Verify AuditHashChain.verify() detects single-entry tampering."""

    def test_single_entry_tamper_detected(self) -> None:
        from remora.audit.hash_chain import AuditHashChain, HashChainEntry

        chain = AuditHashChain()
        e1 = chain.append(
            timestamp="2026-06-30T00:00:00",
            question_hash="q1",
            action="escalate",
            trust_score=0.3,
            phase="critical",
            metadata={"risk_tier": "high"},
        )
        chain.append(
            timestamp="2026-06-30T00:01:00",
            question_hash="q2",
            action="accept",
            trust_score=0.9,
            phase="ordered",
            metadata={"risk_tier": "low"},
        )
        assert chain.verify(), "Unmodified chain must verify"

        # Tamper: change action but keep original hash (self-verification should fail)
        tampered = HashChainEntry(
            timestamp=e1.timestamp,
            question_hash=e1.question_hash,
            action="accept",            # changed from 'escalate'
            trust_score=e1.trust_score,
            phase=e1.phase,
            previous_hash=e1.previous_hash,
            entry_hash=e1.entry_hash,   # original hash — now invalid
            metadata=e1.metadata,
        )
        assert not tampered.verify(), "Tampered entry must fail self-verification"

    def test_chain_linkage_break_detected(self) -> None:
        from remora.audit.hash_chain import AuditHashChain, HashChainEntry

        chain = AuditHashChain()
        e1 = chain.append(
            timestamp="2026-06-30T10:00:00",
            question_hash="a1",
            action="verify",
            trust_score=0.5,
            phase="ordered",
            metadata={},
        )
        e2 = chain.append(
            timestamp="2026-06-30T10:01:00",
            question_hash="a2",
            action="accept",
            trust_score=0.8,
            phase="ordered",
            metadata={},
        )
        # Verify that e2's previous_hash matches e1.entry_hash
        assert e2.previous_hash == e1.entry_hash
        # If e1 is replaced with a different entry, e2's previous_hash check fails
        fake_e1 = HashChainEntry(
            timestamp=e1.timestamp,
            question_hash=e1.question_hash,
            action="accept",
            trust_score=e1.trust_score,
            phase=e1.phase,
            previous_hash=e1.previous_hash,
            entry_hash="fake" * 8,
            metadata=e1.metadata,
        )
        assert not e2.verify(previous=fake_e1), (
            "e2 must fail when previous entry has a different hash"
        )


# ---------------------------------------------------------------------------
# F-4: policy_bundle_hash utility (new: remora/policy/versioning.py)
# ---------------------------------------------------------------------------

class TestPolicyBundleHash:
    """F-4: compute_policy_bundle_hash() produces deterministic stable hashes."""

    def test_bundle_hash_is_deterministic(self) -> None:
        h1 = compute_policy_bundle_hash()
        h2 = compute_policy_bundle_hash()
        assert h1 == h2, "Policy bundle hash must be deterministic"

    def test_bundle_hash_is_hex_sha256(self) -> None:
        h = compute_policy_bundle_hash()
        assert len(h) == 64, f"Expected 64-char hex SHA-256, got {len(h)}"
        assert all(c in "0123456789abcdef" for c in h), "Hash must be lowercase hex"

    def test_bundle_hash_changes_on_different_file_set(self) -> None:
        """Restricting to one file produces a different hash than the full set."""
        h_full = compute_policy_bundle_hash()
        h_engine_only = compute_policy_bundle_hash(
            ["remora/policy/decision_engine.py"]
        )
        assert h_full != h_engine_only

    def test_manifest_covers_expected_files(self) -> None:
        manifest = policy_bundle_manifest()
        expected_keys = {
            "remora/policy/decision_engine.py",
            "remora/policy/invariants.py",
            "remora/policy/observation.py",
            "remora/policy/trap_classifier.py",
            "remora/policy/report.py",
        }
        assert expected_keys == set(manifest.keys())

    def test_manifest_values_are_hex_sha256(self) -> None:
        manifest = policy_bundle_manifest()
        for path, digest in manifest.items():
            assert len(digest) == 64, f"{path}: expected 64-char digest, got {len(digest)}"
            assert all(c in "0123456789abcdef" for c in digest)

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            compute_policy_bundle_hash(
                ["remora/policy/nonexistent_file.py"],
                repo_root=tmp_path,
            )

    def test_bundle_hash_can_be_used_in_audit_block(self) -> None:
        """Integration: bundle hash can populate AuditBlock.policy_bundle_hash."""
        from remora.governance.envelope import AuditBlock
        bundle_hash = compute_policy_bundle_hash()
        audit = AuditBlock(
            policy_version="RemoraDecisionEngine-v3",
            policy_bundle_hash=bundle_hash,
        )
        assert audit.policy_bundle_hash == bundle_hash
        assert len(audit.policy_bundle_hash) == 64


# ---------------------------------------------------------------------------
# Additional invariant sweep — smoke test for new findings
# ---------------------------------------------------------------------------

class TestInvariantsSweep:
    """Ensure core invariants hold for representative edge-case observations."""

    @pytest.mark.parametrize("obs_kwargs,engine", [
        # Critical risk with all ACCEPT conditions — should not ACCEPT
        ({"risk_tier": "critical", "trust_score": 0.99, "phase": "ordered",
          "temperature": 0.01, "evidence_action": "answer",
          "evidence_confidence": 0.99, "counterfactual_passed": True,
          "schema_valid": True, "action_type": "read"}, _engine_conformal_phase),
        # Adversarial + conformal phase
        ({"adversarial_detected": True, "trust_score": 0.99, "phase": "ordered"}, _engine_conformal_phase),
        # Tainted + conformal phase
        ({"argument_tainted": True, "trust_score": 0.99, "phase": "ordered"}, _engine_conformal_phase),
        # Counterfactual=False + conformal
        ({"counterfactual_passed": False, "trust_score": 0.99, "phase": "ordered"}, _engine_conformal_phase),
        # Contradictions>0 + conformal
        ({"evidence_contradictions": 2, "trust_score": 0.99, "phase": "ordered",
          "evidence_action": None}, _engine_conformal_phase),
    ])
    def test_invariants_hold(
        self, obs_kwargs: dict, engine: RemoraDecisionEngine
    ) -> None:
        obs = _obs(**obs_kwargs)
        report = engine.decide(obs)
        assert_invariants(obs, report)
