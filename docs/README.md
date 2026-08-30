# REMORA documentation

Seven documents cover most questions. Everything else in `docs/` is listed further down, grouped by the question it answers, so the full registered set stays reachable from this page.

## Start here

1. [Project front page](../README.md): what REMORA is, the evidence summary and current limitations.
2. [Developer handoff](../DEVELOPER_OVERVIEW.md): the shortest technical path through the repository.
3. [Architecture](../ARCHITECTURE.md): runtime architecture and module stability.
4. [Execution quickstart](deployment/execution-quickstart.md): running the enforcing `/v1/execution/*` path.
5. [Evidence and claims](02-evidence-and-claims.md): what each result establishes and what it does not.
6. [Security](08-security.md): threat model and enforcement assumptions.
7. [Reproducibility](06-reproducibility.md): reproducing the benchmarks and tests.

When documents disagree, the machine-readable registers under `assurance/` win, then `ARCHITECTURE.md` and the API/schema contracts, then the numbered series, then research proposals and design snapshots, then the archive. A module in the tree is not necessarily on the enforcing path: the [capability register](assurance/capability_register_v1.yaml) says what is wired.

## Which one do I want?

Several topics have more than one document. This table says which to open.

| If you want | Open | Rather than |
|---|---|---|
| The runtime architecture as it is | [ARCHITECTURE.md](../ARCHITECTURE.md) | [01-architecture.md](01-architecture.md) (longer narrative, follows ARCHITECTURE.md) or [reference_architecture.md](reference_architecture.md) (compact overview for slides) |
| A non-technical explanation | [Plain-language overview](plain_language_overview.md) | [Executive one-pager](executive_onepager.md) (one page, for a decision) |
| Security as a customer reviewer | [SECURITY_OVERVIEW.md](commercial/SECURITY_OVERVIEW.md) | [08-security.md](08-security.md) (engineering posture) or [threat_model_v1.md](assurance/threat_model_v1.md) (full threat model) |
| To call REMORA from an agent over MCP | [mcp-gateway.md](integrations/mcp-gateway.md) (the governed gateway on the execution path) | [mcp-integration.md](integrations/mcp-integration.md) (the earlier direct MCP integration) |
| GO-STAR | [gostar_integration.md](integrations/gostar_integration.md) (how the two systems connect) | [go_star_bridge.md](integrations/go_star_bridge.md) (the bridge component itself) |
| The statistical analysis plan | [v3](assurance/statistical_analysis_plan_v3.md) for the main benchmark, [v4](assurance/statistical_analysis_plan_v4.md) for the OT semantic track, [v5](assurance/statistical_analysis_plan_v5_bfcl_semantic.md) for BFCL C-ext3 (executed 2026-08-19, 3 of 7 targets met, CLAIM-019) | [v1](assurance/statistical_analysis_plan.md) and [v2](assurance/statistical_analysis_plan_v2.md), kept only as the pre-registration record |
| The claims themselves | [claim_register_v1.yaml](assurance/claim_register_v1.yaml) | [claim_register.md](claim_register.md) (readable rendering) or [claim_evidence_matrix.md](evidence/claim_evidence_matrix.md) (claim to evidence) |

## Everything else

<details>
<summary><strong>Numbered series</strong>: the long-form documents behind the reading path</summary>

| Document | Purpose |
|---|---|
| [01-architecture.md](01-architecture.md) | Detailed architecture narrative |
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

</details>

<details>
<summary><strong>Using and integrating REMORA</strong>: CLI, SDK, lifecycle, integrations, policy examples</summary>

