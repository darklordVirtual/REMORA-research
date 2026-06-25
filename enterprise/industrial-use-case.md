# REMORA Industrial Use Case: Maintenance Recommendation Gate

## Scenario

An AI assistant receives a maintenance question:

> A compressor vibration trend is increasing. Should the assistant recommend a
> work order, adjust the inspection interval, or trigger an operational action?

This is a high-risk industrial workflow because an incorrect answer can create
unnecessary downtime, missed maintenance, safety exposure, or uncontrolled
operational change.

## REMORA Control Flow

1. Classify the request as `maintenance_planning` and `high` risk.
2. Retrieve approved procedures, asset context, recent work orders, and relevant
   engineering standards.
3. Ask multiple oracle families to reason independently.
4. Canonicalize answers and measure disagreement.
5. Classify consensus phase: ordered, critical, or disordered.
6. Require evidence because the request is high risk.
7. Run an independent verifier against the proposed recommendation.
8. Block any direct tool action against production systems.
9. Escalate to the responsible engineer if confidence or evidence is insufficient.
10. Write the full decision trace to the audit ledger.

## Allowed Outcomes

| REMORA outcome | Meaning in this workflow |
|---|---|
| `ACCEPT` | Return a recommendation with evidence references; no autonomous action |
| `VERIFY` | Retrieve more evidence or ask an additional verifier |
| `ABSTAIN` | Do not provide a recommendation because trust is insufficient |
| `ESCALATE` | Route to maintenance or operations owner |
| `EXECUTE` | Not permitted for production-impacting actions |

## Example Policy

```yaml
risk_profile: high
domain: maintenance_planning
require_evidence: true
min_evidence_sources: 2
require_independent_judge: true
allow_tool_action: false
require_human_approval: true
permitted_outcomes:
  - ACCEPT
  - VERIFY
  - ABSTAIN
  - ESCALATE
```

## Why REMORA Adds Value

The assistant may be fluent and plausible even when evidence is weak. REMORA
adds a control layer that asks:

- Do independent models agree?
- Is the agreement backed by approved evidence?
- Is the task allowed to produce an answer or only a recommendation?
- Does the proposed tool call cross an authority boundary?
- Is the system uncertain enough to require human review?

## Deployment Boundary

For this workflow, REMORA should be deployed first in shadow mode. It should
record recommendations and escalations without blocking existing operations.
After reviewer agreement is measured, it can move to human-gated pilot mode.

Autonomous changes to production systems remain out of scope.
