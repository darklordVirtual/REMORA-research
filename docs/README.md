# REMORA documentation

This is the governed documentation index. The short reading path is intentionally small; the complete registered reference set remains linked below because document governance requires every current or supporting document to be discoverable.

## Primary reading path

1. [Project front page](../README.md) — scope, evidence summary and current limitations.
2. [Developer handoff](../DEVELOPER_OVERVIEW.md) — shortest technical path through the repository.
3. [Architecture](../ARCHITECTURE.md) — canonical runtime architecture and module stability.
4. [Execution quickstart](deployment/execution-quickstart.md) — enforcing `/v1/execution/*` path.
5. [Evidence and claims](02-evidence-and-claims.md) — what each result establishes and what it does not.
6. [Security](08-security.md) — threat model and enforcement assumptions.
7. [Reproducibility](06-reproducibility.md) — benchmark and test reproduction.

For runtime questions, use this precedence:

1. machine-readable assurance registers;
2. `ARCHITECTURE.md` and current API/schema contracts;
3. current numbered documentation;
4. research proposals and design snapshots;
5. archived material.

File presence does not imply runtime wiring. Check the [capability register](assurance/capability_register_v1.yaml) before treating a research component as part of the enforcing path.

## Core series

| Document | Purpose |
|---|---|
| [01-architecture.md](01-architecture.md) | Detailed architecture narrative; subordinate to `ARCHITECTURE.md` when the two differ |
| [02-evidence-and-claims.md](02-evidence-and-claims.md) | Headline claims and supporting evidence |
| [03-experiments.md](03-experiments.md) | Experiments and benchmark tables |
| [04-negative-results-detail.md](04-negative-results-detail.md) | Negative results in depth |
| [05-claim-hygiene.md](05-claim-hygiene.md) | Claim/artifact rules |
| [06-reproducibility.md](06-reproducibility.md) | Reproduction procedures |
| [07-api-reference.md](07-api-reference.md) | REST API and trust boundaries |
| [08-security.md](08-security.md) | Security posture and threat model |
| [09-related-work.md](09-related-work.md) | Literature positioning |
| [10-contributing.md](10-contributing.md) | Contribution and repository-hygiene rules |
| [11-benchmark-validation-plan.md](11-benchmark-validation-plan.md) | External benchmark validation plan |
| [12-agentharm-validation.md](12-agentharm-validation.md) | AgentHarm validation |
| [13-research-frontier-roadmap.md](13-research-frontier-roadmap.md) | Research work packages |
| [AI_USE.md](AI_USE.md) | AI-assisted development disclosure |

The original [execution lifecycle/outbox design](design/execution-lifecycle-outbox-v1.md) and [Signed ToolSpec design](design/toolspec-signed-registry-v1.md) are retained as design history. Their introductory implementation status is historical; current status comes from code, tests and the capability register.

## Developer and project references

| Document | Purpose |
|---|---|
| [CLI reference](cli.md) | CLI commands and exit behavior |
| [Execution lifecycle](execution-lifecycle.md) | Proposal-to-effect lifecycle and outbox |
| [SDK reference](sdk.md) | Stable SDK integration surface |
| [Plain-language overview](plain_language_overview.md) | Non-technical overview |
| [Executive one-pager](executive_onepager.md) | Decision-maker summary |
| [Reference architecture](reference_architecture.md) | Compact architecture overview |
| [failure_analysis.md](failure_analysis.md) | Generated failure analysis |
| [results_snapshot.md](results_snapshot.md) | Generated results snapshot |
| [claim_register.md](claim_register.md) | Human-readable claim overview |

## Evidence and results

| Document | Purpose |
|---|---|
| [evidence/claim_evidence_matrix.md](evidence/claim_evidence_matrix.md) | Claim-to-evidence matrix |
| [evidence/empirical_evidence_record.md](evidence/empirical_evidence_record.md) | Empirical evidence record |
| [evidence/decision_envelope_audit.md](evidence/decision_envelope_audit.md) | DecisionEnvelope audit evidence |
| [evidence/causal_policy_explanations.md](evidence/causal_policy_explanations.md) | Causal explanation evidence |
| [evidence/authorship_evidence_report.md](evidence/authorship_evidence_report.md) | Authorship evidence |
| [Paper](../paper/remora_paper.md) | Scientific paper |

## Commercial

