# REMORA Benchmark Validation Plan

**Document:** `docs/benchmark_validation_plan.md`  
**Status:** Draft — PR-14  
**Date:** 2026-05-31  
**Author:** Stian Skogbrott

---

## Purpose

This document describes the steps required to externally validate REMORA's
benchmark claims beyond the in-sample and single-holdout results already
committed.  It addresses the "Requires External Replication" section in
[`docs/claim_register.md`](../docs/claim_register.md).

---

## Current Evidence State

| Claim | N | In-sample | Holdout | External |
|---|---|---|---|---|
| Selective accuracy 88.8% at 18% coverage | 544 | ✅ locked artifact | ✅ 88.0% / 23.2% (22/25) | ❌ needed |
| Tool-call 0% unsafe execution (full policy gate) | 700 | ✅ simulator | N/A (benchmark-scoped) | ❌ needed |
| Critical-phase trust inversion | 544 | ✅ observed | partial | ❌ needed |
| Lyapunov V(t) monotone convergence | — | ✅ unit tested | — | ❌ needed |

---

## Validation Steps

### Step 1 — Cross-dataset replication on TruthfulQA (public)

**Goal:** Run the full REMORA pipeline on the public TruthfulQA validation set
(~817 items) using cached oracle responses and verify that selective accuracy
≥ 85% at ≥ 15% coverage.

**Protocol:**
1. Cache oracle responses for all 817 items using `experiments/end_to_end_n500_v3.py`
   with `--dry-run` mode to avoid live API costs.
2. Fix calibration threshold `τ*` on the first 400 items (training split).
3. Evaluate on the remaining 417 items (holdout).
4. Report: N_accepted, accuracy, Wilson 95% CI, p-value (one-tailed binomial).
5. Lock the result to `results/truthfulqa_holdout_results.json`.

**Acceptance criterion:**  
`accuracy ≥ 0.85` on holdout AND `coverage ≥ 0.12` AND `p < 0.01`.

---

### Step 2 — BoolQ replication (public)

**Goal:** Verify the BoolQ component of the benchmark independently.

**Protocol:**
1. Sample 300 items from BoolQ dev split (stratified by domain).
2. Use 3 independent oracle calls (different seeds or model temperatures).
3. Run full REMORA pipeline.
4. Report metrics as in Step 1.

**Acceptance criterion:**  
`accuracy ≥ 0.80` at `coverage ≥ 0.15`.

---

### Step 3 — Adversarial robustness on external jailbreak set

**Goal:** Verify that `adversarial_detected=True` fires on an external prompt
injection dataset and never yields ACCEPT.

**Dataset:** [PromptBench](https://github.com/microsoft/promptbench) adversarial
subset (100 jailbreak prompts).

**Protocol:**
1. Run each adversarial prompt through `Remora._detect_adversarial_input()`.
2. For all items where `adversarial_detected=True`, verify action = ESCALATE.
3. Report detection rate and false-negative count.

**Acceptance criterion:**  
Detection rate ≥ 90% of known injection patterns AND 0% ACCEPT on detected items.

---

### Step 4 — Tool-call benchmark on live model pool

**Goal:** Replace the deterministic simulator with real API calls.

**Protocol:**
1. Use 3 real oracle providers (e.g. GPT-4o-mini, Claude Haiku, Gemini Flash).
2. Run 100 tool-call scenarios from `artifacts/toolcall_benchmark_v2.json`.
3. Record: action per scenario, human_review_required, elapsed_ms.
4. Compare unsafe execution rate vs majority-vote baseline.

**Acceptance criterion:**  
REMORA full-policy unsafe execution ≤ majority-vote / 5.

---

### Step 5 — Independent code review

**Goal:** Have at least one external reviewer audit the policy engine invariants.

**Artifacts to review:**
- `remora/policy/decision_engine.py` — hard block ordering
- `tests/test_policy_invariants_prop.py` — 246 invariant tests
- `remora/policy/opa_adapter.py` — OPA parity

**Reviewer independence:**  
Must not be a contributor to the REMORA repository.

---

## Timeline

| Step | Owner | Target |
|---|---|---|
| Step 1 — TruthfulQA | Stian | Q3 2026 |
| Step 2 — BoolQ | Stian | Q3 2026 |
| Step 3 — Adversarial | Stian | Q3 2026 |
| Step 4 — Live oracles | Stian + collaborator | Q4 2026 |
| Step 5 — Code review | External reviewer | Q4 2026 |

---

## How to cite pending results

Until external validation is complete, results must be cited as:

> "Observed on the committed in-sample benchmark artifact (N=544, single holdout N=25).
> External replication is pending. See `docs/benchmark_validation_plan.md`."

Do NOT cite the tool-call 0% unsafe execution as a general guarantee —
it is a simulator result.
