# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Policy identity distinguishes deployments that decide differently.

The identity hash exists so a lease issued under one configuration stops
verifying under another. Two gaps defeated that: ``execution_profile`` — the
flag that makes a probabilistic ACCEPT structurally impossible — was left out
of the hash, and the flags were read with ``getattr(..., False)``, so a
renamed attribute reported "off" and froze a stable, wrong hash.
"""
from __future__ import annotations

import inspect

import pytest

import servers.api as api
from remora.policy.decision_engine import RemoraDecisionEngine


def test_every_engine_accept_flag_is_part_of_the_identity() -> None:
    """A new ACCEPT flag must be added to ENGINE_IDENTITY_FLAGS deliberately.

    Without this, adding a flag to the engine silently reopens the gap: same
    files, different decisions, identical hash.
    """
    params = inspect.signature(RemoraDecisionEngine.__init__).parameters
    boolean_flags = {
        name for name, p in params.items()
        if name != "self" and isinstance(p.default, bool)
    }
    # verify_invariants can only make a decision stricter and never unlocks an
    # ACCEPT path, so it is intentionally outside the ACCEPT-path identity.
    boolean_flags.discard("verify_invariants")
    assert boolean_flags == set(api.ENGINE_IDENTITY_FLAGS), (
        "RemoraDecisionEngine ACCEPT flags and ENGINE_IDENTITY_FLAGS have "
        "drifted apart"
    )


def test_identity_reads_state_strictly_not_via_getattr_default() -> None:
    """A removed flag must raise, not silently report False."""

    class _Renamed:
        def __init__(self) -> None:
            self.low_consequence_accept = True
            self.grounded_read_accept = False
            self.semantic_authority_floor = False
            # execution_profile deliberately absent

    with pytest.raises(KeyError):
        api.engine_mode_identity(_Renamed())


def test_execution_profile_changes_the_identity() -> None:
    off = RemoraDecisionEngine()
    on = RemoraDecisionEngine(execution_profile=True)
    assert api.engine_mode_identity(off) != api.engine_mode_identity(on)
    assert (
        api._engine_mode_component_hash(off)
        != api._engine_mode_component_hash(on)
    )


def test_each_accept_flag_moves_the_hash() -> None:
    base = api._engine_mode_component_hash(RemoraDecisionEngine())
    for flag in api.ENGINE_IDENTITY_FLAGS:
        flipped = RemoraDecisionEngine(**{flag: True})
        assert api._engine_mode_component_hash(flipped) != base, flag


def test_the_two_surfaces_have_distinct_policy_identities() -> None:
    """/v1/assess runs the consensus pipeline; /v1/execution runs the engine.

    Reporting one surface's configuration for the other's decision claimed a
    configuration that decision never ran under.
    """
    assess = api._engine_mode_component_hash(surface=api.SURFACE_ASSESS)
    execution = api._engine_mode_component_hash(surface=api.SURFACE_EXECUTION)
    assert assess != execution


def test_assess_identity_does_not_depend_on_the_execution_engine() -> None:
    """The assess hash must be stable when execution flags change."""
    before = api._engine_mode_component_hash(surface=api.SURFACE_ASSESS)
    after = api._engine_mode_component_hash(
        RemoraDecisionEngine(low_consequence_accept=True),
        surface=api.SURFACE_ASSESS,
    )
    assert before == after
