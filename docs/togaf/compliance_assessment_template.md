# Compliance Assessment Template — REMORA Enterprise Deployment

**Status:** draft — not independently audited. Complete before use.
**Audience:** Compliance officers, legal counsel, DPOs, security architects.
**Normative references:**
- EU AI Act (Regulation (EU) 2024/1689) — risk-based regulation for AI systems in the EU/EEA.
- ISO/IEC 42001:2023 — AI Management System Standard for responsible AI governance across the lifecycle.
- GDPR (Regulation (EU) 2016/679) — data protection and privacy.
**Note:** This assessment template is jurisdiction-neutral. Organisations operating outside the EU/EEA
should substitute applicable national or sector-specific frameworks.

**Repository evidence:** `docs/decision_envelope_audit.md`, `enterprise/threat-model.md`,
`enterprise/observability.md`, `servers/api.py`, `remora/adapters/storage/control_plane.py`,
`enterprise/production-readiness.md`

---

## 1. Scoping Assessment

Before completing the control-area checklist, complete this scoping section to determine
which regulatory requirements apply and at what level.

### 1.1 AI Act Role Determination

| Question | Answer |
|---|---|
| Does the organisation develop, train, or fine-tune the AI model(s) used? | (yes / no) |
| Does the organisation integrate the AI model into a product or service? | (yes / no) |
| Does the organisation deploy the AI product/service to end users? | (yes / no) |

**Role determination:**

| Role | Applies? |
|---|---|
| Provider (develops/trains the model) | (yes / no) |
| Deployer (deploys to users) | (yes / no) |
| Importer / Distributor | (yes / no) |

**Notes:** Most organisations deploying REMORA-governed agent workflows will be **deployers**
under the AI Act. If the organisation also builds the agent or the underlying model, it may
also be a **provider**. The operator obligations differ significantly between these roles.

### 1.2 AI Act Risk Classification

| Agent Workflow | Sector | Risk Classification | Justification |
|---|---|---|---|
| (fill in) | (fill in) | (fill in: unacceptable / high / limited / minimal) | (fill in) |

**Reference:** AI Act Annex I (prohibited practices), Annex III (high-risk areas).
High-risk categories include: critical infrastructure, education, employment, essential services,
law enforcement, migration, administration of justice, democratic processes, and biometrics.

### 1.3 ISO/IEC 42001 Applicability

ISO/IEC 42001 applies to any organisation that develops, provides, or uses AI systems.
It is a management system standard — organisations self-certify or seek third-party
certification. Indicate intended use:

| Purpose | Applies? |
|---|---|
| Internal governance improvement | (yes / no) |
| Third-party certification | (yes / no) |
| Customer / procurement requirement | (yes / no) |

---

## 2. Control Area Assessment

### 2.1 Scope and Inventory

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C01 | All AI systems and agent workflows are inventoried | None (organisation must create) | `[ ]` | Create system inventory with systems, tools, data flows, affected persons |
| C02 | For each workflow: purpose, inputs, outputs, and affected persons are documented | Partial — examples and adapters document runtime patterns | `[ ]` | Create per-workflow documentation |
| C03 | Third-party AI models and evidence services are identified | Not consolidated | `[ ]` | Create supplier inventory |
| C04 | Data flows between agent, REMORA, and external services are mapped | Partial — `enterprise/architecture.md` | `[ ]` | Complete data flow diagram |

### 2.2 Governance and Accountability

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C05 | REMORA is formally designated as the AI action governance control point | Not formally designated — TOGAF package begins this process | `[ ]` | Obtain formal designation via architecture contract |
| C06 | Roles and responsibilities for AI governance are defined | `enterprise/human-approval-workflow.md`, `enterprise/policy-model.md` | `[ ]` | Map to organisation's specific structure |
| C07 | A governance charter or AI policy exists | `enterprise/policy-model.md` (design-level) | `[ ]` | Adopt and publish as organisational policy |
| C08 | AI governance is reviewed at defined intervals | Not defined | `[ ]` | Define review cadence |
| C09 | Incidents involving AI agent actions are trackable to specific governance decisions | Envelope hash chain provides traceability | `[ ]` | Test end-to-end traceability in target environment |

### 2.3 Human Oversight

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C10 | Human approval is required for high- and critical-risk actions | `enterprise/human-approval-workflow.md`, `enterprise/risk-profiles.yaml` | `[ ]` | Integrate with organisation's approval / ticketing system |
| C11 | Approval SLAs are defined and monitored | `enterprise/human-approval-workflow.md` (design-level) | `[ ]` | Define SLA targets; instrument monitoring |
| C12 | Approver authority is role-based and documented | `enterprise/human-approval-workflow.md` | `[ ]` | Map to organisation's delegated authority matrix |
| C13 | Humans can override or intervene in any AI decision | Implemented via kill switch and review queue | `[ ]` | Test override capability in target environment |
| C14 | Approval records are immutable and attributable | Partial — OIDC binding not yet implemented | `[ ]` | Implement OIDC-bound approver identity (see SBB gap) |

