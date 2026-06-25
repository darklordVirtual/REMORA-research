# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for new REMORA modules:
  - RemoraAuditChain (governance/audit_chain.py)
  - GovernanceInvariants (policy/invariants.py)
  - PolicyObservation factory methods (policy/observation.py)
  - DecisionEngine.explain() / PolicyTrace (policy/decision_engine.py)
  - New framework adapters: CrewAIActionAdapter, AutoGenActionAdapter, AsyncActionGate
"""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path

import pytest

import remora
from remora import (
    CORE_INVARIANTS,
    ActionGateResult,
    AssessmentBlock,
    AuditBlock,
    AutoGenActionAdapter,
    ChainEntry,
    CrewAIActionAdapter,
    DecisionAction,
    DecisionEnvelope,
    GateBlock,
    InvariantViolationError,
    PolicyObservation,
    PolicyRuleEvaluation,
    PolicyTrace,
    RemoraAuditChain,
    RemoraDecisionEngine,
    RequestBlock,
    assert_invariants,
    check_all_invariants,
    invariant_summary,
)
from remora.adapters.action_gate import AsyncActionGate, AsyncLocalGateway
from remora.adapters.gateway import GatewayResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_obs(**overrides) -> PolicyObservation:
    defaults = dict(
        question="test action",
        phase="ordered",
        trust_score=0.92,
        final_H=0.30,
        final_D=0.08,
        risk_tier="low",
        domain="test",
        action_type="read",
        target_environment="staging",
    )
    defaults.update(overrides)
    return PolicyObservation(**defaults)


def _make_envelope(outcome: str = "accept", request_id: str = "test-req-001") -> DecisionEnvelope:
    return DecisionEnvelope(
        request=RequestBlock(
            request_id=request_id,
            domain="test",
            risk_tier="low",
            proposed_action="noop",
            action_type="read",
            target_environment="staging",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[],
            thermodynamic={"trust_score": 0.9},
            evidence_quality={"required": False},
            policy_triggers=["low_risk_ordered"],
        ),
        gate=GateBlock(
            outcome=outcome,
            blocked_action=None if outcome == "accept" else "noop",
            allowed_next_steps=[],
        ),
        audit=AuditBlock(
            policy_version="test-v1",
            hash="0" * 64,
            previous_hash=None,
            signature=None,
        ),
    )


class _MockGateway:
    """Sync gateway backed by RemoraDecisionEngine."""

    def __init__(self, risk_tier: str = "low") -> None:
        self._engine = RemoraDecisionEngine()
        self._risk_tier = risk_tier
        _tier_params = {
            "low":      dict(phase="ordered",    H=0.30, D=0.08, trust=0.92),
            "medium":   dict(phase="critical",   H=0.70, D=0.25, trust=0.74),
            "high":     dict(phase="critical",   H=1.10, D=0.50, trust=0.55),
            "critical": dict(phase="disordered", H=1.60, D=0.75, trust=0.30),
        }
        self._p = _tier_params[risk_tier]

    def assess_sync(self, question, *, context=None, domain=None, risk_tier=None,
                    action_type=None, target_environment=None) -> GatewayResult:
        tier = risk_tier or self._risk_tier
        obs = PolicyObservation(
            question=question, phase=self._p["phase"],
            trust_score=self._p["trust"], final_H=self._p["H"], final_D=self._p["D"],
            risk_tier=tier, domain=domain, action_type=action_type or "read",
            target_environment=target_environment or "staging",
        )
        report = self._engine.decide(obs)
        action = report.action.value
        h = hashlib.sha256(f"{question}:{action}".encode()).hexdigest()
        return GatewayResult(
            action=action, human_review_required=report.human_review_required,
            evidence_required=report.evidence_required,
            explanation="; ".join(r.value for r in report.reasons),
            confidence=self._p["trust"], risk_estimate=None,
            require_rag=False, refuse_parametric_verdict=False,
            source_of_decision="mock", state_hash=h,
        )


# ===========================================================================
# RemoraAuditChain
# ===========================================================================

class TestRemoraAuditChain:
    def test_empty_chain_verifies(self):
        chain = RemoraAuditChain()
        ok, errors = chain.verify()
        assert ok
        assert errors == []

    def test_append_returns_envelope_with_hash(self):
        chain = RemoraAuditChain()
        env = _make_envelope()
        result = chain.append(env)
        assert result.audit.hash and result.audit.hash != "0" * 64

    def test_hash_chain_links(self):
        chain = RemoraAuditChain()
        e1 = chain.append(_make_envelope(request_id="r1"))
        e2 = chain.append(_make_envelope(request_id="r2"))
        assert e2.audit.previous_hash == e1.audit.hash

    def test_verify_passes_after_multiple_appends(self):
        chain = RemoraAuditChain()
        for i in range(5):
            chain.append(_make_envelope(request_id=f"r{i}"))
        ok, errors = chain.verify()
        assert ok, errors

    def test_summary_counts_entries(self):
        chain = RemoraAuditChain()
        chain.append(_make_envelope())
        chain.append(_make_envelope())
        s = chain.summary()
        assert s["length"] == 2

    def test_hmac_signing(self):
        chain = RemoraAuditChain(secret_key="test-secret")
        env = chain.append(_make_envelope())
        assert env.audit.signature is not None

    def test_export_import_roundtrip(self):
        chain = RemoraAuditChain()
        for i in range(3):
            chain.append(_make_envelope(outcome="accept", request_id=f"r{i}"))
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        chain.export_jsonl(path)
        chain2 = RemoraAuditChain.import_jsonl(path)
        assert len(chain2._entries) == 3
        ok, errors = chain2.verify()
        assert ok, errors

    def test_len_and_iter(self):
        chain = RemoraAuditChain()
        chain.append(_make_envelope())
        chain.append(_make_envelope())
        assert len(chain) == 2
        entries = list(chain)
        assert all(isinstance(e, ChainEntry) for e in entries)

    def test_chain_entry_is_frozen(self):
        chain = RemoraAuditChain()
        chain.append(_make_envelope())
        entry = list(chain)[0]
        with pytest.raises((AttributeError, TypeError)):
            entry.hash = "tampered"  # type: ignore[misc]


# ===========================================================================
# GovernanceInvariants
# ===========================================================================

class TestGovernanceInvariants:
    def test_low_risk_ordered_no_violations(self):
        obs = _make_obs()
        engine = RemoraDecisionEngine()
        report = engine.decide(obs)
        results = check_all_invariants(obs, report)
        violations = [r for r in results if not r.passed]
        assert violations == [], [r.invariant_name for r in violations]

    def test_adversarial_always_escalated(self):
        obs = _make_obs(adversarial_detected=True)
        engine = RemoraDecisionEngine()
        report = engine.decide(obs)
        assert report.action == DecisionAction.ESCALATE
        # assert_invariants must not raise
        assert_invariants(obs, report)

    def test_critical_tier_never_autonomously_accepted(self):
        obs = _make_obs(risk_tier="critical", phase="disordered",
                        final_H=1.6, final_D=0.8, trust_score=0.3)
        engine = RemoraDecisionEngine()
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_assert_invariants_raises_on_violation(self):
        """Manually construct a violating (obs, report) pair."""
        from remora.policy.report import DecisionReport
        obs = _make_obs(adversarial_detected=True)  # adversarial should escalate
        # Forge a report that ACCEPT despite adversarial — should violate
        bad_report = DecisionReport(
            action=DecisionAction.ACCEPT,
            reasons=frozenset(),
            human_review_required=False,
            evidence_required=False,
            explanation="forced accept",
            coverage_policy="",
            source_of_decision="test",
            policy_version="test",
            risk_estimate=None,
            confidence=None,
            audit_root=None,
            raw_observation={},
        )
        with pytest.raises(InvariantViolationError):
            assert_invariants(obs, bad_report)

    def test_invariant_summary_returns_dict(self):
        obs = _make_obs()
        engine = RemoraDecisionEngine()
        report = engine.decide(obs)
        summary = invariant_summary(obs, report)
        assert isinstance(summary, dict)
        assert all(isinstance(v, bool) for v in summary.values())
        assert len(summary) == len(CORE_INVARIANTS)

    def test_core_invariants_tuple_non_empty(self):
        assert len(CORE_INVARIANTS) >= 8


# ===========================================================================
# PolicyObservation factory methods
# ===========================================================================

class TestPolicyObservationFactories:
    def test_from_tool_call_basic(self):
        obs = PolicyObservation.from_tool_call(
            name="send_email",
            arguments={"to": "user@example.com", "subject": "hello"},
            risk_tier="medium",
            domain="comms",
            action_type="write",
            trust_score=0.75,
            phase="critical",
            final_H=0.70,
            final_D=0.25,
        )
        assert "send_email" in obs.question
        assert obs.risk_tier == "medium"
        assert obs.action_type == "write"
        assert obs.trust_score == 0.75
        assert obs.phase == "critical"

    def test_from_tool_call_default_action_type(self):
        obs = PolicyObservation.from_tool_call(
            name="read_file",
            arguments={"path": "/etc/passwd"},
        )
        assert obs.action_type == "tool_call"
        assert obs.target_environment == "prod"

    def test_from_tool_call_args_truncated(self):
        long_args = {"data": "x" * 500}
        obs = PolicyObservation.from_tool_call(name="big_call", arguments=long_args)
        assert len(obs.question) < 300  # truncated at 120 chars of args

    def test_from_json_record_full(self):
        record = {
            "question": "delete_user(u-123)",
            "phase": "disordered",
            "trust_score": "0.25",
            "final_H": "1.55",
            "final_D": "0.72",
            "risk_tier": "critical",
            "domain": "user_mgmt",
            "action_type": "destructive_write",
            "target_environment": "prod",
            "adversarial_detected": "false",
            "oracle_failures": "1",
            "valid_oracle_count": "3",
        }
        obs = PolicyObservation.from_json_record(record)
        assert obs.phase == "disordered"
        assert obs.trust_score == pytest.approx(0.25)
        assert obs.final_H == pytest.approx(1.55)
        assert obs.risk_tier == "critical"
        assert obs.adversarial_detected is False
        assert obs.oracle_failures == 1

    def test_from_json_record_fallback_question_keys(self):
        obs = PolicyObservation.from_json_record({"proposed_action": "deploy"})
        assert obs.question == "deploy"
        obs2 = PolicyObservation.from_json_record({"action": "rollback"})
        assert obs2.question == "rollback"
        obs3 = PolicyObservation.from_json_record({})
        assert obs3.question == "unspecified_action"

    def test_from_json_record_bool_variants(self):
        for truthy in ("true", "True", "1", "yes"):
            obs = PolicyObservation.from_json_record({"adversarial_detected": truthy})
            assert obs.adversarial_detected is True
        for falsy in ("false", "False", "0", "no"):
            obs = PolicyObservation.from_json_record({"adversarial_detected": falsy})
            assert obs.adversarial_detected is False

    def test_minimal_factory(self):
        obs = PolicyObservation.minimal(
            "Backup database",
            risk_tier="low",
            domain="data",
        )
        assert obs.question == "Backup database"
        assert obs.risk_tier == "low"
        assert obs.phase is None
        assert obs.trust_score is None
        assert obs.target_environment == "prod"

    def test_observation_is_frozen(self):
        obs = PolicyObservation.minimal("test")
        with pytest.raises((AttributeError, TypeError)):
            obs.question = "mutated"  # type: ignore[misc]


# ===========================================================================
# PolicyTrace / explain()
# ===========================================================================

class TestExplain:
    def test_explain_returns_policy_trace(self):
        engine = RemoraDecisionEngine()
        obs = _make_obs()
        trace = engine.explain(obs)
        assert isinstance(trace, PolicyTrace)

    def test_explain_decision_path_nonempty(self):
        engine = RemoraDecisionEngine()
        obs = _make_obs()
        trace = engine.explain(obs)
        assert "→" in trace.decision_path
        assert trace.action

    def test_explain_rule_evaluations_are_evaluations(self):
        engine = RemoraDecisionEngine()
        obs = _make_obs()
        trace = engine.explain(obs)
        assert len(trace.rule_evaluations) > 0
        for r in trace.rule_evaluations:
            assert isinstance(r, PolicyRuleEvaluation)
            assert r.rule
            assert r.condition
            assert isinstance(r.triggered, bool)

    def test_explain_triggered_rules_consistent_with_decision(self):
        engine = RemoraDecisionEngine()
        # adversarial → always escalate
        obs = _make_obs(adversarial_detected=True)
        trace = engine.explain(obs)
        assert trace.action == "escalate"
        triggered = [r.rule for r in trace.rule_evaluations if r.triggered]
        assert "adversarial_firewall" in triggered

    def test_explain_observation_summary_contains_key_fields(self):
        engine = RemoraDecisionEngine()
        obs = _make_obs(risk_tier="high", phase="critical")
        trace = engine.explain(obs)
        assert "risk_tier" in trace.observation_summary
        assert trace.observation_summary["risk_tier"] == "high"

    def test_explain_policy_version_set(self):
        engine = RemoraDecisionEngine()
        obs = _make_obs()
        trace = engine.explain(obs)
        assert "RemoraDecisionEngine" in trace.policy_version

    def test_explain_matches_decide(self):
        """explain() and decide() must agree on the action."""
        engine = RemoraDecisionEngine()
        for obs in [
            _make_obs(risk_tier="low"),
            _make_obs(risk_tier="critical", phase="disordered", final_H=1.6, final_D=0.8, trust_score=0.3),
            _make_obs(adversarial_detected=True),
            _make_obs(evidence_contradictions=2),
        ]:
            report = engine.decide(obs)
            trace = engine.explain(obs)
            assert trace.action == (
                report.action.value if hasattr(report.action, "value") else str(report.action)
            ), f"Mismatch for obs={obs.question}: decide={report.action} explain={trace.action}"


# ===========================================================================
# New framework adapters
# ===========================================================================

class TestCrewAIAdapter:
    def test_intercept_tool_low_risk_accepted(self):
        adapter = CrewAIActionAdapter(gateway=_MockGateway("low"))
        result = adapter.intercept_tool(
            "web_search", {"query": "test"},
            domain="research", risk_tier="low", action_type="read",
        )
        assert isinstance(result, ActionGateResult)
        assert result.should_execute
        assert result.envelope.gate.outcome == "accept"

    def test_intercept_tool_critical_blocked(self):
        adapter = CrewAIActionAdapter(gateway=_MockGateway("critical"))
        result = adapter.intercept_tool(
            "delete_all_records", {"confirm": True},
            domain="data", risk_tier="critical", action_type="destructive_write",
        )
        assert not result.should_execute

    def test_intercept_tool_string_input(self):
        adapter = CrewAIActionAdapter(gateway=_MockGateway("low"))
        result = adapter.intercept_tool("search", "what is REMORA?")
        assert isinstance(result, ActionGateResult)

    def test_envelope_structure(self):
        adapter = CrewAIActionAdapter(gateway=_MockGateway("low"))
        result = adapter.intercept_tool("noop", {})
        env = result.envelope
        assert env.request.request_id
        assert env.audit.hash
        assert env.gate.outcome in ("accept", "verify", "abstain", "escalate")


class TestAutoGenAdapter:
    def test_intercept_function_low_risk(self):
        adapter = AutoGenActionAdapter(gateway=_MockGateway("low"))
        result = adapter.intercept_function_call(
            "read_file", {"path": "/docs/readme.md"},
            domain="filesystem", risk_tier="low", action_type="read",
        )
        assert result.should_execute

    def test_intercept_function_critical_blocked(self):
        adapter = AutoGenActionAdapter(gateway=_MockGateway("critical"))
        result = adapter.intercept_function_call(
            "run_bash", {"command": "rm -rf /"},
            domain="exec", risk_tier="critical", action_type="execute",
        )
        assert not result.should_execute

    def test_shadow_replay_record(self):
        adapter = AutoGenActionAdapter(gateway=_MockGateway("low"))
        result = adapter.intercept_function_call("noop", {})
        record = adapter.to_shadow_replay_record(result.envelope, unsafe=False)
        assert "question" in record
        assert "risk_tier" in record
        assert isinstance(record["unsafe"], bool)


class TestAsyncGateway:
    def test_async_gateway_wraps_sync(self):
        sync_gw = _MockGateway("low")
        async_gw = AsyncLocalGateway(sync_gateway=sync_gw)
        # assess_sync still works
        result = async_gw.assess_sync("test action", risk_tier="low")
        assert result.action == "accept"

    def test_async_gateway_assess_coroutine(self):
        sync_gw = _MockGateway("low")
        async_gw = AsyncLocalGateway(sync_gateway=sync_gw)

        async def _run():
            return await async_gw.assess("test action", risk_tier="low")

        result = asyncio.run(_run())
        assert result.action == "accept"

    def test_async_action_gate_intercept(self):
        sync_gw = _MockGateway("low")
        async_gw = AsyncLocalGateway(sync_gateway=sync_gw)
        gate = AsyncActionGate(gateway=async_gw)

        async def _run():
            return await gate.intercept(
                action_name="read_doc",
                action_args={"id": "123"},
                proposed_by="agent",
                domain="docs",
                risk_tier="low",
                action_type="read",
                target_environment="staging",
                context={},
            )

        result = asyncio.run(_run())
        assert isinstance(result, ActionGateResult)
        assert result.should_execute

    def test_async_gate_critical_blocked(self):
        sync_gw = _MockGateway("critical")
        async_gw = AsyncLocalGateway(sync_gateway=sync_gw)
        gate = AsyncActionGate(gateway=async_gw)

        async def _run():
            return await gate.intercept(
                action_name="deploy",
                action_args={"env": "prod"},
                proposed_by="agent",
                domain="infra",
                risk_tier="critical",
                action_type="deploy",
                target_environment="prod",
                context={},
            )

        result = asyncio.run(_run())
        assert not result.should_execute


# ===========================================================================
# Public API completeness
# ===========================================================================

class TestPublicAPI:
    REQUIRED_SYMBOLS = [
        "RemoraDecisionEngine", "PolicyObservation",
        "DecisionAction", "DecisionReport",
        "PolicyTrace", "PolicyRuleEvaluation",
        "DecisionEnvelope", "RequestBlock", "AssessmentBlock", "GateBlock", "AuditBlock",
        "RemoraAuditChain", "ChainEntry",
        "CORE_INVARIANTS", "InvariantViolationError",
        "check_all_invariants", "assert_invariants", "invariant_summary",
        "replay_action_log", "GovernanceDeltaReport", "ReplayResult",
        "LangGraphActionAdapter", "OpenAIToolCallingAdapter",
        "CrewAIActionAdapter", "AutoGenActionAdapter",
        "AsyncLocalGateway", "ActionGateResult",
        "GatewayResult", "LocalGateway", "HttpGateway",
        "get_remora_tracer",
    ]

    def test_all_required_symbols_exported(self):
        missing = [s for s in self.REQUIRED_SYMBOLS if not hasattr(remora, s)]
        assert missing == [], f"Missing from remora.__init__: {missing}"

    def test_py_typed_marker_exists(self):
        pkg_dir = Path(remora.__file__).parent
        assert (pkg_dir / "py.typed").exists(), "py.typed marker not found"

    def test_version_string_set(self):
        assert remora.__version__
        assert "." in remora.__version__
