# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The rest of the M4.1 negative test matrix through the real route (M4-T15, T17-T20).

Same deployment as ``tests/test_ws1_atomic_admission_route.py``:
``REMORA_WS1_ADMISSION=atomic`` over SQLite, the WS1 fixture deployment and
the real dispatcher. The M4-T* names refer to
docs/design/ws1-m4-safe-autonomy-recovery-v0.2.md §5. Faults are injected at
fixed points (a dispatcher that loses the response, a resolver that revises
its source mid-lookup, a monitor that fails or lies), never by timing.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("fastapi")

from remora.decision_providers.composition_adapter import MonitorMode  # noqa: E402
from remora.enforcement.gate import EnforcementGate  # noqa: E402
from remora.enforcement.lease import ExecutionLease, ToolExecutionStateUnknown  # noqa: E402
from remora.verification.planner import VerificationBudget  # noqa: E402
from remora.verification.resolvers import InMemorySource  # noqa: E402
from tests.test_execute_accepted_toolspec import CALL  # noqa: E402
from tests.test_ws1_atomic_admission_route import (  # noqa: E402
    SOURCE,
    _approved,
    _execute,
    _row_state,
    _try,
)
from tests.test_ws1_atomic_admission_route import client as _admission_client  # noqa: E402,F401
from tests.test_ws1_execution_binding import (  # noqa: E402
    _assets,  # noqa: F401  (autouse: restores the fixture's asset inventory)
    _events,
    _install,
    _mint,
    _mod,
    _redeem,
)
from tests.test_ws1_execution_binding import client as _route_client  # noqa: E402,F401
from tests.verification import ws1_deployment_fixture as fixture  # noqa: E402
from tests.verification._ws1 import response  # noqa: E402


@pytest.fixture()
def client(_admission_client):  # noqa: F811
    return _admission_client


def _spent(token: dict) -> bool:
    grant = _mod().PolicyDecisionToken.from_dict(token)
    return _mod()._GATE.check(grant, consume=False).reason == "token_already_consumed"


def _accept_rows(token: dict) -> set[str]:
    jti = _mod().PolicyDecisionToken.from_dict(token).jti
    return {r.state.value for r in _mod()._outbox().rows_for_proposal("acme", "p-ws1-1")
            if r.item_id == f"accept:{jti}"}


# ── M4-T15: the send begins and the response is dropped ─────────────────────


class _DropsTheResponse:
    """Sends through the real dispatcher, then loses the answer."""

    def __init__(self, real: Any) -> None:
        self.real, self.sent = real, 0

    def dispatch(self, *args: Any, **kwargs: Any) -> Any:
        self.real.dispatch(*args, **kwargs)
        self.sent += 1
        raise ToolExecutionStateUnknown("connection reset after the request was sent")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


@pytest.fixture()
def lossy(client, monkeypatch):
    exec_mod = _mod()
    real = exec_mod._local_dispatcher
    holder: dict[str, _DropsTheResponse] = {}

    def wrapped(presented_lease):
        dispatcher = real(presented_lease)
        holder.setdefault("d", _DropsTheResponse(dispatcher))
        return holder["d"]

    monkeypatch.setattr(exec_mod, "_local_dispatcher", wrapped)
    return holder


def test_m4_t15_a_dropped_response_is_unknown_and_never_retried(client, lossy, monkeypatch):
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    execution = _redeem(client, token).json()["tool_execution"]
    assert (execution["executed"], execution["dispatch_began"], execution["state_unknown"]) == (
        False, True, True)
    assert lossy["d"].sent == 1
    assert _accept_rows(token) == {"UNKNOWN"}
    assert _events("execution_result")[-1]["state_unknown"] is True
    # No unconditional retry: not by presenting the grant again, not by the
    # worker, not by the stale-dispatch sweep.
    assert _try(client, token)[:2] == (409, "token_already_consumed")
    assert _mod().dispatch_pending_intents("acme", worker_id="w-2") == []
    _mod().reconcile_stale_dispatches("acme")
    assert lossy["d"].sent == 1 and _accept_rows(token) == {"UNKNOWN"}


def test_m4_t15_the_worker_settles_a_dropped_response_unknown(client, lossy, monkeypatch):
    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    item_id = _approved(client, monkeypatch)
    _execute(client, item_id)
    [result] = _mod().dispatch_pending_intents("acme", worker_id="w-1")
    assert result["tool_execution"]["state_unknown"] is True
    assert _row_state(item_id) == {"UNKNOWN"}
    assert _mod().dispatch_pending_intents("acme", worker_id="w-2") == []
    assert lossy["d"].sent == 1


