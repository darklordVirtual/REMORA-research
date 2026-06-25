# Architecture Contract — AI Agent Action Governance

**Document Type:** Architecture Contract Template (TOGAF Phase G)
**Status:** draft — complete before use; requires sign-off by Enterprise Architect and
Security Architect.
**Version:** 1.0-draft
**Last updated:** (fill in)
**Next review:** (fill in)
**Repository evidence:** `enterprise/human-approval-workflow.md`,
`enterprise/production-readiness.md`, `servers/api.py`, `enterprise/policy-model.md`

---

## 1. Purpose

This Architecture Contract establishes the obligations, constraints, and acceptance
criteria that govern how AI agents are deployed and operated within the organisation
when those agents can propose or execute actions against data, systems, infrastructure,
or external services.

It is intended to be completed by the enterprise architecture team, reviewed by the
security architect, and signed off before any AI agent workflow proceeds beyond
Shadow Mode observation.

---

## 2. Scope

This contract applies to all AI agents, copilots, workflow engines, and autonomous
tools that:

- invoke tools (file I/O, database operations, API calls, shell commands)
- read or write enterprise data
- affect production environments (directly or indirectly)
- send messages, create or modify tickets, or call external APIs
- use external model or evidence services
- interact with infrastructure, networking, or security tooling

**Systems in scope for this deployment:**

| System / Workflow | Owner | Risk Profile | Enrolled Date |
|---|---|---|---|
| (fill in) | (fill in) | (fill in) | (fill in) |

---

## 3. Obligations

### 3.1 Mandatory Obligations (non-waivable)

All of the following must be satisfied before enforcement is enabled:

| # | Obligation | Owner |
|---|---|---|
| O01 | All proposed agent actions are evaluated by REMORA or an approved equivalent governance gateway before tool dispatch | Platform Owner |
| O02 | High- and critical-risk actions are never routed to ACCEPT without human review | Security Architect |
| O03 | Critical-risk production actions are never executed autonomously | Security Architect |
| O04 | Every governance decision produces a `DecisionEnvelope` written to the audit store | Platform Owner |
| O05 | Human approval is required for all actions classified as high or critical risk | Platform Owner |
| O06 | A tool allowlist with validated schemas is established and enforced before pilot | Platform Owner |
| O07 | Shadow Mode observation is completed before enforcement is enabled | Enterprise Architect |
| O08 | Reviewer sign-off on Shadow Mode delta report is obtained before enforcement | Enterprise Architect |
| O09 | A kill switch (ability to disable blocking instantly) is tested before enforcement | Platform Owner |
| O10 | SIEM forwarding of governance events is operational before enforcement | Security Architect |

### 3.2 Obligations Requiring Evidence at Review

| # | Obligation | Evidence Required |
|---|---|---|
| O11 | IdP / OIDC authentication is active for all API callers | Auth config + test results |
| O12 | Approval records carry OIDC-bound approver identity | Approval record sample |
| O13 | Tenant isolation is tested in CI | CI test results |
| O14 | Policy bundle is version-controlled and hash-stamped | Bundle manifest |
| O15 | Audit store is append-only and backed up | Storage config + backup test |

---

## 4. Constraints

| Constraint | Description |
|---|---|
| Fail-closed | REMORA must not bypass governance when the governance service is degraded. Degradation must produce ESCALATE or ABSTAIN. |
| No self-exemption | No agent or system may self-classify its actions as exempt from governance. |
| No ephemeral approval | Approvals are scoped to a single action instance. A past approval does not pre-authorise future similar actions. |
| No direct tool access | Agent runtimes must not have direct network access to the Tool Executor, bypassing REMORA. |
| Policy change requires governance | Policy bundle changes require replay regression against the golden set before deployment. |

---

## 5. Roles and Responsibilities

| Role | Responsibility | Named individual(s) |
|---|---|---|
| Business Owner | Owns the purpose and acceptable risk tolerance for the agent workflow(s) in scope | (fill in) |
| Enterprise Architect | Confirms the solution meets this contract; issues Architecture Decisions | (fill in) |
| Security Architect | Validates fail-closed behaviour, identity binding, and audit completeness | (fill in) |
| Platform Owner | Deploys and operates the REMORA instance; maintains audit store | (fill in) |
| Domain Approver(s) | Reviews and approves actions routed to the human approval queue | (fill in) |
| Compliance Owner | Confirms audit completeness meets regulatory requirements | (fill in) |
| Data Protection Officer | Confirms PII handling, data classification, and retention controls | (fill in) |

---

## 6. Architecture Decision Log

| Decision | Rationale | Alternatives Considered | Date | Author |
|---|---|---|---|---|
| (fill in) | (fill in) | (fill in) | (fill in) | (fill in) |

---

## 7. Technical Control Requirements

| Control | Requirement | Current Status |
|---|---|---|
| Tenant isolation | Policies, decisions, and audit data scoped by tenant ID | (fill in) |
| RBAC / IdP integration | All API callers authenticated via OIDC/SAML | (fill in) |
| Append-only audit store | No record deletion; immutable after write | (fill in) |
| SIEM forwarding | All governance events forwarded to SIEM | (fill in) |
| Review queue | Operational with defined SLA and named approvers | (fill in) |
| Rollback / kill switch | Tested and documented; can disable blocking in < 5 minutes | (fill in) |
| Evidence provenance | Source, freshness, and authority recorded for all VERIFY outcomes | (fill in) |
| Policy bundle governance | Version-controlled, hash-stamped, replay-tested before deployment | (fill in) |
| Data classification | `data_classification` field present in all envelopes | (fill in) |
| Retention policy | `retention_policy` field present; legal hold process documented | (fill in) |

---

## 8. Exceptions and Waivers

Any deviation from the mandatory obligations in §3.1 must be documented here.

| # | Obligation waived | System / workflow | Justification | Risk-mitigating controls | Expiry date | Approved by |
|---|---|---|---|---|---|---|
| (fill in) | (fill in) | (fill in) | (fill in) | (fill in) | (fill in) | (fill in) |

---

## 9. Pilot Exit Criteria

The following criteria must all be met before any workflow may proceed from
Shadow Mode or human-gated pilot to limited enforcement:

| Criterion | Target | Actual | Pass / Fail |
|---|---|---|---|
| Zero critical autonomous executions during pilot period | 0 | (fill in) | |
| False accept rate | < (fill in) % | (fill in) | |
| Audit completeness (decisions with complete envelope) | > (fill in) % | (fill in) | |
| Review queue SLA adherence | > (fill in) % of reviews completed within SLA | (fill in) | |
| Kill switch test | Passed | (fill in) | |
| SIEM alert operational | Confirmed | (fill in) | |
| Rollback test | Passed | (fill in) | |
| Replay hash chain integrity | 100% | (fill in) | |

---

## 10. Sign-Off

| Role | Name | Signature | Date |
|---|---|---|---|
| Enterprise Architect | | | |
| Security Architect | | | |
| Platform Owner | | | |
| Compliance Owner | | | |
| Business Owner | | | |

---

## 11. Document History

| Version | Date | Author | Change Summary |
|---|---|---|---|
| 1.0-draft | (fill in) | (fill in) | Initial draft |
