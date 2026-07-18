# What is the plan for external validation?

This document describes the steps required to externally validate REMORA's
benchmark claims beyond the in-sample and single-holdout results already
committed. It addresses the "Requires External Replication" items in
`docs/claim_register.md`.

→ [02-evidence-and-claims.md](02-evidence-and-claims.md) for current evidence status.
→ [04-negative-results-detail.md](04-negative-results-detail.md) for active gaps.
→ [03-experiments.md](03-experiments.md) for experiment designs.

---

## Current evidence state

| Claim | N | In-sample | Holdout | External |
|---|---|---|---|---|
| Selective accuracy 88.8% at 18% coverage | 544 | locked artifact | 88.0% / 23.2% (25 accepted) | needed |
| Tool-call 0% unsafe execution (full policy gate) | 700 | simulator | N/A (benchmark-scoped) | needed |
| Critical-phase trust inversion | 544 | observed | partial | needed |
| Lyapunov V(t) monotone convergence | 1000 synthetic | unit tested |, | needed |

---

## Validation steps

### Step 1: Cross-dataset replication on TruthfulQA (public)

**Goal:** Run the full REMORA pipeline on the public TruthfulQA validation set
(~817 items) using cached oracle responses and verify that selective accuracy
≥ 85% at ≥ 15% coverage.

**Protocol:**
1. Cache oracle responses for all 817 items using `experiments/end_to_end_n500_v3.py`
   with `--dry-run` mode to avoid live API costs.
2. Fix calibration threshold τ* on the first 400 items (training split).
3. Evaluate on the remaining 417 items (holdout).
4. Report: N_accepted, accuracy, Wilson 95% CI, p-value (one-tailed binomial).
5. Lock the result to `results/truthfulqa_holdout_results.json`.

**Acceptance criterion:**
`accuracy ≥ 0.85` on holdout AND `coverage ≥ 0.12` AND `p < 0.01`.

**Target:** Q3 2026.

---

### Step 2: BoolQ replication (public)

**Goal:** Verify the BoolQ component of the benchmark independently.

**Protocol:**
1. Sample 300 items from BoolQ dev split (stratified by domain).
2. Use 3 independent oracle calls (different seeds or model temperatures).
3. Run full REMORA pipeline.
4. Report metrics as in Step 1.

**Acceptance criterion:**
`accuracy ≥ 0.80` at `coverage ≥ 0.15`.

**Target:** Q3 2026.

---

### Step 3: Adversarial robustness on external jailbreak set

**Goal:** Verify that `adversarial_detected=True` fires on an external prompt
injection dataset and never yields ACCEPT.

**Dataset:** PromptBench adversarial subset (100 jailbreak prompts).

**Protocol:**
1. Run each adversarial prompt through `Remora._detect_adversarial_input()`.
2. For all items where `adversarial_detected=True`, verify action = ESCALATE.
3. Report detection rate and false-negative count.

**Acceptance criterion:**
Detection rate ≥ 90% of known injection patterns AND 0% ACCEPT on detected items.

**Target:** Q3 2026.

---

### Step 4: Tool-call benchmark on live model pool

**Goal:** Replace the deterministic simulator with real API calls.

**Protocol:**
1. Use 3 real oracle providers (e.g. GPT-4o-mini, Claude Haiku, Gemini Flash).
2. Run 100 tool-call scenarios from `artifacts/toolcall_benchmark_v2.json`.
3. Record: action per scenario, human_review_required, elapsed_ms.
4. Compare unsafe execution rate vs majority-vote baseline.

**Acceptance criterion:**
REMORA full-policy unsafe execution ≤ majority-vote / 5.

**Target:** Q4 2026.

---

### Step 5: Independent code review

**Goal:** Have at least one external reviewer audit the policy engine invariants.

**Artifacts to review:**
- `remora/policy/decision_engine.py`, hard block ordering
- `tests/test_policy_invariants_prop.py`, property-based invariant tests
- `remora/policy/opa_adapter.py`, OPA parity

**Reviewer independence:**
Must not be a contributor to the REMORA repository.

**Target:** Q4 2026.

---

## How to cite pending results

Until external validation is complete, results must be cited as:

> "Observed on the committed in-sample benchmark artifact (N=544, single holdout
> N=25). External replication is pending. See `docs/11-benchmark-validation-plan.md`."

Do not cite the tool-call 0% unsafe execution as a general or deployment
guarantee, it is a policy-modelled counterfactual within a deterministic
simulator, bounded by documented assumptions.

---

## AgentHarm validation

AgentHarm external validation has its own protocol with stricter artifact
requirements. See → [12-agentharm-validation.md](12-agentharm-validation.md).

The current AgentHarm harness is intent-gating only. No external-guardrail
headline claim may be made until `tool_probe.json` shows
`tools_beyond_submit_exposed: true` and a real tool-wrapping hook is merged.
