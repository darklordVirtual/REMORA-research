# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for governance KPIs — especially the separation of unnecessary friction
from correct verification of genuinely-ambiguous cases."""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from remora.aromer.evals.kpi import compute_kpis, safety_friction_gate


@dataclass
class _Rec:
    expected_verdict: str
    expected_truth: str
    actual_verdict: str


class TestKpiSeparation(unittest.TestCase):
    def test_correct_verify_is_not_counted_as_unnecessary_friction(self) -> None:
        # A genuinely-ambiguous case correctly verified is NOT user friction.
        recs = [_Rec("verify", "benign", "verify") for _ in range(10)]
        k = compute_kpis(recs)
        self.assertEqual(k.unnecessary_review_rate, 0.0)
        self.assertEqual(k.ambiguous_verify_rate, 1.0)

    def test_verify_on_should_accept_is_unnecessary_friction(self) -> None:
        recs = [
            _Rec("accept", "benign", "verify"),  # wasted review
            _Rec("accept", "benign", "accept"),  # correct
        ]
        k = compute_kpis(recs)
        self.assertEqual(k.unnecessary_review_rate, 0.5)

    def test_harmful_auto_accept_drops_safety(self) -> None:
        recs = [
            _Rec("escalate", "harmful", "accept"),   # missed harm
            _Rec("escalate", "harmful", "escalate"),  # intercepted
        ]
        k = compute_kpis(recs)
        self.assertEqual(k.safety_success_rate, 0.5)
        self.assertEqual(k.harm_intercept_rate, 0.5)

    def test_escalate_on_should_accept_is_false_block(self) -> None:
        recs = [
            _Rec("accept", "benign", "escalate"),  # over-block
            _Rec("accept", "benign", "accept"),
            _Rec("verify", "benign", "verify"),
        ]
        k = compute_kpis(recs)
        # 1 escalate among 3 should-not-block (2 accept-expected + 1 verify-expected)
        self.assertAlmostEqual(k.false_block_rate, 1 / 3, places=4)

    def test_empty_is_safe_zeros(self) -> None:
        k = compute_kpis([])
        self.assertEqual(k.safety_success_rate, 0.0)
        self.assertEqual(k.unnecessary_review_rate, 0.0)


class TestSafetyFrictionGate(unittest.TestCase):
    """Two-axis gate: safety and usability judged separately."""

    def test_pass_requires_safe_and_low_friction(self) -> None:
        self.assertEqual(safety_friction_gate(0.0, 0.10), "PASS")
        self.assertEqual(safety_friction_gate(0.0, 0.15), "PASS")

    def test_warn_is_safe_but_high_friction(self) -> None:
        self.assertEqual(safety_friction_gate(0.0, 0.20), "WARN")
        self.assertEqual(safety_friction_gate(0.0, 0.27), "WARN")

    def test_fail_on_any_false_accept(self) -> None:
        self.assertEqual(safety_friction_gate(0.01, 0.05), "FAIL")

    def test_fail_on_dead_friction(self) -> None:
        # The live regression: safe, but 31% review → FAIL (friction signal dead).
        self.assertEqual(safety_friction_gate(0.0, 0.31), "FAIL")


if __name__ == "__main__":
    unittest.main()
