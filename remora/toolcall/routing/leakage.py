# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Leakage gate: sealed ground truth must never reach the gate under evaluation.

NEGATIVE_RESULTS.md §17 records what this prevents: benchmark metadata leaked
into the gate's input, and the resulting headline claim had to be withdrawn.
Here the check is mechanical rather than a review convention.

Two things are enforced:

1. **Structural disjointness** — no predicate name may appear in the observable
   allowlist, and an episode's observable surface must match that allowlist
   exactly. This catches the realistic regression where someone adds ``route``
   or ``predicates`` to ``observable()`` for convenience.
2. **Payload disjointness** — no predicate name may appear as a *key* inside an
   observable payload such as ``proposed_tool_args``.

Deliberately not enforced: free-text value matching. ``untrusted_context`` is
attacker-controlled prose by construction and may contain any word; flagging it
would produce false positives without catching a real leak, since the gate
cannot read a label out of ordinary text.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from remora.toolcall.routing.episode import OBSERVABLE_FIELDS, RoutingEpisode
from remora.toolcall.routing.predicates import PREDICATE_FIELDS

#: Episode attributes that are sealed ground truth and must never be observable.
SEALED_FIELDS: frozenset[str] = frozenset(
    {
        "predicates",
        "route",
        "route_table_version",
        "matched_row",
        *PREDICATE_FIELDS,
    }
)


class LeakageError(AssertionError):
    """Raised when sealed ground truth is reachable from the observable surface."""


def check_field_sets() -> None:
    """Assert the observable allowlist and the sealed field set are disjoint.

    Import-time-cheap and independent of any episode, so it can run as a
    standalone CI step before any data exists.
    """
    overlap = SEALED_FIELDS & OBSERVABLE_FIELDS
    if overlap:
        raise LeakageError(
            f"observable allowlist contains sealed field(s): {sorted(overlap)}. "
            "The gate under evaluation would be able to read its own answer."
        )


def _leaked_keys(payload: Any, path: str) -> list[str]:
    """Return dotted paths of sealed names appearing as keys inside *payload*."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}"
            if isinstance(key, str) and key in SEALED_FIELDS:
                found.append(here)
            found.extend(_leaked_keys(value, here))
    elif isinstance(payload, (list, tuple)):
        for i, item in enumerate(payload):
            found.extend(_leaked_keys(item, f"{path}[{i}]"))
    return found


def check_episode(episode: RoutingEpisode) -> None:
    """Assert *episode*'s observable surface exposes no sealed ground truth."""
    observable = episode.observable()

    unexpected = set(observable) - set(OBSERVABLE_FIELDS)
    if unexpected:
        raise LeakageError(
            f"episode {episode.id}: observable() emitted non-allowlisted "
            f"field(s): {sorted(unexpected)}"
        )

    leaked = _leaked_keys(observable, "observable")
    if leaked:
        raise LeakageError(
            f"episode {episode.id}: sealed name(s) present as payload keys: "
            f"{sorted(leaked)}"
        )


def check_all(episodes: Iterable[RoutingEpisode]) -> int:
    """Run every check over *episodes*; return the number checked."""
    check_field_sets()
    count = 0
    for episode in episodes:
        check_episode(episode)
        count += 1
    return count
