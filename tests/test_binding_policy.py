# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CR-006 (A2): a strict deployment states what must be bound, and starts only
when it can compare it.

Before: most lease bindings were configuration-conditional. Probe at b9ade2b:
under a strict profile a lease carrying a resolved-effect hash executed with
no resolver bound; task identity, capability set and actor were skipped when
absent; nothing refused at startup.

After: the strict profiles are versioned contracts. review/v2 and
controlled_pilot/v2 (the default for a bare name) require a BindingPolicy in
which every binding is REQUIRED, NOT_APPLICABLE (per read-only tool, for
resolved_effect only) or UNVERIFIABLE (declared, non-core). A REQUIRED binding
without its comparator refuses startup; at dispatch every REQUIRED binding is
compared before the nonce is spent.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.enforcement.binding_policy import (
    BINDINGS,
    BindingPolicy,
    BindingPolicyError,
)
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.enforcement.resolved_effect import ClosedWorldResolver
from remora.profiles import RuntimeProfileError, runtime_profile_contract

ROOT = Path(__file__).resolve().parents[1]
ARGS = {"id": "WO-1"}


def _policy(**changes) -> dict:
    bindings = {b: "REQUIRED" for b in BINDINGS}
    bindings.update(changes.pop("bindings", {}))
    return {"schema": "remora-binding-policy/v1", "bindings": bindings,
            "tools": changes.pop("tools", {})}


# -- the policy model ----------------------------------------------------------

def test_a_policy_stating_every_binding_loads_and_has_a_stable_digest() -> None:
    a, b = BindingPolicy.from_mapping(_policy()), BindingPolicy.from_mapping(_policy())
    assert a.digest == b.digest and len(a.digest) == 64
    assert all(a.required(binding) for binding in BINDINGS)


@pytest.mark.parametrize("binding", BINDINGS)
def test_a_missing_binding_is_refused_because_implicit_is_not_a_state(binding) -> None:
    raw = _policy()
    del raw["bindings"][binding]
    with pytest.raises(BindingPolicyError, match=f"{binding}: missing"):
        BindingPolicy.from_mapping(raw)


@pytest.mark.parametrize("bad", ["OPTIONAL", "", "required", None])
def test_only_the_three_states_exist(bad) -> None:
    raw = _policy(bindings={"actor": bad})
    with pytest.raises(BindingPolicyError):
        BindingPolicy.from_mapping(raw)


def test_not_applicable_is_never_deployment_wide() -> None:
    with pytest.raises(BindingPolicyError, match="NOT_APPLICABLE is per tool"):
        BindingPolicy.from_mapping(_policy(bindings={"resolved_effect": "NOT_APPLICABLE"}))


@pytest.mark.parametrize("core", ["exact_call", "toolspec", "tenant", "resolved_effect",
                                  "runtime_surface", "actor", "audience"])
def test_a_core_binding_cannot_be_declared_unverifiable(core) -> None:
    with pytest.raises(BindingPolicyError, match="core binding"):
        BindingPolicy.from_mapping(_policy(bindings={core: "UNVERIFIABLE"}))


def test_non_core_bindings_may_be_declared_unverifiable_and_are_listed() -> None:
    policy = BindingPolicy.from_mapping(_policy(bindings={"task_identity": "UNVERIFIABLE"}))
    assert policy.unverifiable() == ("task_identity",)


def test_per_tool_overrides_are_limited_to_resolved_effect_not_applicable() -> None:
    ok = BindingPolicy.from_mapping(_policy(tools={"read_x": {"resolved_effect": "NOT_APPLICABLE"}}))
    assert ok.state("resolved_effect", "read_x") == "NOT_APPLICABLE"
    assert ok.state("resolved_effect", "write_y") == "REQUIRED"
    for bad in ({"actor": "NOT_APPLICABLE"}, {"resolved_effect": "UNVERIFIABLE"}):
        with pytest.raises(BindingPolicyError):
            BindingPolicy.from_mapping(_policy(tools={"x": bad}))


def test_a_not_applicable_tool_must_be_signed_read_only() -> None:
    policy = BindingPolicy.from_mapping(_policy(tools={
        "read_x": {"resolved_effect": "NOT_APPLICABLE"},
        "write_y": {"resolved_effect": "NOT_APPLICABLE"},
        "ghost": {"resolved_effect": "NOT_APPLICABLE"}}))
    problems = policy.check_read_only_exemptions(
        {"read_x": "read", "write_y": "write"}, {"read", "search"})
    assert any("write_y" in p and "'write'" in p for p in problems)
    assert any("ghost" in p and "not in the signed" in p for p in problems)
    assert not any("read_x" in p for p in problems)


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda r: r.update(schema="remora-binding-policy/v0"), "schema must be"),
    (lambda r: r["bindings"].update(extra_binding="REQUIRED"), "unknown bindings"),
    (lambda r: r.update(tools={"x": "NOT_APPLICABLE"}), "overrides must be a mapping"),
])
def test_malformed_policies_are_refused_with_a_named_problem(mutate, match) -> None:
    raw = _policy()
    mutate(raw)
    with pytest.raises(BindingPolicyError, match=match):
        BindingPolicy.from_mapping(raw)


