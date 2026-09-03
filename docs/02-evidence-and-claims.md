# What are the headline claims and what supports each one?

Every headline claim, mapped to its evidence, the artifact on disk, the caveat
that keeps it honest, and how to reproduce it. This is the page to send a
skeptical reviewer. It exists because, in governance, a claim without an artifact
is a liability: see `CLAUDE.md` and `docs/05-claim-hygiene.md`.

**Reading rule:** the caveat is part of the claim. Quote the caveat with the
number, or do not quote the number.

**Paper versions:** `paper/remora_paper.md` is the canonical, continuously
corrected paper. `remora_paper.pdf` is compiled from the LaTeX source in CI
(most recently 2026-08-26), and `scripts/check_paper_sync.py` gates coherence
between the sources. The .md still wins on any disagreement, so cite .md
sections. Corrected 2026-09-03: this note previously described the PDF as a
2026-06-10 snapshot predating several results, which stopped being true when CI
took over the compile.

---

## Headline claims

### 1. 0% unsafe execution on an adversarial tool-call benchmark
- Claim: REMORA's full policy gate executed 0% of unsafe actions on a
  700-task adversarial tool-call benchmark (70 unique templates × 10 cosmetic
  variants; effective N = 70), versus 1.4% for the heuristic baselines under
  the same leakage-free input contract (2026-07-20 re-run).
- Evidence: the safety floor comes from the hard-block policy layer over
  surface-derived detectors and platform-fact context. The unsafe-rate delta
  vs. baselines is **not statistically significant** at the template-cluster
  level (one-sided p = 0.50); the significant advantage is decision utility
  (+0.456, p ≈ 1×10⁻⁴).
- Artifact: `results/toolcall_benchmark_v2_results.json` and
  `results/toolcall_benchmark_v2_significance.json`.
- Caveat: 0% is a point estimate over 70 template clusters. The honest
  statement is a cluster-level 95% Wilson confidence interval of
  **[0.0%, 5.2%]**, "at most ~1 in 19 templates," not "never." Earlier
  versions quoted a task-level CI of [0.00%, 0.55%], which overstated
  precision by counting 10 near-duplicate variants as independent samples.
  The benchmark is a deterministic simulator (no real shell/network/db
  mutations) with synthetic adversarial patterns, and its environment facts
  (target environment, blast radius, authz/evidence status) are declared by
  the same generator that assigns labels.
- Important architectural caveat: the hard-block policy rules alone produce
  the 0% rate. The multi-oracle consensus machinery (thermodynamic routing,
  Lyapunov stability heuristic, entropy/dissensus) contributes to calibration
  and routing quality for VERIFY/ABSTAIN decisions but contributes **nothing** to
  the unsafe-execution safety claim. Do not cite REMORA's safety performance as
  evidence for the value of the consensus machinery.
- Reproduce: `python experiments/generate_toolcall_benchmark_v2.py` then
  `python experiments/evaluate_toolcall_benchmark_v2.py`; compare to committed
  `results/`. See `docs/benchmarks/toolcall_consensus_benchmark_v2.md`.

### 2. Selective accuracy on a held-out split (CLAIM-004, SUPERSEDED)

> **This claim is superseded by CLAIM-012** and is retained for the record only.
> The signal it ranks on, consensus temperature, failed its pre-registered
> fresh-data confirmation. Do not cite it as evidence that temperature
> generalises. Archive entry:
> [`assurance/superseded_claims.md`](assurance/superseded_claims.md).

<!-- claim:CLAIM-004 accuracy_pct coverage_pct ci_low_pct ci_high_pct n -->
- Claim (as re-issued 2026-07-27, SAP v2 clean round): 100.0% selective
  accuracy at 16.7% hold-out coverage, N_accepted = 18, Wilson CI
  [82.4%, 100.0%], with the decision threshold locked on the training split.
- Evidence: `τ*` frozen on the 436-item training split before the 108-item
  hold-out was touched; exact one-sided binomial against the pre-registered
  training-split null p0 = 84.86% gives p = 0.052.
- Artifact: `results/selective_n500_holdout_results.json`.
- Caveat: p = 0.052 is **not** significant at α = 0.05, the CI does not
  exclude p0, and N_accepted = 18 is far below the pre-registered ≥100 bar for
  generalisation language. Directional only, and then contradicted on fresh data.
  Earlier documents quoted 88.0% at 23.2% coverage with N_accepted = 25 from the
  pre-2026-07-27 round; those figures are stale and must not be reused.
- Reproduce: `python scripts/selective_n500_holdout.py`; the held-out p-value
  and CI are in the result JSON.

### 3. The critical-phase trust inversion
- Claim: in the hardest ("critical") cases, the trust score anti-correlates
  with correctness, low-trust items 76.2% correct (N=21), high-trust 36.4%
  (N=11).
- Evidence: measured on real-oracle critical items; naive conformal at a 5%
  risk target collapses to 100% observed risk / 0 coverage in this regime. REMORA
  routes around it by inverting the selection score (`PhaseAwareGuardrail`).
