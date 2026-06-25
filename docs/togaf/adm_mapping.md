# TOGAF ADM Phase Mapping — REMORA AI Action Governance

**Status:** draft — not independently audited.
**Audience:** Enterprise architects conducting ADM cycles for AI agent deployment programmes.
**Companion documents:** [`architecture_building_block.md`](architecture_building_block.md),
[`enterprise/production-readiness.md`](../../enterprise/production-readiness.md),
[`architecture_contract_template.md`](architecture_contract_template.md)

---

## Overview

The TOGAF Architecture Development Method (ADM) is a cyclic process for developing,
implementing, and governing enterprise architecture across Business, Data, Application,
and Technology domains. This document maps REMORA's artefacts, capabilities, and gaps
to each ADM phase so that enterprise architecture teams can use REMORA as a governance
building block within an ongoing ADM programme.

REMORA is most relevant to programmes that involve:
- deploying autonomous AI agents in enterprise environments
- governing AI-driven tool calls against production systems
- establishing human oversight of AI-initiated actions
- creating an auditable record of AI governance decisions

---

## ADM Phase Mapping

### Preliminary Phase — Architecture Preparation

**What REMORA contributes:**

The Preliminary phase establishes the architecture framework, governance structures,
and principles that will guide all subsequent ADM phases. REMORA introduces two
critical inputs to this phase:

1. **Fail-closed as a governing principle.** The absence of policy or evidence is not
   a reason to permit an action — it is a reason to block or escalate it. This inverts
   the default permissive stance of most agent frameworks.

2. **Shadow Mode as the mandatory adoption entry point.** Any AI agent workflow must
   operate in observe-only mode before enforcement is enabled. This ensures that
   governance is calibrated before it becomes operational.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Architecture principles | [`architecture_principles.md`](architecture_principles.md) | Needs formal adoption as organisational principles |
| Governance controls | `enterprise/threat-model.md`, `enterprise/production-readiness.md` | No formal TOGAF capability definition or governance charter yet |
| Stakeholder map | [`architecture_building_block.md`](architecture_building_block.md) §7 | Needs mapping to the specific organisation's structure |
| Repository of Architecture | This TOGAF package | Needs uploading to the organisation's architecture repository tool |

---

### Requirements Management — Continuous Cross-Phase Function

**What REMORA contributes:**

Requirements Management is continuous across all ADM phases. REMORA contributes
a structured feedback loop:

- Shadow Mode replay data surfaces previously unknown action patterns
- Review queue outcomes identify policy gaps and false positives
- Golden set regression catches policy regressions before deployment
- Observability metrics (decision latency, escalation rate, audit completeness)
  flow back as quality requirements

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Continuous requirements input | `enterprise/observability.md`, `remora/shadow/replay.py` | No formal requirements log or traceability matrix |
| Policy change requirements | Golden set regression, replay reports | Policy lifecycle tooling not yet shipped |

---

### Phase A — Architecture Vision

**What REMORA contributes:**

Phase A establishes the high-level vision and business case for the architecture
engagement. For AI agent governance, REMORA contributes:

- A clear problem statement: agents can execute actions without oversight, causing
  harm, compliance failures, and audit gaps.
- A vision statement: *"AI agent actions cannot execute in enterprise environments
  unless policy, evidence, risk controls, and — where required — human approval
  permit them."*
- A measurable target state: zero critical autonomous executions in production,
  full audit trail, measurable reduction in unsafe actions vs. baseline.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Architecture Vision document | `README.md`, `enterprise/architecture.md`, [`remora_togaf_positioning.md`](remora_togaf_positioning.md) | No standalone C-level one-pager or business case with financial impact |
| Stakeholder concerns | [`architecture_building_block.md`](architecture_building_block.md) §7 | Needs organisation-specific stakeholder analysis |
| Capability assessment | [`architecture_building_block.md`](architecture_building_block.md) | Needs baseline capability assessment for the specific organisation |

---

### Phase B — Business Architecture

**What REMORA contributes:**

Phase B defines the business processes, roles, and information flows that govern AI
agent actions. REMORA's business architecture contributions:

- **Process:** Agent action governance — the process by which a proposed action is
  evaluated, decided, and — if required — escalated to a human approver.
- **Roles:** Platform owner, domain approver, security architect, compliance owner,
  SOC analyst, audit reviewer.
