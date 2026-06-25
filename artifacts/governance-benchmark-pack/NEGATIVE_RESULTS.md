# Negative and Incomplete Results

> **Why this document exists.**  Publishing negative results is standard
> scientific practice and is almost never done in individual portfolio projects.
> Every number here increases external credibility by proving the system was
> not optimised until only the positive findings remained.

This document contains only **active, unresolved findings**.  Findings that
have been fully addressed are preserved in the
[Resolved Findings Archive](#resolved-findings-archive) below.
All findings are registered in `docs/claim_register.md`.

---

## Active Findings

### 1. External replication and live-deployment validation pending

Core benchmark claims are now internally replicated and documented with
benchmark-scoped caveats, but independent external replication remains pending.

**Outstanding items:**
- Independent third-party rerun of selective QA metrics on public datasets.
- Live-oracle (non-simulator) replication of tool-call safety metrics.
- Production evidence retrieval validation (beyond MultiNLI proxy benchmark).

**Why this remains active:** This is a research-governance gap, not a hidden
performance failure. The mitigation path and protocol are tracked in
`docs/benchmark_validation_plan.md`.

---

## Summary Table

| Finding | Status | Severity |
|---------|--------|----------|
| External replication and live validation pending | Active — formal third-party replication still outstanding | Medium |

---

## Resolved Findings Archive

The following findings were identified, addressed, and removed from the active
list.  They are preserved here as scientific record.

| # | Finding | Resolution | Version |
|---|---------|-----------|---------|
| R1 | Iteration damage on easy questions (−22.2 pp) | `skip_high_trust_threshold=0.75` in `CritiqueRevisionGate`; DISORDERED-phase → immediate ABSTAIN (0 oracle calls) | ≤0.5.0 |
| R2 | Stage 3b critique-revision accuracy impact unmeasured | N=544 calibration analysis: critical-phase items n=26 routed, majority=d2=69.2%, loop neither helps nor harms; phase-differentiated routing implemented | 0.6.1 |
| R3 | Conformal guardrail not wired into decision engine | `conformal_trust_threshold` parameter in `RemoraDecisionEngine`; `CONFORMAL_ACCEPT` decision reason activated at runtime | ≤0.6.0 |
| R4 | Conformal repeated-split failures (20/20 at 5 % target, global) | `MondrianPhaseGuardrail`: per-phase calibration reduces failures to 1–2/20 per stratum; validated across 20-seed repeated splits | 0.6.1 |
| R5 | Lyapunov V(t) — no aggregate distribution published | `experiments/lyapunov_aggregate.py`: N=1000 synthetic sessions, P(ΔV ≤ 0) = 87.2 %, mean ΔV = −0.329 | ≤0.6.0 |
| R6 | Oracle family independence partial (ρ̄ ≈ 0.4–0.6 within-family) | `build_recommended_swarm()`: 3 distinct base-model families (LLaMA 3.3 70B, Claude 3.5 Haiku, Gemma 3 27B) | ≤0.6.0 |
| R7 | T-estimator circularity (D→T→F, D contributes 18 % to T) | `estimate_structural_temperature()` is circularity-free (prompt-only); is the active path in `engine.py`; `_CATEGORY_PRIORS` documented as intentional safety floors | 0.6.1 |
| R8 | Tool-call v1 — no differentiation (every strategy = 0 % unsafe on 252-task non-adversarial suite) | v2 adversarial suite (700 tasks): `remora_full_policy_gate` = **0 % unsafe** vs 10–20 % for all baselines; artifact `results/toolcall_benchmark_v2_summary.md`; implementation `experiments/evaluate_toolcall_benchmark_v2.py`; regression test `tests/test_toolcall_v2_results.py` | 0.7.0 |
| R9 | Conformal exchangeability not verified at runtime | `MondrianPhaseGuardrail.route(prompt=…)` + `PromptDriftDetector` integration: distribution shift triggers ABSTAIN before conformal routing; tests in `tests/test_guardrail.py` (drift integration) and `tests/test_drift_detector.py` | 0.7.0 |
| R10 | χ-proxy difficulty signal below chance (AUC = 0.39) | Negative result preserved as empirical record; χ repurposed to OOD/adversarial escalation (`phase_decision()`, threshold 1.45) | 0.7.1 |
| R11 | Full-coverage baseline framing risk (41.18 % vs selective 88.8 %) | Mixed-comparison caveat standardized in docs; held-out validation added (`results/selective_n500_holdout_results.json`); benchmark-scoped wording enforced | 0.7.1 |
| R12 | Critical-phase trust score cannot safely gate decisions | Operationally mitigated via `CriticalEvidenceRouter` + escalation fallback; benchmark result: 38.5 % resolution on MultiNLI proxy, remainder ESCALATE | 0.7.1 |
