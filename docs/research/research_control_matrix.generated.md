<!-- GENERATED FILE — DO NOT EDIT.
     Source: docs/research/research_control_matrix_v1.yaml
     Regenerate: python scripts/generate_research_control_matrix.py -->

# REMORA Research Control Matrix

The machine-checked chain from research source to tested code, one row per research line. Every code and test path below is verified to exist on disk by CI; the literature narrative lives in [docs/09-related-work.md](../09-related-work.md).

Source of truth: `docs/research/research_control_matrix_v1.yaml` (schema 1, updated 2026-07-21).

## Summary

| ID | Research line | Controls | Maturity |
|----|---------------|----------|----------|
| RES-001 | Causal post-hoc explainability and concept interventions | `causal_policy_explanation` | `implemented_and_tested` |
| RES-002 | Selective prediction and abstention | `phase_aware_guardrail`, `selective_routing` | `implemented_and_tested` |
| RES-003 | Conformal risk control | `conformal_thresholding` | `implemented_and_tested` |
| RES-004 | Multi-oracle consensus and cross-model verification | `multi_oracle_consensus`, `independent_verifier_gate` | `implemented_and_tested` |
| RES-005 | Tool-use safety and agent guardrails | `toolcall_gate`, `action_type_mapping` | `implemented_and_tested` |
| RES-006 | Evidence grounding and retrieval-augmented verification | `evidence_verifier` | `implemented_and_tested` |
| RES-007 | Statistical-physics control signals (entropy, phase, Lyapunov) | `phase_classification`, `thermodynamic_braking` | `implemented_and_tested` |
| RES-008 | Nested learning, context flow, continuum memory | `context_flow_governance`, `governed_memory_layers`, `reviewed_policy_proposals` | `implemented_and_tested` |
| RES-009 | Enterprise AI governance and audit | `enterprise_rollout_reference` | `reference_design` |
| RES-010 | Anytime-valid confidence sequences (optional-stopping-safe monitoring) | `continuous_far_monitoring` | `implemented_and_tested` |

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
- **Scope boundary:** Policy causality only: counterfactuals evaluated against the policy model, not the world. No real-world causal-effect or safety claim.
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

## RES-003 — Conformal risk control

- **Source:** Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022). Conformal risk control. arXiv:2208.02814. (cited in code; anchor `Angelopoulos` — CI-verified)
  - Theorem 1 (referenced in remora/selective/crc.py)
- **Concepts:** split_conformal_calibration, finite_sample_risk_control, repeated_split_robustness
- **REMORA controls:** conformal_thresholding
- **Code:** [`remora/selective/crc.py`](../../remora/selective/crc.py), [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py)
- **Tests:** [`tests/test_crc.py`](../../tests/test_crc.py), [`tests/test_conformal_repeated_splits.py`](../../tests/test_conformal_repeated_splits.py), [`tests/test_binomial_bounds.py`](../../tests/test_binomial_bounds.py)
- **Evidence:** Repeated-split robustness artifacts and negative results preserved in the claim ledger; treated as exchangeability-dependent.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Guarantees hold under exchangeability; repeated-split failures are recorded as negative evidence, not hidden.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §2
- **Landscape (local compendium):** `conformal-risk-2022`, `ltt-2021`

## RES-004 — Multi-oracle consensus and cross-model verification

- **Source:** Wang et al. (2023), Self-Consistency Improves Chain-of-Thought Reasoning; Wang et al. (2024), Mixture-of-Agents. (cited in code; anchor `Wang et al.` — CI-verified)
  - cited at remora/cascade/stages.py (self-consistency, mixture-of-agents synthesizer)
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
- **Code:** [`remora/statphys/potts.py`](../../remora/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py), [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py)
- **Tests:** [`tests/test_statphys.py`](../../tests/test_statphys.py), [`tests/test_thermodynamics.py`](../../tests/test_thermodynamics.py), [`tests/test_thermodynamic_braking.py`](../../tests/test_thermodynamic_braking.py)
- **Evidence:** Phase classification (ordered/critical/disordered) and selective-trust routing; explicit caveats (e.g. 'real oracles are not Potts spins').
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Physics language is an operational analogy and feature family; some theoretical claims remain not-demonstrated or explicitly negative in the claim ledger.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §6
- **Landscape (local compendium):** No anchor in the local compendium: the statistical-physics control signals (q-state Potts, Gibbs/Boltzmann, Lyapunov) are used as an operational analogy specific to REMORA and are not a catalogued research area in the assurance landscape.

## RES-008 — Nested learning, context flow, continuum memory

