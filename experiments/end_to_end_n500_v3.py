from __future__ import annotations

# Author: Stian Skogbrott
# License: Apache-2.0
"""End-to-end N500 policy evaluation (v3) — aggregate metrics from stored artifacts.

Loads ``results/thermodynamic_eval_n500_calibrated_results.json`` (544 items),
builds a PolicyObservation for each item from the thermodynamic fields already
stored in that artifact, runs RemoraDecisionEngine.decide(), and reports
aggregate policy metrics.

No live oracle calls are made.  Fields that genuinely require oracle responses
or live Remora.run() are reported as null with an accompanying reason_* string.

Writes results to ``results/end_to_end_n500_v3.json``.
"""

import json
import random
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INPUT_ARTIFACT = "results/thermodynamic_eval_n500_calibrated_results.json"
_OUTPUT_PATH = _REPO_ROOT / "results" / "end_to_end_n500_v3.json"


def run() -> dict:
    """Execute the v3 evaluation and return the results dict."""
    from remora.policy import PolicyObservation, RemoraDecisionEngine
    from remora.policy.calibration import compute_temperature_threshold

    artifact_path = _REPO_ROOT / _INPUT_ARTIFACT
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    items = raw["items"]

    # Calibrate temperature threshold from N500 data (T* ≈ 0.1972 at 18% coverage)
    temperature_threshold = compute_temperature_threshold(
        n500_data_path=artifact_path, target_coverage=0.18
    )
    engine = RemoraDecisionEngine(temperature_threshold=temperature_threshold)

    # Per-action tallies
    counts: dict[str, int] = {"accept": 0, "verify": 0, "abstain": 0, "escalate": 0}
    # Per-action correctness (majority_correct label)
    correct_by_action: dict[str, list[bool]] = {k: [] for k in counts}
    confidences: list[float] = []

    for item in items:
        obs = PolicyObservation(
            question=item.get("item_id", ""),
            phase=item.get("phase"),
            trust_score=item.get("trust_score"),
            temperature=item.get("temperature"),
            order_parameter=item.get("order_parameter"),
            susceptibility=item.get("susceptibility"),
            hallucination_bound=item.get("hallucination_bound"),
            weighted_support=item.get("trust_score"),  # proxy
        )
        report = engine.decide(obs)
        action_key = report.action.value  # "accept" | "verify" | "abstain" | "escalate"
        counts[action_key] += 1

        mc = item.get("majority_correct")
        if isinstance(mc, bool):
            correct_by_action[action_key].append(mc)

        if report.confidence is not None:
            confidences.append(report.confidence)

    n_items = len(items)
    accepted = counts["accept"]
    verified = counts["verify"]
    abstained = counts["abstain"]
    escalated = counts["escalate"]

    def _accuracy(label_list: list[bool]) -> float | None:
        if not label_list:
            return None
        return sum(1 for v in label_list if v) / len(label_list)

    acc_accept = _accuracy(correct_by_action["accept"])
    acc_verify = _accuracy(correct_by_action["verify"])
    acc_abstain = _accuracy(correct_by_action["abstain"])
    acc_escalate = _accuracy(correct_by_action["escalate"])

    def _risk(acc: float | None) -> float | None:
        return None if acc is None else 1.0 - acc

    # False trust rate: among accepted items, fraction that are wrong
    def _false_trust_rate() -> float | None:
        if not correct_by_action["accept"]:
            return None
        wrong = sum(1 for v in correct_by_action["accept"] if not v)
        return wrong / len(correct_by_action["accept"])

    # False refusal rate: among abstained items, fraction that are correct
    def _false_refusal_rate() -> float | None:
        if not correct_by_action["abstain"]:
            return None
        correct = sum(1 for v in correct_by_action["abstain"] if v)
        return correct / len(correct_by_action["abstain"])

    mean_confidence = (sum(confidences) / len(confidences)) if confidences else None

    result: dict = {
        "n_items": n_items,
        "accepted": accepted,
        "verified": verified,
        "abstained": abstained,
        "escalated": escalated,
        "action_distribution": {
            "accept": accepted / n_items if n_items else 0.0,
            "verify": verified / n_items if n_items else 0.0,
            "abstain": abstained / n_items if n_items else 0.0,
            "escalate": escalated / n_items if n_items else 0.0,
        },
        "accuracy_by_action": {
            "accept": acc_accept,
            "verify": acc_verify,
            "abstain": acc_abstain,
            "escalate": acc_escalate,
        },
        "risk_by_action": {
            "accept": _risk(acc_accept),
            "verify": _risk(acc_verify),
            "abstain": _risk(acc_abstain),
            "escalate": _risk(acc_escalate),
        },
        "false_trust_rate": _false_trust_rate(),
        "false_refusal_rate": _false_refusal_rate(),
        "evidence_calls": None,
        "reason_evidence_calls_unavailable": (
            "N500 artifact lacks question text and evidence blobs required by EvidenceOracleV3"
        ),
        "evidence_answered": None,
        "evidence_abstained": None,
        "evidence_corrected_count": None,
        "reason_evidence_corrected_unavailable": (
            "per-oracle response not stored individually in N500 artifact"
        ),
        "mean_policy_confidence": mean_confidence,
        "assurance_trace_coverage": None,
        "reason_assurance_unavailable": (
            "N500 artifact contains pre-computed consensus; no live Remora.run() was executed"
        ),
        "temperature_threshold": temperature_threshold,
        "policy_engine_version": "RemoraDecisionEngine-v2-temperature-calibrated",
        "policy_version": "RemoraDecisionEngine-v3",
        "in_sample_calibration_warning": (
            "Temperature threshold is derived from the same N500 artifact used for this evaluation."
        ),
        "input_artifact": _INPUT_ARTIFACT,
        "limitations": [
            "Policy decisions derived from thermodynamic fields only; no live oracle calls.",
            "Evidence oracle not evaluated (no question text or evidence blobs in N500 artifact).",
            "Assurance trace requires live Remora.run(); not available from stored artifact.",
            "All 544 items run through deterministic policy engine from stored fields.",
        ],
    }

    return result


