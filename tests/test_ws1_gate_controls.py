# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Four gate controls against the WS1 gate, requested by @astrogilda in #953.

@astrogilda proposed four controls for agent-evidence-vectors: a monitor
outage, a TTL lapsing before consumption, another tenant's evidence, and a
digest change after ACCEPT. They were not yet published when the Study C
holdout ended (latest release v0.24.0). These are REMORA's own versions of
the same four controls. They run against the actual WS1 gate through
``/v1/execution/execute-accepted`` and the real dispatcher, outside every
sealed study. The Probity vectors replace or join them once released.

Each control mints an ACCEPT grant under the WS1 binding, changes one thing,
and redeems. The expected outcome is a refusal before the grant is consumed,
shown by a later redemption of the same grant that succeeds once the change
is undone. One case records the known residual instead: evidence that lapses
between the re-gate and consumption is not seen, because nothing re-reads it
after the re-gate (``Residual_ProvedAtDispatchInstant`` in
formal/ws1_composition/model.py).

With ``REMORA_GATE_CONTROLS_OUT`` set, the outcomes are written there as JSON
(scripts/ws1_gate_controls.py).
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from remora.decision_providers.composition_adapter import MonitorMode  # noqa: E402
from remora.verification.resolvers import InMemorySource  # noqa: E402
from tests.test_ws1_execution_binding import (  # noqa: E402
    _events,
    _install,
    _mint,
    _mod,
    _redeem,
)
from tests.test_ws1_execution_binding import client as _route_client  # noqa: E402,F401
from tests.verification import ws1_deployment_fixture as fixture  # noqa: E402
from tests.verification._ws1 import response  # noqa: E402

OUTCOMES: list[dict] = []
REQUIRED = replace(fixture.PROFILE, mode=MonitorMode.REQUIRED, calibration_hash="1" * 64)


@pytest.fixture()
def client(_route_client):  # noqa: F811
    return _route_client


@pytest.fixture(autouse=True)
def _assets():
    saved = json.loads(json.dumps(fixture.ASSETS))
    yield
    fixture.ASSETS.clear()
    fixture.ASSETS.update(saved)


