# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CR-005: under the strict v2 contract privileged tools reach effects only
through the mediator, and say so in their signed spec.

Before: a write tool's spec said nothing about how the tool reached effects,
its code ran in the process holding the effect credential, and registering it
unmediated was accepted. Probe at b9ade2b: the scaffold's demo tool read the
credential from its own environment and wrote the effect directly.

After: ToolSpec schema version 3 carries ``effect_mode`` (MEDIATED | NONE) and
``credential_policy.direct_effect_credentials``. With effect_mediation
REQUIRED, a spec that leaves the mode unstated, a MEDIATED tool registered
unmediated, a NONE tool that declares capabilities or is not read-only, and an
executor that holds effect credentials all refuse: at startup, at
registration and at dispatch, before the nonce is spent.

What this does not establish: that a deployment's effect credentials are
unreachable outside the mediator. That is a property of the deployment, and
stays NOT_ESTABLISHED.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.enforcement.binding_policy import BINDINGS, BindingPolicy
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.execution.effect_policy import effect_policy_refusal, static_effect_policy_refusal
from remora.profiles import RuntimeProfileError
from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused, sign_bundle
from tests.test_toolspec_runtime import IDENTITY, KEY, _spec

ROOT = Path(__file__).resolve().parents[1]
CEILING = [{"capability": "notification.send", "resources": ["notification://outbox"],
            "purpose": "deliver"}]
MEDIATED = {"effect_mode": "MEDIATED", "downstream_capabilities": CEILING,
            "credential_policy": {"direct_effect_credentials": "FORBIDDEN"}}


def _load(schema_version: int = 3, **fields):
    bundle = sign_bundle({"schema_version": schema_version, "tool_specs": [_spec(**fields)]},
                         key=KEY, signing_identity=IDENTITY,
                         signed_at="2026-10-07T00:00:00+00:00")
    return ToolSpecBundle.load(bundle, key=KEY, trusted_identities=[IDENTITY])


def _one(**fields):
    return _load(**fields).get("store_artifact")


# -- the signed fields ---------------------------------------------------------

def test_a_v3_spec_carries_its_effect_policy() -> None:
    spec = _one(**MEDIATED)
    assert (spec.effect_mode, spec.direct_effect_credentials) == ("MEDIATED", "FORBIDDEN")


def test_an_unstated_effect_mode_stays_unknown_never_none() -> None:
    spec = _one()
    assert spec.effect_mode is None
    assert static_effect_policy_refusal(spec) == "effect_mode_missing"


@pytest.mark.parametrize("version", [1, 2])
def test_an_effect_policy_needs_schema_version_3(version) -> None:
    fields = {"effect_mode": "NONE"} if version == 1 else MEDIATED
    with pytest.raises(ToolSpecRefused) as exc:
        _load(schema_version=version, **fields)
    assert exc.value.reason_code == "toolspec_effect_policy_requires_v3"


@pytest.mark.parametrize("fields", [
    {"effect_mode": "SOMETIMES"},
    {"effect_mode": "MEDIATED", "credential_policy": "FORBIDDEN"},
    {"effect_mode": "MEDIATED", "credential_policy": {"direct_effect_credentials": "MAYBE"}},
    {"effect_mode": "MEDIATED", "credential_policy": {}},
])
def test_a_malformed_effect_policy_is_refused(fields) -> None:
    with pytest.raises(ToolSpecRefused) as exc:
        _load(**fields)
    assert exc.value.reason_code == "toolspec_effect_policy_invalid"


# -- the rules -------------------------------------------------------------------

_FORBIDDEN = {"credential_policy": {"direct_effect_credentials": "FORBIDDEN"}}


@pytest.mark.parametrize("fields, mediated, refusal", [
    (MEDIATED, True, None),
    (MEDIATED, False, "effect_mediation_not_registered"),
    ({"effect_mode": "MEDIATED", **_FORBIDDEN}, True, "effect_capabilities_missing"),
    ({"effect_mode": "MEDIATED", "downstream_capabilities": [], **_FORBIDDEN}, True,
     "effect_capabilities_missing"),
    ({**MEDIATED, "credential_policy": {"direct_effect_credentials": "PERMITTED"}}, True,
     "direct_effect_credentials_not_forbidden"),
    ({"effect_mode": "MEDIATED", "downstream_capabilities": CEILING}, True,
     "direct_effect_credentials_not_forbidden"),
    ({"effect_mode": "NONE", "action_type": "read", **_FORBIDDEN}, False, None),
    ({"effect_mode": "NONE", "action_type": "read", **_FORBIDDEN}, True,
     "effect_none_registered_mediated"),
    ({"effect_mode": "NONE", "action_type": "read", "downstream_capabilities": CEILING,
      **_FORBIDDEN}, False, "effect_none_declares_capabilities"),
    # NONE is a signed claim, not proof: a write tool cannot make it.
    ({"effect_mode": "NONE", "downstream_capabilities": [], **_FORBIDDEN}, False,
     "effect_none_for_consequential_tool"),
])
def test_the_effect_policy_rules(fields, mediated, refusal) -> None:
    assert effect_policy_refusal(_one(**fields), mediated=mediated) == refusal


