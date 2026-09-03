<!-- GENERATED FILE. DO NOT EDIT.
     Source: docs/research/research_control_matrix_v1.yaml
     Regenerate: python scripts/generate_research_control_matrix.py -->

# REMORA Research Control Matrix

The machine-checked chain from research source to tested code, one row per research line. Every code and test path below is verified to exist on disk by CI; the literature narrative lives in [docs/09-related-work.md](../09-related-work.md).

Source of truth: `docs/research/research_control_matrix_v1.yaml` (schema 1, updated 2026-09-03).

## Summary

| ID | Research line | Controls | Maturity |
|----|---------------|----------|----------|
| RES-001 | Causal post-hoc explainability and concept interventions | `causal_policy_explanation` | `implemented_and_tested` |
| RES-002 | Selective prediction and abstention | `phase_aware_guardrail`, `selective_routing` | `implemented_and_tested` |
| RES-003 | CRC-inspired weighted empirical selective routing | `conformal_thresholding` | `empirically_evaluated_adaptation` |
| RES-004a | Multi-oracle consensus and aggregation | `multi_oracle_consensus` | `implemented_and_tested` |
| RES-004b | LLM-as-judge cross-model verification | `independent_verifier_gate` | `implemented_and_tested` |
| RES-005 | Tool-use safety and agent guardrails | `toolcall_gate`, `action_type_mapping` | `implemented_and_tested` |
| RES-006 | Evidence grounding and retrieval-augmented verification | `evidence_verifier` | `implemented_and_tested` |
| RES-007 | Statistical-physics control signals (entropy, phase, Lyapunov) | `phase_classification`, `thermodynamic_braking` | `library_only` |
| RES-008 | Nested learning, context flow, continuum memory | `context_flow_governance`, `governed_memory_layers`, `reviewed_policy_proposals` | `conceptual_translation_implemented` |
| RES-009 | Enterprise AI governance and audit | `enterprise_rollout_reference` | `reference_design` |
| RES-010 | Anytime-valid confidence sequences (optional-stopping-safe monitoring) | `continuous_far_monitoring` | `implemented_and_tested` |
| RES-011 | SDAD-inspired content-bound specification intake | `signed_context_manifest`, `evidence_vector_spec_intake` | `conceptual_translation_implemented` |
| RES-012 | Task-bound execution authority and non-decaying loop state | `task_identity_binding`, `authorization_context_task_fields` | `implemented_and_tested` |

## RES-001; Causal post-hoc explainability and concept interventions

- Source: Bjøru, A. R. (2026). Causal Post-hoc Explainable AI (PhD thesis), NTNU. (cited in code; anchor `Bjøru`; CI-verified)
  - Paper IV §3 (concept-based externally-causal XAI)
  - Paper IV §4.2.1 (global explanation by dataset averaging)
  - Paper IV §4.2.2-§4.2.3 (Probability of Sufficiency / Necessity)
  - Paper IV §4.2.4 (minimal contrastive explanation search)
  - builds on: Pearl, J. (2009). Causality (2nd ed.), ch. 9 (PS/PN definitions).
  - builds on: Galhotra, Pradhan & Salimi (2021), SIGMOD (contrastive explanations).
- Concepts: concept_based_external_causal_xai, probability_of_sufficiency, probability_of_necessity, minimal_contrastive_intervention, global_concept_attribution
- REMORA controls: causal_policy_explanation
- Code: [`remora/causal/schema.py`](../../remora/causal/schema.py), [`remora/causal/search.py`](../../remora/causal/search.py), [`remora/causal/attribution.py`](../../remora/causal/attribution.py), [`remora/causal/explanation.py`](../../remora/causal/explanation.py)
- Tests: [`tests/test_causal.py`](../../tests/test_causal.py), [`tests/test_causal_search_attribution.py`](../../tests/test_causal_search_attribution.py)
- Evidence: PS/PN in {0,1}, minimality, verdict-change, and global mean-PS ordering are unit-tested; result carried on DecisionEnvelope.causal_explanation.
- Maturity: `implemented_and_tested`
- Scope boundary: Deterministic policy-level PS/PN operationalisation: binary per-instance indicators evaluated against the policy model, not population-level probabilities and not the world. No real-world causal-effect or safety claim.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §9
- Landscape (local compendium): No anchor in the local compendium: its interpretability chapter covers mechanistic interpretability (superposition, monosemanticity, circuit tracing), not causal post-hoc concept XAI. This line's sources (Bjøru 2026; Pearl; Galhotra et al.) sit outside the compendium's scope.

## RES-002; Selective prediction and abstention

- Source: Idea family (no single named source in-repo): selective classification / reject option, risk-coverage curves, calibrated abstention. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- Concepts: selective_classification, reject_option, risk_coverage_curve, calibrated_abstention
- REMORA controls: phase_aware_guardrail, selective_routing
- Code: [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py)
- Tests: [`tests/test_guardrail.py`](../../tests/test_guardrail.py), [`tests/test_selective_trust_curve.py`](../../tests/test_selective_trust_curve.py), [`tests/test_selective_n500.py`](../../tests/test_selective_n500.py)
- Evidence: Guardrail and risk-coverage behaviour is unit-tested directly (tests/test_guardrail.py). The empirical arm is the N=500 selective acceptance run, whose committed artifact now backs a NEGATIVE result: on the critical-phase subset trust anti-correlates with correctness (CLAIM-005), which is what PhaseAwareGuardrail routes around. tests/test_selective_trust_curve.py is retained as an artifact lock on a SUPERSEDED result, not as evidence for this line: it pins the N=302 neg_temperature 94.7%-at-25% figure (CLAIM-008, superseded by CLAIM-013), and the temperature signal it rests on failed its pre-registered fresh-data confirmation (CLAIM-012, "do not cite"). The lock exists so that number cannot drift silently; it must not be quoted as a selective-acceptance result.
- Maturity: `implemented_and_tested`
- Scope boundary: Benchmark-scoped selective trust; no universal out-of-distribution safety guarantee.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §1
- Landscape (local compendium): `selective-2017`, `gentle-conformal-2021`, `ltt-2021`

## RES-003; CRC-inspired weighted empirical selective routing

- Source: Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022). Conformal risk control. arXiv:2208.02814. (cited in code; anchor `Angelopoulos`; CI-verified)
  - Framework the router is inspired by, not implementing: the crc.py module docstring documents the two structural gaps (no finite-sample term in the selector; non-monotone selective loss), so Theorem 1 does not attach.
