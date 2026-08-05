# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Raise-only metadata on the advisory path (NEGATIVE_RESULTS theme 8, §14/M4).

The enforcement path takes risk/effect from a server-side registry; the
library path (``assess_tool_call``) judges what the caller hands it. A
caller must be able to RAISE risk and never lower it: a declared
``risk_tier`` weaker than the deterministic name-heuristic floor is
clamped up to the floor, and a declared read on a write-verb tool is
floored to the inferred write family. The clamp is recorded — silent
correction is how the ``assign``/``close``/``approve`` bug hid.

The floor CLAMPS declarations; it never fills unset fields — with
``infer=False`` an unset risk_tier stays unset and the engine fail-closes
as before.
"""
from __future__ import annotations

from remora.assess import assess_tool_call, infer_risk_and_type


def test_declared_low_on_destructive_tool_is_floored_to_critical() -> None:
    a = assess_tool_call(
        "delete_production_database", {"db": "main"},
        risk_tier="low", action_type="destructive_write",
    )
    assert a.envelope.request.risk_tier == "critical"
    assert a.floored.get("risk_tier") == "critical"


def test_declared_critical_on_read_tool_is_kept() -> None:
    a = assess_tool_call(
        "read_telemetry", {"asset": "P-1"},
        risk_tier="critical", action_type="read",
    )
    assert a.envelope.request.risk_tier == "critical"
    assert "risk_tier" not in a.floored


def test_declared_low_on_read_tool_is_kept() -> None:
    a = assess_tool_call(
        "read_telemetry", {"asset": "P-1"},
        risk_tier="low", action_type="read",
    )
    assert a.envelope.request.risk_tier == "low"
    assert a.floored == {}


def test_m4_bug_verbs_floor_declared_read() -> None:
    # The assign/close/approve write bug: verb heuristics must be the
    # fallback authority a caller cannot talk their way under.
    a = assess_tool_call(
        "approve_invoice", {"invoice": "INV-1"},
        risk_tier="low", action_type="read",
    )
    assert a.envelope.request.risk_tier == "medium"
    assert a.envelope.request.action_type == "write"
    assert a.floored.get("risk_tier") == "medium"
    assert a.floored.get("action_type") == "write"


def test_floor_never_fills_unset_fields() -> None:
    a = assess_tool_call("delete_everything", {}, infer=False)
    # Unset stays unset (engine fail-closes on it); the floor only clamps
    # explicit declarations.
    assert a.envelope.request.risk_tier in ("", None, "unspecified")
    assert a.floored == {}


def test_inference_table_covers_the_m4_verbs() -> None:
    for verb in ("assign_ticket", "close_case", "approve_request"):
        action_type, risk = infer_risk_and_type(verb)
        assert action_type == "write", verb
        assert risk == "medium", verb
