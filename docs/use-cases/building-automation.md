# Use case: Building automation (per-zone lighting governance)

> Moved out of the top-level README (2026-07-21) to keep the README a surface,
> not a store. This is a dry-run demonstration; no live command is ever sent.
> Canonical governance semantics live in
> [docs/reference_architecture.md](../reference_architecture.md).

The governance concept is demonstrated in a concrete dry-run scenario: an AI
assistant proposes lighting adjustments across all floors of a commercial
building, and REMORA evaluates each floor-level command independently against
occupancy state and the active energy policy, before any command is sent. The
demo drives the **real `RemoraDecisionEngine`**: each floor becomes a
`PolicyObservation` (occupancy sensing is the caller-supplied evidence layer),
and the decisions and reason codes below are the engine's actual output —
REMORA's canonical ACCEPT/VERIFY/ABSTAIN/ESCALATE outcomes.

```bash
python scripts/demo_building_lights.py   # dry run; no live command is sent
```

Request: turn on all lights on all 8 floors. The engine decides per floor (real
`RemoraDecisionEngine` output):

| Floors | Occupancy | Engine decision | Reason code |
|--------|-----------|-----------------|-------------|
| 1–5, 8 | occupied (active motion) | **ACCEPT** | `evidence_supported` |
| 6, 7 | empty (47 / 131 min idle) | **ABSTAIN** | `disordered_no_evidence` |

REMORA does not treat the user request as a single all-or-nothing action. It
decomposes the tool call by zone, evaluates each floor-level command
independently against occupancy context and the active energy policy, and
blocks the subset that conflicts while allowing the compliant subset to proceed.
Empty floors ABSTAIN via the engine's deny-by-default path
(`disordered_no_evidence`): absence of occupancy evidence blocks activation.
This per-zone governance model extends directly to HVAC scheduling, ventilation
setpoints, energy load management, and any domain where a single agent command
maps to multiple physical sub-actions with differing risk profiles.

Related energy-domain scenarios are summarised in the
[use-case index](README.md).
