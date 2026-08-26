<!-- GENERATED FILE — DO NOT EDIT.
     Source: docs/research/research_control_matrix_v1.yaml
     Regenerate: python scripts/generate_research_control_matrix.py -->

# REMORA Research Control Matrix

The machine-checked chain from research source to tested code, one row per research line. Every code and test path below is verified to exist on disk by CI; the literature narrative lives in [docs/09-related-work.md](../09-related-work.md).

Source of truth: `docs/research/research_control_matrix_v1.yaml` (schema 1, updated 2026-08-24).

## Summary

| ID | Research line | Controls | Maturity |
|----|---------------|----------|----------|
| RES-001 | Causal post-hoc explainability and concept interventions | `causal_policy_explanation` | `implemented_and_tested` |
| RES-002 | Selective prediction and abstention | `phase_aware_guardrail`, `selective_routing` | `implemented_and_tested` |
| RES-003 | CRC-inspired weighted empirical selective routing | `conformal_thresholding` | `empirically_evaluated_adaptation` |
| RES-004 | Multi-oracle consensus and cross-model verification | `multi_oracle_consensus`, `independent_verifier_gate` | `implemented_and_tested` |
| RES-005 | Tool-use safety and agent guardrails | `toolcall_gate`, `action_type_mapping` | `implemented_and_tested` |
| RES-006 | Evidence grounding and retrieval-augmented verification | `evidence_verifier` | `implemented_and_tested` |
| RES-007 | Statistical-physics control signals (entropy, phase, Lyapunov) | `phase_classification`, `thermodynamic_braking` | `implemented_and_tested` |
| RES-008 | Nested learning, context flow, continuum memory | `context_flow_governance`, `governed_memory_layers`, `reviewed_policy_proposals` | `conceptual_translation_implemented` |
| RES-009 | Enterprise AI governance and audit | `enterprise_rollout_reference` | `reference_design` |
| RES-010 | Anytime-valid confidence sequences (optional-stopping-safe monitoring) | `continuous_far_monitoring` | `implemented_and_tested` |
| RES-011 | SDAD-inspired content-bound specification intake | `signed_context_manifest`, `evidence_vector_spec_intake` | `conceptual_translation_implemented` |

## RES-001 — Causal post-hoc explainability and concept interventions

- **Source:** Bjøru, A. R. (2026). Causal Post-hoc Explainable AI (PhD thesis), NTNU. (cited in code; anchor `Bjøru` — CI-verified)
  - Paper IV §3 (concept-based externally-causal XAI)
  - Paper IV §4.2.1 (global explanation by dataset averaging)
  - Paper IV §4.2.2-§4.2.3 (Probability of Sufficiency / Necessity)
  - Paper IV §4.2.4 (minimal contrastive explanation search)
  - builds on: Pearl, J. (2009). Causality (2nd ed.), ch. 9 (PS/PN definitions).
  - builds on: Galhotra, Pradhan & Salimi (2021), SIGMOD (contrastive explanations).
- **Concepts:** concept_based_external_causal_xai, probability_of_sufficiency, probability_of_necessity, minimal_contrastive_intervention, global_concept_attribution
- **REMORA controls:** causal_policy_explanation
- **Code:** [`remora/causal/schema.py`](../../remora/causal/schema.py), [`remora/causal/search.py`](../../remora/causal/search.py), [`remora/causal/attribution.py`](../../remora/causal/attribution.py), [`remora/causal/explanation.py`](../../remora/causal/explanation.py)
- **Tests:** [`tests/test_causal.py`](../../tests/test_causal.py), [`tests/test_causal_search_attribution.py`](../../tests/test_causal_search_attribution.py)
- **Evidence:** PS/PN in {0,1}, minimality, verdict-change, and global mean-PS ordering are unit-tested; result carried on DecisionEnvelope.causal_explanation.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Deterministic policy-level PS/PN operationalisation: binary per-instance indicators evaluated against the policy model, not population-level probabilities and not the world. No real-world causal-effect or safety claim.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §9
- **Landscape (local compendium):** No anchor in the local compendium: its interpretability chapter covers mechanistic interpretability (superposition, monosemanticity, circuit tracing), not causal post-hoc concept XAI. This line's sources (Bjøru 2026; Pearl; Galhotra et al.) sit outside the compendium's scope.

