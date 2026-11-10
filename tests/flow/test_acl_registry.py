# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The file-backed resource ACL registry (remora/flow/acl_registry.py)."""
from __future__ import annotations

import json

import pytest

from remora.flow import acl_registry
from remora.flow.acl_registry import SCHEMA, AclRegistryError, StaticResourceAcl
from remora.flow.check import flow_check, recipients, resource_readers
from remora.flow.label import BOTTOM, PUBLIC, Integrity, Label
from remora.flow.spec import parse_flow

ALICE, BOB = "user://acme/alice", "email://corp.example/bob"
DOC = {"schema": SCHEMA, "tenants": {"acme": [
    {"resource": "res://records/*", "readers": [ALICE, BOB]},
    {"resource": "res://records/public/*", "readers": "PUBLIC"},
    {"resource": "res://records/public/draft", "readers": [ALICE]},
    {"resource": "res://records/cust-secret", "readers": [ALICE]},
]}}


def _acl(doc=None):
    return StaticResourceAcl.from_document(doc if doc is not None else DOC)


@pytest.mark.parametrize("resource, expected", [
    ("res://records/cust-secret", [ALICE]),                 # exact
    ("res://records/public/price-list", PUBLIC),            # the longer subtree
    ("res://records/public/draft", [ALICE]),                # exact beats its subtree
    ("res://records/other", [ALICE, BOB]),                  # the shorter subtree
    ("res://records/public", [ALICE, BOB]),                 # a subtree does not hold its own root
    ("res://files/q3", []),                                 # no entry
    ("RES://Records/cust-secret/", [ALICE]),                # canonicalised before matching
    ("not a resource", []),
    ("res://records/../records/cust-secret", []),
])
def test_the_most_specific_entry_decides(resource, expected):
    answer = _acl().lookup("acme", resource)
    assert answer is PUBLIC if expected is PUBLIC else answer == expected


def test_a_prefix_that_is_not_a_path_boundary_does_not_match():
    acl = _acl({"schema": SCHEMA, "tenants": {"acme": [
        {"resource": "res://records/public/*", "readers": "PUBLIC"}]}})
    assert acl.lookup("acme", "res://records/public-but-not/x") == []
    assert acl.lookup("acme", "res://records/publicx") == []


def test_another_tenant_sees_nothing():
    assert _acl().lookup("globex", "res://records/public/price-list") == []
    assert _acl().entries("globex") == 0 and _acl().entries("acme") == 4


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema="v0"), "schema must be"),
    (lambda d: d.update(extra=1), "exactly schema and tenants"),
    (lambda d: d.update(tenants=[]), "tenants maps"),
    (lambda d: d["tenants"].update({"": []}), "non-empty id"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/y"}), "exactly resource and readers"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/y", "readers": []}), "non-empty list"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/y", "readers": "public"}),
     "non-empty list"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/y", "readers": [ALICE, ALICE]}),
     "twice"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/y", "readers": ["user://acme/*"]}),
     "not one principal"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/y", "readers": ["USER://Acme/a"]}),
     "canonical form"),
    (lambda d: d["tenants"]["acme"].append({"resource": "RES://X/y", "readers": [ALICE]}),
     "canonical form"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://x/*/y", "readers": [ALICE]}),
     "resource"),
    (lambda d: d["tenants"]["acme"].append({"resource": "res://records/*", "readers": [ALICE]}),
     "listed twice"),
    (lambda d: d["tenants"]["acme"].append({"resource": 7, "readers": [ALICE]}), "resource"),
])
def test_a_malformed_registry_is_refused(mutate, message):
    doc = json.loads(json.dumps(DOC))
    mutate(doc)
    with pytest.raises(AclRegistryError, match=message):
        StaticResourceAcl.from_document(doc)


