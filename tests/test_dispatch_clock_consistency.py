# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""dispatch_under_lease must use one clock for issue and verify.

It was handed `now`, issued the lease against it, and then let the dispatcher
verify against the wall clock. In production the two are moments apart. In a
full test run the module-level `NOW` of tests/test_remote_dispatch_boundary.py
was minutes old by the time its tests ran, the 120-second lease TTL had
elapsed, and two security guards failed as lease_expired at random -- the
tests that most need to be trusted when they go red (issue #379).

Both directions are pinned: the supplied clock is honoured, and it is not a
way to revive a lease that has genuinely expired.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from remora.enforcement.lease import DEFAULT_LEASE_TTL_SECONDS, GovernedToolDispatcher
from remora.enforcement.nonce_store import InMemoryNonceStore
from remora.execution.dispatch import dispatch_under_lease, issue_execution_lease

BUNDLE = "bundle-1"
SEMANTIC = {"tool_contract_bundle_hash": "tc-1", "intent_authority_hash": "ia-1"}


def _call():
    return SimpleNamespace(tool_name="wo_close", arguments={"id": "WO-1"},
                           target_environment="staging")


@pytest.fixture(autouse=True)
def _hmac(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "test-key")


def _dispatcher() -> GovernedToolDispatcher:
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE,
                               nonce_store=InMemoryNonceStore())
    d.register("wo_close", lambda args: "ok")
    return d


def test_a_clock_older_than_the_ttl_still_dispatches_when_used_consistently():
    """The exact shape of the flake: `now` is older than the TTL.

    Issue and verify both see the supplied clock, so the lease is fresh
    relative to the only time the function was told about.
    """
    stale = datetime.now(UTC) - timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60)
    result = dispatch_under_lease(
        tenant="acme", principal="agent-1", tool_call=_call(), semantic=SEMANTIC,
        now=stale, dispatcher=_dispatcher(), policy_bundle_hash=BUNDLE,
        proposal_id="prop-1",
    )
    assert result["executed"] is True, result.get("refusal_reason")


def test_the_supplied_clock_cannot_revive_a_genuinely_expired_lease():
    """The clock is consistency, not a bypass.

    A presented lease issued at T is verified against the executor's `now`.
    If that `now` is past the lease's expiry, the lease is expired, whatever
    the wall clock says.
    """
    issued = datetime.now(UTC)
    lease = issue_execution_lease(
        tenant="acme", principal="agent-1", tool_call=_call(), semantic=SEMANTIC,
        now=issued, policy_bundle_hash=BUNDLE,
    )
    later = issued + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1)
    result = dispatch_under_lease(
        tenant="acme", principal="agent-1", tool_call=_call(), semantic=SEMANTIC,
        now=later, dispatcher=_dispatcher(), policy_bundle_hash=BUNDLE,
        proposal_id="prop-1", presented_lease=lease,
    )
    assert result["executed"] is False
    assert result["refusal_reason"] == "lease_expired"


def test_a_presented_lease_verified_within_its_window_dispatches():
    """And the positive side of the presented-lease path, at the same clock."""
    issued = datetime.now(UTC)
    lease = issue_execution_lease(
        tenant="acme", principal="agent-1", tool_call=_call(), semantic=SEMANTIC,
        now=issued, policy_bundle_hash=BUNDLE,
    )
    result = dispatch_under_lease(
        tenant="acme", principal="agent-1", tool_call=_call(), semantic=SEMANTIC,
        now=issued + timedelta(seconds=5), dispatcher=_dispatcher(),
        policy_bundle_hash=BUNDLE, proposal_id="prop-1", presented_lease=lease,
    )
    assert result["executed"] is True, result.get("refusal_reason")
