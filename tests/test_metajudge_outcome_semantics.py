# Author: Stian Skogbrott
# License: Apache-2.0
"""Regression tests for MetaJudge outcome-label fidelity.

Background
----------
``Episode`` carries two labels:

* ``decision_quality`` — the precise 6-value taxonomy
  (correct_accept, false_accept, benign_review, correct_intercept_verify,
  false_block, correct_block).
* ``outcome`` — a *lossy* 4-value legacy projection kept only for the
  historical JSONL on-disk format. ``_quality_to_legacy`` collapses
  ``BENIGN_REVIEW`` (a friction event) onto ``CORRECT_ACCEPT`` (a success).

The MetaJudge's whole job is to recommend friction reductions. If it is fed
the legacy ``outcome`` field, every ``benign_review`` episode arrives labelled
``correct_accept`` and the judge is structurally blind to friction.

These tests lock the live-worker prompt path to ``decision_quality`` so the
friction label can never again be masked at the source.
"""
from __future__ import annotations

import unittest

from remora.aromer.experience.episode import Episode, GroundTruth
from remora.aromer.meta_judge.judge import AromerMetaJudge


def _verify_on_benign_episode() -> Episode:
    """A VERIFY decision on a benign action — i.e. unnecessary review friction."""
    ep = Episode(
        domain="github",
        risk_tier="low",
        action_type="read",
        phase="ordered",
        trust_score=0.82,
        entropy_H=0.20,
        dissensus_D=0.10,
        verdict="VERIFY",
        confidence=0.70,
        rules_triggered=[],
    )
    ep.record_ground_truth(GroundTruth.BENIGN)
    return ep


class TestLossyProjectionIsReal(unittest.TestCase):
    """Document the exact lossy projection these tests defend against."""

    def test_benign_review_is_masked_by_legacy_outcome(self) -> None:
        ep = _verify_on_benign_episode()
        # The precise label correctly records friction…
        self.assertEqual(ep.decision_quality.value, "benign_review")
        # …but the legacy projection collapses it onto a success label.
        self.assertEqual(ep.outcome.value, "correct_accept")


class TestMetaJudgePromptUsesDecisionQuality(unittest.TestCase):
    """The MetaJudge must see the precise label, not the masked legacy one."""

    def _capture_prompt(self, method_name: str) -> str:
        ep = _verify_on_benign_episode()
        judge = AromerMetaJudge()
        captured: dict[str, str] = {}

        def fake_call(prompt: str, context: str) -> str:
            captured["prompt"] = prompt
            captured["context"] = context
            raise RuntimeError("short-circuit after prompt capture")

        judge._call_worker = fake_call  # type: ignore[assignment]

        method = getattr(judge, method_name)
        # Both methods catch the worker exception and degrade gracefully;
        # the prompt has already been captured by then.
        method(ep)
        return captured["prompt"]

    def test_critique_prompt_contains_friction_label(self) -> None:
        prompt = self._capture_prompt("critique")
        self.assertIn("benign_review", prompt)
        self.assertNotIn("correct_accept", prompt)

    def test_rubric_prompt_contains_friction_label(self) -> None:
        prompt = self._capture_prompt("critique_rubric")
        self.assertIn("benign_review", prompt)
        self.assertNotIn("correct_accept", prompt)


if __name__ == "__main__":
    unittest.main()