## RES-002 — Selective prediction and abstention

- **Source:** Idea family (no single named source in-repo): selective classification / reject option, risk-coverage curves, calibrated abstention. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** selective_classification, reject_option, risk_coverage_curve, calibrated_abstention
- **REMORA controls:** phase_aware_guardrail, selective_routing
- **Code:** [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py)
- **Tests:** [`tests/test_guardrail.py`](../../tests/test_guardrail.py), [`tests/test_selective_trust_curve.py`](../../tests/test_selective_trust_curve.py), [`tests/test_selective_n500.py`](../../tests/test_selective_n500.py)
- **Evidence:** N302 and N500 selective-acceptance experiments; benchmark-scoped selective-trust results with Wilson CIs.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Benchmark-scoped selective trust; no universal out-of-distribution safety guarantee.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §1
- **Landscape (local compendium):** `selective-2017`, `gentle-conformal-2021`, `ltt-2021`

## RES-003 — CRC-inspired weighted empirical selective routing

- **Source:** Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022). Conformal risk control. arXiv:2208.02814. (cited in code; anchor `Angelopoulos` — CI-verified)
  - Framework the router is inspired by, not implementing: the crc.py module docstring documents the two structural gaps (no finite-sample term in the selector; non-monotone selective loss), so Theorem 1 does not attach.
- **Concepts:** weighted_empirical_threshold_selection, repeated_split_robustness
- **REMORA controls:** conformal_thresholding
- **Code:** [`remora/selective/crc.py`](../../remora/selective/crc.py), [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py)
- **Tests:** [`tests/test_crc.py`](../../tests/test_crc.py), [`tests/test_conformal_repeated_splits.py`](../../tests/test_conformal_repeated_splits.py), [`tests/test_binomial_bounds.py`](../../tests/test_binomial_bounds.py)
- **Evidence:** Repeated-split holdout results in committed artifacts; all quality evidence for this component is empirical, and negative results are preserved in the claim ledger.
- **Maturity:** `empirically_evaluated_adaptation`
- **Scope boundary:** CRC-inspired, NOT a CRC procedure (external review R3-01): deterministic importance-weighted empirical threshold selector with hand-tuned phase weights, no finite-sample correction and a non-monotone selective loss - no distribution-free guarantee is claimed.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §2
- **Landscape (local compendium):** `conformal-risk-2022`, `ltt-2021`

## RES-004 — Multi-oracle consensus and cross-model verification

- **Source:** Wang et al. (2023), Self-Consistency Improves Chain-of-Thought Reasoning; Wang et al. (2024), Mixture-of-Agents; Zheng et al. (2023), Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena; Cobbe et al. (2021), Training Verifiers to Solve Math Word Problems. (cited in code; anchor `Wang et al.` — CI-verified)
  - cited at remora/cascade/stages.py (self-consistency; single-stage aggregation inspired by MoA, not the multi-layer architecture)
  - cited at remora/verifier/llm_judge.py (LLM-as-judge verifier per Zheng et al. 2023; contrast with Cobbe et al. 2021 trained outcome verifiers)
- **Concepts:** self_consistency_sampling, verifier_model, cross_model_dissensus, multi_agent_debate
- **REMORA controls:** multi_oracle_consensus, independent_verifier_gate
- **Code:** [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py)
- **Tests:** [`tests/test_moa_synthesizer.py`](../../tests/test_moa_synthesizer.py), [`tests/test_llm_judge.py`](../../tests/test_llm_judge.py), [`tests/test_oracle_diversity.py`](../../tests/test_oracle_diversity.py)
- **Evidence:** Majority, self-consistency, verifier, and REMORA tool-call baselines; consensus combined with evidence, policy, risk, and audit.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Consensus is not treated as truth; it is one input among evidence, policy, risk, and audit.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §3
- **Landscape (local compendium):** `llm-uq-survey-2023` — Weak landscape anchor: the compendium treats cross-model consistency/verification only via the confidence-and-calibration survey (llm-uq-survey-2023); the specific self-consistency and mixture-of-agents sources this line cites are not catalogued there.

