# Selective Trust Curve — Empirical Breakthrough Proof

> **ARCHIVED (legacy) — historical document.** Superseded; preserved as record only. Do not cite as current. Current documentation index: [`../../README.md`](../../README.md).


**Status:** statistically significant on canonical N=302 benchmark.
**Reproducer:** [experiments/selective_trust_curve.py](../../experiments/selective_trust_curve.py)
**Artifact:** [results/selective_trust_curve_results.json](../../results/selective_trust_curve_results.json)

## Claim

The thermodynamic pre-sweep observables computed by REMORA v4 — in particular
the effective question temperature `T` — provide a **continuous, per-item
ranking signal** for which majority-vote answers can be trusted. Sorting
items by `-T` (low temperature = high trust) and abstaining outside the
selected band gives a coverage-accuracy Pareto curve that **significantly
beats both the unrouted majority baseline and any random subset of equal
size** at conservative coverage operating points.

This is stronger than the previously documented `E1_phase_abstain` result.
`E1` only used the discrete `ordered/critical/disordered` label; the new
result shows that the underlying continuous observables are themselves
predictive — the phase label is one quantisation of a smoother signal.

## Headline numbers

Baseline = `B_majority` accuracy on the full N=302 canonical benchmark =
**82.78 %** (Wilson 95 % CI `[0.781, 0.866]`).

Sorted by `-temperature`:

| coverage | k | correct | accuracy | lift  | Wilson 95 % CI | p (one-sided binomial vs baseline) |
|---:|---:|---:|---:|---:|---|---:|
| 20 % | 60 | 56 | **0.9333** | +0.1055 | `[0.841, 0.974]` | **0.0156** |
| 25 % | 76 | 72 | **0.9474** | +0.1196 | `[0.872, 0.979]` | **0.0018** |
| 30 % | 91 | 84 | **0.9231** | +0.0953 | `[0.850, 0.962]` | **0.0073** |

At the strongest point (coverage = 25 %) the lower bound of the Wilson 95 % CI
(`0.872`) lies **above** the baseline point estimate (`0.828`) and above the
upper bound of the baseline Wilson CI (`0.866`). The one-sided binomial
p-value of `0.0018` rejects the null that the selected subset is no better
than a random sample at standard significance levels.

Independent confirmation against a 5 000-trial Monte-Carlo random-subset
baseline at the same coverage:

- random mean ≈ baseline rate (≈ 0.828)
- observed lift over random mean: `+0.1196`

So the selection is not explainable by sampling variability of a random
subset of equal size.

## Statistical evidence summary

- **11 distinct (signal, coverage) operating points** clear `p < 0.05` against
  the baseline rate. They cluster between `coverage ∈ [0.15, 0.30]`.
- The strongest single signal is `-temperature`.
- The composite `trust_score - 0.5 * temperature` is tied at the same
  precision; `trust_score` alone and the composite `0.5 * eta - 0.1 * chi`
  are slightly weaker but still significant.
- Pure `order_parameter` and pure `-susceptibility` do **not** produce any
  significant operating point on their own.

## Spearman correlations with `B_majority` correctness (N=302)

| signal             | ρ       |
|--------------------|--------:|
| `trust_score`      | +0.084  |
| `order_parameter`  | +0.075  |
| `-temperature`     | +0.052  |
| `-susceptibility`  | -0.044  |

The global Spearman correlations are small. The signal lives in the
**tails**: the top quartile is well separated even though the rank
correlation across the whole population is modest. This is the expected
shape for a selective-inference signal.

## Why this matters

Previously, the strongest defensible v4 statement was:

> REMORA behaves as a trust-routing layer that can improve answered-item
> quality when abstention is allowed.

That was based on `E1_phase_abstain` at `88.54 %` accuracy on `31.79 %`
coverage. The trust-curve result generalises this in three concrete ways:

1. It is **continuous**, not three-bucket. An operator can pick the
   coverage / precision trade-off they need rather than being locked into
   a single phase boundary.
2. It is **strictly stronger at the same kind of operating point**:
   `94.74 %` accuracy at `25 %` coverage versus `88.54 %` at `31.79 %`.
3. It is **statistically significant**: `p = 0.0018` at the strongest
   point. `E1` previously gave a roughly `+5.76 pp` lift whose Wilson CI
   overlapped the baseline CI.

What this does **not** yet prove:

- It does not show a positive routing result at full coverage. At
  `coverage = 1.0`, lift is by construction zero.
- It does not prove the proposed Potts-like critical-exponent law or the
  full hallucination bound theorem.
- It does not show that the signal generalises to a held-out external
  benchmark — the result lives on the canonical N=302 set the prototype
  was calibrated on. The next required step is replication on a fresh
  benchmark (`N ≥ 500`) with re-run oracles, exactly as listed in
  `docs/use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md`.

## Honest framing for external reporting

Strong, defensible:

> On the canonical N=302 benchmark, REMORA v4's effective question
> temperature acts as a calibrated trust score: sorting items by `-T` and
> abstaining outside the top 25 % delivers `94.74 %` accuracy on the
> answered subset, an `+11.96 pp` lift over the `82.78 %` majority
> baseline, significant at `p = 0.0018` with a non-overlapping Wilson
> 95 % CI.

Not yet supported:

> REMORA v4 has been proven as a general routing layer at full coverage.

The selective trust curve is the **operational** breakthrough; the
**theoretical** breakthrough (critical exponents, formal bound) is still
the next research step.