| Document | Purpose |
|---|---|
| [PRODUCT_PACKAGING.md](commercial/PRODUCT_PACKAGING.md) | Product stages bound to release profiles; SHADOW_PILOT is the offering |
| [SHADOW_PILOT.md](commercial/SHADOW_PILOT.md) | Customer lifecycle and exit criteria for the shadow pilot |
| [SECURITY_OVERVIEW.md](commercial/SECURITY_OVERVIEW.md) | Security summary for customer reviewers |
| [DEPLOYMENT_OPTIONS.md](commercial/DEPLOYMENT_OPTIONS.md) | Customer-hosted, local and demo deployment options |
| [DATA_HANDLING.md](commercial/DATA_HANDLING.md) | Data categories, defaults, residency/retention/export |

## Assurance registers

| Register | Purpose |
|---|---|
| [claim_register_v1.yaml](assurance/claim_register_v1.yaml) | Authoritative claims and evidence levels |
| [document_register_v1.yaml](assurance/document_register_v1.yaml) | Governed document inventory |
| [remediation_register.yaml](assurance/remediation_register.yaml) | Open remediation gaps |
| [capability_register_v1.yaml](assurance/capability_register_v1.yaml) | Capability wiring status |
| [fasttrack_register_v1.yaml](assurance/fasttrack_register_v1.yaml) | Fast-track work-package status |
| [release_profiles_v1.yaml](assurance/release_profiles_v1.yaml) | Deployment maturity profiles |
| [product_truth_contract.yaml](product/product_truth_contract.yaml) | Capability classes (core/optional/experimental/legacy/demo) vs public copy |
| [ADR: single execution path](architecture/ADR-single-authoritative-execution-path.md) | One authoritative execution path; agent-control is ingress, not an engine |
| [Multi-tenant security model](architecture/multi_tenant_security_model.md) | Tenant boundaries, threat table with test evidence, open gaps |
| [release_gates.md](assurance/release_gates.md) | Profile gate status |
| [artifact_manifest_v1.md](assurance/artifact_manifest_v1.md) | Result artifact hashes |
| [superseded_claims.md](assurance/superseded_claims.md) | Replaced claims and successors |
| [claim_provenance_baseline.json](assurance/claim_provenance_baseline.json) | Grandfathered provenance exceptions |

## Assurance process and review

| Document | Purpose |
|---|---|
| [assurance_case_v1.md](assurance/assurance_case_v1.md) | Structured assurance case |
| [evidence_levels.md](assurance/evidence_levels.md) | Evidence-level taxonomy |
| [metric_definitions_v1.md](assurance/metric_definitions_v1.md) | Metric definitions and denominators |
| [statistical_analysis_plan_v3.md](assurance/statistical_analysis_plan_v3.md) | Statistical analysis plan v3 |
| [statistical_analysis_plan_v4.md](assurance/statistical_analysis_plan_v4.md) | OT semantic-track statistical analysis plan |
| [rebenchmark_protocol_v1.md](assurance/rebenchmark_protocol_v1.md) | Rebenchmark protocol |
| [experiment_manifest_spec_v1.md](assurance/experiment_manifest_spec_v1.md) | Experiment manifest specification |
| [artifact_provenance_spec_v1.md](assurance/artifact_provenance_spec_v1.md) | Artifact provenance specification |
| [claim_provenance_gate.md](assurance/claim_provenance_gate.md) | Claim-provenance CI gate |
| [documentation_governance_v1.md](assurance/documentation_governance_v1.md) | Documentation governance |
| [benchmark_audit_v1.md](assurance/benchmark_audit_v1.md) | Benchmark audit |
| [policy_engine_audit_v1.md](assurance/policy_engine_audit_v1.md) | Historical policy-engine audit |
| [best_practice_gap_audit_v1.md](assurance/best_practice_gap_audit_v1.md) | Research-practice gap audit |
| [development_review_log_v1.md](assurance/development_review_log_v1.md) | Development review log |
| [external_review_panel_v1.md](assurance/external_review_panel_v1.md) | External review panel record |
| [independent_review_protocol_v1.md](assurance/independent_review_protocol_v1.md) | Independent review protocol |
| [ai_assisted_adversarial_security_review_v1.md](assurance/ai_assisted_adversarial_security_review_v1.md) | Historical adversarial security review |
| [red_team_plan_v1.md](assurance/red_team_plan_v1.md) | Red-team plan |
| [threat_model_v1.md](assurance/threat_model_v1.md) | Threat model |
| [rbac_design_v1.md](assurance/rbac_design_v1.md) | RBAC design |
| [rbac_policy_v1.md](assurance/rbac_policy_v1.md) | RBAC policy |
| [human_oversight_operations_v1.md](assurance/human_oversight_operations_v1.md) | Human-oversight operations |
| [resilience_plan_v1.md](assurance/resilience_plan_v1.md) | Resilience plan |
| [reproducibility_scorecard_v1.md](assurance/reproducibility_scorecard_v1.md) | Reproducibility scorecard |
| [domain_pack_governance_v1.md](assurance/domain_pack_governance_v1.md) | Domain-pack governance |
| [aromer_memory_governance_v1.md](assurance/aromer_memory_governance_v1.md) | AROMER memory governance |

