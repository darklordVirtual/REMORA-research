# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Committed digests for the two hashes that bind a decision to its conditions.

``AuthorizationContext.hash`` and ``_hash_observation`` are consumed by
comparison: a token is redeemed when the context hash it carries equals the one
recomputed at redemption. Every roundtrip test is therefore structurally blind
to a change applied to both sides. Rename a key, drop the separators argument,
stop sorting, or default an absent optional field to the empty string, and the
suite still passes while every token issued before the change stops verifying
against a peer that did not change with it.

The mutation sweep says the same thing in numbers: 29 mutants across
``AuthorizationContext.hash``, ``_hash_observation`` and ``_canonical_payload``
survived the 2026-09-21 measurement. This is the defect class the
``token._canonical_payload`` cluster had, and the remedy is the one that took
that cluster to zero (``tests/test_token_golden_vectors.py``): freeze the
output for fixed inputs, so the wire format cannot drift silently.

Scope (declared, not exhaustive): these vectors pin the digest for chosen
points of the optional-field lattice and the documented compatibility rules.
They say nothing about whether the hash is the right one to compute, only that
it is the one every already-issued token was bound with.

Regenerating a vector is a wire-format change. It invalidates every token and
lease issued under the old preimage, so it belongs in a reviewed diff that says
so, never in a fix that makes a red test green.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from remora.enforcement.token import AuthorizationContext, _hash_observation

# Each vector: the exact SHA-256 hex a context with these fields must produce.
CONTEXT_VECTORS: dict[str, tuple[AuthorizationContext, str]] = {
    "empty": (
        AuthorizationContext(),
        "a2fb178734a5a4f8fcb24633c8c653cf2fe84b41642030c160f3a3c04c32c26f",
    ),
    "six base fields": (
        AuthorizationContext(
            tenant="acme",
            principal="svc-a",
            target_environment="prod",
            policy_bundle_hash="pb-1",
            toolspec_hash="ts-1",
            intent_authority_hash="ia-1",
        ),
        "b76667bc1f17e2975539822f03bd876b0858f1a774affccf9510608a88ad11ff",
    ),
    "base plus a bound task": (
        AuthorizationContext(
            tenant="acme",
            principal="svc-a",
            target_environment="prod",
            policy_bundle_hash="pb-1",
            toolspec_hash="ts-1",
            intent_authority_hash="ia-1",
            context_id="ctx-1",
            task_id="task-1",
        ),
        "f52cde683c80cbd5cb688d26165ad9aba7ad2a85f7f956da06bbd6d8cf0eb96a",
    ),
    "task_id alone": (
        AuthorizationContext(task_id="task-1"),
        "b57ea296285b713035dbbb1906e5b6942cd4076a026a31f988e9dedb5bfaae43",
    ),
    "context_id alone": (
        AuthorizationContext(context_id="ctx-1"),
        "3f289e5b5388af79afc4feb5e1d63282b3ef36e897639e6f25e847e078be130e",
    ),
}


@pytest.mark.parametrize(
    ("name", "context", "expected"),
    [(name, context, digest) for name, (context, digest) in CONTEXT_VECTORS.items()],
)
def test_context_hash_matches_its_committed_vector(
    name: str, context: AuthorizationContext, expected: str
) -> None:
    assert context.hash() == expected, (
        f"the {name} authorization-context preimage changed: every token and lease "
        "issued under the old one stops verifying against a peer that has this change"
    )


def test_every_context_vector_is_distinct() -> None:
    """A hash that collapses two different authorizations binds neither."""
    digests = {digest for _, digest in CONTEXT_VECTORS.values()}
    assert len(digests) == len(CONTEXT_VECTORS)


