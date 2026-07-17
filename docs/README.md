# REMORA Documentation Index

The single documentation index. Every current document is reachable from
here; anything under [`archive/`](archive/) is historical and must not be
cited as current. Gate status lives in one place only:
[`assurance/release_gates.md`](assurance/release_gates.md).

## Start here

| Audience | Read |
|---|---|
| Architect / reviewer | [`reference_architecture.md`](reference_architecture.md) — the assurance control plane, plane by plane, with code pointers |
| Executive / non-technical | [`executive_onepager.md`](executive_onepager.md) · [`plain_language_overview.md`](plain_language_overview.md) |
| Reproducing results | [`06-reproducibility.md`](06-reproducibility.md) — clone-and-run instructions |
| Auditing claims | [`02-evidence-and-claims.md`](02-evidence-and-claims.md) · [`claim_register.md`](claim_register.md) · [`../NEGATIVE_RESULTS.md`](../NEGATIVE_RESULTS.md) |

## Core series (the numbered narrative)

| # | Document | Purpose |
|---|---|---|
| 01 | [`01-architecture.md`](01-architecture.md) | How REMORA works end to end |
| 02 | [`02-evidence-and-claims.md`](02-evidence-and-claims.md) | Headline claims and their artifacts |
| 03 | [`03-experiments.md`](03-experiments.md) | Experiment design and outputs |
| 04 | [`04-negative-results-detail.md`](04-negative-results-detail.md) | Detailed negative-results record |
| 05 | [`05-claim-hygiene.md`](05-claim-hygiene.md) | The decision rule for adding a claim |
| 06 | [`06-reproducibility.md`](06-reproducibility.md) | Reproduce everything from scratch |
| 07 | [`07-api-reference.md`](07-api-reference.md) | Public interfaces |
| 08 | [`08-security.md`](08-security.md) | Security properties and gaps |
| 09 | [`09-related-work.md`](09-related-work.md) | Literature positioning |
| 10 | [`10-contributing.md`](10-contributing.md) | Contribution guide |
| 11 | [`11-benchmark-validation-plan.md`](11-benchmark-validation-plan.md) | External validation plan |
| 12 | [`12-agentharm-validation.md`](12-agentharm-validation.md) | AgentHarm protocol |