def test_an_empty_ceiling_is_not_read_as_none() -> None:
    spec = _one(downstream_capabilities=[], **_FORBIDDEN)
    assert spec.effect_mode is None
    assert effect_policy_refusal(spec, mediated=False) == "effect_mode_missing"


# -- the dispatcher, before the nonce ----------------------------------------------

@pytest.fixture
def lease_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "effect-mediation-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _policy(**bindings) -> BindingPolicy:
    states = {b: "REQUIRED" for b in BINDINGS}
    states.update(task_identity="UNVERIFIABLE", capability_set="UNVERIFIABLE", **bindings)
    return BindingPolicy.from_mapping({
        "schema": "remora-binding-policy/v1", "bindings": states,
        "tools": {"store_artifact": {"resolved_effect": "NOT_APPLICABLE"}}})


def _dispatcher(check, **bindings) -> GovernedToolDispatcher:
    dispatcher = GovernedToolDispatcher("b1")
    dispatcher.register("store_artifact", lambda args: "stored")
    dispatcher.bind_surface_observer(lambda: "s")
    dispatcher.bind_binding_policy(_policy(**bindings))
    if check is not None:
        dispatcher.bind_effect_policy(check)
    return dispatcher


def _dispatch(dispatcher):
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="store_artifact", arguments={"artifact_id": "a"},
        target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), surface_digest="s")
    result = dispatcher.dispatch(lease, "store_artifact", {"artifact_id": "a"},
                                 tenant_id="acme", target_environment="prod",
                                 actor_identity="agent-1")
    return lease, result


def _signed_check(spec):
    return lambda name, mediated: effect_policy_refusal(spec, mediated=mediated)


def test_a_mediated_tool_registered_unmediated_refuses_before_the_nonce(lease_key) -> None:
    dispatcher = _dispatcher(_signed_check(_one(**MEDIATED)))
    lease, result = _dispatch(dispatcher)
    assert result.refusal_reason == "effect_mediation_not_registered"
    assert not result.executed
    assert lease.nonce not in dispatcher._ledger._consumed


def test_an_unstated_effect_mode_refuses_at_dispatch(lease_key) -> None:
    dispatcher = _dispatcher(_signed_check(_one()))
    lease, result = _dispatch(dispatcher)
    assert result.refusal_reason == "effect_mode_missing"
    assert lease.nonce not in dispatcher._ledger._consumed


def test_a_required_effect_policy_without_a_check_is_unverifiable(lease_key) -> None:
    dispatcher = _dispatcher(None)
    lease, result = _dispatch(dispatcher)
    assert result.refusal_reason == "effect_policy_unverifiable"
    assert lease.nonce not in dispatcher._ledger._consumed


def test_without_effect_mediation_the_check_is_not_consulted(lease_key) -> None:
    """The v1 path and research use: no policy requirement, no effect check."""
    dispatcher = _dispatcher(lambda name, mediated: "never")
    policy = dispatcher._binding_policy
    dispatcher.bind_binding_policy(dataclasses.replace(
        policy, bindings={**policy.bindings, "effect_mediation": "UNVERIFIABLE"}))
    _, result = _dispatch(dispatcher)
    assert result.executed, result.refusal_reason


def test_a_read_only_none_tool_dispatches(lease_key) -> None:
    spec = _one(effect_mode="NONE", action_type="read", **_FORBIDDEN)
    _, result = _dispatch(_dispatcher(_signed_check(spec)))
    assert result.executed, result.refusal_reason


# -- startup -----------------------------------------------------------------------

def _env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("export "):
            key, _, raw = line[len("export "):].partition("=")
            env[key] = shlex.split(raw)[0]
    return env


