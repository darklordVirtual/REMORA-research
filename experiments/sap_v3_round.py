# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SAP v3 power round: collection and pre-registered analysis (n=1231).

Governed by docs/assurance/statistical_analysis_plan_v3.md (IN FORCE).
Two stages, run as separate processes:

  collect  — ask the frozen Workers AI cross-family trio every corpus
             question (CachedOracle -> resumable), compute per-item
             consensus temperature exactly as the N544 round did, and
             write results/sap_v3_collection.json. No split, no
             calibration, no thresholds happen here.
  analyze  — the pre-registered chain: three-way group-aware split
             (dev 40 / risk-cal 30 / test 30, seed 20260727), isotonic
             confidence calibration on dev, SGR primary + CRC secondary
             thresholds on risk-cal for BOTH the temperature arm and the
             calibrated-confidence baseline, one evaluation pass on the
             untouched test split, claims A/B blocks, paired statistics.
             Writes results/sap_v3_round_results.json.

Usage:
    python experiments/sap_v3_round.py collect
    python experiments/sap_v3_round.py analyze
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
import time
from bisect import bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from remora.canonical import phi  # noqa: E402
from remora.correlation import CorrelationMatrix  # noqa: E402
from remora.genome import Genome  # noqa: E402
from remora.oracles.factory import build_benchmark_oracle  # noqa: E402
from remora.oracles.families import CROSS_FAMILY_CF_MODELS, validate_cross_family  # noqa: E402
from remora.persistence import CachedOracle, Store  # noqa: E402
from remora.scoring import _polarity_match  # noqa: E402
from remora.selective.risk_control import crc_threshold, sgr_threshold  # noqa: E402
from remora.thermodynamics import predict_trust_before_iteration  # noqa: E402

from experiments.ablation_v2 import build_eval_prompt, load_benchmark  # noqa: E402
from experiments.thermodynamic_eval import mean_rho, parse_confidence  # noqa: E402
from experiments.selection_signal_shootout_2026_07 import (  # noqa: E402
    _aurc,
    _mcnemar_exact,
    _tie_epsilon,
    _wilson,
)
from selective_n500_holdout import stratified_split  # noqa: E402

BENCHMARK_MODULE = "remora.benchmarks.sap_v3_n1200"
COLLECTION_PATH = ROOT / "results" / "sap_v3_collection.json"
RESULTS_PATH = ROOT / "results" / "sap_v3_round_results.json"

# SAP v3 frozen parameters — change only via a §8 deviation row.
SEED = 20260727
DEV_STAGE1_HOLDOUT = 0.60   # stage 1: dev = the 40% side
RISKCAL_STAGE2_HOLDOUT = 0.50  # stage 2 on the 60% remainder: 30/30
TARGET_RISK = 0.05
DELTA = 0.10
CRC_ALPHA = 0.05
BOOTSTRAP_B = 2000


# ── Isotonic calibration (pool-adjacent-violators) ─────────────────────────

