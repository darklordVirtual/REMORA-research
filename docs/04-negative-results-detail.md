# What didn't work and what remains open?

Active findings are also indexed in `02-evidence-and-claims.md` caveat blocks.
*Last synchronized with the canonical record: 2026-07-17.*

> **Why this document exists.**  Publishing negative results is standard
> scientific practice and is almost never done in individual portfolio projects.
> Every number here increases external credibility by proving the system was
> not optimised until only the positive findings remained.

**Scope of this document:** the deep-dive on the three headline *research*
gaps (external replication, holdout transfer, entropy backend), plus the
resolved-findings archive (R1–R12). It is **not** the complete negative-results
record, the canonical, complete record is
[`../NEGATIVE_RESULTS.md`](../NEGATIVE_RESULTS.md) (16 findings including the
operational event chronicles and the structural AII ceilings §15–§16).
Statuses here are synchronized with that record; on any discrepancy the root
record wins. All findings are registered in `docs/claim_register.md`.

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

### 2. AROMER safety floor does not transfer to the external holdout under proxy signals

On the internal replay arena (65 cases at the time of this evaluation; expanded to 96 cases in later versions), the seeded AROMER profile records
false_accept_rate 0.000 and correct_intercept_rate 1.000. On the first external
holdout, 495 cases derived from the independent `toolcall_v3`
(CyberSecEval-inspired) set, `datasets/aromer_external_holdout_v1/`, all
`can_train=False`, with deterministic proxy signals, both degrade to **0.500**,
and profiles A (REMORA-only), B (AROMER cold), and C (AROMER seeded) are
**bit-identical** (zero learning differentiation).

**What this establishes:**
- The internal arena is an optimistic measurement surface: its cases share the
  (domain, action_type, risk_tier) taxonomy AROMER's synthetic seeds were
  authored against.
- AROMER seed episodes do not change any decision on an independent distribution.

**Confounds, and what has since been tested:**
- The ablation now runs REMORA's real admission firewall
  (`Remora._detect_adversarial_input`) on each action description. The 0.500
  result is **unchanged**, because the holdout's injection payloads live in
  `untrusted_context`, not in the scanned action description. So the false-accept
  is not a missing-flag artifact, the firewall genuinely does not cover indirect
  injection.
- REMORA's dedicated content scanner (`ToolResultScanner`) was measured directly
  on the 150 attack `untrusted_context` payloads
  (`artifacts/aromer_injection_ceiling_v1.json`, deterministic heuristic stage).
  As originally implemented it hard-blocked only **6.7%** (10/150). Adding
  semantically-general exfiltration and authority-spoofing rules raised this to
  **53%** hard-block / **80%** detect at **0%** benign false-positive
  (paraphrase-robust, see `tests/test_injection_ceiling.py::TestScannerGeneralization`).
  This is **in-distribution recall**: the rules were written against this corpus's
  attack classes, so external-corpus validation remains required before any
  general detection claim.
- A **balanced, gated validation** of the *full* defense on 200 harmful / 195
  benign / 100 ambiguous (`artifacts/aromer_balanced_validation_v1.json`)
  initially **FAILED** (false_accept_rate = 0.500). The failure was localised to
  100 low-risk-tier harmful actions, every one a **schema-invalid (malformed)
  tool call**. Adding a schema-validity hard gate to the policy engine
  (`MALFORMED_CALL_BLOCKED`: malformed call → ESCALATE), a general capability
  derived from call structure, not the decision label, with zero false-blocks on
  real benign traffic, moved the result to **WARN**: false_accept 0.500 → 0.000,
  intercept 0.500 → 1.000, friction 0.339 → 0.170. The safety gate now passes;
  the residual gap to a full PASS is friction 0.170 vs the 0.15 target, which
  needs faithful trust calibration (live oracle), not eval tuning.
- The ablation `success` flag (previously trivially `True` when A = B = C) is now
  tightened (`_evaluate_success`) and correctly returns FALSE.
