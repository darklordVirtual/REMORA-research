# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the tool registry and argument-satisfiability check.

A deployment knows which tools exist and what each one requires and produces —
that is a tool registry, ordinary integration infrastructure. This module turns
that knowledge into one observable signal: can the proposed call's required
parameters be sourced at all?

Motivation, measured on the routing benchmark: enabling the low-consequence
ACCEPT path took ABSTAIN recall from 62.5% to 0%. Every lost case was a call
whose required arguments were unobtainable — search_lat_lon with no latitude
available, unit_conversion with no amount to convert. Those are unsatisfiable
calls, not high-blast-radius ones.

The check uses only observable inputs: the proposed tool name, the available
tool list, the task text, and the registry. It never reads a label.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.toolcall.routing.tool_registry import (
    ToolRegistry,
    ToolSignature,
    extract_from_python,
)

REAL_TOOLS = Path(__file__).parent.parent / ".cache" / "routing_bench" / "toolsandbox" / "tools"


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry(
        {
            "search_lat_lon": ToolSignature(
                "search_lat_lon", ("latitude", "longitude"), ()
            ),
            "get_current_location": ToolSignature(
                "get_current_location", (), ("latitude", "longitude")
            ),
            "unit_conversion": ToolSignature(
                "unit_conversion", ("amount", "from_unit", "to_unit"), ()
            ),
            "search_holiday": ToolSignature(
                "search_holiday", ("holiday_name", "year"), ()
            ),
            "get_current_timestamp": ToolSignature(
                "get_current_timestamp", (), ("timestamp",)
            ),
            "timestamp_diff": ToolSignature(
                "timestamp_diff", ("timestamp_0", "timestamp_1"), ()
            ),
        }
    )


# ---------------------------------------------------------------------------
# Satisfiability
# ---------------------------------------------------------------------------

def test_unsatisfiable_when_no_available_tool_produces_a_required_param(registry) -> None:
    """search_lat_lon needs coordinates and nothing available yields them."""
    assert registry.arguments_satisfiable(
        proposed="search_lat_lon",
        available=("search_lat_lon",),
        task_text="What city am I in?",
    ) is False


def test_satisfiable_when_an_available_tool_produces_the_param(registry) -> None:
    """The same call becomes satisfiable once the producer is available."""
    assert registry.arguments_satisfiable(
        proposed="search_lat_lon",
        available=("search_lat_lon", "get_current_location"),
        task_text="What city am I in?",
    ) is True


def test_numeric_suffixes_are_normalised(registry) -> None:
    """timestamp_0 and timestamp_1 are both satisfied by a 'timestamp' producer."""
    assert registry.arguments_satisfiable(
        proposed="timestamp_diff",
        available=("timestamp_diff", "get_current_timestamp"),
        task_text="How many days till Christmas?",
    ) is True
    assert registry.arguments_satisfiable(
        proposed="timestamp_diff",
        available=("timestamp_diff", "search_holiday"),
        task_text="How many days till Christmas?",
    ) is False


def test_param_named_in_the_task_text_counts_as_satisfiable(registry) -> None:
    """A task that names the parameter supplies it."""
    assert registry.arguments_satisfiable(
        proposed="search_holiday",
        available=("search_holiday",),
        task_text="Look up the holiday_name Christmas for year 2026",
    ) is True


def test_unknown_tool_is_none_not_false(registry) -> None:
    """A tool outside the registry is unknown, never confirmed-unsatisfiable.

    This is what keeps the signal from disqualifying every source whose schemas
    have not been extracted; unknown must not behave like a negative.
    """
    assert registry.arguments_satisfiable(
        proposed="some_unregistered_tool",
        available=("some_unregistered_tool",),
        task_text="anything",
    ) is None


def test_tool_with_no_required_params_is_satisfiable(registry) -> None:
    assert registry.arguments_satisfiable(
        proposed="get_current_timestamp",
        available=("get_current_timestamp",),
        task_text="what time is it",
    ) is True


def test_no_proposed_call_is_none(registry) -> None:
    assert registry.arguments_satisfiable(
        proposed=None, available=(), task_text="x"
    ) is None


# ---------------------------------------------------------------------------
# Extraction from Python sources
# ---------------------------------------------------------------------------