def test_bindings_must_be_a_mapping() -> None:
    with pytest.raises(BindingPolicyError, match="bindings must be a mapping"):
        BindingPolicy.from_mapping({"schema": "remora-binding-policy/v1", "bindings": ["actor"]})


def test_a_policy_file_must_hold_a_mapping(tmp_path) -> None:
    from remora.enforcement.binding_policy import load_binding_policy

    path = tmp_path / "policy.yaml"
    path.write_text("- REQUIRED\n", encoding="utf-8")
    with pytest.raises(BindingPolicyError, match="is a mapping"):
        load_binding_policy(path)


# -- versioned contracts ---------------------------------------------------------

@pytest.mark.parametrize(("value", "contract"), [
    ("review", "review/v2"), ("review/v2", "review/v2"), ("review/v1", "review/v1"),
    ("pilot", "controlled_pilot/v2"), ("research", "research"), ("", "research"),
])
def test_a_bare_strict_profile_is_the_latest_contract(monkeypatch, value, contract) -> None:
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", value)
    assert runtime_profile_contract() == contract


@pytest.mark.parametrize("value", ["review/v3", "research/v2", "review/"])
def test_unknown_or_misplaced_versions_are_refused(monkeypatch, value) -> None:
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", value)
    with pytest.raises(RuntimeProfileError):
        runtime_profile_contract()


# -- startup refusal ---------------------------------------------------------------