- Concepts: weighted_empirical_threshold_selection, repeated_split_robustness
- REMORA controls: conformal_thresholding
- Code: [`remora/selective/crc.py`](../../remora/selective/crc.py), [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py)
- Tests: [`tests/test_crc.py`](../../tests/test_crc.py), [`tests/test_conformal_repeated_splits.py`](../../tests/test_conformal_repeated_splits.py), [`tests/test_binomial_bounds.py`](../../tests/test_binomial_bounds.py)
- Evidence: Repeated-split holdout results in committed artifacts; all quality evidence for this component is empirical, and negative results are preserved in the claim ledger.
- Maturity: `empirically_evaluated_adaptation`
- Scope boundary: CRC-inspired, NOT a CRC procedure (external review R3-01): deterministic importance-weighted empirical threshold selector with hand-tuned phase weights, no finite-sample correction and a non-monotone selective loss - no distribution-free guarantee is claimed.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §2
- Landscape (local compendium): `conformal-risk-2022`, `ltt-2021`

## RES-004a; Multi-oracle consensus and aggregation

- Source: Wang et al. (2023), Self-Consistency Improves Chain-of-Thought Reasoning; Wang et al. (2024), Mixture-of-Agents. (cited in code; anchor `Wang et al.`; CI-verified)
  - cited at remora/cascade/stages.py (self-consistency; single-stage aggregation inspired by MoA, not the multi-layer architecture)
- Concepts: self_consistency_sampling, cross_model_dissensus, multi_agent_debate
- REMORA controls: multi_oracle_consensus
- Code: [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py)
- Tests: [`tests/test_moa_synthesizer.py`](../../tests/test_moa_synthesizer.py), [`tests/test_oracle_diversity.py`](../../tests/test_oracle_diversity.py), [`tests/test_toolcall_experiment_outputs.py`](../../tests/test_toolcall_experiment_outputs.py), [`tests/test_toolcall_benchmark_v2_results.py`](../../tests/test_toolcall_benchmark_v2_results.py), [`tests/test_rem010_llm_baselines.py`](../../tests/test_rem010_llm_baselines.py)
- Evidence: Synthesizer thresholds and oracle-diversity behaviour are unit-tested. The aggregation baselines the line is compared against (single model, majority vote, self-consistency, verifier, REMORA gate) are pinned by the tool-call benchmark tests, which re-run the experiment and assert the full baseline set is present: tests/test_toolcall_experiment_outputs.py (v1), tests/test_toolcall_benchmark_v2_results.py (adversarial v2) and tests/test_rem010_llm_baselines.py (LLM-backed baselines, REM-010). Consensus is combined with evidence, policy, risk and audit, never used alone.
- Maturity: `implemented_and_tested`
- Scope boundary: Consensus is not treated as truth; it is one input among evidence, policy, risk, and audit. Single-stage aggregation only: the multi-layer MoA architecture is not implemented.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §3
- Landscape (local compendium): `llm-uq-survey-2023`; Weak landscape anchor: the compendium treats cross-model consistency only via the confidence-and-calibration survey (llm-uq-survey-2023); the specific self-consistency and mixture-of-agents sources this line cites are not catalogued there.

## RES-004b; LLM-as-judge cross-model verification

- Source: Zheng et al. (2023), Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena; Cobbe et al. (2021), Training Verifiers to Solve Math Word Problems. (cited in code; anchor `Zheng`; CI-verified)
  - cited at remora/verifier/llm_judge.py (LLM-as-judge verifier per Zheng et al. 2023; contrast with Cobbe et al. 2021 trained outcome verifiers)
- Concepts: verifier_model, llm_as_judge
- REMORA controls: independent_verifier_gate
- Code: [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py)
- Tests: [`tests/test_llm_judge.py`](../../tests/test_llm_judge.py), [`tests/test_toolcall_experiment_outputs.py`](../../tests/test_toolcall_experiment_outputs.py), [`tests/test_toolcall_benchmark_v2_results.py`](../../tests/test_toolcall_benchmark_v2_results.py)
- Evidence: Judge verdict parsing, malformed-JSON handling and refusal behaviour are unit-tested; the verifier baseline it stands against is asserted present in the re-run tool-call benchmark results (v1 and adversarial v2).
- Maturity: `implemented_and_tested`
- Scope boundary: An untrained prompted judge, NOT a trained outcome verifier in the sense of Cobbe et al.; a judge verdict is an input to the gate, never the gate.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §3
- Landscape (local compendium): `llm-uq-survey-2023`; Weak landscape anchor: LLM-as-judge verification is catalogued in the compendium only through the confidence-and-calibration survey (llm-uq-survey-2023).

## RES-005; Tool-use safety and agent guardrails

- Source: Idea family (no single named source in-repo): tool-invocation safety, dry-run/sandboxed evaluation, critical-action routing, prompt-injection benchmarks. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- Concepts: tool_invocation_safety, dry_run_sandbox, critical_action_routing
- REMORA controls: toolcall_gate, action_type_mapping
- Code: [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py)
- Tests: [`tests/test_remora_toolcall_gate.py`](../../tests/test_remora_toolcall_gate.py), [`tests/test_remora_toolcall_gate_v2.py`](../../tests/test_remora_toolcall_gate_v2.py), [`tests/test_toolcall_scoring.py`](../../tests/test_toolcall_scoring.py), [`tests/test_toolcall_benchmark_v2_results.py`](../../tests/test_toolcall_benchmark_v2_results.py)
- Evidence: Gate behaviour on the observable task surface is unit-tested (tests/test_remora_toolcall_gate*.py, tests/test_toolcall_scoring.py); tests/test_toolcall_benchmark_v2_results.py re-runs the adversarial v2 evaluation and asserts the baseline set and the direction of the unsafe-execution reduction. The benchmark result itself is CLAIM-001: 700 tasks are 70 template clusters x 10 cosmetic variants, and because a deterministic gate decides identically within a template, all CIs and p-values are computed by cluster-level resampling over those 70 clusters (results/toolcall_benchmark_v2_significance.json). The 70 is n_template_clusters in that artifact; the per-baseline effective_n field in results/toolcall_benchmark_v2_results.json is a different, smaller quantity and is not this number. v1 is documented as showing a ceiling effect.
- Maturity: `implemented_and_tested`
- Scope boundary: v2 provides deterministic adversarial evidence, not production proof; live validation is a separate requirement.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §4
- Landscape (local compendium): `agentharm-2024`, `agentdojo-2024`, `injecagent-2024`, `agent-safety-bench-2024`

## RES-006; Evidence grounding and retrieval-augmented verification

