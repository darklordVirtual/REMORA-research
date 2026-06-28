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
| Tool-call benchmark v2 reduces unsafe execution for `remora_full_policy_gate` versus heuristic baselines. | Simulator-scoped 0.0000 unsafe execution for REMORA full gate versus higher heuristic baselines. | `results/toolcall_benchmark_v2_results.json`, `tests/test_toolcall_v2_results.py` |
| Agent tool hook blocks local destructive shell patterns. | Unit tests and smoke behavior verify local blocking without executing the proposed command. | `tests/test_agent_hook.py` |
| Governance Intelligence enrichment prevents mislabelled-action ACCEPTs without blocking legitimate reads. | 0.0% unsafe accepts, 100% mismatch detection, 100% legitimate-read acceptance on the 50-task deterministic benchmark; grid property test (2,160 combinations) shows enrichment never creates a new ACCEPT. | `artifacts/governance_intelligence/evaluation_results.json`, `tests/governance_intelligence/`, `tests/policy/test_governance_intelligence_never_weakens_policy.py` |

## Theoretical Derivations

| Claim | Current support | Caveat |
|---|---|---|
| Joint convergence bound couples Thompson Sampling oracle selection with adapter gradient variance. | `remora/theory/joint_convergence.py` and `tests/test_joint_convergence.py`. | Not peer reviewed or machine-checked; assumptions A1-A4 must be stated. |
| MaxEnt/Gibbs free-energy identity holds for the implemented vote-space model. | `MaxEntropyGrounding.verify_free_energy_formula()` verifies error below `1e-9`. | This grounds the implemented model, not all possible agent systems. |
| Scaling laws quantify average regret, learning rate, and marginal oracle count. | `remora/theory/scaling_analysis.py` and `tests/test_joint_convergence.py`. | The current marginal `k*(T)` formula decreases as `1/log(T)`; it is not a claim that pool size grows automatically. |

## Internal Empirical Observations

| Observation | Current support | Limitation |
|---|---|---|
| Gradient variance follows `D_coupled < C_bandit < B_adapter < A_baseline` in the N500-calibrated adaptation ablation. | `experiments/results/ablation_adaptation.json` reports 0.094288 < 0.094665 < 0.095742 < 0.096095. | Synthetic N500-calibrated simulation, not external replication. |
| Agent-hook `V(t)` trajectory is active during local tool-call gating. | `tests/test_agent_hook.py` verifies state recording. | `V(t)` values are scenario-dependent and should be reported as trajectories or aggregates, not canonical constants. |
| Building-light demo shows split action gating. | `scripts/demo_building_lights.py` is deterministic and performs no live building automation call. | Demonstration only; not an energy-sector deployment result. |
| AROMER replay arena (measured) achieves 87.5% accuracy (`replay_accuracy=0.875`) with 0% false accepts on 96 curated cases (`replay_cases=96`). | `artifacts/aromer/replay_arena_report.json` (REMORA main repo); `replay_accuracy=0.875`, `false_accept_rate=0.0`, `replay_transfer_score=1.0`. | Curated internal arena, not external validation; replay_transfer_score feeds T4 component of AII. |
| AROMER AII measurement defects (static transfer constant, dead stability term, window-noise volatility) were fixed in worker 0.2.0. | Before/after live snapshots `artifacts/aromer/intelligence_before_v020.json` / `intelligence_after_v020.json`; reference formulas tested in `tests/test_aromer_smoothing.py`. | Measurement-integrity result; AII subsequently reached TRAINED (AII=0.8442, 12+ organic cycles, 2026-06-28). |

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
