# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Effect evidence must follow an authorized dispatch, and the audit trail
must keep every lifecycle event (RMR-AUD-004, RMR-AUD-005).

The external audit of 2026-10-18 reproduced five defects on the Python
runtime, each pinned here:

- an ``effect_verified`` record was accepted, and projected as
  ``EFFECT_VERIFIED``, on a proposal the policy had abstained on or a reviewer
  had rejected, because the lineage read only the ``execution_result``;
- with no ``REMORA_EFFECT_VERIFIER_BINDINGS`` the executing agent could attest
  its own effect, in every environment;
- ``PostconditionContract.target_selector`` was never compared with the
  observed object, so evidence about another object verified;
- the audit idempotency key for ``approved`` and ``execution_*`` events named
  only the item, so a second approval or a second refusal on the same item was
  dropped from the chain;
- ``current_state`` returned ``REFUSED`` once any refusal had happened, even
  when the item was still approved or had been approved again.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from remora.execution.projections import current_state
from remora.governance.effect_receipt import ReceiptRefused, resolve_lineage
from remora.governance.effect_verification import (
    EffectStatus,
    PostconditionContract,
    verify_declared_delta,
)

JTI = "jti-1"
CALL_HASH = "c" * 64
AT = datetime.now(UTC) - timedelta(minutes=1)


def _ev(name: str, **payload) -> dict:
    return {"event": name, "timestamp": AT.isoformat(),
            "payload": {"event": name, "proposal_id": "p-1", **payload}}


def _authorized(**over) -> dict:
    return _ev("execution_authorized", **{
        "grant_jti": JTI, "tool_call_hash": CALL_HASH, "pep_allowed": True,
        "actor": "agent-1", **over})


def _result(**over) -> dict:
    return _ev("execution_result", **{
        "grant_jti": JTI, "tool_call_hash": CALL_HASH, "tool_executed": True,
        "actor": "agent-1", **over})


def _effect(status: str = "EFFECT_VERIFIED", *, computed: bool = True) -> dict:
    # A verdict REMORA computed says so (SDD L7); a digest-only attestation
    # without the marker is a claim and is projected as EFFECT_CLAIMED.
    return _ev("effect_verified", status=status, reason_code="x",
               verified_at=AT.isoformat(), verifier_identity="reader",
               expected_sha256="a" * 64, observed_sha256="a" * 64,
               evidence_refs=(["verdict:computed"] if computed else []))


def _accept_chain() -> list[dict]:
    return [_ev("assessed", decision="accept", actor="agent-1"),
            _authorized(), _result()]


def _review_chain(decision: str = "verify") -> list[dict]:
    return [_ev("assessed", decision=decision, actor="agent-1"),
            _ev("approved", actor="human-1"), _authorized(), _result()]


# ── lineage: the dispatch must have been authorized ─────────────────────────

@pytest.mark.parametrize("chain", [_accept_chain(), _review_chain(),
                                   _review_chain("escalate")])
def test_an_authorized_dispatch_has_a_lineage(chain) -> None:
    lineage = resolve_lineage(chain)
    assert lineage.grant_jti == JTI
    assert "agent-1" in lineage.executors


def test_no_effect_after_the_policy_abstained() -> None:
    chain = [_ev("assessed", decision="abstain"), _authorized(), _result()]
    with pytest.raises(ReceiptRefused) as exc:
        resolve_lineage(chain)
    assert exc.value.reason == "dispatched_after_deny"


def test_no_effect_after_a_rejection() -> None:
    chain = _review_chain()
    chain.insert(1, _ev("rejected", actor="human-1"))
    with pytest.raises(ReceiptRefused) as exc:
        resolve_lineage(chain)
    assert exc.value.reason == "dispatched_after_deny"


def test_no_effect_without_an_assessment_decision() -> None:
    chain = [_ev("assessed"), _authorized(), _result()]
    with pytest.raises(ReceiptRefused) as exc:
        resolve_lineage(chain)
    assert exc.value.reason == "assessment_decision_unknown"


@pytest.mark.parametrize("decision", ["verify", "escalate"])
def test_a_reviewed_decision_needs_an_approval(decision) -> None:
    chain = [_ev("assessed", decision=decision), _authorized(), _result()]
    with pytest.raises(ReceiptRefused) as exc:
        resolve_lineage(chain)
    assert exc.value.reason == "dispatched_without_approval"