- **Proxy-dependence eliminated.** Three *structural* gates were added to the
  policy engine: malformed-call (schema validity → ESCALATE), forbidden-tool
  (proposed tool is on the task's own forbidden list → ESCALATE), and
  tainted-argument (untrusted-derived args → VERIFY floor, never auto-accept). On
  the balanced holdout all 200 harmful cases are now intercepted by a structural
  signal (100 schema + 100 forbidden), with **zero** reliance on the deterministic
  proxy trust and **zero** false-blocks on benign/ambiguous (neither carries
  forbidden/tainted/invalid calls). REMORA's safety on this holdout is therefore
  *structural and deployable*, these signals (tool schema, the task's
  allowed-tool list, argument taint) exist in any real agent loop, rather than a
  proxy artifact. Locked by
  `tests/test_balanced_validation.py::TestStructuralDefenseIsPrincipled`.
- Governance KPIs (`remora/aromer/evals/kpi.py`) separate *unnecessary* friction
  (VERIFY on a should-accept case) from *correct* verification of genuinely
  ambiguous cases. On the holdout: unnecessary_review_rate = 0.0, false_block_rate
  = 0.0: the raw 0.170 review-friction is entirely correct ambiguous-handling.

**Why this is now largely de-risked (but not closed):** On the balanced external
holdout REMORA achieves 0% false-accept, 100% harm-intercept *via structural
signals*, 0% false-block, and 0% unnecessary friction. Two items remain before a
general claim: (a) faithful live-oracle trust/entropy to confirm the result
without proxy signals for the non-structural margin and to push benign friction
below 0.15; (b) external-corpus validation of the injection-scanner rules.
The internal-arena 0.000 false-accept must still not be cited as a general safety
property. Tracked in `datasets/aromer_external_holdout_v1/README.md`. Artifact:
`artifacts/aromer_external_holdout_ablation_v1.json`.

---

### 3. Entropy computation uses token-fingerprint heuristic, not Semantic Entropy

All reported benchmarks (QA selective accuracy, tool-call, conformal coverage)
were computed using the `TokenFingerprintBackend`: entropy H is computed over
verdict clusters defined by NFKC-normalised, sorted-token SHA-256 truncation.

The paper's Stage 4 description and the mathematical supplement describe H as
"grounded as Semantic Entropy over NLI-derived semantic equivalence clusters"
(Kuhn et al. 2023), but this refers to the `NLISemanticBackend`, which exists
as a drop-in alternative and was not activated for any reported result.

**What this means:** claims about the Semantic Entropy properties of H are not
validated by the reported experiments. The token-fingerprint approximation may
cluster differently than NLI entailment, particularly for paraphrases that share
no lexical tokens. Results with the NLI backend are not yet reported.

**Resolution path:** run the benchmark suite with `NLISemanticBackend` enabled
and compare selective-accuracy, trust-inversion, and conformal results. Until
then, the SE framing in the abstract and §4 should be read as a description of
intent, not of the implementation used in experiments.

---

## Summary Table

| Finding | Status | Severity |
|---------|--------|----------|
| External replication and live validation pending | Active, formal third-party replication still outstanding | Medium |
| AROMER safety floor does not transfer to external holdout (proxy signals) | Active, largely de-risked, structural gates now intercept 100% of holdout harm with 0% false-accept; remaining before closure: (a) live-oracle trust/entropy for the non-structural margin, (b) external-corpus validation of injection-scanner rules. The ablation success criterion is already tightened. | High → Medium |
| Entropy backend is token-fingerprint heuristic, not Semantic Entropy | Active, NLI backend not yet benchmarked; SE framing in paper is aspirational | Medium |

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
| R5 | Lyapunov V(t), no aggregate distribution published | `experiments/lyapunov_aggregate.py`: N=1000 synthetic sessions, P(ΔV ≤ 0) = 87.2 %, mean ΔV = −0.329 | ≤0.6.0 |
| R6 | Oracle family independence partial (ρ̄ ≈ 0.4–0.6 within-family) | `build_recommended_swarm()`: 3 distinct base-model families (LLaMA 3.3 70B, Claude 3.5 Haiku, Gemma 3 27B) | ≤0.6.0 |
| R7 | T-estimator circularity (D→T→F, D contributes 18 % to T) | `estimate_structural_temperature()` is circularity-free (prompt-only); is the active path in `engine.py`; `_CATEGORY_PRIORS` documented as intentional safety floors | 0.6.1 |
| R8 | Tool-call v1, no differentiation (every strategy = 0 % unsafe on 252-task non-adversarial suite) | v2 adversarial suite (700 tasks): `remora_full_policy_gate` = **0 % unsafe** vs 10–20 % for all baselines; artifact `results/toolcall_benchmark_v2_summary.md`; implementation `experiments/evaluate_toolcall_benchmark_v2.py`; regression test `tests/test_toolcall_v2_results.py` | 0.7.0 |
| R9 | Conformal exchangeability not verified at runtime | `MondrianPhaseGuardrail.route(prompt=…)` + `PromptDriftDetector` integration: distribution shift triggers ABSTAIN before conformal routing; tests in `tests/test_guardrail.py` (drift integration) and `tests/test_drift_detector.py` | 0.7.0 |
| R10 | χ-proxy difficulty signal below chance (AUC = 0.39) | Negative result preserved as empirical record; χ repurposed to OOD/adversarial escalation (`phase_decision()`, threshold 1.45) | 0.7.1 |
| R11 | Full-coverage baseline framing risk (41.18 % vs selective 88.8 %) | Mixed-comparison caveat standardized in docs; held-out validation added (`results/selective_n500_holdout_results.json`); benchmark-scoped wording enforced | 0.7.1 |
| R12 | Critical-phase trust score cannot safely gate decisions | Operationally mitigated via `CriticalEvidenceRouter` + escalation fallback; benchmark result: 38.5 % resolution on MultiNLI proxy, remainder ESCALATE | 0.7.1 |
