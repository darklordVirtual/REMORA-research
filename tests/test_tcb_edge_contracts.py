# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Edge contracts in the trusted computing base the suites never reached.

The coverage residual of issue #280: after the mutation rounds, the
remaining uncovered lines in ``remora/enforcement`` and
``remora/execution`` split into two kinds. The Postgres/D1 adapter
branches are contract-tested against a real server behind the ``pg_dsn``
marker and stay out of scope here. Everything else is genuinely untested
behaviour — environment parsing, failure-posture branches, projection
ladders, reconciler guards — and this file pins it.
"""
from __future__ import annotations

import io
import urllib.error
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import remora.execution.remote_dispatch as rd
from remora.enforcement import outbox as outbox_mod
from remora.enforcement.outbox import ExecutionOutbox, OutboxState
from remora.enforcement.result_envelope import (DEFAULT_MAX_RESULT_BYTES,
                                                ENV_MAX_RESULT_BYTES,
                                                configured_max_bytes)
from remora.enforcement.token import _hash_observation
from remora.enforcement import lease as lease_mod
from remora.execution.projections import (EffectVerificationReplay,
                                          current_state,
                                          record_effect_verification)

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


# ── result envelope: the configured size cap ───────────────────────────────


@pytest.mark.parametrize("raw, expected", [
    ("", DEFAULT_MAX_RESULT_BYTES),
    ("   ", DEFAULT_MAX_RESULT_BYTES),
    ("not-a-number", DEFAULT_MAX_RESULT_BYTES),
    ("-5", DEFAULT_MAX_RESULT_BYTES),
    ("0", DEFAULT_MAX_RESULT_BYTES),
    ("1234", 1234),
], ids=["unset", "blank", "garbage", "negative", "zero", "valid"])
def test_result_cap_env_parsing_fails_to_the_default(
    monkeypatch, raw, expected
) -> None:
    """A misconfigured cap must degrade to the default, never to 'no cap'
    and never to a crash inside the enforcement path."""
    monkeypatch.setenv(ENV_MAX_RESULT_BYTES, raw)
    assert configured_max_bytes() == expected


# ── remote dispatch: the custody-hop failure posture ───────────────────────


def _tool_call():
    return SimpleNamespace(tool_name="wo_close", arguments={"id": "WO-1"},
                           target_environment="staging")


def _lease_stub():
    return SimpleNamespace(to_dict=lambda: {"decision": "accept"})


@pytest.mark.parametrize("raw, expected", [
    ("", rd._DEFAULT_TIMEOUT),
    ("abc", rd._DEFAULT_TIMEOUT),
    ("-1", rd._DEFAULT_TIMEOUT),
    ("0", rd._DEFAULT_TIMEOUT),
    ("2.5", 2.5),
], ids=["unset", "garbage", "negative", "zero", "valid"])
def test_dispatch_timeout_env_parsing(monkeypatch, raw, expected) -> None:
    monkeypatch.setenv(rd.TIMEOUT_ENV, raw)
    assert rd._timeout() == expected


def test_no_execution_endpoint_raises_unavailable(monkeypatch) -> None:
    monkeypatch.delenv(rd.ENDPOINT_ENV, raising=False)
    with pytest.raises(rd.RemoteDispatchUnavailable):
        rd.remote_dispatch(lease=_lease_stub(), tenant="acme",
                           principal="agent-1", tool_call=_tool_call())


def _http_error(code: int, body: bytes = b"nope") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


def test_a_4xx_from_the_executor_is_its_verdict_not_an_outage(
    monkeypatch,
) -> None:
    """The executor answered and refused; the audit record must say
    refusal (with the executor's words), not unavailability."""
    monkeypatch.setenv(rd.ENDPOINT_ENV, "http://executor")
    monkeypatch.setattr(
        rd, "_post", lambda url, payload, timeout: (_ for _ in ()).throw(
            _http_error(422, b"lease expired")))
    out = rd.remote_dispatch(lease=_lease_stub(), tenant="acme",
                             principal="agent-1", tool_call=_tool_call())
    assert out["executed"] is False
    assert out["refusal_reason"] == "execution_domain_refused"
    assert "422" in out["error"] and "lease expired" in out["error"]


def test_a_5xx_is_an_outage_never_a_clean_refusal(monkeypatch) -> None:
    monkeypatch.setenv(rd.ENDPOINT_ENV, "http://executor")
    monkeypatch.setattr(
        rd, "_post", lambda url, payload, timeout: (_ for _ in ()).throw(
            _http_error(503)))
    with pytest.raises(rd.RemoteDispatchUnavailable, match="503"):
        rd.remote_dispatch(lease=_lease_stub(), tenant="acme",
                           principal="agent-1", tool_call=_tool_call())


def test_an_unreachable_executor_is_unknown_state(monkeypatch) -> None:
    monkeypatch.setenv(rd.ENDPOINT_ENV, "http://executor")
    monkeypatch.setattr(
        rd, "_post", lambda url, payload, timeout: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")))
    with pytest.raises(rd.RemoteDispatchUnavailable, match="unreachable"):
        rd.remote_dispatch(lease=_lease_stub(), tenant="acme",
                           principal="agent-1", tool_call=_tool_call())


# ── lease signing key resolution ───────────────────────────────────────────


def test_the_fallback_signing_key_env_is_honoured(monkeypatch) -> None:
    monkeypatch.delenv(lease_mod._ENV_KEY, raising=False)
    monkeypatch.setenv(lease_mod._FALLBACK_ENV_KEY, "fallback-key")
    assert lease_mod._get_signing_key() == b"fallback-key"


def test_no_signing_key_resolves_to_none_not_empty_bytes(monkeypatch) -> None:
    monkeypatch.delenv(lease_mod._ENV_KEY, raising=False)
    monkeypatch.delenv(lease_mod._FALLBACK_ENV_KEY, raising=False)
    assert lease_mod._get_signing_key() is None


# ── observation hashing: every input shape binds stably ────────────────────


def test_observation_hash_is_shape_stable() -> None:
    from dataclasses import dataclass

    @dataclass
    class Obs:
        a: int
        b: str

    as_dataclass = _hash_observation(Obs(a=1, b="x"))
    as_dict = _hash_observation({"a": 1, "b": "x"})
    assert as_dataclass == as_dict  # a dataclass binds as its field dict
    as_scalar = _hash_observation("plain")
    assert as_scalar == _hash_observation("plain")
    assert as_scalar != as_dict


# ── proposal state ladder ──────────────────────────────────────────────────


def _ev(name: str, **payload):
    return {"event": name, "payload": payload}


@pytest.mark.parametrize("events, state", [
    ([], "PROPOSED"),
    ([_ev("assessed")], "ASSESSED"),
    ([_ev("assessed"), _ev("review_enqueued")], "REVIEW_PENDING"),
    ([_ev("assessed", review_item_id="r-1")], "REVIEW_PENDING"),
    ([_ev("approved")], "AUTHORIZED"),
    ([_ev("rejected")], "REFUSED"),
    ([_ev("approved"), _ev("execution_authorized")], "DISPATCHING"),
    ([_ev("execution_authorized"), _ev("execution_refused")], "REFUSED"),
], ids=["empty", "assessed", "enqueued", "review-item", "approved",
        "rejected", "authorized", "execution-refused"])
def test_the_lifecycle_ladder_reads_events_most_specific_first(
    events, state
) -> None:
    assert current_state(events, None) == state


# ── effect verification replay ─────────────────────────────────────────────


def test_a_second_settled_effect_verdict_is_a_replay_not_an_append() -> None:
    chain = SimpleNamespace(append_once=lambda tenant, key, payload: None)
    verification = SimpleNamespace(to_dict=lambda: {"verdict": "confirmed"})
    with pytest.raises(EffectVerificationReplay):
        record_effect_verification(chain, "acme", verification,
                                   settled_dispatch_id="d-1")


# ── outbox reconciler guards ───────────────────────────────────────────────


def _intent(box: ExecutionOutbox):
    return box.record_intent(
        proposal_id="11111111-2222-3333-4444-555555555555",
        tenant_id="acme", item_id="item-1", tool_name="store_artifact",
        tool_call_hash="a" * 64, grant_jti="jti-1", attempt_no=1,
    )


def test_the_never_dispatched_transition_requires_pending(caplog) -> None:
    row = _intent(ExecutionOutbox())
    claimed = replace(row, state=OutboxState.DISPATCHING)
    with pytest.raises(ValueError, match="never-dispatched transition"):
        outbox_mod._check_settleable(
            claimed, OutboxState.FAILED, from_pending=True)


def test_an_unclaimed_intent_reconciles_to_failed_and_nothing_else() -> None:
    row = _intent(ExecutionOutbox())
    with pytest.raises(ValueError, match="reconciles to FAILED"):
        outbox_mod._check_settleable(
            row, OutboxState.UNKNOWN, from_pending=True)


def test_reconcile_unclaimed_spares_young_intents() -> None:
    box = ExecutionOutbox()
    row = _intent(box)
    settled = box.reconcile_unclaimed(
        "acme", older_than=timedelta(hours=1),
        now=row.created_at + timedelta(minutes=5))
    assert settled == []
    old = box.reconcile_unclaimed(
        "acme", older_than=timedelta(hours=1),
        now=row.created_at + timedelta(hours=2))
    assert [r.state for r in old] == [OutboxState.FAILED]
    assert "never dispatched" in old[0].detail
