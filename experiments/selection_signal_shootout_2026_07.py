# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""EXPLORATORY: selection-signal and aggregation shootout on the 2026-07 round data.

Status: exploratory / hypothesis-generating — NOT confirmatory. Nothing in
this artifact may be quoted as a pre-registered result; its purpose is to
pick candidates for the next round's pre-registration (SAP v3).

Motivated by the 2026-07 round findings and the external review:
  (a) majority vote (85.3 %) underperformed the best single model (87.5 %),
  (b) the discrete phase routing helped 0 / hurt 13 items,
  (c) the temperature signal's edge over SIMPLER selection baselines was
      never measured at matched coverage.

This script answers (a) and (c) offline, with zero new API calls: every
oracle response is read back from the round's .remora_cache.json (a cache
miss SKIPS the item and is counted — it never triggers a live call).

Protocol: the same group-aware stratified 80/20 split (seed 42) as the H1'
holdout. Every supervised quantity (per-oracle competence weights, signal
thresholds) is fit on the TRAINING split only; the holdout is touched once
per method for evaluation.

Methods under test
------------------
Selection signals (rank items, accept top coverage-target fraction; the
prediction evaluated among accepted is the majority vote, as in H1'):
  neg_temperature   — the round's pre-registered signal (from the thermo artifact)
  margin            — majority margin (winner votes minus runner-up, tiebreak mean confidence)
  mean_confidence   — mean of the three oracles' self-reported confidences
  single_confidence — the strongest single model's own confidence
  trust_score       — the engine's trust score (thermo artifact)
  neg_susceptibility— negative chi (thermo artifact)
  random            — seeded random ranking (floor)

Aggregators (predict on every answered item; accuracy over the holdout):
  majority          — unweighted vote (round baseline)
  best_single       — strongest single model alone
  confidence_weighted — votes weighted by self-reported confidence
  log_odds_weighted — Nitzan-Paroush optimal weights w_i = log(a_i/(1-a_i)),
                      per-oracle accuracies a_i fit on the TRAINING split
  dawid_skene       — unsupervised EM competence estimation (fit on training
                      split votes only, no labels)

Usage: python experiments/selection_signal_shootout_2026_07.py
Output: results/selection_signal_shootout_2026_07.json (+ provenance sidecar)
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from remora.benchmarks.loaders import BenchmarkItem  # noqa: E402
from remora.canonical import phi  # noqa: E402
from remora.oracles.factory import build_benchmark_oracle  # noqa: E402
from remora.oracles.families import CROSS_FAMILY_CF_MODELS  # noqa: E402
from remora.persistence import Store  # noqa: E402
from remora.scoring import _polarity_match  # noqa: E402

from experiments.ablation_v2 import build_eval_prompt, load_benchmark  # noqa: E402
from selective_n500_holdout import _wilson, stratified_split  # noqa: E402

THERMO_PATH = ROOT / "results" / "thermodynamic_eval_n500_uncalibrated_results.json"
OUT_PATH = ROOT / "results" / "selection_signal_shootout_2026_07.json"
CACHE_PATH = ROOT / ".remora_cache.json"

SEED = 42
HOLDOUT_FRACTION = 0.20
COVERAGE_TARGETS = [0.10, 0.18, 0.30]  # 0.18 = the pre-registered H1' point
BENCHMARK_MODULE = "remora.benchmarks.extended_v2_n500"
STRONG_SINGLE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def _cache_lookup(store: Store, oracle_name: str, prompt: str) -> dict | None:
    key = hashlib.sha256(f"{oracle_name}::{prompt}".encode()).hexdigest()[:32]
    return store.get(key)


def _confidence(extracted: dict) -> float:
    try:
        c = float(extracted.get("confidence", 0.5))
    except (TypeError, ValueError):
        return 0.5
    return min(1.0, max(0.0, c))


def build_table() -> tuple[list[dict], int]:
    """Reconstruct the per-item x per-oracle vote table strictly from cache."""
    items, _meta, _ = load_benchmark(BENCHMARK_MODULE)
    thermo = {
        it["item_id"]: it
        for it in json.loads(THERMO_PATH.read_text(encoding="utf-8"))["items"]
    }
    store = Store(str(CACHE_PATH))
    oracle_names = [build_benchmark_oracle("cloudflare", m).name for m in CROSS_FAMILY_CF_MODELS]

    rows: list[dict] = []
    missing = 0
    for item in items:
        assert isinstance(item, BenchmarkItem)
        prompt = build_eval_prompt(item)
        votes, confs = [], []
        ok = True
        for name in oracle_names:
            cached = _cache_lookup(store, name, prompt)
            if cached is None:
                ok = False
                break
            verdict = phi(cached["extracted"])
            votes.append(verdict.polarity)
            confs.append(_confidence(cached["extracted"]))
        th = thermo.get(item.item_id)
        if not ok or th is None:
            missing += 1
            continue
        rows.append({
            "item_id": item.item_id,
            "benchmark": item.benchmark,
            "ground_truth": item.ground_truth,
            "votes": votes,
            "confs": confs,
            "correct_per_oracle": [
                _polarity_match(v, item.ground_truth) for v in votes
            ],
            "temperature": th["temperature"],
            "trust_score": th["trust_score"],
            "susceptibility": th["susceptibility"],
            "majority_correct": th["majority_correct"],
        })
    return rows, missing


# ── Aggregators ─────────────────────────────────────────────────────────────

def _vote_weighted(row: dict, weights: list[float]):
    tally: dict = {}
    for v, w in zip(row["votes"], weights):
        tally[v] = tally.get(v, 0.0) + w
    return max(tally, key=lambda k: tally[k])


def agg_majority(row: dict, _ctx) -> object:
    return _vote_weighted(row, [1.0, 1.0, 1.0])


def agg_best_single(row: dict, ctx) -> object:
    return row["votes"][ctx["single_idx"]]


def agg_confidence_weighted(row: dict, _ctx) -> object:
    return _vote_weighted(row, row["confs"])


def agg_log_odds(row: dict, ctx) -> object:
    return _vote_weighted(row, ctx["log_odds_weights"])


def agg_dawid_skene(row: dict, ctx) -> object:
    return _vote_weighted(row, ctx["ds_weights"])


def fit_log_odds_weights(train: list[dict]) -> list[float]:
    """Nitzan-Paroush optimal jury weights from TRAIN accuracies (clipped)."""
    n_oracles = len(train[0]["votes"])
    weights = []
    for i in range(n_oracles):
        a = sum(1 for r in train if r["correct_per_oracle"][i]) / len(train)
        a = min(0.999, max(0.001, a))
        weights.append(math.log(a / (1 - a)))
    return weights


def fit_dawid_skene(train: list[dict], iters: int = 30) -> list[float]:
    """Binary Dawid-Skene-style EM WITHOUT labels: estimate per-oracle
    competence from agreement structure alone; returns log-odds weights.
    Votes of None are ignored (no evidence)."""
    n_oracles = len(train[0]["votes"])
    comp = [0.7] * n_oracles  # init: better than chance
    for _ in range(iters):
        # E-step: posterior that the majority polarity is the true one.
        post = []
        for r in train:
            tally: dict = {}
            for v, c in zip(r["votes"], comp):
                if v is None:
                    continue
                w = math.log(max(c, 1e-3) / max(1 - c, 1e-3))
                tally[v] = tally.get(v, 0.0) + w
            if not tally:
                post.append((None, 0.5))
                continue
            best = max(tally, key=lambda k: tally[k])
            z = sum(math.exp(s) for s in tally.values())
            post.append((best, math.exp(tally[best]) / z if z else 0.5))
        # M-step: competence = weighted agreement with the posterior label.
        for i in range(n_oracles):
            num = den = 0.0
            for r, (label, p) in zip(train, post):
                if label is None or r["votes"][i] is None:
                    continue
                num += p if r["votes"][i] == label else (1 - p)
                den += 1.0
            comp[i] = min(0.999, max(0.001, num / den)) if den else 0.5
    return [math.log(c / (1 - c)) for c in comp]


# ── Selection signals ───────────────────────────────────────────────────────

def signal_values(row: dict, rng: random.Random, ctx) -> dict[str, float]:
    votes = row["votes"]
    tally: dict = {}
    for v in votes:
        tally[v] = tally.get(v, 0) + 1
    counts = sorted(tally.values(), reverse=True)
    margin = counts[0] - (counts[1] if len(counts) > 1 else 0)
    return {
        "neg_temperature": -row["temperature"],
        "margin": margin + 0.001 * (sum(row["confs"]) / len(row["confs"])),
        "mean_confidence": sum(row["confs"]) / len(row["confs"]),
        "single_confidence": row["confs"][ctx["single_idx"]],
        "trust_score": row["trust_score"],
        "neg_susceptibility": -row["susceptibility"],
        "random": rng.random(),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    rows, missing = build_table()
    print(f"rows={len(rows)} (cache-missing/skipped: {missing})")
    if missing > len(rows) * 0.05:
        print("FATAL: more than 5% of items missing from cache — refusing to "
              "report a shootout on partial data")
        return 1

    train, holdout = stratified_split(rows, HOLDOUT_FRACTION, seed=SEED)
    single_idx = [build_benchmark_oracle("cloudflare", m).name
                  for m in CROSS_FAMILY_CF_MODELS].index(
        build_benchmark_oracle("cloudflare", STRONG_SINGLE).name)
    ctx = {
        "single_idx": single_idx,
        "log_odds_weights": fit_log_odds_weights(train),
        "ds_weights": fit_dawid_skene(train),
    }

    # Aggregator comparison (all holdout items).
    aggregators = {
        "majority": agg_majority,
        "best_single": agg_best_single,
        "confidence_weighted": agg_confidence_weighted,
        "log_odds_weighted": agg_log_odds,
        "dawid_skene_unsupervised": agg_dawid_skene,
    }
    agg_results = {}
    print("\n== Aggregators (holdout, n=%d) ==" % len(holdout))
    for name, fn in aggregators.items():
        correct = sum(
            1 for r in holdout if _polarity_match(fn(r, ctx), r["ground_truth"])
        )
        n = len(holdout)
        lo, hi = _wilson(correct, n)
        agg_results[name] = {
            "n": n, "correct": correct, "accuracy": round(correct / n, 4),
            "wilson_ci": [round(lo, 4), round(hi, 4)],
        }
        print(f"  {name:26s} {correct}/{n} = {correct/n:.3f} [{lo:.3f},{hi:.3f}]")

    # Selection-signal comparison at matched coverage targets.
    rng = random.Random(SEED)
    train_sig = [(r, signal_values(r, rng, ctx)) for r in train]
    hold_sig = [(r, signal_values(r, rng, ctx)) for r in holdout]
    signal_names = list(train_sig[0][1].keys())

    sel_results: dict[str, dict] = {s: {} for s in signal_names}
    for cov in COVERAGE_TARGETS:
        k = max(1, round(len(train) * cov))
        print(f"\n== Selection @ coverage target {cov:.2f} "
              f"(tau from train, majority prediction, holdout n={len(holdout)}) ==")
        for s in signal_names:
            ranked = sorted(train_sig, key=lambda p: p[1][s], reverse=True)
            tau = ranked[k - 1][1][s]
            accepted = [r for r, v in hold_sig if v[s] >= tau]
            n_acc = len(accepted)
            correct = sum(1 for r in accepted if r["majority_correct"])
            acc = correct / n_acc if n_acc else None
            lo, hi = _wilson(correct, n_acc) if n_acc else (0.0, 1.0)
            sel_results[s][str(cov)] = {
                "tau": round(tau, 6), "n_accepted": n_acc,
                "correct": correct,
                "accuracy_accepted": round(acc, 4) if acc is not None else None,
                "coverage_achieved": round(n_acc / len(holdout), 4),
                "wilson_ci": [round(lo, 4), round(hi, 4)],
            }
            acc_s = f"{acc:.3f}" if acc is not None else "-"
            print(f"  {s:20s} acc={acc_s} ({correct}/{n_acc}) "
                  f"cov={n_acc/len(holdout):.2f}")

    out = {
        "status": "exploratory",
        "warning": (
            "EXPLORATORY / hypothesis-generating only. Fit on the training "
            "split, evaluated once per method on the holdout, but methods "
            "and coverage grid were chosen AFTER seeing the round's primary "
            "results — nothing here is confirmatory. Use to pre-register "
            "candidates for the next round (SAP v3)."
        ),
        "meta": {
            "script": "experiments/selection_signal_shootout_2026_07.py",
            "benchmark_module": BENCHMARK_MODULE,
            "oracle_source": "offline replay of .remora_cache.json (zero new API calls)",
            "thermo_source": THERMO_PATH.name,
            "seed": SEED,
            "n_rows": len(rows),
            "n_missing_skipped": missing,
            "split": {"n_train": len(train), "n_holdout": len(holdout)},
            "single_model": STRONG_SINGLE,
            "train_fit_quantities": [
                "log_odds_weights (labelled train accuracies)",
                "dawid_skene weights (UNLABELLED train votes)",
                "per-signal tau at each coverage target",
            ],
        },
        "aggregators_holdout": agg_results,
        "selection_signals_holdout": sel_results,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")

    from result_provenance import write_sidecar
    write_sidecar(
        OUT_PATH,
        script="experiments/selection_signal_shootout_2026_07.py",
        inputs={"thermo": THERMO_PATH, "cache": CACHE_PATH},
        random_seeds=[SEED],
        command="python experiments/selection_signal_shootout_2026_07.py",
        extra={"status": "exploratory"},
    )
    print(f"\nSaved: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