@pytest.fixture(scope="module", autouse=True)
def _write_outcomes():
    yield
    out = os.environ.get("REMORA_GATE_CONTROLS_OUT")
    if out:
        Path(out).write_text(json.dumps(OUTCOMES, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")


def _record(control: str, case: str, expected: str, refused: dict, after_undo: dict | None):
    OUTCOMES.append({"control": control, "case": case, "expected": expected,
                     "status_code": refused["status_code"], "detail": refused["detail"],
                     "executed": refused["executed"],
                     "ws1_reasons": refused.get("ws1_reasons"),
                     "grant_unspent": None if after_undo is None else after_undo["executed"]})


def _try(client, token):
    r = _redeem(client, token)
    body = r.json()
    return {"status_code": r.status_code, "detail": body.get("detail"),
            "executed": bool(body.get("tool_execution", {}).get("executed"))}


def _monitor(state):
    def monitor(context, checked):
        if state["down"]:
            raise TimeoutError("monitor unreachable")
        return response(context, checked.evidence_digest, prof=REQUIRED,
                        scores={"injection": 0.1})
    return monitor


def test_control_1_monitor_outage_refuses_before_consumption(client, monkeypatch):
    state = {"down": False}
    gate = _install(monkeypatch, "enforce", monitor=_monitor(state), monitor_profile=REQUIRED)
    token = _mint(gate)
    state["down"] = True
    refused = _try(client, token)
    assert (refused["status_code"], refused["detail"]) == (409, "ws1_regate_refused")
    assert not _events("execution_authorized")
    state["down"] = False
    after = _try(client, token)
    assert after["executed"] is True  # the grant was never spent
    _record("monitor_outage", "required monitor raises at the re-gate", "refused_unspent",
            refused, after)


def test_control_2a_evidence_already_lapsed_at_the_regate_refuses(client, monkeypatch):
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    _install(monkeypatch, "enforce", resolvers={
        "assets": InMemorySource("assets", "asset-inventory", fixture.ASSETS, ttl_s=0)})
    refused = _try(client, token)
    assert (refused["status_code"], refused["detail"]) == (409, "ws1_regate_refused")
    # Lapsed evidence is not admitted, so the precondition stays UNKNOWN.
    reasons = _events("execution_ws1_refused")[-1]["ws1"]["record"]["reason_codes"]
    assert set(reasons) & {"verification_stopped", "evidence_expired"}
    refused["ws1_reasons"] = reasons
    _install(monkeypatch, "enforce")
    after = _try(client, token)
    assert after["executed"] is True
    _record("ttl_before_consumption", "evidence valid_until reached at the re-gate",
            "refused_unspent", refused, after)


def test_control_2b_evidence_lapsing_after_the_regate_is_the_documented_residual(
        client, monkeypatch):
    """The re-gate proves the evidence fresh at its instant. If it lapses in
    the moment before consumption, nothing reads it again: the call runs.
    This pins the residual so a change in either direction is seen. It holds
    only where WS1-M4 admission is off (no declared clock skew); with it on,
    the same lapse refuses (tests/test_ws1_m4_admission.py, M4-T02)."""
    clock = {"ms": fixture.time.time_ns() // 1_000_000}
    gate = _install(monkeypatch, "enforce", clock_ms=lambda: clock["ms"], resolvers={
        "assets": InMemorySource("assets", "asset-inventory", fixture.ASSETS, ttl_s=1)})
    token = _mint(gate)
    exec_mod = _mod()
    real_check = exec_mod._GATE.check

    def lapse_then_check(*args, **kwargs):
        clock["ms"] += 5_000  # past valid_until, after the re-gate, before consumption
        return real_check(*args, **kwargs)

    monkeypatch.setattr(exec_mod._GATE, "check", lapse_then_check)
    ran = _try(client, token)
    assert ran["executed"] is True
    _record("ttl_before_consumption", "evidence lapses between the re-gate and consumption",
            "documented_residual_executes", ran, None)


class _OtherTenantSource(InMemorySource):
    """A source that answers with evidence stamped for another tenant."""

    def fetch(self, request, tenant_id, now_s):
        return replace(super().fetch(request, "acme", now_s), tenant_id="other")


def test_control_3a_another_tenants_record_refuses(client, monkeypatch):
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    original = fixture.ASSETS["acme"]["P-1"]
    fixture.ASSETS["acme"]["P-1"] = {"tenant": "other"}
    refused = _try(client, token)
    assert (refused["status_code"], refused["detail"]) == (409, "ws1_regate_refused")
    fixture.ASSETS["acme"]["P-1"] = original
    after = _try(client, token)
    assert after["executed"] is True
    _record("another_tenants_evidence", "the record now belongs to another tenant",
            "refused_unspent", refused, after)


def test_control_3b_evidence_stamped_for_another_tenant_refuses(client, monkeypatch):
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    _install(monkeypatch, "enforce", resolvers={
        "assets": _OtherTenantSource("assets", "asset-inventory", fixture.ASSETS)})
    refused = _try(client, token)
    assert (refused["status_code"], refused["detail"]) == (409, "ws1_regate_refused")
    _install(monkeypatch, "enforce")
    after = _try(client, token)
    assert after["executed"] is True
    _record("another_tenants_evidence", "the source returns evidence stamped for another tenant",
            "refused_unspent", refused, after)


@pytest.mark.parametrize("change", ["registry", "monitor_profile"])
def test_control_4_a_digest_change_after_accept_refuses(client, monkeypatch, change):
    gate = _install(monkeypatch, "enforce")
    token = _mint(gate)
    if change == "registry":
        tools = dict(fixture.REGISTRY.tools)
        predicates = tools["read_telemetry"]
        tools["read_telemetry"] = (replace(predicates[0], max_age_s=20), *predicates[1:])
        _install(monkeypatch, "enforce", registry=replace(fixture.REGISTRY, tools=tools))
    else:
        _install(monkeypatch, "enforce",
                 monitor_profile=replace(fixture.PROFILE, profile_id="changed-profile"))
    refused = _try(client, token)
    # Refused before consumption either by the re-gate or, earlier, by the
    # authorization context: the grant carries the WS1 binding digest.
    assert refused["status_code"] == 409
    assert refused["detail"] in ("ws1_regate_refused", "context_mismatch")
    assert not _events("execution_authorized")
    _install(monkeypatch, "enforce")
    after = _try(client, token)
    assert after["executed"] is True
    _record("digest_change_after_accept", f"{change} digest changed after ACCEPT",
            "refused_unspent", refused, after)
