# REMORA Human Approval Workflow

## Purpose

Human approval is the authority boundary for high-risk AI decisions. REMORA can
recommend, verify, abstain, or escalate; it should not turn an escalated decision
into an action without an authorized reviewer.

## Approval States

| State | Meaning |
|---|---|
| `not_required` | Risk profile permits direct answer or low-risk action |
| `pending` | REMORA escalated and awaits human decision |
| `approved` | Authorized reviewer approved the proposed action or answer |
| `rejected` | Reviewer rejected the proposal |
| `needs_more_evidence` | Reviewer requested additional evidence or clarification |
| `expired` | Approval SLA expired and action is blocked |

## Workflow

```text
REMORA decision
  -> ESCALATE or high-risk VERIFY
  -> create approval case
  -> attach decision trace and evidence refs
  -> route to role-based approver
  -> reviewer approves, rejects, or requests evidence
  -> record approval decision
  -> release answer/action only when policy permits
```

## Reviewer Packet

Every approval case should include:

- original user request,
- proposed answer or tool call,
- risk profile,
- policy version,
- triggered policy rules,
- phase and trust score,
- evidence sources and snippets,
- model disagreement summary,
- counterfactual or contradiction flags,
- recommended decision,
- known limitations,
- approval deadline.

## Separation Of Duties

| Risk tier | Approval model |
|---|---|
| Low | No approval |
| Medium | Optional approval for mutable actions |
| High | One authorized domain reviewer |
| Critical | Two-person review or senior authority approval |

The requester should not be the sole approver for high or critical decisions.

## Approval Guardrails

- Approval cannot override missing identity.
- Approval cannot override missing audit logging for high or critical requests.
- Approval cannot grant a tool outside the allowlist.
- Approval cannot convert critical recommendation-only mode into autonomous execution.
- Approval must include a reason code.
- Rejected decisions must remain blocked.

## Outcome Feedback

Reviewer decisions should be fed back into evaluation:

- approved and later correct,
- approved and later incident-linked,
- rejected as unsafe,
- rejected as low evidence,
- rejected as irrelevant,
- requested more evidence.

This feedback is used to tune policy thresholds and improve evidence coverage,
but only through versioned policy changes and regression tests.
