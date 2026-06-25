# Architecture Principles — REMORA AI Action Governance

**Status:** draft — not independently audited.
**Audience:** Enterprise architects, platform leads, security architects.
**Repository evidence:** `remora/policy/decision_engine.py`, `enterprise/threat-model.md`,
`enterprise/production-readiness.md`, `docs/decision_envelope_audit.md`,
`servers/api.py`

---

## Overview

These principles govern the design, implementation, and operation of REMORA
and of any enterprise deployment that adopts REMORA as its AI Action Governance
Capability. They are derived from the repository's design decisions and from
the requirements of TOGAF Architecture Governance, EU AI Act, and ISO/IEC 42001.

Each principle is stated as a testable constraint: it either holds or it does not,
making it suitable for use in architecture reviews and implementation governance checks.

---

## Principles

### P01 — Policy Before Execution

**Statement:** No AI agent action may reach a tool executor without first receiving
a governance decision from REMORA or an equivalent pre-execution governance gateway.

**Rationale:** Agent actions produce side effects in external systems. Once a side
effect has occurred, it cannot be reliably reversed. The only opportunity to apply
governance is before execution.

**Implications:**
- All agent runtimes must be instrumented to route proposed actions through REMORA.
- Direct calls from agent runtimes to tool executors must be blocked at the network
  or application layer.
- No exception is permitted for "low-risk" or "read-only" actions unless explicitly
  classified as such in the policy configuration and the classification itself has
  been reviewed.

**Repo evidence:** `remora/adapters/action_gate.py`, `remora/policy/decision_engine.py`

---

### P02 — Fail-Closed by Default

**Statement:** In the absence of a valid policy evaluation, a complete evidence set,
or a reachable governance service, the default outcome must be VERIFY, ABSTAIN, or
ESCALATE — never ACCEPT.

**Rationale:** Uncertainty about whether an action is safe is not a reason to permit it.
A missed block is more harmful than a false block. The burden of proof is on permission,
not on rejection.

**Implications:**
- Service unavailability must result in blocking, not in bypassing governance.
- Missing evidence must increase the likelihood of VERIFY or ABSTAIN, not decrease it.
- Policy evaluation errors must produce ESCALATE, not ACCEPT.
- Fail-closed conditions for production mode are explicitly implemented in `servers/api.py`.

**Repo evidence:** `servers/api.py` — fail-closed production conditions; `remora/policy/decision_engine.py` — conservative decision tree

---

### P03 — Critical Actions Are Human-Approved Only

**Statement:** Actions classified as critical risk must never be executed autonomously
in production environments. A named human approver with appropriate authority must
explicitly authorise the action before execution proceeds.

**Rationale:** The consequences of an incorrect critical action — data loss, security
breach, regulatory violation, irreversible system change — exceed the cost of any
reasonable human review delay.

**Implications:**
- The policy engine must never route critical-risk actions to ACCEPT directly.
- Human approval must be binding: it must record the approver's identity, role,
  timestamp, and the specific action approved.
- Approval must be time-bounded: an approval for action X does not pre-authorise
  similar actions.
- Two-person approval rules apply for actions with catastrophic potential.

**Repo evidence:** `enterprise/human-approval-workflow.md`, `enterprise/risk-profiles.yaml`

---

### P04 — Audit by Design

**Statement:** Every governance decision must produce a complete `DecisionEnvelope`
that is written to an append-only store before the decision is returned to the caller.
Audit is not a post-hoc addition — it is a prerequisite for returning a decision.

**Rationale:** A governance system without a complete audit trail is not a governance
system — it is a speed bump. Enterprises need to demonstrate, retrospectively, that
governance was applied correctly to specific actions at specific points in time.

**Implications:**
- `DecisionEnvelope` must be written before the outcome is returned.
- The audit store must be append-only: no record may be modified or deleted after creation.
- The envelope must record all fields necessary for audit: outcome, policy version,
  risk profile, evidence signals, actor identity, tenant, timestamp, and decision hash.
- Current gap: several enterprise fields are missing from the envelope
  (see `docs/decision_envelope_audit.md`). Closing this gap is a prerequisite for
  production deployment in regulated environments.

**Repo evidence:** `remora/governance/envelope.py`, `remora/adapters/storage/control_plane.py`

---

### P05 — Shadow Mode Before Enforcement

**Statement:** Every new agent workflow must operate in observe-only (Shadow Mode) before
any blocking effect is enabled. Enforcement must not be activated before a qualified
reviewer has signed off on the governance decision distribution from the Shadow Mode period.

**Rationale:** Governance policies are always incomplete at first deployment. Shadow Mode
allows the organisation to observe real decision distributions, identify false positives,
and calibrate policy before blocking takes effect.

**Implications:**
- Shadow Mode is mandatory, not optional, for new workflow onboarding.
- The duration of Shadow Mode must be sufficient to cover a representative sample of
  the workflow's action patterns (typically 2–4 weeks).
- A governance delta report must be generated from the Shadow Mode artefacts.
- Reviewer sign-off on the delta report is the gate between Shadow Mode and enforcement.

**Repo evidence:** `remora/shadow/replay.py`, `scripts/shadow_replay.py`

---

### P06 — Tenant Isolation

**Statement:** Policy configurations, governance decisions, audit records, and approval
workflows must be strictly isolated by tenant. No tenant's governance data may be visible
to or influenced by another tenant's configuration or activity.

