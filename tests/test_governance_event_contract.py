# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Governance-event payloads as a tested contract.

The mutation report (docs/assurance/mutation_testing_v1.md, issue #280)
classified the largest surviving residue as event-payload literals: mutants
rewriting ``reason="nonce_already_consumed"`` or dropping a field from a
``governance_event`` call survived every suite because nothing asserted what
the operational record actually says. This file is the decision the report
left open, taken in the promoting direction: the events ARE contract — an
operator triages replays vs outages from these exact names and fields, and
docs/observability work (issue #45) joins lifecycles on them.

Events are captured via caplog on the ``remora.governance`` logger; the
structured payload rides on ``record.remora`` (the ``extra`` dict), so the
assertions pin machine-readable fields, not rendered text.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import (GovernedToolDispatcher,
                                      ToolExecutionStateUnknown)
from remora.enforcement.token import PolicyDecisionToken
from remora.execution.dispatch import issue_execution_lease
from remora.observability.events import SecretFieldError, governance_event

LOGGER = "remora.governance"
NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
BUNDLE = "bundle-events-1"
SEMANTIC = {"tool_contract_bundle_hash": "tc-1", "intent_authority_hash": "ia-1"}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "event-contract-key")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "event-contract-key")
    monkeypatch.delenv("REMORA_PDP_KEY_ID", raising=False)
    monkeypatch.delenv("REMORA_PDP_REVOKED_KEY_IDS", raising=False)


def _lease(principal: str = "agent-1"):
    call = SimpleNamespace(tool_name="wo_close", arguments={"id": "WO-1"},
                           target_environment="staging")
    return issue_execution_lease(
        tenant="acme", principal=principal, tool_call=call,
        semantic=SEMANTIC, now=NOW, policy_bundle_hash=BUNDLE,
        proposal_id="prop-ev-1", grant_jti="jti-ev-1",
    )


def _dispatcher(fn=None) -> GovernedToolDispatcher:
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    d.register("wo_close", fn or (lambda args: {"ok": True}))
    return d


def _dispatch(d, lease, **overrides):
    kwargs = dict(tenant_id="acme", target_environment="staging",
                  actor_identity="agent-1", now=NOW.isoformat())
    kwargs.update(overrides)
    return d.dispatch(lease, "wo_close", {"id": "WO-1"}, **kwargs)


def _events(caplog, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith(name + " ")]


def _payload(record: logging.LogRecord) -> dict:
    return record.remora  # type: ignore[attr-defined]


# ── the emitter itself ─────────────────────────────────────────────────────


def test_a_credential_shaped_field_name_raises_instead_of_logging() -> None:
    with pytest.raises(SecretFieldError):
        governance_event("x.y", signing_key="hunter2")


def test_derived_credential_facts_are_loggable(caplog) -> None:
    """token_jti / token_verified are facts ABOUT a credential -- logging
    them is the whole point of correlation, and the deny-list must not
    swallow them."""
    with caplog.at_level(logging.INFO, logger=LOGGER):
        governance_event("x.y", token_jti="j-1", token_verified=True)
    (rec,) = _events(caplog, "x.y")
    assert _payload(rec) == {"token_jti": "j-1", "token_verified": True}


# ── the PEP decision event ─────────────────────────────────────────────────


def test_grant_checked_payload_on_an_allowed_consuming_check(caplog) -> None:
    token = PolicyDecisionToken.issue(
        action="accept", observation_hash="c" * 64, request_id="req-ev-1",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(seconds=300)).isoformat(),
    )
    gate = EnforcementGate(strict=True)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        r = gate.check(token, consume=True, now=NOW.isoformat())
    assert r.allowed is True
    (rec,) = _events(caplog, "grant.checked")
    assert rec.levelno == logging.INFO
    assert _payload(rec) == {
        "allowed": True, "action": "accept", "reason": r.reason,
        "token_jti": token.jti, "consumed": True,
        "strict_mode": True, "token_verified": True,
    }


def test_grant_checked_payload_on_a_refusal_is_warning_and_unconsumed(
    caplog,
) -> None:
    token = PolicyDecisionToken.issue(
        action="accept", observation_hash="c" * 64, request_id="req-ev-2",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(seconds=300)).isoformat(),
    )
    object.__setattr__(token, "signature", "0" * 64)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        r = EnforcementGate(strict=True).check(
            token, consume=True, now=NOW.isoformat())
    assert r.allowed is False
    (rec,) = _events(caplog, "grant.checked")
    assert rec.levelno == logging.WARNING
    p = _payload(rec)
    assert p["allowed"] is False
    assert p["consumed"] is False  # a refused check must never report a spend
    assert p["reason"] == "token_verification_failed:signature_invalid"
    assert p["token_verified"] is False
    assert p["strict_mode"] is True


# ── lease issuance ─────────────────────────────────────────────────────────


