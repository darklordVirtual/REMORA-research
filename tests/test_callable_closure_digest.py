# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Callable identity covers the import closure, not only the source span (Q3.4).

A v1 ToolSpec attests ``sha256:`` over ``inspect.getsource(fn)``. Change a
helper the tool calls and that digest does not move: the approved spec keeps
verifying while the code that runs is different. A ``closure-sha256:``
digest covers the defining module and every module it transitively imports
from its own package, so the acceptance criterion holds: a dependency change
fails verification.
"""
from __future__ import annotations

import importlib
import secrets
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.enforcement.lease import GovernedToolDispatcher
from remora.toolcall.runtime_surface import RuntimeTool, canonical_json
from remora.toolcall.signed_surface_runtime import (
    SignedSurfaceRuntime,
    closure_digest,
    closure_members,
    source_digest,
)
from remora.toolcall.toolspec import ToolSpecRefused, sign_bundle


@pytest.fixture()
def package(tmp_path, monkeypatch):
    """A throwaway package: tool imports helper; other is unrelated."""
    name = f"closurepkg_{secrets.token_hex(4)}"
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "helper.py").write_text("def scale(x):\n    return x * 2\n")
    (root / "other.py").write_text("UNUSED = 1\n")
    (root / "tool.py").write_text(textwrap.dedent(f"""
        from {name}.helper import scale
        import json

        def run(arguments):
            return json.dumps({{"value": scale(arguments["value"])}})
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module(f"{name}.tool")
    yield name, root, module
    for key in [k for k in sys.modules if k.startswith(name)]:
        del sys.modules[key]


class TestTheClosure:
    def test_the_closure_follows_the_package_and_names_the_rest(self, package):
        name, _, module = package
        members = closure_members(module.run)
        assert {f"{name}.tool", f"{name}.helper", "json"} <= set(members)
        assert f"{name}.other" not in members
        assert members["json"].startswith("stdlib:")

    def test_changing_a_dependency_moves_the_closure_digest(self, package):
        _, root, module = package
        before = closure_digest(module.run)
        source_before = source_digest(module.run)
        (root / "helper.py").write_text("def scale(x):\n    return x * 3\n")
        assert closure_digest(module.run) != before
        assert source_digest(module.run) == source_before, (
            "the v1 source-span digest cannot see this change; that is the gap")

    def test_an_unrelated_module_does_not_move_it(self, package):
        _, root, module = package
        before = closure_digest(module.run)
        (root / "other.py").write_text("UNUSED = 2\n")
        assert closure_digest(module.run) == before

    def test_the_digest_is_stable(self, package):
        _, _, module = package
        assert closure_digest(module.run) == closure_digest(module.run)
        assert closure_digest(module.run).startswith("closure-sha256:")


def _runtime(fn, digest):
    raw = dict(tool_id="write", version=1, callable_digest=digest,
               implementation_identity="closure-fixture-v1", description="Write.",
               argument_schema={"type": "object", "properties": {"value": {"type": "integer"}},
                                "required": ["value"], "additionalProperties": False},
               risk_tier="medium", action_type="write", domain="general", capabilities=["record"],
               semantic_contract={"effect": "update"}, credential_scope=["record:write"],
               allowed_targets=["record"], idempotency_contract={"safe_to_retry": False},
               postcondition_reader="reader", compensation_tool=None,
               timeout_policy={"dispatch_timeout_seconds": 10}, network_policy={"egress": "none"},
               signing_identity="signer")
    key = secrets.token_hex(32)
    bundle = sign_bundle({"schema_version": 1, "tool_specs": [raw]}, key=key,
                         signing_identity="signer", signed_at=datetime.now(UTC).isoformat())
    runtime = SignedSurfaceRuntime(GovernedToolDispatcher("policy"), bundle, key=key,
                                   trusted_identities=["signer"])
    spec = runtime._bundle.get("write")
    observed = RuntimeTool("write", "native", True, True, spec.toolspec_hash,
                           implementation_identity="closure-fixture-v1",
                           argument_schema_json=canonical_json(raw["argument_schema"]))
    return runtime, observed


class TestRegistrationVerifiesTheClosure:
    def test_the_attested_closure_registers(self, package):
        _, _, module = package
        runtime, observed = _runtime(module.run, closure_digest(module.run))
        runtime.register(observed, module.run)

    def test_a_dependency_changed_after_signing_is_refused(self, package):
        _, root, module = package
        runtime, observed = _runtime(module.run, closure_digest(module.run))
        (root / "helper.py").write_text("def scale(x):\n    return x * 3\n")
        with pytest.raises(ToolSpecRefused) as refusal:
            runtime.register(observed, module.run)
        assert refusal.value.reason_code == "toolspec_callable_digest_mismatch"

    def test_a_v1_source_span_spec_still_verifies_as_before(self, package):
        _, _, module = package
        runtime, observed = _runtime(module.run, source_digest(module.run))
        runtime.register(observed, module.run)
