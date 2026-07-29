# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Direct unit tests for remora.reporting (report/envelope assembly).

reporting.py's module docstring promises that "every runtime dependency ...
is injected as a parameter, so the assembly logic can be unit-tested without
instantiating an oracle swarm." These tests exercise exactly that path:
``build_report`` / ``_build_envelope`` / ``state_hash`` are driven from a
hand-built ``RemoraState`` plus injected stubs, with NO ``Remora`` engine
constructed. This realizes the documented testability and gives the two
modules extracted in the 2026-07-29 refactor (reporting.py, state.py)
dedicated coverage instead of transitive-only coverage via ``Remora.report``.

Note: ``build_report`` / ``_build_envelope`` are imported from
``remora.reporting`` specifically — a different, unrelated ``build_envelope``
lives in ``remora.assurance.envelope`` and builds an AssuranceEnvelope.
"""
from __future__ import annotations

import types

from remora.core import OracleResponse
from remora.evidence.provider import OracleProxyEvidenceProvider
from remora.lyapunov import LyapunovController, LyapunovParams
from remora.reporting import _build_envelope, build_report, state_hash
from remora.state import RemoraState


def _state(question: str = "test?", **kw) -> RemoraState:
    return RemoraState(
        question=question,
        controller=LyapunovController.init(LyapunovParams()),
        **kw,
    )


def _genome_off():
    """Genome stub with all optional assurance/graph features disabled.

    build_report reads only these three feature flags off the genome (via
    getattr), so a namespace with them False keeps the test deterministic and
    free of assurance-trace / claim-graph dependencies."""
    return types.SimpleNamespace(
        enable_zkp_assurance=False,
        enable_assurance_trace=False,
        enable_semantic_claim_graph=False,
    )


def test_build_report_without_engine_returns_policy_decision():
    """The documented 'no oracle swarm' path: assemble a full report from an
    empty state and injected deps, with no Remora engine."""
    state = _state()
    rep = build_report(
        state,
        genome=_genome_off(),
        evidence_provider=OracleProxyEvidenceProvider(),
        detect_adversarial=lambda q: False,
    )
    assert "policy_decision" in rep
    pd = rep["policy_decision"]
    for key in ("action", "reasons", "confidence", "human_review_required", "policy_version"):
        assert key in pd, f"policy_decision missing {key}"
    assert "policy_observation" in rep
    assert "envelope" in rep
    assert rep["question"] == "test?"
    assert rep["state_hash"]  # non-empty digest


def test_adversarial_cache_is_honored_else_computed_on_demand():
    """detect_adversarial must run only when state.adversarial_detected is None
    (state built outside run()); a cached bool short-circuits it."""
    seen: list[str] = []

    def detect(q: str) -> bool:
        seen.append(q)
        return True

    cached = _state(question="cached")
    cached.adversarial_detected = False  # not None -> cache honored
    build_report(
        cached,
        genome=_genome_off(),
        evidence_provider=OracleProxyEvidenceProvider(),
        detect_adversarial=detect,
    )
    assert seen == [], "cached adversarial_detected must short-circuit detect_adversarial"

    fresh = _state(question="fresh")  # adversarial_detected defaults to None
    build_report(
        fresh,
        genome=_genome_off(),
        evidence_provider=OracleProxyEvidenceProvider(),
        detect_adversarial=detect,
    )
    assert seen == ["fresh"], "None adversarial_detected must invoke detect_adversarial once"


def test_state_hash_is_deterministic_and_content_addressed():
    state = _state(question="hash me")
    assert state_hash(state) == state_hash(state)
    assert state_hash(_state("a")) != state_hash(_state("b"))


def test_envelope_blocks_action_iff_outcome_is_not_accept():
    """_build_envelope must set gate.blocked_action for any non-accept outcome
    (fail-closed) and leave it None for accept."""
    state = _state(question="block me")
    rep = build_report(
        state,
        genome=_genome_off(),
        evidence_provider=OracleProxyEvidenceProvider(),
        detect_adversarial=lambda q: False,
    )
    env = rep["envelope"]
    if env.gate.outcome != "accept":
        assert env.gate.blocked_action == "block me"[:200]
    else:
        assert env.gate.blocked_action is None


def test_retrieval_first_provider_falls_back_on_exception():
    """For high/critical risk with a retrieval provider, a retrieval failure
    must fall back to the oracle-proxy provider and record the fallback."""
    resp = OracleResponse(
        provider="o1",
        raw_text='{"claim": "c", "answer": true, "confidence": 0.8}',
        extracted={"claim": "c", "answer": True, "confidence": 0.8},
    )
    state = _state(question="critical?", risk_tier="critical")
    state.oracle_log = [resp]

    class _RaisingProvider:
        def fetch(self, **kwargs):
            raise RuntimeError("retrieval backend down")

    rep = build_report(
        state,
        genome=_genome_off(),
        evidence_provider=OracleProxyEvidenceProvider(mean_rho_fn=lambda providers: 0.5),
        retrieval_evidence_provider=_RaisingProvider(),
        detect_adversarial=lambda q: False,
    )
    assert any(
        "retrieval failed" in d and "fallback oracle_proxy" in d for d in state.decisions
    ), f"expected retrieval-fallback record in decisions, got {state.decisions}"
    # The fallback still produces a complete decision.
    assert "policy_decision" in rep
    assert rep["policy_decision"]["action"]


def test_build_envelope_can_be_called_directly():
    """_build_envelope is callable in isolation given obs/decision/rep — the
    same objects build_report produces — without any Remora engine."""
    state = _state(question="direct envelope")
    rep = build_report(
        state,
        genome=_genome_off(),
        evidence_provider=OracleProxyEvidenceProvider(),
        detect_adversarial=lambda q: False,
    )
    obs = rep["policy_observation"]
    # Re-derive a decision object the same way build_report did.
    from remora.policy import RemoraDecisionEngine

    decision = RemoraDecisionEngine().decide(obs)
    env = _build_envelope(state, obs, decision, rep)
    assert env.request.proposed_action == "direct envelope"[:200]
    assert env.audit.policy_version == decision.policy_version
