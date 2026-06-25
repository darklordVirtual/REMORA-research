# Experiment 3: Empirical Phase-Transition Study

This document defines the phase-transition study and records the current N302 and N500 readouts without overstating theory ahead of evidence.

## Goal

Test whether consensus quality in a multi-oracle REMORA system changes sharply across increasing effective question difficulty, and whether thermodynamic observables are useful enough to improve control decisions.

The primary goal is empirical, not theorem-first:

- Measure whether the order parameter $\eta$ drops sharply across temperature bands.
- Measure whether susceptibility-like behavior marks fragile consensus regions.
- Measure whether phase-aware routing adds practical value over majority and D2.

## Why This Study Matters

The current v4 prototype is now calibrated enough to produce a non-trivial critical band on both N302 and N500 artifacts, but it still does not show a decisive routing win over the benchmark baseline. That means the correct next step is still not stronger rhetoric. It is better control policy plus evidence-backfill validation.

If Experiment 3 succeeds, REMORA gains three stronger claims:

1. Consensus quality exhibits transition-like behavior across difficulty.
2. Susceptibility $\chi$ is a useful robustness signal.
3. Phase-aware routing can be calibrated against empirical benchmark outcomes.

## Current Baseline Readout

The first baseline run has already been executed on the current N=302 benchmark using [experiments/phase_transition_study.py](../experiments/phase_transition_study.py), with results stored in [results/phase_transition_study_results.json](../results/phase_transition_study_results.json).

Observed calibrated baseline:

- `ordered`: `12/302`
- `critical`: `84/302`
- `disordered`: `206/302`

Temperature-band summary:

- `T_bin_1`: `65` items, mean $T = 0.400$, mean $\eta = 0.674$, majority `93.8 %`, D2 `93.8 %`
- `T_bin_2`: `56` items, mean $T = 0.570$, mean $\eta = 0.412$, majority `69.6 %`, D2 `69.6 %`
- `T_bin_3`: `62` items, mean $T = 0.881$, mean $\eta = 0.168$, majority `82.3 %`, D2 `79.0 %`
- `T_bin_4`: `59` items, mean $T = 0.899$, mean $\eta = 0.135$, majority `86.4 %`, D2 `86.4 %`
- `T_bin_5`: `60` items, mean $T = 0.908$, mean $\eta = 0.123$, majority `80.0 %`, D2 `80.0 %`

This is a materially better result than the original collapsed baseline. It shows:

- a non-trivial temperature spread,
- an $\eta$ range of `0.5511`,
- and a meaningful critical slice concentrated in the lower-temperature bands.

At the same time, the decisive benchmark advantage still does not appear. The calibrated study is now good enough to support a real empirical story about regime structure, but not yet good enough to support a breakthrough claim about routing superiority.

## Current N500 Readout

The N500 upgrade path has now been executed on a 544-item benchmark using:

- `results/ablation_v2_n500_results.json`
- `results/phase_transition_study_n500_results.json`
- `results/thermodynamic_calibration_n500.json`
- `results/phase_transition_study_n500_calibrated_results.json`

Current calibrated N500 summary:

- `ordered`: `99 / 544`
- `critical`: `32 / 544`
- `disordered`: `413 / 544`
- `eta_range`: `0.6292`

This closes the narrow “does the phase structure survive beyond N302?” question in the positive. The remaining open question is now runtime policy quality, not whether the phase structure exists at all.

## Hypotheses

### H1: Transition-like behavior

As effective temperature $T$ increases, the mean order parameter $\eta$ should show a materially sharper drop than a flat or linear-noise profile.

Operationally, this means:

- low-$T$ bands should have high $\eta$ and high majority/D2 accuracy,
- high-$T$ bands should have lower $\eta$ and weaker accuracy,
- at least one mid/high band should look meaningfully more fragile than its neighbors.

### H2: Susceptibility is informative

Items with high susceptibility-like behavior should be overrepresented among:

- disagreements between majority and D2,
- routed items,
- adversarial or hard benchmark items,
- and low-confidence correctness outcomes.

### H3: Phase-aware control can improve routing

After calibration, a three-phase controller should outperform a naive majority-only acceptance policy on at least one of these axes:

- accuracy on hard/non-ordered slices,
- effective truth rate,
- or harmful routed decisions avoided.

## Study Design

### Data target

Target a benchmark of at least `N >= 500` items.

Preferred path:

