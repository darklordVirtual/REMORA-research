# Risk Register — REMORA Enterprise Adoption

**Status:** draft — not independently audited. Review and assign ownership before use.
**Audience:** Risk managers, security architects, enterprise architects.
**Normative support:** EU AI Act (Art. 9 — risk management system),
ISO/IEC 42001 (Clause 6.1 — actions to address AI risks and opportunities).
**Repository evidence:** `enterprise/threat-model.md`, `enterprise/production-readiness.md`,
`enterprise/observability.md`, `docs/decision_envelope_audit.md`
**Companion documents:** [`architecture_contract_template.md`](architecture_contract_template.md),
[`compliance_assessment_template.md`](compliance_assessment_template.md)

---

## Risk Scoring Convention

| Score | Likelihood | Impact |
|---|---|---|
| 1 — Low | Unlikely under normal conditions | Localised; recoverable quickly |
| 2 — Medium | Possible under certain conditions | Significant; recovery requires effort |
| 3 — High | Probable if no mitigations in place | Severe; major recovery effort or regulatory exposure |

**Net risk = Likelihood × Impact (before mitigation)**

---

## Risk Register

### R01 — Bypass of Governance Gateway

| Field | Detail |
|---|---|
| **Category** | Security |
| **Description** | An agent runtime or tool consumer calls the Tool Executor directly, bypassing REMORA entirely. This can occur if the Tool Executor has a publicly accessible endpoint, if the agent runtime has direct credentials to the target system, or if a developer bypasses the adapter for convenience. |
| **Likelihood** | 3 — High (tool executors are commonly exposed directly during development) |
| **Impact** | 3 — High (unsafe action executes with no governance, no audit trail) |
| **Net Risk** | 9 — Critical |
| **Mitigations** | Enforce network zoning: Tool Executor must only accept requests carrying a valid REMORA clearance token. Monitor for direct tool calls in SIEM. Remove all direct credentials from agent runtimes. Test bypass scenario during Shadow Mode setup. |
| **Residual Risk** | 2 — Medium (after network zoning and monitoring) |
| **Owner** | Security Architect |
| **Status** | Open |

---

### R02 — Incomplete Audit Contract

| Field | Detail |
|---|---|
| **Category** | Compliance |
| **Description** | The `DecisionEnvelope` does not include all fields required for enterprise audit and compliance: `tenant_id`, `actor_identity`, `policy_bundle_hash`, `approver_identity`, `data_classification`, `retention_policy`, and optionally a detached signature. This means the organisation cannot prove which policy governed a decision, who made an approval, or what data classification applied. |
| **Likelihood** | 3 — High (these gaps are confirmed in `docs/decision_envelope_audit.md`) |
| **Impact** | 3 — High (audit failures in regulated environments; non-repudiation impossible) |
| **Net Risk** | 9 — Critical |
| **Mitigations** | Implement envelope v3 with all missing fields before pilot in regulated environments. Intermediate mitigation: store `tenant_id` and `actor_identity` in a companion record linked by `envelope_id`. Sign policy bundles and embed hash. |
| **Residual Risk** | 1 — Low (after envelope v3 implementation) |
| **Owner** | Platform Owner |
| **Status** | Open — `docs/decision_envelope_audit.md` is the remediation tracking document |

---

### R03 — Weak Identity Binding for Approvals

| Field | Detail |
|---|---|
| **Category** | Security / Compliance |
| **Description** | Human approvals in the review queue are not bound to an IdP-verified identity in the current reference implementation. An approval record may not carry the approver's OIDC token claim, making non-repudiation impossible. |
| **Likelihood** | 3 — High (OIDC integration is not in reference implementation) |
| **Impact** | 2 — Medium (approval process exists but non-repudiation is weak) |
| **Net Risk** | 6 — High |
| **Mitigations** | Implement OIDC/SAML authentication for the review queue interface. Bind the approver's identity claim to the approval record at write time. Approval records must be immutable after creation. |
| **Residual Risk** | 1 — Low (after OIDC integration) |
| **Owner** | Platform Owner |
| **Status** | Open |

---

### R04 — Review Queue Overload

| Field | Detail |
|---|---|
| **Category** | Operational |
| **Description** | An unexpectedly high VERIFY or ESCALATE rate floods the review queue, exceeding the capacity of available approvers. This causes reviews to breach SLA, creates a bottleneck, and may lead to approvers rubber-stamping decisions to clear the queue. |
| **Likelihood** | 2 — Medium (common in initial deployments with uncalibrated risk profiles) |
| **Impact** | 2 — Medium (governance quality degrades; pilot may stall) |
| **Net Risk** | 4 — Medium |
| **Mitigations** | Start with a narrow scope and well-bounded workflows. Monitor review queue depth and SLA adherence from day one. Define a maximum review burden threshold (e.g., < 10% of decisions requiring human review in steady state). Tune policy to reduce unnecessary VERIFY outcomes. Establish an overflow escalation path for sustained high volume. |
| **Residual Risk** | 1 — Low (with proactive monitoring and calibration) |
| **Owner** | Platform Owner + Domain Approvers |
| **Status** | Open |

