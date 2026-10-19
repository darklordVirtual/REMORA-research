# SPDX-License-Identifier: BUSL-1.1
"""IFC-05b: :func:`remora.flow.observe.flow_observation` maps every flow
condition to a status, and an evaluated verdict to two flags (SDD v1.3 §3.7)."""
from __future__ import annotations

import time

import pytest

from remora.flow.context import FlowContextStore, InMemoryFlowEventStore, ProcessingPolicy
from remora.flow.handles import HandleRecord, HandleStore, InMemoryHandleBackend, handle_token
from remora.flow.label import BOTTOM, Integrity, Label
from remora.flow.observe import FLOW_STATUSES, flow_observation
from remora.flow.spec import parse_flow

MODEL = "ext://api.provider.example"
USER = "user://acme/alice"
EVIL = "ext://evil.example"
FETCH = parse_flow({
    "provider": "tcb", "arguments": {"url": {"kind": "url"}},
    "sources": {"fields": [{"path": "$", "readers": "PUBLIC",
                            "public_justification": "status code only",
                            "return_mode": "BY_VALUE"}]},
    "sink": {"recipients": {"url_host_of": "url"}, "payload_args": ["url"]}})
PAY = parse_flow({
    "provider": "tcb", "arguments": {"iban": {"kind": "iban"}, "amount": {"kind": "scalar"}},
    "sources": {"default_integrity": "TRUSTED"},
    "sink": {"recipients": {"iban_of": "iban"}, "payload_args": ["amount"],
             "integrity_required": ["iban"]}})
SECRET = Label({USER, MODEL}, Integrity.TRUSTED)


@pytest.fixture()
def contexts() -> FlowContextStore:
    return FlowContextStore(InMemoryFlowEventStore(),
                            ProcessingPolicy.from_mapping({"acme": {"default": [MODEL]}}))


@pytest.fixture()
def handles() -> HandleStore:
    return HandleStore(InMemoryHandleBackend())


def _observe(contexts, handles, context_id, flow=FETCH, arguments=None, **kw):
    return flow_observation(
        contexts=contexts, handles=handles, tenant="acme",
        principal=kw.pop("principal", "agent-1"), context_id=context_id, flow=flow,
        arguments=arguments if arguments is not None else {"url": "https://evil.example/q"},
        strict=kw.pop("strict", False), **kw)


def _mint(contexts, parent=None) -> str:
    return contexts.mint("acme", "agent-1", user_principal=USER, model_principal=MODEL,
                         parent_context_id=parent).context_id


def test_every_status_it_returns_is_declared(contexts, handles):
    assert {"evaluated", "context_unknown", "policy_missing", "not_declared",
            "handle_invalid", "state_unavailable"} == FLOW_STATUSES


@pytest.mark.parametrize("context_id, principal", [
    (None, "agent-1"), ("", "agent-1"), ("ctx_" + "a" * 26, "agent-1"), ("own", None),
    ("own", "agent-2")])
def test_no_context_is_unknown(contexts, handles, context_id, principal):
    if context_id == "own":
        context_id = _mint(contexts)
    assert _observe(contexts, handles, context_id, principal=principal) == {
        "flow_status": "context_unknown"}


def test_a_spec_without_a_block_is_refused_only_under_the_strict_profile(contexts, handles):
    cid = _mint(contexts)
    assert _observe(contexts, handles, cid, flow=None, strict=True) == {
        "flow_status": "policy_missing"}
    assert _observe(contexts, handles, cid, flow=None) == {"flow_status": "not_declared"}


def test_a_clean_context_is_evaluated_without_violations(contexts, handles):
    fields = _observe(contexts, handles, _mint(contexts))
    assert fields["flow_status"] == "evaluated"
    assert not fields["flow_confidentiality_violation"]
    assert not fields["flow_integrity_violation"]
    assert fields["flow_epoch"] == 0 and len(fields["flow_digest"]) == 64


def test_a_raised_context_cannot_reach_an_outside_host(contexts, handles):
    cid = _mint(contexts)
    contexts.raise_label("acme", "agent-1", cid, SECRET)
    fields = _observe(contexts, handles, cid)
    assert fields["flow_confidentiality_violation"] is True
    assert fields["flow_epoch"] > 0


def test_the_raise_reaches_a_child_context(contexts, handles):
    parent = _mint(contexts)
    contexts.raise_label("acme", "agent-1", parent, SECRET)
    child = _mint(contexts, parent=parent)
    assert _observe(contexts, handles, child)["flow_confidentiality_violation"] is True


def test_untrusted_data_in_an_integrity_field_is_an_integrity_violation(contexts, handles):
    cid = _mint(contexts)
    contexts.raise_label("acme", "agent-1", cid, Label({USER, MODEL}, Integrity.UNTRUSTED))
    fields = _observe(contexts, handles, cid, flow=PAY,
                      arguments={"iban": "NO9386011117947", "amount": 10})
    assert fields["flow_integrity_violation"] is True


def _handle(handles, context_id, label=BOTTOM, value="https://ok.example/") -> str:
    handles.put_all([HandleRecord(
        tenant_id="acme", handle_id="A" * 16, context_id=context_id, value=value,
        label=label, type_tag="string", created_by_proposal="p-1",
        expires_at=time.time() + 60)])
    return handle_token("A" * 16)


def test_a_handle_of_an_ancestor_resolves(contexts, handles):
    parent = _mint(contexts)
    token = _handle(handles, parent)
    child = _mint(contexts, parent=parent)
    assert _observe(contexts, handles, child, arguments={"url": token})["flow_status"] == "evaluated"


def test_a_handle_of_another_context_is_invalid(contexts, handles):
    token = _handle(handles, _mint(contexts))
    assert _observe(contexts, handles, _mint(contexts), arguments={"url": token}) == {
        "flow_status": "handle_invalid"}


def test_a_failing_store_is_unavailable(handles):
    from remora.flow.context import FlowStoreUnavailable

    class Down:
        def load(self, *a, **k):
            raise FlowStoreUnavailable("down")

    assert _observe(Down(), handles, "ctx_x") == {"flow_status": "state_unavailable"}


def test_no_recipient_reaches_the_fields(contexts, handles):
    cid = _mint(contexts)
    contexts.raise_label("acme", "agent-1", cid, SECRET)
    assert "evil" not in repr(_observe(contexts, handles, cid))