| Document | Purpose |
|---|---|
| [CLI reference](cli.md) | CLI commands and exit behavior |
| [SDK reference](sdk.md) | Stable SDK integration surface |
| [Execution lifecycle](execution-lifecycle.md) | Proposal-to-effect lifecycle and outbox |
| [integrations/agent_tool_hook.md](integrations/agent_tool_hook.md) | Agent pre-tool-use hook |
| [integrations/mcp-gateway.md](integrations/mcp-gateway.md) | Governed MCP gateway: agent tool calls through the execution path |
| [integrations/mcp-integration.md](integrations/mcp-integration.md) | MCP integration |
| [integrations/rag_oracle.md](integrations/rag_oracle.md) | RAG oracle worker |
| [integrations/cloudflare_workers_ai.md](integrations/cloudflare_workers_ai.md) | Cloudflare Workers AI |
| [integrations/knowledge_domains.md](integrations/knowledge_domains.md) | Knowledge domains |
| [integrations/cyber_evidence_layer.md](integrations/cyber_evidence_layer.md) | Cyber evidence layer |
| [integrations/gostar_integration.md](integrations/gostar_integration.md) | GO-STAR integration |
| [integrations/go_star_bridge.md](integrations/go_star_bridge.md) | GO-STAR bridge |
| [policy_cookbook/README.md](policy_cookbook/README.md) | Policy cookbook |
| [policy_cookbook/cloud_ops.md](policy_cookbook/cloud_ops.md) | Cloud-operations policy examples |
| [policy_cookbook/cyber.md](policy_cookbook/cyber.md) | Cyber policy examples |
| [policy_cookbook/database.md](policy_cookbook/database.md) | Database policy examples |
| [use-cases/README.md](use-cases/README.md) | Use-case index |
| [use-cases/building-automation.md](use-cases/building-automation.md) | Building-automation scenario |

</details>

<details>
<summary><strong>Deploying and operating</strong>: reference deployments, key custody, compliance mappings</summary>

| Document | Purpose |
|---|---|
| [deployment/execution-quickstart.md](deployment/execution-quickstart.md) | Execution-path deployment quickstart |
| [deployment/container-reference.md](deployment/container-reference.md) | Containerised reference deployment for locked pilot installs (wheel-built, digest-pinned, in-image contract smoke) |
| [deployment/azure-reference-architecture.md](deployment/azure-reference-architecture.md) | Azure reference architecture |
| [deployment/onprem-airgapped.md](deployment/onprem-airgapped.md) | On-prem / air-gapped deployment |
| [deployment/authority-custody-evidence.md](deployment/authority-custody-evidence.md) | Deployed evidence for the authority/execution custody split; every value read from the running system |
| [deployment/authority-key-topology.md](deployment/authority-key-topology.md) | Signing topology of the Cloudflare deployment, current and target, read from source |
| [enterprise/audit-anchoring-guide.md](enterprise/audit-anchoring-guide.md) | Audit-chain anchoring guide |
| [enterprise/togaf-enterprise-rollout-plan.md](enterprise/togaf-enterprise-rollout-plan.md) | TOGAF rollout plan |
| [TOGAF enterprise architecture (Markdown)](enterprise/no/REMORA_TOGAF_Enterprise_Architecture_v1.0.md) | Norwegian TOGAF source document |
| [TOGAF enterprise architecture (PDF)](enterprise/no/REMORA_TOGAF_Enterprise_Architecture_v1.0.pdf) | Norwegian TOGAF-aligned architecture PDF |
| [security/pre-deployment-review.md](security/pre-deployment-review.md) | Pre-deployment security review |
| [security/owasp_genai_mapping.md](security/owasp_genai_mapping.md) | OWASP GenAI mapping |
| [governance/eu_ai_act_nsm_mapping.md](governance/eu_ai_act_nsm_mapping.md) | EU AI Act / NSM mapping |
| [governance/nist_ai_rmf_mapping.md](governance/nist_ai_rmf_mapping.md) | NIST AI RMF mapping |
| [reference_architecture.md](reference_architecture.md) | Compact architecture overview |

</details>

<details>
<summary><strong>Commercial</strong>: the shadow-pilot offering and what a customer reviewer needs</summary>

| Document | Purpose |
|---|---|
| [PRODUCT_PACKAGING.md](commercial/PRODUCT_PACKAGING.md) | Product stages bound to release profiles; SHADOW_PILOT is the offering |
| [SHADOW_PILOT.md](commercial/SHADOW_PILOT.md) | Customer lifecycle and exit criteria for the shadow pilot |
| [SECURITY_OVERVIEW.md](commercial/SECURITY_OVERVIEW.md) | Security summary for customer reviewers |
| [DEPLOYMENT_OPTIONS.md](commercial/DEPLOYMENT_OPTIONS.md) | Customer-hosted, local and demo deployment options |
| [DATA_HANDLING.md](commercial/DATA_HANDLING.md) | Data categories, defaults, residency/retention/export |
| [Plain-language overview](plain_language_overview.md) | Non-technical overview |
| [Executive one-pager](executive_onepager.md) | Decision-maker summary |

</details>