- **Source:** Behrouz, Razaviyayn, Zhong & Mirrokni, Nested Learning: The Illusion of Deep Learning Architecture (https://abehrouz.github.io/files/NL.pdf); Google Research blog, 2025-11-07. (idea family / generic construct; attributed via docs/09-related-work.md, not cited in code)
- **Concepts:** nested_learning, context_flow, continuum_memory, governed_self_modification
- **REMORA controls:** context_flow_governance, governed_memory_layers, reviewed_policy_proposals
- **Code:** [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py)
- **Tests:** [`tests/test_governance_context_flow.py`](../../tests/test_governance_context_flow.py), [`tests/test_governance_memory_layers.py`](../../tests/test_governance_memory_layers.py), [`tests/test_nested_governance.py`](../../tests/test_nested_governance.py)
- **Evidence:** Context flow as a governed information stream; update frequency as a policy boundary; self-modification as reviewed policy proposals.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Does not implement the Hope architecture, does not train foundation models, does not claim to solve catastrophic forgetting.
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
- **Scope boundary:** A time-uniform Bernoulli-rate bound, distinct from the split-conformal risk control of RES-003; conservative by construction and valid only under the stated Beta-binomial mixture assumptions.
- **Literature:** [docs/09-related-work.md](../../docs/09-related-work.md) §2
- **Landscape (local compendium):** `confidence-seq-2021`, `game-theoretic-stat-2023`

## Reverse index: code → research

| Code file | Research line(s) |
|-----------|------------------|
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
| [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py) | RES-004 |
| [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py) | RES-006 |
| [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py) | RES-006 |
| [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py) | RES-007 |
| [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py) | RES-003 |
| [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | RES-010 |
| [`remora/selective/conformal.py`](../../remora/selective/conformal.py) | RES-002 |
| [`remora/selective/crc.py`](../../remora/selective/crc.py) | RES-003 |
| [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py) | RES-002 |
| [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) | RES-002 |
| [`remora/statphys/potts.py`](../../remora/statphys/potts.py) | RES-007 |
| [`remora/thermodynamics.py`](../../remora/thermodynamics.py) | RES-007 |
| [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py) | RES-005 |
| [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py) | RES-005 |
| [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) | RES-005 |
| [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) | RES-004 |

## Reverse index: control → research → code

| Control | Research line(s) | Code |
|---------|------------------|------|
| `action_type_mapping` | RES-005 | [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) |
| `causal_policy_explanation` | RES-001 | [`remora/causal/attribution.py`](../../remora/causal/attribution.py), [`remora/causal/explanation.py`](../../remora/causal/explanation.py), [`remora/causal/schema.py`](../../remora/causal/schema.py), [`remora/causal/search.py`](../../remora/causal/search.py) |
| `conformal_thresholding` | RES-003 | [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py), [`remora/selective/crc.py`](../../remora/selective/crc.py) |
| `context_flow_governance` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `continuous_far_monitoring` | RES-010 | [`remora/selective/confidence_sequence.py`](../../remora/selective/confidence_sequence.py) |
| `enterprise_rollout_reference` | RES-009 | [`docs/enterprise/togaf-enterprise-rollout-plan.md`](../../docs/enterprise/togaf-enterprise-rollout-plan.md), [`examples/enterprise_demo.py`](../../examples/enterprise_demo.py) |
| `evidence_verifier` | RES-006 | [`remora/oracles/evidence_v3.py`](../../remora/oracles/evidence_v3.py), [`remora/oracles/evidence_verifier.py`](../../remora/oracles/evidence_verifier.py) |
| `governed_memory_layers` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `independent_verifier_gate` | RES-004 | [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py), [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) |
| `multi_oracle_consensus` | RES-004 | [`remora/cascade/stages.py`](../../remora/cascade/stages.py), [`remora/oracles/diversity.py`](../../remora/oracles/diversity.py), [`remora/verifier/llm_judge.py`](../../remora/verifier/llm_judge.py) |
| `phase_aware_guardrail` | RES-002 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) |
| `phase_classification` | RES-007 | [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py), [`remora/statphys/potts.py`](../../remora/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py) |
| `reviewed_policy_proposals` | RES-008 | [`remora/governance/context_flow.py`](../../remora/governance/context_flow.py), [`remora/governance/memory_layers.py`](../../remora/governance/memory_layers.py), [`remora/governance/nested_governance.py`](../../remora/governance/nested_governance.py) |
| `selective_routing` | RES-002 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`remora/selective/guardrail.py`](../../remora/selective/guardrail.py), [`remora/selective/risk_coverage.py`](../../remora/selective/risk_coverage.py) |
| `thermodynamic_braking` | RES-007 | [`remora/policy/thermodynamic_braking.py`](../../remora/policy/thermodynamic_braking.py), [`remora/statphys/potts.py`](../../remora/statphys/potts.py), [`remora/thermodynamics.py`](../../remora/thermodynamics.py) |
| `toolcall_gate` | RES-005 | [`remora/toolcall/remora_gate.py`](../../remora/toolcall/remora_gate.py), [`remora/toolcall/schema.py`](../../remora/toolcall/schema.py), [`remora/toolcall/scoring.py`](../../remora/toolcall/scoring.py) |

## Reverse index: claim → research

Claims named in a research line's evidence. Not every line cites a claim id in prose; absence here does not mean absence of evidence (see each line's **Evidence** field above).

| Claim | Research line(s) |
|-------|------------------|
| CLAIM-011 | RES-010 |

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
