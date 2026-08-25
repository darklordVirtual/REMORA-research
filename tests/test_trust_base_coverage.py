# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A decision must be able to say WHICH part of the trust base it covers.

`policy_bundle_hash` is a composite over six components. It answers "did the
trust base differ" and can never answer "which part of it", so two
independently signed records carrying only the composite cannot be compared
component by component: a verifier learns the views diverged and nothing about
where.

That gap has two names. In cosai-oasis/ws4-secure-design-agentic-systems#149
it is view-consistency -- distinct from TOCTOU, because it can fail with no
change at all if the PDP evaluated a stale or divergent snapshot. In AIREP
(arXiv:2608.21363, SHELF-026) it is the requirement that a record declare both
what its evidence covers and what it does not.

These tests pin the declaration, and pin that the join it enables can FAIL.
A join that always succeeds is decoration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from servers import api as api_mod  # noqa: E402


def _coverage() -> dict:
    return api_mod.policy_coverage_block(surface=api_mod.SURFACE_EXECUTION)


# ── The declaration ────────────────────────────────────────────────────────


def test_the_block_declares_both_halves() -> None:
    block = _coverage()
    assert set(block) == {"covers", "not_covered"}


def test_every_composed_component_is_named_individually() -> None:
    """The components the composite is built from, each addressable.

    Pinned against the composite's own inputs rather than a hand-written list,
    so a component added to `_policy_component_hashes` and forgotten here is a
    failure rather than a silent hole in the declaration.
    """
    composed = {key for _name, key in api_mod._COVERAGE_COMPONENTS}
    hashes = api_mod._policy_component_hashes(surface=api_mod.SURFACE_EXECUTION)
    # The names in the block are the ones a verifier joins on.
    assert set(_coverage()["covers"]) == {n for n, _k in api_mod._COVERAGE_COMPONENTS}
    # Everything the coverage block maps must be a real component key.
    assert composed <= set(hashes)
    # And every component key except the composite itself must be declared.
    undeclared = set(hashes) - composed - {"policy_hash"}
    assert undeclared == set(), f"component(s) not declared in coverage: {undeclared}"


def test_not_covered_is_present_and_names_something() -> None:
    """Silence about the rest reads as complete coverage. It is not complete.

    The adapter and delegation state the enforcement path resolves at dispatch
    carry no digest. An empty list here would be a claim, not an omission, so
    if these ever gain digests the change has to be deliberate.
    """
    block = _coverage()
    assert isinstance(block["not_covered"], list)
    assert "adapter_state" in block["not_covered"]
    assert "delegation_state" in block["not_covered"]


def test_a_configured_but_absent_component_is_null_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Present-and-unset is not the same fact as not-a-component-here.

    OPA is optional. With no policy path configured the component must still
    appear, carrying None: dropping the key would let a verifier read "this
    deployment has no OPA layer" and "this deployment's OPA layer was not
    captured" as the same thing.
    """
    monkeypatch.delenv("REMORA_OPA_POLICY_PATH", raising=False)
    block = _coverage()
    assert "opa_policy" in block["covers"]
    assert block["covers"]["opa_policy"] is None


# ── The join ───────────────────────────────────────────────────────────────


def _join(admission: dict, closure: dict) -> dict[str, bool]:
    """Component-by-component agreement between two records.

    This is the whole point of the declaration: with only a composite the
    result would be a single bool.
    """
    names = set(admission["covers"]) | set(closure["covers"])
    return {
        n: admission["covers"].get(n) == closure["covers"].get(n)
        for n in sorted(names)
    }


def test_an_unchanged_trust_base_joins_on_every_component() -> None:
    assert all(_join(_coverage(), _coverage()).values())


def test_a_changed_component_is_identified_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The property that makes this evidence rather than decoration.

    One component changes between the two reads. The join must fail, and must
    fail *on that component* -- naming where the views diverged is the thing a
    composite cannot do.
    """
    monkeypatch.delenv("REMORA_OPA_POLICY_PATH", raising=False)
    admission = _coverage()

    policy = tmp_path / "policy.rego"
    policy.write_text("package remora.policy\n", encoding="utf-8")
    monkeypatch.setenv("REMORA_OPA_POLICY_PATH", str(policy))
    closure = _coverage()

    result = _join(admission, closure)
    assert result["opa_policy"] is False, "the changed component must not join"
    others = {n: ok for n, ok in result.items() if n != "opa_policy"}
    assert all(others.values()), f"unrelated components moved: {others}"


def test_the_composite_alone_cannot_say_which_component_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """States the gap this change closes, so a later reader sees the reason.

    Both reads produce a different composite. That is all the composite can
    ever say. The per-component join above says `opa_policy`.
    """
    monkeypatch.delenv("REMORA_OPA_POLICY_PATH", raising=False)
    before = api_mod._policy_component_hashes(surface=api_mod.SURFACE_EXECUTION)

    policy = tmp_path / "policy.rego"
    policy.write_text("package remora.policy\n", encoding="utf-8")
    monkeypatch.setenv("REMORA_OPA_POLICY_PATH", str(policy))
    after = api_mod._policy_component_hashes(surface=api_mod.SURFACE_EXECUTION)

    assert before["policy_hash"] != after["policy_hash"]
    # ...and that inequality carries no component name with it.


# ── Chain compatibility ────────────────────────────────────────────────────


def test_records_written_before_this_field_still_verify() -> None:
    """A chain recorded before policy_components existed must keep verifying.

    Unset means the producer had no component view to declare, which is not
    the same as declaring an empty one, so the key is dropped from the hash
    preimage rather than hashed as null.
    """
    from remora.governance.envelope import (POST_V2_AUDIT_KEYS,
                                            normalize_audit_for_hash)

    assert "policy_components" in POST_V2_AUDIT_KEYS

    without = {"audit": {"policy_version": "v5", "policy_components": None}}
    normalize_audit_for_hash(without)
    assert "policy_components" not in without["audit"]

    block = _coverage()
    with_view = {"audit": {"policy_version": "v5", "policy_components": block}}
    normalize_audit_for_hash(with_view)
    assert with_view["audit"]["policy_components"] == block
