# SPDX-License-Identifier: BUSL-1.1
"""Gate 1 authority-surface tests for ToolContract and ToolContractRegistry.

These are acceptance criteria for Gate 1 ('authority ready'): the contract
layer must reject every poisoning pattern before any experimental scenario is
opened against it.  A linter that silently accepts mutation:true→false or a
duplicate declaration cannot be called an authority.
"""
from __future__ import annotations

import json

import pytest

from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(tool: str = "get_booking", **overrides) -> ToolContract:
    defaults = dict(
        tool=tool, capability="booking_management", effect="read",
        resource_type="booking", mutation=False,
        argument_roles={"booking_id": "target_resource"},
    )
    defaults.update(overrides)
    return ToolContract(**defaults)


def _write(tool: str = "cancel_booking", **overrides) -> ToolContract:
    defaults = dict(
        tool=tool, capability="booking_management", effect="cancel",
        resource_type="booking", mutation=True,
        argument_roles={"booking_id": "target_resource"},
        state_delta={"booking.status": "cancelled"},
    )
    defaults.update(overrides)
    return ToolContract(**defaults)


# ---------------------------------------------------------------------------
# Unconditional hard rejects: construction-time poisoning
# ---------------------------------------------------------------------------

def test_mutation_false_with_nonread_effect_is_rejected() -> None:
    """mutation:True→False while keeping a write effect must fail at construction."""
    with pytest.raises(ValueError, match="mutation must be True"):
        ToolContract(
            tool="cancel_booking", capability="c", effect="cancel",
            resource_type="booking", mutation=False,
        )


def test_read_effect_with_state_delta_is_rejected() -> None:
    """A read contract claiming a post-state change is self-contradictory."""
    with pytest.raises(ValueError, match="read cannot leave a changed state"):
        ToolContract(
            tool="get_booking", capability="c", effect="read",
            resource_type="booking", mutation=False,
            state_delta={"booking.status": "read"},
        )


def test_empty_canonicalisation_description_is_rejected() -> None:
    """An empty string is indistinguishable from an absent entry — refuse it."""
    with pytest.raises(ValueError, match="non-empty descriptions"):
        ToolContract(
            tool="get_sensor", capability="sensors", effect="read",
            resource_type="sensor", mutation=False,
            canonicalisations={"pressure": ""},
        )


# ---------------------------------------------------------------------------
# Duplicate declaration: registry must reject, not silently overwrite
# ---------------------------------------------------------------------------

def test_duplicate_tool_name_in_registry_is_rejected() -> None:
    """The second declaration of the same tool name must raise, not silently win."""
    with pytest.raises(ValueError, match="duplicate tool declaration"):
        ToolContractRegistry([_read("get_booking"), _read("get_booking")])


def test_registry_from_mapping_keeps_last_silently_for_compatibility() -> None:
    """Mapping path keeps last (dict semantics); only the iterable path checks."""
    registry = ToolContractRegistry(
        {"get_booking": _read("get_booking"), "cancel_booking": _write()}
    )
    assert registry.get("get_booking") is not None


def test_registry_with_unique_tools_is_accepted() -> None:
    registry = ToolContractRegistry([_read("get_booking"), _write("cancel_booking")])
    assert registry.get("get_booking").effect == "read"
    assert registry.get("cancel_booking").effect == "cancel"


# ---------------------------------------------------------------------------
# Canonicalisations: schema presence, serialisation, hash sensitivity
# ---------------------------------------------------------------------------

def test_canonicalisations_round_trip_through_json() -> None:
    contract = _read(
        canonicalisations={"pressure": "bar\u2194kPa", "timestamp": "ISO-8601"},
    )
    registry = ToolContractRegistry([contract])
    restored = ToolContractRegistry.from_json_dict(registry.to_json_dict())
    assert restored.get("get_booking").canonicalisations == {
        "pressure": "bar\u2194kPa",
        "timestamp": "ISO-8601",
    }


def test_adding_canonicalisations_changes_json_dict() -> None:
    """A contract with and without canonicalisations must produce different dicts
    so that any hash over the bundle detects the change."""
    without = _read()
    with_ = _read(canonicalisations={"pressure": "bar\u2194kPa"})
    assert without.to_json_dict() != with_.to_json_dict()


def test_empty_canonicalisations_serialise_as_empty_dict() -> None:
    d = _read().to_json_dict()
    assert d["canonicalisations"] == {}


def test_canonicalisations_from_json_rejects_non_map() -> None:
    raw = _read().to_json_dict()
    raw["canonicalisations"] = ["not", "a", "map"]
    with pytest.raises(ValueError, match="must be a map"):
        ToolContractRegistry.from_json_dict({"get_booking": raw})


# ---------------------------------------------------------------------------
# State-delta resource consistency (documented gap, not yet enforced)
# ---------------------------------------------------------------------------

def test_state_delta_on_wrong_resource_type_is_constructible_but_documented() -> None:
    """A contract that declares state_delta on a different resource than
    resource_type is currently accepted at construction — it is caught only
    by effect_consistent() at decision time.  This test pins the current
    behaviour and documents the gap so a future linter can close it."""
    contract = _write(
        resource_type="booking",
        state_delta={"invoice.status": "void"},  # different resource
    )
    # Currently succeeds — effect_consistent() catches this at decision time
    assert contract.resource_type == "booking"
    assert "invoice.status" in contract.state_delta
