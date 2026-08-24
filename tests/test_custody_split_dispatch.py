# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Two trust domains, in one process, so the seam itself can be attacked.

ADR-A's split is only real if the executing side can do its whole job holding
nothing but a public key. That is what these tests establish, before any
deployment claims it:

  AUTHORITY domain   holds the Ed25519 PRIVATE key. Decides, then signs what
                     it decided. Holds no downstream tool credential.
  EXECUTION domain   holds the PUBLIC key only. Verifies, consumes the nonce,
                     and dispatches with the downstream credential.

The domains are simulated by swapping environment material around a single
process. That is weaker than two hosts and stronger than a diagram: every
assertion below is about what a component CAN DO with the material it holds,
which is the property the deployment topology has to preserve.

The rule the seam must not break: a lease is not trusted because it arrived.
`dispatcher.dispatch` re-verifies the entire binding against the concrete call,
so an authority-signed lease for a DIFFERENT call is refused by the executor
just as a forged one is.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _security_extra import require_security_extra  # noqa: E402

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.enforcement.lease import GovernedToolDispatcher  # noqa: E402
from remora.enforcement.nonce_store import InMemoryNonceStore  # noqa: E402
from remora.execution.dispatch import (  # noqa: E402
    dispatch_under_lease,
    issue_execution_lease,
)

# Skips locally without the 'security' extra; fails hard in CI, where a skip
# would silently withhold this file's evidence. See conftest for why.
require_security_extra()

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

# Real current time, not a fixed instant: dispatch() checks the lease against
# the actual clock, and a fixed timestamp made every dispatch here fail
# not-yet-valid -- the not-before guard doing its job on a test that had put
# its own lease in the future.
NOW = datetime.now(UTC)
BUNDLE = "bundle-1"
SEMANTIC = {"tool_contract_bundle_hash": "tc-1", "intent_authority_hash": "ia-1"}


def _call(tool="wo_close", args=None, target="staging"):
    return SimpleNamespace(
        tool_name=tool, arguments=args if args is not None else {"id": "WO-1"},
        target_environment=target)


@pytest.fixture()
def keys(monkeypatch):
    k = ed25519.Ed25519PrivateKey.generate()
    seed = k.private_bytes_raw().hex()
    public = k.public_key().public_bytes_raw().hex()
    for name in (signing.ENV_HMAC, signing.ENV_HMAC_FALLBACK,
                 signing.ENV_ACCEPT_HMAC):
        monkeypatch.delenv(name, raising=False)
    return seed, public


def _become_authority(monkeypatch, keys):
    seed, public = keys
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)


def _become_executor(monkeypatch, keys):
    """Reduce this process to exactly what the execution domain may hold."""
    _seed, public = keys
    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)
    assert signing.public_key_only() is True


def _executor(calls: list) -> GovernedToolDispatcher:
    """The execution domain: holds the tool callable and its credentials."""
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE,
                               nonce_store=InMemoryNonceStore())
    d.register("wo_close", lambda args: calls.append(args) or "closed")
    return d


def _authority_lease(monkeypatch, keys, call=None, principal="agent-1",
                     tenant="acme"):
    _become_authority(monkeypatch, keys)
    return issue_execution_lease(
        tenant=tenant, principal=principal, tool_call=call or _call(),
        semantic=SEMANTIC, now=NOW, policy_bundle_hash=BUNDLE,
        proposal_id="prop-1", grant_jti="jti-1")


def _execute(dispatcher, lease, call=None, principal="agent-1", tenant="acme"):
    return dispatch_under_lease(
        tenant=tenant, principal=principal, tool_call=call or _call(),
        semantic=SEMANTIC, now=NOW, dispatcher=dispatcher,
        policy_bundle_hash=BUNDLE, proposal_id="prop-1", grant_jti="jti-1",
        presented_lease=lease)


# ── the split works ─────────────────────────────────────────────────────────

def test_a_verifier_only_executor_dispatches_an_authority_signed_lease(
        monkeypatch, keys):
    """The whole point: the executor does its job holding no signing material."""
    lease = _authority_lease(monkeypatch, keys)
    assert lease.sig_alg == signing.ALG_ED25519

    calls: list = []
    dispatcher = _executor(calls)
    _become_executor(monkeypatch, keys)

    result = _execute(dispatcher, lease)
    assert result["executed"] is True
    assert calls == [{"id": "WO-1"}]


def test_the_executor_cannot_mint_its_own_lease(monkeypatch, keys):
    """Same process, same moment, without a lease handed to it."""
    calls: list = []
    dispatcher = _executor(calls)
    _become_executor(monkeypatch, keys)

    result = dispatch_under_lease(
        tenant="acme", principal="agent-1", tool_call=_call(),
        semantic=SEMANTIC, now=NOW, dispatcher=dispatcher,
        policy_bundle_hash=BUNDLE)

    assert result["executed"] is False
    assert result["refusal_reason"].startswith("lease_unavailable")
    assert calls == [], "nothing may run without authority"


# ── an arriving lease is not a trusted lease ────────────────────────────────

def test_an_authority_lease_for_a_different_call_is_still_refused(
        monkeypatch, keys):
    """The seam must not turn 'signed by the authority' into 'authorised'.

    This is the failure the split could plausibly introduce: an executor that
    checks the signature and stops. The authority signed a real lease -- for a
    different argument -- and the executor must still refuse it.
    """
    lease = _authority_lease(monkeypatch, keys, call=_call(args={"id": "WO-1"}))

    calls: list = []
    dispatcher = _executor(calls)
    _become_executor(monkeypatch, keys)

    result = _execute(dispatcher, lease, call=_call(args={"id": "WO-999"}))
    assert result["executed"] is False
    assert calls == []


def test_an_authority_lease_for_a_different_tenant_is_refused(monkeypatch, keys):
    lease = _authority_lease(monkeypatch, keys, tenant="acme")

    calls: list = []
    dispatcher = _executor(calls)
    _become_executor(monkeypatch, keys)

    result = dispatch_under_lease(
        tenant="globex", principal="agent-1", tool_call=_call(),
        semantic=SEMANTIC, now=NOW, dispatcher=dispatcher,
        policy_bundle_hash=BUNDLE, presented_lease=lease)
    assert result["executed"] is False
    assert calls == []


def test_a_lease_from_a_foreign_key_is_refused(monkeypatch, keys):
    """A second, valid Ed25519 authority that this executor does not trust."""
    rogue = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE,
                       rogue.private_bytes_raw().hex())
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC,
                       rogue.public_key().public_bytes_raw().hex())
    rogue_lease = issue_execution_lease(
        tenant="acme", principal="agent-1", tool_call=_call(),
        semantic=SEMANTIC, now=NOW, policy_bundle_hash=BUNDLE)

    calls: list = []
    dispatcher = _executor(calls)
    _become_executor(monkeypatch, keys)          # trusts the REAL authority

    result = _execute(dispatcher, rogue_lease)
    assert result["executed"] is False
    assert calls == []


def test_the_nonce_is_still_consumed_exactly_once_across_the_seam(
        monkeypatch, keys):
    """Moving issuance out must not weaken the single-use property."""
    lease = _authority_lease(monkeypatch, keys)

    calls: list = []
    dispatcher = _executor(calls)
    _become_executor(monkeypatch, keys)

    assert _execute(dispatcher, lease)["executed"] is True
    replay = _execute(dispatcher, lease)
    assert replay["executed"] is False
    assert replay["refusal_reason"] == "nonce_already_consumed"
    assert len(calls) == 1