def test_an_absent_optional_field_is_omitted_rather_than_defaulted() -> None:
    """The documented compatibility rule, asserted rather than trusted.

    A context that carries no task must hash exactly as it did before the task
    fields existed. Setting them to the empty string must not change anything,
    because an empty value changes the preimage as much as a populated one.
    """
    without = AuthorizationContext(tenant="acme")
    explicitly_empty = AuthorizationContext(tenant="acme", context_id="", task_id="")
    assert without.hash() == explicitly_empty.hash()

    with_task = AuthorizationContext(tenant="acme", task_id="task-1")
    assert with_task.hash() != without.hash(), (
        "a populated task_id must enter the preimage, or a token minted for one task "
        "is redeemable under another"
    )


def test_the_preimage_is_canonical_json_with_sorted_keys_and_no_whitespace() -> None:
    """Pins the serialization itself, not only its digest.

    A mutant that drops ``sort_keys`` or the compact separators produces a
    different preimage for the same fields. Reconstructing the exact bytes here
    means the failure names the serialization rule that moved.
    """
    context = AuthorizationContext(
        tenant="acme",
        principal="svc-a",
        target_environment="prod",
        policy_bundle_hash="pb-1",
        toolspec_hash="ts-1",
        intent_authority_hash="ia-1",
    )
    expected_preimage = json.dumps(
        {
            "intent_authority_hash": "ia-1",
            "policy_bundle_hash": "pb-1",
            "principal": "svc-a",
            "target_environment": "prod",
            "tenant": "acme",
            "toolspec_hash": "ts-1",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert "\n" not in expected_preimage and ", " not in expected_preimage
    assert context.hash() == hashlib.sha256(expected_preimage.encode()).hexdigest()


def test_each_bound_field_moves_the_digest() -> None:
    """Every field the docstring claims is bound must actually be in the preimage."""
    baseline = AuthorizationContext().hash()
    for field in (
        "tenant",
        "principal",
        "target_environment",
        "policy_bundle_hash",
        "toolspec_hash",
        "intent_authority_hash",
        "context_id",
        "task_id",
    ):
        moved = AuthorizationContext(**{field: "x"})
        assert moved.hash() != baseline, (
            f"{field} does not enter the authorization-context preimage, so a decision "
            f"made under one {field} is redeemable under another"
        )


@dataclasses.dataclass
class _Observation:
    kind: str
    score: float


OBSERVATION_VECTORS: dict[str, tuple[object, str]] = {
    "mapping": (
        {"b": 2, "a": 1},
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777",
    ),
    "dataclass": (
        _Observation(kind="tool_call", score=0.5),
        "3bb7659b1a6fb40d726342bf1ba02829717fd18ed64d9e046bacd4dd06e118ca",
    ),
    "scalar falls back to str": (
        7,
        "fd706e7f528e780342ee327f3c21fd40d1632d1688de1da3fb82fa63f197d894",
    ),
    "none falls back to str": (
        None,
        "7ab553d1c5e4b2e951a145a8db74e087161ed004510ff17114d690a571108a37",
    ),
}


@pytest.mark.parametrize(
    ("name", "observation", "expected"),
    [(name, obs, digest) for name, (obs, digest) in OBSERVATION_VECTORS.items()],
)
def test_observation_hash_matches_its_committed_vector(
    name: str, observation: object, expected: str
) -> None:
    assert _hash_observation(observation) == expected, (
        f"the observation preimage changed for the {name} case: a token bound to an "
        "observation before this change no longer matches the same observation after it"
    )


def test_observation_hash_is_key_order_independent() -> None:
    """Two spellings of one observation must bind identically, or binding is a lottery."""
    assert _hash_observation({"b": 2, "a": 1}) == _hash_observation({"a": 1, "b": 2})


def test_observation_hash_separates_the_three_input_kinds() -> None:
    """A dataclass, its dict form and its string form are different observations."""
    observation = _Observation(kind="tool_call", score=0.5)
    as_dict = dataclasses.asdict(observation)
    assert _hash_observation(observation) == _hash_observation(as_dict), (
        "a dataclass must hash as its field mapping, which is what the branch claims"
    )
    assert _hash_observation(str(observation)) != _hash_observation(observation)
