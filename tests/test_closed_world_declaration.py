# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An index may not infer its own completeness (§29 follow-up).

§26 fixed domain-level coverage. §29's diagnosis found the same error one level
deeper: `from_json_files` marked every scalar-valued key as closed-world
covered, so having seen the key `user_id` once was treated as holding *every*
user_id. On the banking track that produced 45 confirmed-invalid verdicts on
values tau2's own gold actions supplied — `friend_user_5839`, `619-555-0284`,
`account_ownership_dispute`.

Seeing a key is evidence of a key, never evidence of completeness. Completeness
is a property of how the data was assembled, which only the assembler knows, so
it must be declared rather than inferred.

The cost is deliberate: with nothing declared, no value is ever UNSUPPORTED and
the discrimination signal is inert. That is the correct default. A signal that
is silent until someone vouches for the data is preferable to one that invents
authority from a filename.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.toolcall.routing.compatibility import ArgumentValueStatus, StateIndex


@pytest.fixture
def doc(tmp_path) -> Path:
    p = tmp_path / "banking.json"
    p.write_text(
        '{"users": {"u1": {"user_id": "u1", "phone_number": "555-0100"}}}',
        encoding="utf-8",
    )
    return p


def test_an_undeclared_index_never_reports_unsupported(doc) -> None:
    """The §29 defect, as a contract test."""
    index = StateIndex.from_json_files([doc])
    assert index.status("banking", "user_id", "friend_user_5839") is (
        ArgumentValueStatus.UNKNOWN
    )


def test_an_undeclared_index_still_confirms_what_it_holds(doc) -> None:
    """Presence is positive evidence even without a completeness claim."""
    index = StateIndex.from_json_files([doc])
    assert index.status("banking", "user_id", "u1") is ArgumentValueStatus.SUPPORTED


def test_declared_completeness_enables_unsupported(doc) -> None:
    index = StateIndex.from_json_files(
        [doc], closed_world={"banking": {"user_id"}}
    )
    assert index.status("banking", "user_id", "friend_user_5839") is (
        ArgumentValueStatus.UNSUPPORTED
    )


def test_declaration_is_per_argument_not_per_domain(doc) -> None:
    """Vouching for user_id says nothing about phone_number."""
    index = StateIndex.from_json_files(
        [doc], closed_world={"banking": {"user_id"}}
    )
    assert index.status("banking", "phone_number", "619-555-0284") is (
        ArgumentValueStatus.UNKNOWN
    )


def test_declaring_an_uncovered_argument_does_not_invent_coverage(doc) -> None:
    """A declaration cannot conjure data the index does not hold."""
    index = StateIndex.from_json_files(
        [doc], closed_world={"banking": {"account_id"}}
    )
    assert index.status("banking", "account_id", "anything") is (
        ArgumentValueStatus.UNKNOWN
    )
