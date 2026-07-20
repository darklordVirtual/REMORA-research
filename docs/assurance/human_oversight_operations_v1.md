# Operational Human-Oversight Design v1

**Status:** DESIGN / PROTOCOL. Not an implemented or certified capability.
**Created:** 2026-07-20
**Relationship to gates:** extends, does not replace, [REM-021](remediation_register.yaml)
(independent human review, `NOT_STARTED`). REM-021's own scope
([independent_review_protocol_v1.md](independent_review_protocol_v1.md)) is a
one-off methodology-and-claims review that *excludes* live deployment; this
document specifies the **ongoing operational oversight** a live deployment would
need. Nothing here is claimed to run today.
**Legal note:** AI Act references are for design orientation only; not legal advice.

The compendium is explicit that human oversight (AI Act Art. 14) must be
*designed work* distributed across pre-control, co-planning, real-time
monitoring, and post-control — specified as a role matrix, event types, and
intervention thresholds — not a declared duty. This document is that design. It
distinguishes carefully between what REMORA **implements today** (decision-time
review machinery) and what an operator must **add** (the operational layer).

---

## 1. What exists today (decision-time review lifecycle)

These are real, tested controls — the substrate this design builds on.

| Capability | Behaviour | Path |
|---|---|---|
| Enqueue gating | Only VERIFY/ESCALATE enqueue; ACCEPT executes, ABSTAIN never executes | `remora/governance/review_queue.py` |
| Fail-closed timeout | Unattended items expire to ABSTAIN with a recorded `review_expired_to_abstain` event (default 4h) | `remora/governance/review_queue.py` |
| Approval freshness | Approvals carry mandatory bounded expiry (0 < ttl ≤ 24h); `execute()` re-gates on fresh world state and voids an approval that no longer dominates | `remora/governance/review_queue.py` |
| Action binding | Approval bound to the exact `tool_call_hash`; mismatch is refused | `remora/governance/review_queue.py`, `servers/execution_api.py` |
| Role reservation | Per-profile `approval_role` (domain_expert / senior_authority / soc_analyst / legal_counsel) enforced from the authenticated credential | `servers/execution_api.py`, `schemas/risk-profiles.yaml`, `servers/api.py` |
| Non-repudiable identity | Reviewer identity derived from the credential, never a self-reported header | `servers/api.py` (`_authenticated_principal`) |

**Crucial distinction:** the queue TTL is a *safety timeout* (inaction resolves
to ABSTAIN), **not** a reviewer response-time SLA. There is no measurement of
time-to-review today, and the queue is in-memory by design.

## 2. Oversight as designed work (the operational layer)

Human oversight is distributed across four phases; each names concrete artifacts
and the intervention threshold that triggers human action.

| Phase | Purpose | Trigger / threshold | Design artifact |
|---|---|---|---|
| Pre-control | Set what may auto-execute before any traffic | Risk-tier profile + `require_human_approval` per tier | `schemas/risk-profiles.yaml` (exists) |
| Co-planning | Reserve high-consequence action classes for a competent role | `approval_role` reservation per profile | exists; needs §3 RACI |
| Real-time monitoring | Watch the live decision stream for anomalies | Drift-monitor `critical`; degradation ≥ G3; escalate-rate SLO breach | `drift_monitor.py`, `degradation.py`, `_SLO_TARGETS` in `servers/api.py` (exist as signals; alerting is a gap) |
| Post-control | Review executed high-risk actions and incidents after the fact | Any ESCALATE; any executed HIGH/CRITICAL action; any audit-chain break | audit chains (exist); a review cadence (gap) |

## 3. Reviewer responsibility matrix (proposed)

Today the four domain reviewer roles (`soc_analyst`, `domain_expert`,
`legal_counsel`, `senior_authority`) carry identical `{review, read}`
capabilities and are differentiated only by per-profile `approval_role`. This
design adds an operational RACI tying **escalation event classes** (§4) to
**decision authority**. It is a proposal for a deployer to instantiate, not a
code change.

| Role (existing capability role) | Owns event classes | Decision authority | Escalates to |
|---|---|---|---|
| `soc_analyst` | Security / adversarial-input escalations | Approve/deny sandbox + reversible actions | `senior_authority` |
| `domain_expert` | Regulated-domain (medical/legal/energy) escalations | Approve/deny domain actions with evidence | `senior_authority` |
| `legal_counsel` | External-communication / liability escalations | Approve/deny outbound regulated communications | `senior_authority` |
| `operator` (not `review`-capable today; a deployer must grant `review` or set it as an `approval_role`) | Production-scope / blast-radius escalations | Approve/deny reversible production changes | `senior_authority` |
| `senior_authority` | Irreversible / global-blast-radius actions | Final approval; two-person rule for CRITICAL | (incident command) |

## 4. Escalation event taxonomy (proposed)

ESCALATE is a single `DecisionAction` today; `follow_up_type` includes
`manual_escalation` and `incident` as free enum values with no severity
semantics. This design proposes an operational severity taxonomy that a
deployer maps onto those values.

| Severity | Definition | Response expectation (SLA, proposed) | Owner |
|---|---|---|---|
| Sev-1 | Irreversible or global-blast-radius action proposed; adversarial input detected; audit-chain break | Immediate; two-person approval; page on-call | senior_authority |
| Sev-2 | Regulated-domain or production-scope action needing evidence | Within the approval TTL (≤ 24h; ≤ 15 min for production writes per [resilience_plan_v1.md](resilience_plan_v1.md)) | domain role |
| Sev-3 | Routine VERIFY needing confirmation | Best-effort before queue TTL | operator |

The response times are **targets to be set by the deployer**, distinct from the
fail-closed queue TTL. Nothing measures them today (gap, §6).

## 5. Alarm-fatigue mitigation (proposed)

The review queue is a flat in-memory dict with no prioritisation, deduplication,
batching, or noise budget — so unmitigated volume would degrade oversight
quality. Proposed measures (all roadmap):

- Order the queue by severity (§4), not arrival.
- Deduplicate structurally identical proposals (same `tool_call_hash` + tenant).
- Batch Sev-3 confirmations; page only on Sev-1.
- Track a per-reviewer noise budget and surface it, so persistent Sev-3 volume
  becomes a signal to tighten a risk profile rather than a source of fatigue.

## 6. Gaps this design does not yet close (roadmap)

| Gap | Status | Tracked |
|---|---|---|
| Response-time SLA measurement (time-to-review / time-to-approve) | missing | REM-042 |
| Escalation event taxonomy with routing semantics | missing | REM-042 |
| Alarm-fatigue mitigation (prioritise/dedup/batch/budget) | missing | REM-042 |
| On-call roster, coverage, paging/notification | missing | REM-042 |
| Escalation routing/dispatch to a named target (design-only in `artifacts/credibility-pack/policy-model.md`) | design_only | REM-042 |
| Durable, queryable operational review queue (current queue is in-memory) | partial | REM-042 |
| Federated reviewer identity (OIDC binding) | missing | REM-022 §8, REM-042 |
| Independent human review of methodology and claims | not started | REM-021 |

## 7. Acceptance criteria

This design is *implemented* (a future REM-042 closure) when: (1) the review
queue is durable and orders by severity; (2) time-to-review and time-to-approve
are measured against per-severity targets and alertable; (3) an escalation event
carries a severity and routes to a named role per §3; (4) an on-call/coverage
mechanism exists with paging on Sev-1; and (5) reviewer identity is bound to a
federated IdP. Until then this remains a design under an open production gate,
and REMORA must continue to be described as research-grade and shadow-only.