# ── M4-T17: the monitor is unavailable or poisoned ───────────────────────────

REQUIRED = replace(fixture.PROFILE, mode=MonitorMode.REQUIRED, calibration_hash="1" * 64)
BUDGET = VerificationBudget(max_rounds=3, max_resolver_calls=3, max_monitor_calls=2,
                            requests_per_round=1)


def _clean(context, checked):
    return response(context, checked.evidence_digest, prof=REQUIRED,
                    scores={"injection": 0.1})


def _monitored(monkeypatch, monitor):
    return _install(monkeypatch, "enforce", monitor=monitor, monitor_profile=REQUIRED,
                    budget=BUDGET)


def test_m4_t17_a_required_monitor_that_is_down_refuses_unspent(client, monkeypatch):
    token = _mint(_monitored(monkeypatch, _clean))
    calls: list[int] = []

    def down(context, checked):
        calls.append(1)
        raise ConnectionError("monitor unreachable")

    _monitored(monkeypatch, down)
    assert _try(client, token) == (409, "ws1_regate_refused", False)
    assert not _spent(token) and not _events("execution_authorized")
    assert len(calls) <= BUDGET.max_monitor_calls


@pytest.mark.parametrize("poison", [
    {"hint_precondition_ids": ["asset_registered", "admin_granted"]},
    {"evidence_digest": "0" * 64},
    {"uncertainty_codes": ["evidence_conflict"], "out_of_scope": False},
])
def test_m4_t17_a_poisoned_monitor_supplies_no_missing_authority(client, monkeypatch, poison):
    """The evidence is withdrawn after the grant; a monitor that says all is
    well, or hints at authority, or answers for other evidence, does not
    put it back."""
    token = _mint(_monitored(monkeypatch, _clean))
    calls: list[int] = []

    def lying(context, checked):
        calls.append(1)
        body = {"evidence_digest": checked.evidence_digest, **poison}
        digest = body.pop("evidence_digest")
        return response(context, digest, prof=REQUIRED, scores={"injection": 0.0}, **body)

    _monitored(monkeypatch, lying)
    del fixture.ASSETS["acme"]["P-1"]
    assert _try(client, token) == (409, "ws1_regate_refused", False)
    assert not _spent(token) and not _events("execution_authorized")
    assert len(calls) <= BUDGET.max_monitor_calls


# ── M4-T18: the source revises itself during the resolver loop ──────────────


