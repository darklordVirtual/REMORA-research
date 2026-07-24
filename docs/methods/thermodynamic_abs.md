# Trajectory Braking (session-level trust penalty)

> **Vocabulary note (2026-07-03).** This document previously used physical
> thermodynamics language ("continuous thermodynamic trajectory", "Gold
> Standard … proven in test boundaries") without the disclaimers the rest of
> the repository carries. The mechanism is a heuristic session-level penalty
> on the trust threshold; "thermodynamic" and "Lyapunov" here are borrowed
> names for an uncertainty-routing metaphor, not physics (see
> `docs/thermodynamics/limitations.md` and ARCHITECTURE.md §4). The
> "ABS/anti-lock braking" framing is an analogy for intuition only.

## Concept

Evaluating a single tool call in isolation ("is this request safe?") misses
threats that accumulate across a multi-step session. This component tracks a
session-level scalar `V(t)` (defined below) and, when it rises too fast,
raises the trust threshold a marginal action must clear, pushing borderline
ACCEPTs toward VERIFY. It is a monitor plus a threshold penalty, nothing more.

## The "boiled frog" pattern

An agent pursuing a multi-step exploit or a hallucination spiral may emit
individual actions that each barely clear the ACCEPT threshold (e.g. trust
0.66 against a 0.65 threshold) while the underlying oracle dissensus `D` and
distribution entropy `H` drift upward. Gating on the per-step trust score
alone lets such a sequence through.

## The mechanism

The session monitor tracks the scalar

```
V(t) = H(t) + λ · D(t)
```

named a "Lyapunov value" by analogy only, it is not shown to be a Lyapunov
function of any dynamical system and certifies nothing (see
`remora/lyapunov.py` docstring and paper §10.4, where 12.8% of trajectories
have ΔV > 0). The braking signal is the step-to-step change

```
dV = V(t) − V(t−1)
```

When `dV` exceeds an activation threshold `τ_activation`, the required trust
score is raised by a penalty that grows with the excess:

```
Penalty = min(β · (dV − τ_activation), MaxPenalty)
```

The penalty scales with the rate of increase of `V`, a heuristic linear
response with a cap, not a derived control law. Raising the required trust
score downgrades marginal ACCEPT states to VERIFY, so the agent is stopped
for human validation on the basis of its session trajectory rather than any
single action.

## Implementation

- `remora/policy/thermodynamic_braking.py`
- Tests: `tests/test_thermodynamic_braking.py`

Zero extra dependencies; integrates with the existing threshold configuration.
No claim is made that this prevents any specific class of attack, it is a
conservative session-level heuristic whose parameters (`τ_activation`, `β`,
`MaxPenalty`) are tuned, not derived.