- Source: Idea family (no single named source in-repo): RAG evidence lookup, source reliability, per-claim support/contradiction, NLI-style verification. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- Concepts: retrieval_augmented_verification, per_claim_support_contradiction, nli_style_entailment
- REMORA controls: evidence_verifier
- Code: [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py), [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py)
- Tests: [`tests/test_evidence_v3.py`](../../tests/test_evidence_v3.py), [`tests/test_evidence_verifier.py`](../../tests/test_evidence_verifier.py)
- Evidence: Lexical default verifier with a pluggable NLI-style interface; falls back to lexical when no NLI backend is configured.
- Maturity: `implemented_and_tested`
- Scope boundary: Default verifier is lexical plus simple contradiction signals; semantic-entailment quality is not demonstrated by committed artifacts.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §5
- Landscape (local compendium): `rag-2020`, `self-rag-2023`

## RES-007; Statistical-physics control signals (entropy, phase, Lyapunov)

- Source: Generic statistical-physics constructs (q-state Potts model, Gibbs/Boltzmann distribution, Lyapunov objective) used as operational analogy. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- Concepts: entropy_order_parameter, phase_regime_classification, lyapunov_stability
- REMORA controls: phase_classification, thermodynamic_braking
- Code: [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py), [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py)
- Tests: [`tests/test_statphys.py`](../../tests/test_statphys.py), [`tests/test_thermodynamics.py`](../../tests/test_thermodynamics.py), [`tests/test_thermodynamic_braking.py`](../../tests/test_thermodynamic_braking.py)
- Evidence: Regime classification (ordered/critical/disordered) and selective-trust routing exist as tested library code. NOT evidence of runtime effect: verified 2026-08-07 that no governed path populates these signals - servers/api.py never references the consensus state, servers/execution_api.py passes trust_score=None and phase=None, and build_full_observation leaves the fields at their None defaults, so the critical_phase_critical_risk rule cannot fire in production.
- Maturity: `library_only`
- Scope boundary: Library-grade only, and the framing is withdrawn from the paper (2026-08-07). The physics vocabulary (structural temperature, free energy, Lyapunov observable) invited a physical reading the system does not support, and the temperature signal it rested on FAILED its pre-registered fresh-data confirmation (CLAIM-012, NEGATIVE_RESULTS §18): temperature ranked worse than calibrated confidence. The paper now presents only the information-theoretic observables (H, D, trust score); the withdrawn material lives in the negative results. These signals are not populated on any governed path and influence no runtime decision.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §6
- Landscape (local compendium): No anchor in the local compendium: the statistical-physics control signals (q-state Potts, Gibbs/Boltzmann, Lyapunov) are used as an operational analogy specific to REMORA and are not a catalogued research area in the assurance landscape.

## RES-008; Nested learning, context flow, continuum memory

- Source: Behrouz, Razaviyayn, Zhong & Mirrokni, Nested Learning: The Illusion of Deep Learning Architecture (https://abehrouz.github.io/files/NL.pdf); Google Research blog, 2025-11-07. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- Concepts: nested_learning, context_flow, continuum_memory, governed_self_modification
- REMORA controls: context_flow_governance, governed_memory_layers, reviewed_policy_proposals
- Code: [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py)
- Tests: [`tests/test_governance_context_flow.py`](../../tests/test_governance_context_flow.py), [`tests/test_governance_memory_layers.py`](../../tests/test_governance_memory_layers.py), [`tests/test_nested_governance.py`](../../tests/test_nested_governance.py)
- Evidence: Context flow as a governed information stream; update frequency as a policy boundary; self-modification as reviewed policy proposals.
- Maturity: `conceptual_translation_implemented`
- Scope boundary: A governance translation of the Nested Learning ideas, not the architecture: does not implement Hope or nested optimisation problems, does not train foundation models, does not claim to solve catastrophic forgetting.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §7
- Landscape (local compendium): No anchor in the local compendium: the Nested Learning source (Behrouz et al., 2025) is newer than / outside the compendium's catalogue. REMORA implements only the governance framing (context-flow, reviewed memory layers), not the architecture itself.

## RES-009; Enterprise AI governance and audit

- Source: Idea family (no single named source in-repo): policy-as-code, role/authority boundaries, human-approval workflows, audit ledgers, fail-closed deployment. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- Concepts: policy_as_code, human_approval_workflow, audit_ledger, fail_closed_deployment
- REMORA controls: enterprise_rollout_reference
- Code: [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md), [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py)
- Tests: none
- Evidence: TOGAF-structured rollout plan and a runnable enterprise demo; the governance primitives themselves are tested under RES-001..008 and the capability register.
- Maturity: `reference_design`
- Scope boundary: Reference/design grade: not a production-certified enterprise product; must be validated in the target organization before enforcement.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §8
- Landscape (local compendium): `nist-ai-rmf-2023`, `iso-42001-2023`, `eu-ai-act-2024`, `governing-agents-2023`, `visibility-agents-2024`, `infra-agents-2025`

## RES-010; Anytime-valid confidence sequences (optional-stopping-safe monitoring)

- Source: Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). Time-uniform, nonparametric, nonasymptotic confidence sequences. (cited in code; anchor `Howard`; CI-verified)
  - Conjugate-mixture (Beta-binomial) supermartingale; Ville's inequality (cited in remora/selective/confidence_sequence.py)
  - builds on: Ramdas, Grünwald, Vovk & Shafer (2023). Game-theoretic statistics and safe anytime-valid inference. Statistical Science 38(4).
  - builds on: Waudby-Smith & Ramdas (2024). Estimating means of bounded random variables.
- Concepts: time_uniform_confidence_sequence, anytime_valid_inference, optional_stopping_safety
- REMORA controls: continuous_far_monitoring
- Code: [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py)
- Tests: [`tests/test_confidence_sequence.py`](../../tests/test_confidence_sequence.py)
- Evidence: An OFFLINE anytime-valid bound computed over the closed REM-020 longitudinal audit series, not a live monitor: k=0 events in n=168 adapt cycles gives a time-uniform upper bound of 4.72% on the cycle-level false-accept rate (results/far_confidence_sequence_v1.json, CLAIM-011), produced by scripts/compute_far_confidence_sequence.py. Corrected 2026-09-03: this line and the module docstring previously said the sequence is "used by REM-020 to monitor the operational false-accept rate continuously". Nothing outside tests and that one script imports the module, and REM-020 is a closed audit rather than a running gate, so the continuous-monitoring wording claimed a deployment that does not exist. What the construction buys is that the bound stays valid although the series was inspected repeatedly while it accumulated.
- Maturity: `implemented_and_tested`
- Scope boundary: A time-uniform Bernoulli-rate bound, distinct from the CRC-inspired empirical selective routing of RES-003; conservative by construction and valid only under the stated Beta-binomial mixture assumptions.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §2
- Landscape (local compendium): `confidence-seq-2021`, `game-theoretic-stat-2023`

