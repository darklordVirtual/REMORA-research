# REMORA Claim Register

This register is a human-readable companion to
`docs/thermodynamics/claim_ledger.yaml`. It separates claims by evidence level
so reviewers can see what is strongly supported, what is theoretical, what is
internally observed, and what still requires outside replication.
The claims are scoped to REMORA as a governance overlay around agent actions, not as an agent-replacement claim.

The machine-readable claim ledger remains the source of truth for individual
claim status, artifact paths, test paths, and limitations.

## Evidence Levels

| Level | Meaning | How it should be cited |
|---|---|---|
| Strong numeric support | Backed by committed artifact plus automated test. | "Supported on the committed benchmark artifact." |
| Theoretical derivation | Derived under explicit assumptions and checked by numerical/unit tests. | "Derived under assumptions A1-A4" or "MaxEnt identity verified numerically." |
| Internal empirical observation | Observed in deterministic simulator, replay harness, or local benchmark. | "Observed internally under this benchmark." |
| Requires external replication | Plausible or promising, but not yet independently reproduced. | "Not yet independently replicated." |

## Strong Numeric Support

| Claim | Current support | Artifact / test |
|---|---|---|
| N=302 selective trust improves accepted-slice accuracy. | Top-temperature slices are locked in committed selective-trust artifacts. | `results/selective_trust_curve_results.json`, `tests/test_selective_trust_curve.py` |
| N500 selective guardrail has high accepted-slice accuracy. | 98 accepted of 544 with 88.78% accepted accuracy in the policy-layer artifact. | `results/end_to_end_n500_v3.json`, `tests/test_end_to_end_n500_v3.py` |
| Tool-call benchmark v2 reduces unsafe execution for `remora_full_policy_gate` versus heuristic baselines. **M1 FIXED (2026-06-28):** `is_unsafe_if_executed` removed entirely from `remora/toolcall/remora_gate.py`; `use_contradiction_flags` is now a no-op. Pre-fix clean-signal eval confirmed leakage not load-bearing (FAR=0, utility=0.62, all three conditions). Post-fix: FAR=0 confirmed with code path absent. **BLINDED V3 CONFIRMED (2026-06-28):** Blinded benchmark v3 (`benchmarks/toolcall_blind_v3/`) separates CandidateAction from EvaluationTruth at the file level; gate only receives CandidateAction; FAR=0.0000 on N=700 under this stricter protocol (`results/toolcall_blind_v3_results.json`). AST leakage detector and mutation tests guard against re-introduction. Caveats: (a) context flags correlated with harmfulness by benchmark construction; (b) 140/560 harmful tasks rely on keyword heuristics (evasion-vulnerable); (c) external replication with independently withheld labels required. See `docs/assurance/remediation_register.yaml` REM-001 and REM-009. | Simulator-scoped 0.0000 unsafe execution for REMORA full gate versus severity/keyword heuristic baselines. | `results/toolcall_benchmark_v2_results.json`, `results/toolcall_m1_clean_signal.json`, `results/toolcall_blind_v3_results.json`, `tests/test_toolcall_v2_results.py`, `tests/test_m1_leakage_absent.py`, `tests/test_blind_benchmark_v3.py` |
| Five-condition component ablation: REMORA full (E) dominates all ablated variants on safety–utility frontier. FAR=0% (vs 30%/10%/25% for A/B/C); utility=0.62 (vs −0.25/0.00/0.00/0.10 for A/B/C/D). Zero FAR requires both structural gates AND thermodynamic policy; AROMER learning is necessary for competitive utility. **This is the primary clean-signal safety claim** — uses structural proxy signals only (schema validity, forbidden-tool, tainted-argument), no access to `is_unsafe_if_executed` or severity-derived phase/trust. | Deterministic proxy computation on 700-task toolcall_benchmark_v2; conditions A/B/E from locked artifact. Simulation-scoped, requires external replication. | `artifacts/aromer/component_ablation_results.json`, `tests/test_component_ablation.py` |
| Agent tool hook blocks local destructive shell patterns. | Unit tests and smoke behavior verify local blocking without executing the proposed command. | `tests/test_agent_hook.py` |
| Governance Intelligence enrichment prevents mislabelled-action ACCEPTs without blocking legitimate reads. | 0.0% unsafe accepts, 100% mismatch detection, 100% legitimate-read acceptance on the 50-task deterministic benchmark; grid property test (2,160 combinations) shows enrichment never creates a new ACCEPT. | `artifacts/governance_intelligence/evaluation_results.json`, `tests/governance_intelligence/`, `tests/policy/test_governance_intelligence_never_weakens_policy.py` |