**Rationale:** Enterprise deployments are multi-tenant by nature. A shared governance
control plane must not allow data from one business unit, customer, or regulatory
jurisdiction to affect the governance of another.

**Implications:**
- Tenant identity must be present in every API request, envelope, and audit record.
- Storage, policy evaluation, and review queue routing must be tenant-scoped.
- Tenant isolation must be tested explicitly in the CI/CD pipeline.

**Repo evidence:** `remora/adapters/storage/control_plane.py`, `servers/api.py`

---

### P07 — Evidence Provenance

**Statement:** Every VERIFY decision must record the source, type, freshness, and
authority of the evidence used. A VERIFY outcome without documented evidence provenance
is not a valid governance decision.

**Rationale:** Evidence that cannot be attributed to a source or validated for freshness
provides no assurance. In regulated environments, governance decisions based on stale
or unattributed evidence may not be defensible.

**Implications:**
- Evidence connectors must record source identifier, retrieval timestamp, confidence
  score, and authority class.
- Policy must define maximum acceptable evidence age (freshness policy).
- Evidence provenance must be included in the `DecisionEnvelope`.
- Current gap: evidence provenance fields are not fully formalised in the envelope.

**Repo evidence:** `enterprise/policy-model.md`, `remora/policy/observation.py`

---

### P08 — Human Approval Is an Authority Boundary

**Statement:** Human approval in the governance workflow is an authority boundary, not
a user interface feature. It is a binding exercise of delegated authority by a named
individual with a defined role, recorded with identity, timestamp, and scope.

**Rationale:** If approval can be given anonymously, retrospectively, or without scope
limitation, it provides no meaningful governance. Non-repudiation of approval decisions
is essential for compliance and incident response.

**Implications:**
- Approver identity must be bound at approval time using an IdP (OIDC/SAML).
- Approval records must be immutable after creation.
- Each approval is scoped to a specific action instance — it does not pre-authorise
  similar future actions.
- Approval SLAs must be defined and monitored.
- Current gap: OIDC identity binding in approval records is not yet implemented in
  the reference implementation.

**Repo evidence:** `enterprise/human-approval-workflow.md`

---

### P09 — Governance and Execution Are Separated

**Statement:** The governance control plane (REMORA) and the tool execution environment
must be distinct, independently deployable components. The tool executor must not be
reachable except through a channel gated by a valid REMORA governance decision.

**Rationale:** Collocating governance and execution creates a single point of failure
and makes governance bypassing trivially easy. Separation enforces the policy-before-
execution principle at the infrastructure level.

**Implications:**
- The Tool Executor must be in a separate network zone and must only accept requests
  carrying a valid, signed REMORA clearance token.
- The Tool Executor must maintain its own tool allowlist, independent of the agent runtime.
- The Tool Executor must support dry-run mode for testing and pilot phases.
- Direct connections from agent runtimes to tool executors must be blocked.

**Repo evidence:** `remora/adapters/action_gate.py`, `enterprise/tool-governance.md`

---

### P10 — Continuous Improvement Without Policy Drift

**Statement:** Policy bundles must be managed as versioned, signed artefacts. Changes
to policy must pass golden set regression testing and replay validation before deployment.
Policy must not be changed in production without change governance approval.

**Rationale:** A governance system whose policy drifts without control is worse than no
governance — it creates false confidence. Organisations need to demonstrate that the
policy governing today's decisions is the same policy that was reviewed and approved.

**Implications:**
- Policy bundles must be version-controlled and signed.
- A golden set of representative decisions must be maintained and must pass regression
  before any policy deployment.
- Policy changes must go through the same change governance process as production
  software releases.
- Replay must be run against the golden set before and after any policy change.
- Current gap: policy bundle signing is not yet implemented.

**Repo evidence:** `remora/shadow/replay.py`, `enterprise/observability.md`

---

## Derived Design Rules

The following concrete design rules are derived from the principles above and apply
to all REMORA implementations:

| Rule | Derived from |
|---|---|
| All mutating agent actions must route through the REMORA gateway | P01 |
| REMORA must be the only path to the Tool Executor | P01, P09 |
| Service degradation must result in ESCALATE or ABSTAIN, never ACCEPT | P02 |
| Critical-risk actions must never appear as ACCEPT outcomes | P03 |
| `DecisionEnvelope` is mandatory for all four decision outcomes | P04 |
| Audit store must be append-only with no delete capability | P04 |
| Shadow Mode duration must be explicitly agreed before onboarding | P05 |
| Reviewer sign-off on Shadow Mode delta is required before enforcement | P05 |
| `tenant_id` must be present in every envelope and audit record | P06 |
| Tenant isolation must be covered by automated tests in CI | P06 |
| VERIFY outcomes must include evidence source and freshness metadata | P07 |
| Approval records must carry OIDC-bound approver identity | P08 |
| Approvals are scoped to a single action instance | P08 |
| Tool Executor must not be reachable without a valid clearance token | P09 |
| Policy changes must include replay regression before deployment | P10 |

---

## Principle Compliance Assessment

These principles can be used as an architecture review checklist. For each principle,
the reviewer should confirm that:

1. The principle is understood and accepted by the team.
2. The implementation satisfies the principle's implications.
3. Any deviation is documented with a formal waiver (see [`architecture_contract_template.md`](architecture_contract_template.md)).
