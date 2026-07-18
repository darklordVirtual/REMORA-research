# Experiment 5: χ Iteration Utility

This study tests whether thermodynamic susceptibility χ predicts when the
`C_remora` adaptive-routing condition helps or hurts relative to the
majority-vote baseline (`B_majority`) on the canonical N=302 benchmark.

It improves on [Experiment 4](experiment4_susceptibility_validation.md) by
replacing the binary `D2` condition with the more discriminating `C_remora`
condition, and by computing AUROC rather than band-rate comparisons alone.

## Core Question

Does higher χ concentrate items where `C_remora` degrades relative to the
majority-vote baseline?

The hurt direction is the primary concern: if high-χ items are those most
likely to be hurt by adaptive iteration, χ becomes a useful pre-iteration
gate.

## Operational Definitions

- `helped_by_c`: `C_remora` correct, `B_majority` wrong.
- `hurt_by_c`: `C_remora` wrong, `B_majority` correct.

The AUROC of χ for each binary label is computed via the Wilcoxon rank-sum
formula. Higher AUROC means χ discriminates the positive class better than
chance (0.5).

## Hypothesis

### H1

Items with higher χ should have a higher `hurt_by_c` rate than items with low χ.

### H2

AUROC of χ for predicting `hurt_by_c` should exceed 0.55, a weak but
falsifiable threshold for "χ has predictive content beyond chance."

## Study Vehicle

The runnable script is
[experiments/chi_iteration_utility.py](../../experiments/chi_iteration_utility.py).

It reads:

- per-item χ from
  [results/thermodynamic_eval_results.json](../../results/thermodynamic_eval_results.json)
- per-condition correctness from
  [results/ablation_v2_canonical_results.json](../../results/ablation_v2_canonical_results.json)

and writes output to
[results/chi_iteration_utility_results.json](../../results/chi_iteration_utility_results.json).

## Execution

```bash
cd /path/to/REMORA
export PYTHONPATH=.
python experiments/chi_iteration_utility.py \
    --output results/chi_iteration_utility_results.json
```

## Current Baseline Readout

Results from the committed artifact
[results/chi_iteration_utility_results.json](../../results/chi_iteration_utility_results.json),
run on N=302:

| Metric | Value |
|---|---|
| N items | 302 |
| N helped | 4 (1.3 %) |
| N hurt | 44 (14.6 %) |
| B_majority accuracy | 82.78 % |
| C_remora accuracy | 69.54 % |
| AUROC(help) | **0.5881** |
| AUROC(hurt) | **0.5727** |
| ρ(χ, helped) | 0.035 |
| ρ(χ, hurt) | 0.089 |

### Susceptibility-band breakdown

| Band | N | χ̄ | Help rate | Hurt rate |
|---:|---:|---:|---:|---:|
| 1 (lowest) | 60 | 1.63 | 0.0 % | **10.0 %** |
| 2 | 60 | 2.14 | 1.7 % | 8.3 % |
| 3 | 60 | 3.15 | 3.3 % | **20.0 %** |
| 4 | 60 | 3.23 | 0.0 % | 18.3 % |
| 5 (highest) | 62 | 3.31 | 1.6 % | 16.1 % |

Hurt rates in bands 3–5 exceed the lowest band by 6–10 percentage points.

### Phase breakdown

| Phase | N | Help rate | Hurt rate |
|---|---:|---:|---:|
| ordered | 12 | 0.0 % | 8.3 % |
| critical | 84 | 0.0 % | 8.3 % |
| disordered | 206 | 1.9 % | **17.5 %** |

The disordered phase concentrates the overwhelming majority of hurt cases.

## What Counts as Support

This experiment supports χ as a useful pre-iteration gate if:

1. AUROC(hurt) > 0.55, χ discriminates hurt cases above chance.
2. Hurt rate is higher in the highest-χ band than the lowest.

**Both conditions are met.** AUROC(hurt) = 0.5727 exceeds 0.55. The hurt rate
in the three upper bands (16–20 %) exceeds the lowest band (10 %) consistently.

This is **weak but real predictive content**, χ has a modest, nonzero signal
for iteration harm. It is not strong enough to serve as a hard gate without
further calibration.

## What Would Falsify It

The metric would have no predictive value if:

- AUROC(hurt) ≤ 0.50, indistinguishable from random.
- Hurt rates are flat across susceptibility bands.
- High-χ items show the same accuracy profile as low-χ items.

None of these holds in the current result.

## Interpretation

The study confirms a modest AUROC signal: χ is marginally more likely to be
high on items where `C_remora` hurts relative to majority. The effect is real
but small (AUROC ≈ 0.57, ρ ≈ 0.09).

The disordered phase drives most hurt cases. Using phase classification as an
additional gate (not just χ alone) may improve control signal quality.

The current evidence is **insufficient to recommend χ as a standalone
production gate**. It is sufficient to motivate continued development, with a
focus on higher-contrast benchmarks where helped/hurt class imbalance is less
extreme.

## Limitations

- The helped class is severely imbalanced (4 out of 302 items). AUROC(help) is
  unreliable at this scale.
- N=302 is too small for stable AUROC estimates with this level of class
  imbalance. The hurt AUROC should be reproduced on the N=544 benchmark.
- `C_remora` underperforms majority overall (69.54 % vs 82.78 %) on this
  slice, which may reflect calibration mismatch rather than a structural
  problem with adaptive routing.
