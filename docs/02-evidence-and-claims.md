# What are the headline claims and what supports each one?

Every headline claim, mapped to its evidence, the artifact on disk, the caveat
that keeps it honest, and how to reproduce it. This is the page to send a
skeptical reviewer. It exists because, in governance, a claim without an artifact
is a liability: see `CLAUDE.md` and `docs/05-claim-hygiene.md`.

**Reading rule:** the caveat is part of the claim. Quote the caveat with the
number, or do not quote the number.

**Paper versions:** `paper/remora_paper.md` is the canonical, continuously
corrected paper. The PDF (`remora_paper.pdf`, built 2026-06-10 from the .tex)
is a dated snapshot that predates the AgentHarm trimode results, the AROMER
ceiling milestone, and NEGATIVE_RESULTS §15–§16. Where a section reference
below names the PDF, verify against the .md, which supersedes it.

---

## Headline claims

### 1. 0% unsafe execution on an adversarial tool-call benchmark
- **Claim:** REMORA's full policy gate executed 0% of unsafe actions on a
  700-task adversarial tool-call benchmark (70 unique templates × 10 cosmetic
  variants; effective N = 70), versus 1.4% for the heuristic baselines under
  the same leakage-free input contract (2026-07-20 re-run).
- **Evidence:** the safety floor comes from the hard-block policy layer over
  surface-derived detectors and platform-fact context. The unsafe-rate delta
  vs. baselines is **not statistically significant** at the template-cluster
  level (one-sided p = 0.50); the significant advantage is decision utility
  (+0.456, p ≈ 1×10⁻⁴).
- **Artifact:** `results/toolcall_benchmark_v2_results.json` and
  `results/toolcall_benchmark_v2_significance.json`.
- **Caveat:** 0% is a point estimate over 70 template clusters. The honest
  statement is a cluster-level 95% Wilson confidence interval of
  **[0.0%, 5.2%]** — "at most ~1 in 19 templates," not "never." Earlier
  versions quoted a task-level CI of [0.00%, 0.55%], which overstated
  precision by counting 10 near-duplicate variants as independent samples.
  The benchmark is a deterministic simulator (no real shell/network/db
  mutations) with synthetic adversarial patterns, and its environment facts
  (target environment, blast radius, authz/evidence status) are declared by
  the same generator that assigns labels.
- **Important architectural caveat:** the hard-block policy rules alone produce
  the 0% rate. The multi-oracle consensus machinery (thermodynamic routing,
  Lyapunov stability heuristic, entropy/dissensus) contributes to calibration
  and routing quality for VERIFY/ABSTAIN decisions but contributes **nothing** to
  the unsafe-execution safety claim. Do not cite REMORA's safety performance as
  evidence for the value of the consensus machinery.
- **Reproduce:** `python experiments/generate_toolcall_benchmark_v2.py` then
  `python experiments/evaluate_toolcall_benchmark_v2.py`; compare to committed
  `results/`. See `docs/benchmarks/toolcall_consensus_benchmark_v2.md`.

### 2. Selective accuracy on a held-out split (CLAIM-004, SUPERSEDED)

> **This claim is superseded by CLAIM-012** and is retained for the record only.
> The signal it ranks on, consensus temperature, failed its pre-registered
> fresh-data confirmation. Do not cite it as evidence that temperature
> generalises. Archive entry:
> [`assurance/superseded_claims.md`](assurance/superseded_claims.md).

<!-- claim:CLAIM-004 accuracy_pct coverage_pct ci_low_pct ci_high_pct n -->
- **Claim (as re-issued 2026-07-27, SAP v2 clean round):** 100.0% selective
  accuracy at 16.7% hold-out coverage, N_accepted = 18, Wilson CI
  [82.4%, 100.0%], with the decision threshold locked on the training split.
- **Evidence:** `τ*` frozen on the 436-item training split before the 108-item
  hold-out was touched; exact one-sided binomial against the pre-registered
  training-split null p0 = 84.86% gives p = 0.052.
- **Artifact:** `results/selective_n500_holdout_results.json`.
- **Caveat:** p = 0.052 is **not** significant at α = 0.05, the CI does not
  exclude p0, and N_accepted = 18 is far below the pre-registered ≥100 bar for
  generalisation language. Directional only, and then contradicted on fresh data.
  Earlier documents quoted 88.0% at 23.2% coverage with N_accepted = 25 from the
  pre-2026-07-27 round; those figures are stale and must not be reused.
- **Reproduce:** `python scripts/selective_n500_holdout.py`; the held-out p-value
  and CI are in the result JSON.

### 3. The critical-phase trust inversion
- **Claim:** in the hardest ("critical") cases, the trust score anti-correlates
  with correctness, low-trust items 76.2% correct (N=21), high-trust 36.4%
  (N=11).
- **Evidence:** measured on real-oracle critical items; naive conformal at a 5%
  risk target collapses to 100% observed risk / 0 coverage in this regime. REMORA
  routes around it by inverting the selection score (`PhaseAwareGuardrail`).
- **Artifact:** `paper/remora_paper.pdf` §6.1, §13; `NEGATIVE_RESULTS.md`.
- **Caveat:** small sample (N=32 critical items total). Published as a **negative
  result**, reported as a directional finding with its N attached, not a constant.