## RES-011; SDAD-inspired content-bound specification intake

- Source: Nguyen, V. H. & Nguyen, T. (2026). SDAD: Spec-Driven Agentic Development for the AI-Native SDLC. arXiv:2608.20341v1. (cited in code; anchor `2608.20341`; CI-verified)
  - §6.1 (Context Ingestion as Execution)
  - §7.2 (completeness, consistency, unambiguity, verifiability)
  - §13.4 (operational definitions and longitudinal baselines remain open)
- Concepts: context_ingestion_as_execution, four_dimension_spec_fidelity, requirement_to_verification_traceability, content_addressed_context_provenance
- REMORA controls: signed_context_manifest, evidence_vector_spec_intake
- Code: [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py), [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml), [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json)
- Tests: [`tests/test_spec_intake.py`](../../tests/test_spec_intake.py)
- Evidence: Unit tests pin signature/digest refusal, source-order determinism, dimension separation, equal provenance for negative findings, traceability, unresolved handling, and exact reproduction of the committed reference artifact.
- Maturity: `conceptual_translation_implemented`
- Scope boundary: Structural and provenance checks only: no scalar Spec Fidelity score, no semantic-correctness or source-truth claim, no empirical SDAD validation, and no execution-API/dispatch binding until RMR-004. Agentic Autonomy Rate is not adopted as assurance evidence.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §10
- Landscape (local compendium): No anchor in the local compendium: SDAD v1 (August 2026) postdates the catalogue. REMORA adopts only the context/provenance and four-dimension intake decomposition, not the full SDLC framework or its proposed scalar metrics.

## RES-012; Task-bound execution authority and non-decaying loop state

- Source: Yan, T. (2026). Do User-Authored Permission Policies Improve Protection Against AI Agent Overreach? arXiv:2608.27443. (cited in code; anchor `2608.27443`; CI-verified)
  - 113-participant comparison of real-time approval, automated review and pre-set consequence policies
  - finding: user-authored policies blocked FEWER overreach attempts than either alternative
  - builds on: Wu, C. et al. (2026). Safety Does Not Compose: Non-Decaying Loop State for Autonomous LLM Agents. arXiv:2608.27141 (LoopHarness; trajectory-scoped monitors reset each iteration).
  - builds on: AGNTCY Identity WG (2026-08-25). Agent Identity, TBAC and A2A task authorization: standing authority today, task binding still open profile work. Locator for the working group's published identity specification: https://spec.identity.agntcy.org/docs/intro (checked 2026-09-03; the dated analysis is a working-group document, and the record of it in this repository is docs/design/task-bound-execution-authority-v1.md).
- Concepts: task_bound_authority, context_scoped_safety_state, approval_is_not_task_authority, signature_preserving_field_addition
- REMORA controls: task_identity_binding, authorization_context_task_fields
- Code: [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py), [`remora/enforcement/token.py`](../../remora/enforcement/token.py), [`scripts/generate_authorization_context_vectors.py`](../../scripts/generate_authorization_context_vectors.py), [`artifacts/task_authority/authorization_context_preimage_v1.json`](../../artifacts/task_authority/authorization_context_preimage_v1.json)
- Tests: [`tests/test_task_identity.py`](../../tests/test_task_identity.py), [`tests/test_task_bound_authority.py`](../../tests/test_task_bound_authority.py)
- Evidence: An approval bound to one task yields a different AuthorizationContext hash under another, while every binding REMORA already checked stays identical. The committed preimage artifact records that a context carrying no task identity hashes byte-identically to the pre-change implementation, so tokens issued since RMR-001 still verify; scripts/generate_authorization_context_vectors.py --check reproduces it exactly.
- Maturity: `implemented_and_tested`
- Scope boundary: Binding only. This is not proof-of-possession: it binds an authorization to a task and does not prove the presenter holds a key, and nothing here closes the AGNTCY profile's PoP requirement. The A2A envelope and ExecutionLease halves, the declared-operation subset check and the loop-safety store are designed but not implemented at this revision. LoopHarness itself is not implemented; only the context_id key its state would need.
- Literature: [docs/09-related-work.md](../../docs/09-related-work.md) §11
- Landscape (local compendium): No anchor in the local compendium: both sources are from August 2026 and postdate the catalogue. Both arXiv identifiers were retrieved and checked against the arXiv record on 2026-08-30 before being entered here.

## Reverse index: code → research

