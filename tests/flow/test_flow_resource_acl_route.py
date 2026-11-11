# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The execution API's resource ACL registry hook (REMORA_FLOW_RESOURCE_ACL_MODULE).

End to end it is measured by the arm ``remora_flow_resource_acl`` of
scripts/execution_chain_attack_eval.py (tests/test_execution_chain_attack_eval.py).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from remora.flow.label import PUBLIC  # noqa: E402
from tests.flow import acl_fixture  # noqa: E402


@pytest.fixture()
def api(monkeypatch):
    import servers.execution_api as exec_api

    monkeypatch.setattr(exec_api, "_FLOW_RESOURCE_ACL", None)
    monkeypatch.delenv("REMORA_FLOW_RESOURCE_ACL_MODULE", raising=False)
    acl_fixture.CALLS.clear()
    return exec_api


def test_no_registry_is_configured_by_default(api):
    assert api._flow_resource_acl("acme") is None


def test_the_registry_is_the_named_module_and_is_asked_per_tenant(api, monkeypatch):
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_MODULE", "tests.flow.acl_fixture")
    acme, other = api._flow_resource_acl("acme"), api._flow_resource_acl("globex")
    assert acme("res://records/secret") == ["user://acme/alice"]
    assert acme("res://records/pub-1") is PUBLIC
    # The tenant is the authenticated one, bound by the server; the caller of
    # the lookup cannot name another.
    assert other("res://records/secret") == []
    assert acl_fixture.CALLS == [("acme", "res://records/secret"), ("acme", "res://records/pub-1"),
                                 ("globex", "res://records/secret")]


def test_a_module_that_cannot_be_imported_fails_loudly(api, monkeypatch):
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_MODULE", "tests.flow.no_such_registry")
    with pytest.raises(ModuleNotFoundError):
        api._flow_resource_acl("acme")


def test_a_module_without_the_lookup_fails_loudly(api, monkeypatch):
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_MODULE", "tests.flow.test_label_lattice")
    with pytest.raises(AttributeError):
        api._flow_resource_acl("acme")


def test_one_dispatch_asks_the_registry_once_and_uses_that_answer_three_times():
    """The check, the approved recipients and the result label of one dispatch
    read one memoised lookup. Three separate lookups let a registry that
    changed after the check put a recipient in the approved set that the check
    never judged (review, 2026-11-10)."""
    import inspect

    import servers.execution_api as exec_api

    dispatch = inspect.getsource(exec_api._flow_at_dispatch)
    assert dispatch.count("_flow_resource_acl(tenant)") == 1
    assert dispatch.count("memoised_acl(_flow_resource_acl(tenant))") == 1
    assert dispatch.count("resource_acl=acl") == 3
    assert "if unresolved:" in dispatch
    source = inspect.getsource(exec_api)
    assert "FlowLabeler()" not in source
    # Assess is the fourth reader, with its own lookup; dispatch re-checks its digest.
    assert source.count("resource_acl=_flow_resource_acl(tenant)") == 1


def test_a_memoised_lookup_gives_the_first_answer_to_every_asker():
    from remora.flow.check import memoised_acl, recipients
    from remora.flow.spec import parse_flow

    answers = iter([["user://acme/alice"], ["user://acme/alice", "ext://evil.example"], []])
    calls = []

    def flapping(resource):
        calls.append(resource)
        return next(answers)

    acl = memoised_acl(flapping)
    write = parse_flow({"provider": "tcb", "arguments": {"path": {"kind": "resource"}},
                        "sources": {}, "sink": {"recipients": {"resource_of": "path"}}})
    first = recipients(write, {"path": "res://records/a"}, resource_acl=acl)
    again = recipients(write, {"path": "res://records/a"}, resource_acl=acl)
    assert first == again == (frozenset({"user://acme/alice"}), ())
    assert calls == ["res://records/a"]
    assert memoised_acl(None) is None


def test_a_memoised_lookup_replays_a_failure_and_keeps_public_and_generators_stable():
    from remora.flow.check import memoised_acl, resource_readers

    count = {"n": 0}

    def once_then_fine(resource):
        count["n"] += 1
        if count["n"] == 1:
            raise RuntimeError("registry down")
        return PUBLIC

    acl = memoised_acl(once_then_fine)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            acl("res://records/a")
    assert count["n"] == 1
    public = memoised_acl(lambda r: PUBLIC)
    assert public("res://records/a") is PUBLIC and public("res://records/a") is PUBLIC
    # A generator is not a list of principals; it stays refused on every ask.
    from remora.capabilities.resource import ResourceRefused

    gen = memoised_acl(lambda r: (p for p in ["user://acme/alice"]))
    for _ in range(2):
        with pytest.raises(ResourceRefused):
            resource_readers(gen, "res://records/a")


def test_the_shipped_file_registry_binds_by_name_and_is_validated_when_bound(api, monkeypatch,
                                                                             tmp_path):
    import json

    from remora.flow import acl_registry

    path = tmp_path / "acl.json"
    path.write_text(json.dumps({"schema": acl_registry.SCHEMA, "tenants": {"acme": [
        {"resource": "res://records/*", "readers": "PUBLIC"}]}}), encoding="utf-8")
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_MODULE", "remora.flow.acl_registry")
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_FILE", str(path))
    acl_registry.reset()
    assert api._flow_resource_acl("acme")("res://records/x") is PUBLIC
    assert api._flow_resource_acl("globex")("res://records/x") == []
    acl_registry.reset()


def test_a_registry_file_that_cannot_load_is_an_error_not_a_registry_of_refusals(
        api, monkeypatch, tmp_path):
    from remora.flow import acl_registry

    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_MODULE", "remora.flow.acl_registry")
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_FILE", str(tmp_path / "missing.json"))
    acl_registry.reset()
    with pytest.raises(acl_registry.AclRegistryError):
        api._flow_resource_acl("acme")
    # Nothing was bound: the next call fails the same way, and does not find a half-bound lookup.
    assert api._FLOW_RESOURCE_ACL is None
    with pytest.raises(acl_registry.AclRegistryError):
        api._flow_resource_acl("acme")
    acl_registry.reset()
