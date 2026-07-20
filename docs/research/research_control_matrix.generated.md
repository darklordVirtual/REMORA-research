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

## RES-001 — Causal post-hoc explainability and concept interventions

- **Source:** Bjøru, A. R. (2026). Causal Post-hoc Explainable AI (PhD thesis), NTNU.
  - Paper IV §3 (concept-based externally-causal XAI)
  - Paper IV §4.2.1 (global explanation by dataset averaging)
  - Paper IV §4.2.2-§4.2.3 (Probability of Sufficiency / Necessity)
  - Paper IV §4.2.4 (minimal contrastive explanation search)
  - builds on: Pearl, J. (2009). Causality (2nd ed.), ch. 9 (PS/PN definitions).
  - builds on: Galhotra, Pradhan & Salimi (2021), SIGMOD (contrastive explanations).
- **Concepts:** concept_based_external_causal_xai, probability_of_sufficiency, probability_of_necessity, minimal_contrastive_intervention, global_concept_attribution
- **REMORA controls:** causal_policy_explanation
- **Code:** `remora/causal/schema.py`, `remora/causal/search.py`, `remora/causal/attribution.py`, `remora/causal/explanation.py`
- **Tests:** `tests/test_causal.py`, `tests/test_causal_search_attribution.py`
- **Evidence:** PS/PN in {0,1}, minimality, verdict-change, and global mean-PS ordering are unit-tested; result carried on DecisionEnvelope.causal_explanation.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Policy causality only: counterfactuals evaluated against the policy model, not the world. No real-world causal-effect or safety claim.
- **Literature:** docs/09-related-work.md §9

## RES-002 — Selective prediction and abstention

- **Source:** Idea family (no single named source in-repo): selective classification / reject option, risk-coverage curves, calibrated abstention.
- **Concepts:** selective_classification, reject_option, risk_coverage_curve, calibrated_abstention
- **REMORA controls:** phase_aware_guardrail, selective_routing
- **Code:** `remora/selective/guardrail.py`, `remora/selective/conformal.py`, `remora/selective/risk_coverage.py`
- **Tests:** `tests/test_guardrail.py`, `tests/test_selective_trust_curve.py`, `tests/test_selective_n500.py`
- **Evidence:** N302 and N500 selective-acceptance experiments; benchmark-scoped selective-trust results with Wilson CIs.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Benchmark-scoped selective trust; no universal out-of-distribution safety guarantee.
- **Literature:** docs/09-related-work.md §1

## RES-003 — Conformal risk control

- **Source:** Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022). Conformal risk control. arXiv:2208.02814.
  - Theorem 1 (referenced in remora/selective/crc.py)
- **Concepts:** split_conformal_calibration, finite_sample_risk_control, repeated_split_robustness
- **REMORA controls:** conformal_thresholding
- **Code:** `remora/selective/crc.py`, `remora/selective/binomial_bounds.py`, `remora/selective/confidence_sequence.py`
- **Tests:** `tests/test_crc.py`, `tests/test_conformal_repeated_splits.py`, `tests/test_confidence_sequence.py`
- **Evidence:** Repeated-split robustness artifacts and negative results preserved in the claim ledger; treated as exchangeability-dependent.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Guarantees hold under exchangeability; repeated-split failures are recorded as negative evidence, not hidden.
- **Literature:** docs/09-related-work.md §2

## RES-004 — Multi-oracle consensus and cross-model verification

- **Source:** Wang et al. (2023), Self-Consistency Improves Chain-of-Thought Reasoning; Wang et al. (2024), Mixture-of-Agents.
  - cited at remora/cascade/stages.py (self-consistency, mixture-of-agents synthesizer)
- **Concepts:** self_consistency_sampling, verifier_model, cross_model_dissensus, multi_agent_debate
- **REMORA controls:** multi_oracle_consensus, independent_verifier_gate
- **Code:** `remora/cascade/stages.py`, `remora/verifier/llm_judge.py`, `remora/oracles/diversity.py`
- **Tests:** `tests/test_moa_synthesizer.py`, `tests/test_llm_judge.py`, `tests/test_oracle_diversity.py`
- **Evidence:** Majority, self-consistency, verifier, and REMORA tool-call baselines; consensus combined with evidence, policy, risk, and audit.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Consensus is not treated as truth; it is one input among evidence, policy, risk, and audit.
- **Literature:** docs/09-related-work.md §3

## RES-005 — Tool-use safety and agent guardrails