| Code file | Research line(s) |
|-----------|------------------|
| [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json) | RES-011 |
| [`artifacts/task_authority/authorization_context_preimage_v1.json`](../../artifacts/task_authority/authorization_context_preimage_v1.json) | RES-012 |
| [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md) | RES-009 |
| [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py) | RES-009 |
| [`remora/cascade/stages.py`](../../remora/cascade/stages.py) | RES-004a |
| [`remora/causal/attribution.py`](../../remora/causal/attribution.py) | RES-001 |
| [`remora/causal/explanation.py`](../../remora/causal/explanation.py) | RES-001 |
| [`remora/causal/schema.py`](../../remora/causal/schema.py) | RES-001 |
| [`remora/causal/search.py`](../../remora/causal/search.py) | RES-001 |
| [`remora/enforcement/token.py`](../../remora/enforcement/token.py) | RES-012 |
| [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py) | RES-008 |
| [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py) | RES-008 |
| [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) | RES-008 |
| [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py) | RES-011 |
| [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py) | RES-012 |
| [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py) | RES-004a |
| [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py) | RES-006 |
| [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py) | RES-006 |
| [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py) | RES-007 |
| [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py) | RES-007 |
| [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py) | RES-003 |
| [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | RES-010 |
| [`remora/selective/conformal.py`](../../remora/selective/conformal.py) | RES-002 |
| [`remora/selective/crc.py`](../../remora/selective/crc.py) | RES-003 |
| [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py) | RES-002 |
| [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) | RES-002 |
| [`remora/thermodynamics.py`](../../remora/thermodynamics.py) | RES-007 |
| [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py) | RES-005 |
| [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py) | RES-005 |
| [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) | RES-005 |
| [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) | RES-004b |
| [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml) | RES-011 |
| [`scripts/generate_authorization_context_vectors.py`](../../scripts/generate_authorization_context_vectors.py) | RES-012 |

## Reverse index: control → research → code

| Control | Research line(s) | Code |
|---------|------------------|------|
| `action_type_mapping` | RES-005 | [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) |
| `authorization_context_task_fields` | RES-012 | [`artifacts/task_authority/authorization_context_preimage_v1.json`](../../artifacts/task_authority/authorization_context_preimage_v1.json), [`remora/enforcement/token.py`](../../remora/enforcement/token.py), [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py), [`scripts/generate_authorization_context_vectors.py`](../../scripts/generate_authorization_context_vectors.py) |
| `causal_policy_explanation` | RES-001 | [`remora/causal/attribution.py`](../../remora/causal/attribution.py), [`remora/causal/explanation.py`](../../remora/causal/explanation.py), [`remora/causal/schema.py`](../../remora/causal/schema.py), [`remora/causal/search.py`](../../remora/causal/search.py) |
| `conformal_thresholding` | RES-003 | [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py), [`remora/selective/crc.py`](../../remora/selective/crc.py) |
| `context_flow_governance` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `continuous_far_monitoring` | RES-010 | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) |
| `enterprise_rollout_reference` | RES-009 | [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md), [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py) |
| `evidence_vector_spec_intake` | RES-011 | [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json), [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py), [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml) |
| `evidence_verifier` | RES-006 | [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py), [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py) |
| `governed_memory_layers` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `independent_verifier_gate` | RES-004b | [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) |
| `multi_oracle_consensus` | RES-004a | [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py) |
| `phase_aware_guardrail` | RES-002 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) |
| `phase_classification` | RES-007 | [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py), [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py) |
| `reviewed_policy_proposals` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `selective_routing` | RES-002 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) |
| `signed_context_manifest` | RES-011 | [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json), [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py), [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml) |
| `task_identity_binding` | RES-012 | [`artifacts/task_authority/authorization_context_preimage_v1.json`](../../artifacts/task_authority/authorization_context_preimage_v1.json), [`remora/enforcement/token.py`](../../remora/enforcement/token.py), [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py), [`scripts/generate_authorization_context_vectors.py`](../../scripts/generate_authorization_context_vectors.py) |
| `thermodynamic_braking` | RES-007 | [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py), [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py) |
| `toolcall_gate` | RES-005 | [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) |

## Reverse index: claim → research

Claims named in a research line's evidence. Not every line cites a claim id in prose; absence here does not mean absence of evidence (see each line's **Evidence** field above).

| Claim | Research line(s) |
|-------|------------------|
| CLAIM-001 | RES-005 |
| CLAIM-005 | RES-002 |
| CLAIM-008 | RES-002 |
| CLAIM-011 | RES-010 |
| CLAIM-012 | RES-002 |
| CLAIM-013 | RES-002 |

## Bibliography reconciliation

Every reference in [`paper/remora_paper.md`](../../paper/remora_paper.md) with the role it plays in REMORA. The research lines above are deliberately few (a line requires code **and** tests); this table accounts for the rest, so "absent from the matrix" is a stated decision rather than an unexplained gap. Roles describe how REMORA uses a work, not the work's importance. A positioning_only source can be central to the argument of the paper and still be absent from the code; that is the normal case for related work.

| Role | Works | Asserts |
|------|-------|---------|
| Implemented research line | 8 | present in the codebase |
| Grounds a module (no dedicated line) | 11 | present in the codebase |
| Evaluation source | 4 | present in the codebase |
| Standard, regulation or tool | 4 | no code claim |
| Related-work positioning only | 40 | no code claim |

### Implemented research line (8)

Covered by a research line above, with code and tests. The `Line` column points at it.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `angelopoulos-2022-conformal` | arxiv:2208.02814 | RES-003 | [`remora/selective/crc.py`](../../remora/selective/crc.py) | none |
| `bjru-2026-causal` | isbn:978-82-353-0022-5 | RES-001 | [`remora/causal/schema.py`](../../remora/causal/schema.py) | none |
| `cobbe-2021-training` | arxiv:2110.14168 | RES-004b | [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) | none |
| `howard-2021-time` | none | RES-010 | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | none |
| `pearl-2009-causality` | none | RES-001 | [`remora/causal/attribution.py`](../../remora/causal/attribution.py) | none |
| `ramdas-2023-game` | none | RES-010 | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | none |
| `wang-2023a-self` | none | RES-004a | [`remora/cascade/stages.py`](../../remora/cascade/stages.py) | none |
| `zheng-2023-judging` | none | RES-004b | [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) | none |

### Grounds a module (no dedicated line) (11)

Cited in a code docstring as the basis for a module, but not large enough to be its own research line. CI verifies the surname appears in the named file.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `darling-1967-confidence` | none | none | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | none |
| `el-yaniv-2010-foundations` | none | none | [`remora/selective/risk_control.py`](../../remora/selective/risk_control.py) | Selective-classification foundations behind the RES-002 idea family. |
| `farquhar-2024-detecting` | none | none | [`remora/semantic_entropy.py`](../../remora/semantic_entropy.py) | The Nature follow-up to Kuhn et al.; same clustering construct. |
| `geifman-2017-selective` | none | none | [`remora/selective/risk_control.py`](../../remora/selective/risk_control.py) | SGR Algorithm 1 is implemented directly (binary search over cut points). |
| `greenblatt-2024-control` | none | none | [`remora/governance/control_protocols.py`](../../remora/governance/control_protocols.py) | AI-control taxonomy used to classify REMORA as a trusted-monitoring protocol. Classification only: the subversive-agent threat model is explicitly NOT covered. |
| `kirchner-2024-prover` | arxiv:2407.13692 | none | [`remora/selective/pvd.py`](../../remora/selective/pvd.py) | PVD framing only. REMORA does not run the training game; the module derives an offline agreement score from already-produced responses. This file carried a fabricated author list until 2026-08-07 while the paper had long been remediated, which is why tests/test_paper_no_stale_claims.py now also scans cited modules. |
| `kuhn-2023-semantic` | arxiv:2302.09664 | none | [`remora/semantic_entropy.py`](../../remora/semantic_entropy.py) | Semantic Entropy is a core observable with no RES line of its own: it is an input to RES-002/RES-004 rather than a separate control. |
| `shafer-2008-tutorial` | none | none | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | none |
| `tibshirani-2019-conformal` | none | none | [`remora/selective/crc.py`](../../remora/selective/crc.py) | Weighted conformal under covariate shift; source of the importance weights. |
| `ville-1939-etude` | none | none | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | Ville's inequality is the martingale bound the sequence rests on. |
| `vovk-2005-algorithmic` | none | none | [`remora/selective/conformal.py`](../../remora/selective/conformal.py) | none |

