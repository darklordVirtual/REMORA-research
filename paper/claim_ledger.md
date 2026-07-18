# REMORA Claim Ledger

**Version:** main branch, June 2026  
**τ* reference value:** 0.2032 (18th-percentile neg-temperature on 80% training split; verified from `results/selective_n500_holdout_results.json`)  
**Authoritative source for all numeric claims:** `results/*.json` artifacts, not this file.

This table maps each strong claim in the paper to its evidence source,
implementation status, empirical support, limitation, and recommended
paper wording. Use this to stress-test the paper before submission.
REMORA is evaluated here as a governance overlay, not as an agent-replacement system.

| # | Claim | Evidence Source | Implementation Status | Empirical Support | Limitation | Recommended Paper Wording |
|---|-------|----------------|----------------------|-------------------|-----------|---------------------------|
| 1 | REMORA filters failed oracles before consensus | `remora/engine.py` lines 398–403 | Implemented | 104 tests; deterministic | External oracle outage patterns require broader testing | "The implementation excludes failed oracle responses (non-null `error` field) from all consensus aggregation." |
| 2 | Oracle fan-out is parallel | `remora/engine.py` lines 107–111 (`ThreadPoolExecutor`) | Implemented | Code inspection | Sequential fallback on RuntimeError | "Oracle models are queried in parallel using `concurrent.futures.ThreadPoolExecutor`; a sequential fallback is invoked on event-loop conflicts." |
| 3 | Correlation-aware weighting down-weights correlated oracles | `remora/correlation.py` lines 45–57 | Implemented | Functional tests | Empirical benefit not ablated independently vs. unweighted | "Diversity weights are inversely proportional to pairwise rolling agreement rate, penalizing coracles that frequently agree with the swarm." |
| 4 | 88.8% selective accuracy at 18% coverage (in-sample); 88.0% on held-out | `results/selective_n500_results.json`; `results/selective_n500_holdout_results.json` | N/A (evaluation result) | In-sample: 95% CI [81.0, 93.6], p≈0. Held-out: 22/25, CI [70.0, 95.8], p=1.45e-5. **τ* = 0.2032** (18th-percentile neg-temperature on 80% training split, verified from artifact). | Holdout N=25 accepted items is small; coverage shifts from 18% → 23.2% when τ* applied to holdout. | "REMORA achieves 88.8% selective accuracy at 18% in-sample coverage and 88.0% on a stratified 20% holdout (N_accepted=25, τ*=0.2032, Wilson CI [70.0, 95.8%], p=1.45×10⁻⁵) with τ* locked from the training split." |
| 5 | 0% unsafe execution on tool-call benchmark | `results/toolcall_benchmark_v2_results.json` key: `remora_full_policy_gate` | N/A (evaluation result) | Yes; N=700 synthetic adversarial tasks | Synthetic benchmark; real tool ecosystems may differ | "On the 700-task adversarial synthetic tool-call benchmark, REMORA's full policy gate achieves 0% unsafe execution compared to 10–20% for all baselines." |
| 6 | Hard policy blocks are essential (not thermodynamics alone) | `results/toolcall_benchmark_v2_results.json` key: `remora_temperature_gate_heuristic` | N/A (evaluation result) | Temperature-gate-only: 10% unsafe vs 0% full policy | Same caveat as #5 | "The temperature-gate-only ablation achieves 10% unsafe execution; full policy gate (adding hard blocks) reduces this to 0%, demonstrating that thermodynamic routing alone is insufficient." |
| 7 | Critical-phase trust anticorrelation | `NEGATIVE_RESULTS.md` (Resolved Findings Archive R12); `results/mondrian_v2_repeated_splits.json` | N/A (evaluation result) | Q4 high-trust: 50% correct; Q1: 75% correct; N=32 real-oracle items | Small N; simulated augmentation used for N=511 | "On N=32 real-oracle critical-phase items, higher trust scores are associated with lower correctness (Q4: 50% vs Q1: 75%), indicating that trust alone cannot safely gate critical-phase decisions." |
| 8 | Evidence router: 38.5% resolution, 100% precision | `results/rag_critical_router_v1_results.json` | Implemented (oracle-proxy signal) | Yes; N=3000 MultiNLI | MultiNLI is a proxy; real evidence quality may differ; oracle-proxy signal used | "On the MultiNLI evidence benchmark (N=3,000), the evidence router achieves 38.5% resolution rate with 100% precision on evidence-accept decisions (`N=304`, Wilson CI [98.75%, 100.00%]) and 0% false-accept rate on contradicted claims." |
| 9 | χ-proxy AUC = 0.39 | `results/chi_perturbation_study_results.json` | N/A (empirical finding) | Yes; N=302 | AUC measurement is on N=302, partially author-curated | "Susceptibility χ achieves AUC = 0.39 as a standalone difficulty predictor on N=302 items, below chance for binary classification. This is a documented negative result." |
| 10 | Lyapunov stability: P(ΔV≤0) = 87.2% | `results/lyapunov_aggregate_results.json` | N=1000 synthetic sessions | Yes | Synthetic sessions; mean_delta_V=-0.329 | "Across 1,000 synthetic sessions (5–20 steps each), 87.2% exhibit non-increasing V(t) throughout, with mean ΔV = −0.329." |
| 11 | OPA adapter fails closed | `remora/policy/opa_adapter.py` lines 103–208 | Implemented (partial, requires external OPA daemon) | Code inspection; tests in `test_opa_adapter.py` (if exists) | Python fallback uses same rules, not hardened differently | "When the OPA server is unreachable, the adapter silently falls back to the Python policy engine and records `source_of_decision = 'python_fallback'` in the audit envelope." |
| 12 | Audit hash-chain is tamper-evident, not tamper-proof | `remora/audit/hash_chain.py` | Implemented | Code inspection; `verify()` method tested | Does not prevent replacement of entire chain by adversary with storage access | "The SHA-256 hash-chain detects tampering (chain breaks on modification) but does not prevent it. Tamper-proof audit requires external append-only storage as a deployment dependency." |
| 13 | Mondrian ordered-phase: 99.9% coverage, 0/20 failures at 15% target | `results/mondrian_v2_repeated_splits.json` | Implemented | Yes; N=2161 augmented dataset, 20 seeds | Augmented dataset uses simulated trust distributions; 817 TruthfulQA items added | "On the augmented N=2,161 dataset with 20 random seeds, Mondrian phase-stratified conformal achieves 99.9% ordered-phase coverage with 0/20 seed failures at the 15% risk target." |
| 14 | T–D circularity resolved by structural temperature | `remora/thermodynamics.py` lines 251–309; `NEGATIVE_RESULTS.md` finding R7 | Implemented (structural T is active path) | Code inspection; docstring documents resolution | Legacy estimator preserved for backward compatibility | "The structural temperature estimator computes T from prompt structure alone (zlib compression ratio, log-normalized length, domain prior), independent of oracle responses, resolving a previously documented T–D circularity." |
| 15 | Evidence signal is oracle-proxy, not real retrieval | `remora/engine.py` lines 472–522; source docstring | Implemented (proxy) | Code inspection | Core limitation: field evidence quality differs from proxy | "In the current implementation, the EvidenceSignal is constructed as a proxy from oracle consensus statistics, not from a semantic retrieval system. External BM25/NLI retrieval is the pluggable interface target." |
| 16 | Benchmark contains 13.8% author-curated items | `results/ablation_v2_n500_results.json` metadata; `NEGATIVE_RESULTS.md` | N/A | Metadata audit | Selection bias cannot be excluded | "75 of 544 benchmark items (13.8%) were assembled by the system author. Results on this subset should be interpreted with caution; the public-source items (TruthfulQA, BoolQ) are independently sourced." |
| 17 | Frontend is deterministic simulation, not live oracle | `frontend/src/lib/remora-sim.ts` | Demo | Code inspection (seeded RNG, hardcoded scenario biases) | None (correctly labelled) | "The Control Room frontend uses a deterministic simulator with seeded RNG. Oracle votes, latencies, and evidence snippets are synthetic; policy routing and thermodynamic observables use the genuine backend implementation." |

