# Author: Stian Skogbrott
# License: Apache-2.0
"""Compute true accuracy-coverage Pareto frontier using phase-aware tau sorting."""
import json
import numpy as np

with open('results/thermodynamic_eval_n500_calibrated_results.json') as f:
    data = json.load(f)

items = data['items']
N = len(items)

ordered    = [r for r in items if r['phase'] == 'ordered']
critical   = [r for r in items if r['phase'] == 'critical']
disordered = [r for r in items if r['phase'] == 'disordered']

print(f"N={N}  ordered={len(ordered)}  critical={len(critical)}  disordered={len(disordered)}")

# Phase-aware sorting - exploit critical-phase trust inversion
ordered_sorted    = sorted(ordered,    key=lambda x: x['trust_score'], reverse=True)
critical_asc      = sorted(critical,   key=lambda x: x['trust_score'], reverse=False)
disordered_sorted = sorted(disordered, key=lambda x: x['trust_score'], reverse=True)
low_tau_crit      = [r for r in critical_asc if r['trust_score'] < 0.1]


def wci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    m = (z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / d
    return c - m, c + m


def show(pool, label):
    print(f"\n=== {label} ===")
    print(f"{'Cov%':<8}{'N':<6}{'Acc%':<8}{'95% CI':<20}phase")
    print("-" * 55)
    correct = 0
    cps = sorted(set(
        [int(c * N) for c in [.05, .10, .15, .18, .20, .23, .25, .30, .35, .40, .50]] +
        [len(pool)]
    ))
    for i, item in enumerate(pool, 1):
        correct += item['d2_correct']
        if i in cps:
            lo, hi = wci(correct, i)
            print(f"{i/N*100:<8.1f}{i:<6}{correct/i*100:<8.1f}[{lo*100:.1f}, {hi*100:.1f}]  {item['phase']}")


# Baseline: global tau descending
global_sorted = sorted(items, key=lambda x: x['trust_score'], reverse=True)
show(global_sorted, "BASELINE: global tau descending (current documented)")

# Strategy A: phase-aware (ordered desc, critical ASC, disordered desc)
pool_A = ordered_sorted + critical_asc + disordered_sorted
show(pool_A, "STRATEGY A: ordered-desc + critical-ASC + disordered-desc")

# Strategy B: ordered + low-tau critical only (tau<0.1) + disordered
pool_B = ordered_sorted + low_tau_crit + disordered_sorted
show(pool_B, "STRATEGY B: ordered + low-tau-critical(tau<0.1) + disordered")

# Strategy C: ordered + low-tau critical only (tau<0.1), stop there
pool_C = ordered_sorted + low_tau_crit
show(pool_C, "STRATEGY C: ordered + low-tau-critical only (no disordered)")

# Phase inversion verification
print("\n--- Critical phase trust inversion ---")
for thresh in [0.05, 0.10, 0.15, 0.20]:
    hi = [r for r in critical if r['trust_score'] >= thresh]
    lo = [r for r in critical if r['trust_score'] < thresh]
    if hi and lo:
        acc_hi = sum(r['d2_correct'] for r in hi) / len(hi)
        acc_lo = sum(r['d2_correct'] for r in lo) / len(lo)
        print(f"tau>={thresh:.2f}: N={len(hi)}, acc={acc_hi:.1%}  |  tau<{thresh:.2f}: N={len(lo)}, acc={acc_lo:.1%}")

# Ordered-only baseline
n_ord = len(ordered)
acc_ord = sum(r['d2_correct'] for r in ordered) / n_ord
lo, hi = wci(sum(r['d2_correct'] for r in ordered), n_ord)
print(f"\nOrdered-only: N={n_ord} ({n_ord/N*100:.1f}%), acc={acc_ord:.1%}, CI=[{lo:.1%}, {hi:.1%}]")