@pytest.mark.parametrize("voided", ["execution_approval_expired",
                                    "execution_approval_invalidated"])
def test_a_voided_approval_does_not_authorize_a_later_dispatch(voided) -> None:
    chain = [_ev("assessed", decision="verify"), _ev("approved", actor="human-1"),
             _ev(voided), _authorized(), _result()]
    with pytest.raises(ReceiptRefused) as exc:
        resolve_lineage(chain)
    assert exc.value.reason == "dispatched_without_approval"


@pytest.mark.parametrize("authorized", [
    None,
    _authorized(pep_allowed=False),
    _authorized(pep_allowed="true"),
    _authorized(grant_jti="other-jti"),
    _authorized(tool_call_hash="d" * 64),
])
def test_the_result_must_match_an_allowed_authorization(authorized) -> None:
    chain = [_ev("assessed", decision="accept")]
    if authorized is not None:
        chain.append(authorized)
    chain.append(_result())
    with pytest.raises(ReceiptRefused) as exc:
        resolve_lineage(chain)
    assert exc.value.reason == "dispatch_not_authorized"


# ── projection: a fold over the chain, not "any refusal ever" ──────────────

def test_an_effect_after_abstain_is_not_projected_as_verified() -> None:
    chain = [_ev("assessed", decision="abstain"), _authorized(), _result(),
             _effect()]
    assert current_state(chain, None) != "EFFECT_VERIFIED"


def test_an_effect_after_a_valid_lineage_is_projected() -> None:
    assert current_state(_review_chain() + [_effect()], None) == "EFFECT_VERIFIED"


def test_a_digest_only_verified_after_a_valid_lineage_is_only_a_claim() -> None:
    """SDD L7: a reported VERIFIED REMORA did not compute is never projected
    as verified, even when its lineage holds."""
    chain = _review_chain() + [_effect(computed=False)]
    assert current_state(chain, None) == "EFFECT_CLAIMED"


def test_a_binding_refusal_leaves_the_approval_standing() -> None:
    chain = [_ev("assessed", decision="verify"), _ev("approved"),
             _ev("execution_binding_refused")]
    assert current_state(chain, None) == "AUTHORIZED"


def test_a_context_refusal_leaves_the_approval_standing() -> None:
    chain = [_ev("assessed", decision="verify"), _ev("approved"),
             _ev("execution_context_refused")]
    assert current_state(chain, None) == "AUTHORIZED"


@pytest.mark.parametrize("voided", ["execution_approval_expired",
                                    "execution_approval_invalidated"])
def test_a_voided_approval_returns_to_review_and_can_be_approved_again(
    voided,
) -> None:
    chain = [_ev("assessed", decision="verify", review_item_id="i-1"),
             _ev("approved"), _ev(voided)]
    assert current_state(chain, None) == "REVIEW_PENDING"
    chain.append(_ev("approved"))
    assert current_state(chain, None) == "AUTHORIZED"
    chain.append(_authorized())
    assert current_state(chain, None) == "DISPATCHING"


@pytest.mark.parametrize("terminal", ["execution_grant_refused",
                                      "execution_toolspec_changed", "rejected"])
def test_terminal_refusals_still_read_refused(terminal) -> None:
    chain = [_ev("assessed", decision="verify"), _ev("approved"), _ev(terminal)]
    assert current_state(chain, None) == "REFUSED"


@pytest.mark.parametrize("payload,expected", [
    ({"tool_executed": True}, "SUCCEEDED"),
    ({"tool_executed": False, "state_unknown": True}, "UNKNOWN"),
    ({"tool_executed": False}, "REFUSED"),
])
def test_a_result_without_an_outbox_projection_is_not_stuck_dispatching(
    payload, expected,
) -> None:
    # current_state without a dispatch row must still read the recorded
    # result: a chain ending in execution_result never stays DISPATCHING.
    chain = _review_chain()
    chain[-1] = _result(**payload)
    assert current_state(chain, None) == expected


# ── the declared target must be the observed object ─────────────────────────

def _contract() -> PostconditionContract:
    return PostconditionContract(tool_id="close_ticket", reader="get_ticket",
                                 target_selector={"id": "T-1"},
                                 expected_fields={"status": "closed"})