- **Authority boundaries:** Which roles can approve which risk tiers; two-person rules
  for critical actions.
- **Escalation paths:** From automated ACCEPT through to ESCALATE with defined SLAs
  at each tier.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Business process model | `enterprise/human-approval-workflow.md` | Needs BPMN or equivalent notation for the specific organisation |
| Role definitions | `enterprise/human-approval-workflow.md`, `enterprise/policy-model.md` | Needs RACI and organisational mapping |
| Authority boundaries | `enterprise/policy-model.md`, `enterprise/risk-profiles.yaml` | Needs formal delegation of authority documentation |
| Escalation SLAs | `enterprise/human-approval-workflow.md` | Needs organisation-specific SLA targets and review capacity planning |

---

### Phase C — Information Systems Architecture

**C1: Data Architecture**

REMORA's primary data architecture contribution is the `DecisionEnvelope` — the canonical
audit data contract. It records the complete decision context and must be treated as a
critical enterprise data asset subject to classification, retention policy, and access controls.

| Data Entity | Location | Classification | Gap |
|---|---|---|---|
| `DecisionEnvelope` | `remora/governance/envelope.py`, control plane store | Audit / compliance | Missing: `tenant_id`, `actor_identity`, `policy_bundle_hash`, `data_classification`, `retention_policy` |
| Approval records | Control plane store | Compliance / legal hold | Missing: `approver_identity` OIDC binding |
| Shadow Mode action logs | Control plane store | Operational | Retention policy undefined |
| Golden sets | Control plane store | Operational / testing | Governance process undefined |
| Evidence provenance records | Evidence connector layer | Operational | Source policy not formalised |
| Policy bundles | Control plane store | Configuration / compliance | Signing and hash not yet implemented |

**C2: Application Architecture**

| Application Component | REMORA Realisation | Gap |
|---|---|---|
| Governance API | `servers/api.py` | No OIDC/SAML in reference implementation |
| Policy Engine | `remora/policy/decision_engine.py` | No central policy bundle management UI |
| Audit contract | `remora/governance/envelope.py` | Missing enterprise fields (see §2.3 of SBB doc) |
| Adapter Layer | `remora/adapters/action_gate.py` + runtime examples | No certified adapters for enterprise-grade runtimes |
| Control Plane Store | `remora/adapters/storage/control_plane.py` | No HA/DR configuration documented |
| Shadow Replay | `remora/shadow/replay.py` | No UI for reviewer-facing replay |
| Review Queue | `enterprise/human-approval-workflow.md` | No reference integration with enterprise ticketing systems |

---

### Phase D — Technology Architecture

**What REMORA contributes:**

Phase D defines the technology components, infrastructure, and deployment topology
that realise the application and data architectures from Phase C.

| Technology Component | REMORA Evidence | Gap |
|---|---|---|
| API runtime | `servers/api.py` (FastAPI/Uvicorn) | No Kubernetes manifests or Helm chart shipped |
| Persistent store | `remora/adapters/storage/control_plane.py` (Postgres) | No HA/DR or backup runbook |
| Observability | `enterprise/observability.md` | No reference OTel configuration shipped |
| Secrets management | `enterprise/deployment-runbook.md` | No secrets manager integration pattern |
| Network zoning | [`deployment_architecture.md`](deployment_architecture.md) | Blueprint only — no Terraform/IaC shipped |
| IdP integration | Documented requirement | Not implemented in reference code |
| Tool Executor | `remora/adapters/action_gate.py` | No sandboxed execution environment shipped |
| SIEM integration | `enterprise/observability.md` | No reference SIEM connector shipped |

See [`deployment_architecture.md`](deployment_architecture.md) for full topology blueprints.

---

### Phase E — Opportunities and Solutions

**What REMORA contributes:**

Phase E identifies solution options and selects the implementation approach.
For REMORA, the key decision is the transition architecture: how to move from
the current state (no governance) to the target state (full enforcement).

REMORA's built-in Shadow Mode provides a uniquely low-risk entry point that
most governance frameworks cannot offer: the organisation can observe all
governance decisions without any blocking effect, building confidence and
calibrating policy before enforcement begins.

