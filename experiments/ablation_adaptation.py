"""
Ablation Study: Coupled Online Adaptation in REMORA
=====================================================

Isolates the contribution of each online learning component by running
four conditions over a synthetic dataset calibrated to N500 v2 statistics.

Conditions
----------
  A  Baseline     Fixed λ=1.0, random oracle selection (no learning)
  B  Adapter      ThermodynamicAdapter + random oracle selection
  C  Bandit       Fixed λ=1.0 + OracleBandit (Thompson Sampling)
  D  Coupled      ThermodynamicAdapter + OracleBandit  ← full REMORA

N500 calibration
----------------
The synthetic dataset is calibrated to match the N500 v2 benchmark:
  · 700 claims (matching v2 size)
  · Ordered-phase accuracy:   86.9 %
  · Disordered-phase accuracy: 28.6 %
  · Phase distribution: 40 % ordered, 30 % critical, 30 % disordered
  · Oracle pool: {μ₁=0.85, μ₂=0.70, μ₃=0.30} — matching observed oracle spread

Metric: selective accuracy at 18 % coverage (top-18 % by trust score).
Ground-truth label: the oracle majority's answer is correct with probability
equal to the phase-conditional accuracy.

Usage
-----
    python -m experiments.ablation_adaptation [--rounds N] [--seeds K]

Output
------
    experiments/results/ablation_adaptation.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.adaptation import OracleBandit, ThermodynamicAdapter

# ---------------------------------------------------------------------------
# N500-calibrated simulation parameters
# ---------------------------------------------------------------------------

N_ROUNDS = 700                  # claims per trial (matches N500 v2)
N_SEEDS = 50                    # independent trials for CIs

ORACLE_ACCURACIES = [0.85, 0.70, 0.30]   # μ for each oracle
ORACLE_IDS = ["o_high", "o_mid", "o_low"]
ORACLE_SELECT_N = 2             # query 2 of 3 oracles per claim

PHASE_PROBS = {"ordered": 0.40, "critical": 0.30, "disordered": 0.30}
PHASE_ACCURACY = {"ordered": 0.869, "critical": 0.55, "disordered": 0.286}
PHASE_DISSENSUS = {"ordered": 0.10, "critical": 0.45, "disordered": 0.85}
PHASE_ENTROPY   = {"ordered": 0.20, "critical": 0.60, "disordered": 0.90}

COVERAGE_TARGET = 0.18          # selective accuracy threshold
FIXED_LAMBDA = 1.0              # baseline λ


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _sample_phase(rng: random.Random) -> str:
    r = rng.random()
    if r < PHASE_PROBS["ordered"]:
        return "ordered"
    if r < PHASE_PROBS["ordered"] + PHASE_PROBS["critical"]:
        return "critical"
    return "disordered"


def _trust_score(dissensus: float, entropy: float, lambda_: float) -> float:
    """Simplified trust score: 1 - λ·D - T·H (T=1)."""
    return max(0.0, 1.0 - lambda_ * dissensus - entropy)


def _run_condition(
    use_adapter: bool,
    use_bandit: bool,
    seed: int,
    n_rounds: int = N_ROUNDS,
) -> dict[str, object]:
    """Simulate one trial of a given condition.

    Returns per-round records with:  phase, dissensus, trust_score, correct
    """
    rng = random.Random(seed)
    oracle_rngs = [random.Random(seed + 100 * i) for i in range(len(ORACLE_IDS))]

    adapter = ThermodynamicAdapter(
        initial_lambda=FIXED_LAMBDA,
        learning_rate=0.005,   # gentle — avoids over-adapting on 700 rounds
        ema_alpha=0.05,
        min_samples=50,        # warmup before any λ update
    )
    bandit = OracleBandit(ORACLE_IDS, seed=seed)
    current_lambda = FIXED_LAMBDA

    records = []
    for _ in range(n_rounds):
        phase = _sample_phase(rng)
        true_accuracy = PHASE_ACCURACY[phase]
        d_base = PHASE_DISSENSUS[phase]
        h_base = PHASE_ENTROPY[phase]

        # Oracle selection
        if use_bandit:
            selected = bandit.select(ORACLE_SELECT_N)
        else:
            selected = rng.sample(ORACLE_IDS, ORACLE_SELECT_N)

        # Simulate oracle outcomes
        oracle_correct_votes = 0
        for oid in selected:
            idx = ORACLE_IDS.index(oid)
            if oracle_rngs[idx].random() < ORACLE_ACCURACIES[idx]:
                oracle_correct_votes += 1

        # Ground truth: majority correct with phase-conditional probability
        correct = rng.random() < true_accuracy

        # Add noise to dissensus/entropy based on oracle agreement
        agreement = oracle_correct_votes / ORACLE_SELECT_N
        dissensus = d_base + rng.gauss(0, 0.05) * (1.0 - agreement)
        dissensus = max(0.0, min(1.0, dissensus))
        entropy = h_base + rng.gauss(0, 0.03)
        entropy = max(0.0, min(1.0, entropy))

        trust = _trust_score(dissensus, entropy, current_lambda)

        # Online updates
        if use_adapter:
            adapter.record_outcome(dissensus, entropy, phase, "ACCEPT", correct)  # type: ignore[arg-type]
            current_lambda = adapter.adapted_lambda()
        if use_bandit:
            for oid in selected:
                bandit.update(oid, correct=correct)

        # Gradient signal: (trust - y) * (-D), as in ThermodynamicAdapter
        y = 1.0 if correct else 0.0
        grad_sq = ((trust - y) * (-dissensus)) ** 2

        # Oracle quality at this step (empirical accuracy of selected oracles)
        oracle_acc = oracle_correct_votes / ORACLE_SELECT_N

        records.append(
            {
                "phase": phase,
                "dissensus": dissensus,
                "entropy": entropy,
                "trust_score": trust,
                "correct": correct,
                "lambda": current_lambda,
                "grad_sq": grad_sq,
                "oracle_acc": oracle_acc,
            }
        )

    return {"records": records, "final_lambda": current_lambda}


def _selective_accuracy(records: list[dict], coverage: float) -> dict[str, float]:
    """Accuracy on the top-coverage fraction ranked by trust score."""
    n = len(records)
    k = max(1, int(round(n * coverage)))
    ranked = sorted(records, key=lambda r: r["trust_score"], reverse=True)
    top_k = ranked[:k]
    n_correct = sum(1 for r in top_k if r["correct"])
    acc = n_correct / k
    # Wilson CI
    z = 1.96
    denom = 1 + z * z / k
    centre = (acc + z * z / (2 * k)) / denom
    margin = z * math.sqrt(acc * (1 - acc) / k + z * z / (4 * k * k)) / denom
    return {
        "accuracy": acc,
        "ci_lo": max(0.0, centre - margin),
        "ci_hi": min(1.0, centre + margin),
        "n_selected": k,
    }


def _full_accuracy(records: list[dict]) -> float:
    return sum(1 for r in records if r["correct"]) / len(records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CONDITIONS = {
    "A_baseline": (False, False),
    "B_adapter":  (True,  False),
    "C_bandit":   (False, True),
    "D_coupled":  (True,  True),
}


def run_ablation(n_rounds: int = N_ROUNDS, n_seeds: int = N_SEEDS) -> dict:
    results: dict[str, object] = {
        "n500_calibrated": True,
        "n_rounds": n_rounds,
        "n_seeds": n_seeds,
        "coverage_target": COVERAGE_TARGET,
        "oracle_accuracies": dict(zip(ORACLE_IDS, ORACLE_ACCURACIES)),
        "phase_distribution": PHASE_PROBS,
        "phase_accuracy": PHASE_ACCURACY,
        "conditions": {},
    }

    for label, (use_adapter, use_bandit) in CONDITIONS.items():
        seed_accs: list[float] = []
        seed_sel: list[float] = []
        seed_lambdas: list[float] = []
        seed_grad_var: list[float] = []
        seed_oracle_acc: list[float] = []

        for seed in range(n_seeds):
            trial = _run_condition(use_adapter, use_bandit, seed=seed, n_rounds=n_rounds)
            recs = trial["records"]
            seed_accs.append(_full_accuracy(recs))
            seed_sel.append(_selective_accuracy(recs, COVERAGE_TARGET)["accuracy"])
            seed_lambdas.append(trial["final_lambda"])  # type: ignore[arg-type]
            grad_sqs = [r["grad_sq"] for r in recs]
            seed_grad_var.append(sum(grad_sqs) / len(grad_sqs))
            seed_oracle_acc.append(sum(r["oracle_acc"] for r in recs) / len(recs))

        ns = len(seed_accs)
        mean_acc = sum(seed_accs) / ns
        mean_sel = sum(seed_sel) / ns
        mean_lam = sum(seed_lambdas) / ns
        mean_gv = sum(seed_grad_var) / ns
        mean_oa = sum(seed_oracle_acc) / ns
        std_acc = math.sqrt(sum((x - mean_acc) ** 2 for x in seed_accs) / max(1, ns - 1))
        std_sel = math.sqrt(sum((x - mean_sel) ** 2 for x in seed_sel) / max(1, ns - 1))

        results["conditions"][label] = {  # type: ignore[index]
            "use_adapter": use_adapter,
            "use_bandit": use_bandit,
            "full_accuracy_mean": round(mean_acc, 4),
            "full_accuracy_std": round(std_acc, 4),
            "selective_accuracy_mean": round(mean_sel, 4),
            "selective_accuracy_std": round(std_sel, 4),
            "selective_accuracy_ci95": round(1.96 * std_sel / math.sqrt(ns), 4),
            "final_lambda_mean": round(mean_lam, 4),
            "mean_gradient_variance": round(mean_gv, 6),
            "mean_oracle_accuracy": round(mean_oa, 4),
        }

        print(
            f"  {label}:  sel@18%={mean_sel:.3f}+/-{std_sel:.3f}  "
            f"grad_var={mean_gv:.4f}  oracle_acc={mean_oa:.3f}  lam={mean_lam:.3f}"
        )

    # Coupling synergy: D > B+C-A (super-additive improvement)
    cond = results["conditions"]  # type: ignore[index]
    improvement_A_to_D = cond["D_coupled"]["selective_accuracy_mean"] - cond["A_baseline"]["selective_accuracy_mean"]
    improvement_A_to_B = cond["B_adapter"]["selective_accuracy_mean"] - cond["A_baseline"]["selective_accuracy_mean"]
    improvement_A_to_C = cond["C_bandit"]["selective_accuracy_mean"] - cond["A_baseline"]["selective_accuracy_mean"]
    synergy = improvement_A_to_D - (improvement_A_to_B + improvement_A_to_C)
    results["coupling_synergy"] = round(synergy, 4)
    results["improvement_A_to_D"] = round(improvement_A_to_D, 4)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Ablation: coupled online adaptation")
    parser.add_argument("--rounds", type=int, default=N_ROUNDS)
    parser.add_argument("--seeds", type=int, default=N_SEEDS)
    args = parser.parse_args()

    print(f"Running ablation ({args.rounds} rounds × {args.seeds} seeds)…\n")
    out = run_ablation(args.rounds, args.seeds)

    out_dir = Path("experiments/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ablation_adaptation.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nResults -> {out_path}")
    print(f"Coupling synergy: {out['coupling_synergy']:+.4f}")
    print(f"A->D improvement: {out['improvement_A_to_D']:+.4f}")


if __name__ == "__main__":
    main()