def test_lease_issued_payload_carries_the_full_binding_identity(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        lease = _lease()
    (rec,) = _events(caplog, "lease.issued")
    assert _payload(rec) == {
        "decision": lease.decision, "tenant_id": "acme",
        "tool_name": "wo_close", "tool_args_hash": lease.tool_args_hash,
        "target_environment": "staging", "policy_bundle_hash": BUNDLE,
        "expires_at": lease.expires_at, "proposal_id": "prop-ev-1",
        "grant_jti": "jti-ev-1", "signed": True,
    }


# ── dispatch refusals: the reason literal IS the routing key ───────────────


def test_missing_lease_event_has_empty_proposal_and_warning_level(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _dispatcher().dispatch(None, "wo_close", {"id": "WO-1"},
                               tenant_id="acme", now=NOW.isoformat())
    (rec,) = _events(caplog, "dispatch.refused")
    assert rec.levelno == logging.WARNING
    assert _payload(rec) == {
        "reason": "missing_lease", "tenant_id": "acme",
        "tool_name": "wo_close", "proposal_id": "",
    }


def test_unknown_tool_event_reports_the_lease_proposal(caplog) -> None:
    lease = _lease()
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    d.register("other_tool", lambda args: None)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        d.dispatch(lease, "wo_close", {"id": "WO-1"}, tenant_id="acme",
                   target_environment="staging", actor_identity="agent-1",
                   now=NOW.isoformat())
    (rec,) = _events(caplog, "dispatch.refused")
    assert _payload(rec) == {
        "reason": "unknown_tool", "tenant_id": "acme",
        "tool_name": "wo_close", "proposal_id": "prop-ev-1",
    }


def test_a_raising_resolver_event_is_error_level_with_detail(caplog) -> None:
    d = _dispatcher()

    def broken(_tool):
        raise RuntimeError("bundle store down")

    d.bind_toolspec_identity(broken)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _dispatch(d, _lease())
    (rec,) = _events(caplog, "dispatch.refused")
    assert rec.levelno == logging.ERROR
    assert _payload(rec) == {
        "reason": "toolspec_unresolvable", "tenant_id": "acme",
        "tool_name": "wo_close", "proposal_id": "prop-ev-1",
        "grant_jti": "jti-ev-1", "detail": "bundle store down",
    }


def test_a_binding_refusal_event_carries_the_verify_reason(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _dispatch(_dispatcher(), _lease(), tenant_id="globex")
    (rec,) = _events(caplog, "dispatch.refused")
    assert _payload(rec) == {
        "reason": "tenant_mismatch", "tenant_id": "globex",
        "tool_name": "wo_close", "proposal_id": "prop-ev-1",
        "grant_jti": "jti-ev-1",
    }


def test_a_replay_event_says_nonce_already_consumed(caplog) -> None:
    d = _dispatcher()
    lease = _lease()
    assert _dispatch(d, lease).executed is True
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _dispatch(d, lease)
    (rec,) = _events(caplog, "dispatch.refused")
    assert _payload(rec) == {
        "reason": "nonce_already_consumed", "tenant_id": "acme",
        "tool_name": "wo_close", "proposal_id": "prop-ev-1",
        "grant_jti": "jti-ev-1",
    }


def test_a_retry_after_a_failed_execution_names_the_failure(caplog) -> None:
    """The distinction an operator alerts on: 'spent' vs 'spent by an attempt
    that FAILED with unknown state'."""
    d = _dispatcher(fn=lambda args: (_ for _ in ()).throw(OSError("db down")))
    lease = _lease()
    with pytest.raises(ToolExecutionStateUnknown):
        _dispatch(d, lease)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _dispatch(d, lease)
    (rec,) = _events(caplog, "dispatch.refused")
    assert _payload(rec)["reason"] == "nonce_consumed_by_failed_execution"


# ── the two terminal dispatch events ───────────────────────────────────────


def test_dispatch_executed_payload_joins_the_lifecycle(caplog) -> None:
    lease = _lease()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        r = _dispatch(_dispatcher(), lease)
    assert r.executed is True
    (rec,) = _events(caplog, "dispatch.executed")
    assert rec.levelno == logging.INFO
    assert _payload(rec) == {
        "tenant_id": "acme", "tool_name": "wo_close",
        "proposal_id": "prop-ev-1", "grant_jti": "jti-ev-1",
        "tool_args_hash": lease.tool_args_hash,
    }


def test_state_unknown_event_is_error_with_burned_nonce_and_error_type(
    caplog,
) -> None:
    d = _dispatcher(fn=lambda args: (_ for _ in ()).throw(OSError("db down")))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        with pytest.raises(ToolExecutionStateUnknown):
            _dispatch(d, _lease())
    (rec,) = _events(caplog, "dispatch.state_unknown")
    assert rec.levelno == logging.ERROR
    assert _payload(rec) == {
        "tenant_id": "acme", "tool_name": "wo_close",
        "proposal_id": "prop-ev-1", "grant_jti": "jti-ev-1",
        "nonce_burned": True, "error_type": "OSError",
    }