## RES-005 — Tool-use safety and agent guardrails

- **Source:** Idea family (no single named source in-repo): tool-invocation safety, dry-run/sandboxed evaluation, critical-action routing, prompt-injection benchmarks. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** tool_invocation_safety, dry_run_sandbox, critical_action_routing
- **REMORA controls:** toolcall_gate, action_type_mapping
- **Code:** [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py)
- **Tests:** [`tests/test_remora_toolcall_gate.py`](../../tests/test_remora_toolcall_gate.py), [`tests/test_remora_toolcall_gate_v2.py`](../../tests/test_remora_toolcall_gate_v2.py), [`tests/test_toolcall_scoring.py`](../../tests/test_toolcall_scoring.py)
- **Evidence:** Deterministic tool-call benchmark v1 (ceiling effect, documented), adversarial v2 (effective N=70, cluster-level CIs).
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** v2 provides deterministic adversarial evidence, not production proof; live validation is a separate requirement.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §4
- **Landscape (local compendium):** `agentharm-2024`, `agentdojo-2024`, `injecagent-2024`, `agent-safety-bench-2024`

## RES-006 — Evidence grounding and retrieval-augmented verification

- **Source:** Idea family (no single named source in-repo): RAG evidence lookup, source reliability, per-claim support/contradiction, NLI-style verification. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** retrieval_augmented_verification, per_claim_support_contradiction, nli_style_entailment
- **REMORA controls:** evidence_verifier
- **Code:** [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py), [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py)
- **Tests:** [`tests/test_evidence_v3.py`](../../tests/test_evidence_v3.py), [`tests/test_evidence_verifier.py`](../../tests/test_evidence_verifier.py)
- **Evidence:** Lexical default verifier with a pluggable NLI-style interface; falls back to lexical when no NLI backend is configured.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Default verifier is lexical plus simple contradiction signals; semantic-entailment quality is not demonstrated by committed artifacts.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §5
- **Landscape (local compendium):** `rag-2020`, `self-rag-2023`

## RES-007 — Statistical-physics control signals (entropy, phase, Lyapunov)

- **Source:** Generic statistical-physics constructs (q-state Potts model, Gibbs/Boltzmann distribution, Lyapunov objective) used as operational analogy. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** entropy_order_parameter, phase_regime_classification, lyapunov_stability
- **REMORA controls:** phase_classification, thermodynamic_braking
- **Code:** [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py), [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py)
- **Tests:** [`tests/test_statphys.py`](../../tests/test_statphys.py), [`tests/test_thermodynamics.py`](../../tests/test_thermodynamics.py), [`tests/test_thermodynamic_braking.py`](../../tests/test_thermodynamic_braking.py)
- **Evidence:** Regime classification (ordered/critical/disordered) and selective-trust routing exist as tested library code. NOT evidence of runtime effect: verified 2026-08-07 that no governed path populates these signals — servers/api.py never references the consensus state, servers/execution_api.py passes trust_score=None and phase=None, and build_full_observation leaves the fields at their None defaults, so the critical_phase_critical_risk rule cannot fire in production.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Library-grade only, and the framing is withdrawn from the paper (2026-08-07). The physics vocabulary (structural temperature, free energy, Lyapunov observable) invited a physical reading the system does not support, and the temperature signal it rested on FAILED its pre-registered fresh-data confirmation (CLAIM-012, NEGATIVE_RESULTS §18): temperature ranked worse than calibrated confidence. The paper now presents only the information-theoretic observables (H, D, trust score); the withdrawn material lives in the negative results. These signals are not populated on any governed path and influence no runtime decision.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §6
- **Landscape (local compendium):** No anchor in the local compendium: the statistical-physics control signals (q-state Potts, Gibbs/Boltzmann, Lyapunov) are used as an operational analogy specific to REMORA and are not a catalogued research area in the assurance landscape.

