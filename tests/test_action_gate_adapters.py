from __future__ import annotations

from remora.adapters.action_gate import (
    LangGraphActionAdapter,
    OpenAIToolCallingAdapter,
)
from remora.adapters.gateway import GatewayResult


class _FakeGateway:
    def assess_sync(self, question: str, **kwargs) -> GatewayResult:  # noqa: ARG002
        return GatewayResult(
            action="verify",
            human_review_required=True,
            evidence_required=True,
            explanation="High-risk action requires verification",
            confidence=0.71,
            risk_estimate=0.62,
            require_rag=False,
            refuse_parametric_verdict=False,
            source_of_decision="rule_engine",
            state_hash="abc123",
        )


def test_langgraph_adapter_intercept_returns_envelope() -> None:
    adapter = LangGraphActionAdapter(gateway=_FakeGateway())
    out = adapter.intercept(
        action_name="deploy_production",
        action_args={"version": "2025.10"},
        proposed_by="planner",
        domain="devops",
        risk_tier="high",
        action_type="deploy",
        target_environment="production",
        context={"prompt": "Deploy now?"},
    )

    assert out.envelope.gate.outcome == "verify"
    assert out.should_execute is False
    assert out.envelope.request.proposed_action == "deploy_production"


def test_openai_adapter_intercept_tool_call() -> None:
    adapter = OpenAIToolCallingAdapter(gateway=_FakeGateway())
    out = adapter.intercept_tool_call(
        {"name": "rotate_keys", "arguments": {"scope": "cluster"}},
        proposed_by="assistant",
        domain="security",
        risk_tier="critical",
        action_type="security_change",
        target_environment="prod",
        context={"prompt": "Rotate all cluster keys"},
    )

    replay = adapter.to_shadow_replay_record(out.envelope, unsafe=True)
    assert out.envelope.request.proposed_action == "rotate_keys"
    assert replay["unsafe"] is True
    assert replay["risk_tier"] == "critical"


class _AcceptGateway:
    def assess_sync(self, question: str, **kwargs) -> GatewayResult:  # noqa: ARG002
        return GatewayResult(
            action="accept",
            human_review_required=False,
            evidence_required=False,
            explanation="Low-risk action accepted",
            confidence=0.95,
            risk_estimate=0.05,
            require_rag=False,
            refuse_parametric_verdict=False,
            source_of_decision="rule_engine",
            state_hash="ok456",
        )


def _intercept(adapter: LangGraphActionAdapter, **overrides):
    params = dict(
        action_name="restart_service",
        action_args={"service": "billing-db"},
        proposed_by="ops-agent",
        domain="infrastructure",
        risk_tier="high",
        action_type="write",
        target_environment="production",
        context={},
    )
    params.update(overrides)
    return adapter.intercept(**params)


def test_verify_outcome_sets_blocked_action_and_refuses_execution() -> None:
    """VERIFY means should_execute=False, so blocked_action must name the action.

    Regression: blocked_action was only set for abstain/escalate, making
    envelope exports misleading for VERIFY outcomes that are equally
    unexecutable (2026-07-20 review, adapter audit contract).
    """
    out = _intercept(LangGraphActionAdapter(gateway=_FakeGateway()))
    assert out.envelope.gate.outcome == "verify"
    assert out.should_execute is False
    assert out.envelope.gate.blocked_action == "restart_service"


def test_accept_outcome_has_no_blocked_action() -> None:
    out = _intercept(LangGraphActionAdapter(gateway=_AcceptGateway()))
    assert out.envelope.gate.outcome == "accept"
    assert out.should_execute is True
    assert out.envelope.gate.blocked_action is None


def test_request_id_binds_full_governance_context() -> None:
    """Identical tool calls in different governance contexts get distinct ids.

    Regression: the request_id hash omitted domain/risk_tier/action_type/
    target_environment, so the same action assessed in staging and production
    (or reclassified to another risk tier) collided on one request_id.
    """
    adapter = LangGraphActionAdapter(gateway=_FakeGateway())
    prod = _intercept(adapter)
    staging = _intercept(adapter, target_environment="staging")
    low_risk = _intercept(adapter, risk_tier="low")
    other_domain = _intercept(adapter, domain="finance")

    ids = {
        prod.envelope.request.request_id,
        staging.envelope.request.request_id,
        low_risk.envelope.request.request_id,
        other_domain.envelope.request.request_id,
    }
    assert len(ids) == 4


def test_audit_tool_args_hash_binds_full_canonical_arguments() -> None:
    """audit.tool_args_hash must be the canonical full-args hash, so the
    enforcement point can recompute and refuse on argument mutation."""
    from remora.policy.observation import canonical_tool_call_hash

    adapter = LangGraphActionAdapter(gateway=_FakeGateway())
    out = _intercept(adapter, action_args={"service": "billing-db", "force": True})
    expected = canonical_tool_call_hash(
        name="restart_service",
        arguments={"service": "billing-db", "force": True},
        tenant="",
        target="production",
    )
    assert out.envelope.audit.tool_args_hash == expected

    tenanted = _intercept(
        adapter,
        action_args={"service": "billing-db", "force": True},
        context={"tenant_id": "acme"},
    )
    assert tenanted.envelope.audit.tool_args_hash == canonical_tool_call_hash(
        name="restart_service",
        arguments={"service": "billing-db", "force": True},
        tenant="acme",
        target="production",
    )
    assert tenanted.envelope.audit.tool_args_hash != expected