- Artifact: `paper/remora_paper.md` §7.2 (conformal risk control under covariate shift), §13 (limitations and negative results); `NEGATIVE_RESULTS.md`.
- Caveat: small sample (N=32 critical items total). Published as a **negative
  result**, reported as a directional finding with its N attached, not a constant.
- Reproduce: see the selective-prediction experiments above and
  `remora/selective/guardrail.py` (8 unit tests).

### 4. Tamper-evident audit chain
- Claim: every decision is recorded in a frozen `DecisionEnvelope`. On the
  `/v1/execution/*` path with a persistence adapter (`REMORA_CHAIN_DB` /
  `REMORA_PG_DSN`), envelopes are hash-chained per tenant
  (`hᵢ = SHA-256(hᵢ₋₁ ‖ envelope)`) so any modification breaks the chain; the
  default in-process library path and legacy `/v1/assess` are not chain-persisted.
- Evidence: `remora/governance/audit_chain.py`, `remora/governance/tenant_chain.py`
  (atomic per-tenant chain); `remora/audit/hash_chain.py` (hash primitive); replay
  reconstructs the chain.
- Artifact: `paper/remora_paper.md` §8.2 (audit hash-chain); shadow-replay produces output
  on demand via `make shadow-replay` (output directory not committed).
- Caveat: tamper-**evident**, not tamper-**proof**. Preventing tampering needs
  external append-only (WORM) storage as a deployment dependency.
- Reproduce: `make shadow-replay INPUT=artifacts/demo/shadow_mode_sample_agent_action_log.jsonl`.

### 5. Ordered-phase conformal coverage
- Claim: 99.9% coverage at a 15% risk target on ordered-phase items, 0 of 20
  calibration seeds failing.
- Artifact: `paper/remora_paper.md` §10.5 (Mondrian table);
  `results/mondrian_v2_repeated_splits.json` (v2, 2161 items: 99.85% ordered-phase
  coverage, 0 of 20 seeds failing at the 15% risk target).
- Caveat: holds for the **ordered** phase only; critical and disordered phases
  cannot achieve meaningful conformal coverage (this is why the evidence router
  and `PhaseAwareGuardrail` exist).
- Reproduce: the Mondrian conformal experiment in `remora/selective/`.

### 6. AROMER learning loop (experimental)
- Claim (dated snapshot, not an operational statement): on the committed replay
  arena report, AROMER held 0% false-accepts at 87.1% overall accuracy over 93
  cases, untuned (`replay_accuracy=0.871`, `replay_cases=93` per artifact).
