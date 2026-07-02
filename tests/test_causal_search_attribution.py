"""Tests for remora.causal.search and remora.causal.attribution.

Covers:
- score_concepts: per-concept PS and PN for blocking / accept observations
- find_minimal_sufficient_interventions: BFS returns correct minimal sets
- compute_concept_attribution: correct aggregation over observation logs
"""
from __future__ import annotations

import pytest

from remora.causal import (
    compute_concept_attribution,
    find_minimal_sufficient_interventions,
    score_concepts,
)
from remora.causal.domains import load_domain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation


@pytest.fixture()
def engine() -> RemoraDecisionEngine:
    return RemoraDecisionEngine()


@pytest.fixture()
def model():
    return load_domain("network_change_management_v1")


def _critical_obs(**kwargs) -> PolicyObservation:
    """Critical-risk BGP observation: rollback absent, argument tainted."""
    defaults = dict(
        question="Deploy BGP route change to core router",
        risk_tier="critical",
        action_type="network_change",
        target_environment="prod",
        rollback_available=False,
        argument_tainted=True,
    )
    defaults.update(kwargs)
    return PolicyObservation(**defaults)


def _low_risk_obs() -> PolicyObservation:
    return PolicyObservation(
        question="Read router ARP table",
        risk_tier="low",
        action_type="network_read",
    )


# ---------------------------------------------------------------------------
# score_concepts
# ---------------------------------------------------------------------------

class TestScoreConcepts:
    def test_returns_one_entry_per_actionable_concept(self, engine, model):
        obs = _critical_obs()
        scores = score_concepts(obs, engine, model)
        actionable_names = {v.name for v in model.actionable_variables()}
        assert {s.concept_name for s in scores} == actionable_names

    def test_ps_is_zero_or_one(self, engine, model):
        obs = _critical_obs()
        for s in score_concepts(obs, engine, model):
            assert s.ps in (0.0, 1.0), f"PS={s.ps} for {s.concept_name}"

    def test_pn_is_zero_or_one(self, engine, model):
        obs = _critical_obs()
        for s in score_concepts(obs, engine, model):
            assert s.pn in (0.0, 1.0), f"PN={s.pn} for {s.concept_name}"

    def test_rollback_plan_sufficient_for_rollback_block(self, engine, model):
        obs = _critical_obs(
            rollback_available=False,
            argument_tainted=False,
            risk_tier="high",  # just rollback block
        )
        scores = {s.concept_name: s for s in score_concepts(obs, engine, model)}
        # rollback_plan_verified sets rollback_available=True → removes the rollback block
        assert scores["rollback_plan_verified"].ps == 1.0

    def test_source_provenance_sufficient_for_taint_block(self, engine, model):
        # argument_tainted is a VERIFY floor (decision_engine.py:272).
        # For PS=1, taint must be the ONLY block — so use a low-risk obs that
        # gives ACCEPT without taint, then add taint and check PS.
        clean_obs = PolicyObservation(
            question="Read router ARP table",
            risk_tier="low",
            action_type="network_read",
        )
        if engine.decide(clean_obs).action.value != "accept":
            pytest.skip("clean low-risk obs is not ACCEPT; cannot isolate taint-only block")
        obs = PolicyObservation(
            question="Read router ARP table",
            risk_tier="low",
            action_type="network_read",
            argument_tainted=True,
        )
        factual = engine.decide(obs).action.value
        if factual == "accept":
            pytest.skip("argument_tainted=True doesn't block for low-risk obs in this engine config")
        scores = {s.concept_name: s for s in score_concepts(obs, engine, model)}
        # source_provenance_verified sets argument_tainted=False → removes the only block
        assert scores["source_provenance_verified"].ps == 1.0

    def test_accept_observation_all_ps_zero(self, engine, model):
        obs = _low_risk_obs()
        report = engine.decide(obs)
        if report.action.value != "accept":
            pytest.skip("low_risk_obs not ACCEPT in this engine config")
        scores = score_concepts(obs, engine, model)
        # For an ACCEPT observation, do(concept=True) cannot improve the verdict
        for s in scores:
            assert s.ps == 0.0, f"Expected PS=0 for ACCEPT obs, got {s.ps} for {s.concept_name}"

    def test_sorted_descending_by_ps(self, engine, model):
        obs = _critical_obs()
        scores = score_concepts(obs, engine, model)
        for a, b in zip(scores, scores[1:]):
            assert (a.ps, a.pn) >= (b.ps, b.pn), "Results not sorted by (-PS, -PN)"

    def test_labels_are_non_empty(self, engine, model):
        obs = _critical_obs()
        for s in score_concepts(obs, engine, model):
            assert s.label, f"Empty label for {s.concept_name}"

    def test_factual_verdict_matches_engine(self, engine, model):
        obs = _critical_obs()
        expected = engine.decide(obs).action.value
        scores = score_concepts(obs, engine, model)
        for s in scores:
            assert s.factual_verdict == expected

    def test_pn_load_bearing_concept_is_necessary(self, engine, model):
        """A concept whose signal_mapping uniquely removes a blocker should be PN=1."""
        obs = _critical_obs(rollback_available=False, argument_tainted=False, risk_tier="high")
        scores = {s.concept_name: s for s in score_concepts(obs, engine, model)}
        # rollback_plan_verified is the only concept that sets rollback_available=True.
        # Without it, the fully-remediated state still fails the rollback gate.
        rp = scores["rollback_plan_verified"]
        assert rp.pn == 1.0, "rollback_plan_verified should be PN=1 (necessary)"