def main() -> None:
    result = run()

    # Print summary
    n = result["n_items"]
    acc = result["accepted"]
    ver = result["verified"]
    abs_ = result["abstained"]
    esc = result["escalated"]
    ftr = result["false_trust_rate"]
    acc_on_accept = result["accuracy_by_action"]["accept"]

    print("=== REMORA N500 End-to-End Policy Evaluation (v3) ===")
    print(f"Total items : {n}")
    print(
        f"Accepted    : {acc}  ({100 * acc / n:.1f}%)  |  "
        f"Verified : {ver}  ({100 * ver / n:.1f}%)"
    )
    print(
        f"Abstained   : {abs_}  ({100 * abs_ / n:.1f}%)  |  "
        f"Escalated : {esc}  ({100 * esc / n:.1f}%)"
    )
    if acc_on_accept is not None:
        print(f"Accuracy on accepted items : {acc_on_accept:.4f}")
    else:
        print("Accuracy on accepted items : N/A (no items accepted)")
    if ftr is not None:
        print(f"False trust rate           : {ftr:.4f}")
    else:
        print("False trust rate           : N/A (no items accepted)")
    print()

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Results written to: {_OUTPUT_PATH}")


# ---------------------------------------------------------------------------
# Held-out split evaluation (A1 — addresses in-sample threshold concern)
# ---------------------------------------------------------------------------

_HOLDOUT_OUTPUT_PATH = _REPO_ROOT / "results" / "end_to_end_n500_v3_holdout.json"


