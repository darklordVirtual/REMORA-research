# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reversibility classification must be total and fail closed.

``remora.credal`` weighs worst-case loss by whether an action is reversible,
and that weight reaches a decision: ``worst_case_loss`` drives the
``minimax_gate`` in ``remora/policy/decision_engine.py``, which escalates at
0.8. Until this module existed the weight was chosen by membership in a
frozen set of eleven strings, and *everything else* -- including every string
nobody had thought of -- took the reversible weight of 0.30.

That is fail-open on the most safety-relevant classification in the risk
model, and the corpora in this repository show it is not theoretical. Of the
20 distinct ``action_type`` values appearing in committed corpora, 18 fell
outside the irreversible set, among them ``financial_transaction``,
``approve_payment``, ``db_migration``, ``schema_change``, ``security_change``
and ``configuration_change`` -- each a near-synonym of a string that IS in the
set (``financial_write``, ``execute_transfer``, ``config_overwrite``,
``disable_security``).

Measured blast radius, over a uniform grid of (p_harm_upper, severity): 40 of
231 grid points change the minimax gate's verdict purely on which spelling was
used, concentrated in the high-severity corner where escalation matters most.
Worked example at p_harm_upper 0.35, severity 0.9: ``config_overwrite``
yields 0.98 and escalates, ``configuration_change`` yields 0.54 and does not.

The fix is not a longer list. A longer list has the same shape and fails on
the next unanticipated string. Classification becomes three-valued --
irreversible, declared reversible, unknown -- and **unknown carries the
irreversible weight**. Only explicitly declared non-mutating actions get the
discount.

Scope (declared, not exhaustive): this governs the credal worst-case-loss
weight. It does not change the hard-guard floor, the decision thresholds, or
any other gate.
"""

from __future__ import annotations

import pytest

from remora.action_semantics import (
    IRREVERSIBLE_ACTION_TYPES,
    REVERSIBLE_ACTION_TYPES,
    Reversibility,
    classify_reversibility,
    irreversibility_weight,
)

# Real values from the committed corpora that sat outside the irreversible set.
UNANTICIPATED_FROM_CORPORA = (
    "financial_transaction",
    "approve_payment",
    "db_migration",
    "schema_change",
    "security_change",
    "configuration_change",
    "infrastructure_write",
    "medical_write",
    "legal_write",
    "deploy",
    "write",
    "execute",
)

# Each pair means the same thing operationally. The left one was in the set,
# the right one was not, and they received opposite weights.
SYNONYM_PAIRS = (
    ("config_overwrite", "configuration_change"),
    ("disable_security", "security_change"),
    ("financial_write", "financial_transaction"),
    ("execute_transfer", "approve_payment"),
    ("destructive_write", "db_migration"),
)


def test_the_classification_is_total() -> None:
    """Every input reaches a verdict; nothing falls through untyped."""
    for value in ("delete", "read", "a string nobody declared", "", None, "  DELETE  "):
        assert isinstance(classify_reversibility(value), Reversibility)


def test_an_unknown_action_carries_the_irreversible_weight() -> None:
    """The fail-closed rule itself."""
    assert classify_reversibility("wire_funds_offshore") is Reversibility.UNKNOWN
    assert irreversibility_weight("wire_funds_offshore") == irreversibility_weight("delete")


@pytest.mark.parametrize("action_type", UNANTICIPATED_FROM_CORPORA)
def test_corpus_values_outside_the_set_no_longer_take_the_discount(action_type: str) -> None:
    """These are real values from committed corpora, not invented ones."""
    if action_type in REVERSIBLE_ACTION_TYPES:
        pytest.skip(f"{action_type} is explicitly declared reversible")
    assert irreversibility_weight(action_type) == 1.0, (
        f"{action_type!r} takes the reversible weight, so an action the risk model has "
        "never seen is scored as recoverable"
    )


@pytest.mark.parametrize(("declared", "synonym"), SYNONYM_PAIRS)
def test_operational_synonyms_are_weighed_alike(declared: str, synonym: str) -> None:
    """Two spellings of one action must not produce two different decisions."""
    assert irreversibility_weight(declared) == irreversibility_weight(synonym), (
        f"{declared!r} and {synonym!r} are the same action to an operator and are "
        "weighed differently, so the escalation depends on the spelling"
    )


def test_declared_reversible_actions_keep_the_discount() -> None:
    """Fail-closed must not mean refusing everything: reads stay cheap."""
    for action_type in ("read", "query", "list", "search"):
        assert classify_reversibility(action_type) is Reversibility.REVERSIBLE
        assert irreversibility_weight(action_type) == 0.30


def test_the_two_declared_sets_are_disjoint() -> None:
    """An action in both sets has no defined weight."""
    overlap = IRREVERSIBLE_ACTION_TYPES & REVERSIBLE_ACTION_TYPES
    assert not overlap, f"declared both reversible and irreversible: {sorted(overlap)}"


def test_no_declared_reversible_action_mutates_state() -> None:
    """The discount is for actions that change nothing, and the names must show it.

    A guard against the obvious future mistake: widening the reversible set to
    recover utility, one plausible-looking write at a time.
    """
    mutating_markers = ("write", "delete", "update", "create", "execute", "deploy",
                        "transfer", "overwrite", "wipe", "change", "migrat", "approve")
    offenders = sorted(
        name
        for name in REVERSIBLE_ACTION_TYPES
        if any(marker in name for marker in mutating_markers)
    )
    assert not offenders, (
        f"these are declared reversible but their names describe a state change: {offenders}"
    )


def test_the_weight_reaches_the_credal_envelope() -> None:
    """The unit under test is only useful if credal actually consumes it."""
    from remora.credal import compute_from_obs

    import inspect

    source = inspect.getsource(compute_from_obs)
    assert "irreversibility_weight" in source, (
        "credal must obtain the weight from the classification, or this contract governs "
        "nothing that reaches a decision"
    )


def test_the_spelling_no_longer_decides_the_escalation() -> None:
    """End to end, at the risk tier where it matters most.

    Before the fail-closed change, at ``risk_tier="critical"`` and
    ``p_harm_upper=0.5``: ``config_overwrite`` produced worst_case_loss 1.0 and
    crossed the minimax gate, while ``configuration_change`` produced 0.71 and
    did not. Same action to an operator, opposite decision, because one
    spelling was in a list and the other was not.
    """
    from remora.credal import compute_from_obs
    from remora.policy.decision_engine import MINIMAX_ESCALATE_THRESHOLD
    from remora.policy.observation import PolicyObservation

    def envelope(action_type: str):
        return compute_from_obs(
            PolicyObservation(
                question="overwrite the production configuration",
                action_type=action_type,
                risk_tier="critical",
                phase="disordered",
            )
        )

    declared = envelope("config_overwrite")
    synonym = envelope("configuration_change")
    never_seen = envelope("wire_funds_offshore")

    assert declared.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD)
    assert synonym.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD), (
        "a synonym of a declared irreversible action must reach the same gate"
    )
    assert never_seen.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD), (
        "an action type the risk model has never seen must not be scored as recoverable"
    )
    assert declared.worst_case_loss == synonym.worst_case_loss == never_seen.worst_case_loss

    read_only = envelope("read")
    assert not read_only.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD), (
        "fail-closed must not escalate declared read-only work; that would be the "
        "utility collapse this design exists to avoid"
    )
