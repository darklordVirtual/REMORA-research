# Causal-Consequence Gating Signals

Status: research-grade, deterministic, heuristic. Not production-certified.
Causal-consequence *inspired*, this is not causal decision theory and there
is no interventional world model.

## Idea

Pre-execution governance should ask "what does executing this action cause?"
- not just "what does the label say?". The layer derives, per action:

| Field | Content |
|-------|---------|
| `state_change_expected` | whether execution mutates state |
| `blast_radius` | `none, local, tenant, system, external, production, unknown` |
| `affected_assets` / `downstream_effects` | what is touched and what follows |
| `irreversible` | semantics or destructive-with-unknown-rollback |
| `causal_uncertainty` | how unreliable the consequence model is here |
| `expected_loss` | coarse loss score in [0, 1] |
| `if_executed` / `if_blocked` | one-line consequence narratives for reviewers |

## Rules

- read-only → no state change, blast radius none/local, loss ≤ 0.1
- tenant-scoped write → tenant radius, loss 0.2–0.4
- production mutation → production radius, loss 0.5–0.8
- destructive production / security disable / financial transfer / safety-
  critical → loss ≥ 0.8
- DNS/firewall/security changes → system (production when prod-targeted)
- external email/webhook/payment → external (cannot be recalled)
- unknown environment + mutation → blast radius `unknown`, causal uncertainty
  ≥ 0.8, unknown is not safe
- bulk scope widens the radius one step

## How it routes

`expected_loss ≥ 0.8` floors the merged risk tier at `high`; safety-critical
signals floor it at `critical`; `causal_uncertainty ≥ 0.7` on a mutating
action sets `state_transition_uncertain`. Those flow into the engine's
existing tier-, uncertainty-, and rollback-gates. The assessment itself is
also fully available to reviewers via `GovernanceIntelligenceResult.causal`.

## Limitations

- Table-driven: the loss bands are design constants, not measured losses.
- No dependency graph: downstream effects are category narratives, not a
  traced impact analysis.
- `unknown` blast radius is deliberately sticky, the layer prefers admitting
  ignorance over guessing a small radius.