@pytest.fixture
def executor(monkeypatch, tmp_path):
    """The scaffold's execution domain, review/v2, effect_mediation REQUIRED."""
    pytest.importorskip("cryptography")
    from remora.execution.authorization import reset_toolspec_bundle_cache
    from remora.scaffold import init_review

    monkeypatch.chdir(tmp_path)
    init_review(tmp_path / ".remora")
    env = _env(tmp_path / ".remora" / "executor.env")
    # One name per line: a generic secret scanner reads `"X", "Y_KEY"` on one
    # line as an assignment of a secret. These are variable names.
    for name in (
        "REMORA_TOOLSPEC_SIGNING_KEY",
        "REMORA_LEASE_SIGNING_KEY",
        "REMORA_PG_DSN",
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_PDP_SIGNING_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(env["PYTHONPATH"])
    reset_toolspec_bundle_cache()
    yield env, tmp_path / ".remora"
    reset_toolspec_bundle_cache()


def _validate():
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    return validate_runtime_profile_prerequisites()


def test_the_scaffold_executor_satisfies_mandatory_mediation(executor) -> None:
    assert _validate() == "review"


def test_an_executor_holding_the_effect_credential_refuses(executor, monkeypatch) -> None:
    """The two-domain layout: custody accepts it, mandatory mediation does not."""
    env, _ = executor
    monkeypatch.delenv("REMORA_EFFECT_ENDPOINT")
    monkeypatch.setenv(env["REMORA_EFFECT_CREDENTIAL_ENV_NAMES"], "demo-credential")
    with pytest.raises(RuntimeProfileError, match="REMORA_EFFECT_ENDPOINT"):
        _validate()


def test_mediated_tools_need_a_required_capability_set(executor, monkeypatch, tmp_path) -> None:
    import yaml

    states = {b: "REQUIRED" for b in BINDINGS}
    states.update(task_identity="UNVERIFIABLE", capability_set="UNVERIFIABLE")
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump({"schema": "remora-binding-policy/v1", "bindings": states,
                                    "tools": {}}), encoding="utf-8")
    monkeypatch.setenv("REMORA_BINDING_POLICY", str(path))
    with pytest.raises(RuntimeProfileError, match="capability_set must be REQUIRED"):
        _validate()


def _resign(root: Path, monkeypatch, **changes) -> None:
    """Re-sign the scaffold bundle with one spec field changed, and pin it."""
    from remora.execution.authorization import reset_toolspec_bundle_cache
    from remora.toolcall.toolspec_sign import sign_with_seed

    signed = json.loads((root / "toolspec-bundle.json").read_text(encoding="utf-8"))
    spec = dict(signed["tool_specs"][0])
    for key, value in changes.items():
        if value is None:
            spec.pop(key, None)
        else:
            spec[key] = value
    seed = (root / "keys" / "toolspec_ed25519_seed").read_text(encoding="utf-8").strip()
    bundle, public, digest = sign_with_seed({"schema_version": 3, "tool_specs": [spec]}, seed,
                                            signed_at=signed["registry_signature"]["signed_at"])
    (root / "toolspec-bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOLSPEC_VERIFY_KEYS", public)
    monkeypatch.setenv("REMORA_TOOLSPEC_PINNED_DIGEST", digest)
    reset_toolspec_bundle_cache()


def test_a_signed_spec_without_an_effect_mode_refuses_startup(executor, monkeypatch) -> None:
    _, root = executor
    _resign(root, monkeypatch, effect_mode=None)
    with pytest.raises(RuntimeProfileError, match="effect_mode_missing"):
        _validate()


def test_a_write_tool_signed_none_refuses_startup(executor, monkeypatch) -> None:
    _, root = executor
    _resign(root, monkeypatch, effect_mode="NONE", downstream_capabilities=None)
    with pytest.raises(RuntimeProfileError, match="effect_none_for_consequential_tool"):
        _validate()


def test_an_unmediated_registry_refuses_the_executor_at_startup(executor) -> None:
    """The API refuses to start, not to serve: the registration is checked eagerly."""
    env, root = executor
    (root / "unmediated_registry.py").write_text(
        "def register_tools(register):\n"
        "    register('send_notification', lambda arguments: {'status': 'direct'})\n",
        encoding="utf-8")
    child = {**os.environ, **env, "REMORA_TOOL_REGISTRY_MODULE": "unmediated_registry",
             "PYTHONPATH": os.pathsep.join([str(ROOT), env["PYTHONPATH"]])}
    result = subprocess.run([sys.executable, "-c", "import servers.api"], cwd=root.parent,
                            env=child, capture_output=True, text=True, timeout=180)
    assert result.returncode != 0
    assert "effect_mediation_not_registered" in result.stderr