class _RevisingSource:
    """The asset inventory, which publishes a new revision while it answers."""

    def __init__(self, on_fetch) -> None:
        self.real = InMemorySource("assets", "asset-inventory", fixture.ASSETS)
        self.on_fetch = on_fetch

    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        self.on_fetch()
        return self.real.fetch(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


def test_m4_t18_a_source_revision_mid_lookup_refuses_the_stale_receipt(client, monkeypatch):
    token = _mint(_install(monkeypatch, "enforce"))
    admission = _mod()._admission()
    _install(monkeypatch, "enforce", resolvers={"assets": _RevisingSource(
        lambda: admission.advance_authority("acme", SOURCE, revoked=False))})
    assert _try(client, token) == (409, "authority_epoch_stale", False)
    assert not _spent(token)
    _install(monkeypatch, "enforce")
    assert _try(client, token)[2] is True


def test_m4_t18_a_policy_revision_mid_lookup_refuses(client, monkeypatch):
    """The policy bundle changes while the resolver answers. The grant was
    issued under the old bundle, so it no longer binds the call."""
    import servers.api as api_mod

    token = _mint(_install(monkeypatch, "enforce"))
    real = api_mod._policy_component_hashes
    revised: list[bool] = []

    def revise():
        if not revised:
            revised.append(True)
            monkeypatch.setattr(api_mod, "_policy_component_hashes",
                                lambda *a, **k: {**real(*a, **k), "policy_hash": "f" * 64})

    _install(monkeypatch, "enforce", resolvers={"assets": _RevisingSource(revise)})
    assert _try(client, token) == (409, "context_mismatch", False) and revised
    assert not _spent(token) and not _events("execution_authorized")


# ── M4-T19: a path around the executor is offered ────────────────────────────


def _leased(client, token: dict, lease: dict, call: dict = CALL):
    # RMR-SEC-0001: only the execution domain serves /dispatch-leased; the
    # rest of this matrix drives authority routes in the same process.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
        return client.post("/v1/execution/dispatch-leased",
                           json={"lease": lease, "tool_call": call, "tenant_id": "acme"})


def _spent_lease(client, monkeypatch) -> tuple[dict, dict]:
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    assert _redeem(client, token).json()["tool_execution"]["executed"] is True
    return token, _events("execution_result")[-1]["lease"]


def test_m4_t19_a_refused_admission_leaves_no_lease_to_use(client, monkeypatch):
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    _mod()._admission().advance_authority("acme", SOURCE, revoked=True)
    r = _redeem(client, token)
    assert r.status_code == 409
    assert "lease" not in r.text
    assert not any("lease" in e.payload for e in _mod()._CHAIN.entries("acme"))


@pytest.mark.parametrize("field,value", [
    ("tool_args_hash", "0" * 64),
    ("actor_identity", "someone-else"),
    ("expires_at", "2999-01-01T00:00:00+00:00"),
])
def test_m4_t19_an_altered_lease_is_refused_by_the_executor(client, monkeypatch, field, value):
    token, lease = _spent_lease(client, monkeypatch)
    sent = [e for e in _events("execution_result") if e.get("tool_executed")]
    body = _leased(client, token, {**lease, field: value})
    assert body.status_code == 200
    # RMR-SEC-0001: the executor now checks authenticity at the route, before
    # the dispatcher and before any chain write, so the refusal no longer
    # carries the dispatcher's dispatch_began/nested_effects fields.
    assert body.json()["tool_execution"] == {
        "executed": False, "proposal_id": "p-ws1-1",
        "refusal_reason": "signature_invalid"}
    assert [e for e in _events("execution_result") if e.get("tool_executed")] == sent
    assert _events("lease_dispatch_admitted") == [], (
        "an inauthentic lease must not reach the executor's audit record")


def test_m4_t19_a_lease_for_another_call_is_refused(client, monkeypatch):
    token, lease = _spent_lease(client, monkeypatch)
    other = {**CALL, "arguments": {"asset": "wired-1"}}
    r = _leased(client, token, lease, other)
    assert r.json()["tool_execution"]["refusal_reason"] == "tool_args_hash_mismatch"
    assert r.json()["tool_execution"]["executed"] is False


# ── M4-T20: a grant or lease presented again after a restart ────────────────


def _restart(db: str, monkeypatch) -> None:
    """Drop every in-process cache; only the durable state survives."""
    exec_mod = _mod()
    monkeypatch.setattr(exec_mod, "_GATE", EnforcementGate(
        strict=True, audience=exec_mod.PEP_AUDIENCE, db_path=db))
    monkeypatch.setattr(exec_mod, "_ADMISSION", None)
    monkeypatch.setattr(exec_mod, "_DISPATCHER", None)
    exec_mod._reset_outbox()


def test_m4_t20_a_grant_replayed_after_a_restart_is_refused(client, monkeypatch):
    import os

    token, lease = _spent_lease(client, monkeypatch)
    _restart(os.environ["REMORA_CHAIN_DB"], monkeypatch)
    assert _try(client, token)[:2] == (409, "token_already_consumed")
    executed = [e for e in _events("execution_result") if e.get("tool_executed")]
    r = _leased(client, token, lease)
    # Refused by the durable nonce ledger the restart did not clear.
    assert r.json()["tool_execution"]["refusal_reason"] == "nonce_already_consumed"
    assert [e for e in _events("execution_result") if e.get("tool_executed")] == executed
    assert ExecutionLease.from_dict(lease).expires_at > datetime.now(UTC).isoformat(), (
        "the replay must be refused as spent, not merely as expired")


# ── M4-T07 and T08 under atomic admission: a swapped binding ────────────────


@pytest.mark.parametrize("swap,reason", [("arguments", "binding_refused"),
                                         ("target", "binding_refused"),
                                         ("actor", "context_mismatch")])
def test_m4_t07_t08_a_swapped_binding_refuses_unspent(client, monkeypatch, swap, reason):
    from tests.test_ws1_atomic_admission_route import _as_principal

    token = _mint(_install(monkeypatch, "enforce"))
    call = dict(CALL)
    if swap == "arguments":
        call["arguments"] = {"asset": "wired-1"}
    elif swap == "target":
        call["target_environment"] = "staging"
    else:
        _as_principal(monkeypatch, "someone-else")
    r = _redeem(client, token, call)
    assert (r.status_code, r.json().get("detail")) == (409, reason)
    assert not _spent(token) and not _events("execution_authorized")