- **Reproduce:** see the selective-prediction experiments above and
  `remora/selective/guardrail.py` (8 unit tests).

### 4. Tamper-evident audit chain
- **Claim:** every decision is recorded in a frozen `DecisionEnvelope`. On the
  `/v1/execution/*` path with a persistence adapter (`REMORA_CHAIN_DB` /
  `REMORA_PG_DSN`), envelopes are hash-chained per tenant
  (`hᵢ = SHA-256(hᵢ₋₁ ‖ envelope)`) so any modification breaks the chain; the
  default in-process library path and legacy `/v1/assess` are not chain-persisted.
- **Evidence:** `remora/governance/audit_chain.py`, `remora/governance/tenant_chain.py`
  (atomic per-tenant chain); `remora/audit/hash_chain.py` (hash primitive); replay
  reconstructs the chain.
- **Artifact:** `paper/remora_paper.pdf` §7.2; shadow-replay produces output
  on demand via `make shadow-replay` (output directory not committed).
- **Caveat:** tamper-**evident**, not tamper-**proof**. Preventing tampering needs
  external append-only (WORM) storage as a deployment dependency.
- **Reproduce:** `make shadow-replay INPUT=artifacts/demo/shadow_mode_sample_agent_action_log.jsonl`.

### 5. Ordered-phase conformal coverage
- **Claim:** 99.9% coverage at a 15% risk target on ordered-phase items, 0 of 20
  calibration seeds failing.
- **Artifact:** `paper/remora_paper.pdf` §9.3 (Mondrian table);
  `results/mondrian_v2_repeated_splits.json` (v2, 2161 items: 99.85% ordered-phase
  coverage, 0 of 20 seeds failing at the 15% risk target).
- **Caveat:** holds for the **ordered** phase only; critical and disordered phases
  cannot achieve meaningful conformal coverage (this is why the evidence router
  and `PhaseAwareGuardrail` exist).
- **Reproduce:** the Mondrian conformal experiment in `remora/selective/`.

### 6. AROMER learning loop (experimental)
- **Claim:** AROMER, the closed-loop learning layer, runs 24/7 and holds 0%
  false-accepts on its replay arena while learning (87.1% overall accuracy on the
  93-case arena, untuned; `replay_accuracy=0.871`, `replay_cases=93` per artifact).
- **Artifact:** `scripts/aromer_publish_replay.py`,
  `artifacts/aromer/replay_arena_report.json`; live AII at
  `https://aromer.razorsharp.workers.dev/intelligence`.
- **Caveat:** **EXPERIMENTAL.** Episode labels are partly self-labeled (benign-bias
  possible); the world model defaults to shadow mode; the learning loop is **not
  externally validated**. Do not cite AROMER numbers as production evidence.
- **Reproduce:** `python -m remora.aromer.evals.replay_runner --json | python scripts/check_safety_gate.py`.

---

## Complete claim set

The six headline claims above are the narrative highlights, **not** the complete
governed set. The authoritative, machine-checked list is
[`docs/assurance/claim_register_v1.yaml`](assurance/claim_register_v1.yaml)
(11 claims, CLAIM-001 … CLAIM-011), verified by
`scripts/check_claim_provenance.py`. The claims not expanded above, with their
artifacts:

| ID | Claim | Evidence level | Artifact |
|----|-------|----------------|----------|
| CLAIM-002 | FAR=0% external AgentHarm (N=208); FBR=100% companion | externally_benchmarked | `results/external_benchmark_agentharm_v1.json` |
| CLAIM-003 | FAR=0% historical regression corpus (N=167) | regression_tested | `results/false_accept_regression_v1.json` |
| CLAIM-007 | Five-condition component ablation (N=700) | internal_benchmark | `artifacts/aromer/component_ablation_results.json` |
| CLAIM-008 | 94.7% @ 25% coverage, calibration set (N=302) | internal_benchmark | `results/selective_trust_curve_results.json` |
| CLAIM-009 | FA=30.7% on neutral-metadata external datasets (negative) | internal_benchmark | `artifacts/aromer/external_dataset_eval_v2.json` |
| CLAIM-010 | Blinded benchmark v3: FAR=0% without label access (N=700) | regression_tested | `results/toolcall_blind_v3_results.json` |
| CLAIM-011 | Anytime-valid FA-rate bound for REM-020 (cycle level) | theoretical | `results/far_confidence_sequence_v1.json` |

Numbers here mirror the register; the register is the source of truth. When a
section above references `paper/remora_paper.pdf`, treat it as a dated snapshot
and verify against `paper/remora_paper.md` (the reading rule at the top of this
document).

---

## How the math is defended
The full, blackboard-ready derivation of every quantity (entropy, dissensus,
trust, the conformal risk bound, the AROMER index, the world-model Beta–Binomial)
is in `paper/remora_mathematical_supplement.md`, each formula carrying a `source:`
pointer to the implementing file and each number an `artifact:` pointer.

## Standing invitation
If you can break a claim, reproduce a different number, or show a caveat is
understated, open an issue with the "external-review" template. Negative findings
are first-class here, see `NEGATIVE_RESULTS.md` and
→ [04-negative-results-detail.md](04-negative-results-detail.md).