def test_the_scaffold_executor_starts(executor) -> None:
    env, root = executor
    child = {**os.environ, **env,
             "PYTHONPATH": os.pathsep.join([str(ROOT), env["PYTHONPATH"]])}
    result = subprocess.run([sys.executable, "-c", "import servers.api"], cwd=root.parent,
                            env=child, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr[-2000:]


def test_a_tool_spec_copy_cannot_flip_its_mode_unsigned() -> None:
    """The mode is inside the signature: editing it after signing refuses the bundle."""
    bundle = sign_bundle({"schema_version": 3, "tool_specs": [_spec(**MEDIATED)]},
                         key=KEY, signing_identity=IDENTITY,
                         signed_at="2026-10-07T00:00:00+00:00")
    bundle["tool_specs"][0]["effect_mode"] = "NONE"
    with pytest.raises(ToolSpecRefused):
        ToolSpecBundle.load(bundle, key=KEY, trusted_identities=[IDENTITY])
    assert dataclasses.is_dataclass(_one(**MEDIATED))


# -- the API path, in process --------------------------------------------------------

@pytest.fixture
def api_executor(executor, monkeypatch):
    import servers.execution_api as exec_mod

    monkeypatch.setattr(exec_mod, "_BINDING_POLICY_CACHE", None)
    monkeypatch.setattr(exec_mod, "_current_policy_bundle_hash", lambda: "b1")
    exec_mod._reset_tool_dispatcher()
    yield exec_mod, executor[1]
    exec_mod._reset_tool_dispatcher()


def test_the_api_refuses_an_unmediated_registration(api_executor, monkeypatch) -> None:
    exec_mod, root = api_executor
    (root / "unmediated_registry_inproc.py").write_text(
        "def register_tools(register):\n"
        "    register('send_notification', lambda arguments: {'status': 'direct'})\n",
        encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "unmediated_registry_inproc")
    with pytest.raises(RuntimeProfileError, match="effect_mediation_not_registered"):
        exec_mod._tool_dispatcher()


def test_the_api_builds_the_executor_dispatcher_at_startup(api_executor) -> None:
    import servers.api as api_mod

    exec_mod, _ = api_executor
    api_mod._build_executor_dispatcher_at_startup()
    dispatcher = exec_mod._DISPATCHER
    assert dispatcher is not None and dispatcher.is_mediated("send_notification")


def test_startup_builds_nothing_outside_the_executor(api_executor, monkeypatch) -> None:
    import servers.api as api_mod

    exec_mod, _ = api_executor
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")
    api_mod._build_executor_dispatcher_at_startup()
    assert exec_mod._DISPATCHER is None


def test_the_api_effect_check_without_a_bundle_is_unverifiable(api_executor, monkeypatch) -> None:
    exec_mod, _ = api_executor
    assert exec_mod._effect_policy_check("send_notification", True) is None
    assert exec_mod._effect_policy_check("unsigned_tool", True) == "effect_mode_missing"
    monkeypatch.setattr(exec_mod, "_authz_load_bundle", lambda env: None)
    assert exec_mod._effect_policy_check("send_notification", True) == "effect_policy_unverifiable"


def test_mandatory_mediation_needs_a_signed_bundle(executor, monkeypatch) -> None:
    from remora.execution.authorization import reset_toolspec_bundle_cache

    from remora.enforcement.binding_policy import load_binding_policy
    from remora.toolcall.runtime_profile import _effect_mediation_problems

    # The strict prerequisites refuse a missing bundle first; the mediation
    # check refuses it on its own too, rather than passing an empty surface.
    policy = load_binding_policy(os.environ["REMORA_BINDING_POLICY"])
    monkeypatch.delenv("REMORA_TOOLSPEC_BUNDLE")
    reset_toolspec_bundle_cache()
    assert _effect_mediation_problems(policy) == [
        "effect_mediation is REQUIRED but no signed bundle is configured"]


def test_a_bundle_that_does_not_load_refuses_startup(executor, monkeypatch) -> None:
    from remora.execution.authorization import reset_toolspec_bundle_cache

    _, root = executor
    (root / "toolspec-bundle.json").write_text("{}", encoding="utf-8")
    reset_toolspec_bundle_cache()
    with pytest.raises(RuntimeProfileError, match="did not load"):
        _validate()

