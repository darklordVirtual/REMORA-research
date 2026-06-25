# Author: Stian Skogbrott
# License: Apache-2.0
"""Structural tests for the AROMER external holdout builder.

These tests lock the *dataset's* invariants — determinism, holdout discipline,
balance, and signal validity. They deliberately do NOT lock the A/B/C ablation
*result* on the holdout: that result is an empirical finding recorded in the
dataset README and artifact, not an invariant.
"""
from __future__ import annotations

import unittest

from remora.aromer.evals.external_holdout import (
    TARGET_FRACTIONS,
    build_holdout,
    load_toolcall_v3,
)

_VALID_VERDICTS = {"accept", "verify", "escalate", "abstain"}
_VALID_TRUTH = {"harmful", "benign"}


class TestSourceIndependence(unittest.TestCase):
    def test_toolcall_v3_loads(self) -> None:
        cases = load_toolcall_v3()
        self.assertGreater(len(cases), 700, "expected the full toolcall_v3 set")

    def test_load_is_sorted_deterministic(self) -> None:
        ids1 = [c.get("id") for c in load_toolcall_v3()]
        ids2 = [c.get("id") for c in load_toolcall_v3()]
        self.assertEqual(ids1, ids2)
        self.assertEqual(ids1, sorted(ids1))


class TestHoldoutDiscipline(unittest.TestCase):
    def setUp(self) -> None:
        self.selected = build_holdout()
        self.all_cases = [c for cs in self.selected.values() for c in cs]

    def test_every_case_is_held_out_from_training(self) -> None:
        for c in self.all_cases:
            self.assertFalse(c.can_train, f"{c.id} must be can_train=False")

    def test_provenance_is_recorded(self) -> None:
        for c in self.all_cases:
            self.assertEqual(c.source, "toolcall_v3_cyberseceval")
            self.assertEqual(c.label_source, "benchmark_ground_truth")
            self.assertTrue(c.origin_id, "origin id must be preserved for traceability")

    def test_determinism(self) -> None:
        again = build_holdout()
        ids_a = [c.id for cs in self.selected.values() for c in cs]
        ids_b = [c.id for cs in again.values() for c in cs]
        self.assertEqual(ids_a, ids_b)


class TestBalanceAndLabels(unittest.TestCase):
    def setUp(self) -> None:
        self.selected = build_holdout()

    def test_three_buckets_present(self) -> None:
        self.assertEqual(set(self.selected), set(TARGET_FRACTIONS))

    def test_bucket_truth_consistency(self) -> None:
        for c in self.selected["harmful"]:
            self.assertEqual(c.expected_truth, "harmful")
        for c in self.selected["benign"]:
            self.assertEqual(c.expected_truth, "benign")
        for c in self.selected["ambiguous"]:
            self.assertEqual(c.expected_truth, "benign")  # uncertain-but-not-harmful

    def test_harmful_is_largest_or_tied(self) -> None:
        counts = {b: len(c) for b, c in self.selected.items()}
        self.assertGreaterEqual(counts["harmful"], counts["ambiguous"])


class TestSignalValidity(unittest.TestCase):
    def setUp(self) -> None:
        self.all_cases = [c for cs in build_holdout().values() for c in cs]

    def test_signals_in_unit_interval(self) -> None:
        for c in self.all_cases:
            for name, val in (("trust", c.trust_score), ("H", c.final_H), ("D", c.final_D)):
                self.assertGreaterEqual(val, 0.0, f"{c.id} {name}")
                self.assertLessEqual(val, 1.0, f"{c.id} {name}")

    def test_verdict_and_truth_in_valid_sets(self) -> None:
        for c in self.all_cases:
            self.assertIn(c.expected_verdict, _VALID_VERDICTS, c.id)
            self.assertIn(c.expected_truth, _VALID_TRUTH, c.id)

    def test_tainted_or_attack_lowers_trust(self) -> None:
        # Adversarial / tainted harmful cases must not carry top trust.
        for c in self.all_cases:
            if c.category == "harmful" and c.risk_tier in ("high", "critical"):
                self.assertLess(c.trust_score, 0.6, f"{c.id} high-risk harmful trust too high")


if __name__ == "__main__":
    unittest.main()
