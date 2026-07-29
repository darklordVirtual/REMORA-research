# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Direct in-process tests for remora.reporting.build_decision_envelope.

The public helper assembles a canonical DecisionEnvelope from a bare
(observation, decision) pair (used by the CLI, deterministic tests, tooling)
without a full oracle-backed engine run. Previously it was exercised only
through the CLI subprocess; these tests pin the audit contract directly.
"""
from __future__ import annotations

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.reporting import build_decision_envelope


def _envelope(**overrides):
    obs = PolicyObservation.from_tool_call(
        name=overrides.pop("name", "drop_database"),
        arguments=overrides.pop("arguments", {"db": "prod-main"}),
        risk_tier=overrides.pop("risk_tier", "critical"),
        action_type=overrides.pop("action_type", "destructive_write"),
        target_environment=overrides.pop("target_environment", "prod"),
        **overrides,
    )
    decision = RemoraDecisionEngine().decide(obs)
    return build_decision_envelope(obs, decision, question=obs.question), decision


def test_envelope_has_all_canonical_blocks():
    env, decision = _envelope()
    d = env.to_dict()
    for block in ("request", "assessment", "gate", "audit"):
        assert block in d, f"missing {block}"
    assert d["gate"]["outcome"] == decision.action.value
    assert d["audit"]["hash"]
    assert d["request"]["risk_tier"] == "critical"


def test_envelope_blocks_action_for_non_accept_outcome():
    env, _ = _envelope()  # critical destructive -> escalate
    d = env.to_dict()
    assert d["gate"]["outcome"] != "accept"
    assert d["gate"]["blocked_action"]


def test_envelope_audit_hash_is_deterministic():
    e1, _ = _envelope()
    e2, _ = _envelope()
    assert e1.to_dict()["audit"]["hash"] == e2.to_dict()["audit"]["hash"]


def test_envelope_accept_path_does_not_block():
    env, decision = _envelope(
        name="read_file", arguments={"path": "/etc/app/config.yaml"},
        risk_tier="low", action_type="read", target_environment="staging",
        trust_score=0.9, phase="ordered",
    )
    d = env.to_dict()
    assert decision.action.value == "accept"
    assert d["gate"]["blocked_action"] is None