<details>
<summary><strong>Evidence and results</strong>: what was measured and where the numbers come from</summary>

| Document | Purpose |
|---|---|
| [Paper](../paper/remora_paper.md) | Scientific paper |
| [claim_register.md](claim_register.md) | Human-readable claim overview |
| [EVIDENCE_OF_CAPABILITY.md](EVIDENCE_OF_CAPABILITY.md) | Capability evidence summary for reviewers |
| [CONTRIBUTORS.md](CONTRIBUTORS.md) | Contributors and contribution record |
| [results_snapshot.md](results_snapshot.md) | Generated results snapshot |
| [failure_analysis.md](failure_analysis.md) | Generated failure analysis |
| [evidence/claim_evidence_matrix.md](evidence/claim_evidence_matrix.md) | Claim-to-evidence matrix |
| [evidence/empirical_evidence_record.md](evidence/empirical_evidence_record.md) | Empirical evidence record |
| [evidence/decision_envelope_audit.md](evidence/decision_envelope_audit.md) | DecisionEnvelope audit evidence |
| [evidence/causal_policy_explanations.md](evidence/causal_policy_explanations.md) | Causal explanation evidence |
| [evidence/authorship_evidence_report.md](evidence/authorship_evidence_report.md) | Authorship evidence |
| [benchmarks/README.md](benchmarks/README.md) | Benchmark overview |
| [benchmarks/stat_tests.md](benchmarks/stat_tests.md) | Statistical test methodology |
| [benchmarks/toolcall_consensus_benchmark_v2.md](benchmarks/toolcall_consensus_benchmark_v2.md) | Tool-call benchmark v2 |
| [benchmarks/agent-authority-conformance-v0.1.md](benchmarks/agent-authority-conformance-v0.1.md) | Agent Authority Conformance v0.1 (vendor-neutral A-G property model; draft) |
| [benchmarks/aegis-remora-crosswalk.md](benchmarks/aegis-remora-crosswalk.md) | AEGIS Core 3.4.0 x REMORA A-G crosswalk (first application; not a ranking) |
| [research/benchmark_round_2026_07.md](research/benchmark_round_2026_07.md) | July 2026 benchmark round |

</details>

<details>
<summary><strong>Assurance registers and decisions</strong>: the machine-readable sources that other documents defer to</summary>

