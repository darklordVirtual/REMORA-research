"""Bind docs/07-api-reference.md to the actual source (hostile-review P0-3).

The previous version of the API reference documented five MCP tools and six
APIs that did not exist. These tests verify, by introspection against the
real objects, every load-bearing statement the rewritten document makes —
so the document cannot drift from the code without CI failing.
"""
from __future__ import annotations

import dataclasses
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "07-api-reference.md"
DOC_TEXT = DOC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# MCP tools: every tool named in the doc's table must be registered in the
# server, and every registered tool must be documented.
# ---------------------------------------------------------------------------

def _doc_mcp_tools() -> set[str]:
    section = DOC_TEXT.split("## MCP tools", 1)[1].split("\n---\n", 1)[0]
    return set(re.findall(r"`((?:remora|agent)_[a-z_]+)`", section))


def _server_mcp_tools() -> set[str]:
    src = (ROOT / "servers" / "mcp_remora.py").read_text(encoding="utf-8")
    return set(re.findall(r'"((?:remora|agent)_[a-z_]+)"', src))


def test_documented_mcp_tools_exist_in_server() -> None:
    missing = _doc_mcp_tools() - _server_mcp_tools()
    assert not missing, f"doc lists MCP tools not registered in server: {missing}"


def test_all_server_mcp_tools_are_documented() -> None:
    undocumented = _server_mcp_tools() - _doc_mcp_tools()
    assert not undocumented, f"server tools missing from doc: {undocumented}"


def test_doc_tool_count_matches() -> None:
    n = len(_server_mcp_tools())
    assert f"exposes {n} tools" in DOC_TEXT


# ---------------------------------------------------------------------------
# Decision engine: return type, constructor params, report fields
# ---------------------------------------------------------------------------

def test_decide_returns_decision_report() -> None:
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.report import DecisionReport
    from remora.policy import PolicyObservation

    report = RemoraDecisionEngine().decide(PolicyObservation(question="api-doc probe"))
    assert isinstance(report, DecisionReport)
    assert "-> DecisionReport" in DOC_TEXT or "**`DecisionReport`**" in DOC_TEXT
    assert "DecisionEnvelope`\n" not in DOC_TEXT.split("## RemoraDecisionEngine")[1].split("---")[0], \
        "engine section must not claim decide() returns DecisionEnvelope"


def test_documented_report_fields_exist() -> None:
    from remora.policy.report import DecisionReport

    actual = {f.name for f in dataclasses.fields(DecisionReport)}
    section = DOC_TEXT.split("`decide()` returns", 1)[1].split("Hard-block", 1)[0]
    documented = set(re.findall(r"`([a-z_]+)`", section))
    documented -= {"remora", "decisionreport"}
    unknown = {d for d in documented if d not in actual and "/" not in d}
    assert not unknown, f"doc lists DecisionReport fields that don't exist: {unknown}"
    assert {"action", "reasons", "credal", "fallback_used"} <= documented


def test_engine_constructor_params_match() -> None:
    from remora.policy.decision_engine import RemoraDecisionEngine

    params = set(inspect.signature(RemoraDecisionEngine.__init__).parameters) - {"self"}
    for p in ("temperature_threshold", "conformal_trust_threshold",
              "conformal_phase_thresholds"):
        assert p in params
        assert p in DOC_TEXT


# ---------------------------------------------------------------------------
# PolicyObservation: every doc-listed field must exist; count must match
# ---------------------------------------------------------------------------

def test_documented_observation_fields_exist() -> None:
    from remora.policy import PolicyObservation

    actual = {f.name for f in dataclasses.fields(PolicyObservation)}
    section = DOC_TEXT.split("## PolicyObservation", 1)[1].split("---", 1)[0]
    documented = set(re.findall(r"`([a-z_0-9]+)`", section))
    documented -= {"question", "from_json_record", "none", "policyobservation"}
    documented.add("question")
    unknown = documented - actual - {"from_json_record"}
    assert not unknown, f"doc lists PolicyObservation fields that don't exist: {unknown}"


