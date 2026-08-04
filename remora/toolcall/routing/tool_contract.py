# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Declared tool semantics: what a tool *is for*, not just what it accepts.

``tool_registry.py`` answers "can this call's required parameters be sourced?".
That is a question about form. §34 measured what form alone cannot see: on
sealed external data, 86.8% of substituted calls were accepted because a
well-formed call for the wrong tool satisfies every structural signal. §35's
value grounding cut that to 11.6% on development data by asking where the
argument *values* came from — but 30 of 258 still passed, because their values
coincidentally occurred in the task.

The residue is not a threshold problem. It is a missing declaration. A registry
that says ``cancel_booking`` takes a ``booking_id`` cannot distinguish it from
``get_booking``; a registry that says one *cancels* and the other *reads* can.

This module is that declaration, and it is deployment-supplied infrastructure
rather than benchmark metadata: an integrator already knows which of their tools
mutate and what they act on. Nothing here is inferred from a tool's name — §32
recorded what verb heuristics cost when ``assign``, ``close`` and ``approve``
were absent from the mutating-verb list and thirty writes were scored as reads.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: Effects that read state without changing it. Anything not listed is treated
#: as changing state, so an unrecognised effect fails toward caution rather
#: than toward autonomy.
READ_EFFECTS = frozenset({"read", "retrieve", "search", "list", "get", "query", "lookup"})


@dataclass(frozen=True)
class ToolContract:
    """What a tool does, declared by the deployment that owns it."""

    tool: str
    #: The capability family it belongs to, e.g. ``booking_management``. Two
    #: tools in different families are never substitutes for one another.
    capability: str
    #: The single effect this tool has: ``read``, ``create``, ``cancel``,
    #: ``update``, ``delete``, ... Compared against the task's requested effect.
    effect: str
    #: What it acts on, e.g. ``booking``. A hotel tool cannot answer a booking
    #: question however well-formed the call is.
    resource_type: str
    #: Whether it changes state. Declared, never derived from the name.
    mutation: bool
    #: argument name -> the role it plays, e.g.
    #: ``{"booking_id": "target_resource"}``. Roles are how an intent says
    #: *what* is being acted on without knowing the tool's parameter names.
    argument_roles: Mapping[str, str] = None  # type: ignore[assignment]
    #: The state this tool is declared to leave behind: dotted field -> value,
    #: e.g. ``{"work_order.status": "closed"}``. Declared by the deployment,
    #: never inferred. Empty means *nothing is declared about the effect*,
    #: which stays UNKNOWN rather than becoming "no effect" — a mutating tool
    #: with no declared delta is undeclared, not harmless.
    state_delta: Mapping[str, str] = None  # type: ignore[assignment]
    #: Named facts that must hold before this tool may run, e.g.
    #: ``("closure_approved",)``. Checked against an authoritative fact set;
    #: a precondition nobody can adjudicate yields UNKNOWN, never "met".
    preconditions: tuple[str, ...] = ()
    #: Declared value transformations per argument role, e.g.
    #: ``{"pressure": "bar\u2194kPa", "timestamp": "ISO-8601 normalisation"}``.
    #: Written by the contract author from tool documentation before test
    #: scenarios are seen.  The transforms are not evaluated here — this is a
    #: declaration, not an engine.  Any change to canonicalisations changes the
    #: contract hash, preventing silent weakening through omission.
    canonicalisations: Mapping[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "argument_roles", dict(self.argument_roles or {}))
        object.__setattr__(self, "state_delta", dict(self.state_delta or {}))
        object.__setattr__(self, "preconditions", tuple(self.preconditions or ()))
        object.__setattr__(self, "canonicalisations", dict(self.canonicalisations or {}))
        if any(v == "" for v in self.canonicalisations.values()):
            raise ValueError(
                f"{self.tool}: canonicalisations must have non-empty descriptions; "
                f"an empty string is indistinguishable from an absent entry"
            )
        if self.is_read and self.state_delta:
            # A read that declares a post-state is self-contradictory. As with
            # the mutation check below, the contradiction is refused at
            # construction: resolving it later would mean choosing which half
            # of a broken declaration to believe, while a call is pending.
            raise ValueError(
                f"{self.tool}: effect {self.effect!r} is a read effect but the "
                f"contract declares a state_delta {dict(self.state_delta)!r}; a "
                f"read cannot leave a changed state behind"
            )
        if self.mutation is False and self.effect.strip().lower() not in READ_EFFECTS:
            # A contract that declares a non-read effect while claiming not to
            # mutate is self-contradictory, and the contradiction resolves
            # toward autonomy — exactly the wrong direction. Refuse it at
            # construction rather than let it grant an accept later.
            raise ValueError(
                f"{self.tool}: effect {self.effect!r} is not a read effect, so "
                f"mutation must be True; a contract cannot declare a "
                f"state-changing effect and mutation=False"
            )

    @property
    def is_read(self) -> bool:
        return self.effect.strip().lower() in READ_EFFECTS and not self.mutation

    def roles_present(self, proposed_args: Mapping[str, Any]) -> set[str]:
        """Roles this call actually fills, from the arguments it carries."""
        return {
            role
            for name, role in self.argument_roles.items()
            if name in proposed_args and proposed_args[name] not in (None, "")
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "effect": self.effect,
            "resource_type": self.resource_type,
            "mutation": self.mutation,
            "argument_roles": dict(sorted(self.argument_roles.items())),
            "state_delta": dict(sorted(self.state_delta.items())),
            "preconditions": list(self.preconditions),
            "canonicalisations": dict(sorted(self.canonicalisations.items())),
        }


