# Author: Stian Skogbrott
# License: Apache-2.0
"""Degradation ladder G0–G4 with tamper-evident recorded mode transitions.

Implements REM-032 (design: ``docs/assurance/resilience_plan_v1.md`` §1–2).
The canonical mode-degradation rule — *every* degradation from full
governance toward hard-blocks-only must be recorded — previously existed as
a stated principle with no dedicated recorder. This module provides it:

- :class:`GovernanceLink` — the monitored links (telemetry, external PDP,
  oracle pool, control plane).
- :class:`GovernanceMode` — the ladder G0..G4; the current mode is the worst
  mode implied by any down link.
- :class:`DegradationRecorder` — link up/down reporting; every mode
  transition (in either direction) appends a :class:`ChainedEvent` to a
  hash-chained, append-only event log (same tamper-evidence discipline as
  the decision audit chain: each entry hashes its predecessor).
- :func:`g4_refuses` — the G4 policy: with the control plane unreachable,
  mutating or production-targeting actions must refuse; read-only actions
  may proceed with a warning. Uses the decision engine's own action-type
  and environment vocabularies so hook and engine cannot drift apart.

The recorder is deliberately storage-agnostic: events accumulate in memory,
can be exported as JSONL, and an optional ``sink`` callback lets callers
forward each event into their audit pipeline.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from remora.policy.decision_engine import (
    _MUTATING_TYPES,
    _PROD_ENVS,
)

# ---------------------------------------------------------------------------
# Links and modes
# ---------------------------------------------------------------------------


class GovernanceLink(str, Enum):
    TELEMETRY = "telemetry"              # AROMER / learning telemetry
    EXTERNAL_PDP = "external_pdp"        # OPA daemon
    ORACLE_POOL = "oracle_pool"          # consensus oracle quorum
    CONTROL_PLANE = "control_plane"      # PDP reachable from the agent hook


class GovernanceMode(str, Enum):
    G0_FULL = "G0_full_governance"
    G1_NO_LEARNING = "G1_no_learning"
    G2_NO_EXTERNAL_PDP = "G2_no_external_pdp"
    G3_NO_ORACLES = "G3_no_oracles"
    G4_CONTROL_PLANE_UNREACHABLE = "G4_control_plane_unreachable"


# Which mode a single down link implies, and ladder severity (worst wins).
_LINK_MODE: dict[GovernanceLink, GovernanceMode] = {
    GovernanceLink.TELEMETRY: GovernanceMode.G1_NO_LEARNING,
    GovernanceLink.EXTERNAL_PDP: GovernanceMode.G2_NO_EXTERNAL_PDP,
    GovernanceLink.ORACLE_POOL: GovernanceMode.G3_NO_ORACLES,
    GovernanceLink.CONTROL_PLANE: GovernanceMode.G4_CONTROL_PLANE_UNREACHABLE,
}

MODE_SEVERITY: dict[GovernanceMode, int] = {
    GovernanceMode.G0_FULL: 0,
    GovernanceMode.G1_NO_LEARNING: 1,
    GovernanceMode.G2_NO_EXTERNAL_PDP: 2,
    GovernanceMode.G3_NO_ORACLES: 3,
    GovernanceMode.G4_CONTROL_PLANE_UNREACHABLE: 4,
}


def g4_refuses(action_type: str | None, target_environment: str | None) -> bool:
    """G4 policy: does this action stop when the control plane is unreachable?

    Mutating action types and production-targeting environments refuse;
    everything else may proceed with a warning. Vocabulary is imported from
    the decision engine so this cannot drift from the engine's own
    classification.
    """
    normalized_type = (action_type or "").strip().lower()
    normalized_env = (target_environment or "").strip().lower()
    return normalized_type in _MUTATING_TYPES or normalized_env in _PROD_ENVS


# ---------------------------------------------------------------------------
# Tamper-evident event log (shared with the review queue, REM-033)
# ---------------------------------------------------------------------------

_GENESIS = "0" * 64


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class ChainedEvent:
    """One append-only, hash-chained event.

    ``entry_hash = sha256(prev_hash || canonical(payload))`` — modifying any
    recorded event (or removing one) breaks verification of every later
    entry. Tamper-evident, not tamper-proof: the same WORM caveat as the
    decision audit chain applies.
    """

    sequence: int
    timestamp: str
    kind: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChainedEventLog:
    """Append-only event log with per-entry hash chaining."""

    def __init__(
        self,
        sink: Callable[[ChainedEvent], None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._events: list[ChainedEvent] = []
        self._sink = sink
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def events(self) -> tuple[ChainedEvent, ...]:
        return tuple(self._events)

    def append(self, kind: str, payload: dict[str, Any]) -> ChainedEvent:
        prev_hash = self._events[-1].entry_hash if self._events else _GENESIS
        timestamp = self._now_fn().isoformat()
        body = {
            "sequence": len(self._events),
            "timestamp": timestamp,
            "kind": kind,
            "payload": payload,
        }
        entry_hash = hashlib.sha256(
            (prev_hash + _canonical(body)).encode("utf-8")
        ).hexdigest()
        event = ChainedEvent(
            sequence=len(self._events),
            timestamp=timestamp,
            kind=kind,
            payload=payload,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        self._events.append(event)
        if self._sink is not None:
            self._sink(event)
        return event

    def verify(self) -> tuple[bool, list[str]]:
        """Recompute the chain; every break is reported (complete defect set)."""
        problems: list[str] = []
        prev_hash = _GENESIS
        for i, event in enumerate(self._events):
            if event.sequence != i:
                problems.append(f"sequence_gap_at:{i}")
            if event.prev_hash != prev_hash:
                problems.append(f"chain_break_at:{i}")
            body = {
                "sequence": event.sequence,
                "timestamp": event.timestamp,
                "kind": event.kind,
                "payload": event.payload,
            }
            expected = hashlib.sha256(
                (event.prev_hash + _canonical(body)).encode("utf-8")
            ).hexdigest()
            if expected != event.entry_hash:
                problems.append(f"hash_mismatch_at:{i}")
            prev_hash = event.entry_hash
        return (not problems, problems)

    def export_jsonl(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(_canonical(event.to_dict()) + "\n")


# ---------------------------------------------------------------------------
# Degradation recorder
# ---------------------------------------------------------------------------


@dataclass
class DegradationRecorder:
    """Tracks link health and records every governance-mode transition.

    Callers report ``link_down`` / ``link_up`` as they observe outages
    (an OPA request failing over, an oracle quorum miss, a hook timeout).
    The current mode is derived — worst mode implied by any down link — and
    every transition, in either direction, is appended to the event log.
    """

    sink: Callable[[ChainedEvent], None] | None = None
    now_fn: Callable[[], datetime] | None = None
    _down: set[GovernanceLink] = field(default_factory=set)
    _log: ChainedEventLog = field(init=False)
    _mode: GovernanceMode = field(default=GovernanceMode.G0_FULL, init=False)

    def __post_init__(self) -> None:
        self._log = ChainedEventLog(sink=self.sink, now_fn=self.now_fn)

    @property
    def current_mode(self) -> GovernanceMode:
        return self._mode

    @property
    def down_links(self) -> frozenset[GovernanceLink]:
        return frozenset(self._down)

    @property
    def events(self) -> tuple[ChainedEvent, ...]:
        return self._log.events

    def verify_chain(self) -> tuple[bool, list[str]]:
        return self._log.verify()

    def export_jsonl(self, path: str | Path) -> None:
        self._log.export_jsonl(path)

    def link_down(self, link: GovernanceLink, cause: str) -> GovernanceMode:
        self._down.add(link)
        return self._transition(cause)

    def link_up(self, link: GovernanceLink, cause: str) -> GovernanceMode:
        self._down.discard(link)
        return self._transition(cause)

    def _compute_mode(self) -> GovernanceMode:
        if not self._down:
            return GovernanceMode.G0_FULL
        return max(
            (_LINK_MODE[link] for link in self._down),
            key=lambda mode: MODE_SEVERITY[mode],
        )

    def _transition(self, cause: str) -> GovernanceMode:
        new_mode = self._compute_mode()
        if new_mode != self._mode:
            self._log.append(
                "governance_mode_transition",
                {
                    "from_mode": self._mode.value,
                    "to_mode": new_mode.value,
                    "cause": cause,
                    "down_links": sorted(link.value for link in self._down),
                    "direction": (
                        "degradation"
                        if MODE_SEVERITY[new_mode] > MODE_SEVERITY[self._mode]
                        else "recovery"
                    ),
                },
            )
            self._mode = new_mode
        return self._mode