### 2.4 Risk Management

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C15 | Risk tiers are defined for all action types | `enterprise/risk-profiles.yaml` (LOW / MEDIUM / HIGH / CRITICAL) | `[ ]` | Validate tiers against organisation's risk appetite |
| C16 | Risk assessment is performed before deploying new agent workflows | Partial — `enterprise/production-readiness.md` | `[ ]` | Conduct formal risk assessment per workflow |
| C17 | Risk is monitored on an ongoing basis | `enterprise/observability.md` | `[ ]` | Implement dashboards and alert rules |
| C18 | Risk register is maintained | [`risk_register.md`](risk_register.md) | `[ ]` | Review, accept, and assign ownership to all risks |
| C19 | Unacceptable-risk AI practices are prohibited | Policy engine blocks explicitly prohibited action types | `[ ]` | Enumerate prohibited action types; confirm policy covers them |

### 2.5 Identity and Access Control

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C20 | All API callers are authenticated | Documented requirement; fail-closed in production mode | `[ ]` | Implement OIDC/SAML in target environment |
| C21 | Tenant isolation is enforced | `remora/adapters/storage/control_plane.py`, `servers/api.py` | `[ ]` | Test tenant isolation in CI |
| C22 | Access to audit records is restricted and logged | Not specified in reference implementation | `[ ]` | Define and implement access controls on audit store |
| C23 | Service principal identity is recorded in governance decisions | Not yet in envelope | `[ ]` | Add `actor_identity` to `DecisionEnvelope` (see SBB gap) |

### 2.6 Auditability and Logging

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C24 | Every governance decision produces a complete `DecisionEnvelope` | `remora/governance/envelope.py` | `[ ]` | Close enterprise fields gap (see `docs/decision_envelope_audit.md`) |
| C25 | Audit store is append-only | Designed as append-only | `[ ]` | Verify in deployment configuration |
| C26 | `tenant_id` is present in all envelopes | Not yet present | `[ ]` | Add to `DecisionEnvelope` (see SBB gap) |
| C27 | `policy_bundle_hash` is present in all envelopes | Not yet present | `[ ]` | Implement policy bundle signing and hashing |
| C28 | Timestamps are explicit and timezone-aware in all envelopes | Not confirmed | `[ ]` | Verify and enforce in `DecisionEnvelope` |
| C29 | Past decisions can be replayed and verified | `remora/shadow/replay.py`, hash chain | `[ ]` | Run replay smoke test in target environment |
| C30 | Audit logs are forwarded to SIEM | Documented as requirement | `[ ]` | Configure and test SIEM forwarding |

### 2.7 Security

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C31 | Fail-closed behaviour is tested when auth, store, or backend is unavailable | Implemented in `servers/api.py` | `[ ]` | Verify in target environment with deliberate fault injection |
| C32 | Tool Executor is isolated and unreachable without REMORA clearance | Architectural requirement | `[ ]` | Verify network zoning in deployment |
| C33 | Threat model is current and reviewed | `enterprise/threat-model.md` | `[ ]` | Review against target deployment topology |
| C34 | Secrets (tokens, keys) are managed via a secrets manager | Documented in `enterprise/deployment-runbook.md` | `[ ]` | Verify in target environment |
| C35 | Prompt injection and indirect injection threats are assessed | `enterprise/threat-model.md` | `[ ]` | Test injection scenarios in Shadow Mode |

### 2.8 Evidence and Knowledge Management

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C36 | Evidence provenance (source, freshness, authority) is recorded for VERIFY outcomes | Partial | `[ ]` | Formalise evidence provenance fields in envelope |
| C37 | Evidence freshness policy is defined | Not yet defined | `[ ]` | Define maximum evidence age per evidence class |
| C38 | RAG / evidence connectors are assessed for data sovereignty and confidentiality | Not addressed | `[ ]` | Include in supplier assessment |

### 2.9 Data Protection and Privacy

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C39 | Data classification is present in all envelopes | Not yet present | `[ ]` | Add `data_classification` field to envelope (see SBB gap) |
| C40 | Retention policy is defined and enforced per data class | Not yet defined | `[ ]` | Define retention periods; implement in audit store |
| C41 | PII is identified, redacted, or pseudonymised before storage in audit records | Not addressed | `[ ]` | Assess which fields may contain PII; implement redaction |
| C42 | Legal hold process is documented | Not addressed | `[ ]` | Define legal hold capability in audit store |
| C43 | DPIA / PIA has been conducted for workflows processing personal data | Not addressed | `[ ]` | Conduct DPIA before processing personal data |

