# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Flow control in the execution domain: /v1/execution/dispatch-leased.

With REMORA_FLOW_CONTROL=1 the executing process reads the call's flow
context from its own store, as the lease's actor, refuses unless the verdict
is clean, and commits the result's labels before returning it. A domain that
does not share the authority's flow store sees an unknown context and
refuses. The lease's nonce is untouched by a flow refusal.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from remora.execution.dispatch import issue_execution_lease  # noqa: E402
from remora.flow.label import Integrity, Label  # noqa: E402
from remora.flow.spec import parse_flow  # noqa: E402
from remora.governance.task_identity import TaskIdentity  # noqa: E402
from tests.test_dispatch_leased_endpoint import CALL, SEMANTIC, _post  # noqa: E402
from tests.test_dispatch_leased_endpoint import executor as _executor  # noqa: E402,F401

MODEL = "ext://api.provider.example"
USER = "user://acme/alice"
WO_FLOW = parse_flow({
    "provider": "tcb",
    "arguments": {"work_order_id": {"kind": "text"}, "status": {"kind": "text"}},
    "sources": {"default_integrity": "TRUSTED"},
    "sink": {"recipients": {"static": ["ext://work-orders.example"]},
             "payload_args": ["status"]}})


@pytest.fixture()
def executor(_executor, monkeypatch, tmp_path):  # noqa: F811
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_FLOW_CONTROL", "1")
    for var in ("REMORA_PG_DSN", "REMORA_CHAIN_DB", "REMORA_STATE_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    policy = tmp_path / "processing.json"
    policy.write_text(json.dumps({"acme": {"default": [MODEL]}}), encoding="utf-8")
    monkeypatch.setenv("REMORA_FLOW_PROCESSING_POLICY", str(policy))
    monkeypatch.setattr(exec_mod, "_FLOW_CONTEXTS", None)
    monkeypatch.setattr(exec_mod, "_FLOW_HANDLES", None)
    monkeypatch.setattr(exec_mod, "_flow_spec",
                        lambda tool: WO_FLOW if tool == CALL["tool_name"] else None)
    return _executor


def _context(executor) -> str:
    r = executor.client.post("/v1/contexts",
                             json={"user_principal": USER, "model_principal": MODEL})
    assert r.status_code == 200, r.text
    return r.json()["context_id"]


def _binding(call) -> tuple[int, str, str]:
    """What the authority signs into the lease (IFC-06): the flow decision it
    judged at mint, and the hash of the call with every handle resolved. When
    no decision can be judged (an unknown context or handle), a placeholder
    binding, so that the executor's own check is what refuses."""
    import servers.execution_api as exec_mod
    from remora.policy.observation import PolicyObservation, canonical_tool_call_hash

    def digest(arguments):
        return canonical_tool_call_hash(
            name=call["tool_name"], arguments=arguments, tenant="acme",
            target=call.get("target_environment") or "")

    tool_call = exec_mod.ToolCallRequest(**call)
    token = exec_mod._FLOW_PRINCIPAL.set("employee-1")
    try:
        obs = exec_mod._with_flow(PolicyObservation(question="mint"), tool_call, "acme")
        if obs.flow_status != "evaluated":
            return 0, "0" * 64, digest(call["arguments"])
        expected = (int(obs.flow_epoch), str(obs.flow_digest))
        _refusal, _commit, resolved, release, _approved = exec_mod._flow_at_dispatch(
            "acme", tool_call, expected, "p-mint")
        if release is not None:
            release()  # the mint-time check must not hold the context
    finally:
        exec_mod._FLOW_PRINCIPAL.reset(token)
    return expected[0], expected[1], digest(
        resolved if resolved is not None else call["arguments"])


def _lease(executor, call, *, bound: bool = True):
    return issue_execution_lease(
        tenant="acme", principal="employee-1", tool_call=SimpleNamespace(**call),
        semantic=SEMANTIC, now=datetime.now(UTC), policy_bundle_hash=executor.bundle,
        task_identity=TaskIdentity.from_fields(
            {"context_id": call["context_id"], "task_id": "task-1"}),
        flow_binding=_binding(call) if bound else None)


def _call(context_id):
    return dict(CALL, context_id=context_id, task_id="task-1")


def test_a_clean_flow_executes_and_commits_labels(executor):
    call = _call(_context(executor))
    body = _post(executor, _lease(executor, call), call=call).json()
    assert body["tool_execution"]["executed"] is True, body
    assert "flow_commit" in body["tool_execution"]


def test_an_unknown_context_refuses_before_the_tool_runs(executor):
    call = _call("ctx_" + "a" * 26)
    body = _post(executor, _lease(executor, call), call=call).json()
    assert body["tool_execution"]["refusal_reason"] == "flow_context_unknown"
    assert executor.registry.CALLS == []


def test_a_flow_violation_refuses_and_leaves_the_lease_unspent(executor):
    import servers.execution_api as exec_mod

    context_id = _context(executor)
    call = _call(context_id)
    lease = _lease(executor, call)
    exec_mod._flow_contexts().raise_label("acme", "employee-1", context_id,
                                          Label({USER, MODEL}, Integrity.TRUSTED))
    body = _post(executor, lease, call=call).json()
    assert body["tool_execution"]["refusal_reason"] == "flow_confidentiality_violation"
    assert executor.registry.CALLS == []


# ── IFC-06: the tool receives the values the flow check judged ─────────────
#
# An external review of 265abfbe (2026-10-21) found that the dispatch-time
# flow check resolved handles and then discarded the result, so the tool
# received the opaque handle token. The lease still binds the handle form
# the approver saw; the tool now gets the resolved values.

def _handle(executor, context_id: str, value, *, type_tag: str = "text") -> str:
    import time

    import servers.execution_api as exec_mod
    from remora.flow.handles import HandleRecord, handle_token, new_handle_id

    state = exec_mod._flow_contexts().load("acme", "employee-1", context_id)
    hid = new_handle_id()
    exec_mod._flow_handles().put_all([HandleRecord(
        handle_id=hid, tenant_id="acme", context_id=context_id, value=value,
        label=state.label, type_tag=type_tag, created_by_proposal="p-src",
        expires_at=time.time() + 600)])
    return handle_token(hid)


def _call_with(context_id: str, status) -> dict:
    return dict(_call(context_id),
                arguments={"work_order_id": "WO-1", "status": status})


@pytest.mark.parametrize("form", ["whole", "reference", "embedded"])
def test_the_tool_receives_the_resolved_handle_value(executor, form):
    context_id = _context(executor)
    token = _handle(executor, context_id, "closed")
    status = {"whole": token,
              "reference": {"$handle": token, "$type": "text"},
              "embedded": f"now {token}"}[form]
    call = _call_with(context_id, status)
    body = _post(executor, _lease(executor, call), call=call).json()
    assert body["tool_execution"]["executed"] is True, body
    assert executor.registry.CALLS == [
        {"work_order_id": "WO-1",
         "status": "now closed" if form == "embedded" else "closed"}]


def test_an_unknown_handle_refuses_before_the_tool_runs(executor):
    from remora.flow.handles import handle_token, new_handle_id

    context_id = _context(executor)
    call = _call_with(context_id, handle_token(new_handle_id()))
    body = _post(executor, _lease(executor, call), call=call).json()
    assert body["tool_execution"]["refusal_reason"] == "flow_handle_invalid"
    assert executor.registry.CALLS == []


def test_the_lease_still_binds_the_handle_form(executor):
    """A lease for the resolved value is not a lease for the handle."""
    context_id = _context(executor)
    token = _handle(executor, context_id, "closed")
    lease = _lease(executor, _call_with(context_id, "closed"))
    body = _post(executor, lease, call=_call_with(context_id, token)).json()
    assert body["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


# ── IFC-06: the lease carries the flow decision (SDD P0 item 6) ────────────
#
# Until this slice the executor computed its expected epoch and digest a
# moment before comparing the context against them, so a label raised or a
# handle changed after the authority's grant was invisible to it. The lease
# now signs the epoch, the digest and the hash of the resolved call.

def _handle_record(executor, context_id: str, value) -> tuple[str, str]:
    import time

    import servers.execution_api as exec_mod
    from remora.flow.handles import HandleRecord, handle_token, new_handle_id

    state = exec_mod._flow_contexts().load("acme", "employee-1", context_id)
    hid = new_handle_id()
    exec_mod._flow_handles().put_all([HandleRecord(
        handle_id=hid, tenant_id="acme", context_id=context_id, value=value,
        label=state.label, type_tag="text", created_by_proposal="p-src",
        expires_at=time.time() + 600)])
    return hid, handle_token(hid)


def test_a_lease_without_a_flow_decision_is_refused_while_flow_is_on(executor):
    call = _call(_context(executor))
    body = _post(executor, _lease(executor, call, bound=False), call=call).json()
    assert body["tool_execution"]["refusal_reason"] == "flow_lease_unbound"
    assert executor.registry.CALLS == []


def test_a_handle_whose_value_changed_after_the_grant_is_refused(executor):
    """The authority judged and signed the call with the handle resolved to
    "closed". The store then resolves it to another value; the tool must not
    receive it. Before this slice the tool ran with the new value."""
    import time

    import servers.execution_api as exec_mod
    from remora.flow.handles import HandleRecord

    context_id = _context(executor)
    hid, token = _handle_record(executor, context_id, "closed")
    call = _call_with(context_id, token)
    lease = _lease(executor, call)
    state = exec_mod._flow_contexts().load("acme", "employee-1", context_id)
    # The store refuses a second record under one handle id through its API,
    # so the changed value is written to the backend directly: what a shared
    # store another process writes to, or a replaced record, would look like.
    exec_mod._flow_handles()._backend._records[("acme", hid)] = HandleRecord(
        handle_id=hid, tenant_id="acme", context_id=context_id, value="open",
        label=state.label, type_tag="text", created_by_proposal="p-src",
        expires_at=time.time() + 600)
    body = _post(executor, lease, call=call).json()
    assert body["tool_execution"]["refusal_reason"] == "resolved_call_mismatch"
    assert executor.registry.CALLS == []


def test_a_label_raised_after_the_grant_refuses_before_the_tool_runs(executor):
    """The context moved between the authority's decision and the dispatch;
    the executor compares against the epoch and digest the lease signed."""
    import servers.execution_api as exec_mod

    context_id = _context(executor)
    call = _call(context_id)
    lease = _lease(executor, call)
    # A raise the flow still passes: the recipient and the model stay readers,
    # so the executor's own verdict is clean and only the lease-bound epoch
    # and digest can refuse. Before this slice the call executed.
    exec_mod._flow_contexts().raise_label(
        "acme", "employee-1", context_id,
        Label({USER, MODEL, "ext://work-orders.example"}, Integrity.TRUSTED))
    body = _post(executor, lease, call=call).json()
    assert body["tool_execution"]["refusal_reason"] == "flow_epoch_changed", body
    assert executor.registry.CALLS == []


def test_two_dispatches_in_one_context_run_exactly_one_tool(executor):
    """IFC-06's race, closed by the dispatch fence. Two leases judged at the
    same epoch: the first passes the check, takes the fence and is held
    inside the tool; the second, arriving meanwhile, is refused as
    flow_dispatch_contended before its tool runs and before anything is
    spent. Exactly one tool call happens. After the first commits (which
    raises the label here), a lease at the old epoch refuses as
    flow_epoch_changed."""
    import threading

    import servers.execution_api as exec_mod

    raising = parse_flow({
        "provider": "tcb",
        "arguments": {"work_order_id": {"kind": "text"}, "status": {"kind": "text"}},
        "sources": {"default_integrity": "TRUSTED", "fields": [
            {"path": "$", "return_mode": "BY_VALUE", "type": "object",
             "readers": {"static": [USER, MODEL, "ext://work-orders.example"]}},
            {"path": "$.status", "return_mode": "BY_VALUE", "type": "string",
             "readers": {"static": [USER, MODEL, "ext://work-orders.example"]}},
            {"path": "$.work_order", "return_mode": "BY_VALUE", "type": "string",
             "readers": {"static": [USER, MODEL, "ext://work-orders.example"]}}]},
        "sink": {"recipients": {"static": ["ext://work-orders.example"]},
                 "payload_args": ["status"]}})
    executor.monkeypatch.setattr(exec_mod, "_flow_spec",
                                 lambda tool: raising if tool == CALL["tool_name"] else None)
    context_id = _context(executor)
    calls = [dict(_call(context_id), arguments={"work_order_id": f"WO-{i}", "status": "closed"})
             for i in (1, 2)]
    leases = [_lease(executor, call) for call in calls]
    assert leases[0].flow_epoch == leases[1].flow_epoch
    inside, proceed = threading.Event(), threading.Event()

    def hold(_arguments):
        inside.set()
        assert proceed.wait(timeout=15)

    executor.registry.BEFORE_CALL.append(hold)
    first: dict = {}
    worker = threading.Thread(
        target=lambda: first.update(_post(executor, leases[0], call=calls[0]).json()))
    try:
        worker.start()
        assert inside.wait(timeout=15), "the first dispatch never reached the tool"
        second = _post(executor, leases[1], call=calls[1]).json()["tool_execution"]
        assert second["executed"] is False
        assert second["refusal_reason"] == "flow_dispatch_contended", second
    finally:
        proceed.set()
        worker.join(timeout=15)
        executor.registry.BEFORE_CALL.clear()
    assert first["tool_execution"]["executed"] is True and "result" in first["tool_execution"]
    assert len(executor.registry.CALLS) == 1   # the loser never reached the tool
    stale = _post(executor, leases[1], call=calls[1]).json()["tool_execution"]
    assert stale["refusal_reason"] == "flow_epoch_changed", stale
    assert len(executor.registry.CALLS) == 1


def test_a_refused_dispatch_does_not_hold_the_context(executor):
    """A fence taken by a call that is refused later (a replayed lease whose
    nonce is spent) is released on the way out, so the next call in the
    context runs instead of waiting for the fence to expire."""
    import servers.execution_api as exec_mod

    context_id = _context(executor)
    call = _call(context_id)
    lease, later = _lease(executor, call), _lease(executor, call)   # minted while the key is held
    assert _post(executor, lease, call=call).json()["tool_execution"]["executed"] is True
    replay = _post(executor, lease, call=call).json()["tool_execution"]
    assert replay["refusal_reason"] == "nonce_already_consumed"
    state = exec_mod._flow_contexts().load("acme", "employee-1", context_id)
    assert state.open_dispatches == ()
    again = _post(executor, later, call=call).json()["tool_execution"]
    assert again["executed"] is True


def test_an_expired_fence_does_not_hold_the_context(executor):
    """A process that died mid-call leaves its fence; once the fence's expiry
    (the lease TTL) has passed, the next call runs."""
    import servers.execution_api as exec_mod

    context_id = _context(executor)
    call = _call(context_id)
    contexts = exec_mod._flow_contexts()
    held = contexts.begin_dispatch(
        "acme", "employee-1", context_id,
        expected_seq=contexts.load("acme", "employee-1", context_id).seq,
        proposal_id="p-dead", expires_at=1.0, now=0.0)
    assert held is not None
    assert len(contexts.load("acme", "employee-1", context_id).open_dispatches) == 1
    body = _post(executor, _lease(executor, call), call=call).json()
    assert body["tool_execution"]["executed"] is True, body


def test_a_live_fence_of_another_proposal_refuses_before_the_tool(executor):
    import time

    import servers.execution_api as exec_mod

    context_id = _context(executor)
    call = _call(context_id)
    lease = _lease(executor, call)
    contexts = exec_mod._flow_contexts()
    now = time.time()
    held = contexts.begin_dispatch(
        "acme", "employee-1", context_id,
        expected_seq=contexts.load("acme", "employee-1", context_id).seq,
        proposal_id="p-other", expires_at=now + 60, now=now)
    assert held is not None
    body = _post(executor, lease, call=call).json()["tool_execution"]
    assert (body["executed"], body["refusal_reason"]) == (False, "flow_dispatch_contended")
    assert executor.registry.CALLS == []
    contexts.end_dispatch("acme", "employee-1", context_id, held)
    assert _post(executor, lease, call=call).json()["tool_execution"]["executed"] is True


# ── IFC-12: the recipients the flow check approved bind the mediated effects ─

NOTIFY_FLOW = parse_flow({
    "provider": "tcb",
    "arguments": {"url": {"kind": "url"}, "message": {"kind": "text"}},
    "sources": {"default_integrity": "TRUSTED", "fields": [
        {"path": "$", "return_mode": "BY_VALUE", "type": "object",
         "readers": {"static": [USER, MODEL]}},
        {"path": "$.sent", "return_mode": "BY_VALUE", "type": "string",
         "readers": {"static": [USER, MODEL]}},
        {"path": "$.leak", "return_mode": "BY_VALUE", "type": "string",
         "readers": {"static": [USER, MODEL]}}]},
    "sink": {"recipients": {"url_host_of": "url"}, "payload_args": ["message"]}})
NOTIFY = {"tool_name": "notify_partner",
          "arguments": {"url": "https://partner.example/hook", "message": "closed"},
          "target_environment": "staging"}


def test_a_mediated_tool_may_send_the_payload_only_to_the_recipients_the_flow_check_approved(
        executor):
    """§3.5.1 of the flow-control design: the tool was approved to post to
    partner.example and, misbehaving, also posts to a collector nobody
    approved. The mediator refuses the second effect as
    capability_recipient_not_approved before any executor runs; the first
    goes through; the lease carries the digest of the approved set."""
    from remora.capabilities import CapabilityPolicy, CapabilityResolver
    from remora.enforcement.effect_capability import DownstreamCeiling
    from remora.enforcement.flow_recipients import recipients_digest
    import servers.execution_api as exec_mod

    exec_mod_spec = exec_mod._flow_spec
    executor.monkeypatch.setattr(
        exec_mod, "_flow_spec",
        lambda tool: NOTIFY_FLOW if tool == "notify_partner" else exec_mod_spec(tool))
    ceiling = DownstreamCeiling.from_dict("notify_partner", [
        {"capability": "network.http.post",
         "resources": ["https://partner.example/*", "https://exfil.example/*"],
         "purpose": "notify"}])
    executor.monkeypatch.setattr(
        exec_mod, "_downstream_ceiling", lambda tool: ceiling if tool == "notify_partner" else None)
    policy = CapabilityPolicy.from_dict({
        "policy_version": "p", "registry_version": "r",
        "registry": {"notify_partner": ["staging"]},
        "principals": {"employee-1": ["notify_partner"]}, "tasks": {"notify": ["notify_partner"]},
        "tenants": {"acme": ["notify_partner"]}, "environments": {"staging": ["notify_partner"]}})
    capability_set = CapabilityResolver(policy).resolve(
        principal_id="employee-1", tenant_id="acme", environment="staging", task_type="notify",
        now=datetime.now(UTC))
    call = dict(NOTIFY, context_id=_context(executor), task_id="task-1")
    lease = issue_execution_lease(
        tenant="acme", principal="employee-1", tool_call=SimpleNamespace(**call),
        semantic=SEMANTIC, now=datetime.now(UTC), policy_bundle_hash=executor.bundle,
        task_identity=TaskIdentity.from_fields(
            {"context_id": call["context_id"], "task_id": "task-1"}),
        capability_set=capability_set, flow_binding=_binding(call),
        flow_recipients=frozenset({"ext://partner.example"}))
    assert lease.flow_recipients_digest == recipients_digest({"ext://partner.example"})
    executor.registry.EFFECTS.clear()
    body = _post(executor, lease, call=call, capability_set=capability_set.to_dict()).json()
    execution = body["tool_execution"]
    assert execution["executed"] is True, body
    assert execution["result"]["sent"] == "EXECUTED"
    assert execution["result"]["leak"] == "capability_recipient_not_approved"
    assert executor.registry.EFFECTS == [("network.http.post", "https://partner.example/hook")]
    assert execution["nested_effects"]["by_state"] == {"EXECUTED": 1, "REFUSED": 1}


def test_a_raise_between_the_check_and_the_fence_refuses_before_the_tool(executor):
    """The fence is taken at the sequence the dispatch check read, not at a
    sequence of its own. A raise that commits after the check passed and
    before the fence is appended moves the stream; the fence must then be
    lost and the call refused before its tool runs. Before the fence took the
    check's sequence, begin_dispatch loaded the context again, appended after
    the raise, and the tool ran on a verdict computed from the old label."""
    import servers.execution_api as exec_mod
    import remora.flow.labeler as labeler_mod

    context_id = _context(executor)
    call = _call(context_id)
    lease = _lease(executor, call)
    original = labeler_mod.verify_flow_at_dispatch
    raised: list[int] = []

    def check_then_raise(**kwargs):
        verdict = original(**kwargs)
        if not raised:
            # A raise the flow still passes, so only the fence can refuse.
            state = exec_mod._flow_contexts().raise_label(
                "acme", "employee-1", context_id,
                Label({USER, MODEL, "ext://work-orders.example"}, Integrity.TRUSTED))
            raised.append(state.seq)
        return verdict

    executor.monkeypatch.setattr(labeler_mod, "verify_flow_at_dispatch", check_then_raise)
    body = _post(executor, lease, call=call).json()["tool_execution"]
    assert raised, "the check never ran"
    assert (body["executed"], body.get("refusal_reason")) == (False, "flow_dispatch_contended"), body
    assert executor.registry.CALLS == []
    state = exec_mod._flow_contexts().load("acme", "employee-1", context_id)
    assert state.open_dispatches == ()


def _hold_first_call(executor):
    """Hold the first tool call inside the tool until ``proceed`` is set;
    later calls run straight through."""
    import threading

    inside, proceed = threading.Event(), threading.Event()
    seen: list[int] = []

    def hold(_arguments):
        seen.append(1)
        if len(seen) == 1:
            inside.set()
            assert proceed.wait(timeout=30)

    executor.registry.BEFORE_CALL.append(hold)
    return inside, proceed


def test_a_tool_running_past_the_fence_ttl_still_holds_the_context(executor):
    """The fence's expiry bounds a process that died mid-call, not a call
    that is still running. With a fence TTL of one second the first tool is
    held for well past it; a second proposal in the same context must still
    be refused before its tool runs, and the first call's result is released.
    Before the fence was renewed while the tool ran, the hold expired, the
    second proposal began, and both tools ran at once."""
    import threading
    import time

    import remora.enforcement.lease as lease_mod

    context_id = _context(executor)
    calls = [dict(_call(context_id), arguments={"work_order_id": f"WO-{i}", "status": "closed"})
             for i in (1, 2)]
    leases = [_lease(executor, call) for call in calls]
    ttl = 1.0
    executor.monkeypatch.setattr(lease_mod, "DEFAULT_LEASE_TTL_SECONDS", ttl)
    inside, proceed = _hold_first_call(executor)
    first: dict = {}
    worker = threading.Thread(
        target=lambda: first.update(_post(executor, leases[0], call=calls[0]).json()))
    try:
        worker.start()
        assert inside.wait(timeout=30), "the first dispatch never reached the tool"
        time.sleep(3 * ttl)
        second = _post(executor, leases[1], call=calls[1]).json()["tool_execution"]
        assert (second["executed"], second.get("refusal_reason")) == (
            False, "flow_dispatch_contended"), second
        assert len(executor.registry.CALLS) == 0   # the first is still inside its tool
    finally:
        proceed.set()
        worker.join(timeout=30)
        executor.registry.BEFORE_CALL.clear()
    assert first["tool_execution"]["executed"] is True
    assert "result" in first["tool_execution"], first
    assert len(executor.registry.CALLS) == 1


def test_a_commit_whose_fence_expired_withholds_the_result(executor):
    """If the hold could not be kept alive (the renewal failed, the process
    was paused past the TTL), another proposal may have run in the context
    meanwhile, so the commit refuses and the result is withheld."""
    import threading
    import time

    import remora.enforcement.lease as lease_mod
    from remora.flow.context import FlowContextStore

    context_id = _context(executor)
    call = _call(context_id)
    lease = _lease(executor, call)
    ttl = 1.0
    executor.monkeypatch.setattr(lease_mod, "DEFAULT_LEASE_TTL_SECONDS", ttl)
    executor.monkeypatch.setattr(FlowContextStore, "renew_dispatch",
                                 lambda self, *a, **k: False, raising=False)
    inside, proceed = _hold_first_call(executor)
    first: dict = {}
    worker = threading.Thread(target=lambda: first.update(_post(executor, lease, call=call).json()))
    try:
        worker.start()
        assert inside.wait(timeout=30), "the dispatch never reached the tool"
        time.sleep(2 * ttl)
    finally:
        proceed.set()
        worker.join(timeout=30)
        executor.registry.BEFORE_CALL.clear()
    body = first["tool_execution"]
    assert body["executed"] is True and "result" not in body, body
    assert body.get("result_withheld") == "flow_dispatch_fence_expired", body


def test_a_commit_that_outlasts_the_fence_ttl_still_holds_the_context(executor):
    """The owner's reproduction (REMORA-research#1085): the tool returns, then
    persisting the result blocks past the fence TTL. The renewal stays on
    until the commit and the release finish, so a competing dispatch in the
    same context is refused as flow_dispatch_contended and its tool never
    runs; once the commit is released, the first call's result is visible and
    exactly one tool call was recorded. Before the renewal outlived the
    commit, the hold expired here, the second call ran, and both did."""
    import threading
    import time

    import remora.enforcement.lease as lease_mod
    import remora.flow.labeler as labeler_mod

    context_id = _context(executor)
    calls = [dict(_call(context_id), arguments={"work_order_id": f"WO-{i}", "status": "closed"})
             for i in (1, 2)]
    leases = [_lease(executor, call) for call in calls]
    ttl = 1.0
    executor.monkeypatch.setattr(lease_mod, "DEFAULT_LEASE_TTL_SECONDS", ttl)
    persisting, proceed = threading.Event(), threading.Event()
    real_label_result = labeler_mod.FlowLabeler.label_result
    seen: list[int] = []

    def blocked_label_result(self, *args, **kwargs):
        seen.append(1)
        if len(seen) == 1:
            persisting.set()
            assert proceed.wait(timeout=30)
        return real_label_result(self, *args, **kwargs)

    executor.monkeypatch.setattr(labeler_mod.FlowLabeler, "label_result", blocked_label_result)
    first: dict = {}
    worker = threading.Thread(
        target=lambda: first.update(_post(executor, leases[0], call=calls[0]).json()))
    try:
        worker.start()
        assert persisting.wait(timeout=30), "the first dispatch never reached its commit"
        time.sleep(2 * ttl)
        second = _post(executor, leases[1], call=calls[1]).json()["tool_execution"]
        assert (second["executed"], second.get("refusal_reason")) == (
            False, "flow_dispatch_contended"), second
        assert len(executor.registry.CALLS) == 1   # only the first call's tool has run
    finally:
        proceed.set()
        worker.join(timeout=30)
    assert first["tool_execution"]["executed"] is True
    assert "result" in first["tool_execution"], first
    assert len(executor.registry.CALLS) == 1


def test_the_final_commit_is_refused_when_the_fence_lapsed_in_the_same_step(executor):
    """The ownership check is the append that records the commit, not a read
    before it: the hold is judged in the state the append is conditioned on.
    Here the hold expires between the early check and the append (the clock
    jumps once), so the commit is refused and the result withheld."""
    import time

    import servers.execution_api as exec_mod
    from remora.flow import context as context_mod
    import remora.flow.labeler as labeler_mod

    context_id = _context(executor)
    call = _call(context_id)
    contexts, handles = exec_mod._flow_contexts(), exec_mod._flow_handles()
    seq = contexts.load("acme", "employee-1", context_id).seq
    now = time.time()
    dispatch_id = contexts.begin_dispatch(
        "acme", "employee-1", context_id, expected_seq=seq, proposal_id="p-late",
        expires_at=now + 5, now=now)
    assert dispatch_id is not None
    state = contexts.load("acme", "employee-1", context_id)
    # Only the store's clock jumps; the early check in the labeler still sees
    # the hold as live, so the refusal below can only come from the append.
    real_time = time.time
    executor.monkeypatch.setattr(
        context_mod, "time", SimpleNamespace(time=lambda: real_time() + 60))
    with pytest.raises(labeler_mod.FlowCommitFailed) as refused:
        labeler_mod.commit_labeled_result(
            labeler_mod.FlowLabeler(), WO_FLOW, contexts=contexts, handles=handles, tenant_id="acme",
            principal="employee-1", context_id=context_id, proposal_id="p-late",
            arguments=call["arguments"], raw_result={"ok": True}, expected_epoch=state.epoch,
            dispatch_id=dispatch_id)
    assert str(refused.value) == "flow_dispatch_fence_expired"