### Evaluation source (4)

A dataset or benchmark REMORA is evaluated **on**. Not a method REMORA implements.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `andriushchenko-2024-agentharm` | arxiv:2410.09024 | none | [`scripts/run_agentharm_benchmark.py`](../../scripts/run_agentharm_benchmark.py) | AgentHarm external validation (CLAIM-002). Imported historical artifact: it cannot be regenerated from this repository. |
| `clark-2019-boolq` | none | none | [`remora/benchmarks/extended_v2.py`](../../remora/benchmarks/extended_v2.py) | BoolQ items in the QA benchmark composition. |
| `lin-2022-truthfulqa` | none | none | [`remora/benchmarks/extended_v2.py`](../../remora/benchmarks/extended_v2.py) | TruthfulQA items in the QA benchmark composition. |
| `williams-2018-broad` | none | none | [`experiments/rag_critical_router_v1.py`](../../experiments/rag_critical_router_v1.py) | MultiNLI as the evidence-router proxy benchmark. |

### Standard, regulation or tool (4)

Aligned with or integrated, not a research result. Alignment is a mapping claim, never a conformity claim.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `european-2024-regulation` | none | none | [`remora/evidence/domains/ai_governance.py`](../../remora/evidence/domains/ai_governance.py) | EU AI Act Art. 12/14 mapped at runtime; no conformity assessment claimed. |
| `international-2016-iec` | none | none | none | IEC 61511 SIL framing in the case study. |
| `open-2024-open` | url:https://www.openpolicyagent.org/ | none | [`remora/policy/opa_adapter.py`](../../remora/policy/opa_adapter.py) | OPA/Rego adapter, failing closed to the Python engine. |
| `standards-2021-norsok` | none | none | none | NORSOK D-010 well-barrier framing in the case study. |

### Related-work positioning only (40)

Compared against or used as framing in the paper. No code, no evaluation - and that is the honest status, not an oversight.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `angelopoulos-2021-gentle` | arxiv:2107.07511 | none | none | Conformal tutorial; framing only. |
| `bloomfield-2010-safety` | none | none | none | none |
| `chennabasappa-2025-llamafirewall` | arxiv:2505.03574 | none | none | LlamaFirewall - closest industrial system in scope. |
| `choi-2026-membrane` | arxiv:2606.05743 | none | none | Membrane; contrasted with AROMER's never-weaken constraint. |
| `chow-1970-optimum` | none | none | none | Origin of the error-reject tradeoff. |
| `corsi-2021-formal` | none | none | none | none |
| `debenedetti-2024-agentdojo` | none | none | none | AgentDojo - named as a required replication target, not run. |
| `debenedetti-2025-defeating` | arxiv:2503.18813 | none | none | CaMeL; shelf SHELF-008. |
| `dong-2025-evaluating` | arxiv:2502.11347 | none | none | TEE attestation sketch; hardware integration pending. |
| `du-2024-improving` | none | none | none | Multi-agent debate; REMORA's dissensus is a one-shot analogue. |
| `endsley-1995-toward` | none | none | none | Situation awareness; supervision framing only. |
| `ge-2026-governance` | arxiv:2603.07191 | none | none | none |
| `guldimann-2024-compl` | arxiv:2410.07959 | none | none | COMPL-AI. |
| `guo-2017-calibration` | none | none | none | Calibration; REMORA deliberately does not calibrate per-oracle. |
| `inan-2023-llama` | arxiv:2312.06674 | none | none | Llama Guard - content guardrail, contrasted with action gating. |
| `kadavath-2022-language` | arxiv:2207.05221 | none | none | Self-knowledge; motivates structural over self-reported uncertainty. |
| `kelly-1998-arguing` | none | none | none | Assurance cases; DecisionEnvelope populates one node. |
| `kuncheva-2003-measures` | none | none | none | Ensemble diversity measures. |
| `lakshminarayanan-2017-simple` | none | none | none | Deep ensembles. |
| `michael-2026-permission` | arxiv:2607.13718 | none | none | Agent-permissions survey; names the open low-burden/formal/deterministic triad REMORA is positioned against. Survey size verified against the arXiv abstract 2026-08-26: '21 proposals for agent permissions systems' - the paper's count. |
| `mohri-2024-language` | none | none | none | Conformal factuality; pre-empts the general LLM-abstention move. |
| `mu-2024-rule` | none | none | none | Rule-based rewards - safety rules in training, not enforcement. |
| `qin-2026-airguard` | arxiv:2605.28914 | none | none | AIRGuard - authority confusion and action-time authorization; explicit non-claim: predates/parallels REMORA on pre-action checks. |
| `raji-2022-outsider` | arxiv:2206.04737 | none | none | Audit-ecosystem design; motivates the replay/transparency framing. |
| `rebedea-2023-nemo` | none | none | none | NeMo Guardrails. |
| `rhodes-2026-poe` | arxiv:2607.05397 | none | none | Proof of Execution - certificate-first execution evidence; REMORA differs by growing evidence out of a deployed enforcement path. |
| `ruan-2024-identifying` | none | none | none | ToolEmu anticipates the Shadow Mode counterfactual idea. |
| `shamsujjoha-2024-taxonomy` | arxiv:2408.02205 | none | none | Swiss-cheese guardrail taxonomy. |
| `sharma-2025-constitutional` | arxiv:2501.18837 | none | none | Constitutional classifiers. |
| `shi-2025-progent` | arxiv:2504.11703 | none | none | Progent; shelf SHELF-009. Defines the (safety, friction) frontier. |
| `wang-2023b-lora` | arxiv:2310.00035 | none | none | LoRA ensembles; motivates but does not validate heterogeneous aggregation. |
| `wang-2025-agentspec` | arxiv:2503.18666 | none | none | AgentSpec - DSL near-isomorphic to REMORA's policy invariants. |
| `wang-2026-pcaa` | arxiv:2606.04104 | none | none | Proof-Carrying Agent Actions - runtime-portable action certificate; REMORA trades portability for exact-call binding to one kernel. |
| `xiang-2025-guardagent` | none | none | none | GuardAgent. |
| `yadkori-2024-mitigating` | arxiv:2405.01563 | none | none | Conformal abstention for hallucination mitigation. |
| `yang-2026-agenttrust` | arxiv:2606.08539 | none | none | AgentTrust; opposite corner of the safety/friction trade-off. |
| `yao-2024-bench` | arxiv:2406.12045 | none | none | tau-bench. |
| `yuan-2024-judge` | none | none | none | R-Judge. |
| `zhan-2024-injecagent` | none | none | none | InjecAgent. |
| `zhang-2024-calibrating` | arxiv:2404.02655 | none | none | Confidence elicitation by fidelity. |

