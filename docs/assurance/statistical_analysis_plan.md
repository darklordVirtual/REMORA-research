# Statistical Analysis Plan (SAP)

**Date pre-registered:** 2026-06-28
**Version:** 1.0
**Status:** Pre-registered, analyses not yet re-run after this document
**Implements:** intern_forbedring.txt §9, `docs/assurance/remediation_register.yaml` REM-012

This document pre-declares the statistical methods, hypotheses, sample sizes,
significance thresholds, and multiple-comparison corrections for all primary
claims in the REMORA paper. Analyses run before this document existed are
labelled **[POST-HOC]** and must be replicated under the pre-declared protocol
before the claim is considered pre-registered.

---

## 1. Primary Selective-Prediction Claim (§10.1)

**Hypothesis H1:** REMORA selective accuracy (threshold locked from training split)
exceeds the full-coverage majority-vote baseline on a held-out test set.

**Test:** One-sided binomial test (H₁: accuracy > p₀ = 0.4618 [holdout majority-vote baseline]).

**Pre-declared parameters:**
- Split: stratified 80/20 by benchmark source, seed=42
- τ* selection: 18% coverage target on 436-item training split
- Threshold: locked at τ* = 0.203; NOT re-optimised on holdout
- Significance level α = 0.05 (one-sided)
- Effect size: Wilson 95% CI on accepted items
- Minimum reportable N_accepted: 25 (current); target ≥ 100 for generalization claims

**Status [POST-HOC]:** Run at commit 7da2ae3. N_accepted=25, p=1.45×10⁻⁵, CI [70.0%, 95.8%].
Wide CI (25.8 pp) prevents generalization claims. Re-run under this SAP required with
a dataset providing N_accepted ≥ 100.

**Interpretation constraint:** With N_accepted=25, the result is a directional observation
only. Do not report as "established" or "confirmed generalization." Language required:
"one directional held-out observation consistent with no in-sample threshold artefact."

---

## 2. Tool-Call Safety Claim (§10.3)

**Hypothesis H2:** REMORA full policy gate achieves lower unsafe execution rate than
all baseline conditions on the N=700 toolcall benchmark v2.

**Test:** Exact binomial proportion test (H₂: FAR_REMORA < FAR_baseline for each baseline).

**Pre-declared parameters:**
- Benchmark: `toolcall_benchmark_v2` (N=700: 560 harmful, 140 benign)
- Primary metric: false accept rate (FAR = unsafe executions / harmful tasks)
- Baseline conditions: severity_heuristic, keyword_heuristic, temperature_gate
- Significance level α = 0.05 per comparison; Bonferroni-adjusted α = 0.0125 for 4 comparisons
- Paired comparison: same task set across all conditions

**Status [POST-HOC]:** FAR=0.0 (0/560 harmful) vs. baselines (10–20%). No p-value
reported because FAR=0 makes the test degenerate (exact binomial: p < 10⁻¹⁰).
See `results/toolcall_benchmark_v2_results.json`.

**Status [SUPERSEDED 2026-07-20 — see §8 deviation D-3]:** the task-level exact
binomial test above is withdrawn: the 700 tasks are 70 templates × 10
near-duplicate variants, so task-level units violate the test's independence
assumption. Under the corrected template-cluster analysis
(`experiments/toolcall_v2_significance.py`) and the leakage-free input contract
(REM-038), FAR_REMORA = 0.0 vs. FAR_baseline = 1.4%, cluster sign-flip
permutation one-sided p = 0.50: **H2 is NOT supported** on benchmark v2. The
cluster-level utility delta (+0.456, p ≈ 1×10⁻⁴) is significant but was not a
pre-declared hypothesis; it is reported as post-hoc.

**M1 constraint:** All analysis must use the code path where `is_unsafe_if_executed`
is absent from the gate (post-fix state, commit 375800d). Pre-fix analyses are
documented in `results/toolcall_m1_clean_signal.json` for comparison.
As of 2026-07-20 this constraint extends to the oracle context flags, severity,
and tags (REM-038): all analysis must use the surface-derived gate.

---

## 3. Component Ablation Claim (§10.3)

**Hypothesis H3:** Full REMORA (condition E) dominates all ablated variants on
the safety–utility frontier (Pareto-dominates A/B/C/D for both FAR and utility).

**Test:** Direct comparison of point estimates; no significance test (deterministic
simulation with no sampling noise).

**Pre-declared parameters:**
- N=700 tasks; conditions A–E as defined in `experiments/_m1_flag_coverage.py`
- Primary: FAR and mean utility per condition
- Clean-signal constraint: conditions C and D must not use `is_unsafe_if_executed`
  or severity-derived phase/trust (verified by leakage detector on each run)

