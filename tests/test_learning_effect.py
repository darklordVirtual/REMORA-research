# Author: Stian Skogbrott
# License: Apache-2.0
"""Locks AROMER's measurable, safe learning effect.

Guards the bidirectional world-model fix: AROMER must be able to REDUCE review
friction on contexts it has proven safe, while never accepting a harmful action.
Before the fix the world model could only lower trust, so friction_reduction was
structurally impossible (<= 0).
"""
from __future__ import annotations

import unittest

from remora.aromer.evals.learning_effect import run
from remora.aromer.world_model.domain_prior import DomainHarmPrior


class TestLearningEffect(unittest.TestCase):
    def setUp(self) -> None:
        self.report = run()

    def test_friction_is_reduced(self) -> None:
        self.assertGreater(self.report.friction_reduction, 0.0,
                           "AROMER must reduce friction on proven-safe contexts")

    def test_safety_preserved(self) -> None:
        self.assertTrue(self.report.safety_preserved)
        self.assertEqual(self.report.profile_a_static["false_accept_rate"], 0.0)
        self.assertEqual(self.report.profile_c_aromer["false_accept_rate"], 0.0)

    def test_static_baseline_has_friction_to_reduce(self) -> None:
        # The demonstration is only meaningful if static REMORA actually reviews
        # these proven-safe benign actions.
        self.assertGreater(self.report.profile_a_static["review_friction"], 0.0)


class TestBidirectionalAdjustTrust(unittest.TestCase):
    """The world model must boost proven-safe contexts and lower risky ones."""

    def _prior(self, tmp_factory):
        import os
        return DomainHarmPrior(os.path.join(tmp_factory, "w.json"), shadow_mode=False)

    def test_boost_for_proven_safe(self) -> None:
        import tempfile
        p = self._prior(tempfile.mkdtemp())
        for _ in range(25):
            p.update("git", "read", "low", harm_occurred=False)
        boosted = p.adjust_trust(0.50, "git", "read", "low")
        self.assertGreater(boosted, 0.50, "proven-safe context must boost trust")
        self.assertLessEqual(boosted, 0.95, "boost must be capped")

    def test_lower_for_proven_risky(self) -> None:
        import tempfile
        p = self._prior(tempfile.mkdtemp())
        for _ in range(25):
            p.update("shell", "execution", "critical", harm_occurred=True)
        lowered = p.adjust_trust(0.80, "shell", "execution", "critical")
        self.assertLess(lowered, 0.80, "proven-risky context must lower trust")

    def test_no_boost_without_enough_evidence(self) -> None:
        import tempfile
        p = self._prior(tempfile.mkdtemp())
        for _ in range(3):  # low confidence
            p.update("git", "read", "low", harm_occurred=False)
        self.assertEqual(p.adjust_trust(0.50, "git", "read", "low"), 0.50,
                         "low-confidence context must not boost")

    def test_boost_fires_at_medium_confidence(self) -> None:
        # CI-driven gate: ~12+ clean observations clear the 95% upper-bound gate,
        # so friction starts dropping before the strict n>=20 high-confidence mark.
        import tempfile
        p = self._prior(tempfile.mkdtemp())
        for _ in range(15):  # medium confidence, all clean
            p.update("git", "read", "low", harm_occurred=False)
        self.assertGreater(p.adjust_trust(0.50, "git", "read", "low"), 0.50,
                           "a CI-proven-safe context must boost at medium confidence")


class TestBoostSafetyBoundary(unittest.TestCase):
    """Characterise exactly when the trust boost can and cannot cause a false
    accept. Structural gates and uncertainty signals must dominate the boost;
    only an action that defeats EVERY signal at once can slip through.
    """

    def _aromer_verdict(self, **obs_kw) -> str:
        import os
        import tempfile
        from remora.policy import PolicyObservation, RemoraDecisionEngine
        w = DomainHarmPrior(os.path.join(tempfile.mkdtemp(), "w.json"), shadow_mode=False)
        for _ in range(25):
            w.update("information", "read", "low", harm_occurred=False)
        trust = w.adjust_trust(0.50, "information", "read", "low")
        self.assertGreater(trust, 0.80)  # boost fired
        obs = PolicyObservation(
            question="x", trust_score=trust, risk_tier="low",
            domain="information", action_type="read", **obs_kw,
        )
        return RemoraDecisionEngine().decide(obs).action.value.lower()

    def test_structural_gates_dominate_boost(self) -> None:
        # Even with a strong trust boost, structural signals still ESCALATE/VERIFY.
        self.assertEqual(self._aromer_verdict(phase="ordered", final_H=0.2, final_D=0.1,
                                              tool_forbidden=True), "escalate")
        self.assertEqual(self._aromer_verdict(phase="ordered", final_H=0.2, final_D=0.1,
                                              schema_valid=False), "escalate")
        self.assertNotEqual(self._aromer_verdict(phase="ordered", final_H=0.2, final_D=0.1,
                                                 argument_tainted=True), "accept")

    def test_uncertainty_signal_blocks_boost(self) -> None:
        # High entropy/dissensus → the boost cannot turn it into an auto-accept.
        self.assertNotEqual(
            self._aromer_verdict(phase="critical", final_H=0.7, final_D=0.6), "accept")


if __name__ == "__main__":
    unittest.main()
