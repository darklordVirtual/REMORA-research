# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's tool declaration is valid, shipped, and says what the tools do."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.toolcall.deployment_registry import load_deployment_tool_metadata

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
METADATA = PILOT / "tool_metadata.json"


def test_the_declaration_validates_against_the_engine_vocabulary(monkeypatch):
    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://unused")  # the loader checks the profile first
    resolved = load_deployment_tool_metadata(METADATA)
    assert set(resolved) == {"read_sensor", "adjust_setpoint", "set_valve_position",
                             "acknowledge_alarm", "create_work_order", "close_work_order"}
    assert all(entry["domain"] == "ot_plant" for entry in resolved.values())


def test_only_the_read_is_low_and_every_write_is_critical(monkeypatch):
    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://unused")
    resolved = load_deployment_tool_metadata(METADATA)
    assert resolved["read_sensor"]["risk_tier"] == "low"
    assert resolved["read_sensor"]["action_type"] == "read"
    for name, entry in resolved.items():
        if name != "read_sensor":
            assert entry["risk_tier"] == "critical", name
            assert entry["action_type"] == "write", name


def test_every_declared_tool_has_a_stated_reason():
    raw = json.loads(METADATA.read_text(encoding="utf-8"))
    for name in raw["tools"]:
        assert name in raw["_why"], f"{name} is declared without saying why"


def test_the_image_and_the_compose_file_ship_the_declaration():
    dockerfile = (PILOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PILOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "COPY deploy/ot-pilot/tool_metadata.json /app/tool_metadata.json" in dockerfile
    assert "REMORA_TOOL_METADATA_FILE: /app/tool_metadata.json" in compose
    assert 'REMORA_GROUNDED_READ_ACCEPT: "1"' in compose
    assert 'REMORA_GROUNDED_READ_IN_PRODUCTION: "1"' in compose


@pytest.mark.parametrize("name", ["adjust_setpoint", "set_valve_position", "acknowledge_alarm",
                                  "create_work_order", "close_work_order"])
def test_the_state_index_covers_the_declared_domain(name):
    """The declaration's domain must be the one the semantic bundle's state index scopes."""
    import sys

    sys.path.insert(0, str(PILOT))
    import ot_bundle  # noqa: E402

    bundle = ot_bundle.build_semantic_bundle()
    scopes = {scope.domain for scope in bundle.state.scopes}
    assert "ot_plant" in scopes
