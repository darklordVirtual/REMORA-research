from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.policy import DecisionAction, PolicyObservation, RemoraDecisionEngine


_FIXTURE = Path(__file__).parent / "fixtures" / "policy_curated_cases.json"


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text())


_CURATED_CASES = _load_cases()


@pytest.mark.parametrize("case", _CURATED_CASES, ids=[c["name"] for c in _CURATED_CASES])
def test_policy_curated_cases(case: dict) -> None:
    """Curated scenario suite with explicit expected outcomes.

    These cases are hand-picked enterprise/governance scenarios meant to catch
    regressions in hard-block precedence and acceptance semantics.
    """
    engine_kwargs = case.get("engine", {})
    engine = RemoraDecisionEngine(**engine_kwargs)
    obs = PolicyObservation(**case["observation"])

    report = engine.decide(obs)

    assert report.action == DecisionAction(case["expected_action"])
    assert report.human_review_required is case["expected_human_review_required"]
    assert report.evidence_required is case["expected_evidence_required"]

    reasons = {r.value for r in report.reasons}
    expected_any = set(case.get("required_reasons_any", []))
    if expected_any:
        assert reasons & expected_any, (
            f"Expected one of {sorted(expected_any)} in reasons={sorted(reasons)}"
        )


def test_policy_curated_matrix_invariants_large_scope() -> None:
    """Large curated matrix over policy inputs.

    We intentionally sweep many realistic combinations to ensure safety
    invariants remain true under broad input variation.
    """
    engine = RemoraDecisionEngine()

    phases = ["ordered", "critical", "disordered", None]
    risk_tiers = ["low", "medium", "high", "critical", None]
    trust_scores = [0.05, 0.3, 0.6, 0.85, None]
    evidence_actions = [None, "answer", "evidence_accept"]
    contradiction_values = [0, 1]
    counterfactuals = [None, True, False]
    adversarial_flags = [False, True]
    refuse_flags = [False, True]
    shifts = [False, True]

    seen = 0

    for phase in phases:
        for risk in risk_tiers:
            for trust in trust_scores:
                for evidence_action in evidence_actions:
                    for contradictions in contradiction_values:
                        for counterfactual_passed in counterfactuals:
                            for adversarial in adversarial_flags:
                                for refuse_parametric in refuse_flags:
                                    for distribution_shift in shifts:
                                        # Keep runtime practical while still broad:
                                        # skip combos that are semantically impossible/noisy.
                                        if contradictions > 0 and evidence_action == "answer":
                                            continue
                                        if phase == "disordered" and trust == 0.85 and evidence_action == "answer":
                                            # low-value duplicate region in matrix
                                            continue

                                        obs = PolicyObservation(
                                            question="curated matrix action",
                                            phase=phase,
                                            risk_tier=risk,
                                            trust_score=trust,
                                            evidence_action=evidence_action,
                                            evidence_confidence=0.8 if evidence_action else None,
                                            evidence_contradictions=contradictions,
                                            counterfactual_passed=counterfactual_passed,
                                            adversarial_detected=adversarial,
                                            refuse_parametric_verdict=refuse_parametric,
                                            distribution_shift_detected=distribution_shift,
                                        )
                                        report = engine.decide(obs)
                                        seen += 1

                                        # Invariant A: adversarial always escalates
                                        if adversarial:
                                            assert report.action == DecisionAction.ESCALATE

                                        # Invariant B: counterfactual failure always escalates
                                        if counterfactual_passed is False:
                                            assert report.action == DecisionAction.ESCALATE

                                        # Invariant C: critical risk never autonomously accepts
                                        if risk == "critical":
                                            assert report.action != DecisionAction.ACCEPT
                                            assert report.human_review_required is True

                                        # Invariant D: contradictions > 0 never accepts
                                        if contradictions > 0:
                                            assert report.action in {
                                                DecisionAction.ABSTAIN,
                                                DecisionAction.ESCALATE,
                                            }

                                        # Invariant E: high risk without evidence must verify/escalate/abstain
                                        if risk == "high" and evidence_action is None:
                                            assert report.action in {
                                                DecisionAction.VERIFY,
                                                DecisionAction.ESCALATE,
                                                DecisionAction.ABSTAIN,
                                            }

    # Confirms broad sweep is materially larger than legacy spot tests.
    assert seen >= 2000


def test_curated_fixture_has_minimum_size() -> None:
    """Guardrail to ensure curated suite stays substantial over time."""
    assert len(_CURATED_CASES) >= 20
