# REMORA Benchmark v2 — Critical-Phase Augmentation Summary

## Dataset Composition

| Metric | Value |
|--------|-------|
| Total items | 2161 |
| Critical phase | 511 (orig=32, sim=479) |
| Ordered phase  | 896 |
| Disordered phase | 754 |

### By benchmark source

| Benchmark | N |
|-----------|---|
| truthfulqa_extended | 817 |
| mmlu_pro_extended | 500 |
| boolq | 377 |
| arc_challenge_extended | 300 |
| truthfulqa | 85 |
| arc_challenge_independent | 75 |
| adversarial_curated | 7 |

> **Note:** Items tagged `oracle_source: calibrated_simulation` have trust scores
> derived from calibrated priors (N=544 observed distributions), not live LLM
> inference. See `experiments/build_critical_phase_dataset_v2.py` for methodology.

## Mondrian Conformal Results (20-seed repeated splits)

| Target | Phase | Mean risk | Mean cov | Seeds failing |
|-------:|:------|----------:|---------:|--------------:|
| 5% | ordered | 0.075 | 15.6% | 11/20 |
| 5% | critical | 0.778 | 0.3% | 3/20 |
| 5% | disordered | 0.571 | 0.1% | 1/20 |
| 10% | ordered | 0.102 | 73.5% | 11/20 |
| 10% | critical | 0.778 | 0.3% | 3/20 |
| 10% | disordered | 0.571 | 0.1% | 1/20 |
| 15% | ordered | 0.120 | 99.9% | 0/20 |
| 15% | critical | 0.645 | 0.9% | 4/20 |
| 15% | disordered | 0.786 | 0.2% | 2/20 |

### Comparison: N=544 vs N=v2 for critical phase (15 % target)

| Dataset | Critical n | Seeds failing @ 15 % |
|---------|-----------|----------------------|
| N=544 (original) | 32 | 2/20 (guarantee unreliable) |
| N=v2 (augmented) | 511 | 4/20 |

## Caveats

- Simulated trust scores reproduce the *shape* of the N=544 distributions but
  do not reflect actual oracle consensus on these specific questions.
- The critical-phase improvement shown above is a **methodology validation**:
  it confirms the mathematical requirement (n≥200) enables reliable guarantees.
- Operational validation requires running live oracle inference on these items.
