# Pre-registration: Trust Stability Forecasting (TSF)

**Status: PRE-REGISTERED. SYNTHETIC HARNESS ONLY. No real-system evidence.**

TSF asks whether a forecaster can predict near-future *destabilization* of
REMORA's trust signal from its recent history. This directory contains a
synthetic-trace harness for developing and unit-testing the forecasting code.

> **Synthetic harness only. Not evidence of predictive destabilization.**
> Any output here is generated from a synthetic trace generator and says nothing
> about REMORA's behavior on real action logs.

## Baselines (frozen)

| ID | Description |
|----|-------------|
| B1 | Persistence (predict next = last value). |
| B2 | Moving-average forecaster. |
| B3 | Random/shuffle control (must NOT be beaten by chance). |

A candidate forecaster is only interesting if it beats B1 and B2 and clearly
beats B3, on held-out synthetic traces, by a pre-registered margin.

## Metrics

Forecast horizon h ∈ {1, 3, 5} steps. Primary: AUROC for the binary
"destabilization within h" label. Secondary: Brier score, lead time.

## Protocol

Fixed seed (42); train/held-out split on disjoint trace families; thresholds
locked on train. Bootstrap 95% CIs on AUROC differences vs each baseline.

## Claim rule

No predictive-stability claim of any kind, even on synthetic data, may leave this
directory. Synthetic results are for code validation only. Real-system claims
require a separate, pre-registered study on real action logs.
