#!/usr/bin/env python3
"""Evaluate REMORA's thermodynamic router policy on the benchmark suite.

This experiment measures the thermodynamic controller as a runtime policy,
not just as a descriptive analysis layer. It supports two operating modes:

1. Guardrail-only: answer only items that the thermodynamic router accepts and
   abstain on items marked `require_rag=True`.
2. Evidence-backed: for flagged items, query a configured evidence oracle and
   score the combined end-to-end policy.

The goal is to answer a narrower and more testable question than the broader
"routing superiority" claim:

    Does the thermodynamic controller improve selective answer quality and
    concentrate likely errors into the evidence-required bucket?

If an evidence oracle is configured, the experiment also reports whether the
combined policy improves end-to-end accuracy or ETR relative to a plain
parametric majority baseline.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.engine import Remora
from remora.genome import Genome, RouterMode
from remora.oracles.cloudflare_rag import CloudflareRAGOracle
from remora.oracles.factory import build_swarm
from remora.persistence import CachedOracle, Store
from remora.scoring import _polarity_match
from remora.scoring import effective_truth_rate, score_one


PHASE_RE = re.compile(r"thermodynamic phase=(ordered|critical|disordered)")


def build_eval_prompt(question: str, context: str | None) -> str:
    ctx = f"\nContext:\n{context}\n" if context else ""
    return (
        f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
        'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
        f"Question: {question}\n\nJSON:"
    )


def make_genome(**overrides: Any) -> Genome:
    params = {
        "max_iterations": 4,
        "max_subquestions": 1,
        "converged_threshold": 0.72,
        "entropy_abort_ratio": 1.3,
        "negation_ratio": 0.25,
        "decomposition_strategy": "simple",
        "early_exit_on_convergence": True,
        "enable_routing": True,
        "router_mode": RouterMode.BALANCED,
        "enable_thermodynamic_control": True,
        "thermo_calibration_path": None,
        **overrides,
    }
    return Genome(**params)


def load_benchmark_module(module_name: str):
    module = importlib.import_module(module_name)
    if not hasattr(module, "load_all_extended_v2") or not hasattr(module, "_ITEMS"):
        raise ValueError(
            f"Benchmark module {module_name!r} must define load_all_extended_v2() and _ITEMS"
        )
    return module


def wrap_oracles(oracles: list, cache_path: str | None) -> list:
    if not cache_path:
        return oracles
    store = Store(cache_path)
    return [CachedOracle(oracle, store) for oracle in oracles]


def maybe_progress(index: int, total: int, every: int, label: str) -> None:
    if every > 0 and (index == total or index % every == 0):
        print(f"[{label}] {index}/{total}", flush=True)


def extract_phase(report: dict) -> str | None:
    for decision in report.get("decisions", []):
        match = PHASE_RE.search(decision)
        if match:
            return match.group(1)
    return None


def majority_vote(item, oracles: list) -> dict:
    prompt = build_eval_prompt(item.question, item.context)
    verdicts = [(oracle.name, phi(oracle.ask(prompt).extracted)) for oracle in oracles]
    votes: dict[bool | None, int] = defaultdict(int)
    for _, verdict in verdicts:
        votes[verdict.polarity] += 1
    predicted = max(votes, key=votes.__getitem__)
    return {
        "predicted": predicted,
        "correct": _polarity_match(predicted, item.ground_truth),
        "oracle_calls": len(oracles),
    }


def build_evidence_oracle(worker_url: str | None, secret: str | None) -> CloudflareRAGOracle | None:
    if not worker_url:
        return None
    return CloudflareRAGOracle(worker_url=worker_url, secret=secret, rerank=True, dual_consensus=False)


def score_policy_subset(items: list, reports: list[dict]) -> dict:
    if not items:
        return {
            "n": 0,
            "accuracy": 0.0,
            "etr_rate": 0.0,
            "false_trust_rate": 0.0,
        }
    score_results = [score_one(item, report) for item, report in zip(items, reports)]
    n = len(score_results)
    correct = sum(1 for result in score_results if result.correct)
    etr = effective_truth_rate(items, reports, score_results=score_results)
    return {
        "n": n,
        "accuracy": round(correct / n, 4),
        "etr_rate": etr["etr_rate"],
        "false_trust_rate": round(1.0 - (correct / n), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-module", default="remora.benchmarks.extended_v2")
    parser.add_argument("--backend", default="groq", help="Oracle backend: auto|groq|mock|cloudflare|...")
    parser.add_argument("--cache", default=".remora_cache.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--router-mode", default="balanced", choices=["strict", "balanced", "hybrid"])
    parser.add_argument("--router-confidence-min", type=float, default=0.80)
    parser.add_argument("--thermo-lambda", type=float, default=0.4)
    parser.add_argument("--thermo-calibration", default=None)
    parser.add_argument("--trust-threshold-high", type=float, default=0.45)
    parser.add_argument("--trust-threshold-low", type=float, default=0.08)
    parser.add_argument("--hallucination-threshold", type=float, default=0.05)
    parser.add_argument("--output", default="results/thermodynamic_router_eval_results.json")
    parser.add_argument("--evidence-worker-url", default=None)
    parser.add_argument("--evidence-secret", default=None)
    args = parser.parse_args()

    module = load_benchmark_module(args.benchmark_module)
    items = module.load_all_extended_v2()
    meta_by_id = {row["item_id"]: row for row in module._ITEMS}
    if args.limit > 0:
        items = items[: args.limit]

    router_mode = {
        "strict": RouterMode.STRICT,
        "balanced": RouterMode.BALANCED,
        "hybrid": RouterMode.HYBRID,
    }[args.router_mode]

    oracles = wrap_oracles(build_swarm(args.backend), args.cache)
    genome = make_genome(
        router_mode=router_mode,
        router_confidence_min=args.router_confidence_min,
        thermo_lambda=args.thermo_lambda,
        thermo_calibration_path=args.thermo_calibration,
        trust_threshold_high=args.trust_threshold_high,
        trust_threshold_low=args.trust_threshold_low,
        hallucination_threshold=args.hallucination_threshold,
    )
    correlation = CorrelationMatrix(window_size=500)
    engine = Remora(oracles=oracles, genome=genome, correlation=correlation)
    evidence_oracle = build_evidence_oracle(args.evidence_worker_url, args.evidence_secret)

    overall_reports: list[dict] = []
    answered_items: list = []
    answered_reports: list[dict] = []
    evidence_augmented_reports: list[dict] = []
    evidence_augmented_items: list = []
    details: list[dict] = []
    phase_counts: Counter[str] = Counter()
    phase_flagged: Counter[str] = Counter()
    total = len(items)

    for index, item in enumerate(items, start=1):
        state = engine.run(item.question, context=item.context)
        report = engine.report(state)
        overall_reports.append(report)
        majority = majority_vote(item, oracles)
        phase = extract_phase(report) or "unknown"
        phase_counts[phase] += 1

        thermo_score = score_one(item, report)
        answered = bool(report.get("top_claims")) and not report.get("require_rag", False)
        if report.get("require_rag", False):
            phase_flagged[phase] += 1

        detail = {
            "item_id": item.item_id,
            "benchmark": item.benchmark,
            "domain": meta_by_id[item.item_id].get("domain", "unknown"),
            "is_adversarial": bool(meta_by_id[item.item_id].get("is_adversarial", False)),
            "phase": phase,
            "require_rag": bool(report.get("require_rag", False)),
            "answered_parametrically": answered,
            "thermo_correct": bool(thermo_score.correct) if answered else None,
            "majority_correct": bool(majority["correct"]),
            "majority_predicted": majority["predicted"],
            "oracle_calls": report.get("oracle_calls", 0),
            "iterations": report.get("iterations", 0),
            "evidence_request_reason": report.get("evidence_request_reason"),
        }

        if answered:
            answered_items.append(item)
            answered_reports.append(report)

        if evidence_oracle and report.get("require_rag", False):
            evidence_resp = evidence_oracle.ask(build_eval_prompt(item.question, item.context))
            evidence_verdict = phi(evidence_resp.extracted)
            evidence_report = {
                "question": item.question,
                "iterations": report.get("iterations", 0),
                "oracle_calls": report.get("oracle_calls", 0) + 1,
                "total_cost_usd": round(report.get("total_cost_usd", 0.0) + evidence_resp.cost_usd, 6),
                "final_V": report.get("final_V"),
                "final_H": report.get("final_H"),
                "final_D": report.get("final_D"),
                "V_reduction": report.get("V_reduction"),
                "is_converging": report.get("is_converging"),
                "open_candidates": report.get("open_candidates", 0),
                "falsified_count": report.get("falsified_count", 0),
                "top_claims": [[f"[{evidence_verdict.fingerprint()[:8]}] pol={evidence_verdict.polarity}", float(evidence_resp.extracted.get("confidence", 0.0) or 0.0)]],
                "known_negations": report.get("known_negations", []),
                "decisions": report.get("decisions", []) + ["evidence_backfill"],
                "require_rag": False,
                "refuse_parametric_verdict": False,
                "evidence_request_reason": report.get("evidence_request_reason"),
                "trajectory": report.get("trajectory", []),
                "final_entropy": report.get("final_entropy"),
                "entropy_trajectory": report.get("entropy_trajectory", []),
                "state_hash": report.get("state_hash"),
            }
            evidence_augmented_items.append(item)
            evidence_augmented_reports.append(evidence_report)
            detail["evidence_used"] = True
            detail["evidence_correct"] = evidence_verdict.polarity == item.ground_truth
            detail["evidence_predicted"] = evidence_verdict.polarity
        else:
            detail["evidence_used"] = False

        details.append(detail)
        maybe_progress(index, total, args.progress_every, "thermo-router-eval")

    overall_scores = [score_one(item, report) for item, report in zip(items, overall_reports)]
    answered_summary = score_policy_subset(answered_items, answered_reports)
    overall_etr = effective_truth_rate(items, overall_reports, score_results=overall_scores)

    flagged = [row for row in details if row["require_rag"]]
    accepted = [row for row in details if row["answered_parametrically"]]
    majority_wrong = [row for row in details if not row["majority_correct"]]
    flagged_majority_wrong = [row for row in flagged if not row["majority_correct"]]

    summary = {
        "n_items": total,
        "backend": args.backend,
        "router_mode": args.router_mode,
        "thermo_lambda": args.thermo_lambda,
        "thermo_calibration": args.thermo_calibration,
        "trust_threshold_high": args.trust_threshold_high,
        "trust_threshold_low": args.trust_threshold_low,
        "hallucination_threshold": args.hallucination_threshold,
        "majority_accuracy": round(sum(1 for row in details if row["majority_correct"]) / total, 4) if total else 0.0,
        "parametric_accuracy": round(sum(1 for result in overall_scores if result.correct) / total, 4) if total else 0.0,
        "parametric_etr": overall_etr["etr_rate"],
        "guardrail_coverage": round(len(accepted) / total, 4) if total else 0.0,
        "guardrail_require_rag_rate": round(len(flagged) / total, 4) if total else 0.0,
        "guardrail_accuracy_on_answered": answered_summary["accuracy"],
        "guardrail_etr_on_answered": answered_summary["etr_rate"],
        "guardrail_false_trust_rate": answered_summary["false_trust_rate"],
        "guardrail_vs_majority_same_coverage_delta": round(
            answered_summary["accuracy"] - (
                (sum(1 for row in accepted if row["majority_correct"]) / len(accepted)) if accepted else 0.0
            ),
            4,
        ),
        "flagged_majority_error_rate": round(len(flagged_majority_wrong) / len(flagged), 4) if flagged else 0.0,
        "accepted_majority_error_rate": round(sum(1 for row in accepted if not row["majority_correct"]) / len(accepted), 4) if accepted else 0.0,
        "majority_error_intercept_rate": round(len(flagged_majority_wrong) / len(majority_wrong), 4) if majority_wrong else 0.0,
        "phase_counts": dict(phase_counts),
        "phase_flagged_counts": dict(phase_flagged),
    }

    result = {
        "summary": summary,
        "answered_policy": answered_summary,
        "evidence_backfill": None,
        "details": details,
    }

    if evidence_oracle:
        combined_items = list(answered_items) + list(evidence_augmented_items)
        combined_reports = list(answered_reports) + list(evidence_augmented_reports)
        combined_scores = [score_one(item, report) for item, report in zip(combined_items, combined_reports)]
        combined_etr = effective_truth_rate(combined_items, combined_reports, score_results=combined_scores)
        result["evidence_backfill"] = {
            "n_answered": len(combined_items),
            "coverage": round(len(combined_items) / total, 4) if total else 0.0,
            "accuracy": round(sum(1 for score in combined_scores if score.correct) / len(combined_scores), 4) if combined_scores else 0.0,
            "etr_rate": combined_etr["etr_rate"],
            "extra_evidence_calls": len(evidence_augmented_reports),
        }

    output_path = ROOT / args.output
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