def pav_fit(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Isotonic (non-decreasing) fit of y on x via pool-adjacent-violators.

    Returns (x_grid, y_hat) usable with pav_predict. Deterministic; ties in
    x are pooled by averaging.
    """
    if len(xs) != len(ys) or not xs:
        raise ValueError("pav_fit needs equal-length non-empty inputs")
    pairs = sorted(zip(xs, ys), key=lambda p: p[0])
    # blocks: [sum_y, count, x_last]
    blocks: list[list[float]] = []
    for x, y in pairs:
        blocks.append([float(y), 1.0, float(x)])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] >= blocks[-1][0] / blocks[-1][1]:
            s, c, _ = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
            blocks[-1][2] = max(blocks[-1][2], x)
    grid = [b[2] for b in blocks]
    vals = [b[0] / b[1] for b in blocks]
    return grid, vals


def pav_predict(grid: list[float], vals: list[float], x: float) -> float:
    """Stepwise-constant prediction from a pav_fit result (clamped)."""
    idx = bisect_right(grid, x)
    if idx >= len(vals):
        return vals[-1]
    return vals[idx]


# ── Collection ─────────────────────────────────────────────────────────────

def collect() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    validate_cross_family(CROSS_FAMILY_CF_MODELS)

    items, _meta, _ = load_benchmark(BENCHMARK_MODULE)
    store = Store(".remora_cache.json")
    oracles = [
        CachedOracle(build_benchmark_oracle("cloudflare", m), store)
        for m in CROSS_FAMILY_CF_MODELS
    ]
    genome = Genome(enable_thermodynamic_control=True)
    correlation = CorrelationMatrix(window_size=500)

    rows = []
    t0 = time.perf_counter()
    for i, item in enumerate(items, 1):
        prompt = build_eval_prompt(item)
        responses = [o.ask(prompt) for o in oracles]
        verdicts = [(r.provider, phi(r.extracted)) for r in responses]
        confidences = [
            parse_confidence(r.extracted.get("confidence", 0.5)) for r in responses
        ]
        rho_bar = mean_rho(correlation, [p for p, _ in verdicts])
        thermo = predict_trust_before_iteration(
            pre_sweep_verdicts=[(p, v.fingerprint()) for p, v in verdicts],
            pre_sweep_confidences=confidences,
            rho_bar=rho_bar,
            lambda_coupling=genome.negation_weight,
            calibration=None,  # UNCALIBRATED, as in SAP v2/v3
        )
        votes = [v.polarity for _, v in verdicts]
        tally: dict = {}
        for v in votes:
            tally[v] = tally.get(v, 0) + 1
        majority = max(tally, key=lambda k: tally[k])
        rows.append({
            "item_id": item.item_id,
            "benchmark": item.benchmark,
            "ground_truth": item.ground_truth,
            "votes": votes,
            "confidences": confidences,
            "correct_per_oracle": [_polarity_match(v, item.ground_truth) for v in votes],
            "majority_prediction": majority,
            "majority_correct": _polarity_match(majority, item.ground_truth),
            "temperature": thermo.temperature,
        })
        if i % 25 == 0 or i == len(items):
            el = time.perf_counter() - t0
            rate = i / el if el else 0
            eta = (len(items) - i) / rate if rate else 0
            print(f"    [collect] {i}/{len(items)} ({100*i/len(items):.0f}%)  "
                  f"{rate:.1f} items/s  ETA {eta/60:.0f} min", flush=True)

    out = {
        "sap": "v3",
        "stage": "collection",
        "benchmark_module": BENCHMARK_MODULE,
        "n_items": len(rows),
        "oracles": list(CROSS_FAMILY_CF_MODELS),
        "backend": "cloudflare",
        "temperature_mode": "uncalibrated",
        "items": rows,
    }
    COLLECTION_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    from result_provenance import write_sidecar
    write_sidecar(
        COLLECTION_PATH,
        script="experiments/sap_v3_round.py",
        inputs={},
        random_seeds=[SEED],
        command="python experiments/sap_v3_round.py collect",
    )
    print(f"Saved: {COLLECTION_PATH}")
    return 0


# ── Analysis (pre-registered) ──────────────────────────────────────────────

def three_way_split(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """SAP v3 §2: dev 40 / risk-cal 30 / test 30, group-aware, seeded."""
    rest, dev = stratified_split(rows, DEV_STAGE1_HOLDOUT, seed=SEED)
    # stage 1 returns (train=40%, holdout=60%): dev is the 40% side.
    dev, rest = rest, dev
    riskcal, test = stratified_split(rest, RISKCAL_STAGE2_HOLDOUT, seed=SEED)
    return dev, riskcal, test


def signals_for(row: dict, calib: dict) -> dict[str, float]:
    """The pre-registered arms: temperature; calibrated mean confidence;
    margin + calibrated-confidence hybrid. Higher = safer to accept."""
    cal_confs = [
        pav_predict(calib["grids"][i], calib["vals"][i], c)
        for i, c in enumerate(row["confidences"])
    ]
    mean_cal = sum(cal_confs) / len(cal_confs)
    tally: dict = {}
    for v in row["votes"]:
        tally[v] = tally.get(v, 0) + 1
    counts = sorted(tally.values(), reverse=True)
    margin = counts[0] - (counts[1] if len(counts) > 1 else 0)
    return {
        "neg_temperature": -row["temperature"],
        "calibrated_mean_confidence": mean_cal,
        "margin_plus_calibrated_confidence": margin + mean_cal,
    }


def _certify_and_test(name: str, riskcal_sv, test_sv, key: str) -> dict:
    scores_cal = [sv[key] + _tie_epsilon(r["item_id"]) for r, sv in riskcal_sv]
    losses_cal = [0 if r["majority_correct"] else 1 for r, _ in riskcal_sv]
    sgr = sgr_threshold(scores_cal, losses_cal, target_risk=TARGET_RISK, delta=DELTA)
    crc = crc_threshold(scores_cal, losses_cal, alpha=CRC_ALPHA)

    def eval_on_test(threshold: float) -> dict:
        acc_items = [
            r for r, sv in test_sv
            if sv[key] + _tie_epsilon(r["item_id"]) >= threshold
        ]
        n_acc = len(acc_items)
        errs = sum(1 for r in acc_items if not r["majority_correct"])
        lo, hi = _wilson(n_acc - errs, n_acc) if n_acc else (0.0, 1.0)
        return {
            "n_accepted": n_acc,
            "errors": errs,
            "selective_risk": round(errs / n_acc, 6) if n_acc else None,
            "unconditional_risk": round(errs / len(test_sv), 6),
            "coverage": round(n_acc / len(test_sv), 4),
            "accuracy_wilson_ci": [round(lo, 4), round(hi, 4)],
        }

    block: dict = {"signal": name}
    block["sgr"] = {
        "certified": sgr.certified,
        "risk_bound": round(sgr.risk_bound, 6),
        "certified_coverage_riskcal": round(sgr.coverage, 4),
        "empirical_risk_riskcal": round(sgr.empirical_risk, 6),
    }
    if sgr.certified:
        block["sgr"]["test"] = eval_on_test(sgr.threshold)
        block["sgr"]["realized_within_budget"] = (
            block["sgr"]["test"]["selective_risk"] is not None
            and block["sgr"]["test"]["selective_risk"] <= TARGET_RISK
        )
    block["crc"] = {
        "certified": crc.certified,
        "criterion": round(crc.risk_bound, 6),
        "certified_coverage_riskcal": round(crc.coverage, 4),
    }
    if crc.certified:
        block["crc"]["test"] = eval_on_test(crc.threshold)
        block["crc"]["realized_within_budget_unconditional"] = (
            block["crc"]["test"]["unconditional_risk"] <= CRC_ALPHA
        )
    return block


def analyze() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    data = json.loads(COLLECTION_PATH.read_text(encoding="utf-8"))
    rows = data["items"]
    dev, riskcal, test = three_way_split(rows)
    print(f"split: dev={len(dev)} riskcal={len(riskcal)} test={len(test)}")

    # ── Development split: everything fitted lives here ────────────────────
    oracle_ids = data["oracles"]
    dev_acc = [
        sum(1 for r in dev if r["correct_per_oracle"][i]) / len(dev)
        for i in range(len(oracle_ids))
    ]
    baseline_single_idx = max(range(len(oracle_ids)), key=lambda i: dev_acc[i])
    calib = {"grids": [], "vals": []}
    for i in range(len(oracle_ids)):
        grid, vals = pav_fit(
            [r["confidences"][i] for r in dev],
            [1.0 if r["correct_per_oracle"][i] else 0.0 for r in dev],
        )
        calib["grids"].append(grid)
        calib["vals"].append(vals)
    p0_dev = sum(1 for r in dev if r["majority_correct"]) / len(dev)

    frozen = {
        "baseline_single_model": oracle_ids[baseline_single_idx],
        "dev_per_oracle_accuracy": [round(a, 4) for a in dev_acc],
        "p0_dev_majority_accuracy": round(p0_dev, 6),
        "calibration_sha256": hashlib.sha256(
            json.dumps(calib, sort_keys=True).encode()
        ).hexdigest(),
    }
    print(f"frozen: single={frozen['baseline_single_model']} p0_dev={p0_dev:.4f}")

    riskcal_sv = [(r, signals_for(r, calib)) for r in riskcal]
    test_sv = [(r, signals_for(r, calib)) for r in test]

    # ── Claim B: certified gates per arm ───────────────────────────────────
    arms = {}
    for key in ("neg_temperature", "calibrated_mean_confidence",
                "margin_plus_calibrated_confidence"):
        arms[key] = _certify_and_test(key, riskcal_sv, test_sv, key)
        s = arms[key]["sgr"]
        print(f"  [{key}] SGR certified={s['certified']} "
              f"cov={s['certified_coverage_riskcal']}"
              + (f" test={s['test']}" if s.get("test") else ""))

    # ── Claim A: ranking quality on the test split ─────────────────────────
    rng = random.Random(SEED)
    aurc = {}
    ranked_flags = {}
    for key in ("neg_temperature", "calibrated_mean_confidence",
                "margin_plus_calibrated_confidence"):
        ranked = sorted(
            test_sv, key=lambda p: p[1][key] + _tie_epsilon(p[0]["item_id"]),
            reverse=True,
        )
        flags = [r["majority_correct"] for r, _ in ranked]
        ranked_flags[key] = flags
        aurc[key] = round(_aurc(flags), 6)

    def paired_bootstrap_aurc(key_a: str, key_b: str) -> dict:
        n = len(test_sv)
        idx_a = {r["item_id"]: sv for r, sv in test_sv}
        diffs = []
        items_list = [r for r, _ in test_sv]
        for _ in range(BOOTSTRAP_B):
            sample = [items_list[rng.randrange(n)] for _ in range(n)]
            def a_of(k):
                ranked = sorted(
                    sample,
                    key=lambda r: idx_a[r["item_id"]][k] + _tie_epsilon(r["item_id"]),
                    reverse=True,
                )
                return _aurc([r["majority_correct"] for r in ranked])
            diffs.append(a_of(key_a) - a_of(key_b))
        diffs.sort()
        lo = diffs[int(0.025 * BOOTSTRAP_B)]
        hi = diffs[int(0.975 * BOOTSTRAP_B) - 1]
        return {"delta_aurc": round(aurc[key_a] - aurc[key_b], 6),
                "bootstrap_ci95": [round(lo, 6), round(hi, 6)]}

    claim_a = {
        "aurc": aurc,
        "temperature_vs_calibrated_confidence": paired_bootstrap_aurc(
            "neg_temperature", "calibrated_mean_confidence"),
        "temperature_vs_margin_hybrid": paired_bootstrap_aurc(
            "neg_temperature", "margin_plus_calibrated_confidence"),
    }

    # ── Aggregation arm (separate; test split; paired McNemar) ─────────────
    def conf_weighted_prediction(row: dict) -> object:
        tally: dict = {}
        for i, v in enumerate(row["votes"]):
            w = pav_predict(calib["grids"][i], calib["vals"][i], row["confidences"][i])
            tally[v] = tally.get(v, 0.0) + w
        return max(tally, key=lambda k: tally[k])

    maj_flags = [bool(r["majority_correct"]) for r, _ in test_sv]
    cw_flags = [
        bool(_polarity_match(conf_weighted_prediction(r), r["ground_truth"]))
        for r, _ in test_sv
    ]
    single_flags = [bool(r["correct_per_oracle"][baseline_single_idx]) for r, _ in test_sv]
    aggregation = {
        "majority_accuracy_test": round(sum(maj_flags) / len(maj_flags), 4),
        "calibrated_confidence_weighted_accuracy_test": round(sum(cw_flags) / len(cw_flags), 4),
        "baseline_single_accuracy_test": round(sum(single_flags) / len(single_flags), 4),
        "mcnemar_cw_vs_majority": _mcnemar_exact(maj_flags, cw_flags),
        "mcnemar_cw_vs_single": _mcnemar_exact(single_flags, cw_flags),
    }

    # ── Fixed-sample secondary: exact binomial for temperature-SGR arm ─────
    def exact_binom_geq(k: int, n: int, p0: float) -> float:
        return sum(
            math.comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
            for i in range(k, n + 1)
        )

    secondary = {}
    sgr_temp = arms["neg_temperature"]["sgr"]
    if sgr_temp.get("test"):
        t = sgr_temp["test"]
        k_corr = t["n_accepted"] - t["errors"]
        secondary["exact_binomial_vs_p0_dev"] = {
            "p0": frozen["p0_dev_majority_accuracy"],
            "n_accepted": t["n_accepted"],
            "correct": k_corr,
            "p_one_sided": round(
                exact_binom_geq(k_corr, t["n_accepted"], p0_dev), 8),
        }

    out = {
        "sap": "v3",
        "stage": "analysis",
        "seed": SEED,
        "collection_source": COLLECTION_PATH.name,
        "split_sizes": {"dev": len(dev), "riskcal": len(riskcal), "test": len(test)},
        "frozen_development_objects": frozen,
        "claim_B_risk_control": arms,
        "claim_A_ranking": claim_a,
        "aggregation_arm": aggregation,
        "secondary": secondary,
        "reporting_note": (
            "Guarantee statements must be quoted with loss definition, data "
            "distribution, calibration sample, model/policy versions, "
            "coverage, and assumptions (SAP v3 §6). SGR zero-coverage is a "
            "legitimate outcome. CRC controls expected UNCONDITIONAL loss."
        ),
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    from result_provenance import write_sidecar
    write_sidecar(
        RESULTS_PATH,
        script="experiments/sap_v3_round.py",
        inputs={"collection": COLLECTION_PATH},
        random_seeds=[SEED],
        command="python experiments/sap_v3_round.py analyze",
    )
    print(f"Saved: {RESULTS_PATH}")
    return 0


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "collect":
        return collect()
    if stage == "analyze":
        return analyze()
    print("usage: sap_v3_round.py collect|analyze")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