## RES-008 — Nested learning, context flow, continuum memory

- **Source:** Behrouz, Razaviyayn, Zhong & Mirrokni, Nested Learning: The Illusion of Deep Learning Architecture (https://abehrouz.github.io/files/NL.pdf); Google Research blog, 2025-11-07. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** nested_learning, context_flow, continuum_memory, governed_self_modification
- **REMORA controls:** context_flow_governance, governed_memory_layers, reviewed_policy_proposals
- **Code:** [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py)
- **Tests:** [`tests/test_governance_context_flow.py`](../../tests/test_governance_context_flow.py), [`tests/test_governance_memory_layers.py`](../../tests/test_governance_memory_layers.py), [`tests/test_nested_governance.py`](../../tests/test_nested_governance.py)
- **Evidence:** Context flow as a governed information stream; update frequency as a policy boundary; self-modification as reviewed policy proposals.
- **Maturity:** `conceptual_translation_implemented`
- **Scope boundary:** A governance translation of the Nested Learning ideas, not the architecture: does not implement Hope or nested optimisation problems, does not train foundation models, does not claim to solve catastrophic forgetting.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §7
- **Landscape (local compendium):** No anchor in the local compendium: the Nested Learning source (Behrouz et al., 2025) is newer than / outside the compendium's catalogue. REMORA implements only the governance framing (context-flow, reviewed memory layers), not the architecture itself.

## RES-009 — Enterprise AI governance and audit

- **Source:** Idea family (no single named source in-repo): policy-as-code, role/authority boundaries, human-approval workflows, audit ledgers, fail-closed deployment. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** policy_as_code, human_approval_workflow, audit_ledger, fail_closed_deployment
- **REMORA controls:** enterprise_rollout_reference
- **Code:** [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md), [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py)
- **Tests:** —
- **Evidence:** TOGAF-structured rollout plan and a runnable enterprise demo; the governance primitives themselves are tested under RES-001..008 and the capability register.
- **Maturity:** `reference_design`
- **Scope boundary:** Reference/design grade: not a production-certified enterprise product; must be validated in the target organization before enforcement.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §8
- **Landscape (local compendium):** `nist-ai-rmf-2023`, `iso-42001-2023`, `eu-ai-act-2024`, `governing-agents-2023`, `visibility-agents-2024`, `infra-agents-2025`

## RES-010 — Anytime-valid confidence sequences (optional-stopping-safe monitoring)

- **Source:** Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). Time-uniform, nonparametric, nonasymptotic confidence sequences. (cited in code; anchor `Howard` — CI-verified)
  - Conjugate-mixture (Beta-binomial) supermartingale; Ville's inequality (cited in remora/selective/confidence_sequence.py)
  - builds on: Ramdas, Grünwald, Vovk & Shafer (2023). Game-theoretic statistics and safe anytime-valid inference. Statistical Science 38(4).
  - builds on: Waudby-Smith & Ramdas (2024). Estimating means of bounded random variables.
- **Concepts:** time_uniform_confidence_sequence, anytime_valid_inference, optional_stopping_safety
- **REMORA controls:** continuous_far_monitoring
- **Code:** [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py)
- **Tests:** [`tests/test_confidence_sequence.py`](../../tests/test_confidence_sequence.py)
- **Evidence:** Used by REM-020 to monitor the operational false-accept rate continuously without inflating the coverage guarantee under optional stopping (peeking); supplementary anytime-valid FAR bound in results/far_confidence_sequence_v1.json (CLAIM-011).
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** A time-uniform Bernoulli-rate bound, distinct from the CRC-inspired empirical selective routing of RES-003; conservative by construction and valid only under the stated Beta-binomial mixture assumptions.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §2
- **Landscape (local compendium):** `confidence-seq-2021`, `game-theoretic-stat-2023`

