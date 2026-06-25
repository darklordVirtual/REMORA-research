"""Tests for AROMER Review Friction Optimizer."""
from __future__ import annotations

import json
import tempfile
import pathlib
import unittest

from remora.aromer.learning.friction_optimizer import (
    FrictionSignal,
    extract_signals,
    propose_adjustments,
    run,
)


def _ep(domain: str, action_type: str, risk_tier: str,
        adj_type: str = "reduce_review_friction") -> dict:
    scope = f"{domain}/{action_type}/{risk_tier}"
    critique = {
        "decision_quality": "benign_review",
        "was_overconservative": True,
        "risk_reasoning_score": 0.8,
        "evidence_score": 0.75,
        "recommended_adjustment": {
            "type": adj_type, "scope": scope, "max_delta": 0.05
        },
        "promote_to_memory": False,
    }
    return {
        "domain": domain, "action_type": action_type, "risk_tier": risk_tier,
        "verdict": "VERIFY", "ground_truth": "benign",
        "critique_text": json.dumps(critique),
    }


class TestExtractSignals(unittest.TestCase):
    def test_empty_episodes(self) -> None:
        self.assertEqual(extract_signals([]), {})

    def test_counts_reduce_signals(self) -> None:
        eps = [_ep("git", "write", "medium") for _ in range(4)]
        sigs = extract_signals(eps)
        scope = "git/write/medium"
        self.assertIn(scope, sigs)
        self.assertEqual(sigs[scope].reduce_count, 4)
        self.assertEqual(sigs[scope].vigilance_count, 0)

    def test_counts_vigilance_signals(self) -> None:
        eps = [_ep("db", "write", "high", "increase_vigilance") for _ in range(2)]
        sigs = extract_signals(eps)
        scope = "db/write/high"
        self.assertEqual(sigs[scope].vigilance_count, 2)
        self.assertEqual(sigs[scope].reduce_count, 0)

    def test_skips_episodes_without_critique(self) -> None:
        eps = [{"domain": "x", "critique_text": ""}]
        self.assertEqual(extract_signals(eps), {})

    def test_net_signal_positive_for_reduce(self) -> None:
        eps = [_ep("infra", "read", "low") for _ in range(5)]
        sigs = extract_signals(eps)
        self.assertGreater(sigs["infra/read/low"].net_signal, 0.0)


class TestProposeAdjustments(unittest.TestCase):
    def _make_signals(self, scope: str, reduce: int, vigilance: int = 0) -> dict:
        total = reduce + vigilance
        return {scope: FrictionSignal(
            scope=scope, reduce_count=reduce, vigilance_count=vigilance,
            none_count=0, total=total,
        )}

    def test_no_proposal_below_min_signals(self) -> None:
        sigs = self._make_signals("git/write/medium", reduce=2)
        result = propose_adjustments(sigs, [])
        self.assertEqual(result, [])

    def test_proposal_at_min_signals(self) -> None:
        sigs = self._make_signals("git/write/medium", reduce=3)
        result = propose_adjustments(sigs, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].adjustment_type, "reduce_review_friction")

    def test_blocked_by_vigilance_signal(self) -> None:
        sigs = self._make_signals("db/write/high", reduce=5, vigilance=1)
        result = propose_adjustments(sigs, [])
        self.assertEqual(result, [])

    def test_delta_capped_at_max(self) -> None:
        sigs = self._make_signals("infra/read/low", reduce=10)
        result = propose_adjustments(sigs, [])
        self.assertLessEqual(result[0].max_delta, 0.05)

    def test_approved_when_holdout_fa_zero(self) -> None:
        sigs = self._make_signals("test/read/low", reduce=5)
        # Holdout has only benign cases → FA=0
        holdout = [
            {"domain": "test", "action_type": "read", "risk_tier": "low",
             "ground_truth": "benign", "verdict": "ACCEPT", "can_train": False}
        ]
        result = propose_adjustments(sigs, holdout)
        self.assertTrue(result[0].approved)

    def test_blocked_when_holdout_has_fa(self) -> None:
        sigs = self._make_signals("danger/exec/critical", reduce=5)
        holdout = [
            {"domain": "danger", "action_type": "exec", "risk_tier": "critical",
             "ground_truth": "harmful", "verdict": "ACCEPT", "can_train": False}
        ]
        result = propose_adjustments(sigs, holdout)
        self.assertFalse(result[0].approved)
        self.assertIn("blocked", result[0].reason)


class TestRunEndToEnd(unittest.TestCase):
    def test_run_with_no_episodes_produces_empty_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = pathlib.Path(tmp) / "empty.jsonl"
            store.write_text("")
            report = run(episode_store_path=store, dry_run=True, verbose=False)
        self.assertEqual(report.n_episodes_scanned, 0)
        self.assertEqual(report.n_approved, 0)

    def test_run_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = pathlib.Path(tmp) / "episodes.jsonl"
            # 3 reduce signals for same scope
            lines = [json.dumps(_ep("infra", "read", "low")) for _ in range(3)]
            store.write_text("\n".join(lines))
            out = pathlib.Path(tmp) / "out.json"
            # Patch OUTPUT_PATH temporarily
            import remora.aromer.learning.friction_optimizer as mod
            orig = mod.OUTPUT_PATH
            mod.OUTPUT_PATH = out
            try:
                run(episode_store_path=store, dry_run=False, verbose=False)
            finally:
                mod.OUTPUT_PATH = orig
            data = json.loads(out.read_text())
            self.assertIn("adjustments", data)
            self.assertIn("quality_gate", data)


if __name__ == "__main__":
    unittest.main()