| Register | Purpose |
|---|---|
| [claim_register_v1.yaml](assurance/claim_register_v1.yaml) | Claims and evidence levels |
| [document_register_v1.yaml](assurance/document_register_v1.yaml) | Governed document inventory |
| [remediation_register.yaml](assurance/remediation_register.yaml) | Open remediation gaps |
| [capability_register_v1.yaml](assurance/capability_register_v1.yaml) | Capability wiring status |
| [credential_topology.yaml](assurance/credential_topology.yaml) | Credential custody and agent-zone reachability (Agent Authority property E) |
| [fasttrack_register_v1.yaml](assurance/fasttrack_register_v1.yaml) | Fast-track work-package status |
| [release_profiles_v1.yaml](assurance/release_profiles_v1.yaml) | Deployment maturity profiles |
| [release_gates.md](assurance/release_gates.md) | Profile gate status |
| [shipped_surfaces_v1.yaml](assurance/shipped_surfaces_v1.yaml) | Advertised surfaces bound to the CI jobs that guard them (issue #84) |
| [product_truth_contract.yaml](product/product_truth_contract.yaml) | Capability classes (core/optional/experimental/legacy/demo) vs public copy |
| [artifact_manifest_v1.md](assurance/artifact_manifest_v1.md) | Result artifact hashes |
| [superseded_claims.md](assurance/superseded_claims.md) | Replaced claims and successors |
| [claim_provenance_baseline.json](assurance/claim_provenance_baseline.json) | Grandfathered provenance exceptions |
| [claim_metric_binding_baseline.json](assurance/claim_metric_binding_baseline.json) | Published numbers not stored in their artifact, with reasons; shrink-only |
| [prose_style_baseline.json](assurance/prose_style_baseline.json) | Shrink-only per-file counts of structural prose tells (`scripts/check_prose_style.py`) |
| [ADR: single execution path](architecture/ADR-single-authoritative-execution-path.md) | One authoritative execution path; agent-control is ingress, not an engine |
| [ADR: tainted arguments](architecture/ADR-tainted-argument-approval.md) | Approval suffices; sanitisation not required, with the residual stated (issue #40) |
| [ADR: authority custody and lease durability](architecture/ADR-authority-custody-and-lease-durability.md) | A and B implemented (Ed25519 custody split, durable lease nonces); C, D and E accepted as direction only |
| [ADR: canonical decision engine](architecture/ADR-canonical-decision-engine.md) | The policy core decides; the consensus engine is a research surface with a stated lifetime; cross-surface middleware shared (issue #296) |
| [Multi-tenant security model](architecture/multi_tenant_security_model.md) | Tenant boundaries, threat table with test evidence, open gaps |
| [Cloudflare state architecture](architecture/cloudflare_state_architecture.md) | Design: DO/D1/R2/KV/Workflows placement rules, tenant keying, secrets custody |

</details>

<details>
<summary><strong>Assurance process and review</strong>: how claims, metrics and reviews are governed</summary>

| Document | Purpose |
|---|---|
| [assurance_case_v1.md](assurance/assurance_case_v1.md) | Structured assurance case |
| [evidence_levels.md](assurance/evidence_levels.md) | Evidence-level taxonomy |
| [metric_definitions_v1.md](assurance/metric_definitions_v1.md) | Metric definitions and denominators |
| [statistical_analysis_plan.md](assurance/statistical_analysis_plan.md) | Statistical analysis plan v1 (superseded; pre-registration record) |
| [statistical_analysis_plan_v2.md](assurance/statistical_analysis_plan_v2.md) | Statistical analysis plan v2 (superseded; pre-registration record) |
| [statistical_analysis_plan_v3.md](assurance/statistical_analysis_plan_v3.md) | Statistical analysis plan v3 |
| [statistical_analysis_plan_v4.md](assurance/statistical_analysis_plan_v4.md) | OT semantic-track statistical analysis plan |
| [statistical_analysis_plan_v5_bfcl_semantic.md](assurance/statistical_analysis_plan_v5_bfcl_semantic.md) | Pre-registered BFCL semantic-authority confirmation (C-ext3; executed 2026-08-19, 3 of 7 targets met, CLAIM-019) |
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
| [mutation_testing_v1.md](assurance/mutation_testing_v1.md) | Measured mutation pass over the grant/lease/PEP paths; kill rates, survivor triage, golden-vector fix (issue #280) |
| [domain_pack_governance_v1.md](assurance/domain_pack_governance_v1.md) | Domain-pack governance |
| [aromer_memory_governance_v1.md](assurance/aromer_memory_governance_v1.md) | AROMER memory governance |
| [validation/EXTERNAL_VALIDATION_PLAN.md](validation/EXTERNAL_VALIDATION_PLAN.md) | External validation plan |
| [validation/external-review.md](validation/external-review.md) | External review record |
| [validation/review_checklist.md](validation/review_checklist.md) | Reviewer checklist |
| [validation/pilot_evaluation_protocol_v1.md](validation/pilot_evaluation_protocol_v1.md) | Pilot evaluation protocol |
| [validation/external_validation_report_template.md](validation/external_validation_report_template.md) | Validator report template |
| [validation/credibility_pack_repro.md](validation/credibility_pack_repro.md) | Credibility-pack reproduction |
| [validation/audit_result_schema.md](validation/audit_result_schema.md) | Audit result schema |

</details>

<details>
<summary><strong>Research</strong>: active research tracks, design proposals and the AROMER layer</summary>

Design documents describe a proposal at the time it was written; whether it shipped is answered by code, tests and the capability register. AROMER is an experimental layer with its own version and a one-way dependency on REMORA.

| Document | Purpose |
|---|---|
| [research/research_control_matrix.generated.md](research/research_control_matrix.generated.md) | Generated research-to-control map |
| [research/research_control_matrix_v1.yaml](research/research_control_matrix_v1.yaml) | Research-control matrix source |
| [research/research_shelf_v1.yaml](research/research_shelf_v1.yaml) | Vetted external-component shelf |
| [research/routing_benchmark_v1_design.md](research/routing_benchmark_v1_design.md) | Routing benchmark design |
| [research/task_intent_authority_v1.md](research/task_intent_authority_v1.md) | TaskIntent authority rules |
| [research/method_alternatives_2026_07.md](research/method_alternatives_2026_07.md) | Method alternatives considered |
| [research/governance_intelligence_layer.md](research/governance_intelligence_layer.md) | Governance-intelligence research |
| [research/causal_consequence_gating.md](research/causal_consequence_gating.md) | Causal consequence gating |
| [research/misspecification_aware_governance.md](research/misspecification_aware_governance.md) | Misspecification-aware governance |
| [research/policy_generalization_risk.md](research/policy_generalization_risk.md) | Policy generalization risk |
| [research/research_modes.md](research/research_modes.md) | Research modes |
| [research/verify_control_protocols.md](research/verify_control_protocols.md) | VERIFY-control research |
| [research/adjacent-systems-crosswalk-v2.md](research/adjacent-systems-crosswalk-v2.md) | Adjacent-systems crosswalk v2, corrected against HEAD; v1's errors reproduced rather than deleted |
| [research/REMORA_forskningsmonografi_no.md](research/REMORA_forskningsmonografi_no.md) | Norwegian research monograph: consolidated code-anchored description (language: Norwegian) |
| [design/execution-lifecycle-outbox-v1.md](design/execution-lifecycle-outbox-v1.md) | Execution lifecycle/outbox design (design history) |
| [design/toolspec-signed-registry-v1.md](design/toolspec-signed-registry-v1.md) | Signed ToolSpec design (design history) |
| [design/cloudflare-mcp-gateway-v1.md](design/cloudflare-mcp-gateway-v1.md) | Governed MCP gateway design for the Cloudflare deployment (open proposal) |
| [design/aps-authority-profile-v0.md](design/aps-authority-profile-v0.md) | RFC 8785 canonicalisation for APS interop: three divergence classes closed, the number model declined with its reason (open proposal) |
| [design/runtime-trust-base-identity-v1.md](design/runtime-trust-base-identity-v1.md) | Binding the executing runtime into the execution lease (ADR-D), and what a self-declared identity does not establish (open proposal) |
| [methods/nested_governance.md](methods/nested_governance.md) | Nested governance model |
| [methods/architecture_risk_register.md](methods/architecture_risk_register.md) | Architecture risk register |
| [methods/theoretical_foundations_proposals_v1.md](methods/theoretical_foundations_proposals_v1.md) | Theoretical-foundation proposals |
| [aromer/SUBPROJECT.md](aromer/SUBPROJECT.md) | AROMER subproject charter (issue #297) |
| [aromer/quickstart_aromer.md](aromer/quickstart_aromer.md) | AROMER quickstart |
| [aromer/REMORA_AROMER_MASTER_DOCUMENT.md](aromer/REMORA_AROMER_MASTER_DOCUMENT.md) | AROMER technical reference |

</details>

<details>
<summary><strong>Historical research tracks</strong>: thermodynamic and statistical-physics material, kept for reproducibility</summary>

This material was withdrawn from the paper and is outside the execution architecture. It stays so the earlier experiments can be re-run.

| Document | Purpose |
|---|---|
| [methods/thermodynamic_abs.md](methods/thermodynamic_abs.md) | Thermodynamic abstraction research |
| [thermodynamics/README.md](thermodynamics/README.md) | Thermodynamics research overview |
| [thermodynamics/temperature_estimator.md](thermodynamics/temperature_estimator.md) | Temperature-estimator research |
| [thermodynamics/runtime_policy.md](thermodynamics/runtime_policy.md) | Historical runtime-policy experiment |
| [thermodynamics/limitations.md](thermodynamics/limitations.md) | Known limitations |
| [thermodynamics/claim_ledger.yaml](thermodynamics/claim_ledger.yaml) | Thermodynamics claim ledger |
| [claims/thermodynamics_claims.yaml](claims/thermodynamics_claims.yaml) | Thermodynamics claims record |
| [use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md](use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md) | Thermodynamics evidence status |
| [experiments/experiment3_phase_transition_study.md](experiments/experiment3_phase_transition_study.md) | Phase-transition study |
| [experiments/experiment4_susceptibility_validation.md](experiments/experiment4_susceptibility_validation.md) | Susceptibility validation |
| [experiments/experiment5_chi_iteration_utility.md](experiments/experiment5_chi_iteration_utility.md) | Chi-iteration utility |

</details>

## Archive

`docs/archive/` holds superseded material. Development history lives in Git commits and merged pull requests rather than in copies. When a statement goes stale, update or retire it instead of adding a parallel explanation.