def test_extraction_reads_required_params_and_literal_outputs(tmp_path) -> None:
    """Required params exclude defaulted ones; outputs come from Literal keys."""
    module = tmp_path / "tools.py"
    module.write_text(
        "from typing import Dict, Literal, Optional\n"
        "def get_current_location() -> Dict[Literal['latitude', 'longitude'], float]:\n"
        "    ...\n"
        "def search_lat_lon(latitude: float, longitude: float) -> Optional[str]:\n"
        "    ...\n"
        "def with_default(a: int, b: int = 3) -> float:\n"
        "    ...\n",
        encoding="utf-8",
    )
    sigs = extract_from_python([module])
    assert sigs["search_lat_lon"].required_params == ("latitude", "longitude")
    assert set(sigs["get_current_location"].produced_names) >= {"latitude", "longitude"}
    assert sigs["with_default"].required_params == ("a",)


def test_producer_name_is_derived_from_the_function_name(tmp_path) -> None:
    """get_current_timestamp produces 'timestamp' even without a Literal return."""
    module = tmp_path / "tools.py"
    module.write_text(
        "def get_current_timestamp() -> float:\n    ...\n", encoding="utf-8"
    )
    sigs = extract_from_python([module])
    assert "timestamp" in sigs["get_current_timestamp"].produced_names


@pytest.mark.skipif(
    not REAL_TOOLS.exists(),
    reason="ToolSandbox tool cache absent; run scripts/build_routing_bench.py --fetch",
)
def test_real_toolsandbox_signatures_extract() -> None:
    sigs = extract_from_python(sorted(REAL_TOOLS.glob("*.py")))
    assert sigs["search_lat_lon"].required_params == ("latitude", "longitude")
    assert set(sigs["get_current_location"].produced_names) >= {"latitude", "longitude"}
    assert sigs["unit_conversion"].required_params == ("amount", "from_unit", "to_unit")


def test_none_default_counts_as_required(tmp_path) -> None:
    """``latitude: float | None = None`` is a sentinel, not an optional parameter.

    Defaulting to None is the standard Python way of saying "not supplied"; the
    call still cannot do its job without a value. A real default such as
    ``days=0`` does make a parameter optional. ToolSandbox's
    search_weather_around_lat_lon(days=0, latitude=None, longitude=None) is the
    case that exposed this: treating all three as optional made an
    unsatisfiable call look satisfiable.
    """
    module = tmp_path / "tools.py"
    module.write_text(
        "from typing import Optional\n"
        "def search_weather(days: int = 0, latitude: Optional[float] = None,\n"
        "                   longitude: Optional[float] = None) -> Optional[dict]:\n"
        "    ...\n",
        encoding="utf-8",
    )
    sigs = extract_from_python([module])
    assert sigs["search_weather"].required_params == ("latitude", "longitude")


@pytest.mark.skipif(
    not REAL_TOOLS.exists(),
    reason="ToolSandbox tool cache absent; run scripts/build_routing_bench.py --fetch",
)
def test_real_weather_tool_requires_coordinates() -> None:
    sigs = extract_from_python(sorted(REAL_TOOLS.glob("*.py")))
    required = sigs["search_weather_around_lat_lon"].required_params
    assert "latitude" in required and "longitude" in required
    assert "days" not in required


# ---------------------------------------------------------------------------
# Class-method tools (tau2 exposes its tools as methods, not functions)
# ---------------------------------------------------------------------------

def test_public_class_methods_are_extracted(tmp_path) -> None:
    """tau2 defines tools as methods on a domain class, not module functions."""
    module = tmp_path / "tools.py"
    module.write_text(
        "class AirlineTools:\n"
        "    def __init__(self, db):\n        ...\n"
        "    def _get_user(self, user_id: str):\n        ...\n"
        "    def get_reservation_details(self, reservation_id: str):\n        ...\n"
        "    def search_direct_flight(self, origin: str, destination: str,\n"
        "                             date: str):\n        ...\n",
        encoding="utf-8",
    )
    sigs = extract_from_python([module])
    assert "get_reservation_details" in sigs
    assert sigs["get_reservation_details"].required_params == ("reservation_id",)
    assert sigs["search_direct_flight"].required_params == (
        "origin", "destination", "date",
    )