def _verify(observed):
    return verify_declared_delta(_contract(), observed, proposal_id="p",
                                 execution_id="e", toolspec_hash="",
                                 verifier_identity="reader")


def test_evidence_about_another_object_does_not_verify() -> None:
    result = _verify({"id": "T-999", "status": "closed"})
    assert result.status is EffectStatus.UNOBSERVABLE
    assert result.reason_code == "postcondition_target_mismatch"


def test_evidence_about_the_declared_object_verifies() -> None:
    assert _verify({"id": "T-1", "status": "closed"}).status is EffectStatus.VERIFIED


def test_a_selector_field_the_reader_does_not_return_is_not_compared() -> None:
    """The documented limit: binding is as strong as the reader's projection."""
    assert _verify({"status": "closed"}).status is EffectStatus.VERIFIED


def test_a_selector_type_difference_is_a_different_object() -> None:
    contract = PostconditionContract(tool_id="t", reader="r",
                                     target_selector={"id": 1},
                                     expected_fields={"status": "closed"})
    result = verify_declared_delta(contract, {"id": True, "status": "closed"},
                                   proposal_id="p", execution_id="e",
                                   toolspec_hash="", verifier_identity="r")
    assert result.reason_code == "postcondition_target_mismatch"


def _surface_runtime(monkeypatch):
    from remora.enforcement.lease import GovernedToolDispatcher
    from remora.toolcall.runtime_surface import RuntimeTool
    from remora.toolcall.surface_runtime import SurfaceRuntime

    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "surface-test-key")
    rt = SurfaceRuntime(GovernedToolDispatcher("policy"), {"write": "a" * 64},
                        mode="enforce")
    rt.register(RuntimeTool("write", "native", True, True, "a" * 64),
                lambda args: args)
    return rt


@pytest.mark.parametrize("selector,ok", [({"id": "row-1"}, True),
                                         ({"id": "row-2"}, False),
                                         ({"table": "rows"}, True)])
def test_a_contract_selector_must_name_the_called_object(
    monkeypatch, selector, ok,
) -> None:
    rt = _surface_runtime(monkeypatch)
    contract = PostconditionContract(tool_id="write", reader="reader",
                                     target_selector=selector,
                                     expected_fields={"value": 1})

    def assess():
        return rt.assess("write", {"id": "row-1", "value": 1}, tenant="t",
                         principal="actor", target="test", postcondition=contract)

    if ok:
        assess()
    else:
        with pytest.raises(ValueError, match="postcondition_target_not_call_argument"):
            assess()


# ── the API path ───────────────────────────────────────────────────────────

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from tests.test_effect_record_endpoint import (  # noqa: E402
    CALL,
    _dispatch_binding,
    _make_client,
    _record,
)


def _approved_item(client) -> tuple[str, str]:
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item, pid = assessed["review_item_id"], assessed["proposal_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item}).status_code == 200
    return item, pid


def _events(client, pid: str) -> list[str]:
    import servers.execution_api as exec_mod

    # Deferred events reach the chain when the outbox is drained.
    exec_mod.drain_audit_outbox("acme")
    trail =client.get(f"/v1/execution/proposals/{pid}/lifecycle").json()
    return [e["event"] for e in trail["events"]]


def _advance_queue(clock_days: int = 2) -> None:
    import servers.execution_api as exec_mod

    later = datetime.now(UTC) + timedelta(days=clock_days)
    for queue in exec_mod._QUEUES.values():
        queue._now_fn = lambda: later
        queue._log._now_fn = lambda: later


def _durable_client(monkeypatch, tmp_path):
    # The durable path is where the key collision lives: the event joins the
    # state transaction through the audit outbox, keyed for exactly-once.
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    client, _ = _make_client(monkeypatch, tmp_path)
    return client


def test_a_second_approval_is_recorded(monkeypatch, tmp_path) -> None:
    client = _durable_client(monkeypatch, tmp_path)
    item, pid = _approved_item(client)
    _advance_queue()
    r = client.post("/v1/execution/execute",
                    json={"item_id": item, "tool_call": CALL})
    assert r.json()["outcome"] == "approval_expired"
    assert client.post("/v1/execution/approve",
                       json={"item_id": item}).status_code == 200
    names = _events(client, pid)
    assert names.count("approved") == 2, names
    assert names[-1] == "approved"
    view = client.get(f"/v1/execution/proposals/{pid}").json()
    assert view["current_state"] == "AUTHORIZED"


def test_every_binding_refusal_is_recorded_and_the_approval_stands(
    monkeypatch, tmp_path,
) -> None:
    client = _durable_client(monkeypatch, tmp_path)
    item, pid = _approved_item(client)
    changed ={**CALL, "arguments": {"artifact_id": "rec-2", "content": {"n": 1}}}
    for _ in range(2):
        r = client.post("/v1/execution/execute",
                        json={"item_id": item, "tool_call": changed})
        assert r.json()["outcome"] == "binding_refused"
    assert _events(client, pid).count("execution_binding_refused") == 2
    assert client.get(
        f"/v1/execution/proposals/{pid}").json()["current_state"] == "AUTHORIZED"
    r = client.post("/v1/execution/execute",
                    json={"item_id": item, "tool_call": CALL})
    assert r.json()["outcome"] == "execute"


def _executed_proposal(client) -> str:
    item, _pid = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item, "tool_call": CALL})
    assert r.status_code == 200, r.text
    return str(r.json()["proposal_id"])


