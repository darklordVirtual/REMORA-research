# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Execution lifecycle as a runtime authority (FT-01).

``schemas/execution_lifecycle_v1.yaml`` is the canonical proposal-to-effect
state machine (maintainer contract decisions 2026-08-05; design
``docs/design/execution-lifecycle-outbox-v1.md``). This module loads that
schema — the transition table is NEVER duplicated in code — and exposes:

- :class:`LifecycleModel`: the parsed model (states, terminal states,
  ``(state, event) -> state`` transition map);
- :class:`LifecycleTracker`: a per-proposal cursor that applies declared
  events and raises :class:`IllegalTransition` on anything the model does
  not allow — an illegal transition is a bug surfacing, never a silent
  drift.

Realization status is honest by construction: the schema declares the
outbox states (``DISPATCH_PENDING`` onward) AHEAD of their implementation
(FT-02), so this module can model them while the fasttrack register
remains the authority on what is actually wired. Conformance of the live
``/v1/execution`` event stream against this model is the next FT-01
slice (it touches the protected execution path).
"""
from __future__ import annotations

from remora.errors import RemoraError

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "execution_lifecycle_v1.yaml"
)

INITIAL_STATE = "PROPOSED"


class IllegalTransition(RemoraError):
    """A declared event was applied in a state the model does not allow."""

    code = "illegal_lifecycle_transition"
    category = "governance"


@dataclass(frozen=True)
class LifecycleModel:
    """The parsed lifecycle schema: single source of truth for transitions."""

    states: frozenset[str]
    terminal_states: frozenset[str]
    #: ``(from_state, event) -> to_state``
    transitions: dict[tuple[str, str], str]
    version: int

    @classmethod
    def load(cls, path: Path | None = None) -> "LifecycleModel":
        raw = yaml.safe_load((path or _SCHEMA_PATH).read_text(encoding="utf-8"))
        transitions: dict[tuple[str, str], str] = {}
        for row in raw["transitions"]:
            # YAML 1.1 parses a bare `on` key as boolean True (the GitHub
            # workflow gotcha); accept both spellings of the event key.
            event = row.get("on", row.get(True))
            key = (str(row["from"]), str(event))
            if key in transitions:
                raise ValueError(
                    f"ambiguous transition: {key} maps to both "
                    f"{transitions[key]} and {row['to']}"
                )
            transitions[key] = str(row["to"])
        return cls(
            states=frozenset(str(s) for s in raw["states"]),
            terminal_states=frozenset(str(s) for s in raw["terminal_states"]),
            transitions=transitions,
            version=int(raw["version"]),
        )


_DEFAULT_MODEL: LifecycleModel | None = None


def default_model() -> LifecycleModel:
    global _DEFAULT_MODEL
    if _DEFAULT_MODEL is None:
        _DEFAULT_MODEL = LifecycleModel.load()
    return _DEFAULT_MODEL


@dataclass
class LifecycleTracker:
    """Cursor over one proposal's lifecycle; refuses undeclared moves."""

    model: LifecycleModel = field(default_factory=default_model)
    state: str = INITIAL_STATE
    trail: tuple[tuple[str, str, str], ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.state in self.model.terminal_states

    def transitions_key(self, state: str, event: str) -> str | None:
        return self.model.transitions.get((state, event))

    def apply(self, event: str) -> str:
        """Apply a declared event; return the new state or raise.

        A refused application leaves the tracker unchanged — the refusal
        itself is the signal, and callers decide whether it is fatal.
        """
        nxt = self.model.transitions.get((self.state, event))
        if nxt is None:
            raise IllegalTransition(
                f"event {event!r} is not legal in state {self.state!r} "
                f"(lifecycle v{self.model.version})"
            )
        self.trail = self.trail + ((self.state, event, nxt),)
        self.state = nxt
        return nxt


# ── Runtime conformance (FT-01 slice 4) ─────────────────────────────────────

#: ReviewQueue ItemStatus value -> lifecycle state. The model collapses
#: human approval and post-re-gate authorization into AUTHORIZED; the two
#: dispatch-refusal terminals map onto the model's terminals.
ITEM_STATUS_STATE: dict[str, str] = {
    "pending": "REVIEW_PENDING",
    "approved": "AUTHORIZED",
    "expired_to_abstain": "EXPIRED_TO_ABSTAIN",
    # A reviewer's explicit refusal maps to the model's REFUSED, the same
    # terminal a re-gate refusal reaches: both mean "authorization was
    # withheld". The queue keeps them distinct in its own vocabulary.
    "rejected": "REFUSED",
    "authorized": "AUTHORIZED",
    "executed": "SUCCEEDED",
    "dispatch_refused": "REFUSED",
    "dispatch_failed": "FAILED",
    # Dispatch began and the absence of an effect is not proven. The model
    # already had this state and this transition
    # (DISPATCHING -> UNKNOWN, on: crash_or_timeout_after_possible_effect);
    # the queue had no vocabulary to reach it, so a raising tool was recorded
    # as FAILED -- a state the model reserves for tool_raised_pre_effect.
    "dispatch_unknown": "UNKNOWN",
}


def check_transition(state: str, event: str) -> str:
    """Validate one runtime transition against the declared model.

    Returns the destination state, or raises :class:`IllegalTransition`.
    Used by /v1/execution as defense-in-depth: the queue's own guards stay
    the primary refusal path; this catches drift between the declared
    machine and what the endpoints actually do.
    """
    model = default_model()
    nxt = model.transitions.get((state, event))
    if nxt is None:
        raise IllegalTransition(
            f"runtime performed {event!r} from {state!r}, which lifecycle "
            f"v{model.version} does not declare"
        )
    return nxt