def test_self_and_private_methods_are_excluded(tmp_path) -> None:
    """`self` is never a parameter, and a leading underscore means internal."""
    module = tmp_path / "tools.py"
    module.write_text(
        "class T:\n"
        "    def __init__(self, db):\n        ...\n"
        "    def _helper(self, x: int):\n        ...\n"
        "    def public(self, x: int):\n        ...\n",
        encoding="utf-8",
    )
    sigs = extract_from_python([module])
    assert set(sigs) == {"public"}
    assert sigs["public"].required_params == ("x",)


TAU2_TOOLS = Path(__file__).parent.parent / ".cache" / "routing_bench" / "tau2_tools"
SIGNATURE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "routing_bench" / "tau2_tool_signatures.json"
)


def test_registry_round_trips_through_json(registry) -> None:
    """Serialization exists so a registry can be committed as a fixture and CI
    can enforce invariants without the gitignored extraction cache."""
    assert ToolRegistry.from_json_dict(registry.to_json_dict()).signatures == (
        registry.signatures
    )


def test_committed_tau2_signature_fixture_loads() -> None:
    """The metamorphic invariants must run in CI, where .cache does not exist.

    An empty registry silently made every obtainable/unobtainable pair
    observationally identical in CI while the invariant passed locally — the
    exact Windows-local-vs-CI gap this fixture closes.
    """
    import json

    loaded = ToolRegistry.from_json_dict(
        json.loads(SIGNATURE_FIXTURE.read_text(encoding="utf-8"))
    )
    assert "get_reservation_details" in loaded.signatures
    assert loaded.signatures["get_reservation_details"].required_params == (
        "reservation_id",
    )


@pytest.mark.skipif(
    not TAU2_TOOLS.exists(),
    reason="tau2 tool cache absent; run scripts/build_routing_bench.py --fetch",
)
def test_committed_fixture_matches_a_fresh_extraction() -> None:
    """The committed fixture must never drift from what extraction produces."""
    import json

    fresh = ToolRegistry(extract_from_python(sorted(TAU2_TOOLS.glob("*.py"))))
    committed = json.loads(SIGNATURE_FIXTURE.read_text(encoding="utf-8"))
    assert fresh.to_json_dict() == committed


@pytest.mark.skipif(
    not TAU2_TOOLS.exists(),
    reason="tau2 tool cache absent; run scripts/build_routing_bench.py --fetch",
)
def test_real_tau2_signatures_extract() -> None:
    sigs = extract_from_python(sorted(TAU2_TOOLS.glob("*.py")))
    assert "get_reservation_details" in sigs
    assert sigs["get_reservation_details"].required_params == ("reservation_id",)
    assert not any(name.startswith("_") for name in sigs)


# ---------------------------------------------------------------------------
# Arguments already present in the proposed call
# ---------------------------------------------------------------------------

def test_supplied_argument_satisfies_its_parameter(registry) -> None:
    """A parameter present in the proposed call has been sourced by definition.

    The check gates a *proposed call*; if the value is already in it, the agent
    obtained it somewhere. Whether that somewhere was legitimate is a different
    question, answered by argument_tainted, not by this signal.

    Without this, tau2's multi-turn tasks look unsatisfiable: the value came
    from an earlier conversation turn the benchmark's single-call view does not
    contain, so neither the task text nor another tool appears to supply it.
    """
    assert registry.arguments_satisfiable(
        proposed="search_lat_lon",
        available=("search_lat_lon",),
        task_text="What city am I in?",
        proposed_args={"latitude": 37.3, "longitude": -122.0},
    ) is True


def test_partially_supplied_arguments_are_still_unsatisfiable(registry) -> None:
    """One supplied parameter does not excuse a missing one."""
    assert registry.arguments_satisfiable(
        proposed="search_lat_lon",
        available=("search_lat_lon",),
        task_text="What city am I in?",
        proposed_args={"latitude": 37.3},
    ) is False


def test_empty_proposed_args_change_nothing(registry) -> None:
    """The default stays the pre-existing behaviour."""
    assert registry.arguments_satisfiable(
        proposed="search_lat_lon",
        available=("search_lat_lon",),
        task_text="What city am I in?",
        proposed_args={},
    ) is False