**Status:** DONE (artifact: `artifacts/aromer/component_ablation_results.json`).
Leakage-free. Valid under this SAP.

---

## 4. AgentHarm External Benchmark (§10.6)

**Hypothesis H4 (intent-gating):** Under the intent-gating protocol, REMORA Mode 3
achieves blocked_recall ≥ 0.95 with FPR < 0.10 on the N=88 AgentHarm benchmark.

**Test:** Proportion test on point estimates; Wilson 95% CI for both metrics.
One-sided for blocked_recall (H: > 0.95); one-sided for FPR (H: < 0.10).

**Pre-declared parameters:**
- Dataset: AgentHarm (44 harmful, 44 benign), `hint_included=False, detailed_prompt=False`
- Protocol: Mode 3 cascade only (Modes 1/2 are exploratory baselines, not hypothesis-tested)
- Evaluation scope: **intent-gating only**, not tool-call interception
  (see `experiments/agentharm/INTERCEPTION_NOTES.md`)
- This claim does NOT imply execution prevention

**Status [POST-HOC]:** blocked_recall=0.977 (43/44), FPR=0.023 (1/44). Both meet targets.
Artifact: `artifacts/agentharm_trimode_results.json`. Valid under this SAP with
the stated intent-gating scope constraint.

---

## 5. AROMER Learning Claim

**Hypothesis H5:** AROMER reaches AII ≥ 0.80 (TRAINED threshold) and sustains it for
≥ 10 consecutive adapt() cycles without false accepts.

**Test:** Point measurement at AROMER worker `/intelligence` endpoint; time-series
of adapt() cycle AII values.

**Pre-declared parameters:**
- AII formula: AII = 0.30·T1 + 0.25·T2 + 0.20·T3 + 0.15·T4 + 0.10·T5
- TRAINED threshold: AII ≥ 0.80 (pre-declared; not tuned post-hoc)
- Sustain window: ≥ 10 consecutive cycles with AII ≥ 0.80
- FAR constraint: 0 false accepts during sustain window

**Status:** DONE. Peak AII=0.844 (cycle 12). 12+ consecutive TRAINED cycles.
FAR=0 throughout. Documented in NEGATIVE_RESULTS.md §11–§12.
Current AII=0.8266 (TRAINED_SHADOW_ONLY, 2026-06-28).

---

## 6. Multiple Comparison Policy

Where multiple hypotheses are tested on the same dataset:
- Primary hypotheses H1–H4 are each tested at α = 0.05
- Bonferroni correction applied when multiple baselines tested against the
  same primary condition (§2: α = 0.0125 for 4 comparisons)
- Exploratory analyses (ablation sub-conditions, Mode 1/2 AgentHarm) are
  labelled exploratory and do not carry hypothesis-test status

---

## 7. Data and Artifact Pre-declaration

All analyses must be run against these locked artifacts:

| Claim | Dataset | Artifact |
|-------|---------|----------|
| H1 (selective prediction) | N=544 benchmark | `artifacts/benchmark_n500_locked.json` |
| H2/H3 (toolcall safety) | toolcall_benchmark_v2 (N=700) | `remora/toolcall/benchmark_v2.py` |
| H4 (AgentHarm) | AgentHarm public v1 | `artifacts/agentharm_trimode_results.json` |
| H5 (AROMER) | Live AROMER worker log | `/intelligence?history=24` |

Any update to H1–H4 datasets requires incrementing the SAP version and
documenting the change in `docs/assurance/remediation_register.yaml`.

---

## 8. Known Protocol Deviations (Pre-existing)

| Deviation | Impact | Mitigation |
|-----------|--------|-----------|
| H1 pre-registered post-hoc (analysis ran before SAP) | Possible experimenter bias in τ* selection | τ* was locked before holdout evaluation; no re-optimisation documented in git history |
| H2 dataset partially curated by authors | Selection bias possible | Benchmark generation script committed; category distribution documented |
| H4 evaluated after framework design (not pre-registered) | Possible overfitting of Mode 3 pipeline to AgentHarm format | Replication on τ-bench and ToolEmu required (REM-014) |
| D-3 (2026-07-20): H2 inference unit changed from task (N=700) to template cluster (n=70), and the pre-declared exact binomial test replaced by cluster bootstrap + cluster sign-flip permutation | The pre-declared task-level test treated 10 near-duplicate variants as independent samples, overstating precision ~10×; combined with the REM-038 leakage fix, H2's conclusion REVERSES (unsafe-rate delta not significant, p=0.50) | Recorded here explicitly rather than silently swapped; both old and new methods documented in NEGATIVE_RESULTS.md §17; the withdrawn task-level result must not be quoted |
