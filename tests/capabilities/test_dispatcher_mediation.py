# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The dispatcher creates each mediated execution's authority (NTA-2 phase 2).

A tool registered as mediated receives a ``CapabilityMediator`` built by the
dispatcher from the lease it verified: the capability set bound into the lease,
the tool's declared downstream ceiling, and the deployment's effect executors.
The tool never supplies any of it. Unmediated tools are called exactly as
before.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from remora.capabilities import CapabilityRefusal, StaticEpochSource
from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
    ToolExecutionStateUnknown,
)
from tests.capabilities.test_capability_mediation import CEILING, _parent


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "mediation-dispatch-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


ARGS = {"month": "2026-09"}


def _lease(capability_set=None):
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-42",
        tool_name="report.generate", arguments=ARGS, target_environment="prod",
        policy_bundle_hash="b1", issued_at=datetime.now(UTC).isoformat(),
        capability_set=capability_set)


def _dispatcher(tool, *, mediated=True, ceiling=CEILING, executors=None, epochs=None):
    d = GovernedToolDispatcher("b1")
    d.register("report.generate", tool, mediated=mediated)
    d.bind_downstream_ceilings(lambda name: ceiling if name == ceiling.tool else None)
    d.bind_effect_executors(executors if executors is not None else {
        "database.read": lambda resource, args: [("row", 1)],
        "filesystem.read": lambda resource, args: "<html/>",
        "network.http.post": lambda resource, args: "posted"})
    if epochs is not None:
        d.bind_capability_epochs(epochs)
    return d


def _run(d, capability_set):
    return d.dispatch(_lease(capability_set), "report.generate", ARGS, tenant_id="acme",
                      target_environment="prod", actor_identity="agent-42",
                      capability_set=capability_set)


def report(arguments, capabilities):
    rows = capabilities.invoke("database.read", "database://reporting-eu/monthly")
    capabilities.invoke("network.http.post", "https://billing.example/api/invoice")
    template = capabilities.invoke("filesystem.read", "workspace://templates/report.html")
    return {"rows": rows.result, "template": template.result}


def test_a_mediated_tool_gets_its_effects_through_the_dispatcher():
    parent = _parent()
    result = _run(_dispatcher(report), parent)
    assert result.executed
    assert result.result == {"rows": [("row", 1)], "template": "<html/>"}
    summary = result.nested_effects
    assert summary["mediated"] is True and summary["settled"] is True
    assert summary["by_state"] == {"EXECUTED": 2, "REFUSED": 1}
    graph = result.effect_graph
    assert [n.capability for n in graph.children] == [
        "database.read", "network.http.post", "filesystem.read"]
    assert graph.children[1].refusal == CapabilityRefusal.NOT_ALLOWED.value


def test_the_context_comes_from_the_lease_not_the_tool():
    seen = {}

    def tool(arguments, capabilities):
        seen["context"] = capabilities.context
        return "ok"

    parent = _parent()
    lease = _lease(parent)
    d = _dispatcher(tool)
    d.dispatch(lease, "report.generate", ARGS, tenant_id="acme", target_environment="prod",
               actor_identity="agent-42", capability_set=parent)
    ctx = seen["context"]
    assert (ctx.tenant_id, ctx.principal_id, ctx.tool_name) == ("acme", "agent-42",
                                                               "report.generate")
    assert ctx.capability_digest == parent.digest == lease.capability_digest
    assert ctx.parent_lease_digest == lease.digest()
    assert ctx.policy_bundle_hash == "b1"


def test_the_mediator_closes_when_the_tool_returns():
    kept = {}

    def tool(arguments, capabilities):
        kept["m"] = capabilities
        return "ok"

    _run(_dispatcher(tool), _parent())
    late = kept["m"].invoke("filesystem.read", "workspace://reports/a.pdf")
    assert late.refusal == CapabilityRefusal.CONTEXT_MISSING.value


def test_a_mediated_tool_without_a_bound_capability_set_is_refused_before_the_nonce():
    calls = []
    d = _dispatcher(lambda a, c: calls.append(a))
    lease = _lease(None)
    result = d.dispatch(lease, "report.generate", ARGS, tenant_id="acme",
                        target_environment="prod", actor_identity="agent-42")
    assert result.refusal_reason == "capability_set_required" and calls == []
    assert result.dispatch_began is False


def test_an_undeclared_tool_may_run_but_reaches_no_effect():
    def tool(arguments, capabilities):
        return capabilities.invoke("filesystem.read", "workspace://reports/a.pdf").refusal

    d = GovernedToolDispatcher("b1")
    d.register("report.generate", tool, mediated=True)
    d.bind_effect_executors({"filesystem.read": lambda r, a: "x"})
    result = _run(d, _parent())
    assert result.executed and result.result == CapabilityRefusal.NOT_ALLOWED.value


def test_a_revoked_caller_set_refuses_the_nested_effect_too():
    parent = _parent()

    def tool(arguments, capabilities):
        return capabilities.invoke("filesystem.read", "workspace://reports/a.pdf").refusal

    d = _dispatcher(tool, epochs=StaticEpochSource(
        revoked_sets=frozenset({parent.capability_set_id})))
    # The dispatch itself is refused for the revoked set before the tool runs.
    assert _run(d, parent).refusal_reason == CapabilityRefusal.REVOKED.value