## RES-011 — SDAD-inspired content-bound specification intake

- **Source:** Nguyen, V. H. & Nguyen, T. (2026). SDAD: Spec-Driven Agentic Development for the AI-Native SDLC. arXiv:2608.20341v1. (cited in code; anchor `2608.20341` — CI-verified)
  - §6.1 (Context Ingestion as Execution)
  - §7.2 (completeness, consistency, unambiguity, verifiability)
  - §13.4 (operational definitions and longitudinal baselines remain open)
- **Concepts:** context_ingestion_as_execution, four_dimension_spec_fidelity, requirement_to_verification_traceability, content_addressed_context_provenance
- **REMORA controls:** signed_context_manifest, evidence_vector_spec_intake
- **Code:** [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py), [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml), [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json)
- **Tests:** [`tests/test_spec_intake.py`](../../tests/test_spec_intake.py)
- **Evidence:** Unit tests pin signature/digest refusal, source-order determinism, dimension separation, equal provenance for negative findings, traceability, unresolved handling, and exact reproduction of the committed reference artifact.
- **Maturity:** `conceptual_translation_implemented`
- **Scope boundary:** Structural and provenance checks only: no scalar Spec Fidelity score, no semantic-correctness or source-truth claim, no empirical SDAD validation, and no execution-API/dispatch binding until RMR-004. Agentic Autonomy Rate is not adopted as assurance evidence.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §10
- **Landscape (local compendium):** No anchor in the local compendium: SDAD v1 (August 2026) postdates the catalogue. REMORA adopts only the context/provenance and four-dimension intake decomposition, not the full SDLC framework or its proposed scalar metrics.

## Reverse index: code → research

| Code file | Research line(s) |
|-----------|------------------|
| [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json) | RES-011 |
| [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md) | RES-009 |
| [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py) | RES-009 |
| [`remora/cascade/stages.py`](../../remora/cascade/stages.py) | RES-004 |
| [`remora/causal/attribution.py`](../../remora/causal/attribution.py) | RES-001 |
| [`remora/causal/explanation.py`](../../remora/causal/explanation.py) | RES-001 |
| [`remora/causal/schema.py`](../../remora/causal/schema.py) | RES-001 |
| [`remora/causal/search.py`](../../remora/causal/search.py) | RES-001 |
| [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py) | RES-008 |
| [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py) | RES-008 |
| [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) | RES-008 |
| [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py) | RES-011 |
| [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py) | RES-004 |
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
| [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) | RES-004 |
| [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml) | RES-011 |

## Reverse index: control → research → code

| Control | Research line(s) | Code |
|---------|------------------|------|
| `action_type_mapping` | RES-005 | [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) |
| `causal_policy_explanation` | RES-001 | [`remora/causal/attribution.py`](../../remora/causal/attribution.py), [`remora/causal/explanation.py`](../../remora/causal/explanation.py), [`remora/causal/schema.py`](../../remora/causal/schema.py), [`remora/causal/search.py`](../../remora/causal/search.py) |
| `conformal_thresholding` | RES-003 | [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py), [`remora/selective/crc.py`](../../remora/selective/crc.py) |
| `context_flow_governance` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `continuous_far_monitoring` | RES-010 | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) |
| `enterprise_rollout_reference` | RES-009 | [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md), [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py) |
| `evidence_vector_spec_intake` | RES-011 | [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json), [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py), [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml) |
| `evidence_verifier` | RES-006 | [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py), [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py) |
| `governed_memory_layers` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `independent_verifier_gate` | RES-004 | [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py), [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) |
| `multi_oracle_consensus` | RES-004 | [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py), [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) |
| `phase_aware_guardrail` | RES-002 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) |
| `phase_classification` | RES-007 | [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py), [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py) |
| `reviewed_policy_proposals` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `selective_routing` | RES-002 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) |
| `signed_context_manifest` | RES-011 | [`artifacts/spec_intake/sdad_spec_fidelity_v1.json`](../../artifacts/spec_intake/sdad_spec_fidelity_v1.json), [`remora/governance/spec_intake.py`](../../remora/governance/spec_intake.py), [`schemas/spec_intake_v1.yaml`](../../schemas/spec_intake_v1.yaml) |
| `thermodynamic_braking` | RES-007 | [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py), [`remora/research_attic/statphys/potts.py`](../../remora/research_attic/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py) |
| `toolcall_gate` | RES-005 | [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) |

