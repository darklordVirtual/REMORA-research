# Temperature Estimator

This document describes the effective temperature estimation pipeline in
`remora/thermodynamics.py`. The functions documented here are the primary bridge
between oracle observations and the thermodynamic phase classifier.

---

## What temperature means here

Effective temperature `T` is a scalar derived from observable consensus signals.
It measures disorder in the oracle pool, not physical temperature. High `T` means
the oracles disagree or express low confidence; low `T` means strong, consistent
agreement.

The range is approximately `[0.02, 2+]` in practice. The critical temperature
`T_c` is the threshold that separates the ordered phase from the disordered phase
for a given oracle configuration.

---

## `estimate_temperature()`

**Location:** `remora/thermodynamics.py:111`

**Signature:**

```python
def estimate_temperature(
    weighted_distribution: dict[str, float],
    rho_bar: float,
    individual_confidences: list[float],
) -> float:
```

**Inputs:**

| Argument | Type | Description |
|---|---|---|
| `weighted_distribution` | `dict[str, float]` | Probability mass over verdict fingerprints (confidence-weighted or frequency counts, normalised to sum to 1) |
| `rho_bar` | `float` | Mean pairwise correlation among oracle outputs, estimated from the current window |
| `individual_confidences` | `list[float]` | Per-oracle confidence scores for the pre-sweep round |

**Formula:**

Six observable signals are combined with fixed weights:

```
T = 0.30 * H                  # Shannon entropy of verdict distribution
  + 0.20 * (4 * σ²)           # Scaled confidence variance
  + 0.10 * log₂(k_eff)        # Effective answer count (exp of entropy)
  + 0.22 * (1 - mean_conf)    # Confidence deficit
  + 0.18 * (1 - max_support)  # Dissensus (complement of plurality share)
  + 0.08 * ρ̄                  # Correlation-pressure prior
  + 0.02                      # Floor offset
```

where:

- **H** = Shannon entropy = `Σ -p·log₂(p)` over the verdict distribution
- **σ²** = population variance of `individual_confidences`
- **k\_eff** = `exp(H)` — the effective number of competing answers
- **mean\_conf** = mean of `individual_confidences`
- **max\_support** = largest weight in `weighted_distribution`
- **ρ̄** = `rho_bar`, clamped to `[0, 1]`

**Return:** `max(T, 1e-9)` — always strictly positive.

**Design intent:** The formula keeps temperature informative even when all oracles
agree on the pre-sweep. In that regime entropy is zero and max\_support is 1, but
the confidence deficit and correlation-pressure terms still produce a nonzero
temperature that scales with how confident and independent the oracles are.

---

## `apply_temperature_calibration()`

**Location:** `remora/thermodynamics.py:88`

**Signature:**

```python
def apply_temperature_calibration(
    temperature: float,
    calibration: ThermodynamicCalibration | None = None,
) -> float:
```

Applies an affine rescaling to align the raw estimated temperature with empirical
phase boundaries:

```
T' = scale * T + offset
```

The `ThermodynamicCalibration` dataclass carries the calibration parameters. Default
values are `scale=1.0`, `offset=0.0`, which leaves the raw temperature unchanged.

Calibration can be loaded from disk with `load_thermodynamic_calibration(path)` or
constructed from a JSON dict with `thermodynamic_calibration_from_dict(payload)`.

The calibrated temperature is what `classify_phase()` and `trust_score()` receive.

---

## `critical_temperature()`

**Location:** `remora/thermodynamics.py:147`

**Signature:**

```python
def critical_temperature(lambda_coupling: float, rho_bar: float, k: int) -> float:
```

Computes the critical temperature proxy for `k` distinct verdict states:

```
T_c = λ · (1 - ρ̄) / log(k)
```

where:

- **λ** (`lambda_coupling`) — coupling strength, controls how strongly oracle
  disagreement penalises free energy
- **ρ̄** (`rho_bar`) — mean pairwise oracle correlation; higher correlation lowers
  `T_c` (the system is easier to disorder)
- **k** — number of distinct verdict fingerprints observed in the pre-sweep

When `k <= 1`, `T_c = ∞` (the system is trivially ordered; no phase transition is
possible).

---

## Phase classification

`classify_phase()` at `remora/thermodynamics.py:245` maps the calibrated temperature
and order parameter η into one of three phases:

| Phase | Condition |
|---|---|
| `ordered` | `T < T_c` and `η > ordered_min_eta` (default 0.5) |
| `critical` | `|T - T_c| / T_c < tolerance` (default 15 %) |
| `disordered` | otherwise |

The phase label feeds directly into the policy router:

| Phase | Default policy action |
|---|---|
| `ordered` | `ACCEPT` (or `VERIFY` at moderate temperature) |
| `critical` | `VERIFY` |
| `disordered` | `ABSTAIN` or `ESCALATE` |

---

## Trust score

`trust_score()` at `remora/thermodynamics.py:265` collapses all thermodynamic
observables into a single scalar in `[0, 1]`:

```
score = η · (1 - halluc_bound) · phase_weight · fragility_penalty
```

where:

| Factor | Default | Description |
|---|---|---|
| η | — | Order parameter (consensus strength) |
| `halluc_bound` | — | Upper bound on false-consensus rate from `hallucination_bound()` |
| `phase_weight` | 1.0 / 0.5 / 0.1 | Per-phase multiplier (ordered / critical / disordered) |
| `fragility_penalty` | `1 / (1 + χ / chi_scale)` | Penalises high susceptibility (default `chi_scale=10`) |

---

## Free energy

`free_energy()` at `remora/thermodynamics.py:214` computes:

```
F(T) = λD - T·H
```

where `D = 1 - max_support` (dissensus) and `H` is Shannon entropy. This is
analogous to Helmholtz free energy `F = U - TS`. The Lyapunov potential used
elsewhere is the special case `V = F(T = -1)`:

```
V(H, D) = H + λD = F(T=-1; H, D)
```

At `T = -1`, entropy enters with a positive sign (disorder is always penalised),
whereas in `F(T)` the thermal term `T·H` is subtracted (high temperature forgives
disorder).

---

## Integration point

The full pipeline runs in `predict_trust_before_iteration()` at
`remora/thermodynamics.py:349`, which accepts raw pre-sweep verdicts and confidences
and returns a `ThermodynamicState` with all observables populated. This is the
function called by the router when a question arrives.

Test coverage: `tests/test_thermodynamics.py`.