@dataclass(frozen=True)
class ToolContractRegistry:
    """Deployment-declared contracts, keyed by tool name.

    Absence is ``None``, never a default contract. A tool nobody declared is
    unknown, and ``goal_match`` turns that into UNKNOWN rather than a mismatch:
    fabricating a contract would let an unmodelled deployment either block
    everything or, worse, accept on invented semantics.
    """

    contracts: Mapping[str, ToolContract]

    def __init__(self, contracts: Iterable[ToolContract] | Mapping[str, ToolContract]):
        resolved: dict[str, ToolContract]
        if isinstance(contracts, Mapping):
            resolved = dict(contracts)
        else:
            resolved = {}
            for c in contracts:
                if c.tool in resolved:
                    raise ValueError(
                        f"duplicate tool declaration: {c.tool!r} appears more "
                        f"than once in the contract bundle; a tool must have "
                        f"exactly one contract"
                    )
                resolved[c.tool] = c
        object.__setattr__(self, "contracts", resolved)

    def __contains__(self, tool: str) -> bool:
        return tool in self.contracts

    def get(self, tool: str | None) -> ToolContract | None:
        return self.contracts.get(tool) if tool else None

    def to_json_dict(self) -> dict[str, dict[str, Any]]:
        return {
            name: contract.to_json_dict()
            for name, contract in sorted(self.contracts.items())
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Mapping[str, Any]]) -> "ToolContractRegistry":
        contracts = []
        for tool, entry in data.items():
            roles = entry.get("argument_roles") or {}
            if not isinstance(roles, Mapping):
                raise ValueError(f"{tool}: 'argument_roles' must be a map")
            delta = entry.get("state_delta") or {}
            if not isinstance(delta, Mapping):
                raise ValueError(f"{tool}: 'state_delta' must be a map")
            preconditions = entry.get("preconditions") or ()
            if isinstance(preconditions, (str, bytes)) or not isinstance(
                preconditions, Iterable
            ):
                raise ValueError(f"{tool}: 'preconditions' must be a list of names")
            canonicalisations = entry.get("canonicalisations") or {}
            if not isinstance(canonicalisations, Mapping):
                raise ValueError(f"{tool}: 'canonicalisations' must be a map")
            contracts.append(
                ToolContract(
                    tool=tool,
                    capability=str(entry["capability"]),
                    effect=str(entry["effect"]),
                    resource_type=str(entry["resource_type"]),
                    mutation=bool(entry["mutation"]),
                    argument_roles={str(k): str(v) for k, v in roles.items()},
                    state_delta={str(k): str(v) for k, v in delta.items()},
                    preconditions=tuple(str(p) for p in preconditions),
                    canonicalisations={str(k): str(v) for k, v in canonicalisations.items()},
                )
            )
        return cls(contracts)