def _post_effect(client, pid: str, **over):
    body = {**_dispatch_binding(client, pid), **_record(**over)}
    return client.post(f"/v1/execution/proposals/{pid}/effect", json=body)


def test_in_development_a_self_attestation_is_recorded_as_one(
    monkeypatch, tmp_path,
) -> None:
    client, state = _make_client(monkeypatch, tmp_path)
    monkeypatch.delenv("REMORA_EFFECT_VERIFIER_BINDINGS", raising=False)
    pid = _executed_proposal(client)
    state["effect_principal"] = "employee-1"   # the executor itself
    r = _post_effect(client, pid, verifier_identity="employee-1")
    assert r.status_code == 200, r.text
    assert r.json()["self_attested"] is True
    view = client.get(f"/v1/execution/proposals/{pid}").json()
    assert view["effect"]["self_attested"] is True
    assert view["current_state"] != "EFFECT_VERIFIED"


def test_a_separate_verifier_settles_the_proposal(monkeypatch, tmp_path) -> None:
    client, _ = _make_client(monkeypatch, tmp_path)
    pid = _executed_proposal(client)
    r = _post_effect(client, pid)   # as reader-svc, bound to acme.reader/v1
    assert r.status_code == 200, r.text
    assert r.json()["self_attested"] is False
    view = client.get(f"/v1/execution/proposals/{pid}").json()
    # The separate verifier's record is the one the proposal shows (a
    # self-attestation never is). The tool has no signed postcondition, so
    # REMORA computed nothing and the record is a claim (SDD L7).
    assert view["current_state"] == "EFFECT_CLAIMED"
    assert view["effect"]["self_attested"] is False


def _production(monkeypatch, tmp_path):
    client, state = _make_client(monkeypatch, tmp_path)
    pid = _executed_proposal(client)
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    return client, pid, state


def test_production_requires_verifier_bindings(monkeypatch, tmp_path) -> None:
    client, pid, _state = _production(monkeypatch, tmp_path)
    monkeypatch.delenv("REMORA_EFFECT_VERIFIER_BINDINGS", raising=False)
    r = _post_effect(client, pid, verifier_identity="employee-1")
    assert r.status_code == 503, r.text
    assert "effect_verifier_bindings_required" in r.text


def test_production_refuses_the_executor_as_its_own_verifier(
    monkeypatch, tmp_path,
) -> None:
    client, pid, state = _production(monkeypatch, tmp_path)
    # employee-1 executed the call and is bound to the reader identity: the
    # binding alone does not make it an independent observer.
    state["effect_principal"] = "employee-1"
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_BINDINGS",
                       "employee-1=acme.reader/v1")
    r = _post_effect(client, pid)
    assert r.status_code == 403, r.text
    assert "verifier_is_executor" in r.text


# ── P0-4A through the public API only ───────────────────────────────────────