def test_a_tool_that_raises_carries_its_nested_effects_out():
    def tool(arguments, capabilities):
        capabilities.invoke("database.read", "database://reporting-eu/monthly")
        raise RuntimeError("render failed")

    with pytest.raises(ToolExecutionStateUnknown) as exc:
        _run(_dispatcher(tool), _parent())
    assert exc.value.nested_effects["count"] == 1
    assert exc.value.nested_effects["by_state"] == {"EXECUTED": 1}


def test_an_unmediated_tool_is_called_with_its_arguments_only():
    received = []
    d = GovernedToolDispatcher("b1")
    d.register("report.generate", lambda arguments: received.append(arguments) or "ok")
    result = _run(d, _parent())
    assert received == [ARGS] and result.executed
    assert result.nested_effects == {"mediated": False, "count": 0, "settled": True}
    assert result.effect_graph is None


def test_the_lease_digest_is_stable_and_binding():
    lease = _lease(_parent())
    assert lease.digest() == lease.digest() and len(lease.digest()) == 64
    assert _lease(_parent()).digest() != lease.digest()


def test_an_unreadable_ceiling_refuses_before_the_nonce():
    calls = []

    def broken(name):
        raise OSError("bundle unreadable")

    d = _dispatcher(lambda a, c: calls.append(a))
    d.bind_downstream_ceilings(broken)
    result = _run(d, _parent())
    assert result.refusal_reason == "downstream_ceiling_unavailable" and calls == []
    assert result.dispatch_began is False


def test_a_parent_at_the_depth_cap_derives_no_effect_authority():
    from remora.capabilities import delegate
    from remora.capabilities.delegation import MAX_DELEGATION_DEPTH

    chain = _parent()
    now = datetime.now(UTC)
    for n in range(MAX_DELEGATION_DEPTH):
        chain = delegate(chain, delegatee="agent-42", tools=["report.generate"],
                         purpose="relay", now=now, transitive=True)
    calls = []
    result = _run(_dispatcher(lambda a, c: calls.append(a)), chain)
    assert result.refusal_reason == "capability_delegation_denied" and calls == []


# Phase 3: the three-domain split and the strict declaration rule.

def _three_domain(tool):
    from remora.enforcement.effect_client import RemoteEffectClient
    from remora.enforcement.effect_domain import EffectDomain
    from remora.enforcement.nonce_store import InMemoryNonceStore

    store = InMemoryNonceStore()
    effect_calls: list = []
    domain = EffectDomain(
        ceilings=lambda name: CEILING if name == CEILING.tool else None,
        executors={"database.read": lambda r, a: effect_calls.append(r) or [7]},
        execution_started=lambda lease: store.consumed(lease.nonce, tenant_id=lease.tenant_id))
    worker = GovernedToolDispatcher("b1", nonce_store=store)
    worker.register("report.generate", tool, mediated=True)
    worker.bind_downstream_ceilings(lambda name: CEILING if name == CEILING.tool else None)
    worker.bind_effect_domain(RemoteEffectClient(post=lambda path, body: (
        domain.serve(body) if path.endswith("/effects") else domain.close(body))))
    return worker, domain, effect_calls


def test_in_three_domains_the_effect_runs_in_the_effect_domain_only():
    def tool(arguments, capabilities):
        return capabilities.invoke("database.read", "database://reporting-eu/monthly").result

    worker, _, effect_calls = _three_domain(tool)
    result = _run(worker, _parent())
    assert result.executed and result.result == [7]
    assert effect_calls == ["database://reporting-eu/monthly"]
    assert result.nested_effects["by_state"] == {"EXECUTED": 1}


def test_the_effect_domain_closes_when_the_tool_returns():
    kept = {}

    def tool(arguments, capabilities):
        kept["request"] = capabilities
        return "ok"

    parent = _parent()
    lease = _lease(parent)
    worker, domain, _ = _three_domain(tool)
    worker.dispatch(lease, "report.generate", ARGS, tenant_id="acme",
                    target_environment="prod", actor_identity="agent-42", capability_set=parent)
    answer = domain.serve({"lease": lease.to_dict(), "capability_set": parent.to_dict(),
                           "capability": "database.read",
                           "resource": "database://reporting-eu/monthly", "arguments": {}})
    assert answer["refusal"] == CapabilityRefusal.CONTEXT_MISSING.value


def test_a_domain_refusal_is_recorded_as_a_refusal():
    def tool(arguments, capabilities):
        return capabilities.invoke("database.read", "database://billing-us/x").refusal

    worker, _, effect_calls = _three_domain(tool)
    result = _run(worker, _parent())
    assert result.result == CapabilityRefusal.RESOURCE_NOT_AUTHORIZED.value
    assert effect_calls == [] and result.nested_effects["by_state"] == {"REFUSED": 1}


def test_a_strict_dispatcher_refuses_a_mediated_tool_without_a_declaration():
    calls = []
    d = GovernedToolDispatcher("b1", require_downstream_declaration=True)
    d.register("report.generate", lambda a, c: calls.append(a), mediated=True)
    result = _run(d, _parent())
    assert result.refusal_reason == "downstream_declaration_required" and calls == []


def test_strict_profiles_require_the_declaration_by_default(monkeypatch):
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review")
    assert GovernedToolDispatcher("b1")._require_declaration is True
    monkeypatch.delenv("REMORA_RUNTIME_PROFILE")
    assert GovernedToolDispatcher("b1")._require_declaration is False