### Cited in code but not in the paper (8)

The reconciliation runs both ways. These sources ground code or a research line while the paper carries no reference to them; recorded so the asymmetry is visible instead of hidden.

| Source id | Work | Code | Note |
|-----------|------|------|------|
| `agntcy-identity-wg` | AGNTCY Identity working group: Agent Identity, TBAC and A2A task authorization (2026-08-25 analysis) | [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py) | The standards-side source of RES-012, absent from the paper. The url locates the working group's published identity specification (checked 2026-09-03); the dated analysis is a working-group document, and the record of it in this repository is docs/design/task-bound-execution-authority-v1.md. REMORA claims no conformance: the profile's proof-of-possession requirement is explicitly open, as RES-012's scope boundary states. |
| `behrouz-2025-nested` | Nested Learning | RES-008 (narrative attribution) | Source of RES-008 and absent from the paper. Deliberately NOT cited in code: RES-008 carries in_code_citation false because REMORA implements the governance framing, not the architecture, so the attribution lives in docs/09-related-work.md rather than in a module docstring. |
| `galhotra-2021-contrastive` | Contrastive explanations (SIGMOD) | [`remora/causal/search.py`](../../remora/causal/search.py) | builds_on source for RES-001. |
| `rfc-3161-timestamping` | RFC 3161, Time-Stamp Protocol (TSP) | [`remora/audit/hash_chain.py`](../../remora/audit/hash_chain.py), [`remora/audit/merkle.py`](../../remora/audit/merkle.py), [`remora/governance/envelope.py`](../../remora/governance/envelope.py) | Named in the audit modules as an EXTERNAL trust anchor REMORA does not provide: the hash chain detects tampering but cannot prevent it, so a trusted timestamp authority is listed among the deployment-side controls that must be combined with it. Not implemented here. |
| `rfc-8785-jcs` | RFC 8785, JSON Canonicalization Scheme (JCS) | [`remora/interop/jcs.py`](../../remora/interop/jcs.py), [`remora/enforcement/runtime_identity.py`](../../remora/enforcement/runtime_identity.py) | Implemented for wire interoperability only, after the 2026-08-28 REMORA x APS conformance feedback. jcs.py states what it does NOT do: it must not replace the internal canonicalisation behind canonical_tool_call_hash, because rewriting those bytes would make the historical audit record unverifiable. runtime_identity.py cites the same RFC to record that it deliberately does not use it. |
| `wang-2024-moa` | Mixture-of-Agents | [`remora/cascade/stages.py`](../../remora/cascade/stages.py) | Single-stage aggregation inspired by MoA. The paper no longer discusses MoA (the multi-layer architecture is not implemented), so it carries no paper reference. |
| `wu-2026-safety-does-not-compose` | Safety Does Not Compose: Non-Decaying Loop State for Autonomous LLM Agents (arXiv:2608.27141) | [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py) | builds_on source for RES-012, cited where it is load-bearing rather than where it is merely relevant: the non-decaying loop state it proposes needs a key, and that key is the context_id this module defines. LoopHarness itself is NOT implemented, which RES-012's scope boundary states. Identifier checked against the arXiv record on 2026-08-30. |
| `yan-2026-permission-policies` | Do User-Authored Permission Policies Improve Protection Against AI Agent Overreach? (arXiv:2608.27443) | [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py) | Source of RES-012 and absent from the paper. Cited in the module the finding motivates: across 113 participants a reusable-policy setup blocked fewer overreach attempts than either real-time approval or automated review, because users approved actions outside the original task. That is the empirical case for binding an authorization to the task it was granted under. Identifier checked against the arXiv record on 2026-08-30. |

### Discussed in related work only (4)

Works that appear only in [docs/09-related-work.md](../09-related-work.md): no code, no evaluation and no reference in the paper. They were invisible to every check until 2026-09-03, which is what made the reconciliation paper-to-matrix rather than bidirectional. A declared identifier must appear in that document.

| Source id | Identifier | Section | Work | Note |
|-----------|------------|---------|------|------|
| `kaptein-2026-policies-on-paths` | arxiv:2603.16586 | [docs/09-related-work.md](../../docs/09-related-work.md) §4b | Runtime Governance for AI Agents: Policies on Paths (arXiv:2603.16586) | Path-level comparator. REMORA binds authority per call and claims no trajectory-level enforcement. |
| `li-2026-vigil` | arxiv:2606.26524 | [docs/09-related-work.md](../../docs/09-related-work.md) §4b | VIGIL: Runtime Enforcement of Behavioral Specifications in AI Agent Skills (arXiv:2606.26524) | Trace-level comparator. Distinct from the tool-stream injection paper of the same name tracked in research_shelf_v1.yaml. |
| `microsoft-2026-agent-governance-toolkit` | none | [docs/09-related-work.md](../../docs/09-related-work.md) §4b | Agent Governance Toolkit (announced 2026-04-02) | Broader-surface comparator; no identifier recorded because the source is a product announcement, not a paper. |
| `patel-2026-bitter-lesson` | arxiv:2608.06370 | [docs/09-related-work.md](../../docs/09-related-work.md) §4a | The Bitter Lesson of Tool Calling (arXiv:2608.06370) | The PTC source behind the GPTC planning layer (RF-11, SCOPED). It is cited in remora/toolcall/ptc/__init__.py, so it also appears under code_identifiers; it carries no REMORA number, because the ablation that would produce one has not been run. |

### Citation identifiers found in the package (14)

Reverse scan: every `arXiv:` and `RFC` identifier appearing in `remora/**/*.py`, with the files that carry it. The generator fails on an identifier that is in the code but not here, and on one that is here but no longer in the code. Presence is a citation, never an implementation claim - several of these are cited precisely to record what REMORA does **not** do.