def run_holdout(cal_fraction: float = 0.50, seed: int = 42) -> dict:
    """Held-out split evaluation: threshold calibrated on cal set, evaluated on test set.

    Splits the 544-item artifact into a calibration partition and a held-out
    test partition.  The temperature threshold is derived *only* from the
    calibration split and then applied without adjustment to the test split.
    This eliminates the in-sample threshold-selection bias present in ``run()``.

    Parameters
    ----------
    cal_fraction:
        Fraction of items used for threshold calibration (default 0.50 → 272 cal / 272 test).
    seed:
        Random seed for reproducible split.

    Returns
    -------
    dict with keys: calibration_split, test_split, methodology_note.
    """
    from remora.policy import PolicyObservation, RemoraDecisionEngine
    from remora.policy.calibration import compute_temperature_threshold

    artifact_path = _REPO_ROOT / _INPUT_ARTIFACT
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    items = raw["items"]

    # Deterministic shuffle + split
    rng = random.Random(seed)
    shuffled = items[:]
    rng.shuffle(shuffled)
    n_cal = int(len(shuffled) * cal_fraction)
    cal_items = shuffled[:n_cal]
    test_items = shuffled[n_cal:]

    # --- Calibration split: find threshold ---
    import tempfile

    cal_artifact = {"items": cal_items}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(cal_artifact, tmp)
        tmp_path = Path(tmp.name)

    try:
        temperature_threshold = compute_temperature_threshold(
            n500_data_path=tmp_path, target_coverage=0.18
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    engine = RemoraDecisionEngine(temperature_threshold=temperature_threshold)

    def _evaluate_partition(partition: list[dict]) -> dict:
        counts: dict[str, int] = {"accept": 0, "verify": 0, "abstain": 0, "escalate": 0}
        correct_by_action: dict[str, list[bool]] = {k: [] for k in counts}
        for item in partition:
            obs = PolicyObservation(
                question=item.get("item_id", ""),
                phase=item.get("phase"),
                trust_score=item.get("trust_score"),
                temperature=item.get("temperature"),
                order_parameter=item.get("order_parameter"),
                susceptibility=item.get("susceptibility"),
                hallucination_bound=item.get("hallucination_bound"),
                weighted_support=item.get("trust_score"),
            )
            report = engine.decide(obs)
            key = report.action.value
            counts[key] += 1
            mc = item.get("majority_correct")
            if isinstance(mc, bool):
                correct_by_action[key].append(mc)

        n = len(partition)

        def _acc(lst: list[bool]) -> float | None:
            return sum(lst) / len(lst) if lst else None

        accepted = counts["accept"]
        coverage = accepted / n if n else 0.0
        acc_accept = _acc(correct_by_action["accept"])
        return {
            "n": n,
            "counts": counts,
            "coverage_accept": coverage,
            "accuracy_on_accepted": acc_accept,
            "false_trust_rate": (
                sum(1 for v in correct_by_action["accept"] if not v)
                / len(correct_by_action["accept"])
                if correct_by_action["accept"]
                else None
            ),
        }

    cal_metrics = _evaluate_partition(cal_items)
    test_metrics = _evaluate_partition(test_items)

    result = {
        "methodology": "held_out_split",
        "methodology_note": (
            "Temperature threshold derived exclusively from calibration partition "
            f"({n_cal} items, seed={seed}). Test partition ({len(test_items)} items) "
            "is held out during threshold selection. This eliminates the in-sample "
            "threshold-selection bias reported in end_to_end_n500_v3.json."
        ),
        "cal_fraction": cal_fraction,
        "seed": seed,
        "temperature_threshold_from_cal": temperature_threshold,
        "total_items": len(items),
        "calibration_split": cal_metrics,
        "test_split": test_metrics,
        "input_artifact": _INPUT_ARTIFACT,
        "limitations": [
            "Policy decisions derived from thermodynamic fields only; no live oracle calls.",
            "Split is random; results may vary slightly across seeds.",
            "cal_fraction=0.50 leaves ~272 test items; CIs are still wide.",
        ],
    }
    return result


def main_holdout() -> None:
    result = run_holdout()
    test = result["test_split"]
    print("=== REMORA N500 Held-Out Evaluation ===")
    print(f"Threshold calibrated on : {result['calibration_split']['n']} items")
    print(f"Evaluated on (held-out) : {test['n']} items")
    print(f"Coverage (accept rate)  : {test['coverage_accept']:.1%}")
    acc = test["accuracy_on_accepted"]
    print(f"Accuracy on accepted    : {acc:.4f}" if acc is not None else "Accuracy: N/A")
    ftr = test["false_trust_rate"]
    print(f"False trust rate        : {ftr:.4f}" if ftr is not None else "FTR: N/A")
    print(f"Temperature threshold   : {result['temperature_threshold_from_cal']:.4f}")
    print()
    _HOLDOUT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HOLDOUT_OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Results written to: {_HOLDOUT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
