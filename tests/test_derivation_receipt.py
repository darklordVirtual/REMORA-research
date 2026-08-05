# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""DerivationReceipt (NEGATIVE_RESULTS theme 3): derived values, machine-verified.

Value grounding (§35) costs legitimate read autonomy on values that are
correct but not literally in the user's text — dates, unit conversions,
normalized numbers. The receipt makes the derivation itself checkable:
a declared source span (verbatim in the task text) plus a named transform
from a versioned whitelist, re-executed server-side and compared exactly.

Invariants under test:
- a receipt whose transform is not whitelisted is REJECTED — a model's
  explanation ("llm_reasoning") is not a derivation proof;
- a receipt whose source span is not verbatim in the task text is REJECTED;
- a receipt whose re-executed output differs from the claimed value is
  REJECTED (fail-closed: rejection leaves the value ungrounded, it never
  un-grounds anything else);
- verification is deterministic and locale-independent (English month
  names are parsed by an internal table, not strptime's locale).
"""
from __future__ import annotations

from remora.toolcall.routing.compatibility import StateIndex, values_grounded
from remora.toolcall.routing.derivation import (
    DERIVATION_TRANSFORMS_VERSION,
    DerivationReceipt,
    verify_receipt,
)

TASK = "Book the meeting room for April 3rd, 2024 and cap spend at $1,299."


def _receipt(**overrides) -> DerivationReceipt:
    base = dict(
        argument="date",
        value="2024-04-03",
        transform="en_date_to_iso",
        source_span="April 3rd, 2024",
    )
    base.update(overrides)
    return DerivationReceipt(**base)


# ── verify_receipt: the transform whitelist is the authority ────────────────

def test_english_date_receipt_verifies() -> None:
    assert verify_receipt(_receipt(), task_text=TASK) is True


def test_unknown_transform_is_rejected() -> None:
    r = _receipt(transform="llm_reasoning")
    assert verify_receipt(r, task_text=TASK) is False


def test_span_not_in_task_text_is_rejected() -> None:
    r = _receipt(source_span="April 4th, 2024")
    assert verify_receipt(r, task_text=TASK) is False


def test_wrong_output_is_rejected() -> None:
    r = _receipt(value="2024-04-04")
    assert verify_receipt(r, task_text=TASK) is False


def test_number_normalize_strips_currency_and_separators() -> None:
    r = DerivationReceipt(
        argument="budget", value=1299, transform="number_normalize",
        source_span="$1,299",
    )
    assert verify_receipt(r, task_text=TASK) is True


def test_number_normalize_wrong_number_rejected() -> None:
    r = DerivationReceipt(
        argument="budget", value=1300, transform="number_normalize",
        source_span="$1,299",
    )
    assert verify_receipt(r, task_text=TASK) is False


def test_unit_convert_uses_exact_table() -> None:
    task = "The cable run is 5 km through the west duct."
    r = DerivationReceipt(
        argument="length_m", value=5000, transform="unit_convert",
        source_span="5 km", params={"from_unit": "km", "to_unit": "m"},
    )
    assert verify_receipt(r, task_text=task) is True


def test_unit_convert_unknown_pair_rejected() -> None:
    task = "Transfer 3 gb of logs."
    r = DerivationReceipt(
        argument="size", value=3072, transform="unit_convert",
        source_span="3 gb", params={"from_unit": "gb", "to_unit": "mb"},
    )
    # Binary-vs-decimal is ambiguous; the pair is deliberately not in the
    # table and must be rejected, not guessed.
    assert verify_receipt(r, task_text=task) is False


def test_transform_vocabulary_is_versioned() -> None:
    assert DERIVATION_TRANSFORMS_VERSION == "v1"


# ── values_grounded integration: receipts ground, never un-ground ───────────

def _empty_state() -> StateIndex:
    return StateIndex(frozenset(), ())


def test_derived_date_grounds_with_valid_receipt() -> None:
    verdict = values_grounded(
        {"date": "2024-04-03"},
        task_text=TASK,
        state=_empty_state(),
        domain="general",
        receipts=(_receipt(),),
    )
    assert verdict is True


def test_derived_date_stays_ungrounded_without_receipt() -> None:
    verdict = values_grounded(
        {"date": "2024-04-03"},
        task_text=TASK,
        state=_empty_state(),
        domain="general",
    )
    assert verdict is False


def test_invalid_receipt_does_not_ground() -> None:
    verdict = values_grounded(
        {"date": "2024-04-03"},
        task_text=TASK,
        state=_empty_state(),
        domain="general",
        receipts=(_receipt(transform="llm_reasoning"),),
    )
    assert verdict is False


def test_episode_threading_parses_valid_and_drops_malformed() -> None:
    from remora.toolcall.routing.episode import RoutingEpisode
    from remora.toolcall.routing.evaluate import _derivation_receipts

    episode = RoutingEpisode(
        id="e1", source_dataset="test", source_commit="", cluster_id="c1",
        user_task=TASK, available_tools=("book_room",),
        untrusted_context=None, proposed_tool_name="book_room",
        proposed_tool_args={"date": "2024-04-03"}, domain="general",
        proposed_derivations=(
            {"argument": "date", "value": "2024-04-03",
             "transform": "en_date_to_iso", "source_span": "April 3rd, 2024"},
            {"argument": "broken"},  # malformed: dropped, never raised
        ),
    )
    receipts = _derivation_receipts(episode)
    assert len(receipts) == 1
    assert receipts[0].argument == "date"


def test_receipt_for_other_argument_does_not_ground() -> None:
    verdict = values_grounded(
        {"date": "2024-04-03"},
        task_text=TASK,
        state=_empty_state(),
        domain="general",
        receipts=(_receipt(argument="deadline"),),
    )
    assert verdict is False