## Reverse index: claim → research

Claims named in a research line's evidence. Not every line cites a claim id in prose; absence here does not mean absence of evidence (see each line's **Evidence** field above).

| Claim | Research line(s) |
|-------|------------------|
| CLAIM-011 | RES-010 |

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
| `angelopoulos-2022-conformal` | arxiv:2208.02814 | RES-003 | — | — |
| `bjru-2026-causal` | isbn:978-82-353-0022-5 | RES-001 | — | — |
| `cobbe-2021-training` | arxiv:2110.14168 | RES-004 | — | — |
| `howard-2021-time` | — | RES-010 | — | — |
| `pearl-2009-causality` | — | RES-001 | — | — |
| `ramdas-2023-game` | — | RES-010 | — | — |
| `wang-2023a-self` | — | RES-004 | — | — |
| `zheng-2023-judging` | — | RES-004 | — | — |

### Grounds a module (no dedicated line) (11)

Cited in a code docstring as the basis for a module, but not large enough to be its own research line. CI verifies the surname appears in the named file.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `darling-1967-confidence` | — | — | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | — |
| `el-yaniv-2010-foundations` | — | — | [`remora/selective/risk_control.py`](../../remora/selective/risk_control.py) | Selective-classification foundations behind the RES-002 idea family. |
| `farquhar-2024-detecting` | — | — | [`remora/semantic_entropy.py`](../../remora/semantic_entropy.py) | The Nature follow-up to Kuhn et al.; same clustering construct. |
| `geifman-2017-selective` | — | — | [`remora/selective/risk_control.py`](../../remora/selective/risk_control.py) | SGR Algorithm 1 is implemented directly (binary search over cut points). |
| `greenblatt-2024-control` | — | — | [`remora/governance/control_protocols.py`](../../remora/governance/control_protocols.py) | AI-control taxonomy used to classify REMORA as a trusted-monitoring protocol. Classification only: the subversive-agent threat model is explicitly NOT covered. |
| `kirchner-2024-prover` | arxiv:2407.13692 | — | [`remora/selective/pvd.py`](../../remora/selective/pvd.py) | PVD framing only. REMORA does not run the training game; the module derives an offline agreement score from already-produced responses. This file carried a fabricated author list until 2026-08-07 while the paper had long been remediated, which is why tests/test_paper_no_stale_claims.py now also scans cited modules. |
| `kuhn-2023-semantic` | arxiv:2302.09664 | — | [`remora/semantic_entropy.py`](../../remora/semantic_entropy.py) | Semantic Entropy is a core observable with no RES line of its own: it is an input to RES-002/RES-004 rather than a separate control. |
| `shafer-2008-tutorial` | — | — | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | — |
| `tibshirani-2019-conformal` | — | — | [`remora/selective/crc.py`](../../remora/selective/crc.py) | Weighted conformal under covariate shift; source of the importance weights. |
| `ville-1939-etude` | — | — | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | Ville's inequality is the martingale bound the sequence rests on. |
| `vovk-2005-algorithmic` | — | — | [`remora/selective/conformal.py`](../../remora/selective/conformal.py) | — |

### Evaluation source (4)

