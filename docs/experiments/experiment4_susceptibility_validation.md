# Experiment 4: Susceptibility Validation

This study tests the narrow empirical claim that high susceptibility $\chi$ predicts when iteration does not help.

## Core Question

Given REMORA's thermodynamic pre-sweep readout, does higher susceptibility concentrate items where `D2_balanced` fails to improve over `B_majority`?

This is the cleanest next experiment because it does not depend on speculative theorems. It uses existing canonical benchmark outputs and asks a falsifiable question about one new metric.

## Operational Definitions

- `helped_vs_majority`: D2 is correct and majority is incorrect.
- `hurt_vs_majority`: majority is correct and D2 is incorrect.
- `not_helpful_iteration`: not `helped_vs_majority`.

The main target is deliberately conservative: if high $\chi$ cannot even predict `not_helpful_iteration`, then it is not yet a useful control metric.

## Hypothesis

### H1

Items in the highest susceptibility band should have a higher `not_helpful_iteration` rate than items in the lowest susceptibility band.

### H2

Items in the highest susceptibility band should also show one or more of the following:

- higher `hurt_vs_majority` rate,
- lower D2 accuracy,
- higher routed rate,
- greater concentration of hard or adversarial items.

## Study Vehicle

The runnable study script is [experiments/susceptibility_validation.py](../../experiments/susceptibility_validation.py).

It reads the existing per-item thermodynamic output from [results/thermodynamic_eval_results.json](../../results/thermodynamic_eval_results.json), bins items by susceptibility quantiles, and computes utility metrics for each band.

## Execution

```bash
cd /workspaces/REMORA
export PYTHONPATH=/workspaces/REMORA
python3 experiments/susceptibility_validation.py --output results/susceptibility_validation_results.json
```

## Current Baseline Readout

The first baseline run has now been executed on the current N=302 benchmark, with output stored in [results/susceptibility_validation_results.json](../../results/susceptibility_validation_results.json).

Observed baseline:

- overall `helped_vs_majority`: `0.0 %`
- overall `hurt_vs_majority`: `0.7 %`
- overall `not_helpful_iteration`: `100.0 %`

Susceptibility-band summary after calibration:

- `chi_bin_1`: `n=76`, mean $\chi=1.717$, `not_help=100.0 %`, `hurt=0.0 %`, D2 `79.0 %`
- `chi_bin_2`: `n=75`, mean $\chi=2.563$, `not_help=100.0 %`, `hurt=0.0 %`, D2 `86.7 %`
- `chi_bin_3`: `n=76`, mean $\chi=3.208$, `not_help=100.0 %`, `hurt=2.6 %`, D2 `76.3 %`
- `chi_bin_4`: `n=75`, mean $\chi=3.303$, `not_help=100.0 %`, `hurt=0.0 %`, D2 `86.7 %`

Interpretation: this remains a negative but somewhat more informative result. On the current benchmark, $\chi$ still does **not** validate as a useful predictor of non-helpful iteration, because the label distribution remains too degenerate:

- there are **no helped items**,
- only **two hurt items** in total,
- and `not_helpful_iteration` is therefore trivially `100 %` in every susceptibility band.

The calibrated run does add one weak signal: the only noticeable concentration of hurt cases appears in `chi_bin_3`, which also has the lowest D2 accuracy of any susceptibility band (`76.3 %`). That is not strong enough to count as validation, but it is enough to justify a targeted follow-up on the hurt items rather than discarding $\chi$ entirely.

## What Counts as Support

This experiment supports $\chi$ as a useful metric if the highest susceptibility band shows a materially worse utility profile than the lowest band.

Concrete support signals:

1. Higher `not_helpful_iteration` in high-$\chi$ than low-$\chi$.
2. Higher `hurt_vs_majority` in high-$\chi$ than low-$\chi$.
3. Lower D2 accuracy in high-$\chi$ than low-$\chi$.
4. Stronger concentration of hard/adversarial items in high-$\chi$.

## What Would Falsify It

The metric is not yet useful if one or more of these holds:

- `not_helpful_iteration` is uniformly high in all bands,
- `hurt_vs_majority` does not concentrate in high-$\chi$ regions,
- D2 accuracy is flat across susceptibility bands,
- or the study yields too few helped/hurt examples to discriminate anything.

That last case is important. A negative result here does not necessarily kill susceptibility as a concept. It may simply mean the current benchmark and calibration are too blunt to validate it yet.

That is still the current situation: the study is runnable and honest, and calibration improved the shape of the metric, but the present benchmark slice remains too low-contrast to establish predictive value for $\chi$.