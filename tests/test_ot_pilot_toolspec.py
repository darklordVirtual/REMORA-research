# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's ToolSpec bundle attests the callables the pilot registers, and its WS1 deployment resolves."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
SEED = "7a" * 32


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PILOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def signed(tmp_path_factory):
    pytest.importorskip("cryptography")
    from remora.toolcall.toolspec_sign import sign_with_seed

    builder = _load("build_toolspec")
    bundle, public, digest = sign_with_seed(builder.unsigned_bundle(), SEED, signed_at="2026-11-04T00:00:00+00:00")
    path = tmp_path_factory.mktemp("toolspec") / "toolspec-bundle.json"
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle, public, digest, path


def test_the_bundle_describes_exactly_the_six_pilot_tools(signed):
    bundle, *_ = signed
    assert bundle["schema_version"] == 4
    assert sorted(s["tool_id"] for s in bundle["tool_specs"]) == [
        "acknowledge_alarm", "adjust_setpoint", "close_work_order", "create_work_order",
        "read_sensor", "set_valve_position"]
    assert all(s["signing_identity"] == bundle["registry_signature"]["signing_identity"]
               for s in bundle["tool_specs"])


def test_risk_declaration_and_bundle_agree(signed):
    bundle, *_ = signed
    metadata = json.loads((PILOT / "tool_metadata.json").read_text(encoding="utf-8"))["tools"]
    for spec in bundle["tool_specs"]:
        meta = metadata[spec["tool_id"]]
        assert (spec["risk_tier"], spec["action_type"], spec["domain"]) == (
            meta["risk_tier"], meta["action_type"], meta["domain"]), spec["tool_id"]


def test_the_runtime_loads_the_bundle_and_every_callable_measures_as_attested(signed, monkeypatch):
    bundle, public, digest, path = signed
    from remora.execution.authorization import load_toolspec_bundle
    from remora.toolcall.callable_digest import callable_digest_for

    environ = {"REMORA_TOOLSPEC_BUNDLE": str(path), "REMORA_TOOLSPEC_VERIFY_KEYS": public,
               "REMORA_TOOLSPEC_PINNED_DIGEST": digest}
    loaded = load_toolspec_bundle(environ)
    assert loaded is not None and loaded.bundle_digest == digest
    sys.path.insert(0, str(PILOT))
    registry = _load("ot_registry")
    registered: dict[str, object] = {}
    registry.register_tools(lambda name, fn: registered.__setitem__(name, fn))
    assert set(registered) == {s["tool_id"] for s in bundle["tool_specs"]}
    for name, fn in registered.items():
        loaded.verify_callable(name, callable_digest_for(loaded.get(name), fn))
    loaded.verify_target("read_sensor", "prod")
    loaded.validate_arguments("read_sensor", {"sensor_id": "PT-101"})
    loaded.validate_arguments("adjust_setpoint", {"loop": "PIC-101", "value": 4.2})


def test_a_tampered_bundle_is_refused(signed):
    bundle, public, digest, path = signed
    from remora.execution.authorization import load_toolspec_bundle
    from remora.toolcall.toolspec import ToolSpecRefused

    tampered = json.loads(path.read_text())
    tampered["tool_specs"][0]["risk_tier"] = "low"
    bad = path.with_name("tampered.json"); bad.write_text(json.dumps(tampered))
    with pytest.raises(ToolSpecRefused):
        load_toolspec_bundle({"REMORA_TOOLSPEC_BUNDLE": str(bad), "REMORA_TOOLSPEC_VERIFY_KEYS": public,
                              "REMORA_TOOLSPEC_PINNED_DIGEST": digest})


def test_the_ws1_deployment_builds_and_resolves_the_round_and_the_work_orders():
    ws1 = _load("ot_ws1")
    deployment = ws1.build_ws1_deployment()
    assert set(deployment.registry.tools) == {"read_sensor", "adjust_setpoint", "set_valve_position",
                                              "acknowledge_alarm", "create_work_order", "close_work_order"}
    assert deployment.grounding == {"sensor_on_round": ("argument_values_supported", "argument_values_grounded")}
    round_source = deployment.resolvers["round"]
    assert "PT-101" in round_source.records["ot-pilot"] and "PT-999" not in round_source.records["ot-pilot"]
    wo_source = deployment.resolvers["work_orders"]
    assert wo_source.records["ot-pilot"]["PIC-101"]["work_order"] == "WO-1201"
    assert wo_source.records["ot-pilot"]["V-12"]["work_order"] == "WO-1204"


def test_the_image_and_compose_file_ship_the_ws1_module_and_the_bundle_mount():
    dockerfile = (PILOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PILOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "COPY deploy/ot-pilot/ot_ws1.py /app/ot_ws1.py" in dockerfile
    assert "COPY deploy/ot-pilot/ot_ws1_facts.json /app/ot_ws1_facts.json" in dockerfile
    assert "REMORA_WS1_MODE: shadow" in compose and "REMORA_WS1_DEPLOYMENT_MODULE: ot_ws1" in compose
    assert "./toolspec-bundle.json:/app/toolspec-bundle.json:ro" in compose
    assert "REMORA_TOOLSPEC_PINNED_DIGEST: ${OT_TOOLSPEC_PINNED_DIGEST" in compose
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/ot-pilot/toolspec-bundle.json" in gitignore and "deploy/ot-pilot/.toolspec-seed" in gitignore
