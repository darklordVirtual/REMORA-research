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


def test_the_registry_reaches_assess_dispatch_recipients_and_the_labeller():
    """Every flow call site on the route passes the lookup; one that did not
    would decide on an unresolved recipient or label a result with no reader."""
    import inspect

    import servers.execution_api as exec_api

    source = inspect.getsource(exec_api)
    assert source.count("resource_acl=_flow_resource_acl(tenant)") == 4
    assert "FlowLabeler()" not in source