def test_observation_field_count_matches() -> None:
    from remora.policy import PolicyObservation

    n = len(dataclasses.fields(PolicyObservation))
    assert f"{n} fields" in DOC_TEXT


# ---------------------------------------------------------------------------
# Oracle ABC / OracleResponse
# ---------------------------------------------------------------------------

def test_oracle_response_fields_match() -> None:
    from remora.core import OracleResponse

    actual = {f.name for f in dataclasses.fields(OracleResponse)}
    assert actual == {"provider", "raw_text", "extracted", "cost_usd",
                      "latency_ms", "error"}
    for field in actual:
        assert field in DOC_TEXT
    # The previously documented phantom fields must not reappear
    for phantom in ("normalized", '"answer"'):
        assert phantom not in DOC_TEXT


def test_oracle_ask_takes_prompt_only() -> None:
    from remora.core import Oracle

    params = list(inspect.signature(Oracle.ask).parameters)
    assert params == ["self", "prompt"]
    assert "ask(self, prompt: str, **kwargs)" not in DOC_TEXT


def test_build_recommended_swarm_location() -> None:
    from remora.oracles.factory import build_recommended_swarm  # noqa: F401
    assert "remora/oracles/factory.py" in DOC_TEXT


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def test_action_gate_result_fields() -> None:
    from remora.adapters.action_gate import ActionGateResult

    actual = {f.name for f in dataclasses.fields(ActionGateResult)}
    assert actual == {"envelope", "should_execute"}
    assert "should_execute" in DOC_TEXT
    # Phantom fields from the old doc must not reappear
    adapters_section = DOC_TEXT.split("## Adapters", 1)[1].split("## Enforcement", 1)[0]
    assert "allowed:" not in adapters_section


def test_adapters_use_gateway_and_intercept() -> None:
    from remora.adapters.action_gate import (
        LangGraphActionAdapter,
        OpenAIToolCallingAdapter,
    )
    from remora.adapters.gateway import LocalGateway

    assert "gateway" in inspect.signature(LangGraphActionAdapter.__init__).parameters
    assert hasattr(LangGraphActionAdapter, "intercept")
    assert hasattr(OpenAIToolCallingAdapter, "intercept_tool_call")
    assert hasattr(LocalGateway, "assess_sync")
    assert not hasattr(LangGraphActionAdapter, "gate")
    assert "LocalGateway(engine)" in DOC_TEXT
    assert "adapter.gate(" not in DOC_TEXT
    # The phantom gateway class from the old docstrings must not reappear
    src = (ROOT / "remora" / "adapters" / "action_gate.py").read_text(encoding="utf-8")
    assert "DirectPolicyGateway" not in src
    assert "DirectPolicyGateway" not in DOC_TEXT


# ---------------------------------------------------------------------------
# Safety + envelope + enforcement
# ---------------------------------------------------------------------------

def test_detect_adversarial_returns_bool() -> None:
    from remora.safety.adversarial import detect_adversarial

    assert detect_adversarial("hello world") in (True, False)
    assert "AdversarialFlag" not in DOC_TEXT


def test_envelope_blocks_match() -> None:
    from remora.governance.envelope import DecisionEnvelope

    actual = {f.name for f in dataclasses.fields(DecisionEnvelope)}
    expected = {"request", "assessment", "gate", "reviewer_context",
                "follow_up", "history", "policy_learning", "audit",
                "causal_explanation"}
    assert actual == expected
    for block in expected:
        assert f"`{block}`" in DOC_TEXT


def test_enforcement_api_matches() -> None:
    from remora.enforcement import EnforcementGate, PolicyDecisionToken

    issue_params = set(inspect.signature(PolicyDecisionToken.issue).parameters)
    assert {"action", "observation_hash", "request_id", "issued_at",
            "expires_at"} <= issue_params
    assert hasattr(EnforcementGate, "check") and hasattr(EnforcementGate, "enforce")
    assert "Integration status" in DOC_TEXT or "Integration status:" in DOC_TEXT
