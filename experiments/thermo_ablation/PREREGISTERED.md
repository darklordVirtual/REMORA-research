# Pre-registration: Thermodynamic-control ablation

**Status: PRE-REGISTERED. No live runs have been executed. No results exist yet.**

This file fixes the analysis plan *before* data collection so the ablation cannot
be tuned after the fact. It does not contain results and must not be cited as one.

## Question

Does REMORA's thermodynamic-control variant improve selective-prediction quality
(lower AURC) over the non-thermo baseline, on the same held-out action log, with
no test-set tuning?

## Variants (frozen)

| ID | Description |
|----|-------------|
| V0 | No thermodynamic control (baseline gate). |
| V1 | Thermo control, fixed temperature. |
| V2 | Thermo control, adaptive temperature (routing on). |
| V3 | V2 + thermodynamic abstention threshold. |
| V4 | V2 + evidence-weighted free energy. |
| V5 | Full thermo (V3 + V4). |

## Primary metric

**AURC** (Area Under the Risk–Coverage curve), lower is better. Computed on the
held-out split only. Risk = error rate among accepted actions; coverage =
fraction accepted.

## Secondary metrics

Selective accuracy at fixed coverage (0.5, 0.8); abstention rate; decision latency.

## Protocol (frozen)

1. Split the action log into train / held-out by a fixed seed (42); never re-split.
2. Any threshold (tau*) is locked on the train split and applied unchanged to held-out.
3. Each variant is scored on the identical held-out split.
4. Report bootstrap 95% CIs (n=1000 resamples) on AURC differences vs V0.
5. A variant "wins" only if its AURC CI upper bound is below V0's point estimate.

## Decision rule for claims

No claim of thermodynamic benefit may be made unless `results_schema.json`-shaped
output exists with `status: ok`, the held-out split was used, and the CI rule
above is satisfied. Negative or null results MUST be reported, not discarded.