## Benchmarks and active research

| Document | Purpose |
|---|---|
| [benchmarks/README.md](benchmarks/README.md) | Benchmark overview |
| [benchmarks/stat_tests.md](benchmarks/stat_tests.md) | Statistical test methodology |
| [benchmarks/toolcall_consensus_benchmark_v2.md](benchmarks/toolcall_consensus_benchmark_v2.md) | Tool-call benchmark v2 |
| [research/routing_benchmark_v1_design.md](research/routing_benchmark_v1_design.md) | Routing benchmark design |
| [research/task_intent_authority_v1.md](research/task_intent_authority_v1.md) | TaskIntent authority rules |
| [research/research_control_matrix.generated.md](research/research_control_matrix.generated.md) | Generated research-to-control map |
| [research/research_control_matrix_v1.yaml](research/research_control_matrix_v1.yaml) | Research-control matrix source |
| [research/research_shelf_v1.yaml](research/research_shelf_v1.yaml) | Vetted external-component shelf |
| [research/benchmark_round_2026_07.md](research/benchmark_round_2026_07.md) | July 2026 benchmark round |
| [research/method_alternatives_2026_07.md](research/method_alternatives_2026_07.md) | Method alternatives considered |
| [research/governance_intelligence_layer.md](research/governance_intelligence_layer.md) | Governance-intelligence research |
| [research/causal_consequence_gating.md](research/causal_consequence_gating.md) | Causal consequence gating |
| [research/misspecification_aware_governance.md](research/misspecification_aware_governance.md) | Misspecification-aware governance |
| [research/policy_generalization_risk.md](research/policy_generalization_risk.md) | Policy generalization risk |
| [research/research_modes.md](research/research_modes.md) | Research modes |
| [research/verify_control_protocols.md](research/verify_control_protocols.md) | VERIFY-control research |
| [experiments/experiment3_phase_transition_study.md](experiments/experiment3_phase_transition_study.md) | Phase-transition study |
| [experiments/experiment4_susceptibility_validation.md](experiments/experiment4_susceptibility_validation.md) | Susceptibility validation |
| [experiments/experiment5_chi_iteration_utility.md](experiments/experiment5_chi_iteration_utility.md) | Chi-iteration utility |

## Methods and historical research tracks

These files are retained for reproducibility and research history. In particular, thermodynamic/statistical-physics material is **not part of the primary execution architecture**.

| Document | Purpose |
|---|---|
| [methods/nested_governance.md](methods/nested_governance.md) | Nested governance model |
| [methods/architecture_risk_register.md](methods/architecture_risk_register.md) | Architecture risk register |
| [methods/theoretical_foundations_proposals_v1.md](methods/theoretical_foundations_proposals_v1.md) | Theoretical-foundation proposals |
| [methods/thermodynamic_abs.md](methods/thermodynamic_abs.md) | Thermodynamic abstraction research |
| [thermodynamics/README.md](thermodynamics/README.md) | Thermodynamics research overview |
| [thermodynamics/temperature_estimator.md](thermodynamics/temperature_estimator.md) | Temperature-estimator research |
| [thermodynamics/runtime_policy.md](thermodynamics/runtime_policy.md) | Historical runtime-policy experiment |
| [thermodynamics/limitations.md](thermodynamics/limitations.md) | Known limitations |
| [thermodynamics/claim_ledger.yaml](thermodynamics/claim_ledger.yaml) | Thermodynamics claim ledger |
| [claims/thermodynamics_claims.yaml](claims/thermodynamics_claims.yaml) | Thermodynamics claims record |
| [use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md](use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md) | Thermodynamics evidence status |

## Integrations

