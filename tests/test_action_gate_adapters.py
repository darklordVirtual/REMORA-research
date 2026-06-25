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