| Transition Option | Description | Risk | Recommendation |
|---|---|---|---|
| Shadow Mode first | Observe all actions for 2–4 weeks; no blocking | Low | **Recommended for all deployments** |
| Direct enforcement | Enable blocking immediately | High | Not recommended |
| Human-gated only | Route all decisions to human approval | Medium | Viable for very low-volume, high-criticality workflows |
| Selective enforcement | Enable blocking for a single, well-understood tool | Low-Medium | Good second step after Shadow Mode |

**Transition architectures:** See [`migration_plan.md`](migration_plan.md) for T0–T2
transition diagrams.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Options assessment | `enterprise/production-readiness.md` Stage 0–4 | No formal options paper with cost/risk comparison |
| Transition architectures | [`migration_plan.md`](migration_plan.md) | Timeline is indicative; needs calibration to organisation's context |
| Implementation approach | Shadow Mode → human-gated → limited enforcement | Confirmed by `enterprise/production-readiness.md` |

---

### Phase F — Migration Planning

**What REMORA contributes:**

Phase F produces a prioritised, sequenced migration plan. REMORA's staged adoption
model maps directly onto this phase.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Migration roadmap | [`migration_plan.md`](migration_plan.md) | Indicative timeline; needs programme manager calibration |
| Work packages | [`enterprise_pilot_playbook.md`](enterprise_pilot_playbook.md) §0–5 | Needs resource and budget estimation |
| Transition architecture sign-off | [`architecture_contract_template.md`](architecture_contract_template.md) | Needs organisation-specific completion |
| Exit criteria | [`enterprise_pilot_playbook.md`](enterprise_pilot_playbook.md) §5 | Needs threshold values agreed by stakeholders |

---

### Phase G — Implementation Governance

**What REMORA contributes:**

Phase G ensures that implementation conforms to the architecture. REMORA contributes
an architecture contract template and a set of runtime governance controls.

The fail-closed conditions in `servers/api.py` are themselves a form of implementation
governance: REMORA will not enter production enforcement mode unless the required
infrastructure (auth, persistent store, non-mock backend) is in place.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Architecture Contract | [`architecture_contract_template.md`](architecture_contract_template.md) | Needs organisation-specific completion and sign-off |
| Compliance assessment | [`compliance_assessment_template.md`](compliance_assessment_template.md) | Needs completion against organisation's regulatory baseline |
| Implementation checklist | `enterprise/production-readiness.md` Stage 0–4 | Comprehensive but needs formal acceptance package |
| Waiver / exception process | [`architecture_contract_template.md`](architecture_contract_template.md) §Exceptions | Process defined; needs integration with organisation's change governance |
| Non-compliance escalation | `enterprise/threat-model.md` | Needs organisation-specific escalation path |

---

### Phase H — Architecture Change Management

**What REMORA contributes:**

Phase H ensures that the architecture continues to evolve in a controlled manner.
REMORA's key contributions to this phase are:

- **Policy lifecycle management:** Changes to policy bundles must be tested against
  the golden set before deployment. Replay ensures that new policy does not alter
  decisions on known-good cases.
- **Drift detection:** Observability metrics surface changes in agent behaviour that
  may indicate that policy has become stale or that the agent runtime has changed.
- **Continuous improvement loop:** Shadow Mode replay, golden set regression, and
  review queue outcomes feed back into policy calibration.

| Sub-deliverable | REMORA Artefact | Gap |
|---|---|---|
| Change governance for policy | `remora/shadow/replay.py`, golden set | No formal CAB/release policy process yet |
| Architecture compliance monitoring | `enterprise/observability.md` | Dashboards and alert rules not yet shipped |
| Technology change assessment | `enterprise/deployment-runbook.md` | Runbook covers deployment; change impact assessment process undefined |
| Lesson learning | Shadow Mode replay, review findings | No formalised lesson-learning process |

---

## Summary of Gaps by Phase

| Phase | Most Critical Gap |
|---|---|
| Preliminary | Formal TOGAF capability definition and governance charter |
| Requirements Management | Formal requirements log and traceability matrix |
| Phase A | C-level business case with quantified impact |
| Phase B | RACI and delegation of authority documentation |
| Phase C | Envelope enterprise fields; OIDC binding; data classification |
| Phase D | Kubernetes/IaC artefacts; HA/DR runbook; secrets management pattern |
| Phase E | Formal options assessment with cost/risk comparison |
| Phase F | Resource and budget estimation for migration phases |
| Phase G | Architecture contract completion; formal acceptance package |
| Phase H | CAB/release policy for policy bundle changes; automated drift detection |
