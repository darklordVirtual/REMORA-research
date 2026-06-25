# Architecture Building Block — AI Action Governance Capability

**Status:** draft — not independently audited.
**TOGAF Type:** Architecture Building Block (ABB) — generic, implementation-independent.
**Realised by:** [`solution_building_block.md`](solution_building_block.md)
**Repository evidence:** `remora/policy/decision_engine.py`, `remora/governance/envelope.py`,
`remora/shadow/replay.py`, `enterprise/policy-model.md`, `enterprise/threat-model.md`,
`enterprise/human-approval-workflow.md`, `enterprise/risk-profiles.yaml`

---

## 1. Name

**AI Action Governance Capability**

---

## 2. Purpose

Ensure that autonomous AI agents cannot execute actions against enterprise systems,
data, or external services without an explicit policy evaluation, sufficient evidence,
an appropriate risk-level clearance, and — where the risk profile requires it — a named
human authorisation.

The capability answers the question: *"Should this proposed action be permitted to execute,
and under what conditions?"* before any side-effects occur.

---

## 3. Business Goals

| Goal | Description |
|---|---|
| Reduce unsafe agent actions | Prevent agents from executing actions that violate policy, lack evidence, or exceed acceptable risk |
| Protect production environments | Ensure critical and high-risk mutations require human approval before execution |
| Increase trust in agent automation | Provide a verifiable, replayable record of every governance decision |
| Establish an audit trail | Generate a complete, tamper-sensitive log for compliance and forensic purposes |
| Enable controlled adoption | Allow organisations to observe and calibrate governance before enforcement begins |
| Reduce autonomous blast radius | Limit the scope of what agents can do without oversight |
| Support regulatory compliance | Provide controls relevant to EU AI Act, ISO/IEC 42001, GDPR, and sector frameworks |

---

## 4. Core Capabilities

| Capability | Description |
|---|---|
| **Pre-execution action gating** | Intercept and evaluate every proposed agent action before tool dispatch |
| **Risk-based policy routing** | Route actions to accept, verify, abstain, or escalate based on risk profile and policy |
| **Metadata-misspecification hardening** | Deterministic, opt-in pre-policy enrichment (v0.9.0): fail-closed label normalization, action-semantics extraction, misspecification, blast-radius, and fleet-level generalization signals under a strengthen-only rule — caller-supplied labels are not trusted blindly |
| **Evidence-based decision support** | Evaluate evidence sufficiency before recommending verify or abstain |
| **Human approval routing** | Route high- and critical-risk actions to a named human approver |
| **Tamper-evident audit trail** | Generate a `DecisionEnvelope` with hash chain for every decision |
| **Shadow Mode observation** | Operate in observe-only mode before enforcement is enabled |
| **Replay and auditability** | Reproduce past decisions from logged envelopes for review and forensic purposes |
| **Multi-runtime integration** | Integrate with OpenAI tool calling, LangGraph, MCP, and custom agent loops |
| **Tenant isolation** | Scope decisions, policy, and audit data by tenant |
| **Continuous improvement** | Feed telemetry, golden sets, and review findings back into policy calibration |

---

## 5. Inputs

| Input | Description | Source |
|---|---|---|
| Proposed agent action | The action the agent is attempting to perform | Agent runtime |
| Action context and arguments | Parameters, target, environment, and intent | Agent runtime |
| Risk level | Pre-classified risk tier for the action type | Policy configuration |
| Target environment | Production, staging, sandbox, or external | Environment metadata |
| Tenant and actor identity | Who is requesting and in whose context | IdP / authentication layer |
| Policy and evidence signals | Current policy state, evidence freshness, oracle signals | Policy engine, evidence connectors |
| Injection / contradiction alerts | Warnings about potential prompt injection or conflicting signals | Safety layer |
| Tool schema | Expected argument schema for the target tool | Tool allowlist |

---

## 6. Outputs

| Output | Description | Consumer |
|---|---|---|
| Decision outcome | ACCEPT / VERIFY / ABSTAIN / ESCALATE | Agent runtime, audit |
| `DecisionEnvelope` | Canonical audit contract with all decision metadata | Audit store, SIEM |
| Audit hash / hash chain | Tamper-sensitive integrity proof of the decision sequence | Replay engine, forensics |
| Human review requirements | Whether human approval is required and the SLA | Review queue |
| Evidence requirements | What additional evidence is needed for VERIFY outcomes | Evidence connectors |
| Allowed next steps | What the agent may do following this decision | Agent runtime |
| Rejection reason | Structured explanation for ABSTAIN and ESCALATE outcomes | Agent runtime, logging |