---

### R05 — Insufficient Evidence Provenance

| Field | Detail |
|---|---|
| **Category** | Compliance |
| **Description** | VERIFY decisions are made based on evidence from RAG or knowledge base connectors, but the source, freshness, and authority of that evidence are not formally recorded in the `DecisionEnvelope`. In a regulated context, a governance decision based on stale or unattributed evidence may not be defensible. |
| **Likelihood** | 2 — Medium (evidence provenance fields are not formalised) |
| **Impact** | 2 — Medium (VERIFY decisions are weakly supported; audit quality suffers) |
| **Net Risk** | 4 — Medium |
| **Mitigations** | Formalise evidence provenance fields: source identifier, retrieval timestamp, confidence score, and authority class. Define a freshness policy: maximum acceptable evidence age per evidence class. Include provenance metadata in `DecisionEnvelope`. |
| **Residual Risk** | 1 — Low (after provenance implementation) |
| **Owner** | Platform Owner |
| **Status** | Open |

---

### R06 — Third-Party Model and Evidence Service Risk

| Field | Detail |
|---|---|
| **Category** | Legal / Operational |
| **Description** | External AI model providers and RAG/evidence services process data that may be subject to data residency, confidentiality, or AI Act obligations. The organisation may be unaware of how these providers handle data, whether they use it for training, or whether they are subject to the same regulatory obligations. |
| **Likelihood** | 2 — Medium (most organisations use external AI services without full due diligence) |
| **Impact** | 3 — High (data sovereignty breach; AI Act compliance failure; supplier dependency) |
| **Net Risk** | 6 — High |
| **Mitigations** | Conduct supplier due diligence before pilot. Create a supplier inventory documenting: provider name, data categories processed, data residency, AI Act role, contractual controls. Evaluate on-premises or sovereign cloud alternatives for high-sensitivity workloads. |
| **Residual Risk** | 2 — Medium (after due diligence; full mitigation requires on-prem alternatives) |
| **Owner** | Compliance Owner + Platform Owner |
| **Status** | Open |

---

### R07 — Audit Store Failure or Log Chain Break

| Field | Detail |
|---|---|
| **Category** | Operational / Security |
| **Description** | The audit store becomes unavailable, a write fails silently, or the hash chain is broken. This results in a gap in the audit trail — governance decisions occurred but were not recorded — potentially invalidating the organisation's compliance posture. |
| **Likelihood** | 1 — Low (with properly configured persistent storage) |
| **Impact** | 3 — High (compliance gap; replay impossible for affected period) |
| **Net Risk** | 3 — Medium |
| **Mitigations** | Use a durable, backed-up Postgres instance. Implement write-ahead logging. Configure REMORA to fail-closed (ESCALATE or ABSTAIN) for high-risk actions when the audit store is unavailable. Queue decision records for retry on transient write failure. Test store failure scenarios in staging. |
| **Residual Risk** | 1 — Low (with proper storage configuration and testing) |
| **Owner** | Platform Owner |
| **Status** | Open |

---

### R08 — Policy Drift Without Governance

| Field | Detail |
|---|---|
| **Category** | Operational |
| **Description** | A policy bundle is updated in production without going through golden set regression, change governance, or reviewer sign-off. The result is that live governance decisions are made against an untested, unreviewed policy version, possibly causing unsafe acceptance of previously blocked actions. |
| **Likelihood** | 2 — Medium (common in organisations without policy CI/CD maturity) |
| **Impact** | 3 — High (fundamental governance control failure) |
| **Net Risk** | 6 — High |
| **Mitigations** | Enforce policy bundle signing: unsigned bundles must not be loaded in production. Wire golden set regression to the CI/CD pipeline as a mandatory gate. Require change governance (CAB or equivalent) approval for any policy deployment. Monitor for policy version changes in SIEM. |
| **Residual Risk** | 1 — Low (after CI/CD and signing controls) |
| **Owner** | Security Architect + Platform Owner |
| **Status** | Open |

---

### R09 — CI/CD Pipeline Without Governance Quality Gates

| Field | Detail |
|---|---|
| **Category** | Engineering / Operational |
| **Description** | Changes to REMORA (policy engine, adapter layer, API) are deployed without running the governance test suite, golden set regression, or claim consistency checks. A regression in the policy engine or envelope service goes undetected until it manifests in production. |
| **Likelihood** | 2 — Medium |
| **Impact** | 2 — Medium (silent regression in governance decisions) |
| **Net Risk** | 4 — Medium |
| **Mitigations** | Require the following as mandatory CI gates before any deployment: `pytest tests/test_policy_curated_suite.py` (304 cases), `pytest tests/test_policy_invariants_prop.py`, `python scripts/shadow_replay.py --golden-set`, `python scripts/check_claim_consistency.py`. Block merge on failure of any gate. |
| **Residual Risk** | 1 — Low (after CI gates implemented) |
| **Owner** | Platform Owner |
| **Status** | Open |