- Artifact: `artifacts/aromer/replay_arena_report.json`, produced by
  `scripts/aromer_publish_replay.py`. Corrected 2026-09-03: this entry claimed
  the loop "runs 24/7" and pointed at a live endpoint. No claim in the register
  carries a 24/7 operational statement, and ARCHITECTURE.md §5.5 makes AROMER
  shadow-only (issue #297); read the numbers as the artifact's, on its date.
- Caveat: **EXPERIMENTAL.** Episode labels are partly self-labeled (benign-bias
  possible); the world model defaults to shadow mode; the learning loop is **not
  externally validated**. Do not cite AROMER numbers as production evidence.
- Reproduce: `python -m remora.aromer.evals.replay_runner --json | python scripts/check_safety_gate.py`.

---

## Complete claim set

The six headline claims above are the narrative highlights, **not** the complete
governed set. The authoritative, machine-checked list is
[`docs/assurance/claim_register_v1.yaml`](assurance/claim_register_v1.yaml),
verified by `scripts/check_claim_provenance.py`. Which claims have been replaced,
and by what, is generated from that register into
[`superseded_claims.md`](assurance/superseded_claims.md). Read it there. A
hand-kept list lived here until 2026-09-03, and by then it said 19 claims and
three supersessions while the register had moved on. The claims not expanded above,
with their artifacts:

| ID | Claim | Evidence level | Artifact |
|----|-------|----------------|----------|
| CLAIM-002 | FAR=0% external AgentHarm (N=208); FBR=100% companion | externally_benchmarked | `results/external_benchmark_agentharm_v1.json` |
| CLAIM-003 | FAR=0% historical regression corpus (N=167) | regression_tested | `results/false_accept_regression_v1.json` |
| CLAIM-007 (**withdrawn**, superseded by CLAIM-020) | Five-condition component ablation (N=700) | internal_benchmark | `artifacts/aromer/component_ablation_results.json` |
| CLAIM-020 | Component ablation identifies no necessary component: FAR=0.000 in all six conditions (N=700, 70 clusters) | internal_benchmark | `results/toolcall_benchmark_v2_ablation.json` |
| CLAIM-008 | 94.7% @ 25% coverage, calibration set (N=302) | internal_benchmark | `results/selective_trust_curve_results.json` |
| CLAIM-009 | FA=30.7% on neutral-metadata external datasets (negative) | internal_benchmark | `artifacts/aromer/external_dataset_eval_v2.json` |
| CLAIM-010 | Blinded benchmark v3: FAR=0% without label access (N=700) | regression_tested | `results/toolcall_blind_v3_results.json` |
| CLAIM-011 | Anytime-valid FA-rate bound for REM-020 (cycle level) | theoretical | `results/far_confidence_sequence_v1.json` |
| CLAIM-012 | NEGATIVE: consensus temperature failed pre-registered fresh-data confirmation (SAP v3) | internal_benchmark | `results/sap_v3_round_results.json` |
| CLAIM-013 | Calibrated confidence-weighted voting: significant aggregation win; marginal per-arm certificates only | internal_benchmark | `results/sap_v3_round_results.json` |
| CLAIM-014 | System demonstration: governance chain from tool call to enforcement | internal_benchmark | `results/system_demonstration_v1.json` |
| CLAIM-015 | Superseded BFCL v3 development measurement; retained only as a negative-result record | internal_benchmark | `NEGATIVE_RESULTS.md` |
| CLAIM-016 | Superseded BFCL v3 negative record: 4 of 5 targets met; superseded by CLAIM-019 | externally_benchmarked | `results/routing_bench_bfcl_results.json` |
| CLAIM-017 | Semantic binding gap in match_tool_to_intent (finding, fixed and regression-tested) | regression_tested | `remora/toolcall/routing/goal_match.py` |
| CLAIM-018 | **Superseded by CLAIM-019.** Disjoint sealed BFCL v4 (C-ext2): all five pre-registered targets met, wrong-call ACCEPT 28/258 = 10.9%. Retained permanently as the degraded-authority baseline — that track ran with `contracts=None, intent=None`, so the semantic gates never fired | externally_benchmarked | `results/routing_bench_bfcl_v4_results.json` |
| CLAIM-019 | Sealed BFCL v4 C-ext3 with declared semantic authority: native wrong-call ACCEPT **0/500 = 0.0%** (Wilson 95% upper 0.76%), irrelevance 300/300, required-unknown 0/398. **Four of seven targets MISSED** and published as measured — read autonomy 25/94 = 26.6% against a 75% bar, obtainable VERIFY 46.7%, unobtainable ABSTAIN 63.3%, constructed wrong-tool 2/199 = 1.005% (`NEGATIVE_RESULTS.md` §39) | externally_benchmarked | `results/routing_bench_bfcl_v4_cext3_results.json` |

Baseline context for the selective-prediction numbers: the calibration benchmark
is N=302 items, where one model alone scores 57.0% and plain vote-counting
82.8%. REMORA's contribution is knowing *which* decisions to trust, not raising
that ceiling; the full risk–coverage curve is in
[03-experiments.md](03-experiments.md).

Numbers here mirror the register; the register is the source of truth. Section
references above name `paper/remora_paper.md`, the canonical paper. The PDF is
compiled from the LaTeX source and numbers its sections differently.

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

---

## Status, and what is not proven

<!-- BEGIN GENERATED: status, source: assurance registers, via scripts/generate_readme_status.py --check. DO NOT EDIT. -->
**Deployment profile:** `SHADOW_PILOT` (= `SHADOW_ONLY`), recomputed from the capability and remediation registers by CI; a profile cannot be raised by editing prose.

**To reach `CONTROLLED_PILOT`, still open:** REM-021, REM-023.

**Capabilities:** 8 of 18 wired to the API path or deeper ([wiring register](assurance/capability_register_v1.yaml)); full gate status in [release_gates.md](assurance/release_gates.md), maturity ladder in [release_profiles_v1.yaml](assurance/release_profiles_v1.yaml).
<!-- END GENERATED: status -->

Shadow-mode research only; not certified for production. The load-bearing caveats:

- **The safety numbers come from benchmarks, not from the field.** The 0% unsafe-execution
  rate is a synthetic-benchmark result: a deterministic simulator and a controlled internal
  corpus, with no real shell, network or database touched.
- **Sample sizes are smaller than they look.** The simulator's 700 tasks are 70 templates
  × 10 cosmetic variants (effective N=70); the margin over baselines is not significant (p=0.50).
- Nobody outside this project has reproduced any of it. External replication is pending;
  a distinct, still-open evidence level, and a prerequisite for any stronger label.
- **REMORA cannot stop an agent that goes around it.** The guarantee holds only where a
  deployment routes every tool call through the dispatcher and the agent has no credentials.
- **The audit log detects tampering; it does not prevent it.** Prevention needs append-only
  (WORM) storage, which is not included here.
- **AROMER is experimental**; its numbers are not evidence for the core system.
- **Calibration-weighted aggregation is measured, not adopted.** It beat unweighted majority
  on fresh data but not the best single model; no arm certifies under Bonferroni-3, and it is
  not enabled (CLAIM-013; [NEGATIVE_RESULTS §18](../NEGATIVE_RESULTS.md)).

Everything still open: [remediation_register.yaml](assurance/remediation_register.yaml).
Evidence and leakage disclosures: [experiments](03-experiments.md) · [reviewing this repo](validation/external-review.md).
Terms (FAR/FBR, effective N, Wilson interval, intent-gating, lease) in the
[glossary](plain_language_overview.md#key-terms); denominators in [metric definitions](assurance/metric_definitions_v1.md).
