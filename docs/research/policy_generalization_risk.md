# Policy Generalization Risk

Status: research-grade, deterministic, heuristic. Not production-certified.
LDT-*inspired* — this is not Logical Decision Theory; there are no logical
counterfactuals, only a conservative projection.

## Core question

> If REMORA ACCEPTed this class of action repeatedly — across similar agents,
> tenants, and future cases — would that standing policy remain safe?

Approving one DNS edit is a decision about an action. Auto-approving DNS edits
is a decision about a *policy*, and the policy's risk is not the sum of its
actions: repeated infrastructure edits, permission grants, and external sends
compound into systemic exposure that no single-action gate sees.

## Signals

| Field | Content |
|-------|---------|
| `policy_generalization_risk` | [0, 1] standing-policy risk |
| `similar_action_seen_count` | caller-supplied repetition count (REMORA is stateless) |
| `repeated_action_pattern` | count ≥ 3 |
| `fleet_level_effect` | `none, local, tenant, systemic, unknown` |
| `standing_policy_safe` | risk < 0.5 and effect none/local |
| `generalized_counterfactual` | one-line standing-policy narrative for reviewers |

## Rules

- repeated low-risk reads → low risk, effect none/local, standing policy safe
- DNS/firewall/security/network classes → systemic, risk ≥ 0.85
- destructive production writes → systemic, risk ≥ 0.8
- external sends / bulk email → tenant effect, risk ≥ 0.65
- permission grants → tenant effect, risk ≥ 0.6 (systemic when repeated)
- count > 10 and mutating → risk ≥ 0.75, effect widens one step
- critical tier and repeated → systemic, risk ≥ 0.85
- unknown environment and repeated mutation → systemic/unknown, risk ≥ 0.8

## How it routes

The enriched observation populates the existing v0.9 fields
(`policy_generalization_risk`, `fleet_level_effect`,
`similar_action_seen_count`), so the engine's existing gates fire:
`FLEET_SYSTEMIC_VERIFY`, `POLICY_GENERALIZATION_VERIFY` (> 0.70), and
`SIMILAR_ACTION_FLOOD_VERIFY` (> 50). Before this layer those fields were
caller-populated only; now any caller that can supply a repetition count gets
the projection for free, and callers that supply nothing still get the
class-based component.

## Limitations

- REMORA is stateless: repetition counts must come from the caller (session
  store, AROMER episodic memory, or fleet telemetry). Garbage counts in,
  garbage projection out — though the strengthen-only merge means a missing
  count can only under-detect repetition, never weaken other gates.
- Class taxonomy is coarse; two "write" actions may generalize very
  differently.
- The thresholds (3, 10, 50) are design constants pending external calibration.
