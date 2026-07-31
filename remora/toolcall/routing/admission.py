# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Coverage admission for a discrimination holdout (§29 remediation).

§29 spent a blind set that could not test its own hypothesis: 836 of 942
wrong-argument episodes were unjudgeable because the index did not cover the
arguments the tasks used. The check that would have caught it was cheap and
available before locking.

This gate decides whether a candidate set is *eligible* to be sealed as a
discrimination track. It reads only structural facts — argument names, the
coverage manifest, whether completeness is declared, and how many episodes are
therefore judgeable. It never runs the router, never reads a prediction and
never computes accuracy, so running it does not spend the set. A test asserts
that structurally by forbidding the imports.

Eligibility is assessed per argument role and then in aggregate. A pooled
fraction alone can hide that one important role is almost entirely uncovered,
which is how §29 passed a casual inspection.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from remora.toolcall.routing.compatibility import ArgumentValueStatus, StateIndex
from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.mutations import MutationFamily, family_of

#: Pre-registered admission threshold. Set above the 80% floor discussed in
#: review, because a pooled figure can mask a single dead role.
MINIMUM_JUDGEABLE_FRACTION = 0.90

#: A role must contribute at least this many judgeable episodes to be admitted,
#: so a role that is technically covered but rare cannot carry the aggregate.
MINIMUM_ROLE_EPISODES = 20


@dataclass(frozen=True)
class RoleCoverage:
    """Judgeability for one argument role."""

    role: str
    identity_n: int
    wrong_arg_n: int
    judgeable_n: int

    @property
    def judgeable_fraction(self) -> float:
        total = self.identity_n + self.wrong_arg_n
        return self.judgeable_n / total if total else 0.0

    @property
    def eligible(self) -> bool:
        return (
            self.judgeable_n >= MINIMUM_ROLE_EPISODES
            and self.judgeable_fraction >= MINIMUM_JUDGEABLE_FRACTION
        )


@dataclass(frozen=True)
class AdmissionResult:
    status: str
    observed_judgeable_fraction: float
    minimum_judgeable_fraction: float
    eligible_argument_roles: tuple[str, ...] = ()
    excluded_argument_roles: tuple[str, ...] = ()
    per_role: tuple[RoleCoverage, ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "minimum_judgeable_fraction": self.minimum_judgeable_fraction,
            "observed_judgeable_fraction": round(self.observed_judgeable_fraction, 4),
            "eligible_argument_roles": list(self.eligible_argument_roles),
            "excluded_argument_roles": list(self.excluded_argument_roles),
            "per_role": [
                {
                    "role": r.role,
                    "identity_n": r.identity_n,
                    "wrong_arg_n": r.wrong_arg_n,
                    "judgeable_n": r.judgeable_n,
                    "judgeable_fraction": round(r.judgeable_fraction, 4),
                    "eligible": r.eligible,
                }
                for r in self.per_role
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2, sort_keys=True) + "\n"


def assess_admission(
    episodes: list[RoutingEpisode], state: StateIndex
) -> AdmissionResult:
    """Decide whether *episodes* may be sealed as a discrimination track.

    An argument occurrence is judgeable when the index can determine its status
    at all — SUPPORTED or UNSUPPORTED. UNKNOWN means the discriminating signal
    is absent, so the episode can neither succeed nor fail at discrimination and
    must not be counted as either.
    """
    families = (MutationFamily.IDENTITY, MutationFamily.WRONG_ARG_VALUE)
    counts: dict[str, dict[str, int]] = {}

    for episode in episodes:
        family = family_of(episode)
        if family not in families:
            continue
        key = "identity" if family is MutationFamily.IDENTITY else "wrong_arg"
        for name, value in episode.proposed_tool_args.items():
            if not isinstance(value, str):
                continue
            bucket = counts.setdefault(
                name, {"identity": 0, "wrong_arg": 0, "judgeable": 0}
            )
            bucket[key] += 1
            if (
                state.status(episode.domain, name, value)
                is not ArgumentValueStatus.UNKNOWN
            ):
                bucket["judgeable"] += 1

    per_role = tuple(
        sorted(
            (
                RoleCoverage(name, b["identity"], b["wrong_arg"], b["judgeable"])
                for name, b in counts.items()
            ),
            key=lambda r: (-r.judgeable_n, r.role),
        )
    )
    eligible = tuple(r.role for r in per_role if r.eligible)
    excluded = tuple(r.role for r in per_role if not r.eligible)

    admitted = [r for r in per_role if r.eligible]
    total = sum(r.identity_n + r.wrong_arg_n for r in admitted)
    judgeable = sum(r.judgeable_n for r in admitted)
    fraction = judgeable / total if total else 0.0

    status = (
        "eligible"
        if eligible and fraction >= MINIMUM_JUDGEABLE_FRACTION
        else "ineligible"
    )
    return AdmissionResult(
        status=status,
        observed_judgeable_fraction=fraction,
        minimum_judgeable_fraction=MINIMUM_JUDGEABLE_FRACTION,
        eligible_argument_roles=eligible,
        excluded_argument_roles=excluded,
        per_role=per_role,
    )