def _token_client(monkeypatch, tmp_path):
    """Real bearer tokens and the real role table; nothing patched on auth."""
    import importlib
    import json

    tokens = {
        "tok-alice": {"tenant": "acme", "role": "operator", "actor_id": "agent-alice"},
        "tok-bob": {"tenant": "acme", "role": "reviewer", "actor_id": "human-bob"},
        "tok-reader": {"tenant": "acme", "role": "effect_verifier",
                       "actor_id": "reader-svc"},
    }
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_EFFECT_VERIFIER_BINDINGS", raising=False)
    monkeypatch.setenv("REMORA_API_TOKENS", json.dumps(tokens))
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "p0-4a-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "p0-4a-lease-key")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    # The tool fails before it writes anything: its sandbox path is a file,
    # so the directory cannot be created. The dispatcher cannot tell that
    # from a lost response and records the outcome as unknown.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(blocker / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        monkeypatch.delenv(var, raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    api_mod = importlib.reload(api_mod)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app)


def _as(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _alice_crashed_call(client) -> str:
    assessed = client.post("/v1/execution/assess", json=CALL, headers=_as("tok-alice"))
    assert assessed.status_code == 200, assessed.text
    item = assessed.json()["review_item_id"]
    approved = client.post("/v1/execution/approve", json={"item_id": item},
                           headers=_as("tok-bob"))
    assert approved.status_code == 200, approved.text
    executed = client.post("/v1/execution/execute",
                           json={"item_id": item, "tool_call": CALL},
                           headers=_as("tok-alice"))
    assert executed.status_code == 200, executed.text
    pid = str(assessed.json()["proposal_id"])
    view = client.get(f"/v1/execution/proposals/{pid}", headers=_as("tok-alice")).json()
    assert view["current_state"] not in ("SUCCEEDED", "EFFECT_VERIFIED"), view
    return pid


def _alice_receipt(client, pid: str):
    trail = client.get(f"/v1/execution/proposals/{pid}/lifecycle",
                       headers=_as("tok-alice")).json()
    result = [e for e in trail["events"] if e["event"] == "execution_result"][-1]
    payload = result.get("payload") or result
    assert payload["tool_executed"] is False and payload["state_unknown"] is True
    body = {
        "tool_call_hash": payload["tool_call_hash"], "grant_jti": payload["grant_jti"],
        **_record(verifier_identity="agent-alice",
                  expected_sha256="1" * 64, observed_sha256="2" * 64),
    }
    return client.post(f"/v1/execution/proposals/{pid}/effect", json=body,
                       headers=_as("tok-alice"))


def test_p0_4a_the_executor_cannot_verify_its_own_crashed_call(
    monkeypatch, tmp_path,
) -> None:
    """On b64e3cc1 this returned 200 and the proposal read EFFECT_VERIFIED."""
    client = _token_client(monkeypatch, tmp_path)
    pid = _alice_crashed_call(client)
    # Development: the receipt is kept as a self-attestation, and it does not
    # settle the proposal.
    r = _alice_receipt(client, pid)
    assert r.status_code == 200, r.text
    assert r.json()["self_attested"] is True
    view = client.get(f"/v1/execution/proposals/{pid}", headers=_as("tok-alice")).json()
    assert view["current_state"] != "EFFECT_VERIFIED", view
    assert view["effect"]["self_attested"] is True


def test_p0_4a_is_refused_in_production(monkeypatch, tmp_path) -> None:
    client = _token_client(monkeypatch, tmp_path)
    pid = _alice_crashed_call(client)
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_BINDINGS",
                       "agent-alice=agent-alice,reader-svc=acme.reader/v1")
    r = _alice_receipt(client, pid)
    # The operator role does not hold verify_effect.
    assert r.status_code == 403, r.text
    view = client.get(f"/v1/execution/proposals/{pid}", headers=_as("tok-alice")).json()
    assert view["current_state"] != "EFFECT_VERIFIED", view


def test_strict_profiles_require_verifier_bindings(monkeypatch) -> None:
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review")
    monkeypatch.delenv("REMORA_EFFECT_VERIFIER_BINDINGS", raising=False)
    assert exec_mod._effect_separation_required() is True


def test_recording_an_effect_needs_the_verify_effect_capability(monkeypatch) -> None:
    import servers.api as api_mod

    assert "verify_effect" in api_mod._ALL_CAPABILITIES
    perms = api_mod._role_permissions_map()
    assert "verify_effect" in perms["effect_verifier"]
    assert "verify_effect" in perms["admin"]
    assert "verify_effect" not in perms["operator"]