---

## 7. Stakeholders and Interests

| Stakeholder | Primary Interest |
|---|---|
| Business Owner | Agent automation is safe, controllable, and aligned with business policy |
| Enterprise Architect | Capability is integrated into the architecture programme and ADM |
| Security Architect | Controls are fail-closed, identity-bound, and independently auditable |
| Platform Engineer | Integration with existing runtimes is practical and well-documented |
| Domain Approver | Review interface is clear, actionable, and has a defined SLA |
| Compliance Owner | Audit records are complete, attributable, and meet retention requirements |
| SOC / Incident Response | Events are forwarded to SIEM; kill switch is available and tested |
| Audit / Assurance | Past decisions can be reproduced and validated from stored envelopes |
| Data Protection Officer | PII is redacted, classified, and subject to retention policy |

---

## 8. Architecture Requirements

| Requirement | Description | Priority |
|---|---|---|
| Fail-closed by default | In the absence of a valid policy or sufficient evidence, the default outcome must be VERIFY, ABSTAIN, or ESCALATE — never ACCEPT | Mandatory |
| No autonomous critical execution | Critical-risk production mutations must never execute without human approval | Mandatory |
| Audit by design | Every decision must produce a `DecisionEnvelope` — including ACCEPT | Mandatory |
| Policy before execution | No tool can be dispatched without a REMORA clearance | Mandatory |
| Tenant isolation | Policy, decisions, and audit data must be scoped by tenant | Mandatory |
| Evidence provenance | Evidence used in VERIFY decisions must record source type, freshness, and authority | Mandatory |
| Human approval is an authority boundary | Approval is not a UI feature — it is a binding authorisation with an identity, a timestamp, and a role | Mandatory |
| Governance and execution are separated | The control plane and tool executor must be distinct components | Mandatory |
| Replayability | Past decisions must be reproducible from stored envelopes | Mandatory |
| Observability and SLOs | Decision latency, escalation rate, abstain rate, and audit completeness must be measurable | Mandatory |
| Shadow Mode before enforcement | Any new workflow must operate in observe-only mode before blocking is enabled | Recommended |
| Change governance | Policy bundle changes must be gated by replay regression and golden set validation | Recommended |

---

## 9. Related Architecture Building Blocks

| ABB | Relationship |
|---|---|
| Identity and Access Governance | REMORA consumes identity signals for caller and approver attribution |
| Audit and Records Management | REMORA produces audit records that feed into this capability |
| Security Monitoring (SIEM) | REMORA forwards decision events as structured security telemetry |
| Policy-as-Code | REMORA's policy engine implements and enforces the organisation's policy-as-code artefacts |
| Human Approval Workflow | REMORA routes decisions requiring human judgement to this capability |
| Evidence and Knowledge Management | REMORA consumes evidence signals from RAG, knowledge bases, and oracles |
| Tool Governance | REMORA enforces the tool allowlist and schema validation |
| Change Management | Policy bundle changes flow through change management before deployment |

---

## 10. Success Criteria

| Criterion | Target |
|---|---|
| Critical autonomous executions in production | 0 |
| Audit completeness (decisions with complete envelope) | > 99% |
| False accept rate (incorrect ACCEPT for high/critical actions) | Below agreed threshold |
| Review burden (VERIFY + ESCALATE as % of total decisions) | Within agreed SLA capacity |
| Reduction in unsafe executions vs. baseline | Measurable and positive |
| Hash chain integrity | 100% of replayed envelopes pass verification |
| Shadow Mode coverage before enforcement | 100% of enrolled workflows |

---

## 11. Constraints and Assumptions

- The capability assumes agent runtimes can be instrumented to route actions through REMORA before dispatch.
- The capability does not define the content of policy — that is the responsibility of the deploying organisation.
- The capability is cloud-agnostic and can be deployed on-premises; specific infrastructure choices are out of scope for this ABB.
- The capability does not replace existing IAM, SIEM, DLP, or approval systems — it integrates with them.
