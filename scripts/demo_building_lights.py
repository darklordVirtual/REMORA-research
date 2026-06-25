#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic REMORA dry-run demo for building-light action gating.

The script demonstrates split execution: safe occupied zones are allowed while
unoccupied zones are blocked before any building automation command is sent.
It performs no live tool calls and mutates no external system.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FloorContext:
    floor: int
    occupancy_label: str
    occupied: bool
    minutes_since_motion: int
    policy: str


@dataclass(frozen=True)
class FloorDecision:
    floor: int
    action: str
    confidence: float
    reason: str


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


def evaluate_floor(context: FloorContext) -> FloorDecision:
    """Return the dry-run REMORA policy decision for one floor."""

    if context.occupied:
        return FloorDecision(
            floor=context.floor,
            action="ALLOW",
            confidence=0.92,
            reason="confirmed occupancy and permitted manual override",
        )

    if context.minutes_since_motion >= 5:
        return FloorDecision(
            floor=context.floor,
            action="BLOCK",
            confidence=0.96,
            reason="no occupancy evidence and active energy policy",
        )

    return FloorDecision(
        floor=context.floor,
        action="VERIFY",
        confidence=0.62,
        reason="recent motion but insufficient occupancy confirmation",
    )


def evaluate_floors(floors: list[FloorContext]) -> list[FloorDecision]:
    return [evaluate_floor(floor) for floor in floors]


def _line(char: str = "-", width: int = 96) -> str:
    return char * width


def main() -> None:
    decisions = evaluate_floors(FLOORS)
    allowed = [decision.floor for decision in decisions if decision.action == "ALLOW"]
    blocked = [decision.floor for decision in decisions if decision.action == "BLOCK"]
    verify = [decision.floor for decision in decisions if decision.action == "VERIFY"]

    print()
    print("REMORA building-light action-gating dry run")
    print(_line("="))
    print("Request: Turn on all lights on all 8 floors.")
    print("Safety model: No live building automation command is sent.")
    print("Policy: Occupied floors may execute; empty floors must not be activated without evidence.")
    print()
    print(f"{'Floor':<8}{'Occupancy':<34}{'Motion age':<14}{'Decision':<10}{'Confidence':<12}Reason")
    print(_line())
    for context, decision in zip(FLOORS, decisions, strict=True):
        motion_age = "active" if context.occupied else f"{context.minutes_since_motion} min"
        print(
            f"{context.floor:<8}"
            f"{context.occupancy_label:<34}"
            f"{motion_age:<14}"
            f"{decision.action:<10}"
            f"{decision.confidence:<12.0%}"
            f"{decision.reason}"
        )

    print(_line())
    print(f"EXECUTE dry-run command: lights_on(floors={allowed})")
    if blocked:
        print(f"BLOCKED dry-run command: lights_on(floors={blocked})")
    if verify:
        print(f"VERIFY dry-run command: lights_on(floors={verify})")
    print()
    print("Interpretation:")
    print("- REMORA does not treat the user request as a single all-or-nothing action.")
    print("- It decomposes the tool call by zone and gates each critical sub-action.")
    print("- Empty floors are blocked because the proposed action conflicts with context and policy.")
    print()


if __name__ == "__main__":
    main()
