# REMORA Documentation Index

The single authoritative index for this repository's documentation, organized
by what you are trying to do. Every linked document is current. Superseded
documents are deliberately **not** linked here — they are tracked with their
successors in the [document register](assurance/document_register_v1.yaml),
and anything under `docs/archive/` is historical and must not be cited as
current truth.

**How stable is what you are reading about?** Per-module maturity
(CORE / EXPERIMENTAL / RESEARCH_ONLY) is tracked in the
[Module Stability Index](../ARCHITECTURE.md#9-module-stability-index) —
check it before depending on a module. As a rule of thumb: the consensus
engine, policy pipeline, enforcement chain, governance/audit chains and
safety firewall are CORE; thermodynamics, Lyapunov, cascade, causal and
AROMER are EXPERIMENTAL; statistical-physics models are RESEARCH_ONLY.

## Start here

| Document | What it gives you |
|---|---|
| [Project front page](../README.md) | What REMORA is, headline evidence, quickstart, key terms |
| [CLI reference](cli.md) | Every `remora` command: try/demo/assess/explain/replay, exit codes, live mode |
| [Plain-language overview](plain_language_overview.md) | Non-technical introduction |
| [Executive one-pager](executive_onepager.md) | One-page summary for decision-makers |
| [Reference architecture](reference_architecture.md) | The system at a glance |

## Core series

The numbered series is the primary reading path.

| Document | Contents |
|---|---|
| [01-architecture.md](01-architecture.md) | Architecture narrative: pipeline, layers, guards |
| [02-evidence-and-claims.md](02-evidence-and-claims.md) | Every headline claim and what supports it |
| [03-experiments.md](03-experiments.md) | All experiments and benchmark tables |
| [04-negative-results-detail.md](04-negative-results-detail.md) | Negative results, in depth (summary: [NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md)) |
| [05-claim-hygiene.md](05-claim-hygiene.md) | The claim/artifact decision rule |
| [06-reproducibility.md](06-reproducibility.md) | Step-by-step benchmark reproduction |
| [07-api-reference.md](07-api-reference.md) | REST API, PolicyObservation contract, trust boundary |
| [08-security.md](08-security.md) | Threat model and security posture (disclosures: [SECURITY.md](../SECURITY.md)) |
| [09-related-work.md](09-related-work.md) | Literature positioning |
| [10-contributing.md](10-contributing.md) | Contribution rules and quality gates |
| [11-benchmark-validation-plan.md](11-benchmark-validation-plan.md) | Plan for external benchmark validation |
| [12-agentharm-validation.md](12-agentharm-validation.md) | AgentHarm external-benchmark validation |
| [13-research-frontier-roadmap.md](13-research-frontier-roadmap.md) | Research frontier roadmap: RF-01–RF-10 work packages (PROPOSED, except RF-10 slice 1 = CAP-014) |
| [AI_USE.md](AI_USE.md) | Disclosure of AI-assisted development |

## Evidence and results

| Document | Contents |
|---|---|
| [results_snapshot.md](results_snapshot.md) | Generated canonical results snapshot |
| [claim_register.md](claim_register.md) | Generated human-readable claim overview |
| [failure_analysis.md](failure_analysis.md) | Generated failure analysis |
| [evidence/claim_evidence_matrix.md](evidence/claim_evidence_matrix.md) | Claim-to-evidence matrix |
| [evidence/empirical_evidence_record.md](evidence/empirical_evidence_record.md) | Empirical evidence record |
| [evidence/decision_envelope_audit.md](evidence/decision_envelope_audit.md) | DecisionEnvelope audit trail evidence |
| [evidence/causal_policy_explanations.md](evidence/causal_policy_explanations.md) | Causal explanation evidence |
| [evidence/authorship_evidence_report.md](evidence/authorship_evidence_report.md) | Authorship evidence |
| [Paper](../paper/remora_paper.md) | The scientific whitepaper |

## Assurance: registers (machine-readable sources of truth)

| Register | Governs |
|---|---|
| [claim_register_v1.yaml](assurance/claim_register_v1.yaml) | All claims, evidence levels, artifacts (authoritative) |
| [document_register_v1.yaml](assurance/document_register_v1.yaml) | Every governed document |
| [remediation_register.yaml](assurance/remediation_register.yaml) | Open gaps (REM ids) |
| [capability_register_v1.yaml](assurance/capability_register_v1.yaml) | Capability wiring status (CAP ids) |
| [release_profiles_v1.yaml](assurance/release_profiles_v1.yaml) | Deployment maturity ladder |
| [release_gates.md](assurance/release_gates.md) | Gate status per profile |
| [artifact_manifest_v1.md](assurance/artifact_manifest_v1.md) | SHA-256 manifest of result artifacts |
| [superseded_claims.md](assurance/superseded_claims.md) | Generated archive of claims a later round replaced, and what replaced them |
| [claim_provenance_baseline.json](assurance/claim_provenance_baseline.json) | Grandfathered provenance violations |

## Assurance: process and audits

| Document | Contents |
|---|---|
| [assurance_case_v1.md](assurance/assurance_case_v1.md) | The structured assurance case |
| [evidence_levels.md](assurance/evidence_levels.md) | Evidence-level taxonomy |
| [metric_definitions_v1.md](assurance/metric_definitions_v1.md) | Canonical metric definitions and denominators |
| [statistical_analysis_plan_v3.md](assurance/statistical_analysis_plan_v3.md) | Pre-registered statistical analysis plan (in force) |
| [rebenchmark_protocol_v1.md](assurance/rebenchmark_protocol_v1.md) | Protocol for the next clean benchmark round |
| [experiment_manifest_spec_v1.md](assurance/experiment_manifest_spec_v1.md) | Experiment manifest specification |
| [artifact_provenance_spec_v1.md](assurance/artifact_provenance_spec_v1.md) | Artifact provenance specification |
| [claim_provenance_gate.md](assurance/claim_provenance_gate.md) | The claim-provenance CI gate |
| [documentation_governance_v1.md](assurance/documentation_governance_v1.md) | How documentation itself is governed |
| [benchmark_audit_v1.md](assurance/benchmark_audit_v1.md) | Benchmark audit findings |
| [policy_engine_audit_v1.md](assurance/policy_engine_audit_v1.md) | Policy-engine audit |
| [best_practice_gap_audit_v1.md](assurance/best_practice_gap_audit_v1.md) | Gap audit vs research best practice |
| [development_review_log_v1.md](assurance/development_review_log_v1.md) | Development review log |
| [external_review_panel_v1.md](assurance/external_review_panel_v1.md) | External review panel record |
| [independent_review_protocol_v1.md](assurance/independent_review_protocol_v1.md) | Protocol for independent review |
| [ai_assisted_adversarial_security_review_v1.md](assurance/ai_assisted_adversarial_security_review_v1.md) | Adversarial security review |
| [red_team_plan_v1.md](assurance/red_team_plan_v1.md) | Red-team plan |
| [threat_model_v1.md](assurance/threat_model_v1.md) | Threat model |
| [rbac_design_v1.md](assurance/rbac_design_v1.md) · [rbac_policy_v1.md](assurance/rbac_policy_v1.md) | RBAC design and policy |
| [human_oversight_operations_v1.md](assurance/human_oversight_operations_v1.md) | Human-oversight operations |
| [resilience_plan_v1.md](assurance/resilience_plan_v1.md) | Resilience plan |
| [reproducibility_scorecard_v1.md](assurance/reproducibility_scorecard_v1.md) | Reproducibility scorecard |
| [domain_pack_governance_v1.md](assurance/domain_pack_governance_v1.md) | Domain-pack governance |
| [aromer_memory_governance_v1.md](assurance/aromer_memory_governance_v1.md) | AROMER memory governance |

## Benchmarks and research

| Document | Contents |
|---|---|
| [benchmarks/README.md](benchmarks/README.md) | Benchmark overview |
| [benchmarks/stat_tests.md](benchmarks/stat_tests.md) | Statistical test methodology |
| [benchmarks/toolcall_consensus_benchmark_v2.md](benchmarks/toolcall_consensus_benchmark_v2.md) | Tool-call benchmark v2 |
| [research/routing_benchmark_v1_design.md](research/routing_benchmark_v1_design.md) | Tool-routing benchmark design: predicates, frozen routing, leakage gates |
| [research/research_control_matrix.generated.md](research/research_control_matrix.generated.md) | Research-line → control → code → test matrix (generated) |
| [research/research_control_matrix_v1.yaml](research/research_control_matrix_v1.yaml) | Matrix source |
| [research/research_shelf_v1.yaml](research/research_shelf_v1.yaml) | Vetted external-component shelf: source, retrieval status, adoption verdict per candidate |
| [research/benchmark_round_2026_07.md](research/benchmark_round_2026_07.md) | 2026-07 benchmark round |
| [research/method_alternatives_2026_07.md](research/method_alternatives_2026_07.md) | Method alternatives considered |
| [research/governance_intelligence_layer.md](research/governance_intelligence_layer.md) | Governance-intelligence layer |
| [research/causal_consequence_gating.md](research/causal_consequence_gating.md) | Causal consequence gating |
| [research/misspecification_aware_governance.md](research/misspecification_aware_governance.md) | Misspecification-aware governance |
| [research/policy_generalization_risk.md](research/policy_generalization_risk.md) | Policy generalization risk |
| [research/research_modes.md](research/research_modes.md) | Research modes |
| [research/verify_control_protocols.md](research/verify_control_protocols.md) | AI-control VERIFY-resolution design + frozen pre-registered re-scoring rule (RF-04) |
| [experiments/experiment3_phase_transition_study.md](experiments/experiment3_phase_transition_study.md) | Phase-transition study |
| [experiments/experiment4_susceptibility_validation.md](experiments/experiment4_susceptibility_validation.md) | Susceptibility validation |
| [experiments/experiment5_chi_iteration_utility.md](experiments/experiment5_chi_iteration_utility.md) | Chi iteration utility |

## Methods and theory

| Document | Contents |
|---|---|
| [methods/nested_governance.md](methods/nested_governance.md) | Nested governance layer model |
| [methods/architecture_risk_register.md](methods/architecture_risk_register.md) | Architecture risk register |
| [methods/theoretical_foundations_proposals_v1.md](methods/theoretical_foundations_proposals_v1.md) | Theoretical foundations proposals |
| [methods/thermodynamic_abs.md](methods/thermodynamic_abs.md) | Thermodynamic abstraction |
| [thermodynamics/README.md](thermodynamics/README.md) | Thermodynamics overview (diagnostic-grade signals) |
| [thermodynamics/temperature_estimator.md](thermodynamics/temperature_estimator.md) | Temperature estimator |
| [thermodynamics/runtime_policy.md](thermodynamics/runtime_policy.md) | Runtime policy for thermo signals |
| [thermodynamics/limitations.md](thermodynamics/limitations.md) | Known limitations |
| [thermodynamics/claim_ledger.yaml](thermodynamics/claim_ledger.yaml) | Thermodynamics claim ledger (authoritative) |
| [claims/thermodynamics_claims.yaml](claims/thermodynamics_claims.yaml) | Thermodynamics claims |
| [use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md](use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md) | Thermodynamics evidence status |

## Integrations

| Document | Contents |
|---|---|
| [integrations/agent_tool_hook.md](integrations/agent_tool_hook.md) | Agent tool hook (PreToolUse) |
| [integrations/mcp-integration.md](integrations/mcp-integration.md) | MCP integration |
| [integrations/rag_oracle.md](integrations/rag_oracle.md) | RAG oracle worker |
| [integrations/cloudflare_workers_ai.md](integrations/cloudflare_workers_ai.md) | Cloudflare Workers AI |
| [integrations/knowledge_domains.md](integrations/knowledge_domains.md) | Knowledge domains |
| [integrations/cyber_evidence_layer.md](integrations/cyber_evidence_layer.md) | Cyber evidence layer |
| [integrations/go_star_bridge.md](integrations/go_star_bridge.md) · [integrations/gostar_integration.md](integrations/gostar_integration.md) | GO-STAR bridge and integration |

## Deployment and operations

| Document | Contents |
|---|---|
| [deployment/execution-quickstart.md](deployment/execution-quickstart.md) | Execution-path deployment quickstart: install → configure → registry → run → verify the chain |
| [deployment/azure-reference-architecture.md](deployment/azure-reference-architecture.md) | Azure reference architecture |
| [deployment/onprem-airgapped.md](deployment/onprem-airgapped.md) | On-prem / air-gapped deployment |
| [enterprise/togaf-enterprise-rollout-plan.md](enterprise/togaf-enterprise-rollout-plan.md) | TOGAF enterprise rollout plan |
| [enterprise/audit-anchoring-guide.md](enterprise/audit-anchoring-guide.md) | Audit-chain Merkle checkpointing: coverage, verification, threat-model delta |
| [policy_cookbook/README.md](policy_cookbook/README.md) | Policy cookbook (recipes: [cloud_ops](policy_cookbook/cloud_ops.md), [cyber](policy_cookbook/cyber.md), [database](policy_cookbook/database.md)) |
| [security/pre-deployment-review.md](security/pre-deployment-review.md) | Pre-deployment security review |
| [security/owasp_genai_mapping.md](security/owasp_genai_mapping.md) | OWASP GenAI mapping |
| [governance/eu_ai_act_nsm_mapping.md](governance/eu_ai_act_nsm_mapping.md) | EU AI Act / NSM mapping |
| [governance/nist_ai_rmf_mapping.md](governance/nist_ai_rmf_mapping.md) | NIST AI RMF mapping |
| [use-cases/README.md](use-cases/README.md) | Worked scenarios ([building automation](use-cases/building-automation.md)) |

## Validation and external review

| Document | Contents |
|---|---|
| [validation/EXTERNAL_VALIDATION_PLAN.md](validation/EXTERNAL_VALIDATION_PLAN.md) | External validation plan |
| [validation/external-review.md](validation/external-review.md) | External review record |
| [validation/review_checklist.md](validation/review_checklist.md) | Reviewer checklist |
| [validation/pilot_evaluation_protocol_v1.md](validation/pilot_evaluation_protocol_v1.md) | Pre-registered pilot framework: preconditions, metrics, go/no-go, stop conditions (PROPOSED) |
| [validation/external_validation_report_template.md](validation/external_validation_report_template.md) | Report template for external validators |
| [validation/credibility_pack_repro.md](validation/credibility_pack_repro.md) | Credibility-pack reproduction |
| [validation/audit_result_schema.md](validation/audit_result_schema.md) | Audit result schema |

## AROMER (experimental learning layer)

| Document | Contents |
|---|---|
| [aromer/quickstart_aromer.md](aromer/quickstart_aromer.md) | AROMER quickstart |
| [aromer/REMORA_AROMER_MASTER_DOCUMENT.md](aromer/REMORA_AROMER_MASTER_DOCUMENT.md) | AROMER master document |