A dataset or benchmark REMORA is evaluated **on**. Not a method REMORA implements.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `andriushchenko-2024-agentharm` | arxiv:2410.09024 | — | [`scripts/run_agentharm_benchmark.py`](../../scripts/run_agentharm_benchmark.py) | AgentHarm external validation (CLAIM-002). Imported historical artifact: it cannot be regenerated from this repository. |
| `clark-2019-boolq` | — | — | [`remora/benchmarks/extended_v2.py`](../../remora/benchmarks/extended_v2.py) | BoolQ items in the QA benchmark composition. |
| `lin-2022-truthfulqa` | — | — | [`remora/benchmarks/extended_v2.py`](../../remora/benchmarks/extended_v2.py) | TruthfulQA items in the QA benchmark composition. |
| `williams-2018-broad` | — | — | [`experiments/rag_critical_router_v1.py`](../../experiments/rag_critical_router_v1.py) | MultiNLI as the evidence-router proxy benchmark. |

### Standard, regulation or tool (4)

Aligned with or integrated, not a research result. Alignment is a mapping claim, never a conformity claim.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `european-2024-regulation` | — | — | [`remora/evidence/domains/ai_governance.py`](../../remora/evidence/domains/ai_governance.py) | EU AI Act Art. 12/14 mapped at runtime; no conformity assessment claimed. |
| `international-2016-iec` | — | — | — | IEC 61511 SIL framing in the case study. |
| `open-2024-open` | — | — | [`remora/policy/opa_adapter.py`](../../remora/policy/opa_adapter.py) | OPA/Rego adapter, failing closed to the Python engine. |
| `standards-2021-norsok` | — | — | — | NORSOK D-010 well-barrier framing in the case study. |

### Related-work positioning only (40)

Compared against or used as framing in the paper. No code, no evaluation — and that is the honest status, not an oversight.