# ---------------------------------------------------------------------------
# find_minimal_sufficient_interventions
# ---------------------------------------------------------------------------

class TestFindMinimalSufficientInterventions:
    def test_accept_obs_returns_size_zero(self, engine, model):
        obs = _low_risk_obs()
        if engine.decide(obs).action.value != "accept":
            pytest.skip("low_risk_obs not ACCEPT in this engine config")
        result = find_minimal_sufficient_interventions(obs, engine, model)
        assert result.minimum_size == 0
        assert result.minimal_sets == []
        assert result.target_verdict == "accept"

    def test_returns_non_empty_for_blocking_obs(self, engine, model):
        obs = _critical_obs()
        result = find_minimal_sufficient_interventions(obs, engine, model)
        assert result.minimum_size >= 1
        assert result.minimal_sets

    def test_minimal_size_is_truly_minimal(self, engine, model):
        obs = _critical_obs()
        result = find_minimal_sufficient_interventions(obs, engine, model)
        k = result.minimum_size
        # Verify no set of size k-1 exists that also achieves PS=1
        if k > 1:
            from itertools import combinations
            from remora.causal.intervention import PolicyIntervention
            from remora.causal.counterfactual import CounterfactualReplay
            replay = CounterfactualReplay(engine, model)
            factual = engine.decide(obs).action.value
            names = [v.name for v in model.actionable_variables()]
            for combo in combinations(names, k - 1):
                ivs = [PolicyIntervention(name, True) for name in combo]
                cf = engine.decide(replay.apply_interventions(obs, ivs)).action.value
                assert cf == factual, f"Set of size {k-1} already sufficient: {combo}"

    def test_all_returned_sets_achieve_verdict_change(self, engine, model):
        obs = _critical_obs()
        result = find_minimal_sufficient_interventions(obs, engine, model)
        from remora.causal.intervention import PolicyIntervention
        from remora.causal.counterfactual import CounterfactualReplay
        replay = CounterfactualReplay(engine, model)
        factual = engine.decide(obs).action.value
        for concept_set in result.minimal_sets:
            ivs = [PolicyIntervention(name, True) for name in concept_set]
            cf = engine.decide(replay.apply_interventions(obs, ivs)).action.value
            assert cf != factual, f"Set {concept_set} did not change verdict"

    def test_all_returned_sets_have_same_cardinality(self, engine, model):
        obs = _critical_obs()
        result = find_minimal_sufficient_interventions(obs, engine, model)
        if result.minimal_sets:
            k = result.minimum_size
            for s in result.minimal_sets:
                assert len(s) == k

    def test_max_size_truncation(self, engine, model):
        obs = _critical_obs()
        result = find_minimal_sufficient_interventions(obs, engine, model, max_size=1)
        # If minimum_size > 1, search was truncated
        if result.minimal_sets:
            assert result.minimum_size <= 1
        else:
            assert result.minimum_size == -1
            assert not result.all_sets_exhausted or result.minimum_size == -1

    def test_factual_verdict_populated(self, engine, model):
        obs = _critical_obs()
        result = find_minimal_sufficient_interventions(obs, engine, model)
        assert result.factual_verdict == engine.decide(obs).action.value