---

## High-Risk Claims (Require Extra Care)

| Claim | Risk | Required Caveat |
|-------|------|----------------|
| "88.8% accuracy at 18% coverage" | In-sample optimum; small holdout N=25 accepted | Must state both in-sample and held-out results; note holdout N |
| "0% unsafe execution" | Synthetic benchmark; adversarial patterns not exhaustive | Must state "synthetic adversarial benchmark" |
| "100% precision on evidence-accept" | MultiNLI proxy; oracle-proxy evidence signal | Must state "oracle-proxy evidence signal; MultiNLI as proxy for real evidence" |
| "Lyapunov stability" | Synthetic sessions, not formal Lyapunov theorem | Must state "empirical measurement on synthetic sessions; not a formal Lyapunov theorem" |
| "tamper-evident audit" | Not tamper-proof without WORM storage | Must state distinction every time |
| "critical-phase anticorrelation" | N=32 real-oracle items is small | Must state N and note simulated augmentation |

---

## Claims Explicitly Avoided

The following claims were NOT made in the paper and must not be added:

- "REMORA guarantees truth."
- "REMORA solves hallucination."
- "REMORA is production-ready for safety-critical systems."
- "Thermodynamics proves model correctness."
- "The audit is immutable." (always "tamper-evident")
- "The system autonomously changes critical parameters safely."
- "Oracle diversity is guaranteed." (always "partial diversity")
