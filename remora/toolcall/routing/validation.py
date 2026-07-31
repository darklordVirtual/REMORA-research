# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Which arguments policy requires validated before autonomous execution.

§27 left the engine epistemically honest — UNKNOWN outside a covered scope
rather than an invented UNSUPPORTED — but not yet acting on that honesty:
UNKNOWN fell through to the low-consequence ACCEPT path, so on an uncovered
domain 61.5% of corrupted identifiers were accepted autonomously.

Routing every UNKNOWN to VERIFY is the wrong fix. It rebuilds the constant
blocker of §21 one level up: a system that verifies everything it cannot
confirm verifies everything.

**The requirement is decided independently of index coverage.** Whether an
argument must be validated is a property of what it steers, not of whether we
happen to hold a table for it. An argument that determines where the action
lands — a customer, an account, a recipient, a deployment target — must be
confirmed before autonomous execution. Free text must not be, because an
authoritative membership test is meaningless for it.

Unrecognised roles default to OPTIONAL rather than REQUIRED. Defaulting to
REQUIRED would make every unfamiliar tool signature a source of friction, which
is the constant-blocker failure mode again — this is one of the few places where
the conservative-looking default is the wrong one.
"""
from __future__ import annotations

import re
from enum import Enum


class ValidationRequirement(str, Enum):
    """Whether policy requires an argument's value confirmed before autonomy."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    NOT_APPLICABLE = "not_applicable"


#: Role tokens that make an argument target-steering. Deliberately conservative
#: and enumerated rather than pattern-guessed: an argument earns REQUIRED by
#: naming something the action acts upon.
_REQUIRES_VALIDATION: frozenset[str] = frozenset({
    # who and what the action operates on
    "customer", "account", "subscription", "line", "user", "member", "tenant",
    "principal", "role", "group",
    # where it lands
    "recipient", "recipients", "destination", "target", "address", "iban",
    "payee", "endpoint", "host",
    # which thing
    "device", "resource", "asset", "file", "path", "database", "table",
    "deployment", "environment", "cluster", "bucket",
    # commercial objects
    "order", "invoice", "payment", "transaction", "reservation", "booking",
    "ticket", "claim",
    # access objects
    "credential", "token", "key", "permission", "policy",
})

#: Free-text roles, where a membership test against a system of record has no
#: meaning. These are NOT_APPLICABLE rather than OPTIONAL: there is nothing to
#: validate, as opposed to nothing required.
_NOT_APPLICABLE: frozenset[str] = frozenset({
    "note", "notes", "subject", "body", "message", "text", "description",
    "comment", "comments", "reason", "summary", "content", "title",
})

_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(name: str) -> set[str]:
    return {tok for tok in _SPLIT.split(str(name).lower()) if tok}


def requirement_for(argument_name: str) -> ValidationRequirement:
    """Classify one argument by what it steers."""
    tokens = _tokens(argument_name)
    if tokens & _NOT_APPLICABLE:
        return ValidationRequirement.NOT_APPLICABLE
    if tokens & _REQUIRES_VALIDATION:
        return ValidationRequirement.REQUIRED
    return ValidationRequirement.OPTIONAL


def unvalidated_required(statuses: dict[str, bool | None]) -> tuple[str, ...]:
    """Arguments that policy requires validated and that are not confirmed.

    *statuses* maps argument name to its value status as the policy contract
    carries it: ``True`` supported, ``False`` unsupported, ``None`` unknown.
    Both unsupported and unknown count as unvalidated — the first because it is
    confirmed wrong, the second because nothing confirms it right.
    """
    return tuple(
        name
        for name, status in statuses.items()
        if requirement_for(name) is ValidationRequirement.REQUIRED and status is not True
    )