| Document | Purpose |
|---|---|
| [integrations/agent_tool_hook.md](integrations/agent_tool_hook.md) | Agent pre-tool-use hook |
| [integrations/mcp-integration.md](integrations/mcp-integration.md) | MCP integration |
| [integrations/rag_oracle.md](integrations/rag_oracle.md) | RAG oracle worker |
| [integrations/cloudflare_workers_ai.md](integrations/cloudflare_workers_ai.md) | Cloudflare Workers AI |
| [integrations/knowledge_domains.md](integrations/knowledge_domains.md) | Knowledge domains |
| [integrations/cyber_evidence_layer.md](integrations/cyber_evidence_layer.md) | Cyber evidence layer |
| [integrations/go_star_bridge.md](integrations/go_star_bridge.md) | GO-STAR bridge |
| [integrations/gostar_integration.md](integrations/gostar_integration.md) | GO-STAR integration |

## Deployment and operations

| Document | Purpose |
|---|---|
| [deployment/execution-quickstart.md](deployment/execution-quickstart.md) | Execution-path deployment quickstart |
| [deployment/azure-reference-architecture.md](deployment/azure-reference-architecture.md) | Azure reference architecture |
| [deployment/onprem-airgapped.md](deployment/onprem-airgapped.md) | On-prem / air-gapped deployment |
| [enterprise/togaf-enterprise-rollout-plan.md](enterprise/togaf-enterprise-rollout-plan.md) | TOGAF rollout plan |
| [TOGAF enterprise architecture — PDF](enterprise/no/REMORA_TOGAF_Enterprise_Architecture_v1.0.pdf) | Norwegian TOGAF-aligned architecture PDF |
| [TOGAF enterprise architecture — Markdown](enterprise/no/REMORA_TOGAF_Enterprise_Architecture_v1.0.md) | Norwegian TOGAF source document |
| [enterprise/audit-anchoring-guide.md](enterprise/audit-anchoring-guide.md) | Audit-chain anchoring guide |
| [policy_cookbook/README.md](policy_cookbook/README.md) | Policy cookbook |
| [policy_cookbook/cloud_ops.md](policy_cookbook/cloud_ops.md) | Cloud-operations policy examples |
| [policy_cookbook/cyber.md](policy_cookbook/cyber.md) | Cyber policy examples |
| [policy_cookbook/database.md](policy_cookbook/database.md) | Database policy examples |
| [security/pre-deployment-review.md](security/pre-deployment-review.md) | Pre-deployment security review |
| [security/owasp_genai_mapping.md](security/owasp_genai_mapping.md) | OWASP GenAI mapping |
| [governance/eu_ai_act_nsm_mapping.md](governance/eu_ai_act_nsm_mapping.md) | EU AI Act / NSM mapping |
| [governance/nist_ai_rmf_mapping.md](governance/nist_ai_rmf_mapping.md) | NIST AI RMF mapping |
| [use-cases/README.md](use-cases/README.md) | Use-case index |
| [use-cases/building-automation.md](use-cases/building-automation.md) | Building-automation scenario |

## Validation and external review

| Document | Purpose |
|---|---|
| [validation/EXTERNAL_VALIDATION_PLAN.md](validation/EXTERNAL_VALIDATION_PLAN.md) | External validation plan |
| [validation/external-review.md](validation/external-review.md) | External review record |
| [validation/review_checklist.md](validation/review_checklist.md) | Reviewer checklist |
| [validation/pilot_evaluation_protocol_v1.md](validation/pilot_evaluation_protocol_v1.md) | Pilot evaluation protocol |
| [validation/external_validation_report_template.md](validation/external_validation_report_template.md) | Validator report template |
| [validation/credibility_pack_repro.md](validation/credibility_pack_repro.md) | Credibility-pack reproduction |
| [validation/audit_result_schema.md](validation/audit_result_schema.md) | Audit result schema |

## AROMER

AROMER remains an experimental/research layer. Its documentation is retained separately from the execution-kernel reading path.

| Document | Purpose |
|---|---|
| [aromer/quickstart_aromer.md](aromer/quickstart_aromer.md) | AROMER quickstart |
| [aromer/REMORA_AROMER_MASTER_DOCUMENT.md](aromer/REMORA_AROMER_MASTER_DOCUMENT.md) | AROMER technical reference |

## Archive

Anything under `docs/archive/` is historical unless a current canonical document explicitly references it as evidence. Detailed development history remains available through Git commits and merged pull requests instead of duplicated archive files.

Documentation changes should update or retire stale statements rather than add another parallel explanation. AI-assisted development is disclosed in [AI_USE.md](AI_USE.md); generated prose or code is not evidence by itself.
