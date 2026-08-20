# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The lifecycle state machine is a committed, machine-readable artifact.

FT-01 (design docs/design/execution-lifecycle-outbox-v1.md, direction
approved 2026-08-05): schemas/execution_lifecycle_v1.yaml declares the
canonical states and legal transitions. These tests pin the structural
invariants so implementation and model cannot drift apart silently: every
state is reachable from PROPOSED, terminal states have no outgoing
transitions, and the maintainer-decided v1 semantics (synchronous execute,
UNKNOWN as explicit terminal, manual-plus-probe resolution) are recorded.
"""
from __future__ import annotations

import pytest

from pathlib import Path

import yaml

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "execution_lifecycle_v1.yaml"


def _load() -> dict:
    return yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))


def test_schema_exists_and_declares_the_fasttrack_states() -> None:
    doc = _load()
    states = set(doc["states"])
    required = {
        "PROPOSED", "ASSESSED", "REVIEW_PENDING", "AUTHORIZED", "REFUSED",
        "DISPATCH_PENDING", "DISPATCHING", "SUCCEEDED", "FAILED", "UNKNOWN",
        "EXPIRED_TO_ABSTAIN",
    }
    missing = required - states
    assert not missing, f"missing states: {sorted(missing)}"


def test_every_state_is_reachable_from_proposed() -> None:
    doc = _load()
    transitions = doc["transitions"]
    adjacency: dict[str, set[str]] = {}
    for t in transitions:
        adjacency.setdefault(t["from"], set()).add(t["to"])
    reachable = {"PROPOSED"}
    frontier = ["PROPOSED"]
    while frontier:
        node = frontier.pop()
        for nxt in adjacency.get(node, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    unreachable = set(doc["states"]) - reachable
    assert not unreachable, f"unreachable states: {sorted(unreachable)}"


def test_terminal_states_have_no_outgoing_transitions() -> None:
    doc = _load()
    terminal = set(doc["terminal_states"])
    outgoing = {t["from"] for t in doc["transitions"]}
    violations = terminal & outgoing
    assert not violations, f"terminal states with outgoing transitions: {sorted(violations)}"
    # UNKNOWN is explicitly terminal in v1 (maintainer decision: manual
    # resolution + optional probe; resolution produces a NEW record, never a
    # transition out of UNKNOWN).
    assert "UNKNOWN" in terminal


def test_v1_decisions_are_recorded() -> None:
    doc = _load()
    decisions = doc["v1_decisions"]
    assert decisions["execute_api"] == "synchronous"
    assert decisions["envelope_updates"] == "append_only_revisions"
    assert decisions["unknown_resolution"] == "manual_with_optional_probe"
    assert decisions["proposal_id"] == "new_canonical_uuid4"
