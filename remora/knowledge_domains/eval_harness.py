# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic evaluation harness for claim-grounded answering systems.

Scores a committed system-under-test against a fixed gold standard: micro-averaged
grounding precision/recall/F1 (did it cite the right claim ids?) and refusal
accuracy (did it refuse off-corpus questions?). No model call — the predictions
are a committed, deliberately-imperfect set, so the numbers exercise the SCORER,
not any LLM. Point the same scorer at real REMORA oracle outputs to grade them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    """The question, the ids that truly support an answer, and whether a grounded
    system should REFUSE (no supporting claim exists)."""

    qid: str
    gold_ids: frozenset[str]
    should_refuse: bool


@dataclass(frozen=True)
class Prediction:
    """A system-under-test answer: cited ids and whether it refused."""

    qid: str
    cited_ids: frozenset[str]
    refused: bool


# Fixed gold standard: 10 cases (7 answerable, 3 that must be refused).
GOLD: tuple[Case, ...] = (
    Case("q1", frozenset({"CLAIM-A", "CLAIM-B"}), False),
    Case("q2", frozenset({"CLAIM-C"}), False),
    Case("q3", frozenset({"CLAIM-D", "CLAIM-E"}), False),
    Case("q4", frozenset({"CLAIM-F"}), False),
    Case("q5", frozenset({"CLAIM-G", "CLAIM-H"}), False),
    Case("q6", frozenset({"CLAIM-I"}), False),
    Case("q7", frozenset({"CLAIM-J"}), False),
    Case("q8", frozenset(), True),
    Case("q9", frozenset(), True),
    Case("q10", frozenset(), True),
)

# Deliberately imperfect SUT: q3 misses a gold id (recall), q4 adds a
# hallucinated citation (precision), q9 fails to refuse (refusal).
PREDICTIONS: tuple[Prediction, ...] = (
    Prediction("q1", frozenset({"CLAIM-A", "CLAIM-B"}), False),
    Prediction("q2", frozenset({"CLAIM-C"}), False),
    Prediction("q3", frozenset({"CLAIM-D"}), False),
    Prediction("q4", frozenset({"CLAIM-F", "CLAIM-X"}), False),
    Prediction("q5", frozenset({"CLAIM-G", "CLAIM-H"}), False),
    Prediction("q6", frozenset({"CLAIM-I"}), False),
    Prediction("q7", frozenset({"CLAIM-J"}), False),
    Prediction("q8", frozenset(), True),
    Prediction("q9", frozenset({"CLAIM-Z"}), False),
    Prediction("q10", frozenset(), True),
)


def _round(x: float) -> float:
    return round(x, 4)


def evaluate(
    gold: tuple[Case, ...], preds: tuple[Prediction, ...]
) -> dict[str, float]:
    """Micro-averaged grounding P/R/F1 over answerable cases plus refusal
    accuracy over refusal-relevant ones."""
    by_pred = {p.qid: p for p in preds}
    tp = fp = fn = 0
    refuse_total = refuse_correct = 0
    for case in gold:
        pred = by_pred[case.qid]
        if case.should_refuse:
            refuse_total += 1
            if pred.refused and not pred.cited_ids:
                refuse_correct += 1
            continue
        tp += len(pred.cited_ids & case.gold_ids)
        fp += len(pred.cited_ids - case.gold_ids)
        fn += len(case.gold_ids - pred.cited_ids)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    refusal_accuracy = refuse_correct / refuse_total if refuse_total else 0.0
    return {
        "n_cases": len(gold),
        "grounding_precision": _round(precision),
        "grounding_recall": _round(recall),
        "grounding_f1": _round(f1),
        "refusal_accuracy": _round(refusal_accuracy),
    }