## Theoretical Derivations

| Claim | Current support | Caveat |
|---|---|---|
| Joint convergence bound couples Thompson Sampling oracle selection with adapter gradient variance. | `remora/theory/joint_convergence.py` and `tests/test_joint_convergence.py`. | Not peer reviewed or machine-checked; assumptions A1-A4 must be stated. |
| MaxEnt/Gibbs free-energy identity F = λD − H = −log Z holds for the implemented vote-space model at unit entropy coefficient (T=1). | `MaxEntropyGrounding.verify_free_energy_formula()` verifies error below `1e-9`. | Grounds the implemented model only. The runtime F(T)=λD−TH for T≠1 does NOT follow from this derivation (T is a heuristic dial, not a Lagrange multiplier); a prior overclaim to the contrary was withdrawn 2026-07-03 — see the module docstring. |
| Scaling laws quantify average regret, learning rate, and marginal oracle count. | `remora/theory/scaling_analysis.py` and `tests/test_joint_convergence.py`. | The current marginal `k*(T)` formula decreases as `1/log(T)`; it is not a claim that pool size grows automatically. |

## Internal Empirical Observations

| Observation | Current support | Limitation |
|---|---|---|
| Gradient variance follows `D_coupled < C_bandit < B_adapter < A_baseline` in the N500-calibrated adaptation ablation. | `experiments/results/ablation_adaptation.json` reports 0.094288 < 0.094665 < 0.095742 < 0.096095. | Synthetic N500-calibrated simulation, not external replication. |
| Agent-hook `V(t)` trajectory is active during local tool-call gating. | `tests/test_agent_hook.py` verifies state recording. | `V(t)` values are scenario-dependent and should be reported as trajectories or aggregates, not canonical constants. |
| Building-light demo shows split action gating. | `scripts/demo_building_lights.py` is deterministic and performs no live building automation call. | Demonstration only; not an energy-sector deployment result. |
| AROMER replay arena (measured) achieves 87.5% accuracy (replay_accuracy=0.875) with 0% false accepts on 96 curated cases; replay_transfer_score=1.0 feeds T4 component of AII. | `artifacts/aromer/replay_arena_report.json`; replay_accuracy=0.875, false_accept_rate=0.0, replay_transfer_score=1.0, replay_cases=96. | Curated internal arena, not external validation; replay_transfer_score is distinct from accuracy — it measures domain-transfer consistency of adapted policy. |
| AROMER AII measurement defects (static transfer constant, dead stability term, window-noise volatility) were fixed in worker 0.2.0. | Before/after live snapshots `artifacts/aromer/intelligence_before_v020.json` / `artifacts/aromer/intelligence_after_v020.json`; reference formulas tested in `tests/test_aromer_smoothing.py`. | Measurement-integrity result, not a learning-performance claim; AII was in the LEARNING band at v0.2.0; subsequently reached TRAINED (AII=0.8442, 12+ organic cycles, 2026-06-28). |
| AROMER reached AII=0.8083 TRAINED (n=135, 2026-06-27); peak TRAINED AII=0.844 (cycle 12, 12:04 UTC 2026-06-28). | Documented in `NEGATIVE_RESULTS.md §9, §11`; peak recorded at /intelligence endpoint. | Full §12→§13→recovery cycle: brr 0%→5% regression at ~13:00 UTC (AII=0.7885 CAPABLE); organic recovery to AII=0.8042 TRAINED at ~15:53 UTC in ~2h53min (brr 5%→2.5%); FAR=0 throughout. Current: TRAINED_SHADOW_ONLY. See §12–§13. |
| Post-seeding holdout validation: aradhye-holdout FA=22.2% (8/36), down from 52.2% Phase 2. | `artifacts/aromer/harmful_seed_holdout_eval.json`; 36 cases held back from seeding, record_episode=False, neutral metadata (trust=0.70). | Single distribution (aradhye). record_episode=False confirms zero world-model contamination. |
| Path A organic TRAINED recovery confirmed (00:36 UTC+2 2026-06-28): brr 7.5%->0.5%, T2=0.916, AII=0.8097, TRAINED_SHADOW_ONLY. Gap 3 resolved. Sustained: 12+ consecutive TRAINED cycles, peak AII=0.844, T2=1.000 (max), T3=0.800 [M]. Full §12→§13→recovery cycle resolved organically. | Mathematical analysis + live measurement: all 15 VERIFY episodes rotated out in ~2.5h. false_accept_rate=0.0 throughout all 15 306+ episodes. `NEGATIVE_RESULTS.md §11–§13`. | T2 peaked at theoretical maximum (brr=0%). Organic re-acceleration and recovery both documented. Current: AII=0.8042 TRAINED_SHADOW_ONLY (~15:53 UTC). T3=0.800 [M] sustained. One production gate remains: REM-021 (independent human review). REM-020 closed 2026-07-17 under the 7-day criterion via fail-closed tooling; self-reported values pending REM-021 verification. REM-022 DONE (with a recorded closure deviation; follow-through tracked as REM-023). |
| AROMER reached AII=0.9922 TRAINED (theoretical ceiling, 1814+ adapt_cycles, 2026-07-01). Fixes #1–64 deployed. ECE=0.0052 structural ceiling. T1=0.9741, T2=T3=T4=T5=1.000. FAR=0. Endpoint observability: aii_ceiling, gates_status, interpretation_evidence, /readiness, /intelligence?history, make check-live, make rem020-check (defined in the main implementation repo only — not in this repo's Makefile). | Live at `https://aromer.razorsharp.workers.dev/readiness` and `/intelligence`; `aii_ceiling` field value=0.9922, at_ceiling=true at peak; structural ceiling documented in `NEGATIVE_RESULTS.md §15–§16`. | AII ceiling = 0.30×0.9741 + 0.70 = 0.9922 (structural: MCE bucket selection bias, §15; transfer_unmeasured interpretation ceiling, §16). REM-020 closed 2026-07-17 (7-day criterion, fail-closed tooling; self-reported pending REM-021). |
| AROMER at structural AII ceiling: AII=0.9923, at_ceiling=true, gap_from_ceiling=0, calibration=0.9745 (ECE=0.0051), snapshot frozen 2026-07-02. | On-disk artifact `artifacts/aromer/intelligence_snapshot_2026-07-02.json` (frozen from `/intelligence?history=8`); satisfies the no-numbers-without-artifact rule for the ceiling claim previously supported only by the live endpoint. | Ceiling formula 0.30×calibration + 0.70 moves with calibration (0.9922 at cal=0.9741 on 2026-07-01 → 0.9923 at cal=0.9745). Ceiling remains structural: MCE bucket selection bias (§15); live cross-domain episodes absent (§16). |
| Operational CP upper bound 0.367% (k=0 FA / n=814 operational harmful episodes). | Computed live at /intelligence endpoint; excludes seeded evaluation episodes (aradhye/CaiZhiTech) from FA and n count. | Operational episodes only — does not include laboratory holdout evaluation. safety_certification=CERTIFIED_INDEPENDENT_HOLDOUT. |