1. Rebuild the benchmark using the dedicated `n500` preset in [scripts/build_benchmark.py](../scripts/build_benchmark.py).
2. Preserve domain balance and source diversity.
3. Retain difficulty labels and adversarial markers in the generated benchmark metadata.

### Oracle pool

Minimum acceptable pool:

- existing heterogeneous benchmark pool used by REMORA v2/v3.

Preferred breakthrough-oriented pool:

- true cross-provider oracles so $\bar{\rho}$ is not mostly intra-family behavior.

### Conditions to compare

Use these comparison layers:

1. `B_majority`
2. `D2_balanced`
3. thermodynamic pre-sweep readout only
4. calibrated phase-aware router policy

Do not lead with speculative theorem claims. Lead with comparative empirical behavior.

## Metrics

### Primary metrics

- Mean order parameter $\eta$ by temperature band
- Mean trust score by temperature band
- Majority accuracy by temperature band
- D2 accuracy by temperature band
- Routed rate by temperature band

### Secondary metrics

- Phase counts: ordered / critical / disordered
- Adversarial accuracy by phase
- Per-domain phase split
- Harmful vs helpful routed decisions relative to majority
- Effective Truth Rate where available

### Transition evidence threshold

The study should count as promising only if at least one of the following holds:

1. The range of mean $\eta$ across temperature bands is large and monotonic enough to show a non-trivial transition profile.
2. A calibrated `critical` band emerges with materially elevated fragility and lower outcome stability.
3. Phase-aware control improves at least one benchmark-relevant metric on the hard slice.

## Execution Plan

### Step 1: Use current study script

The initial study vehicle is [experiments/phase_transition_study.py](../experiments/phase_transition_study.py).

Smoke run:

```bash
cd /workspaces/REMORA
export PYTHONPATH=/workspaces/REMORA
python3 experiments/phase_transition_study.py --max-items 25 --output /tmp/phase_transition_smoke.json
```

Canonical run against the current N=302 benchmark:

```bash
cd /workspaces/REMORA
export PYTHONPATH=/workspaces/REMORA
python3 experiments/phase_transition_study.py --output results/phase_transition_study_results.json
```

The current baseline should be treated as an improved empirical diagnostic. It now supports continued phase-transition investigation, but still requires larger-scale validation and stronger control gains before it becomes a publishable core result.

### Step 2: Expand benchmark scale

Rebuild to a larger benchmark before claiming a transition study:

```bash
cd /workspaces/REMORA
export PYTHONPATH=/workspaces/REMORA
python3 scripts/build_benchmark.py --preset n500 \
	--snapshot-json artifacts/benchmark_n500_locked.json
```

Then rerun the phase-transition study on the rebuilt benchmark.

The currently committed N500 commands are:

```bash
cd /workspaces/REMORA
export PYTHONPATH=/workspaces/REMORA
python3 -m experiments.phase_transition_study \
	--benchmark-module remora.benchmarks.extended_v2_n500 \
	--results results/ablation_v2_n500_results.json \
	--output results/phase_transition_study_n500_results.json

python3 -m experiments.calibrate_thermodynamics \
	--phase-study results/phase_transition_study_n500_results.json \
	--output results/thermodynamic_calibration_n500.json

python3 -m experiments.phase_transition_study \
	--benchmark-module remora.benchmarks.extended_v2_n500 \
	--results results/ablation_v2_n500_results.json \
	--calibration results/thermodynamic_calibration_n500.json \
	--output results/phase_transition_study_n500_calibrated_results.json
```

### Step 3: Calibrate the controller

Tune the following pieces only after baseline measurement exists:

- temperature estimator weights,
- trust thresholds,
- hallucination penalty,
- and the boundary between `ordered`, `critical`, and `disordered`.

Calibration target: produce a non-trivial `critical` slice that is empirically harder and more fragile than the ordered slice.

## Falsification Criteria

Experiment 3 should be treated as falsified, or at least not breakthrough-supporting yet, if:

- $\eta$ remains flat across temperature bands,
- no critical region emerges even after reasonable calibration,
- susceptibility does not correlate with harder or more failure-prone items,
- or phase-aware routing fails to improve any practical benchmark metric.

## What Would Count as a Breakthrough Signal

The strongest realistic near-term success signal is not a theorem. It is this:

- a larger benchmark,
- a clear transition-like drop in $\eta$,
- a measurable fragile middle band,
- and a calibrated routing policy that uses those observables to improve behavior.

That would justify a much stronger paper claim: REMORA does not merely route consensus. It measures when consensus enters a regime where it should no longer be trusted.