| Source id | Identifier | Line | Code | Note |
|-----------|------------|------|------|------|
| `angelopoulos-2021-gentle` | arxiv:2107.07511 | — | — | Conformal tutorial; framing only. |
| `bloomfield-2010-safety` | — | — | — | — |
| `chennabasappa-2025-llamafirewall` | arxiv:2505.03574 | — | — | LlamaFirewall - closest industrial system in scope. |
| `choi-2026-membrane` | arxiv:2606.05743 | — | — | Membrane; contrasted with AROMER's never-weaken constraint. |
| `chow-1970-optimum` | — | — | — | Origin of the error-reject tradeoff. |
| `corsi-2021-formal` | — | — | — | — |
| `debenedetti-2024-agentdojo` | — | — | — | AgentDojo - named as a required replication target, not run. |
| `debenedetti-2025-defeating` | arxiv:2503.18813 | — | — | CaMeL; shelf SHELF-008. |
| `dong-2025-evaluating` | arxiv:2502.11347 | — | — | TEE attestation sketch; hardware integration pending. |
| `du-2024-improving` | — | — | — | Multi-agent debate; REMORA's dissensus is a one-shot analogue. |
| `endsley-1995-toward` | — | — | — | Situation awareness; supervision framing only. |
| `ge-2026-governance` | arxiv:2603.07191 | — | — | — |
| `guldimann-2024-compl` | arxiv:2410.07959 | — | — | COMPL-AI. |
| `guo-2017-calibration` | — | — | — | Calibration; REMORA deliberately does not calibrate per-oracle. |
| `inan-2023-llama` | arxiv:2312.06674 | — | — | Llama Guard - content guardrail, contrasted with action gating. |
| `kadavath-2022-language` | arxiv:2207.05221 | — | — | Self-knowledge; motivates structural over self-reported uncertainty. |
| `kelly-1998-arguing` | — | — | — | Assurance cases; DecisionEnvelope populates one node. |
| `kuncheva-2003-measures` | — | — | — | Ensemble diversity measures. |
| `lakshminarayanan-2017-simple` | — | — | — | Deep ensembles. |
| `michael-2026-permission` | arxiv:2607.13718 | — | — | Agent-permissions survey; names the open low-burden/formal/deterministic triad REMORA is positioned against. Survey size verified against the arXiv abstract 2026-08-26: '21 proposals for agent permissions systems' - the paper's count. |
| `mohri-2024-language` | — | — | — | Conformal factuality; pre-empts the general LLM-abstention move. |
| `mu-2024-rule` | — | — | — | Rule-based rewards - safety rules in training, not enforcement. |
| `qin-2026-airguard` | arxiv:2605.28914 | — | — | AIRGuard - authority confusion and action-time authorization; explicit non-claim: predates/parallels REMORA on pre-action checks. |
| `raji-2022-outsider` | arxiv:2206.04737 | — | — | Audit-ecosystem design; motivates the replay/transparency framing. |
| `rebedea-2023-nemo` | — | — | — | NeMo Guardrails. |
| `rhodes-2026-poe` | arxiv:2607.05397 | — | — | Proof of Execution - certificate-first execution evidence; REMORA differs by growing evidence out of a deployed enforcement path. |
| `ruan-2024-identifying` | — | — | — | ToolEmu anticipates the Shadow Mode counterfactual idea. |
| `shamsujjoha-2024-taxonomy` | arxiv:2408.02205 | — | — | Swiss-cheese guardrail taxonomy. |
| `sharma-2025-constitutional` | arxiv:2501.18837 | — | — | Constitutional classifiers. |
| `shi-2025-progent` | arxiv:2504.11703 | — | — | Progent; shelf SHELF-009. Defines the (safety, friction) frontier. |
| `wang-2023b-lora` | arxiv:2310.00035 | — | — | LoRA ensembles; motivates but does not validate heterogeneous aggregation. |
| `wang-2025-agentspec` | arxiv:2503.18666 | — | — | AgentSpec - DSL near-isomorphic to REMORA's policy invariants. |
| `wang-2026-pcaa` | arxiv:2606.04104 | — | — | Proof-Carrying Agent Actions - runtime-portable action certificate; REMORA trades portability for exact-call binding to one kernel. |
| `xiang-2025-guardagent` | — | — | — | GuardAgent. |
| `yadkori-2024-mitigating` | arxiv:2405.01563 | — | — | Conformal abstention for hallucination mitigation. |
| `yang-2026-agenttrust` | arxiv:2606.08539 | — | — | AgentTrust; opposite corner of the safety/friction trade-off. |
| `yao-2024-bench` | arxiv:2406.12045 | — | — | tau-bench. |
| `yuan-2024-judge` | — | — | — | R-Judge. |
| `zhan-2024-injecagent` | — | — | — | InjecAgent. |
| `zhang-2024-calibrating` | arxiv:2404.02655 | — | — | Confidence elicitation by fidelity. |

### Cited in code but not in the paper (3)

The reconciliation runs both ways. These sources ground code or a research line while the paper carries no reference to them — recorded so the asymmetry is visible instead of hidden.

| Source id | Work | Code | Note |
|-----------|------|------|------|
| `behrouz-2025-nested` | Nested Learning | RES-008 (narrative attribution) | Source of RES-008 and absent from the paper. Deliberately NOT cited in code: RES-008 carries in_code_citation false because REMORA implements the governance framing, not the architecture, so the attribution lives in docs/09-related-work.md rather than in a module docstring. |
| `galhotra-2021-contrastive` | Contrastive explanations (SIGMOD) | [`remora/causal/search.py`](../../remora/causal/search.py) | builds_on source for RES-001. |
| `wang-2024-moa` | Mixture-of-Agents | [`remora/cascade/stages.py`](../../remora/cascade/stages.py) | Single-stage aggregation inspired by MoA. The paper no longer discusses MoA (the multi-layer architecture is not implemented), so it carries no paper reference. |

## Research landscape coverage

Crosswalk to the broader AI-assurance landscape (`docs/researchpapers/kompendium_ai_assurance_3utgave.md`). local-only working document (gitignored, not published; ~201 works, 2. edition figure). compendium_refs are validated against this file when present locally and skipped in CI where it is absent. These are reference pointers, **not** implementation claims — a work appearing here means it informs a line, not that REMORA implements it.

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
| `llm-uq-survey-2023` | RES-004 |
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
