# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""``remora build-toolspec``: the packaged way for a host to author a signed
ToolSpec bundle.

Until this command the only flow was the pilot's own script under
``deploy/ot-pilot``, which a host that installs the wheel does not have. The
command measures each tool's callable the way registration does, signs with a
seed the caller holds, and refuses to write a bundle the runtime loader would
refuse to load.
"""
from __future__ import annotations

import hashlib
import json
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from remora.cli import main as cli_main  # noqa: E402

SEED = "11" * 32
STAMP = "2026-01-01T00:00:00+00:00"


def _spec(**overrides):
    description = "Move one setpoint on the plant."
    spec = {
        "tool_id": "write_setpoint",
        "version": 1,
        "callable": "host_tools:write_setpoint",
        "implementation_identity": "host_tools.write_setpoint@test",
        "description": description,
        "argument_schema": {
            "type": "object",
            "properties": {"tag": {"type": "string"},
                           "value": {"type": "number", "minimum": 16, "maximum": 24}},
            "required": ["tag", "value"],
            "additionalProperties": False,
        },
        "risk_tier": "medium",
        "action_type": "write",
        "domain": "ot",
        "capabilities": ["setpoint.write"],
        "semantic_contract": {"capability": "setpoint.write", "effect": "write",
                              "resource_type": "setpoint", "mutation": True,
                              "argument_roles": {"tag": "resource"}},
        "credential_scope": ["ot:setpoint.write"],
        "allowed_targets": ["staging"],
        "idempotency_contract": {"safe_to_retry": False, "key_derivation": "canonical_args"},
        "postcondition_reader": None,
        "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 15},
        "network_policy": {"egress": "none"},
    }
    spec.update(overrides)
    return {k: v for k, v in spec.items() if v is not ...}


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """A host directory holding the tool's callable and a place for the output."""
    (tmp_path / "host_tools.py").write_text(textwrap.dedent('''
        def write_setpoint(tag, value):
            """Stand in for a plant write."""
            return {"tag": tag, "value": value}
    '''), encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_SEED", SEED)
    monkeypatch.delitem(sys.modules, "host_tools", raising=False)
    yield tmp_path
    sys.modules.pop("host_tools", None)
    if str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))


def _build(host: Path, bundle: dict, *extra: str) -> tuple[int, Path]:
    source = host / "unsigned.json"
    source.write_text(json.dumps(bundle), encoding="utf-8")
    out = host / "toolspec-bundle.json"
    rc = cli_main(["build-toolspec", str(source), "--out", str(out),
                   "--module-path", str(host), *extra])
    return rc, out


def test_build_toolspec_signs_a_bundle_the_runtime_loads(host, capsys):
    from remora.crypto import SignatureDomain, VerificationKey
    from remora.toolcall.toolspec import ToolSpecBundle

    rc, out = _build(host, {"schema_version": 5, "tool_specs": [_spec()]})
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    signed = json.loads(out.read_text(encoding="utf-8"))

    key = VerificationKey.from_text(printed["public_key"], [SignatureDomain.TOOLSPEC_BUNDLE])
    bundle = ToolSpecBundle.load(
        signed, verification_keys=[key], accept_hmac=False,
        pinned_bundle_digest=printed["pinned_digest"], require_pinned_digest=True)
    assert "write_setpoint" in bundle and len(bundle) == 1
    assert printed["tools"] == 1 and printed["signing_identity"] == key.kid
    assert SEED not in out.read_text(encoding="utf-8") + json.dumps(printed)


def test_build_toolspec_measures_the_callable_as_registration_does(host, capsys):
    from remora.toolcall.callable_digest import source_digest

    rc, out = _build(host, {"schema_version": 5, "tool_specs": [_spec()]})
    assert rc == 0
    spec = json.loads(out.read_text(encoding="utf-8"))["tool_specs"][0]
    import host_tools

    assert spec["callable_digest"] == source_digest(host_tools.write_setpoint)
    assert "callable" not in spec
    assert spec["description_sha256"] == hashlib.sha256(
        spec["description"].encode("utf-8")).hexdigest()


