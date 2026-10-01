# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The complete refusal contract of ``PolicyDecisionToken.check_bindings``.

``check_bindings`` answers one question: was this token minted for *this*
request. It is the half of verification that a non-strict gate still runs
after waiving the signature, so every one of its branches is load-bearing on a
path where nothing else is checking.

Nineteen of its mutants survived the 2026-09-21 sweep. The shape is familiar
from the gate-contract round recorded in ``docs/assurance/mutation_testing_v1.md``:
tests asserted that a bad token was refused without asserting *which* refusal,
so a mutant that swapped two reason literals, reordered the checks or moved a
boundary by one comparison operator changed nothing any test could see. An
operator reading ``token_expired`` in an audit log when the real cause was
``context_mismatch`` is looking at the wrong incident.

This module pins, for each branch: the exact reason literal, the precedence
between branches when a token fails several at once, the boundaries at their
exact instants, and the propagation of ``is_signed`` on every return.

Scope (declared, not exhaustive): the binding checks only. The signature
checks live in ``verify`` and are covered by the signing-contract suites; this
module deliberately constructs unsigned tokens so a signature verdict can
never mask a binding verdict.
"""

from __future__ import annotations

import pytest

from remora.enforcement.token import AuthorizationContext, PolicyDecisionToken

ISSUED = "2026-09-21T12:00:00+00:00"
EXPIRES = "2026-09-21T12:05:00+00:00"
INSIDE = "2026-09-21T12:02:00+00:00"
OBSERVATION = "obs-hash-1"

BOUND_CONTEXT = AuthorizationContext(tenant="acme", principal="svc-a")
OTHER_CONTEXT = AuthorizationContext(tenant="acme", principal="svc-b")


def _token(**overrides) -> PolicyDecisionToken:
    fields = {
        "action": "accept",
        "observation_hash": OBSERVATION,
        "request_id": "req-1",
        "issued_at": ISSUED,
        "expires_at": EXPIRES,
        "signature": "",
        "is_signed": False,
        "context_hash": BOUND_CONTEXT.hash(),
    }
    fields.update(overrides)
    return PolicyDecisionToken(**fields)


def test_a_token_bound_to_this_request_passes_every_check() -> None:
    result = _token().check_bindings(
        observation_hash=OBSERVATION, now=INSIDE, context=BOUND_CONTEXT
    )
    assert (result.verified, result.reason) == (True, "ok")


@pytest.mark.parametrize(
    ("name", "kwargs", "call", "expected_reason"),
    [
        (
            "a token carrying no context hash, checked against a context",
            {"context_hash": ""},
            {"now": INSIDE, "context": BOUND_CONTEXT},
            "context_unbound",
        ),
        (
            "a token bound to a different context",
            {},
            {"now": INSIDE, "context": OTHER_CONTEXT},
            "context_mismatch",
        ),
        (
            "a token with no expiry when expiry is mandatory",
            {"expires_at": None},
            {"now": INSIDE},
            "missing_expiry",
        ),
        (
            "a token whose timestamps do not parse",
            {"expires_at": "not-a-timestamp"},
            {"now": INSIDE},
            "expiry_unparseable",
        ),
        (
            "a token redeemed before it was issued",
            {},
            {"now": "2026-09-21T11:59:59+00:00"},
            "token_not_yet_valid",
        ),
        (
            "a token redeemed after it expired",
            {},
            {"now": "2026-09-21T12:06:00+00:00"},
            "token_expired",
        ),
        (
            "a token bound to a different observation",
            {},
            {"now": INSIDE, "observation_hash": "obs-hash-2"},
            "observation_hash_mismatch",
        ),
    ],
)
def test_each_branch_reports_its_own_reason(
    name: str, kwargs: dict, call: dict, expected_reason: str
) -> None:
    result = _token(**kwargs).check_bindings(**call)
    assert result.verified is False, f"{name} must not verify"
    assert result.reason == expected_reason, (
        f"{name} reported {result.reason!r}; an operator reading that literal in an "
        f"audit log would diagnose the wrong failure (expected {expected_reason!r})"
    )


def test_every_reason_literal_is_distinct() -> None:
    """Two branches sharing a literal make the audit record ambiguous."""
    reasons = [
        _token(context_hash="").check_bindings(now=INSIDE, context=BOUND_CONTEXT).reason,
        _token().check_bindings(now=INSIDE, context=OTHER_CONTEXT).reason,
        _token(expires_at=None).check_bindings(now=INSIDE).reason,
        _token(expires_at="not-a-timestamp").check_bindings(now=INSIDE).reason,
        _token().check_bindings(now="2026-09-21T11:00:00+00:00").reason,
        _token().check_bindings(now="2026-09-21T13:00:00+00:00").reason,
        _token().check_bindings(now=INSIDE, observation_hash="other").reason,
        _token().check_bindings(now=INSIDE).reason,
    ]
    assert len(set(reasons)) == len(reasons), f"reason literals collide: {reasons}"


def test_the_context_check_precedes_the_expiry_check() -> None:
    """Order is contract: the first thing wrong must be the thing reported."""
    expired_and_foreign = _token().check_bindings(
        now="2026-09-21T13:00:00+00:00", context=OTHER_CONTEXT
    )
    assert expired_and_foreign.reason == "context_mismatch", (
        "a token that is both expired and bound to another context must report the "
        "context, or a stolen token looks like a stale one"
    )


def test_the_expiry_check_precedes_the_observation_check() -> None:
    expired_and_rebound = _token().check_bindings(
        now="2026-09-21T13:00:00+00:00", observation_hash="obs-hash-2"
    )
    assert expired_and_rebound.reason == "token_expired"


def test_expiry_is_exclusive_and_issuance_is_inclusive_at_the_exact_instant() -> None:
    """The two boundaries, sitting exactly on them.

    A mutant flipping ``>=`` to ``>`` or ``<`` to ``<=`` is invisible unless a
    test stands on the instant itself.
    """
    at_issuance = _token().check_bindings(now=ISSUED)
    assert (at_issuance.verified, at_issuance.reason) == (True, "ok"), (
        "a token must be usable at its own issued_at instant"
    )

    at_expiry = _token().check_bindings(now=EXPIRES)
    assert (at_expiry.verified, at_expiry.reason) == (False, "token_expired"), (
        "the validity window is [issued_at, expires_at); the expiry instant is outside it"
    )

    just_inside = _token().check_bindings(now="2026-09-21T12:04:59.999999+00:00")
    assert just_inside.verified is True


def test_naive_timestamps_are_coerced_rather_than_raising() -> None:
    """Fail-closed means a verdict, never an uncaught TypeError."""
    naive = _token(issued_at="2026-09-21T12:00:00", expires_at="2026-09-21T12:05:00")
    inside = naive.check_bindings(now="2026-09-21T12:02:00")
    assert (inside.verified, inside.reason) == (True, "ok")

    after = naive.check_bindings(now="2026-09-21T12:06:00")
    assert (after.verified, after.reason) == (False, "token_expired")


def test_relaxing_expiry_waives_only_the_missing_expiry_branch() -> None:
    """``require_expiry=False`` is the unsigned development path, not a bypass."""
    no_expiry = _token(expires_at=None)
    assert no_expiry.check_bindings(now=INSIDE, require_expiry=False).verified is True

    still_checked = no_expiry.check_bindings(
        now=INSIDE, require_expiry=False, observation_hash="obs-hash-2"
    )
    assert still_checked.reason == "observation_hash_mismatch", (
        "waiving mandatory expiry must not waive observation binding"
    )

    expired = _token().check_bindings(now="2026-09-21T13:00:00+00:00", require_expiry=False)
    assert expired.reason == "token_expired", (
        "an expiry that IS set is still enforced when require_expiry is False"
    )


def test_an_argument_left_out_is_a_check_not_run() -> None:
    """Omitting observation_hash or context must not silently pass a bound token."""
    assert _token().check_bindings(now=INSIDE).verified is True
    assert _token(context_hash="").check_bindings(now=INSIDE).verified is True, (
        "no context supplied means the context check does not run; it must not "
        "refuse on a hash it was never asked to compare"
    )


@pytest.mark.parametrize("is_signed", [True, False])
def test_is_signed_is_propagated_on_every_return(is_signed: bool) -> None:
    """The gate reads is_signed off this result to decide what it may claim."""
    signed_token = _token(is_signed=is_signed, signature="deadbeef" if is_signed else "")
    verdicts = [
        signed_token.check_bindings(observation_hash=OBSERVATION, now=INSIDE),
        signed_token.check_bindings(now=INSIDE, context=OTHER_CONTEXT),
        signed_token.check_bindings(now="2026-09-21T13:00:00+00:00"),
        signed_token.check_bindings(now=INSIDE, observation_hash="obs-hash-2"),
        _token(is_signed=is_signed, expires_at=None).check_bindings(now=INSIDE),
        _token(is_signed=is_signed, expires_at="nope").check_bindings(now=INSIDE),
        _token(is_signed=is_signed, context_hash="").check_bindings(
            now=INSIDE, context=BOUND_CONTEXT
        ),
    ]
    assert all(verdict.is_signed is is_signed for verdict in verdicts), (
        "a binding refusal that drops is_signed lets a non-strict gate claim a token "
        "was verified when it was not"
    )