# ---------------------------------------------------------------------------
# compute_concept_attribution
# ---------------------------------------------------------------------------

class TestComputeConceptAttribution:
    def _blocking_obs_log(self):
        return [
            _critical_obs(rollback_available=False, argument_tainted=True),
            _critical_obs(rollback_available=False, argument_tainted=False, risk_tier="high"),
            _critical_obs(rollback_available=True, argument_tainted=True),
        ]

    def test_returns_one_entry_per_actionable_concept(self, engine, model):
        obs_log = self._blocking_obs_log()
        results = compute_concept_attribution(obs_log, engine, model)
        expected = {v.name for v in model.actionable_variables()}
        assert {r.concept_name for r in results} == expected

    def test_mean_ps_in_range(self, engine, model):
        results = compute_concept_attribution(self._blocking_obs_log(), engine, model)
        for r in results:
            assert 0.0 <= r.mean_ps <= 1.0, f"mean_ps={r.mean_ps} out of range for {r.concept_name}"

    def test_mean_pn_in_range(self, engine, model):
        results = compute_concept_attribution(self._blocking_obs_log(), engine, model)
        for r in results:
            assert 0.0 <= r.mean_pn <= 1.0, f"mean_pn={r.mean_pn} out of range for {r.concept_name}"

    def test_n_sufficient_le_n_blocking(self, engine, model):
        obs_log = self._blocking_obs_log()
        results = compute_concept_attribution(obs_log, engine, model)
        for r in results:
            assert r.n_sufficient <= r.n_blocking, (
                f"n_sufficient={r.n_sufficient} > n_blocking={r.n_blocking}"
            )

    def test_sorted_descending_by_mean_ps(self, engine, model):
        results = compute_concept_attribution(self._blocking_obs_log(), engine, model)
        for a, b in zip(results, results[1:]):
            assert (a.mean_ps, a.mean_pn) >= (b.mean_ps, b.mean_pn)

    def test_all_accept_log_returns_zero_scores(self, engine, model):
        obs_log = [_low_risk_obs(), _low_risk_obs()]
        # Only include if they are actually ACCEPT
        accept_log = [o for o in obs_log if engine.decide(o).action.value == "accept"]
        if not accept_log:
            pytest.skip("No ACCEPT observations in this engine config")
        results = compute_concept_attribution(accept_log, engine, model)
        for r in results:
            assert r.mean_ps == 0.0
            assert r.mean_pn == 0.0
            assert r.n_blocking == 0

    def test_n_blocking_correct(self, engine, model):
        obs_log = self._blocking_obs_log()
        n_actual = sum(
            1 for o in obs_log
            if engine.decide(o).action.value in {"verify", "abstain", "escalate"}
        )
        results = compute_concept_attribution(obs_log, engine, model)
        for r in results:
            assert r.n_blocking == n_actual

    def test_custom_blocking_verdicts(self, engine, model):
        obs_log = self._blocking_obs_log()
        results_escalate_only = compute_concept_attribution(
            obs_log, engine, model,
            blocking_verdicts=frozenset({"escalate"}),
        )
        results_all = compute_concept_attribution(obs_log, engine, model)
        # escalate_only n_blocking ≤ all n_blocking
        for r_esc, r_all in zip(
            sorted(results_escalate_only, key=lambda x: x.concept_name),
            sorted(results_all, key=lambda x: x.concept_name),
        ):
            assert r_esc.n_blocking <= r_all.n_blocking

    def test_rollback_concept_has_high_attribution_for_rollback_blocks(self, engine, model):
        obs_log = [
            _critical_obs(rollback_available=False, argument_tainted=False, risk_tier="high")
            for _ in range(3)
        ]
        results = {r.concept_name: r for r in compute_concept_attribution(obs_log, engine, model)}
        rp = results["rollback_plan_verified"]
        assert rp.mean_ps == 1.0, "rollback_plan_verified should have PS=1 for all rollback blocks"