def test_build_toolspec_keeps_a_declared_digest(host):
    declared = "sha256:" + "ab" * 32
    spec = _spec(callable=..., callable_digest=declared)
    rc, out = _build(host, {"schema_version": 5, "tool_specs": [spec]})
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["tool_specs"][0][
        "callable_digest"] == declared


def test_build_toolspec_is_reproducible_for_one_seed_and_signing_time(host):
    bundle = {"schema_version": 5, "tool_specs": [_spec()]}
    rc, out = _build(host, bundle, "--signed-at", STAMP)
    first = out.read_bytes()
    rc2, out = _build(host, bundle, "--signed-at", STAMP)
    assert rc == rc2 == 0 and out.read_bytes() == first


@pytest.mark.parametrize("broken, why", [
    (lambda s: s.pop("risk_tier"), "missing"),
    (lambda s: s["argument_schema"]["properties"]["value"].update(multipleOf=0.5),
     "argument_schema"),
    (lambda s: s.update(callable="host_tools:no_such_function"), "no_such_function"),
    (lambda s: s.update(callable="no_such_module:fn"), "no_such_module"),
    (lambda s: s.update(callable_digest="sha256:" + "ab" * 32), "both"),
    (lambda s: s.pop("callable"), "callable"),
])
def test_build_toolspec_refuses_and_writes_nothing(host, capsys, broken, why):
    spec = _spec()
    broken(spec)
    rc, out = _build(host, {"schema_version": 5, "tool_specs": [spec]})
    assert rc != 0 and not out.exists()
    assert why in capsys.readouterr().err


def test_build_toolspec_refuses_an_empty_bundle_and_a_duplicate_tool(host, capsys):
    rc, out = _build(host, {"schema_version": 5, "tool_specs": []})
    assert rc != 0 and not out.exists()
    rc, out = _build(host, {"schema_version": 5, "tool_specs": [_spec(), _spec()]})
    assert rc != 0 and not out.exists()
    assert "write_setpoint" in capsys.readouterr().err


def test_build_toolspec_needs_the_seed_from_the_environment(host, monkeypatch, capsys):
    monkeypatch.delenv("REMORA_TOOLSPEC_SIGNING_SEED")
    rc, out = _build(host, {"schema_version": 5, "tool_specs": [_spec()]})
    assert rc == 2 and not out.exists()
    assert "REMORA_TOOLSPEC_SIGNING_SEED" in capsys.readouterr().err


def test_build_toolspec_new_key_prints_seed_and_public_key(capsys):
    rc = cli_main(["build-toolspec", "--new-key"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(bytes.fromhex(payload["seed"])) == 32 and payload["public_key"]


def test_sign_limits_is_reproducible_for_one_seed_and_signing_time(tmp_path, monkeypatch):
    policy = json.loads((Path(__file__).resolve().parents[1] / "deploy" / "ot-pilot"
                         / "limits.json").read_text(encoding="utf-8"))["policy"]
    monkeypatch.setenv("REMORA_LIMITS_SIGNING_SEED", SEED)
    source = tmp_path / "policy.json"
    source.write_text(json.dumps(policy), encoding="utf-8")
    outputs = []
    for name in ("a.json", "b.json"):
        out = tmp_path / name
        assert cli_main(["sign-limits", str(source), "--out", str(out),
                         "--signed-at", "2026-01-01T00:00:00Z"]) == 0
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["signed_at"] == "2026-01-01T00:00:00Z"


def test_a_malformed_signing_time_is_refused(host, capsys):
    rc, out = _build(host, {"schema_version": 5, "tool_specs": [_spec()]},
                     "--signed-at", "yesterday")
    assert rc == 2 and not out.exists()
    assert "--signed-at" in capsys.readouterr().err
