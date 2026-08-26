# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The pilot pack (issue #90) stays internally consistent.

The pack is partner-facing: a schema that stops validating, an example
that stops conforming to its own schema, or an export script that stops
parsing would ship a broken onboarding experience while every other gate
stayed green. These tests bind the pack's pieces to each other and to the
contracts they claim alignment with.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[1] / "artifacts" / "pilot-pack"

EXAMPLE_EVENT = {
    "event_id": "evt-0001",
    "occurred_at": "2026-08-26T09:00:00+00:00",
    "tool_call": {
        "name": "lookup_work_order",
        "arguments": {"id": "WO-17"},
        "target_environment": "staging",
    },
    "registry_metadata": {
        "domain": "maintenance", "action_type": "read", "risk_tier": "low",
    },
    "ground_truth": {"label": "allow", "labeled_by": "reviewer-a"},
}


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads((PACK / "event_schema.json").read_text(encoding="utf-8"))


def test_the_event_schema_is_valid_and_accepts_the_worked_example(schema) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(EXAMPLE_EVENT, schema)


def test_an_inferred_only_event_is_rejected(schema) -> None:
    """Protocol precondition 4: registry metadata is REQUIRED — an event
    with only a tool name must not validate as scoreable input."""
    jsonschema = pytest.importorskip("jsonschema")
    bare = {k: v for k, v in EXAMPLE_EVENT.items() if k != "registry_metadata"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bare, schema)


def test_ground_truth_labels_are_the_decision_vocabulary(schema) -> None:
    labels = schema["properties"]["ground_truth"]["properties"]["label"]["enum"]
    assert labels == ["allow", "block", "review"]


def test_the_export_recipe_computes_metrics_from_a_stream(tmp_path, capsys) -> None:
    spec = importlib.util.spec_from_file_location(
        "export_envelopes", PACK / "export_envelopes.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    stream = tmp_path / "envelopes.jsonl"
    rows = [
        {"decision": {"action": "ALLOW", "latency_ms": 12}, "signature": "s"},
        {"decision": {"action": "BLOCK", "latency_ms": 40}, "signature": "s"},
        {"decision": {"action": "REVIEW"}, "signature": None},
    ]
    stream.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    import sys
    argv = sys.argv
    sys.argv = ["export_envelopes.py", str(stream)]
    try:
        assert mod.main() == 0
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "missing audit data:      0" in out
    assert "allow" in out and "block" in out and "review" in out
    assert "unsigned envelopes:      1" in out


def test_the_example_registry_module_honours_the_contract() -> None:
    """register_tools uses the REAL contract — register(name, fn), no extra
    kwargs (the dispatcher accepts callables only) — and every registered
    tool carries explicit metadata in TOOL_METADATA."""
    spec = importlib.util.spec_from_file_location(
        "partner_tool_registry",
        PACK / "example-config" / "partner_tool_registry.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    seen: dict[str, object] = {}

    def register(name, fn):  # the dispatcher's actual signature
        seen[name] = fn

    mod.register_tools(register)
    assert set(seen) == {"lookup_work_order", "stage_report"}
    assert set(mod.TOOL_METADATA) == set(seen)
    for name, meta in mod.TOOL_METADATA.items():
        for key in ("domain", "action_type", "risk_tier"):
            assert meta.get(key), f"{name} missing explicit {key}"