| Identifier | Work | Code | Recorded as | Note |
|------------|------|------|-------------|------|
| RFC 3161 | Time-Stamp Protocol | [`remora/audit/hash_chain.py`](../../remora/audit/hash_chain.py), [`remora/audit/merkle.py`](../../remora/audit/merkle.py), [`remora/governance/envelope.py`](../../remora/governance/envelope.py) | `rfc-3161-timestamping` | none |
| RFC 8785 | JSON Canonicalization Scheme | [`remora/interop/jcs.py`](../../remora/interop/jcs.py), [`remora/enforcement/runtime_identity.py`](../../remora/enforcement/runtime_identity.py) | `rfc-8785-jcs` | none |
| arXiv:2110.14168 | Cobbe et al. (2021), Training Verifiers | [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) | `cobbe-2021-training` | none |
| arXiv:2208.02814 | Angelopoulos et al. (2022), Conformal risk control | [`remora/selective/crc.py`](../../remora/selective/crc.py) | `angelopoulos-2022-conformal` | none |
| arXiv:2312.06942 | Greenblatt et al. (2024), AI control | [`remora/governance/control_protocols.py`](../../remora/governance/control_protocols.py) | `greenblatt-2024-control` | none |
| arXiv:2407.13692 | Kirchner et al. (2024), Prover-verifier games | [`remora/selective/pvd.py`](../../remora/selective/pvd.py) | `kirchner-2024-prover` | none |
| arXiv:2504.10374 | Bhatt et al. (2025), control-protocol interventions | [`remora/governance/control_protocols.py`](../../remora/governance/control_protocols.py) | none | Cited beside Greenblatt et al. as the source of the defer-to-trusted / trusted-editing / defer-to-resample strategies the module encodes. Not in the paper and not a matrix line: the module is library-only and flag-gated (RF-04 slice 1). |
| arXiv:2506.02918 | Guo et al. (2025), learned post-action state prediction | [`remora/toolcall/routing/effect_prediction.py`](../../remora/toolcall/routing/effect_prediction.py) | none | Cited as DELIBERATELY NOT implemented: a model-predicted post-state must never be what establishes SUPPORTED, which the module derives from the declared delta only. |
| arXiv:2510.09462 | Suspiciousness-suppression pattern and monitor channel separation | [`remora/governance/control_protocols.py`](../../remora/governance/control_protocols.py) | none | Cited for the adaptive-attack guard and the agent-visible/audit channel split. No author line is recorded in the module, so none is asserted here. |
| arXiv:2605.26047 | Monitor channel separation (second source) | [`remora/governance/control_protocols.py`](../../remora/governance/control_protocols.py) | none | Cited alongside 2510.09462 for channel separation. No author line is recorded in the module, so none is asserted here. |
| arXiv:2608.06370 | Patel et al. (2026), The Bitter Lesson of Tool Calling | [`remora/toolcall/ptc/__init__.py`](../../remora/toolcall/ptc/__init__.py) | `patel-2026-bitter-lesson` | none |
| arXiv:2608.20341 | Nguyen & Nguyen (2026), SDAD | [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py) | none | Source of RES-011; the entry carries it as citation_anchor. |
| arXiv:2608.27141 | Wu et al. (2026), Safety Does Not Compose | [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py) | `wu-2026-safety-does-not-compose` | none |
| arXiv:2608.27443 | Yan (2026), user-authored permission policies | [`remora/governance/task_identity.py`](../../remora/governance/task_identity.py) | `yan-2026-permission-policies` | none |

## Research landscape coverage

Crosswalk to the broader AI-assurance landscape (`docs/researchpapers/kompendium_ai_assurance_3utgave.md`). local-only working document (gitignored, not published; ~201 works, 2. edition figure). compendium_refs are validated against this file when present locally and skipped in CI where it is absent. These are reference pointers, **not** implementation claims; a work appearing here means it informs a line, not that REMORA implements it.

### Compendium work → REMORA research line

| Compendium id | Research line(s) |
|---------------|------------------|
| `agent-safety-bench-2024` | RES-005 |
| `agentdojo-2024` | RES-005 |
| `agentharm-2024` | RES-005 |
| `confidence-seq-2021` | RES-010 |
| `conformal-risk-2022` | RES-003 |
| `eu-ai-act-2024` | RES-009 |
| `game-theoretic-stat-2023` | RES-010 |
| `gentle-conformal-2021` | RES-002 |
| `governing-agents-2023` | RES-009 |
| `infra-agents-2025` | RES-009 |
| `injecagent-2024` | RES-005 |
| `iso-42001-2023` | RES-009 |
| `llm-uq-survey-2023` | RES-004a, RES-004b |
| `ltt-2021` | RES-002, RES-003 |
| `nist-ai-rmf-2023` | RES-009 |
| `rag-2020` | RES-006 |
| `selective-2017` | RES-002 |
| `self-rag-2023` | RES-006 |
| `visibility-agents-2024` | RES-009 |

### Deliberately not implemented (scope boundaries)

Whole areas of the landscape REMORA does not implement as controls, recorded so the boundary is explicit and auditable rather than an unstated gap. These are boundaries, not roadmap promises.

| Area | Compendium chapter | Representative works | Why REMORA does not implement it |
|------|--------------------|----------------------|----------------------------------|
| Formal methods, neural-network verification, guaranteed-safe AI | Ch. 8 (formal methods, verification, guaranteed safety) | `reluplex-2017`, `shielding-2018`, `guaranteed-safe-2024` | REMORA verifies its policy layer by tests and deterministic invariants, not by formal proof. Neural-network verification and proof-carrying guarantees are out of scope; the safety floor is a policy property, not a proved model property. |
| Provenance, workload identity, software supply chain | Ch. 7 (provenance, identity, supply chain) | `slsa-v1`, `in-toto-2019`, `spiffe-spec`, `c2pa-spec` | REMORA provides a tamper-evident DecisionEnvelope hash chain, not SBOM/ML-BOM, artifact signing, or SPIFFE-style workload identity. Supply-chain and identity attestation are assumed to be provided by the host environment. |
| Fairness, differential privacy, training-data protection | Ch. 9 (fairness, privacy, data protection) | `dp-sgd-2016`, `membership-inference-2017`, `gdpr-2016` | REMORA governs execution permission at inference time, not model training. Differential privacy, membership-inference defence, and fairness-metric selection are out of scope; the governed agent's model is treated as given. |
| MLOps, distributed-systems foundations, production drift | Ch. 6 (MLOps, system design, production operations) | `sculley-debt-2015`, `mlops-2022`, `sre-2016` | REMORA is a pre-execution governance overlay, not an MLOps platform. Data pipelines, SRE error budgets, and deployment infrastructure are the host's responsibility; REMORA consumes them rather than providing them. |
| Mechanistic interpretability (model-internal feature analysis) | Ch. 2 (interpretability subset) | `monosemanticity-2023`, `scaling-monosem-2024`, `biology-of-llm-2025` | REMORA's causal explanation (RES-001) is post-hoc over the policy model, not model-internal feature/circuit analysis. Mechanistic interpretability of the governed model is out of scope. |