---

### R10 — PII and Data Classification Not Defined

| Field | Detail |
|---|---|
| **Category** | Legal / Privacy |
| **Description** | Agent actions may involve personal data. If `data_classification` is not present in the `DecisionEnvelope`, and PII is not redacted before storage, the audit store may contain personal data subject to GDPR, with no defined retention period or access controls. |
| **Likelihood** | 3 — High (audit records routinely capture action arguments which may contain PII) |
| **Impact** | 3 — High (GDPR violation; fines; mandatory breach notification) |
| **Net Risk** | 9 — Critical |
| **Mitigations** | Conduct a data flow assessment to identify which action arguments may contain PII. Implement field-level redaction in the adapter layer for PII before the argument is written to the envelope. Add `data_classification` and `retention_policy` fields to `DecisionEnvelope`. Define retention periods and implement automated purging. Conduct a DPIA before deploying any workflow that processes personal data. |
| **Residual Risk** | 2 — Medium (after redaction and classification controls; DPIA required) |
| **Owner** | DPO + Platform Owner |
| **Status** | Open — **highest priority before processing personal data** |

---

### R11 — Unclear Deployer / Provider Role Under AI Act

| Field | Detail |
|---|---|
| **Category** | Legal / Regulatory |
| **Description** | If the organisation both builds the agent workflow and deploys it to users, it may carry both provider and deployer obligations under the EU AI Act. These obligations differ significantly, particularly around conformity assessment, technical documentation, and registration requirements for high-risk AI systems. |
| **Likelihood** | 2 — Medium |
| **Impact** | 3 — High (incorrect role determination leads to compliance gaps) |
| **Net Risk** | 6 — High |
| **Mitigations** | Engage legal counsel to determine the organisation's role(s) under the AI Act for each workflow. Document the determination and update the compliance assessment. Implement obligations appropriate to the determined role. Note: most organisations deploying REMORA-governed workflows are deployers, not providers. |
| **Residual Risk** | 1 — Low (after legal determination and documented obligations) |
| **Owner** | Compliance Owner + Legal |
| **Status** | Open |

---

### R12 — Agent Runtime Behavioural Drift

| Field | Detail |
|---|---|
| **Category** | Security / Compliance |
| **Description** | The agent runtime's behaviour changes over time — due to model updates, prompt changes, or tool changes — causing previously safe action patterns to shift toward higher-risk categories. The existing policy, calibrated against an older behaviour baseline, no longer accurately reflects the current risk profile. |
| **Likelihood** | 2 — Medium (model and prompt changes are routine) |
| **Impact** | 2 — Medium (policy becomes stale; governance accuracy degrades) |
| **Net Risk** | 4 — Medium |
| **Mitigations** | Define behavioural drift metrics (change in escalation rate, abstain rate, action distribution). Alert on significant drift. Schedule periodic policy reviews (quarterly or on each major model/prompt update). Run Shadow Mode replay against updated baselines after significant changes. |
| **Residual Risk** | 1 — Low (with monitoring and review schedule) |
| **Owner** | Platform Owner |
| **Status** | Open |

---

## Risk Summary Matrix

| Risk | Net Score | Priority | Owner |
|---|:---:|---|---|
| R01 Bypass of governance gateway | 9 — Critical | 1 | Security Architect |
| R02 Incomplete audit contract | 9 — Critical | 1 | Platform Owner |
| R10 PII not classified or redacted | 9 — Critical | 1 | DPO |
| R03 Weak identity binding for approvals | 6 — High | 2 | Platform Owner |
| R06 Third-party service risk | 6 — High | 2 | Compliance Owner |
| R08 Policy drift | 6 — High | 2 | Security Architect |
| R11 AI Act role ambiguity | 6 — High | 2 | Legal |
| R04 Review queue overload | 4 — Medium | 3 | Platform Owner |
| R05 Evidence provenance | 4 — Medium | 3 | Platform Owner |
| R09 CI/CD without quality gates | 4 — Medium | 3 | Platform Owner |
| R12 Agent behavioural drift | 4 — Medium | 3 | Platform Owner |
| R07 Audit store failure | 3 — Medium | 4 | Platform Owner |

---

## Immediate Actions (before Shadow Mode)

1. **R01** — Verify that the Tool Executor is in an isolated network zone before any deployment.
2. **R10** — Conduct data flow assessment for all enrolled workflows; implement PII redaction.
3. **R02** — Determine whether regulated-environment deployment requires envelope v3 before pilot.
4. **R11** — Obtain legal determination of AI Act role before committing to compliance scope.