- **Source:** Idea family (no single named source in-repo): tool-invocation safety, dry-run/sandboxed evaluation, critical-action routing, prompt-injection benchmarks.
- **Concepts:** tool_invocation_safety, dry_run_sandbox, critical_action_routing
- **REMORA controls:** toolcall_gate, action_type_mapping
- **Code:** `remora/toolcall/remora_gate.py`, `remora/toolcall/schema.py`, `remora/toolcall/scoring.py`
- **Tests:** `tests/test_remora_toolcall_gate.py`, `tests/test_remora_toolcall_gate_v2.py`, `tests/test_toolcall_scoring.py`
- **Evidence:** Deterministic tool-call benchmark v1 (ceiling effect, documented), adversarial v2 (effective N=70, cluster-level CIs).
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** v2 provides deterministic adversarial evidence, not production proof; live validation is a separate requirement.
- **Literature:** docs/09-related-work.md §4

## RES-006 — Evidence grounding and retrieval-augmented verification

- **Source:** Idea family (no single named source in-repo): RAG evidence lookup, source reliability, per-claim support/contradiction, NLI-style verification.
- **Concepts:** retrieval_augmented_verification, per_claim_support_contradiction, nli_style_entailment
- **REMORA controls:** evidence_verifier
- **Code:** `remora/oracles/evidence_v3.py`, `remora/oracles/evidence_verifier.py`
- **Tests:** `tests/test_evidence_v3.py`, `tests/test_evidence_verifier.py`
- **Evidence:** Lexical default verifier with a pluggable NLI-style interface; falls back to lexical when no NLI backend is configured.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Default verifier is lexical plus simple contradiction signals; semantic-entailment quality is not demonstrated by committed artifacts.
- **Literature:** docs/09-related-work.md §5

## RES-007 — Statistical-physics control signals (entropy, phase, Lyapunov)

- **Source:** Generic statistical-physics constructs (q-state Potts model, Gibbs/Boltzmann distribution, Lyapunov objective) used as operational analogy.
- **Concepts:** entropy_order_parameter, phase_regime_classification, lyapunov_stability
- **REMORA controls:** phase_classification, thermodynamic_braking
- **Code:** `remora/statphys/potts.py`, `remora/thermodynamics.py`, `remora/policy/thermodynamic_braking.py`
- **Tests:** `tests/test_statphys.py`, `tests/test_thermodynamics.py`, `tests/test_thermodynamic_braking.py`
- **Evidence:** Phase classification (ordered/critical/disordered) and selective-trust routing; explicit caveats (e.g. 'real oracles are not Potts spins').
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Physics language is an operational analogy and feature family; some theoretical claims remain not-demonstrated or explicitly negative in the claim ledger.
- **Literature:** docs/09-related-work.md §6

## RES-008 — Nested learning, context flow, continuum memory

- **Source:** Behrouz, Razaviyayn, Zhong & Mirrokni, Nested Learning: The Illusion of Deep Learning Architecture (https://abehrouz.github.io/files/NL.pdf); Google Research blog, 2025-11-07.
- **Concepts:** nested_learning, context_flow, continuum_memory, governed_self_modification
- **REMORA controls:** context_flow_governance, governed_memory_layers, reviewed_policy_proposals
- **Code:** `remora/governance/context_flow.py`, `remora/governance/memory_layers.py`, `remora/governance/nested_governance.py`
- **Tests:** `tests/test_governance_context_flow.py`, `tests/test_governance_memory_layers.py`, `tests/test_nested_governance.py`
- **Evidence:** Context flow as a governed information stream; update frequency as a policy boundary; self-modification as reviewed policy proposals.
- **Maturity:** `implemented_and_tested`
- **Scope boundary:** Does not implement the Hope architecture, does not train foundation models, does not claim to solve catastrophic forgetting.
- **Literature:** docs/09-related-work.md §7

## RES-009 — Enterprise AI governance and audit

- **Source:** Idea family (no single named source in-repo): policy-as-code, role/authority boundaries, human-approval workflows, audit ledgers, fail-closed deployment.
- **Concepts:** policy_as_code, human_approval_workflow, audit_ledger, fail_closed_deployment
- **REMORA controls:** enterprise_rollout_reference
- **Code:** `docs/enterprise/togaf-enterprise-rollout-plan.md`, `examples/enterprise_demo.py`
- **Tests:** —
- **Evidence:** TOGAF-structured rollout plan and a runnable enterprise demo; the governance primitives themselves are tested under RES-001..008 and the capability register.
- **Maturity:** `reference_design`
- **Scope boundary:** Reference/design grade: not a production-certified enterprise product; must be validated in the target organization before enforcement.
- **Literature:** docs/09-related-work.md §8