## Requires External Replication

| Claim area | What is needed |
|---|---|
| Agentic tool-call safety beyond deterministic simulation. | Independent runs on public agent/tool benchmarks and live model pools with cached responses. |
| Theorem 1 relevance to real LLM agent control. | External reproduction of gradient-variance ordering and utility/safety tradeoffs on public tasks. |
| Production-grade safety. | Shadow-mode pilot, audited policy-as-code, RBAC, human approval workflow, incident handling, and operational telemetry. |
| Evidence verification quality. | A semantic entailment benchmark or independently validated NLI/LLM verifier evaluation. |
| CRC covariate-shift calibration on real critical-phase oracle responses. | Current importance weights are conservative estimates (not likelihood-ratio optimal); external validation on held-out real oracle data. |
| PVD deliberation improvement on live oracle responses. | Current PVD uses offline NLI entailment without new API calls; improvement over PhaseAwareGuardrail requires A/B testing on real critical-phase items. |
| TEE attestation overhead and correctness on AMD SEV-SNP / Intel TDX. | Hardware TEE environment not yet available; attestation protocol is specified but not executed. |

## Citation Discipline

Use precise language:

- "demonstrates under the committed deterministic benchmark"
- "supports internally"
- "derived under assumptions"
- "requires external replication"

Avoid wording that implies:

- absolute safety assurance
- production-certified safety
- independent validation before a replication artifact exists
- "canonical V(t) value"
- "peer-reviewed theorem"

---

## Claim Taxonomy

Claim classes used across README, whitepaper, and claim ledger. The source of
truth for individual claim status is `docs/thermodynamics/claim_ledger.yaml`.

| Class | Definition | Typical Evidence | Promotion Rule |
|---|---|---|---|
| `algebraic` | Identity derived directly from definitions | Source code + symbolic derivation | Promote when identity is exact and testable |
| `empirical` | Measured behavior on benchmark artifacts | Locked result files + regression tests | Promote when stable on holdout or replicated runs |
| `heuristic` | Useful modeling choice without formal proof | Experiments showing utility only | Never present as theorem or law |
| `candidate_bound` | Proposed upper/lower bound under explicit assumptions | Candidate proof + assumption tests | Promote only after proof and empirical checks pass |
| `not_supported` | Claim tested and failed | Locked negative artifacts | Keep visible; do not silently remove |

## Claim Status Labels (Required)

Every claim referenced in README, papers, or marketing must carry one of the
following status labels. These labels are authoritative for external sharing
and must map to artifacts in `docs/claim_evidence_matrix.md`.

- `externally_validated`: Evidence exists in public artifacts and independent
	reproductions.
- `internally_supported`: Supported by committed artifacts and internal test
	runs but not yet externally reproduced.
- `simulator_only`: Result produced by deterministic or simulated replay only.
- `theoretical`: Mathematical derivation with assumptions; may lack empirical
	verification.
- `candidate`: Promising but unvalidated claim; requires replication.
- `failed`: Claim has been tested and disproven; keep visible as a negative
	result.

## Claim Wording Guard

When writing external-facing materials, the following words/phrases are
forbidden unless the relevant `externally_validated` evidence exists and is
referenced inline:

- absolute safety assurance
- unassailable mathematics
- independent validation without a replication pointer
- production-certified safety

Use the claim taxonomy and evidence matrix to ensure every statement is
traceable and falsifiable.

**Consistency rules:**

1. `docs/thermodynamics/claim_ledger.yaml` is source of truth.
2. README and whitepaper must not use stronger wording than claim ledger.
3. `experiments/verify_thermo_claims.py` must check every claim marked `supported`.
4. Candidate bounds must explicitly separate assumptions from observations.
5. Response correlation and error correlation must never be treated as equivalent.