def test_the_file_is_strict_json_with_a_digest(tmp_path):
    path = tmp_path / "acl.json"
    path.write_text(json.dumps(DOC), encoding="utf-8")
    acl = StaticResourceAcl.from_file(path)
    assert acl.digest.startswith("sha256:") and len(acl.digest) == 71
    assert acl.lookup("acme", "res://records/cust-secret") == [ALICE]
    path.write_text('{"schema": "%s", "tenants": {}, "tenants": {}}' % SCHEMA, encoding="utf-8")
    with pytest.raises(AclRegistryError, match="duplicate member"):
        StaticResourceAcl.from_file(path)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(AclRegistryError, match="strict JSON"):
        StaticResourceAcl.from_file(path)
    with pytest.raises(AclRegistryError, match="cannot read"):
        StaticResourceAcl.from_file(tmp_path / "missing.json")


@pytest.fixture()
def module(monkeypatch, tmp_path):
    path = tmp_path / "acl.json"
    path.write_text(json.dumps(DOC), encoding="utf-8")
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_FILE", str(path))
    acl_registry.reset()
    yield path
    acl_registry.reset()


def test_the_module_interface_loads_once_and_keeps_the_digest(module):
    digest = acl_registry.validate()
    assert acl_registry.resource_acl("acme", "res://records/cust-secret") == [ALICE]
    module.write_text(json.dumps({"schema": SCHEMA, "tenants": {}}), encoding="utf-8")
    # A changed file takes effect at restart, not mid-flight.
    assert acl_registry.resource_acl("acme", "res://records/cust-secret") == [ALICE]
    assert acl_registry.registry_digest() == digest
    acl_registry.reset()
    assert acl_registry.resource_acl("acme", "res://records/cust-secret") == []


def test_an_unset_or_bad_file_is_loud(monkeypatch, tmp_path):
    acl_registry.reset()
    monkeypatch.delenv("REMORA_FLOW_RESOURCE_ACL_FILE", raising=False)
    with pytest.raises(AclRegistryError, match="is not set"):
        acl_registry.validate()
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("REMORA_FLOW_RESOURCE_ACL_FILE", str(bad))
    with pytest.raises(AclRegistryError):
        acl_registry.validate()
    acl_registry.reset()


# ── the registry under the check it feeds ────────────────────────────────

_WRITE = parse_flow({"provider": "tcb", "arguments": {"path": {"kind": "resource"},
                                                      "body": {"kind": "text"}},
                     "sources": {}, "sink": {"recipients": {"resource_of": "path"}}})
SECRET = Label({ALICE, "ext://api.provider.example"}, Integrity.TRUSTED)


def _lookup(resource):
    return _acl().lookup("acme", resource)


def test_secret_data_may_go_to_its_own_record_and_nowhere_wider():
    def check(path, label):
        return flow_check(_WRITE, context_label=label, value_labels={},
                          resolved_args={"path": path, "body": "x"}, epoch=0,
                          resource_acl=_lookup)

    assert check("res://records/cust-secret", SECRET).clean          # Alice only
    assert check("res://records/other", SECRET).conf_viol == {BOB}   # Bob may not read it
    assert check("res://records/public/price-list", SECRET).conf_viol  # nor may everyone
    assert check("res://records/public/price-list", BOTTOM).clean
    assert check("res://files/unknown", BOTTOM).conf_viol == {"unresolved:path"}
    assert check("res://files/unknown", SECRET).conf_viol == {"unresolved:path"}


def test_resource_readers_refuses_what_the_registry_does_not_know():
    from remora.capabilities.resource import ResourceRefused

    assert resource_readers(_lookup, "res://records/cust-secret") == frozenset({ALICE})
    assert resource_readers(_lookup, "res://records/public/x") is PUBLIC
    with pytest.raises(ResourceRefused):
        resource_readers(_lookup, "res://files/unknown")
    assert recipients(_WRITE, {"path": "res://files/unknown"}, resource_acl=_lookup) == (
        frozenset(), ("path",))
