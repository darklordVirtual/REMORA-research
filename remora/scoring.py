# Author: Stian Skogbrott
# License: Apache-2.0
"""Scoring utilities for evaluating REMORA oracle reports against benchmark ground truth."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
from remora.benchmarks.loaders import BenchmarkItem, GroundTruthType
from remora.canonical import _normalize_text, _coerce_polarity

@dataclass
class ScoreResult:
    item_id: str; benchmark: str; correct: bool
    confidence: float; predicted: Any; expected: Any; method: str

def extract_prediction(report: dict, truth_type: str) -> tuple[Any, float]:
    top_claims = report.get("top_claims", [])
    if not top_claims: return None, 0.0
    top_claim, top_confidence = top_claims[0]
    confidence = min(1.0, max(0.0, float(top_confidence)))
    if truth_type == GroundTruthType.POLARITY.value:
        pred = _coerce_polarity(top_claim)
        if pred is None:
            negations = report.get("known_negations", [])
            if negations: pred = False
        return pred, confidence
    if truth_type == GroundTruthType.SHORT_ANSWER.value: return str(top_claim), confidence
    if truth_type == GroundTruthType.CATEGORICAL.value: return str(top_claim).strip().lower(), confidence
    return top_claim, confidence

def _polarity_match(predicted, expected) -> bool:
    exp_pol = _coerce_polarity(expected) if not isinstance(expected, bool) else expected
    return predicted == exp_pol

def _short_answer_match(predicted: str, expected: str) -> bool:
    if predicted is None or expected is None: return False
    pred_norm = set(_normalize_text(str(predicted)).split())
    exp_norm = set(_normalize_text(str(expected)).split())
    return len(pred_norm & exp_norm) / len(exp_norm) >= 0.5 if exp_norm else False

def _categorical_match(predicted: str, expected: str) -> bool:
    return str(predicted).strip().lower() == str(expected).strip().lower()

def score_one(item: BenchmarkItem, report: dict) -> ScoreResult:
    predicted, confidence = extract_prediction(report, item.truth_type)
    if item.truth_type == GroundTruthType.POLARITY.value:
        correct = _polarity_match(predicted, item.ground_truth); method = "polarity"
    elif item.truth_type == GroundTruthType.SHORT_ANSWER.value:
        correct = _short_answer_match(predicted, item.ground_truth); method = "token_overlap"
    elif item.truth_type == GroundTruthType.CATEGORICAL.value:
        correct = _categorical_match(predicted, item.ground_truth); method = "categorical_exact"
    else:
        correct = predicted == item.ground_truth; method = "direct_equality"
    return ScoreResult(item_id=item.item_id, benchmark=item.benchmark, correct=correct,
        confidence=confidence, predicted=predicted, expected=item.ground_truth, method=method)

def score_batch(items: list[BenchmarkItem], reports: list[dict]) -> dict:
    if len(items) != len(reports):
        raise ValueError(f"items ({len(items)}) and reports ({len(reports)}) differ in length")
    results = [score_one(it, r) for it, r in zip(items, reports)]
    by_benchmark: dict[str, list] = {}
    for r in results: by_benchmark.setdefault(r.benchmark, []).append(r)
    per_bm = {}
    for bm, rs in by_benchmark.items():
        n = len(rs); correct = sum(1 for r in rs if r.correct)
        per_bm[bm] = {"n": n, "correct": correct, "accuracy": correct/n if n else 0.0,
            "mean_confidence": sum(r.confidence for r in rs)/n if n else 0.0}
    n = len(results); n_c = sum(1 for r in results if r.correct)
    return {"overall": {"n": n, "correct": n_c, "accuracy": n_c/n if n else 0.0},
        "per_benchmark": per_bm,
        "details": [{"item_id": r.item_id, "benchmark": r.benchmark, "correct": r.correct,
            "confidence": r.confidence, "predicted": r.predicted,
            "expected": r.expected, "method": r.method} for r in results]}


# ── Effective Truth Rate ───────────────────────────────────────────────────────

@dataclass
class ETRResult:
    """
    Effective Truth Rate (ETR) for a single item.

    ETR is a composite truthfulness metric that requires a correct answer
    to also be evidence-supported, oracle-consistent, and non-contradicted.
    An answer that is accidentally correct but unsupported does not count
    toward ETR — only calibrated, grounded, stable verdicts do.

    This mirrors the distinction between 'Effective Harm Rate' and raw
    technical success rates in AI security evaluation: a system that is
    technically correct but poorly calibrated or easily manipulated does
    not provide the reliability needed for high-stakes decisions.

    Fields
    ------
    item_id             Benchmark item identifier
    answer_correct      Ground-truth answer match (standard accuracy)
    evidence_supported  oracle confidence >= evidence_min_confidence
    oracle_consistent   weighted_support >= oracle_min_support
    not_contradicted    falsified_fraction < max_contradiction_fraction
    etr                 True iff ALL four conditions are satisfied
    """
    item_id: str
    benchmark: str
    answer_correct: bool
    evidence_supported: bool
    oracle_consistent: bool
    not_contradicted: bool
    etr: bool
    confidence: float
    weighted_support: float
    falsified_count: int
    open_candidates: int


def evidence_score_from_rag(
    report: dict,
    rag_verdicts: Optional[list[dict]] = None,
) -> float:
    """
    Compute an evidence score combining oracle confidence with RAG source authority.

    When RAG verdicts are available, the evidence score is:
        evidence_score = top_claim_confidence * 0.5 + rag_weighted_score * 0.5

    Where rag_weighted_score = mean(rag_confidence_i * authority_weight_i) over
    all RAG verdicts with answer matching the top claim.

    When no RAG verdicts are provided, falls back to top_claim_confidence alone.

    Parameters
    ----------
    report : dict
        REMORA report dict from engine.report().
    rag_verdicts : list[dict] or None
        List of RAG oracle response dicts with keys:
            answer (bool|None), confidence (float), confidence_weight (float, optional)

    Returns
    -------
    float: evidence score in [0, 1]
    """
    top_claims = report.get("top_claims", [])
    parametric_conf = float(top_claims[0][1]) if top_claims else 0.0

    if not rag_verdicts:
        return parametric_conf

    # Get the top claim's polarity from candidates
    top_polarity = None
    if report.get("top_claims") and report.get("state_candidates"):
        # Best effort: infer polarity from top claim text
        top_text = top_claims[0][0].lower() if top_claims else ""
        if "pol=true" in top_text or "yes" in top_text:
            top_polarity = True
        elif "pol=false" in top_text or "no" in top_text:
            top_polarity = False

    # Compute RAG contribution
    rag_scores = []
    for rv in rag_verdicts:
        answer = rv.get("answer")
        conf = float(rv.get("confidence", 0.0))
        authority = float(rv.get("confidence_weight", 1.0))
        # If RAG agrees with top-claim direction (or top polarity unknown), credit it
        if top_polarity is None or answer == top_polarity:
            rag_scores.append(conf * min(authority, 2.0) / 2.0)

    if not rag_scores:
        return parametric_conf * 0.7  # RAG disagreed — penalise slightly

    rag_mean = sum(rag_scores) / len(rag_scores)
    return 0.5 * parametric_conf + 0.5 * rag_mean


def effective_truth_rate(
    items: list[BenchmarkItem],
    reports: list[dict],
    score_results: Optional[list[ScoreResult]] = None,
    rag_verdicts_per_item: Optional[list[Optional[list[dict]]]] = None,
    evidence_min_confidence: float = 0.65,
    oracle_min_support: float = 0.72,
    max_contradiction_fraction: float = 0.30,
) -> dict:
    """
    Compute Effective Truth Rate across a set of items and REMORA reports.

    ETR(item) = answer_correct
                AND confidence >= evidence_min_confidence
                AND weighted_support >= oracle_min_support
                AND (falsified / total_candidates) < max_contradiction_fraction

    Parameters
    ----------
    items : list[BenchmarkItem]
        Benchmark items with ground truth.
    reports : list[dict]
        REMORA report dicts from engine.report().
    score_results : list[ScoreResult] or None
        Pre-computed ScoreResult objects. If None, computed from items+reports.
    evidence_min_confidence : float
        Minimum weighted support to count as evidence-backed (default 0.65).
    oracle_min_support : float
        Minimum weighted_support from the top claim to count as oracle-consistent
        (default 0.72, matching REMORA's converged_threshold).
    max_contradiction_fraction : float
        Maximum ratio of falsified claims to open candidates before a verdict
        is considered contradicted (default 0.30).

    Returns
    -------
    dict with keys:
        etr_rate         float   — ETR / N
        accuracy         float   — standard accuracy
        etr_vs_accuracy  float   — ETR uplift or penalty vs accuracy
        n_correct        int
        n_etr            int
        n_evidence_gap   int     — correct but not evidence-supported
        n_consensus_gap  int     — correct+evidence but not oracle-consistent
        n_contradiction  int     — failed contradiction check
        details          list[ETRResult]
    """
    if score_results is None:
        score_results = [score_one(it, r) for it, r in zip(items, reports)]

    etr_results: list[ETRResult] = []
    for idx, (item, report, sr) in enumerate(zip(items, reports, score_results)):
        # Evidence score: combine parametric confidence with RAG source authority
        rag_vs = rag_verdicts_per_item[idx] if rag_verdicts_per_item else None
        confidence = evidence_score_from_rag(report, rag_vs)
        # Oracle consistency: top-claim weighted support
        top_claims = report.get("top_claims", [])
        final_support = float(top_claims[0][1]) if top_claims else 0.0
        _traj = report.get("trajectory", [])  # noqa: F841
        open_cands = int(report.get("open_candidates", 0))
        falsified  = int(report.get("falsified_count", 0))
        total_seen = open_cands + falsified

        evidence_ok  = confidence >= evidence_min_confidence
        consensus_ok = final_support >= oracle_min_support
        contradiction_ok = (
            (falsified / total_seen) < max_contradiction_fraction
            if total_seen > 0 else True
        )

        etr = sr.correct and evidence_ok and consensus_ok and contradiction_ok
        etr_results.append(ETRResult(
            item_id=item.item_id,
            benchmark=item.benchmark,
            answer_correct=sr.correct,
            evidence_supported=evidence_ok,
            oracle_consistent=consensus_ok,
            not_contradicted=contradiction_ok,
            etr=etr,
            confidence=confidence,
            weighted_support=final_support,
            falsified_count=falsified,
            open_candidates=open_cands,
        ))

    n = len(etr_results)
    n_correct = sum(1 for r in etr_results if r.answer_correct)
    n_etr     = sum(1 for r in etr_results if r.etr)
    # Breakdown: where does ETR fail beyond simple accuracy?
    n_evidence_gap  = sum(1 for r in etr_results if r.answer_correct and not r.evidence_supported)
    n_consensus_gap = sum(1 for r in etr_results
                          if r.answer_correct and r.evidence_supported and not r.oracle_consistent)
    n_contradiction = sum(1 for r in etr_results
                          if r.answer_correct and r.evidence_supported
                          and r.oracle_consistent and not r.not_contradicted)

    return {
        "etr_rate":        round(n_etr / n, 4) if n else 0.0,
        "accuracy":        round(n_correct / n, 4) if n else 0.0,
        "etr_vs_accuracy": round((n_etr - n_correct) / n, 4) if n else 0.0,
        "n":               n,
        "n_correct":       n_correct,
        "n_etr":           n_etr,
        "n_evidence_gap":  n_evidence_gap,
        "n_consensus_gap": n_consensus_gap,
        "n_contradiction": n_contradiction,
        "thresholds": {
            "evidence_min_confidence":    evidence_min_confidence,
            "oracle_min_support":         oracle_min_support,
            "max_contradiction_fraction": max_contradiction_fraction,
        },
        "details": etr_results,
    }
