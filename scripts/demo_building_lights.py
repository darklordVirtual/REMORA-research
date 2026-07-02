#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic REMORA dry-run demo for building-light action gating.

This demo drives the REAL decision engine (`remora.policy.RemoraDecisionEngine`):
each floor-level sub-action becomes a `PolicyObservation`, and the printed
decision and reason codes come from `engine.decide()` — REMORA's canonical
ACCEPT / VERIFY / ABSTAIN / ESCALATE outcomes, not demo-local vocabulary.
No live building-automation command is sent and no external system is mutated.

What the mapping encodes:
- An occupied floor has occupancy-sensor evidence: the observation carries
  `evidence_action="answer"` with high evidence confidence in the ordered
  phase, so the engine ACCEPTs via its evidence-supported path.
- An empty floor has no occupancy evidence: no evidence signal, low trust,
  disordered phase — the engine ABSTAINs (deny-by-default: absence of
  evidence blocks activation; it does not prove the floor is unsafe).

A prior version of this script hard-coded ALLOW/BLOCK outcomes with invented
confidence percentages and imported nothing from `remora/`; it was replaced
2026-07-03 (hostile-review finding P1-9).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.policy import PolicyObservation, RemoraDecisionEngine  # noqa: E402


@dataclass(frozen=True)
class FloorContext:
    floor: int
    occupancy_label: str
    occupied: bool
    minutes_since_motion: int
    policy: str


FLOORS = [
    FloorContext(1, "12 persons, open office", True, 0, "manual override allowed"),
    FloorContext(2, "8 persons, meetings active", True, 0, "manual override allowed"),
    FloorContext(3, "15 persons, development team", True, 0, "manual override allowed"),
    FloorContext(4, "6 persons, finance", True, 0, "manual override allowed"),
    FloorContext(5, "3 persons, management", True, 0, "manual override allowed"),
    FloorContext(6, "empty", False, 47, "motion auto-off after 5 minutes"),
    FloorContext(7, "empty", False, 131, "motion auto-off after 5 minutes"),
    FloorContext(8, "1 person, conference room", True, 0, "manual override allowed"),
]


def observation_for(context: FloorContext) -> PolicyObservation:
    """Map one floor-level sub-action to a PolicyObservation.

    REMORA is stateless: occupancy sensing is the caller's evidence layer,
    encoded here as the evidence fields of the observation.
    """
    question = (
        f"lights_on(floor={context.floor}) — occupancy: {context.occupancy_label}; "
        f"policy: {context.policy}"
    )
    if context.occupied:
        return PolicyObservation(
            question=question,
            phase="ordered",
            trust_score=0.85,
            evidence_action="answer",
            evidence_confidence=0.90,
            evidence_signal_source="occupancy_sensor",
            risk_tier="low",
            action_type="write",
            target_environment="staging",  # dry-run: no production write
            schema_valid=True,
            rollback_available=True,
        )
    return PolicyObservation(
        question=question,
        phase="disordered",
        trust_score=0.30,
        risk_tier="low",
        action_type="write",
        target_environment="staging",
        schema_valid=True,
        rollback_available=True,
    )


def _line(char: str = "-", width: int = 110) -> str:
    return char * width


def main() -> None:
    engine = RemoraDecisionEngine()
    reports = [(ctx, engine.decide(observation_for(ctx))) for ctx in FLOORS]

    accepted = [c.floor for c, r in reports if r.action.value == "accept"]
    held = [c.floor for c, r in reports if r.action.value == "verify"]
    blocked = [c.floor for c, r in reports if r.action.value in ("abstain", "escalate")]

    print()
    print("REMORA building-light action-gating dry run (real RemoraDecisionEngine)")
    print(_line("="))
    print("Request: Turn on all lights on all 8 floors.")
    print("Safety model: No live building automation command is sent.")
    print("Policy: Occupied floors may execute; empty floors must not be activated without evidence.")
    print()
    print(f"{'Floor':<8}{'Occupancy':<34}{'Motion age':<13}{'Decision':<10}Engine reason codes")
    print(_line())
    for context, report in reports:
        motion_age = "active" if context.occupied else f"{context.minutes_since_motion} min"
        reasons = ", ".join(r.value for r in report.reasons)
        print(
            f"{context.floor:<8}"
            f"{context.occupancy_label:<34}"
            f"{motion_age:<13}"
            f"{report.action.value.upper():<10}"
            f"{reasons}"
        )

    print(_line())
    print(f"EXECUTE dry-run command: lights_on(floors={accepted})")
    if blocked:
        print(f"BLOCKED dry-run command: lights_on(floors={blocked})")
    if held:
        print(f"HELD for validation:     lights_on(floors={held})")
    print()
    print("Interpretation:")
    print("- REMORA does not treat the user request as a single all-or-nothing action.")
    print("- Each floor-level sub-action is gated independently by the real policy engine.")
    print("- Empty floors ABSTAIN (deny-by-default): no occupancy evidence means no activation,")
    print("  which is REMORA's conservative default rather than a claim the floor is unsafe.")
    print()


if __name__ == "__main__":
    main()
