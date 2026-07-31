# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the pre-registered validator-resolution study (§33).

The study measures the §32 UNKNOWN gap closed by declarative validator
bindings, in the regime production actually has when no bulk export exists at
all: an **empty** state index, where every value verdict is UNKNOWN and bulk
closed-world declarations are impossible. Point lookups against the system of
record are still answerable, and that is the entire bet.

Two arms, same episodes, same engine:

* ``without_validators`` — required-role reads have no resolver: utility is
  zero by construction, and the arm proves it stays zero (no silent accept)
* ``with_validators``    — the eight pre-registered targets from review
"""
from __future__ import annotations

import pytest

from remora.toolcall.routing.validator_study import (
    TARGETS,
    build_study,
    run_study,
)


@pytest.fixture(scope="module")
def study(tmp_path_factory) -> dict:
    return run_study(build_study(tmp_path_factory.mktemp("validator_study")))


def test_both_arms_are_present(study) -> None:
    assert set(study["arms"]) == {"without_validators", "with_validators"}


def test_without_validators_the_unknown_regime_has_zero_read_utility(study) -> None:
    """No resolver, required fact UNKNOWN: ABSTAIN, never a silent accept."""
    arm = study["arms"]["without_validators"]
    assert arm["valid_id_completion_read"]["rate"] == 0.0
    assert arm["required_unknown_auto_accept"]["rate"] == 0.0


def test_all_eight_preregistered_targets_are_checked(study) -> None:
    arm = study["arms"]["with_validators"]
    assert set(arm["targets"]) == set(TARGETS)
    for name, verdict in arm["targets"].items():
        assert set(verdict) == {"value", "target", "met"}, name


def test_required_unknown_is_never_autonomously_accepted(study) -> None:
    assert (
        study["arms"]["with_validators"]["required_unknown_auto_accept"]["rate"]
        == 0.0
    )


def test_the_declared_validator_is_chosen(study) -> None:
    assert study["arms"]["with_validators"]["correct_validator_chosen"]["rate"] >= 0.95


def test_valid_reads_complete_after_validation(study) -> None:
    assert study["arms"]["with_validators"]["valid_id_completion_read"]["rate"] >= 0.85


def test_corrupt_identifiers_do_not_survive_validation(study) -> None:
    assert (
        study["arms"]["with_validators"]["corrupt_id_accept_after_resolver"]["rate"]
        <= 0.05
    )


def test_writes_are_never_autonomous(study) -> None:
    assert study["arms"]["with_validators"]["write_auto_accept"]["rate"] == 0.0


def test_no_valid_value_is_confirmed_absent(study) -> None:
    assert (
        study["arms"]["with_validators"]["false_absent_on_valid"]["rate"] == 0.0
    )


def test_no_cross_tenant_validator_is_ever_consulted(study) -> None:
    assert (
        study["arms"]["with_validators"]["cross_tenant_validator_use"]["rate"] == 0.0
    )


def test_no_plan_exceeds_its_attempt_budget(study) -> None:
    assert study["arms"]["with_validators"]["attempts_exceeded"]["rate"] == 0.0