### 2.10 Operations and Continuity

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C44 | Observability dashboards and SLOs are defined | `enterprise/observability.md` | `[ ]` | Build dashboards and configure alert rules |
| C45 | Rollback / kill switch is tested | Documented in runbook | `[ ]` | Test in staging before enforcement |
| C46 | HA/DR configuration is documented | Not defined | `[ ]` | Define and test HA/DR for audit store and API |
| C47 | Incident response process covers AI governance failures | Not defined | `[ ]` | Extend existing IR process to cover REMORA events |

### 2.11 Change Management

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C48 | Policy bundle changes pass golden set regression before deployment | `remora/shadow/replay.py` (capability exists) | `[ ]` | Establish golden set; wire to CI/CD |
| C49 | Policy changes go through change governance (CAB or equivalent) | Not defined | `[ ]` | Define policy change governance process |
| C50 | AI governance decisions are reviewed periodically for drift | Not defined | `[ ]` | Schedule periodic review; define drift metrics |

### 2.12 Third Parties

| Control | Requirement | Repo Evidence | Status | Gap / Action |
|---|---|---|---|---|
| C51 | Third-party model and evidence service providers are assessed for data handling | Not consolidated | `[ ]` | Conduct supplier due diligence; document in risk register |
| C52 | Data processed by third-party services is governed by contractual controls | Not addressed | `[ ]` | Include in supplier contract review |
| C53 | Regional data residency requirements are assessed for external services | Not addressed | `[ ]` | Confirm data residency for all external AI/RAG services |

---

## 3. ISO/IEC 42001 Control Mapping

| ISO 42001 Clause | Requirement Summary | REMORA Artefact | Assessment Controls |
|---|---|---|---|
| 4.1 Understanding the organisation | Context and interested parties | `enterprise/architecture.md` | C01–C04 |
| 4.2 Interested parties | Stakeholder requirements | [`architecture_building_block.md`](architecture_building_block.md) §7 | C05–C09 |
| 5.1 Leadership | Management commitment | Organisation-specific | C05, C07 |
| 5.2 Policy | AI policy | `enterprise/policy-model.md` | C07 |
| 5.3 Roles | Roles and responsibilities | `enterprise/human-approval-workflow.md` | C06 |
| 6.1 Risk assessment | AI risk management | `enterprise/risk-profiles.yaml`, `enterprise/threat-model.md` | C15–C19 |
| 6.2 Objectives | AI management objectives | `enterprise/production-readiness.md` | C05 |
| 8.1 Operational planning | AI system lifecycle controls | `enterprise/deployment-runbook.md` | C44–C47 |
| 8.2 AI risk treatment | Risk controls | REMORA policy engine + envelope | C15–C35 |
| 8.4 Human oversight | Human control measures | `enterprise/human-approval-workflow.md` | C10–C14 |
| 9.1 Monitoring | Monitoring and measurement | `enterprise/observability.md` | C44 |
| 9.3 Management review | Governance review | Organisation-specific | C08 |
| 10.2 Continual improvement | Improvement process | Shadow Mode replay, golden sets | C48–C50 |

---

## 4. EU AI Act Control Mapping (Deployer Obligations)

| AI Act Article | Requirement | REMORA Artefact | Assessment Controls |
|---|---|---|---|
| Art. 9 Risk management system | Systematic risk identification and mitigation | `enterprise/risk-profiles.yaml`, `enterprise/threat-model.md` | C15–C19 |
| Art. 13 Transparency | Information to deployers and users | `docs/plain_language_overview.md` | C01–C04 |
| Art. 14 Human oversight | Effective human oversight measures | `enterprise/human-approval-workflow.md` | C10–C14 |
| Art. 17 Quality management | Quality management system | `enterprise/production-readiness.md` | C44–C50 |
| Art. 12 Logging | Automatic logging of events | `DecisionEnvelope`, audit store | C24–C30 |
| Art. 26 Deployer obligations | Register high-risk AI; conduct DPIA | Organisation-specific | C05, C43 |
| Art. 27 Fundamental rights impact assessment | Assessment before deploying high-risk AI | Organisation-specific | C43 |

---

## 5. Assessment Summary

| Control Area | Controls | Passed | Failed | Not Assessed |
|---|---|---|---|---|
| Scope and Inventory | C01–C04 | | | |
| Governance | C05–C09 | | | |
| Human Oversight | C10–C14 | | | |
| Risk Management | C15–C19 | | | |
| Identity | C20–C23 | | | |
| Auditability | C24–C30 | | | |
| Security | C31–C35 | | | |
| Evidence | C36–C38 | | | |
| Data Protection | C39–C43 | | | |
| Operations | C44–C47 | | | |
| Change Management | C48–C50 | | | |
| Third Parties | C51–C53 | | | |
| **Total** | **53** | | | |

---

## 6. Reviewers and Sign-Off

| Role | Name | Date | Notes |
|---|---|---|---|
| Compliance Owner | | | |
| Data Protection Officer | | | |
| Security Architect | | | |
| Enterprise Architect | | | |
