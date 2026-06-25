# REMORA TOGAF Enterprise Architecture Package

**Status:** draft — internal working document, not independently audited.
**Audience:** Enterprise architects, security architects, platform owners, compliance teams.
**Related framework mappings:** [`docs/governance/nist_ai_rmf_mapping.md`](../governance/nist_ai_rmf_mapping.md)

---

## Overview

This folder contains the TOGAF-aligned enterprise architecture package for REMORA.
It positions REMORA as an **AI Action Governance Capability** within the TOGAF Architecture
Development Method (ADM) and provides the artefacts needed to adopt it as part of an
enterprise architecture programme.

REMORA sits between agent runtimes and tool execution. Before an agent can run a tool
or perform an action, REMORA evaluates risk, policy, evidence, uncertainty, and environment,
and decides whether the action should **ACCEPT**, **VERIFY**, **ABSTAIN**, or **ESCALATE**.

---

## Document Index

| Document | Purpose | Audience |
|---|---|---|
| [remora_togaf_positioning.md](remora_togaf_positioning.md) | C-level one-pager: what REMORA is and where it fits in enterprise architecture | CTO, EA, CISO |
| [architecture_building_block.md](architecture_building_block.md) | ABB definition for AI Action Governance Capability | Enterprise architects |
| [solution_building_block.md](solution_building_block.md) | SBB: REMORA components as realisation of the ABB, with component diagram and gap analysis | Platform architects |
| [adm_mapping.md](adm_mapping.md) | TOGAF ADM phase-by-phase mapping with repo evidence and identified gaps | Enterprise architects |
| [architecture_principles.md](architecture_principles.md) | Governing principles for AI action governance, with derived design rules | Architects, leads |
| [archimate_view.md](archimate_view.md) | ArchiMate-style layered view (Motivation, Business, Application, Technology) in Mermaid | Enterprise architects |
| [architecture_contract_template.md](architecture_contract_template.md) | Reusable governance contract for enterprise AI agent deployments | EA, Security, Compliance |
| [compliance_assessment_template.md](compliance_assessment_template.md) | Assessment checklist covering EU AI Act and ISO/IEC 42001 control areas | Compliance, Legal |
| [enterprise_pilot_playbook.md](enterprise_pilot_playbook.md) | Phase-by-phase pilot guide from Shadow Mode through to limited enforcement | Platform teams |
| [migration_plan.md](migration_plan.md) | Gantt-style migration timeline with transition architectures and rollback strategy | Programme managers |
| [risk_register.md](risk_register.md) | Risk register for enterprise adoption with prioritised mitigations | Risk, Security |
| [deployment_architecture.md](deployment_architecture.md) | Cloud, hybrid, and on-premises deployment blueprints with network zoning | Infrastructure, Platform |

---

## Companion Documents in This Repository

| Document | Relevance |
|---|---|
| [`enterprise/architecture.md`](../../enterprise/architecture.md) | REMORA target architecture and component overview |
| [`enterprise/production-readiness.md`](../../enterprise/production-readiness.md) | Stage 0–4 production readiness checklist |
| [`enterprise/policy-model.md`](../../enterprise/policy-model.md) | Policy engine design, risk tiers, and decision routing |
| [`enterprise/human-approval-workflow.md`](../../enterprise/human-approval-workflow.md) | Human review and approval workflow design |
| [`enterprise/threat-model.md`](../../enterprise/threat-model.md) | Threat model for the governance control plane |
| [`enterprise/observability.md`](../../enterprise/observability.md) | Metrics, SLOs, and monitoring design |
| [`enterprise/deployment-runbook.md`](../../enterprise/deployment-runbook.md) | Operational runbook for deployment and rollback |
| [`enterprise/remora-control-plane.md`](../../enterprise/remora-control-plane.md) | Control plane storage and tenant isolation design |
| [`docs/decision_envelope_audit.md`](../decision_envelope_audit.md) | Audit of the DecisionEnvelope contract and identified gaps |
| [`docs/governance/nist_ai_rmf_mapping.md`](../governance/nist_ai_rmf_mapping.md) | NIST AI RMF 1.0 mapping (companion framework) |
| [`docs/deployment/azure-reference-architecture.md`](../deployment/azure-reference-architecture.md) | Azure-specific deployment reference |
| [`docs/deployment/onprem-airgapped.md`](../deployment/onprem-airgapped.md) | On-premises and air-gapped deployment guide |

---

## Reading Order

For an enterprise architecture engagement, the recommended reading order is:

1. `remora_togaf_positioning.md` — understand what REMORA is
2. `architecture_principles.md` — understand the governing constraints
3. `architecture_building_block.md` — understand the capability
4. `adm_mapping.md` — understand where it fits in your ADM cycle
5. `solution_building_block.md` — understand the implementation
6. `archimate_view.md` — visualise the architecture
7. `architecture_contract_template.md` — establish governance
8. `compliance_assessment_template.md` — assess regulatory alignment
9. `enterprise_pilot_playbook.md` — plan adoption
10. `migration_plan.md` — schedule the programme
11. `risk_register.md` — manage risk
12. `deployment_architecture.md` — design the infrastructure

---

## Key Caveats

- REMORA is **research-grade software**, not a production-certified product.
- All claims in these documents must be backed by artefacts in the repository (see [`docs/claim_hygiene.md`](../claim_hygiene.md)).
- This package does not replace IAM, SIEM, DLP, or organisational policy programmes.
- Identified gaps between the current implementation and enterprise requirements are explicitly noted in each document.