Architecture supplements: [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
(canonical top-level reference) · [`architecture_risk_register.md`](architecture_risk_register.md) ·
[`remora_architecture.html`](remora_architecture.html) (infographic) ·
[`decision_envelope_audit.md`](decision_envelope_audit.md) (audit semantics) ·
[`nested_governance.md`](nested_governance.md) · [`thermodynamic_abs.md`](thermodynamic_abs.md).

## Assurance and governance (`assurance/`)

**Live status surfaces** (kept current; everything else defers to these):

- [`assurance/release_gates.md`](assurance/release_gates.md) — gate register + elevation record
- [`assurance/remediation_register.yaml`](assurance/remediation_register.yaml) — REM-item register
- [`assurance/claim_register_v1.yaml`](assurance/claim_register_v1.yaml) · [`claim_register.md`](claim_register.md) · [`claim_evidence_matrix.md`](claim_evidence_matrix.md)

Process and audits: [`assurance/evidence_levels.md`](assurance/evidence_levels.md) ·
[`assurance/statistical_analysis_plan.md`](assurance/statistical_analysis_plan.md) ·
[`assurance/reproducibility_scorecard_v1.md`](assurance/reproducibility_scorecard_v1.md) ·
[`assurance/rbac_policy_v1.md`](assurance/rbac_policy_v1.md) ·
[`assurance/rbac_design_v1.md`](assurance/rbac_design_v1.md) ·
[`assurance/external_security_audit_v1.md`](assurance/external_security_audit_v1.md) ·
[`assurance/red_team_plan_v1.md`](assurance/red_team_plan_v1.md) ·
[`assurance/independent_review_protocol_v1.md`](assurance/independent_review_protocol_v1.md).

Historical snapshots (banner-marked, preserved unedited):
`assurance/operation_baseline_2026_06_30.md`, `assurance/paper_alignment_2026-06-30.md`,
`assurance/operation_master_plan_v1.md`, `assurance/product_strategy_v1.md`,
`assurance/threat_model_v1.md`, `assurance/simulated_hostile_review_v1.md`,
`researchpapers/`.

Compliance mappings: [`governance/nist_ai_rmf_mapping.md`](governance/nist_ai_rmf_mapping.md) ·
[`security/owasp_genai_mapping.md`](security/owasp_genai_mapping.md) ·
[`security/pre-deployment-review.md`](security/pre-deployment-review.md) ·
[`enterprise/togaf-enterprise-rollout-plan.md`](enterprise/togaf-enterprise-rollout-plan.md).

## Evidence and benchmarks

- [`empirical_evidence_record.md`](empirical_evidence_record.md) — v4 statistical proof pack (N=302/N=544)
- [`results_snapshot.md`](results_snapshot.md) — canonical results snapshot
- Tool-call: [`toolcall_benchmarks.md`](toolcall_benchmarks.md) · [`toolcall_consensus_benchmark_v2.md`](toolcall_consensus_benchmark_v2.md)
- AgentHarm: [`agentharm_live_benchmark.md`](agentharm_live_benchmark.md) · [`agentharm_trimode_benchmark.md`](agentharm_trimode_benchmark.md) · [`claim_hygiene.md`](claim_hygiene.md)
- Domain/live: [`domain_benchmark.md`](domain_benchmark.md) · [`live_benchmark.md`](live_benchmark.md)
- Statistics: [`stat_tests.md`](stat_tests.md) · [`credibility_pack_repro.md`](credibility_pack_repro.md) · [`reproducibility.md`](reproducibility.md) (audit schema)
- Validation plans: [`11-benchmark-validation-plan.md`](11-benchmark-validation-plan.md) · [`EXTERNAL_VALIDATION_PLAN.md`](EXTERNAL_VALIDATION_PLAN.md) · [`external-review.md`](external-review.md) · [`review_checklist.md`](review_checklist.md) · [`external_validation_report_template.md`](external_validation_report_template.md)
- Experiments detail: [`experiments/`](experiments/) (experiment3–5; experiments 1–2 are covered in [`03-experiments.md`](03-experiments.md))
- Thermodynamics method docs: [`thermodynamics/`](thermodynamics/) (claim ledger, limitations, runtime policy, temperature estimator) · [`claims/thermodynamics_claims.yaml`](claims/thermodynamics_claims.yaml)

## AROMER (experimental learning layer)

[`quickstart_aromer.md`](quickstart_aromer.md) ·
[`aromer_learning_evidence_v1.md`](aromer_learning_evidence_v1.md) ·
[`REMORA_AROMER_MASTER_DOCUMENT.md`](REMORA_AROMER_MASTER_DOCUMENT.md) (authoritative technical reference) ·
[`REMORA_AROMER_FINAL_REPORT.md`](REMORA_AROMER_FINAL_REPORT.md).
AROMER metrics are not evidence for the core governance engine — see README
Limitations.

## Integrations and operations

- MCP: [`mcp-integration.md`](mcp-integration.md) · agent hook: [`agent_tool_hook.md`](agent_tool_hook.md)
- Oracles: [`rag_oracle.md`](rag_oracle.md) · [`cloudflare_workers_ai.md`](cloudflare_workers_ai.md) · [`knowledge_domains.md`](knowledge_domains.md)
- Cyber: [`cyber_evidence_layer.md`](cyber_evidence_layer.md) · [`go_star_bridge.md`](go_star_bridge.md) · [`gostar_integration.md`](gostar_integration.md)
- Deployment: [`deployment/azure-reference-architecture.md`](deployment/azure-reference-architecture.md) · [`deployment/onprem-airgapped.md`](deployment/onprem-airgapped.md)
- Policy cookbook: [`policy_cookbook/`](policy_cookbook/)
- Use cases: [`use-cases/`](use-cases/) (sector scenarios 01–07)

## Research notes and proposals

[`research/`](research/) (causal consequence gating, governance intelligence
layer, misspecification-aware governance, policy generalization risk) ·
[`causal_policy_explanations.md`](causal_policy_explanations.md) ·
[`theoretical_foundations_proposals_v1.md`](theoretical_foundations_proposals_v1.md)
(PROPOSED frameworks — roadmap, not implemented claims).

## Meta

[`AI_USE.md`](AI_USE.md) — AI-assisted development disclosure ·
[`authorship_evidence_report.md`](authorship_evidence_report.md) ·
[`archive/`](archive/) — superseded documents, do not cite.

---

**Conventions.** One live status surface per fact (gates → `release_gates.md`;
claims → claim registers; current metrics → repository README). Dated
snapshots carry a `HISTORICAL SNAPSHOT` banner and are never edited.
Duplicate topics resolve to the numbered series as canonical; the loose
files (`claim_hygiene.md`, `related_work.md`, `benchmark_validation_plan.md`)
are forwarding stubs kept so older links and tooling paths still resolve.
New documents must be added to this index.