@pytest.fixture
def strict(monkeypatch, tmp_path):
    """A complete v2 configuration from the scaffold; tests then break one thing."""
    from remora.scaffold import init_review

    monkeypatch.chdir(tmp_path)
    init_review(tmp_path / ".remora")
    env = {}
    for line in (tmp_path / ".remora" / "authority.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("export "):
            key, _, raw = line[len("export "):].partition("=")
            env[key] = shlex.split(raw)[0]
    for name in ("REMORA_TOOLSPEC_SIGNING_KEY", "REMORA_LEASE_SIGNING_KEY",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_PG_DSN",
                 "REMORA_CAPABILITY_POLICY_FILE"):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(env["PYTHONPATH"])
    return env, tmp_path


def _validate():
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    return validate_runtime_profile_prerequisites()


def test_the_scaffold_configuration_satisfies_review_v2(strict, caplog) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        assert _validate() == "review"
    accepted = [r.getMessage() for r in caplog.records if "binding_policy.accepted" in r.getMessage()]
    assert accepted and "review/v2" in accepted[-1]
    assert "task_identity" in accepted[-1]  # the declared gap is recorded


def test_v2_without_a_binding_policy_refuses(strict, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_BINDING_POLICY")
    with pytest.raises(RuntimeProfileError, match="requires REMORA_BINDING_POLICY"):
        _validate()


def test_a_missing_resolver_is_not_not_applicable(strict, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_EFFECT_REGISTRY_MODULE")
    with pytest.raises(RuntimeProfileError, match="missing resolver is not NOT_APPLICABLE"):
        _validate()


def test_capability_set_required_needs_a_capability_policy(strict, monkeypatch, tmp_path) -> None:
    path = tmp_path / "policy.yaml"
    import yaml

    path.write_text(yaml.safe_dump(_policy()), encoding="utf-8")
    monkeypatch.setenv("REMORA_BINDING_POLICY", str(path))
    with pytest.raises(RuntimeProfileError, match="REMORA_CAPABILITY_POLICY_FILE"):
        _validate()


def test_a_write_tool_cannot_be_exempted_from_resolved_effect(strict, monkeypatch, tmp_path) -> None:
    import yaml

    raw = _policy(bindings={"task_identity": "UNVERIFIABLE", "capability_set": "UNVERIFIABLE"},
                  tools={"send_notification": {"resolved_effect": "NOT_APPLICABLE"}})
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv("REMORA_BINDING_POLICY", str(path))
    with pytest.raises(RuntimeProfileError, match="needs a read-only action"):
        _validate()


def test_v1_remains_selectable_explicitly_without_a_policy(strict, monkeypatch, caplog) -> None:
    import logging

    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    monkeypatch.delenv("REMORA_BINDING_POLICY")
    with caplog.at_level(logging.WARNING):
        assert _validate() == "review"
    assert any("runtime_profile.legacy_contract" in r.getMessage() for r in caplog.records)


def test_the_api_refuses_to_start_not_to_serve(strict) -> None:
    env, tmp = strict
    child = {**os.environ, **env, "PYTHONPATH": os.pathsep.join([str(ROOT), env["PYTHONPATH"]])}
    child.pop("REMORA_BINDING_POLICY")
    result = subprocess.run([sys.executable, "-c", "import servers.api"], cwd=tmp, env=child,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode != 0
    assert "requires REMORA_BINDING_POLICY" in result.stderr


def test_the_scaffold_effect_registry_resolves_the_demo_tool(strict) -> None:
    import importlib

    resolver = importlib.import_module("remora_effects").build_resolver()
    effect = resolver.resolve("send_notification", {"to": "ops@example.com"}, "prod")
    assert (effect.tool_name, effect.effect) == ("send_notification", "send")


# -- the dispatcher compares what the policy requires --------------------------------

@pytest.fixture
def lease_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "binding-policy-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _lease(*, actor="agent-1", effect_hash="", surface="") -> ExecutionLease:
    from remora.enforcement.resolved_effect import ResolvedEffect

    resolved = ResolvedEffect("wo_close", "impl@1", "env:prod", "write") if effect_hash else None
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity=actor, tool_name="wo_close",
        arguments=ARGS, target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), resolved_effect=resolved, surface_digest=surface)


def _dispatcher(policy: BindingPolicy, *, resolver=None, observer=None):
    dispatcher = GovernedToolDispatcher("b1")
    dispatcher.register("wo_close", lambda args: "ok")
    if resolver is not None:
        dispatcher.bind_effect_resolver(resolver)
    if observer is not None:
        dispatcher.bind_surface_observer(observer)
    dispatcher.bind_binding_policy(policy)
    return dispatcher


def _run(dispatcher, lease, actor="agent-1"):
    return dispatcher.dispatch(lease, "wo_close", ARGS, tenant_id="acme",
                               target_environment="prod", actor_identity=actor)


_RESOLVER = ClosedWorldResolver(tools={"wo_close": ("impl@1", "write")}, resources={},
                                resource_argument={})
_LENIENT = dict(task_identity="UNVERIFIABLE", capability_set="UNVERIFIABLE")


def _p(**extra) -> BindingPolicy:
    return BindingPolicy.from_mapping(_policy(bindings={**_LENIENT, **extra.pop("bindings", {})},
                                              **extra))


def test_a_required_resolved_effect_without_a_resolver_refuses(lease_key) -> None:
    result = _run(_dispatcher(_p(), observer=lambda: "s"), _lease(effect_hash="x", surface="s"))
    assert result.refusal_reason == "resolved_effect_unverifiable"


def test_a_required_resolved_effect_refuses_a_lease_without_one(lease_key) -> None:
    result = _run(_dispatcher(_p(), resolver=_RESOLVER, observer=lambda: "s"), _lease(surface="s"))
    assert result.refusal_reason == "resolved_effect_unbound"


def test_a_not_applicable_tool_needs_no_resolver(lease_key) -> None:
    policy = _p(tools={"wo_close": {"resolved_effect": "NOT_APPLICABLE"}})
    result = _run(_dispatcher(policy, observer=lambda: "s"), _lease(surface="s"))
    assert result.executed, result.refusal_reason


def test_a_required_surface_without_an_observer_refuses(lease_key) -> None:
    policy = _p(tools={"wo_close": {"resolved_effect": "NOT_APPLICABLE"}})
    assert _run(_dispatcher(policy), _lease(surface="s")).refusal_reason == "surface_unobservable"


def test_a_required_surface_refuses_a_lease_naming_none(lease_key) -> None:
    policy = _p(tools={"wo_close": {"resolved_effect": "NOT_APPLICABLE"}})
    assert _run(_dispatcher(policy, observer=lambda: "s"), _lease()).refusal_reason == "surface_unbound"


def test_a_required_actor_refuses_a_lease_naming_none(lease_key) -> None:
    policy = _p(tools={"wo_close": {"resolved_effect": "NOT_APPLICABLE"}})
    result = _run(_dispatcher(policy, observer=lambda: "s"), _lease(actor="", surface="s"), actor="")
    assert result.refusal_reason == "actor_unbound"


def test_a_required_task_identity_refuses_a_call_naming_none(lease_key) -> None:
    policy = BindingPolicy.from_mapping(_policy(
        bindings={"capability_set": "UNVERIFIABLE"},
        tools={"wo_close": {"resolved_effect": "NOT_APPLICABLE"}}))
    result = _run(_dispatcher(policy, observer=lambda: "s"), _lease(surface="s"))
    assert result.refusal_reason == "task_identity_required"


def test_every_policy_refusal_leaves_the_nonce_unspent(lease_key) -> None:
    policy = _p(tools={"wo_close": {"resolved_effect": "NOT_APPLICABLE"}})
    dispatcher = _dispatcher(policy, observer=lambda: "s")
    lease = _lease(surface="")
    assert _run(dispatcher, lease).refusal_reason == "surface_unbound"
    assert lease.nonce not in dispatcher._ledger._consumed
