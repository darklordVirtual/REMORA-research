# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The unsigned ``/effect`` path never turns a claim into a verdict (SDD L7).

``POST /v1/execution/proposals/{id}/effect`` takes a status from the
submitter. Before this change it recorded that status as reported, so a bare
``EFFECT_VERIFIED`` settled the proposal as verified although REMORA never
compared anything. L7 says ``EFFECT_VERIFIED`` is a verdict REMORA computes:

* when the tool's signed ToolSpec declares a ``postcondition``, an unsigned
  receipt must carry the observed object and the call's arguments, and
  REMORA computes the status on the same code path as a signed receipt; a
  bare claimed ``EFFECT_VERIFIED`` is refused;
* when no postcondition is declared, a claimed ``EFFECT_VERIFIED`` is
  recorded as a claim: the proposal shows ``EFFECT_CLAIMED``, never
  ``EFFECT_VERIFIED``, and the claim does not settle the dispatch, so a
  later computed verdict can.

The unsigned path still has ``vantage=same_deployment`` (decision 4); the
controlled_pilot refusal is tested in ``test_effect_receipt_endpoint_signed``.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from tests.test_effect_receipt_endpoint_signed import (  # noqa: E402
    CALL,
    CONTENT,
    _client,
    _executed,
    _post,
    _state,
)


def _unsigned(client, pid: str, dispatch: dict, *, status="EFFECT_VERIFIED",
              observed=None, arguments=None, reason="postcondition_verified",
              **extra):
    body = {
        "execution_id": dispatch.get("execution_id") or "exec-1",
        "execution_context_hash": dispatch.get("execution_context_hash") or "",
        "tool_id": "store_artifact",
        "tool_call_hash": dispatch["tool_call_hash"],
        "grant_jti": dispatch["grant_jti"],
        "status": status, "reason_code": reason,
        "verifier_identity": "acme.reader/v1",
        "expected_sha256": "a" * 64, "observed_sha256": "b" * 64,
        "verified_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
        **extra,
    }
    if observed is not None:
        body["observed"] = observed
    if arguments is not None:
        body["arguments"] = arguments
    return client.post(f"/v1/execution/proposals/{pid}/effect", json=body)


@pytest.fixture()
def with_post(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path, with_postcondition=True)


@pytest.fixture()
def without_post(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path, with_postcondition=False)


# ── a declared postcondition: REMORA computes ──────────────────────────────

def test_a_bare_claimed_verified_is_refused_when_a_postcondition_exists(with_post):
    """L7: a status without the observation REMORA needs is not evidence."""
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch)
    assert r.status_code == 409, r.text
    assert "postcondition_observation_required" in r.json()["detail"]
    assert _state(client, pid)["current_state"] != "EFFECT_VERIFIED"


def test_an_unsigned_observation_is_evaluated_by_remora(with_post):
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch,
                  observed={"artifact_id": "rec-1", "content": CONTENT},
                  arguments=CALL["arguments"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "EFFECT_VERIFIED"
    assert body["verdict_source"] == "computed"
    assert body["vantage"] == "same_deployment"
    assert _state(client, pid)["current_state"] == "EFFECT_VERIFIED"


def test_a_claim_that_disagrees_with_the_observation_records_the_computed_verdict(with_post):
    """expected != observed under the contract -> MISMATCH whatever is claimed."""
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch,
                  observed={"artifact_id": "rec-1", "content": {"n": 2}},
                  arguments=CALL["arguments"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "EFFECT_MISMATCH"
    assert body["claimed_status"] == "EFFECT_VERIFIED"
    assert body["claim_disagrees"] is True
    assert _state(client, pid)["current_state"] == "EFFECT_MISMATCH"


def test_an_observation_of_another_target_never_verifies_unsigned(with_post):
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch,
                  observed={"artifact_id": "rec-999", "content": CONTENT},
                  arguments=CALL["arguments"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EFFECT_UNOBSERVABLE"
    assert _state(client, pid)["current_state"] != "EFFECT_VERIFIED"


def test_unsigned_arguments_other_than_the_dispatched_call_are_refused(with_post):
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch,
                  observed={"artifact_id": "rec-2", "content": CONTENT},
                  arguments={"artifact_id": "rec-2", "content": CONTENT})
    assert r.status_code == 409, r.text
    assert "arguments_not_the_dispatched_call" in r.json()["detail"]


def test_an_observation_without_arguments_is_refused(with_post):
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch,
                  observed={"artifact_id": "rec-1", "content": CONTENT})
    assert r.status_code == 409, r.text
    assert "arguments_required" in r.json()["detail"]


def test_a_reported_mismatch_without_an_observation_is_still_recorded(with_post):
    """Bad news reported about oneself is recorded as reported: it cannot
    raise the state, so it needs no observation (unchanged behaviour)."""
    client, _ = with_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch, status="EFFECT_MISMATCH",
                  reason="postcondition_mismatch")
    assert r.status_code == 200, r.text
    assert _state(client, pid)["current_state"] == "EFFECT_MISMATCH"


# ── no postcondition: a claim stays a claim ────────────────────────────────

def test_a_claim_without_a_postcondition_shows_as_claimed_never_verified(without_post):
    client, _ = without_post
    pid, dispatch = _executed(client)
    r = _unsigned(client, pid, dispatch)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["effect_state"] == "EFFECT_CLAIMED"
    assert body["claimed_status"] == "EFFECT_VERIFIED"
    assert body["verdict_source"] == "claimed"
    state = _state(client, pid)
    assert state["current_state"] == "EFFECT_CLAIMED"
    assert state["effect"]["effect_state"] == "EFFECT_CLAIMED"
    assert state["effect"]["verdict_source"] == "claimed"
    assert state["effect"]["status"] == "EFFECT_VERIFIED"  # as reported


def test_the_envelope_never_shows_a_claim_as_verified(without_post):
    client, _ = without_post
    pid, dispatch = _executed(client)
    assert _unsigned(client, pid, dispatch).status_code == 200
    envelope = client.get(f"/v1/execution/proposals/{pid}/envelope")
    assert envelope.status_code == 200, envelope.text
    effect = envelope.json()["effect"]
    assert effect["effect_outcome"] == "EFFECT_CLAIMED"
    assert effect["ledger_entry"]["effect_verdict_source"] == "claimed"


def test_a_claim_does_not_settle_the_dispatch(without_post):
    """A later claim is appended; it does not replay-block, and it never
    becomes a verdict."""
    client, _ = without_post
    pid, dispatch = _executed(client)
    assert _unsigned(client, pid, dispatch).status_code == 200
    again = _unsigned(client, pid, dispatch)
    assert again.status_code == 200, again.text
    assert _state(client, pid)["current_state"] == "EFFECT_CLAIMED"


def test_a_signed_computed_verdict_settles_after_a_claim(monkeypatch, tmp_path):
    """The claim recorded first does not block the computed verdict."""
    client, _ = _client(monkeypatch, tmp_path, with_postcondition=True)
    pid, dispatch = _executed(client)
    claimed = _unsigned(client, pid, dispatch, status="EFFECT_UNOBSERVABLE",
                        reason="reader_unavailable")
    assert claimed.status_code == 200, claimed.text
    signed = _post(client, pid, dispatch)
    assert signed.status_code == 200, signed.text
    assert _state(client, pid)["current_state"] == "EFFECT_VERIFIED"
